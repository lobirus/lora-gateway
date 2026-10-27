"""Gateway-served parts of the public /v1 API (Caddy routes these paths to the backend instead of LiteLLM):

* GET /v1/models    - LiteLLM's list for the caller's key, plus the gateway's own pipeline models/aliases (e.g. "talk"),
                      so clients such as malac discover them.
* WS  /v1/realtime  - OpenAI Realtime API. Provider realtime models are relayed to LiteLLM; pipeline models (open-weight
                      STT -> chat -> TTS) are served here. Auth: "Authorization: Bearer <virtual key>", "api-key: <key>",
                      or the browser subprotocol "openai-insecure-api-key.<key>".
"""
import time

import httpx
from fastapi import APIRouter, Request, WebSocket
from starlette.datastructures import UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select

from .. import realtime
from ..config import settings
from ..db import Alias, Model, SessionLocal
from ..litellm_sync import deployable, is_pipeline

router = APIRouter(tags=["v1"])


def _names() -> tuple[list[str], set[str]]:
    """(pipeline names to add, every explicit routable name). LiteLLM expands `<provider>/*` wildcard routes into
    every model its price map knows for that provider (many of them not served by the account), so /v1/models only
    keeps names the gateway registered explicitly: catalog models (curated + synced), aliases and pipeline models."""
    db = SessionLocal()
    try:
        models = db.scalars(select(Model)).all()
        aliases = db.scalars(select(Alias)).all()
        pipe = [m.model_name for m in models if is_pipeline(m) and deployable(m)]
        pipe += [a.name for a in aliases if a.target and is_pipeline(a.target) and deployable(a.target)]
        explicit = {m.model_name for m in models if deployable(m)} | {a.name for a in aliases if deployable(a.target)}
        return pipe, explicit
    finally:
        db.close()


@router.get("/v1/models")
async def list_models(request: Request):
    headers = {k: v for k, v in request.headers.items() if k.lower() in ("authorization", "api-key", "x-api-key")}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(settings.litellm_url + "/v1/models", headers=headers, params=dict(request.query_params))
    if r.status_code != 200:
        return Response(r.content, status_code=r.status_code, media_type=r.headers.get("content-type", "application/json"))
    j = r.json()
    pipe, explicit = await run_in_threadpool(_names)
    if request.query_params.get("include_wildcard") not in ("1", "true"):
        j["data"] = [m for m in j.get("data", []) if m.get("id") in explicit]
    have = {m.get("id") for m in j.get("data", [])}
    now = int(time.time())
    for n in pipe:
        if n not in have:
            j.setdefault("data", []).append({"id": n, "object": "model", "created": now, "owned_by": "lora-gateway"})
    return JSONResponse(j)


TRANSLATE_PROMPT = ("Translate the user's text into natural English. Output only the translation, nothing else. "
                    "If it is already English, output it unchanged.")


@router.post("/v1/audio/translations")
async def translations(request: Request):
    """OpenAI /v1/audio/translations (speech -> English text). LiteLLM has no translations route, so the gateway runs
    it as two logged requests with the caller's key: a transcription with the requested model, then (if the speech was
    not English) a short chat call with the "fast" alias (falls back to "default") that translates the text."""
    auth = {k: v for k, v in request.headers.items() if k.lower() in ("authorization", "api-key", "x-api-key")}
    form = await request.form()
    up = form.get("file")
    model = form.get("model")
    if not isinstance(up, UploadFile) or not model:
        return JSONResponse({"error": {"message": "file and model are required", "type": "invalid_request_error"}}, status_code=400)
    data = await up.read()
    tags = {"x-litellm-tags": "voice:translation"}
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=300) as c:
        r = await c.post("/v1/audio/transcriptions", headers={**auth, **tags},
                         data={"model": model, "response_format": "verbose_json" if str(model).find("4o") < 0 else "json"},
                         files={"file": (up.filename or "audio", data, up.content_type or "application/octet-stream")})
        if r.status_code >= 400:
            return Response(r.content, status_code=r.status_code, media_type="application/json")
        j = r.json()
        text, lang = (j.get("text") or "").strip(), (j.get("language") or "").lower()
        cost = float(r.headers.get("x-litellm-response-cost") or 0)
        if text and lang not in ("en", "english"):
            for llm in ("fast", "default"):
                t = await c.post("/v1/chat/completions", headers={**auth, **tags}, json={
                    "model": llm, "max_tokens": 2048, "messages": [{"role": "system", "content": TRANSLATE_PROMPT}, {"role": "user", "content": text}],
                    "reasoning": {"enabled": False}})
                if t.status_code == 200:
                    text = (t.json()["choices"][0]["message"].get("content") or text).strip()
                    cost += float(t.headers.get("x-litellm-response-cost") or 0)
                    break
    fmt = form.get("response_format") or "json"
    if fmt == "text":
        return Response(text, media_type="text/plain")
    return JSONResponse({"text": text, "source_language": lang or None}, headers={"x-litellm-response-cost": f"{cost:.8f}"})


def _ws_key(ws: WebSocket) -> tuple[str | None, str | None]:
    """Returns (key, subprotocol to accept)."""
    auth = ws.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip(), None
    if ws.headers.get("api-key"):
        return ws.headers["api-key"].strip(), None
    protos = [p.strip() for p in (ws.headers.get("sec-websocket-protocol") or "").split(",") if p.strip()]
    key = next((p[len("openai-insecure-api-key."):] for p in protos if p.startswith("openai-insecure-api-key.")), None)
    return key, ("realtime" if "realtime" in protos else None)


@router.websocket("/v1/realtime")
async def realtime_ws(ws: WebSocket, model: str = ""):
    key, proto = _ws_key(ws)
    await ws.accept(subprotocol=proto)
    if not key:
        await ws.send_json({"type": "error", "error": {"type": "invalid_request_error", "code": "missing_api_key",
                                                        "message": "Missing API key (Authorization: Bearer <key>)"}})
        await ws.close(code=4401)
        return
    if not model:
        await ws.send_json({"type": "error", "error": {"type": "invalid_request_error", "code": "missing_model",
                                                        "message": "Pass ?model=<realtime model or alias>"}})
        await ws.close(code=1008)
        return
    protos = ws.headers.get("sec-websocket-protocol") or ""
    beta = (ws.headers.get("openai-beta") or "").startswith("realtime") or "openai-beta.realtime-v1" in protos
    await realtime.serve(ws, model, key, "source:api,voice:realtime", beta)

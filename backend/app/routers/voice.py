"""Voice in the Playground: speech-to-text, text-to-speech and a realtime WebSocket relay.

Like /api/playground/chat, every request is forwarded to LiteLLM with a *virtual key* (the internal playground key or
the key picked in the UI) and tagged source:playground, so it is authorised, budgeted and logged like client traffic.
The browser only ever holds its console session; it never sees a provider key, a virtual key or the master key.

Realtime: the browser cannot set an Authorization header on a WebSocket, so it first POSTs /realtime/ticket (normal
JWT auth) and gets a 60-second signed ticket bound to the user, model and key; it then opens
/api/playground/realtime?ticket=... and the backend relays every frame to LiteLLM's /v1/realtime.
"""
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import quote

import httpx
import jwt
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .. import realtime
from ..config import settings
from ..db import ApiKey, SessionLocal, User
from ..security import current_user, decrypt
from .playground import SOURCE_TAG, USER_AGENT, _err_message, ensure_playground_key, resolve_model

log = logging.getLogger("gateway.voice")
router = APIRouter(prefix="/api/playground", tags=["voice"])

MAX_UPLOAD = 25 * 1024 * 1024  # OpenAI's transcription limit; Caddy and LiteLLM accept it too
TICKET_TTL = 60


def _key(db, key_id: int | None) -> ApiKey:
    if key_id:
        k = db.get(ApiKey, key_id)
        if not k or k.revoked:
            raise HTTPException(404, "API key not found or revoked")
        return k
    return ensure_playground_key(db)


def _prepare(model: str, key_id: int | None, username: str, kind: str) -> dict:
    db = SessionLocal()
    try:
        k = _key(db, key_id)
        m = resolve_model(db, model)
        tags = [SOURCE_TAG, f"playground-user:{username}", f"voice:{kind}"]
        return {"raw": decrypt(k.key_enc), "key_name": k.name, "tags": ",".join(tags),
                "model_kind": (m.kind if m else None) or "chat", "resolved": m.model_name if m else None,
                "price_per_minute": m.price_per_minute if m else None,
                "price_per_m_chars": m.price_per_m_chars if m else None,
                "default_voice": m.default_voice if m else None}
    finally:
        db.close()


def _headers(prep: dict, json_body: bool = False) -> dict:
    h = {"Authorization": f"Bearer {prep['raw']}", "User-Agent": USER_AGENT, "x-litellm-tags": prep["tags"]}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _cost(headers) -> float | None:
    try:
        v = headers.get("x-litellm-response-cost")
        return float(v) if v is not None else None
    except ValueError:
        return None


# ---------------------------------------------------------------- speech to text
@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), model: str = Form(..., max_length=200),
                     language: str | None = Form(None, max_length=16), prompt: str | None = Form(None, max_length=2000),
                     task: Literal["transcribe", "translate"] = Form("transcribe"), key_id: int | None = Form(None),
                     user: User = Depends(current_user)):
    data = await file.read()
    if not data:
        raise HTTPException(400, "The audio file is empty")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Audio files are limited to 25 MB")
    prep = await run_in_threadpool(_prepare, model, key_id, user.username, "transcription")
    form = {"model": model, "response_format": "json"}
    if language and task == "transcribe":
        form["language"] = language
    if prompt:
        form["prompt"] = prompt
    path = "/v1/audio/translations" if task == "translate" else "/v1/audio/transcriptions"
    # translations are served by the gateway itself (gateway_v1.translations), transcriptions by LiteLLM
    base = "http://127.0.0.1:8000" if task == "translate" else settings.litellm_url
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as c:
            r = await c.post(base + path, headers=_headers(prep), data=form,
                             files={"file": (file.filename or "audio.webm", data, file.content_type or "application/octet-stream")})
    except httpx.HTTPError as e:
        return JSONResponse({"ok": False, "error": f"Gateway connection error: {e}"}, status_code=502)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    meta = {"latency_ms": ms, "status": r.status_code, "model": model, "resolved_model": prep["resolved"],
            "request_id": r.headers.get("x-litellm-call-id"), "key_name": prep["key_name"], "bytes": len(data),
            "cost": _cost(r.headers), "task": task, "endpoint": path}
    if r.status_code >= 400:
        return JSONResponse({"ok": False, "error": _err_message(r.content, r.status_code), "metrics": meta})
    try:
        j = r.json()
    except ValueError:
        j = {"text": r.text}
    dur = j.get("duration")
    if dur is None and meta["cost"] and prep["price_per_minute"]:
        dur = meta["cost"] / (prep["price_per_minute"] / 60)  # derived from the per-minute price
    meta["audio_seconds"] = round(float(dur), 2) if dur else None
    return {"ok": True, "text": j.get("text", ""), "language": j.get("language"), "metrics": meta}


# ---------------------------------------------------------------- text to speech
class SpeechIn(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    input: str = Field(min_length=1, max_length=4096)
    voice: str | None = Field(default=None, max_length=120)
    response_format: Literal["mp3", "wav", "opus", "aac", "flac", "pcm"] = "mp3"
    speed: float | None = Field(default=None, ge=0.25, le=4)
    instructions: str | None = Field(default=None, max_length=2000)
    key_id: int | None = None


AUDIO_TYPES = {"mp3": "audio/mpeg", "wav": "audio/wav", "opus": "audio/ogg", "aac": "audio/aac", "flac": "audio/flac",
               "pcm": "audio/L16"}


@router.post("/speech")
async def speech(body: SpeechIn, user: User = Depends(current_user)):
    prep = await run_in_threadpool(_prepare, body.model, body.key_id, user.username, "speech")
    voice = body.voice or prep["default_voice"]
    if not voice:
        raise HTTPException(400, "Pick a voice for this model")
    payload = {"model": body.model, "input": body.input, "voice": voice, "response_format": body.response_format}
    if body.speed:
        payload["speed"] = body.speed
    if body.instructions:
        payload["instructions"] = body.instructions
    t0 = time.perf_counter()
    client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0))
    try:
        req = client.build_request("POST", settings.litellm_url + "/v1/audio/speech", json=payload,
                                   headers=_headers(prep, json_body=True))
        r = await client.send(req, stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        return JSONResponse({"ok": False, "error": f"Gateway connection error: {e}"}, status_code=502)
    ttfb = round((time.perf_counter() - t0) * 1000, 1)
    if r.status_code >= 400:
        raw = await r.aread()
        await r.aclose()
        await client.aclose()
        return JSONResponse({"ok": False, "error": _err_message(raw, r.status_code)}, status_code=r.status_code)
    cost = _cost(r.headers)
    if cost is None and prep["price_per_m_chars"]:
        cost = len(body.input) * prep["price_per_m_chars"] / 1_000_000
    headers = {"Cache-Control": "no-store", "Content-Encoding": "identity", "X-Gw-Ttfb-Ms": str(ttfb),
               "X-Gw-Voice": quote(voice), "X-Gw-Key": prep["key_name"], "X-Gw-Chars": str(len(body.input))}
    if cost is not None:
        headers["X-Gw-Cost"] = f"{cost:.8f}"
    if r.headers.get("x-litellm-call-id"):
        headers["X-Gw-Request-Id"] = r.headers["x-litellm-call-id"]
    if prep["resolved"]:
        headers["X-Gw-Model"] = prep["resolved"]

    async def gen():
        try:
            async for chunk in r.aiter_raw():
                yield chunk
        finally:
            await r.aclose()
            await client.aclose()

    ctype = r.headers.get("content-type") or AUDIO_TYPES.get(body.response_format, "application/octet-stream")
    return StreamingResponse(gen(), media_type=ctype, headers=headers)


# ---------------------------------------------------------------- realtime (WebSocket relay)
class TicketIn(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    key_id: int | None = None


@router.post("/realtime/ticket")
def realtime_ticket(body: TicketIn, user: User = Depends(current_user)):
    exp = datetime.now(timezone.utc) + timedelta(seconds=TICKET_TTL)
    t = jwt.encode({"sub": str(user.id), "usr": user.username, "typ": "realtime", "model": body.model,
                    "kid": body.key_id, "exp": exp}, settings.jwt_secret, algorithm="HS256")
    return {"ticket": t, "path": f"/api/playground/realtime?ticket={t}", "expires_in": TICKET_TTL}


@router.websocket("/realtime")
async def realtime_relay(ws: WebSocket, ticket: str = ""):
    try:
        claims = jwt.decode(ticket, settings.jwt_secret, algorithms=["HS256"])
        if claims.get("typ") != "realtime":
            raise jwt.PyJWTError("wrong ticket type")
    except jwt.PyJWTError:
        await ws.close(code=4401, reason="Invalid or expired ticket")
        return
    await ws.accept()
    model = claims["model"]
    try:
        prep = await run_in_threadpool(_prepare, model, claims.get("kid"), claims.get("usr", "?"), "realtime")
    except HTTPException as e:
        await ws.send_json({"type": "error", "error": {"message": e.detail, "code": "gateway"}})
        await ws.close(code=1011)
        return
    await realtime.serve(ws, model, prep["raw"], prep["tags"], beta=False,
                         announce={"model": model, "resolved_model": prep["resolved"], "key_name": prep["key_name"]})

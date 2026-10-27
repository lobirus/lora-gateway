"""Playground: admin-only chat proxy used by the web console.

The browser talks to /api/playground/* with its session JWT. The backend resolves a LiteLLM *virtual key*
(the internal "playground" key by default, or any key picked in the UI) and forwards the request to LiteLLM,
so the request is authenticated, rate-limited, budgeted and logged exactly like a real client call.
The LiteLLM master key never leaves the server. Every request is tagged source:playground.
"""
import json
import logging
import re
import time
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import Alias, ApiKey, Model, Provider, SessionLocal, User, get_db
from ..litellm_sync import deployable
from ..schemas import KeyIn
from ..security import current_user, decrypt

log = logging.getLogger("gateway.playground")
router = APIRouter(prefix="/api/playground", tags=["playground"])

PLAYGROUND_KEY_NAME = "playground"
SOURCE_TAG = "source:playground"
USER_AGENT = "gw-playground/1.0"
VISION_RE = re.compile(r"(vision|-vl\b|-vl-|\dv-|\dv\b)", re.I)
FALLBACK_DEFAULT_MAX_TOKENS = 8192   # reasoning models need room to think before they answer
FALLBACK_MAX_OUTPUT_TOKENS = 131072
HARD_MAX_TOKENS = 1_048_576
EFFORT_LEVELS = ("off", "low", "medium", "high")


# ---------------------------------------------------------------- schemas
class PgMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = ""
    images: list[str] = Field(default_factory=list, max_length=8)  # data: URLs (base64)


class PlaygroundIn(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    messages: list[PgMessage] = Field(min_length=1, max_length=200)
    system: str | None = Field(default=None, max_length=100_000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_tokens: int = Field(default=FALLBACK_DEFAULT_MAX_TOKENS, ge=1, le=HARD_MAX_TOKENS)
    # "default" / None = provider default; other values are applied only if the model supports them
    reasoning_effort: Literal["default", "off", "low", "medium", "high"] | None = None
    # images for a model without vision: False -> 422 (the UI asks first); True -> drop them and tell the model
    strip_images: bool = False
    stream: bool = True
    api_format: Literal["openai", "anthropic"] = "openai"
    key_id: int | None = None
    compare_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]*$")


# ---------------------------------------------------------------- helpers
def is_vision(m: Model) -> bool:
    if m.supports_vision is not None:  # explicit metadata wins over the name heuristic
        return bool(m.supports_vision)
    return "vision" in (m.tags or []) or bool(VISION_RE.search(m.model_name) or VISION_RE.search(m.upstream_id))


def caps(m: Model | None) -> dict:
    """Capability metadata the Playground uses for defaults, limits and guards."""
    if m is None:
        return {"vision": False, "reasoning": False, "max_output_tokens": FALLBACK_MAX_OUTPUT_TOKENS,
                "default_max_tokens": FALLBACK_DEFAULT_MAX_TOKENS, "reasoning_efforts": []}
    cap = m.max_output_tokens or FALLBACK_MAX_OUTPUT_TOKENS
    if m.context_window:
        cap = min(cap, m.context_window)
    default = min(m.default_max_tokens or FALLBACK_DEFAULT_MAX_TOKENS, cap)
    efforts = [e for e in (m.reasoning_efforts or []) if e in EFFORT_LEVELS]
    return {"vision": is_vision(m), "reasoning": bool(m.supports_reasoning), "max_output_tokens": cap,
            "default_max_tokens": default, "reasoning_efforts": efforts}


def resolve_model(db: Session, name: str) -> Model | None:
    m = db.scalar(select(Model).where(Model.model_name == name))
    if m:
        return m
    a = db.scalar(select(Alias).where(Alias.name == name))
    return a.target if a else None


def ensure_playground_key(db: Session) -> ApiKey:
    """Return the internal playground virtual key, creating it in LiteLLM on first use."""
    k = db.scalar(select(ApiKey).where(ApiKey.name == PLAYGROUND_KEY_NAME))
    if k and not k.revoked:
        return k
    if k and k.revoked:  # free the unique name so a fresh key can be minted
        k.name = f"{PLAYGROUND_KEY_NAME}-revoked-{k.id}"
        db.commit()
    from .keys import create_key
    return create_key(db, KeyIn(name=PLAYGROUND_KEY_NAME))


def _model_entry(m: Model, name: str | None = None, kind: str = "model", alias: Alias | None = None) -> dict:
    p = m.provider
    return {
        "name": name or m.model_name, "kind": kind,
        "display_name": m.display_name if kind == "model" else ((alias.description if alias else None) or m.display_name),
        "target": m.model_name if kind == "alias" else None, "upstream_id": m.upstream_id,
        "provider_slug": p.slug, "provider_name": p.name, "provider_enabled": p.enabled,
        "enabled": m.enabled, "live": deployable(m), **caps(m),
        "input_price_per_m": m.input_price_per_m, "output_price_per_m": m.output_price_per_m,
        "context_window": m.context_window, **audio_meta(m), "pinned": bool(m.pinned) or kind == "alias",
        "synced": bool(m.synced),
    }


def audio_meta(m: Model | None) -> dict:
    if m is None:
        return {"audio": "chat", "voices": [], "default_voice": None, "price_per_minute": None, "price_per_m_chars": None,
                "audio_input_price_per_m": None, "audio_output_price_per_m": None}
    return {"audio": m.kind or "chat", "voices": m.voices or [], "default_voice": m.default_voice,
            "price_per_minute": m.price_per_minute, "price_per_m_chars": m.price_per_m_chars,
            "audio_input_price_per_m": m.audio_input_price_per_m, "audio_output_price_per_m": m.audio_output_price_per_m}


def _price_index(db: Session) -> dict:
    """model_name / deployment-id -> pricing + provider, for cost and 'resolved model' metadata."""
    idx: dict[str, dict] = {}
    for m in db.scalars(select(Model)).all():
        e = {"model": m.model_name, "upstream_id": m.upstream_id, "provider": m.provider.name, "provider_slug": m.provider.slug,
             "in": m.input_price_per_m or 0.0, "out": m.output_price_per_m or 0.0}
        idx[m.model_name] = e
        idx[f"gw-m-{m.id}"] = e
    for a in db.scalars(select(Alias)).all():
        if a.target:
            e = dict(idx.get(a.target.model_name, {}))
            idx[a.name] = e
            idx[f"gw-a-{a.id}"] = e
    return idx


def _split_data_url(url: str) -> tuple[str, str]:
    m = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", url, re.S)
    if not m:
        raise HTTPException(400, "Images must be base64 data: URLs (image/png, image/jpeg, image/webp, image/gif)")
    return m.group(1), m.group(2)


IMAGE_NOTE = ("[Note from the gateway: the user attached {n} image(s) here, but they were removed because this model "
              "cannot view images. You have not seen them; do not describe or guess their content - say you cannot see them.]")


def strip_images(messages: list[PgMessage]) -> tuple[list[PgMessage], int]:
    """Remove image parts and leave a note in their place so the model does not hallucinate about them."""
    out, removed = [], 0
    for m in messages:
        if m.images:
            removed += len(m.images)
            note = IMAGE_NOTE.format(n=len(m.images))
            out.append(PgMessage(role=m.role, content=(m.content + "\n\n" + note) if m.content.strip() else note, images=[]))
        else:
            out.append(m)
    return out, removed


def apply_reasoning(payload: dict, level: str | None, c: dict, api_format: str) -> str | None:
    """Translate the Playground reasoning level into upstream parameters. Returns the applied level (or None)."""
    if not level or level == "default" or level not in c["reasoning_efforts"] or api_format != "openai":
        return None  # unsupported levels are ignored; the Anthropic path has no portable equivalent
    if level == "off":
        # Together honours reasoning.enabled=false (LiteLLM forwards it as a provider-specific param)
        payload["reasoning"] = {"enabled": False}
    else:
        payload["reasoning_effort"] = level
        # LiteLLM drops reasoning_effort for together_ai models it does not know (drop_params) unless allowed explicitly
        payload["allowed_openai_params"] = ["reasoning_effort"]
    return level


def build_payload(body: PlaygroundIn, messages: list[PgMessage] | None = None) -> tuple[str, dict]:
    msgs = [m for m in (messages if messages is not None else body.messages) if m.content.strip() or m.images]
    if not msgs or msgs[-1].role != "user":
        raise HTTPException(400, "The conversation must end with a user message")
    if body.api_format == "openai":
        out: list[dict] = []
        if body.system and body.system.strip():
            out.append({"role": "system", "content": body.system})
        for m in msgs:
            if m.images and m.role == "user":
                parts: list[dict] = [{"type": "text", "text": m.content}] if m.content else []
                for u in m.images:
                    _split_data_url(u)
                    parts.append({"type": "image_url", "image_url": {"url": u}})
                out.append({"role": m.role, "content": parts})
            else:
                out.append({"role": m.role, "content": m.content})
        payload: dict = {"model": body.model, "messages": out, "max_tokens": body.max_tokens, "stream": body.stream}
        if body.stream:
            payload["stream_options"] = {"include_usage": True}
        path = "/v1/chat/completions"
    else:
        out = []
        for m in msgs:
            if m.images and m.role == "user":
                parts = []
                for u in m.images:
                    mt, data = _split_data_url(u)
                    parts.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": data}})
                if m.content:
                    parts.append({"type": "text", "text": m.content})
                out.append({"role": m.role, "content": parts})
            else:
                out.append({"role": m.role, "content": m.content})
        payload = {"model": body.model, "messages": out, "max_tokens": body.max_tokens, "stream": body.stream}
        if body.system and body.system.strip():
            payload["system"] = body.system
        path = "/v1/messages"
    if body.temperature is not None:
        payload["temperature"] = body.temperature
    if body.top_p is not None:
        payload["top_p"] = body.top_p
    return path, payload


def _resolve(prepared: dict, headers: httpx.Headers) -> dict:
    idx = prepared["prices"]
    dep = headers.get("x-litellm-model-id") or ""
    e = idx.get(dep) or idx.get(prepared["model"]) or {}
    upstream = headers.get("x-litellm-model-name") or e.get("upstream_id")
    return {"request_id": headers.get("x-litellm-call-id"), "deployment_id": dep or None,
            "model_group": headers.get("x-litellm-model-group") or prepared["model"],
            "resolved_model": e.get("model"), "upstream_model": upstream,
            "provider": e.get("provider"), "provider_slug": e.get("provider_slug"),
            "header_cost": headers.get("x-litellm-response-cost")}


def _metrics(prepared: dict, info: dict, t0: float, ttft: float | None, usage: dict, status: int, finish: str | None) -> dict:
    total = (time.perf_counter() - t0) * 1000
    tin = int(usage.get("in") or 0)
    tout = int(usage.get("out") or 0)
    e = prepared["prices"].get(info.get("deployment_id") or "") or prepared["prices"].get(prepared["model"]) or {}
    info = dict(info)
    hc = info.pop("header_cost", None)
    cost, cost_source = None, None
    try:
        if hc is not None and float(hc) > 0:
            cost, cost_source = float(hc), "litellm"
    except ValueError:
        pass
    if cost is None and e and (tin or tout):
        cost, cost_source = (tin * e.get("in", 0) + tout * e.get("out", 0)) / 1_000_000, "pricing"
    gen_ms = total - ttft if (ttft is not None and prepared["stream"]) else total
    tps = round(tout / (gen_ms / 1000), 1) if tout and gen_ms > 0 else None
    return {**info, "status": status, "ok": 200 <= status < 300, "latency_ms": round(total, 1),
            "ttft_ms": round(ttft, 1) if ttft is not None else None, "tokens_in": tin, "tokens_out": tout,
            "reasoning_tokens": usage.get("reasoning"), "tokens_per_sec": tps, "cost": cost, "cost_source": cost_source,
            "finish_reason": finish, "truncated": finish in ("length", "max_tokens"),
            "api_format": prepared["api_format"], "stream": prepared["stream"], "key_name": prepared["key_name"],
            "max_tokens": prepared.get("max_tokens"), "reasoning_effort": prepared.get("reasoning_effort"),
            "images_removed": prepared.get("images_removed", 0)}


def _err_message(raw: bytes | str, status: int) -> str:
    text = raw.decode(errors="replace") if isinstance(raw, bytes) else raw
    try:
        j = json.loads(text)
        e = j.get("error", j) if isinstance(j, dict) else j
        msg = (e.get("message") or e.get("detail")) if isinstance(e, dict) else str(e)
        msg = msg or text
    except Exception:  # noqa: BLE001
        msg = text
    return f"HTTP {status}: {str(msg)[:1500]}"


def _usage_openai(u: dict | None) -> dict:
    if not u:
        return {}
    det = u.get("completion_tokens_details") or {}
    return {"in": u.get("prompt_tokens"), "out": u.get("completion_tokens"), "reasoning": det.get("reasoning_tokens")}


def prepare(body: PlaygroundIn, user: User) -> dict:
    """Blocking DB work (key lookup/creation, pricing) - runs in a thread before the stream starts."""
    db = SessionLocal()
    try:
        if body.key_id:
            k = db.get(ApiKey, body.key_id)
            if not k or k.revoked:
                raise HTTPException(404, "API key not found or revoked")
        else:
            k = ensure_playground_key(db)
        m = resolve_model(db, body.model)
        c = caps(m)
        messages, removed = body.messages, 0
        if any(x.images for x in messages) and not c["vision"]:
            if not body.strip_images:
                raise HTTPException(422, f"{body.model} does not accept images. Switch to a vision model, or resend with "
                                         "strip_images=true to send the text only.")
            messages, removed = strip_images(messages)
        max_tokens = min(body.max_tokens, c["max_output_tokens"])
        body = body.model_copy(update={"max_tokens": max_tokens})
        path, payload = build_payload(body, messages)
        effort = apply_reasoning(payload, body.reasoning_effort, c, body.api_format)
        tags = [SOURCE_TAG, f"playground-user:{user.username}"] + ([f"compare:{body.compare_id}"] if body.compare_id else [])
        headers = {"User-Agent": USER_AGENT, "x-litellm-tags": ",".join(tags), "Content-Type": "application/json"}
        raw = decrypt(k.key_enc)
        if body.api_format == "anthropic":
            headers["x-api-key"] = raw
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {raw}"
        return {"path": path, "payload": payload, "headers": headers, "prices": _price_index(db), "model": body.model,
                "stream": body.stream, "api_format": body.api_format, "key_name": k.name,
                "max_tokens": max_tokens, "reasoning_effort": effort, "images_removed": removed}
    finally:
        db.close()


def _sse(obj: dict) -> bytes:
    return f"data: {json.dumps(obj, default=str)}\n\n".encode()


# ---------------------------------------------------------------- endpoints
@router.get("/options")
def options(db: Session = Depends(get_db), _: User = Depends(current_user)):
    pg = ensure_playground_key(db)
    models = []
    for a in db.scalars(select(Alias).order_by(Alias.id)).all():
        if a.target:
            models.append(_model_entry(a.target, a.name, "alias", a))
        else:
            models.append({"name": a.name, "kind": "alias", "display_name": a.description or a.name, "target": None,
                           "upstream_id": None, "provider_slug": None, "provider_name": None, "provider_enabled": False,
                           "enabled": False, "live": False, **caps(None), "input_price_per_m": 0, "output_price_per_m": 0,
                           "context_window": None, **audio_meta(None), "pinned": True, "synced": False})
    for p in db.scalars(select(Provider).order_by(Provider.id)).all():
        for m in sorted(p.models, key=lambda x: x.id):
            models.append(_model_entry(m))
    keys = [{"id": k.id, "name": k.name, "key_prefix": k.key_prefix, "models": k.models or [],
             "internal": k.id == pg.id, "max_budget": k.max_budget, "rpm_limit": k.rpm_limit}
            for k in db.scalars(select(ApiKey).where(ApiKey.revoked.is_(False)).order_by(ApiKey.id)).all()]
    return {"models": models, "keys": keys, "default_key_id": pg.id,
            "openai_base_url": f"https://{settings.public_host}/v1", "anthropic_base_url": f"https://{settings.public_host}",
            "source_tag": SOURCE_TAG}


@router.post("/chat")
async def chat(body: PlaygroundIn, user: User = Depends(current_user)):
    prepared = await run_in_threadpool(prepare, body, user)
    url = settings.litellm_url + prepared["path"]
    timeout = httpx.Timeout(600.0, connect=10.0)

    if not body.stream:
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(url, json=prepared["payload"], headers=prepared["headers"])
        except httpx.HTTPError as e:
            return JSONResponse({"ok": False, "error": f"Gateway connection error: {e}", "metrics": None})
        info = _resolve(prepared, r.headers)
        if r.status_code >= 400:
            m = _metrics(prepared, info, t0, None, {}, r.status_code, None)
            return JSONResponse({"ok": False, "error": _err_message(r.content, r.status_code), "metrics": m})
        j = r.json()
        if body.api_format == "anthropic":
            blocks = j.get("content") or []
            content = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            reasoning = "".join(b.get("thinking", "") or "" for b in blocks if b.get("type") == "thinking")
            u = j.get("usage") or {}
            usage = {"in": u.get("input_tokens"), "out": u.get("output_tokens")}
            finish = j.get("stop_reason")
        else:
            ch = (j.get("choices") or [{}])[0]
            msg = ch.get("message") or {}
            content = msg.get("content") or ""
            reasoning = msg.get("reasoning_content") or ""
            usage = _usage_openai(j.get("usage"))
            finish = ch.get("finish_reason")
        m = _metrics(prepared, info, t0, None, usage, r.status_code, finish)
        return {"ok": True, "content": content, "reasoning": reasoning, "metrics": m}

    async def gen():
        t0 = time.perf_counter()
        ttft = None
        usage: dict = {}
        finish = None
        status = 0
        info: dict = {}
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                async with c.stream("POST", url, json=prepared["payload"], headers=prepared["headers"]) as r:
                    status = r.status_code
                    info = _resolve(prepared, r.headers)
                    yield _sse({"type": "meta", **{k: v for k, v in info.items() if k != "header_cost"}})
                    if r.status_code >= 400:
                        raw = await r.aread()
                        yield _sse({"type": "error", "status": r.status_code, "message": _err_message(raw, r.status_code),
                                    "metrics": _metrics(prepared, info, t0, None, {}, r.status_code, None)})
                        return
                    event = None
                    async for line in r.aiter_lines():
                        if line.startswith("event:"):
                            event = line[6:].strip()
                            continue
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            ev = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(ev, dict):
                            continue
                        if ev.get("error") or ev.get("type") == "error":
                            e = ev.get("error") or {}
                            msg = e.get("message") if isinstance(e, dict) else str(e)
                            code = (e.get("code") if isinstance(e, dict) else None) or 500
                            try:
                                code = int(code)
                            except (TypeError, ValueError):
                                code = 500
                            status = code
                            yield _sse({"type": "error", "status": code, "message": f"HTTP {code}: {msg}",
                                        "metrics": _metrics(prepared, info, t0, ttft, usage, code, None)})
                            return
                        text_piece, reason_piece = "", ""
                        if body.api_format == "anthropic":
                            et = ev.get("type") or event
                            if et == "message_start":
                                u = (ev.get("message") or {}).get("usage") or {}
                                usage["in"] = u.get("input_tokens") or usage.get("in")
                            elif et == "content_block_delta":
                                d = ev.get("delta") or {}
                                if d.get("type") == "text_delta":
                                    text_piece = d.get("text") or ""
                                elif d.get("type") == "thinking_delta":
                                    reason_piece = d.get("thinking") or ""
                            elif et == "message_delta":
                                u = ev.get("usage") or {}
                                if u.get("output_tokens") is not None:
                                    usage["out"] = u["output_tokens"]
                                if u.get("input_tokens"):
                                    usage["in"] = u["input_tokens"]
                                finish = (ev.get("delta") or {}).get("stop_reason") or finish
                        else:
                            if ev.get("usage"):
                                usage = _usage_openai(ev["usage"])
                            for ch in ev.get("choices") or []:
                                d = ch.get("delta") or {}
                                text_piece += d.get("content") or ""
                                reason_piece += d.get("reasoning_content") or ""
                                if ch.get("finish_reason"):
                                    finish = ch["finish_reason"]
                        if (text_piece or reason_piece) and ttft is None:
                            ttft = (time.perf_counter() - t0) * 1000
                        if reason_piece:
                            yield _sse({"type": "reasoning", "text": reason_piece})
                        if text_piece:
                            yield _sse({"type": "delta", "text": text_piece})
            yield _sse({"type": "done", "metrics": _metrics(prepared, info, t0, ttft, usage, status or 200, finish)})
        except httpx.HTTPError as e:
            yield _sse({"type": "error", "status": 502, "message": f"Gateway connection error: {e}",
                        "metrics": _metrics(prepared, info, t0, ttft, usage, 502, None) if info else None})

    # Content-Encoding: identity keeps GZipMiddleware and Caddy's encoder from buffering the event stream
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Content-Encoding": "identity"})

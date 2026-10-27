import json
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import Alias, Model, Provider, User, get_db
from ..litellm_sync import deployable, sync_safe
from ..config import settings
from ..schemas import AliasIn, AliasPatch, ModelIn, ModelPatch, TestIn
from ..security import current_user

router = APIRouter(prefix="/api", tags=["models"])


def model_out(m: Model) -> dict:
    return {
        "id": m.id, "provider_id": m.provider_id, "provider_slug": m.provider.slug, "provider_name": m.provider.name,
        "provider_enabled": m.provider.enabled, "model_name": m.model_name, "upstream_id": m.upstream_id,
        "display_name": m.display_name, "input_price_per_m": m.input_price_per_m,
        "output_price_per_m": m.output_price_per_m, "context_window": m.context_window, "enabled": m.enabled,
        "tags": m.tags or [], "live": deployable(m),
        "max_output_tokens": m.max_output_tokens, "default_max_tokens": m.default_max_tokens,
        "supports_reasoning": m.supports_reasoning, "supports_vision": m.supports_vision,
        "reasoning_efforts": m.reasoning_efforts or [],
        "kind": m.kind or "chat", "voices": m.voices or [], "default_voice": m.default_voice,
        "price_per_minute": m.price_per_minute, "price_per_m_chars": m.price_per_m_chars,
        "audio_input_price_per_m": m.audio_input_price_per_m, "audio_output_price_per_m": m.audio_output_price_per_m,
        "api_base": m.api_base, "synced": bool(m.synced), "pinned": bool(m.pinned), "available": m.available,
        "status_note": m.status_note, "pipeline": m.provider.kind == "pipeline",
    }


def alias_out(a: Alias) -> dict:
    return {"id": a.id, "name": a.name, "description": a.description, "target_model_id": a.target_model_id,
            "target": model_out(a.target) if a.target else None, "live": deployable(a.target),
            "updated_at": a.updated_at}


@router.get("/models")
def list_models(db: Session = Depends(get_db), _: User = Depends(current_user)):
    ms = db.scalars(select(Model).join(Provider).order_by(Provider.id, Model.id)).all()
    return [model_out(m) for m in ms]


@router.post("/models")
def create_model(body: ModelIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    if not db.get(Provider, body.provider_id):
        raise HTTPException(404, "Provider not found")
    if db.scalar(select(Model).where(Model.model_name == body.model_name)) or db.scalar(select(Alias).where(Alias.name == body.model_name)):
        raise HTTPException(409, "A model or alias with this name already exists")
    m = Model(provider_id=body.provider_id, model_name=body.model_name.strip(), upstream_id=body.upstream_id.strip(),
              display_name=body.display_name or body.upstream_id, input_price_per_m=body.input_price_per_m,
              output_price_per_m=body.output_price_per_m, context_window=body.context_window, enabled=body.enabled,
              tags=body.tags or [], max_output_tokens=body.max_output_tokens,
              default_max_tokens=body.default_max_tokens, supports_reasoning=body.supports_reasoning,
              supports_vision=body.supports_vision, reasoning_efforts=body.reasoning_efforts, kind=body.kind or "chat",
              voices=body.voices, default_voice=body.default_voice, price_per_minute=body.price_per_minute,
              price_per_m_chars=body.price_per_m_chars, audio_input_price_per_m=body.audio_input_price_per_m,
              audio_output_price_per_m=body.audio_output_price_per_m, api_base=body.api_base or None,
              pinned=True if body.pinned is None else body.pinned)
    db.add(m)
    db.commit()
    db.refresh(m)
    return {"model": model_out(m), "sync": sync_safe(db)}


@router.patch("/models/{mid}")
def update_model(mid: int, body: ModelPatch, db: Session = Depends(get_db), _: User = Depends(current_user)):
    m = db.get(Model, mid)
    if not m:
        raise HTTPException(404, "Model not found")
    data = body.model_dump(exclude_unset=True)
    if "model_name" in data and data["model_name"] != m.model_name:
        n = data["model_name"]
        if db.scalar(select(Model).where(Model.model_name == n)) or db.scalar(select(Alias).where(Alias.name == n)):
            raise HTTPException(409, "Name already in use")
    for k, v in data.items():
        setattr(m, k, v)
    db.commit()
    db.refresh(m)
    return {"model": model_out(m), "sync": sync_safe(db)}


@router.delete("/models/{mid}")
def delete_model(mid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    m = db.get(Model, mid)
    if not m:
        raise HTTPException(404, "Model not found")
    db.delete(m)
    db.commit()
    return {"ok": True, "sync": sync_safe(db)}


@router.get("/aliases")
def list_aliases(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [alias_out(a) for a in db.scalars(select(Alias).order_by(Alias.id)).all()]


@router.post("/aliases")
def create_alias(body: AliasIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    name = body.name.strip()
    if db.scalar(select(Alias).where(Alias.name == name)) or db.scalar(select(Model).where(Model.model_name == name)):
        raise HTTPException(409, "Name already in use")
    a = Alias(name=name, target_model_id=body.target_model_id, description=body.description)
    db.add(a)
    db.commit()
    db.refresh(a)
    return {"alias": alias_out(a), "sync": sync_safe(db)}


@router.patch("/aliases/{aid}")
def update_alias(aid: int, body: AliasPatch, db: Session = Depends(get_db), _: User = Depends(current_user)):
    a = db.get(Alias, aid)
    if not a:
        raise HTTPException(404, "Alias not found")
    data = body.model_dump(exclude_unset=True)
    if "target_model_id" in data:
        if data["target_model_id"] is not None and not db.get(Model, data["target_model_id"]):
            raise HTTPException(404, "Target model not found")
        a.target_model_id = data["target_model_id"]
    if "description" in data:
        a.description = data["description"]
    db.commit()
    db.refresh(a)
    return {"alias": alias_out(a), "sync": sync_safe(db)}


@router.delete("/aliases/{aid}")
def delete_alias(aid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    a = db.get(Alias, aid)
    if not a:
        raise HTTPException(404, "Alias not found")
    db.delete(a)
    db.commit()
    return {"ok": True, "sync": sync_safe(db)}


@router.post("/sync")
def force_sync(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return sync_safe(db)


def run_test(model_name: str, prompt: str, max_tokens: int) -> dict:
    """Streaming chat completion through LiteLLM; measures TTFT and total latency."""
    body = {"model": model_name, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
            "stream": True, "stream_options": {"include_usage": True}, "metadata": {"tags": ["gateway-test"]}}
    t0 = time.perf_counter()
    ttft = None
    text, reasoning, usage, err = [], [], None, None
    try:
        with httpx.stream("POST", f"{settings.litellm_url}/v1/chat/completions", json=body, timeout=120,
                          headers={"Authorization": f"Bearer {settings.litellm_master_key}"}) as r:
            if r.status_code >= 400:
                r.read()
                try:
                    err = r.json().get("error", {}).get("message") or r.text
                except Exception:  # noqa: BLE001
                    err = r.text
                err = f"HTTP {r.status_code}: {str(err)[:400]}"
            else:
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        ev = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if ev.get("usage"):
                        usage = ev["usage"]
                    for ch in ev.get("choices") or []:
                        d = ch.get("delta") or {}
                        piece = d.get("content")
                        rpiece = d.get("reasoning_content")
                        if (piece or rpiece) and ttft is None:
                            ttft = (time.perf_counter() - t0) * 1000
                        if piece:
                            text.append(piece)
                        if rpiece:
                            reasoning.append(rpiece)
    except httpx.HTTPError as e:
        err = f"Connection error: {e}"
    total = (time.perf_counter() - t0) * 1000
    return {"ok": err is None, "model": model_name, "latency_ms": round(total), "ttft_ms": round(ttft) if ttft else None,
            "output": "".join(text).strip()[:2000], "reasoning_chars": len("".join(reasoning)), "usage": usage, "error": err}


SAMPLE = Path(__file__).resolve().parent.parent / "assets" / "sample.mp3"  # "Hello from the Lora gateway. The quick brown fox..."
MASTER = lambda: {"Authorization": f"Bearer {settings.litellm_master_key}", "x-litellm-tags": "gateway-test"}  # noqa: E731


def run_audio_test(m: Model) -> dict:
    """Kind-specific smoke test: transcribe a bundled clip, synthesise a sentence, or open a realtime session."""
    kind = m.kind or "chat"
    t0 = time.perf_counter()
    out = {"ok": False, "model": m.model_name, "latency_ms": 0, "ttft_ms": None, "output": "", "reasoning_chars": 0,
           "usage": None, "error": None}
    try:
        if kind == "transcription":
            r = httpx.post(f"{settings.litellm_url}/v1/audio/transcriptions", headers=MASTER(), timeout=120,
                           data={"model": m.model_name}, files={"file": ("sample.mp3", SAMPLE.read_bytes(), "audio/mpeg")})
            if r.status_code < 400:
                out.update(ok=True, output=r.json().get("text", ""))
            else:
                out["error"] = f"HTTP {r.status_code}: {r.text[:400]}"
        elif kind == "speech":
            r = httpx.post(f"{settings.litellm_url}/v1/audio/speech", headers=MASTER(), timeout=120,
                           json={"model": m.model_name, "input": "Hello from the Lora gateway.", "voice": m.default_voice or "alloy"})
            if r.status_code < 400 and r.content:
                out.update(ok=True, output=f"{len(r.content):,} bytes of {r.headers.get('content-type', 'audio')}")
            else:
                out["error"] = f"HTTP {r.status_code}: {r.text[:400]}"
        elif kind == "realtime":
            import asyncio
            import websockets

            async def probe():
                url = settings.litellm_url.replace("http://", "ws://") + "/v1/realtime?model=" + m.model_name
                async with websockets.connect(url, additional_headers=MASTER(), open_timeout=20) as ws:
                    first = json.loads(await asyncio.wait_for(ws.recv(), 20))
                    return first

            first = asyncio.run(probe())
            if first.get("type") == "session.created":
                out.update(ok=True, output=f"session.created ({(first.get('session') or {}).get('model', m.upstream_id)})")
            else:
                out["error"] = json.dumps(first)[:400]
        else:
            return run_test(m.model_name, "Reply with exactly: pong", 64)
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"[:400]
    out["latency_ms"] = round((time.perf_counter() - t0) * 1000)
    return out


@router.post("/models/{mid}/test")
def test_model(mid: int, body: TestIn | None = None, db: Session = Depends(get_db), _: User = Depends(current_user)):
    m = db.get(Model, mid)
    if not m:
        raise HTTPException(404, "Model not found")
    if not deployable(m):
        raise HTTPException(400, "Model is not live (enable it and its provider, and make sure the provider has an API key)")
    if (m.kind or "chat") in ("transcription", "speech", "realtime"):
        return run_audio_test(m)
    body = body or TestIn()
    return run_test(m.model_name, body.prompt, body.max_tokens)


@router.post("/test/{name:path}")
def test_by_name(name: str, body: TestIn | None = None, _: User = Depends(current_user)):
    body = body or TestIn()
    return run_test(name, body.prompt, body.max_tokens)

"""Provider catalog sync: import every model a provider serves (with kind, context, capabilities and prices).

Sources (no guessing):
* Together  GET /v1/models  - type (chat/language/code/transcribe/audio/embedding/rerank/image/video), pricing
  (input/output per 1M tokens; transcribe.price_per_minute; audio models: "input" = USD per 1M characters),
  context_length; voices from GET /v1/voices.
* OpenRouter GET /api/v1/models - pricing per token, context_length, architecture.input/output_modalities,
  supported_parameters (reasoning).
* Vercel AI Gateway GET /v1/models - type, pricing per token, context_window, max_tokens, tags (reasoning, vision).
* Everything else: the OpenAI-style GET /models list; optional fields some providers add (DeepInfra metadata.pricing,
  Groq context_window, Mistral capabilities) are used, otherwise the price stays 0 and the model is tagged
  "price-unknown". Kinds then come from the model id (whisper/transcribe -> transcription, tts/kokoro/orpheus ->
  speech, embed -> embedding, realtime -> realtime).

Synced models are named "<provider slug>/<upstream id>", routable by default (registered in LiteLLM) but not pinned,
so the console shows the curated/pinned set unless you search or filter. Models the gateway cannot serve (image and
video generation, moderation) are skipped. Optional availability probe: one tiny real request per model (Together lists
dedicated-only and data-sharing-gated models next to serverless ones; the probe disables the ones that fail).
"""
import concurrent.futures as cf
import json
import logging
import re
import threading
import time
from datetime import timedelta
from pathlib import Path

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .catalog import SKIP_SYNC, SYNC_STYLE
from .config import settings
from .db import Meta, Model, Provider, SessionLocal, engine, utcnow
from .litellm_sync import provider_base, sync_safe
from .security import decrypt

log = logging.getLogger("gateway.catalog_sync")
SAMPLE = Path(__file__).resolve().parent / "assets" / "sample.mp3"
SYNC_EVERY = timedelta(hours=24)

TOGETHER_TYPES = {"chat": "chat", "language": "chat", "code": "chat", "transcribe": "transcription", "audio": "speech",
                  "embedding": "embedding", "rerank": None, "image": None, "video": None, "moderation": None}


def _num(v) -> float | None:
    try:
        f = float(v)
        return f if f >= 0 else None
    except (TypeError, ValueError):
        return None


def kind_from_name(mid: str) -> str | None:
    s = mid.lower()
    if re.search(r"(dall-e|gpt-image|flux|stable-diffusion|sdxl|imagen|video|veo|sora|wan2|seedance|seedream)", s):
        return None
    if "moderation" in s or "guard" in s and "prompt-guard" in s:
        return None
    if "realtime" in s:
        return "realtime"
    if re.search(r"(whisper|transcribe|parakeet|voxtral-mini-transcribe|asr|speech-to-text|stt)", s):
        return "transcription"
    if re.search(r"(tts|kokoro|orpheus|sonic|text-to-speech|aura|playai|speech)", s):
        return "speech"
    if re.search(r"(embed|bge-|e5-|gte-|nomic)", s):
        return "embedding"
    if "rerank" in s:
        return None
    if re.search(r"-audio(-|$)", s):
        return "input"
    return "chat"


def _vision_from_name(mid: str) -> bool | None:
    return True if re.search(r"(vision|-vl\b|-vl-|\bvl\b|pixtral|llava)", mid, re.I) else None


# ---------------------------------------------------------------- per-provider readers -> list of model dicts
def read_together(p: Provider, key: str) -> list[dict]:
    base = provider_base(p)
    with httpx.Client(timeout=60, headers={"Authorization": f"Bearer {key}"}) as c:
        data = c.get(f"{base}/models").json()
        data = data.get("data", data) if isinstance(data, dict) else data
        voices = {}
        try:
            vj = c.get(f"{base}/voices").json()
            for e in vj.get("data", vj) if isinstance(vj, dict) else vj:
                voices[e["model"]] = [v["name"] if isinstance(v, dict) else v for v in e.get("voices", [])]
        except Exception:  # noqa: BLE001
            log.warning("together voices unavailable")
    out = []
    for m in data:
        kind = TOGETHER_TYPES.get(m.get("type"), None)
        if not kind:
            continue
        pr = m.get("pricing") or {}
        e = {"upstream_id": m["id"], "display_name": m.get("display_name") or m["id"], "kind": kind,
             "context_window": m.get("context_length") or None}
        if kind == "transcription":
            tr = pr.get("transcribe") or {}
            e["price_per_minute"] = _num(tr.get("price_per_minute")) if isinstance(tr, dict) else None
        elif kind == "speech":
            e["price_per_m_chars"] = _num(pr.get("input"))
            e["voices"] = voices.get(m["id"], [])
            e["default_voice"] = e["voices"][0] if e["voices"] else None
            e["context_window"] = None
        else:
            e["input_price_per_m"] = _num(pr.get("input")) or 0
            e["output_price_per_m"] = _num(pr.get("output")) or 0
            e["supports_vision"] = _vision_from_name(m["id"])
        e["price_known"] = any(_num(pr.get(k)) for k in ("input", "output")) or bool(e.get("price_per_minute"))
        out.append(e)
    return out


def read_openrouter(p: Provider, key: str | None) -> list[dict]:
    base = provider_base(p) or "https://openrouter.ai/api/v1"
    h = {"Authorization": f"Bearer {key}"} if key else {}
    data = httpx.get(f"{base}/models", headers=h, timeout=60).json().get("data", [])
    out = []
    for m in data:
        arch = m.get("architecture") or {}
        outs = arch.get("output_modalities") or ["text"]
        ins = arch.get("input_modalities") or ["text"]
        if "text" not in outs and "audio" not in outs:
            continue  # image-only generators
        pr = m.get("pricing") or {}
        pin, pout = _num(pr.get("prompt")), _num(pr.get("completion"))
        if pin is None or pout is None:
            continue  # variable-price routers such as openrouter/auto
        kind = "input" if "audio" in outs else "chat"
        out.append({"upstream_id": m["id"], "display_name": m.get("name") or m["id"], "kind": kind,
                    "context_window": m.get("context_length") or None,
                    "input_price_per_m": round(pin * 1_000_000, 6), "output_price_per_m": round(pout * 1_000_000, 6),
                    "supports_vision": "image" in ins, "supports_reasoning": "reasoning" in (m.get("supported_parameters") or []),
                    "max_output_tokens": (m.get("top_provider") or {}).get("max_completion_tokens") or None,
                    "price_known": True, "audio_in": "audio" in ins})
    return out


def read_vercel(p: Provider, key: str | None) -> list[dict]:
    base = provider_base(p) or "https://ai-gateway.vercel.sh/v1"
    h = {"Authorization": f"Bearer {key}"} if key else {}
    data = httpx.get(f"{base}/models", headers=h, timeout=60).json().get("data", [])
    out = []
    for m in data:
        t = m.get("type") or "language"
        kind = {"language": "chat", "embedding": "embedding"}.get(t)
        if not kind:
            continue
        pr = m.get("pricing") or {}
        tags = m.get("tags") or []
        out.append({"upstream_id": m["id"], "display_name": m.get("name") or m["id"], "kind": kind,
                    "context_window": m.get("context_window") or None, "max_output_tokens": m.get("max_tokens") or None,
                    "input_price_per_m": round((_num(pr.get("input")) or 0) * 1_000_000, 6),
                    "output_price_per_m": round((_num(pr.get("output")) or 0) * 1_000_000, 6),
                    "supports_vision": "vision" in tags or None, "supports_reasoning": "reasoning" in tags or None,
                    "price_known": bool(pr)})
    return out


def read_openai_style(p: Provider, key: str) -> list[dict]:
    base = provider_base(p)
    data = httpx.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=60).json()
    data = data.get("data", data) if isinstance(data, dict) else data
    out = []
    for m in data or []:
        mid = m.get("id")
        if not mid:
            continue
        kind = kind_from_name(mid)
        if not kind:
            continue
        meta = m.get("metadata") or {}
        pr = meta.get("pricing") or m.get("pricing") or {}
        pin = _num(pr.get("input_tokens") or pr.get("input"))
        pout = _num(pr.get("output_tokens") or pr.get("output"))
        caps = m.get("capabilities") or {}
        e = {"upstream_id": mid, "display_name": m.get("name") or mid, "kind": kind,
             "context_window": m.get("context_window") or m.get("context_length") or meta.get("context_length") or m.get("max_context_length") or None,
             "input_price_per_m": pin or 0, "output_price_per_m": pout or 0, "price_known": pin is not None,
             "supports_vision": caps.get("vision") if isinstance(caps, dict) and "vision" in caps else _vision_from_name(mid)}
        out.append(e)
    return out


READERS = {"together": read_together, "openrouter": read_openrouter, "vercel": read_vercel}


# ---------------------------------------------------------------- probing (optional, real requests)
def _probe_one(m: dict, name: str) -> tuple[bool, str]:
    h = {"Authorization": f"Bearer {settings.litellm_master_key}", "x-litellm-tags": "gateway-test,catalog-probe"}
    url = settings.litellm_url
    try:
        if m["kind"] in ("chat", "input"):
            r = httpx.post(f"{url}/v1/chat/completions", headers=h, timeout=60,
                           json={"model": name, "messages": [{"role": "user", "content": "Say ok"}], "max_tokens": 16})
        elif m["kind"] == "transcription":
            r = httpx.post(f"{url}/v1/audio/transcriptions", headers=h, timeout=60, data={"model": name},
                           files={"file": ("sample.mp3", SAMPLE.read_bytes(), "audio/mpeg")})
        elif m["kind"] == "speech":
            r = httpx.post(f"{url}/v1/audio/speech", headers=h, timeout=60,
                           json={"model": name, "input": "Hi.", "voice": m.get("default_voice") or "alloy"})
        elif m["kind"] == "embedding":
            r = httpx.post(f"{url}/v1/embeddings", headers=h, timeout=60, json={"model": name, "input": "hi"})
        else:
            return True, ""
    except httpx.HTTPError as e:
        return False, f"probe failed: {e}"[:300]
    if r.status_code < 400:
        return True, ""
    try:
        msg = r.json().get("error", {}).get("message") or r.text
    except Exception:  # noqa: BLE001
        msg = r.text
    msg = re.sub(r"\s+", " ", str(msg))
    if "non-serverless" in msg:
        msg = "Not serverless on this provider (needs a dedicated endpoint)"
    elif "third-party data sharing" in msg:
        msg = "Needs third-party data sharing enabled in the provider account"
    elif "No deployments are ready" in msg:
        msg = "Provider endpoint stopped (no ready deployment)"
    return False, f"HTTP {r.status_code}: {msg}"[:300]


# ---------------------------------------------------------------- main entry
_lock = threading.Lock()


def sync_provider(db: Session, p: Provider, probe: bool = False) -> dict:
    """Upsert the provider's catalog. Returns counts; never deletes curated (non-synced) models."""
    key = decrypt(p.api_key_enc)
    if p.kind in SKIP_SYNC:
        return {"ok": False, "error": "This provider has no model list to sync"}
    style = SYNC_STYLE.get(p.kind, "openai")
    if not key:
        return {"ok": False, "error": "Add an API key first"}
    t0 = time.perf_counter()
    try:
        items = READERS.get(style, read_openai_style)(p, key)
    except Exception as e:  # noqa: BLE001
        p.last_sync_at, p.last_sync_ok, p.last_sync_msg = utcnow(), False, f"{type(e).__name__}: {e}"[:500]
        db.commit()
        return {"ok": False, "error": p.last_sync_msg}
    existing = {m.upstream_id: m for m in db.scalars(select(Model).where(Model.provider_id == p.id)).all()}
    seen, added, updated = set(), 0, 0
    for e in items:
        up = e["upstream_id"]
        seen.add(up)
        cur = existing.get(up)
        fields = {k: v for k, v in e.items() if k not in ("upstream_id", "price_known", "audio_in") and v is not None}
        tags = ["synced"] + ([] if e.get("price_known") else ["price-unknown"]) + (["audio-in"] if e.get("audio_in") else [])
        if cur is None:
            name = f"{p.slug}/{up}"
            if db.scalar(select(Model).where(Model.model_name == name)):
                continue
            db.add(Model(provider_id=p.id, model_name=name, upstream_id=up, synced=True, pinned=False, enabled=True,
                         tags=tags, **{"display_name": up, **fields}))
            added += 1
        elif cur.synced:  # refresh prices / capabilities of synced rows (curated rows keep their hand-tuned values)
            for k, v in fields.items():
                if k in ("display_name",):
                    continue
                if getattr(cur, k) != v:
                    setattr(cur, k, v)
                    updated += 1
            cur.tags = sorted(set((cur.tags or []) + tags) - ({"price-unknown"} if e.get("price_known") else set()))
    removed = 0
    for up, m in existing.items():
        if m.synced and up not in seen and m.enabled:
            m.enabled = False
            m.status_note = "No longer listed by the provider"
            removed += 1
    db.commit()
    probed = None
    if probe:
        probed = probe_provider(db, p)
    msg = f"{len(items)} models listed, {added} added, {updated} fields updated, {removed} retired"
    if probed:
        msg += f", probe: {probed['ok']} ok / {probed['failed']} unavailable"
    p.last_sync_at, p.last_sync_ok, p.last_sync_msg = utcnow(), True, msg
    db.commit()
    s = sync_safe(db)
    return {"ok": True, "listed": len(items), "added": added, "updated": updated, "retired": removed, "probe": probed,
            "seconds": round(time.perf_counter() - t0, 1), "gateway_sync": s, "message": msg}


def probe_provider(db: Session, p: Provider, only_unprobed: bool = True) -> dict:
    """Send one tiny real request per synced model (in parallel) and disable those the provider will not serve."""
    sync_safe(db)  # make sure new rows are routable first
    db.expire_all()
    ms = [m for m in db.scalars(select(Model).where(Model.provider_id == p.id)).all() if m.synced and (m.kind or "chat") in ("chat", "input", "transcription", "speech", "embedding")
          and (m.available is None or not only_unprobed)]
    jobs = {m.id: {"kind": m.kind or "chat", "default_voice": m.default_voice, "name": m.model_name} for m in ms}
    res: dict[int, tuple[bool, str]] = {}
    with cf.ThreadPoolExecutor(8) as ex:
        futs = {ex.submit(_probe_one, j, j["name"]): mid for mid, j in jobs.items()}
        for f in cf.as_completed(futs):
            res[futs[f]] = f.result()
    ok = failed = 0
    for m in ms:
        good, note = res.get(m.id, (True, ""))
        m.available = good
        m.status_note = None if good else note
        if not good:
            m.enabled = False
            failed += 1
        else:
            ok += 1
    db.commit()
    sync_safe(db)
    return {"ok": ok, "failed": failed}


def sync_all(probe: bool = False, force: bool = False) -> dict:
    """Sync every enabled provider with a key and auto_sync on (scheduler + 'Sync all')."""
    if not _lock.acquire(blocking=False):
        return {"ok": False, "error": "A sync is already running"}
    try:
        db = SessionLocal()
        try:
            out = {}
            for p in db.scalars(select(Provider).order_by(Provider.id)).all():
                if p.enabled and p.api_key_enc and (p.auto_sync or force) and p.kind not in SKIP_SYNC:
                    out[p.slug] = sync_provider(db, p, probe=probe)
            m = db.get(Meta, "last_catalog_sync") or Meta(key="last_catalog_sync")
            m.value = utcnow().isoformat()
            db.merge(m)
            db.commit()
            return {"ok": True, "providers": out}
        finally:
            db.close()
    finally:
        _lock.release()


def scheduler_loop():
    """Daily sync. Runs in every worker; a Postgres advisory lock makes only one of them do the work."""
    time.sleep(120)
    while True:
        try:
            with engine.connect() as c:
                got = c.execute(text("SELECT pg_try_advisory_lock(424243)")).scalar()
                if got:
                    try:
                        db = SessionLocal()
                        last = db.get(Meta, "last_catalog_sync")
                        db.close()
                        from datetime import datetime
                        due = not last or not last.value or datetime.fromisoformat(last.value) + SYNC_EVERY < utcnow()
                        if due:
                            log.info("scheduled catalog sync: %s", json.dumps(sync_all(probe=True), default=str)[:500])
                    finally:
                        c.execute(text("SELECT pg_advisory_unlock(424243)"))
                        c.commit()
        except Exception:  # noqa: BLE001
            log.exception("scheduled catalog sync failed")
        time.sleep(3600)


def start_scheduler():
    threading.Thread(target=scheduler_loop, name="catalog-sync", daemon=True).start()

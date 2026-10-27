"""Reconcile the control-plane DB (providers/models/aliases) into LiteLLM's DB-backed model list."""
import hashlib
import json
import logging
import threading

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .catalog import KIND_MODE, PROVIDER_KINDS
from .config import settings
from .db import Alias, Model, Provider
from .security import decrypt

log = logging.getLogger("gateway.sync")
_lock = threading.Lock()


def ll_client(timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(base_url=settings.litellm_url, timeout=timeout,
                        headers={"Authorization": f"Bearer {settings.litellm_master_key}"})


def provider_base(p: Provider) -> str:
    return (p.api_base or PROVIDER_KINDS.get(p.kind, ("", "", False))[1] or "").rstrip("/")


def model_kind(m: Model | None) -> str:
    return (m.kind if m and m.kind in KIND_MODE else "chat")


def build_litellm_params(p: Provider, m: Model) -> dict:
    prefix, default_base, needs_base = PROVIDER_KINDS.get(p.kind, ("openai", "", True))
    kind = model_kind(m)
    base = m.api_base or p.api_base or default_base
    params: dict = {"api_key": decrypt(p.api_key_enc)}
    if kind in ("transcription", "speech"):
        # audio endpoints: every supported provider speaks the OpenAI audio API (/audio/transcriptions, /audio/speech),
        # so route them through LiteLLM's OpenAI client with the provider's base URL (works for Together, Groq, ...)
        params["model"] = f"openai/{m.upstream_id}"
        if base and base.rstrip("/") != "https://api.openai.com/v1":
            params["api_base"] = base
        if kind == "transcription":
            if p.kind != "openai":  # OpenAI's gpt-4o transcribe models bill by audio tokens: LiteLLM's built-in prices
                params["input_cost_per_second"] = (m.price_per_minute or 0) / 60
        else:
            # input_cost_per_token=0 marks the deployment as custom-priced so LiteLLM uses the per-character price
            params["input_cost_per_token"] = 0.0
            params["output_cost_per_token"] = 0.0
            params["input_cost_per_character"] = (m.price_per_m_chars or 0) / 1_000_000
        return params
    params["model"] = f"{prefix}/{m.upstream_id}"
    builtin_audio_pricing = kind in ("realtime", "input") and p.kind == "openai"
    if not builtin_audio_pricing:
        # realtime / audio-chat on OpenAI: LiteLLM's built-in price map has the audio-token prices (custom pricing
        # cannot express them), so no override there; everything else uses the catalog's per-token prices
        params["input_cost_per_token"] = (m.input_price_per_m or 0) / 1_000_000
        params["output_cost_per_token"] = (m.output_price_per_m or 0) / 1_000_000
    if needs_base or m.api_base or (p.api_base and p.api_base.rstrip("/") != default_base.rstrip("/")):
        params["api_base"] = base
    return params


def wildcard_params(p: Provider) -> dict:
    """`<slug>/*` route: any upstream model id works without a catalog entry (LiteLLM wildcard routing)."""
    prefix, default_base, needs_base = PROVIDER_KINDS.get(p.kind, ("openai", "", True))
    params = {"model": f"{prefix}/*", "api_key": decrypt(p.api_key_enc)}
    if needs_base or (p.api_base and p.api_base.rstrip("/") != default_base.rstrip("/")):
        params["api_base"] = p.api_base or default_base
    return params


def is_pipeline(m: Model | None) -> bool:
    return bool(m and m.provider and m.provider.kind == "pipeline")


def deployable(m: Model | None) -> bool:
    """Routable: enabled model on an enabled provider with a key (pipeline models need no key - the gateway serves them)."""
    if is_pipeline(m):
        return bool(m.enabled and m.provider.enabled)
    return bool(m and m.enabled and m.provider and m.provider.enabled and m.provider.api_key_enc)


WILDCARD_KINDS = {"together", "openrouter", "vercel", "groq", "mistral", "deepinfra", "fireworks", "cerebras", "sambanova",
                  "hyperbolic", "nebius", "novita", "baseten", "xai", "deepseek", "openai", "gemini", "anthropic", "zai"}


def desired_state(db: Session) -> dict[str, dict]:
    out: dict[str, dict] = {}
    models = db.scalars(select(Model)).all()
    for m in models:
        if deployable(m) and not is_pipeline(m):
            out[f"gw-m-{m.id}"] = {"model_name": m.model_name, "litellm_params": build_litellm_params(m.provider, m),
                                  "mode": KIND_MODE[model_kind(m)],
                                  "meta": {"provider": m.provider.slug, "kind": "model", "model_db_id": m.id, "audio": model_kind(m)}}
    for p in db.scalars(select(Provider)).all():
        if p.enabled and p.api_key_enc and p.kind in WILDCARD_KINDS:
            out[f"gw-w-{p.id}"] = {"model_name": f"{p.slug}/*", "litellm_params": wildcard_params(p), "mode": "chat",
                                  "meta": {"provider": p.slug, "kind": "wildcard"}}
    for a in db.scalars(select(Alias)).all():
        if deployable(a.target) and not is_pipeline(a.target):
            out[f"gw-a-{a.id}"] = {"model_name": a.name, "litellm_params": build_litellm_params(a.target.provider, a.target),
                                  "mode": KIND_MODE[model_kind(a.target)],
                                  "meta": {"provider": a.target.provider.slug, "kind": "alias", "target": a.target.model_name,
                                           "audio": model_kind(a.target)}}
    for k, v in out.items():
        v["hash"] = hashlib.sha256(json.dumps([v["model_name"], v["litellm_params"], v["mode"]], sort_keys=True).encode()).hexdigest()[:24]
    return out


def current_deployments(c: httpx.Client) -> list[dict]:
    r = c.get("/model/info")
    r.raise_for_status()
    return r.json().get("data", [])


def sync(db: Session) -> dict:
    with _lock:
        want = desired_state(db)
        added, removed, kept = [], [], []
        with ll_client() as c:
            have: dict[str, list] = {}
            seen_ids = set()
            for d in current_deployments(c):
                info = d.get("model_info") or {}
                gw_id = info.get("gw_id")
                # LiteLLM lists a wildcard deployment once per known model; keep one entry per deployment id
                if not gw_id or info.get("id") in seen_ids:
                    continue
                seen_ids.add(info.get("id"))
                have.setdefault(gw_id, []).append(d)
            for gw_id, deps in have.items():
                for i, d in enumerate(deps):
                    info = d["model_info"]
                    w = want.get(gw_id)
                    if w is None or info.get("gw_hash") != w["hash"] or i > 0:
                        r = c.post("/model/delete", json={"id": info["id"]})
                        if r.status_code >= 400:
                            log.warning("delete %s failed: %s", info["id"], r.text[:300])
                        removed.append(d.get("model_name"))
                    else:
                        kept.append(gw_id)
            for gw_id, w in want.items():
                if gw_id in kept:
                    continue
                body = {"model_name": w["model_name"], "litellm_params": w["litellm_params"],
                        "model_info": {"id": gw_id, "gw_id": gw_id, "gw_hash": w["hash"], "mode": w["mode"],
                                       **{f"gw_{k}": v for k, v in w["meta"].items()}}}
                r = c.post("/model/new", json=body)
                if r.status_code >= 400:
                    log.error("add %s failed: %s", w["model_name"], r.text[:500])
                    raise RuntimeError(f"LiteLLM rejected model {w['model_name']}: {r.text[:300]}")
                added.append(w["model_name"])
        return {"added": added, "removed": removed, "unchanged": len(kept)}


def sync_safe(db: Session) -> dict:
    try:
        return {"ok": True, **sync(db)}
    except Exception as e:  # noqa: BLE001
        log.exception("sync failed")
        return {"ok": False, "error": str(e)}

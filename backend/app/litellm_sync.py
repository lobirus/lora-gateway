"""Reconcile the control-plane DB (providers/models/aliases) into LiteLLM's DB-backed model list."""
import hashlib
import json
import logging
import threading

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .catalog import PROVIDER_KINDS
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


def build_litellm_params(p: Provider, m: Model) -> dict:
    prefix, default_base, needs_base = PROVIDER_KINDS.get(p.kind, ("openai", "", True))
    params = {
        "model": f"{prefix}/{m.upstream_id}",
        "api_key": decrypt(p.api_key_enc),
        "input_cost_per_token": (m.input_price_per_m or 0) / 1_000_000,
        "output_cost_per_token": (m.output_price_per_m or 0) / 1_000_000,
    }
    base = p.api_base or default_base
    if needs_base or (p.api_base and p.api_base.rstrip("/") != default_base.rstrip("/")):
        params["api_base"] = base
    return params


def deployable(m: Model | None) -> bool:
    return bool(m and m.enabled and m.provider and m.provider.enabled and m.provider.api_key_enc)


def desired_state(db: Session) -> dict[str, dict]:
    out: dict[str, dict] = {}
    models = db.scalars(select(Model)).all()
    for m in models:
        if deployable(m):
            out[f"gw-m-{m.id}"] = {"model_name": m.model_name, "litellm_params": build_litellm_params(m.provider, m),
                                  "meta": {"provider": m.provider.slug, "kind": "model", "model_db_id": m.id}}
    for a in db.scalars(select(Alias)).all():
        if deployable(a.target):
            out[f"gw-a-{a.id}"] = {"model_name": a.name, "litellm_params": build_litellm_params(a.target.provider, a.target),
                                  "meta": {"provider": a.target.provider.slug, "kind": "alias", "target": a.target.model_name}}
    for k, v in out.items():
        v["hash"] = hashlib.sha256(json.dumps([v["model_name"], v["litellm_params"]], sort_keys=True).encode()).hexdigest()[:24]
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
            have = {}
            for d in current_deployments(c):
                info = d.get("model_info") or {}
                gw_id = info.get("gw_id")
                if not gw_id:
                    continue
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
                        "model_info": {"id": gw_id, "gw_id": gw_id, "gw_hash": w["hash"], **{f"gw_{k}": v for k, v in w["meta"].items()}}}
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

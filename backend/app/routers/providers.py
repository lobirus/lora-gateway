import re
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..catalog import PROVIDER_KINDS
from ..db import Provider, User, get_db, utcnow
from ..litellm_sync import provider_base, sync_safe
from ..schemas import ProviderIn, ProviderPatch
from ..security import current_user, decrypt, encrypt, mask

router = APIRouter(prefix="/api/providers", tags=["providers"])


def provider_out(p: Provider) -> dict:
    key = decrypt(p.api_key_enc)
    return {
        "id": p.id, "slug": p.slug, "name": p.name, "kind": p.kind, "api_base": provider_base(p),
        "enabled": p.enabled, "description": p.description, "has_key": bool(key), "key_masked": mask(key),
        "last_test_at": p.last_test_at, "last_test_ok": p.last_test_ok, "last_test_msg": p.last_test_msg,
        "model_count": len(p.models), "enabled_model_count": sum(1 for m in p.models if m.enabled),
        "status": ("active" if p.enabled and key else "missing_key" if p.enabled else "disabled"),
    }


@router.get("")
def list_providers(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [provider_out(p) for p in db.scalars(select(Provider).order_by(Provider.id)).all()]


@router.get("/kinds")
def kinds(_: User = Depends(current_user)):
    return [{"kind": k, "litellm_prefix": v[0], "default_api_base": v[1]} for k, v in PROVIDER_KINDS.items()]


@router.post("")
def create_provider(body: ProviderIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    if body.kind not in PROVIDER_KINDS:
        raise HTTPException(400, f"Unknown kind {body.kind}")
    slug = (body.slug or re.sub(r"[^a-z0-9]+", "-", body.name.lower())).strip("-")
    if db.scalar(select(Provider).where(Provider.slug == slug)):
        raise HTTPException(409, "Provider slug already exists")
    if body.kind == "openai_compatible" and not body.api_base:
        raise HTTPException(400, "api_base is required for OpenAI-compatible providers")
    p = Provider(slug=slug, name=body.name, kind=body.kind, api_base=body.api_base or None,
                 api_key_enc=encrypt(body.api_key), enabled=body.enabled, description=body.description)
    db.add(p)
    db.commit()
    db.refresh(p)
    s = sync_safe(db)
    return {"provider": provider_out(p), "sync": s}


@router.patch("/{pid}")
def update_provider(pid: int, body: ProviderPatch, db: Session = Depends(get_db), _: User = Depends(current_user)):
    p = db.get(Provider, pid)
    if not p:
        raise HTTPException(404, "Provider not found")
    if body.name is not None:
        p.name = body.name
    if body.api_base is not None:
        p.api_base = body.api_base or None
    if body.api_key is not None:
        p.api_key_enc = encrypt(body.api_key.strip()) if body.api_key.strip() else None
        p.last_test_ok = None
    if body.enabled is not None:
        p.enabled = body.enabled
    if body.description is not None:
        p.description = body.description
    db.commit()
    db.refresh(p)
    s = sync_safe(db)
    return {"provider": provider_out(p), "sync": s}


@router.delete("/{pid}")
def delete_provider(pid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    p = db.get(Provider, pid)
    if not p:
        raise HTTPException(404, "Provider not found")
    db.delete(p)
    db.commit()
    return {"ok": True, "sync": sync_safe(db)}


def _probe(p: Provider) -> tuple[bool, str, list[dict]]:
    key = decrypt(p.api_key_enc)
    if not key:
        return False, "No API key configured", []
    base = provider_base(p)
    headers = {"Authorization": f"Bearer {key}"}
    url = f"{base}/models"
    if p.kind == "anthropic":
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        url = f"{base}/v1/models"
    if p.kind == "openrouter":
        url = f"{base}/key"
    t0 = time.perf_counter()
    try:
        r = httpx.get(url, headers=headers, timeout=20)
    except httpx.HTTPError as e:
        return False, f"Connection error: {e}", []
    ms = int((time.perf_counter() - t0) * 1000)
    if r.status_code in (401, 403):
        return False, f"Authentication failed (HTTP {r.status_code})", []
    if r.status_code >= 400:
        return False, f"HTTP {r.status_code}: {r.text[:200]}", []
    models = []
    try:
        data = r.json()
        items = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict) and it.get("id"):
                    pr = it.get("pricing") or {}
                    models.append({"id": it["id"], "name": it.get("display_name") or it.get("name") or it["id"],
                                   "type": it.get("type"), "context_length": it.get("context_length"),
                                   "input_price_per_m": pr.get("input") if isinstance(pr.get("input"), (int, float)) else None,
                                   "output_price_per_m": pr.get("output") if isinstance(pr.get("output"), (int, float)) else None})
    except Exception:  # noqa: BLE001
        pass
    return True, f"OK in {ms} ms" + (f" - {len(models)} upstream models" if models else ""), models


@router.post("/{pid}/test")
def test_provider(pid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    p = db.get(Provider, pid)
    if not p:
        raise HTTPException(404, "Provider not found")
    ok, msg, _models = _probe(p)
    p.last_test_at, p.last_test_ok, p.last_test_msg = utcnow(), ok, msg
    db.commit()
    return {"ok": ok, "message": msg}


@router.get("/{pid}/upstream-models")
def upstream_models(pid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    p = db.get(Provider, pid)
    if not p:
        raise HTTPException(404, "Provider not found")
    ok, msg, models = _probe(p)
    if not ok:
        raise HTTPException(400, msg)
    return sorted(models, key=lambda m: m["id"])

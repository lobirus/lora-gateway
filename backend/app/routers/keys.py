from datetime import timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..db import ApiKey, User, get_db, ll_engine, utcnow
from ..litellm_sync import ll_client
from ..schemas import KeyIn, KeyPatch
from ..security import current_user, decrypt, encrypt, sha256_hex

router = APIRouter(prefix="/api/keys", tags=["keys"])


def _spend_by_token() -> dict:
    try:
        with ll_engine.connect() as c:
            rows = c.execute(text('SELECT token, spend, budget_reset_at FROM "LiteLLM_VerificationToken"')).all()
        return {r[0]: {"spend": r[1] or 0.0, "budget_reset_at": r[2]} for r in rows}
    except Exception:  # noqa: BLE001
        return {}


def _usage_by_token() -> dict:
    try:
        with ll_engine.connect() as c:
            rows = c.execute(text('''SELECT api_key, count(*), max("startTime"), coalesce(sum(total_tokens),0)
                                     FROM "LiteLLM_SpendLogs" GROUP BY api_key''')).all()
        return {r[0]: {"requests": r[1], "last_used_at": r[2], "tokens": r[3]} for r in rows}
    except Exception:  # noqa: BLE001
        return {}


def key_out(k: ApiKey, spend: dict | None = None, usage: dict | None = None, reveal: bool = False) -> dict:
    s = (spend or {}).get(k.token_hash, {})
    u = (usage or {}).get(k.token_hash, {})
    return {
        "id": k.id, "name": k.name, "key_prefix": k.key_prefix, "max_budget": k.max_budget,
        "budget_duration": k.budget_duration, "rpm_limit": k.rpm_limit, "tpm_limit": k.tpm_limit,
        "models": k.models or [], "expires_at": k.expires_at, "revoked": k.revoked, "revoked_at": k.revoked_at,
        "created_at": k.created_at, "spend": s.get("spend", 0.0), "budget_reset_at": s.get("budget_reset_at"),
        "requests": u.get("requests", 0), "tokens": u.get("tokens", 0), "last_used_at": u.get("last_used_at"),
        **({"key": decrypt(k.key_enc)} if reveal else {}),
    }


@router.get("")
def list_keys(db: Session = Depends(get_db), _: User = Depends(current_user)):
    spend, usage = _spend_by_token(), _usage_by_token()
    return [key_out(k, spend, usage) for k in db.scalars(select(ApiKey).order_by(ApiKey.revoked, ApiKey.id.desc())).all()]


def create_key(db: Session, body: KeyIn) -> ApiKey:
    if db.scalar(select(ApiKey).where(ApiKey.name == body.name)):
        raise HTTPException(409, "A key with this name already exists")
    req = {"key_alias": body.name, "metadata": {"created_by": "gateway-ui"}}
    if body.max_budget is not None:
        req["max_budget"] = body.max_budget
    if body.budget_duration:
        req["budget_duration"] = body.budget_duration
    if body.rpm_limit:
        req["rpm_limit"] = body.rpm_limit
    if body.tpm_limit:
        req["tpm_limit"] = body.tpm_limit
    if body.models:
        req["models"] = body.models
    if body.expires_days:
        req["duration"] = f"{body.expires_days}d"
    with ll_client() as c:
        r = c.post("/key/generate", json=req)
    if r.status_code >= 400:
        raise HTTPException(502, f"LiteLLM key generation failed: {r.text[:300]}")
    raw = r.json()["key"]
    k = ApiKey(name=body.name, key_enc=encrypt(raw), key_prefix=raw[:8] + "…" + raw[-4:], token_hash=sha256_hex(raw),
               max_budget=body.max_budget, budget_duration=body.budget_duration, rpm_limit=body.rpm_limit,
               tpm_limit=body.tpm_limit, models=body.models or [],
               expires_at=(utcnow() + timedelta(days=body.expires_days)) if body.expires_days else None)
    db.add(k)
    db.commit()
    db.refresh(k)
    return k


@router.post("")
def create(body: KeyIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    k = create_key(db, body)
    return key_out(k, reveal=True)


@router.get("/{kid}/reveal")
def reveal(kid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    k = db.get(ApiKey, kid)
    if not k:
        raise HTTPException(404, "Key not found")
    return {"key": decrypt(k.key_enc)}


@router.patch("/{kid}")
def update(kid: int, body: KeyPatch, db: Session = Depends(get_db), _: User = Depends(current_user)):
    k = db.get(ApiKey, kid)
    if not k or k.revoked:
        raise HTTPException(404, "Key not found")
    raw = decrypt(k.key_enc)
    req = {"key": raw}
    data = body.model_dump(exclude_unset=True)
    if body.clear_budget:
        req["max_budget"] = None
        k.max_budget = None
    for f in ("max_budget", "budget_duration", "rpm_limit", "tpm_limit", "models"):
        if f in data and not (f == "max_budget" and body.clear_budget):
            req[f] = data[f]
            setattr(k, f, data[f])
    with ll_client() as c:
        r = c.post("/key/update", json=req)
    if r.status_code >= 400:
        raise HTTPException(502, f"LiteLLM key update failed: {r.text[:300]}")
    db.commit()
    return key_out(k)


@router.delete("/{kid}")
def revoke(kid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    k = db.get(ApiKey, kid)
    if not k:
        raise HTTPException(404, "Key not found")
    if not k.revoked:
        with ll_client() as c:
            r = c.post("/key/delete", json={"keys": [decrypt(k.key_enc)]})
        if r.status_code >= 400 and "not found" not in r.text.lower():
            raise HTTPException(502, f"LiteLLM key delete failed: {r.text[:300]}")
        k.revoked = True
        k.revoked_at = utcnow()
        db.commit()
    return {"ok": True}

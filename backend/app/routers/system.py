import time

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..config import settings
from ..db import Alias, ApiKey, Model, Provider, User, engine, get_db, ll_engine
from ..litellm_sync import deployable, ll_client
from ..security import current_user

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health/live")
def live():
    return {"ok": True}


@router.get("/health")
def health():
    out = {"backend": {"ok": True}}
    for name, eng in (("gateway_db", engine), ("litellm_db", ll_engine)):
        t0 = time.perf_counter()
        try:
            with eng.connect() as c:
                c.execute(text("SELECT 1"))
            out[name] = {"ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
        except Exception as e:  # noqa: BLE001
            out[name] = {"ok": False, "error": str(e)[:200]}
    t0 = time.perf_counter()
    try:
        r = httpx.get(f"{settings.litellm_url}/health/readiness", timeout=5)
        j = r.json()
        out["litellm"] = {"ok": r.status_code == 200, "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                          "version": j.get("litellm_version"), "db": j.get("db"), "cache": j.get("cache")}
    except Exception as e:  # noqa: BLE001
        out["litellm"] = {"ok": False, "error": str(e)[:200]}
    out["ok"] = all(v.get("ok") for v in out.values() if isinstance(v, dict))
    return out


@router.get("/overview")
def overview(db: Session = Depends(get_db), _: User = Depends(current_user)):
    providers = db.scalars(select(Provider)).all()
    models = db.scalars(select(Model)).all()
    aliases = db.scalars(select(Alias)).all()
    keys = db.scalars(select(ApiKey).where(ApiKey.revoked.is_(False))).all()
    live_names = []
    try:
        with ll_client(10) as c:
            r = c.get("/model/info")
            live_names = sorted({d["model_name"] for d in r.json().get("data", [])})
    except Exception:  # noqa: BLE001
        pass
    return {
        "providers_total": len(providers), "providers_active": sum(1 for p in providers if p.enabled and p.api_key_enc),
        "models_total": len(models), "models_live": sum(1 for m in models if deployable(m)),
        "aliases": len(aliases), "keys_active": len(keys), "litellm_model_names": live_names,
    }


@router.get("/connect")
def connect_info(request_host: str | None = None, _: User = Depends(current_user), db: Session = Depends(get_db)):
    host = settings.public_host
    # pinned models only (the synced catalog can hold hundreds; clients discover those via /v1/models)
    models = [m.model_name for m in db.scalars(select(Model)).all() if deployable(m) and m.pinned and (m.kind or "chat") in ("chat", "input")]
    aliases = [a.name for a in db.scalars(select(Alias)).all() if deployable(a.target)]
    return {
        "public_host": host,
        "openai_base_url": f"https://{host}/v1",
        "anthropic_base_url": f"https://{host}",
        "local_openai_base_url": "http://127.0.0.1:4000/v1",
        "local_anthropic_base_url": "http://127.0.0.1:4000",
        "models": models, "aliases": aliases,
    }

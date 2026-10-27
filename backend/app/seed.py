import logging
import secrets
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from .catalog import CATALOG, CATALOG_VERSION, DEFAULT_ALIASES
from .config import PLACEHOLDER_VALUES, settings
from .db import Alias, ApiKey, Meta, Model, Provider, SessionLocal, User
from .litellm_sync import sync_safe
from .schemas import KeyIn
from .security import encrypt, hash_password

log = logging.getLogger("gateway.seed")


def _catalog_version(db: Session) -> int:
    m = db.get(Meta, "catalog_version")
    return int(m.value) if m and m.value else 0


def seed_catalog(db: Session):
    fresh = not db.scalar(select(Provider))
    upgrade = not fresh and _catalog_version(db) < CATALOG_VERSION
    for p in CATALOG:
        existing = db.scalar(select(Provider).where(Provider.slug == p["slug"]))
        if existing:
            if upgrade:  # one-time: add catalog models this install does not have yet (never re-adds deleted ones later)
                n = 0
                for m in p["models"]:
                    if not db.scalar(select(Model).where(Model.model_name == m["model_name"])):
                        db.add(Model(provider_id=existing.id, **m))
                        n += 1
                if n:
                    log.info("catalog upgrade: added %d models to %s", n, p["slug"])
            continue
        key = settings.seed_together_key if p["slug"] == "together" else None
        prov = Provider(slug=p["slug"], name=p["name"], kind=p["kind"], api_base=p.get("api_base"),
                        api_key_enc=encrypt(key), enabled=p["enabled"] and (bool(key) or p["kind"] == "pipeline"),
                        description=p.get("description"))
        db.add(prov)
        db.flush()
        for m in p["models"]:
            if not db.scalar(select(Model).where(Model.model_name == m["model_name"])):
                db.add(Model(provider_id=prov.id, **m))
        log.info("seeded provider %s", p["slug"])
    db.flush()
    for name, target, desc in (DEFAULT_ALIASES if fresh or upgrade else []):
        if db.scalar(select(Alias).where(Alias.name == name)):
            continue
        m = db.scalar(select(Model).where(Model.model_name == target))
        db.add(Alias(name=name, target_model_id=m.id if m else None, description=desc))
    meta = db.get(Meta, "catalog_version") or Meta(key="catalog_version")
    meta.value = str(CATALOG_VERSION)
    db.merge(meta)
    db.commit()


CAP_FIELDS = ("max_output_tokens", "default_max_tokens", "supports_reasoning", "supports_vision", "reasoning_efforts",
              "voices", "default_voice", "price_per_minute", "price_per_m_chars", "audio_input_price_per_m",
              "audio_output_price_per_m")


def backfill_capabilities(db: Session):
    """Fill capability columns that are still NULL from the catalog (existing installs; never overwrites edits)."""
    n = 0
    for p in CATALOG:
        for spec in p["models"]:
            m = db.scalar(select(Model).where(Model.model_name == spec["model_name"]))
            if not m or m.upstream_id != spec["upstream_id"]:
                continue
            for f in CAP_FIELDS:
                if f in spec and getattr(m, f) is None:
                    setattr(m, f, spec[f])
                    n += 1
    if n:
        db.commit()
        log.info("backfilled %d model capability fields", n)


def seed_admin(db: Session):
    """Create the first admin account, only when the user table is empty.

    The password comes from ADMIN_PASSWORD. If it is unset (or still a placeholder), a random password is
    generated and printed once to the backend log. It is never stored anywhere in plain text.
    """
    if db.scalar(select(User)):
        return
    uname = (settings.admin_username or "admin").strip().lower() or "admin"
    password = settings.admin_password
    generated = not password or password.lower() in PLACEHOLDER_VALUES
    if generated:
        password = secrets.token_urlsafe(18)
    elif len(password) < 10:
        raise RuntimeError("ADMIN_PASSWORD must be at least 10 characters (or leave it empty to generate one)")
    db.add(User(username=uname, password_hash=hash_password(password), is_admin=True))
    db.commit()
    if generated:
        banner = "=" * 72
        # printed exactly once, on the very first start; change it in Settings after logging in
        print(f"\n{banner}\n  Lora Gateway: created admin user '{uname}'\n  Generated password: {password}\n"
              f"  This is shown only once. Log in and change it under Settings.\n{banner}\n", flush=True)
    else:
        log.info("created admin user %s (password from ADMIN_PASSWORD)", uname)


def seed_all():
    db = SessionLocal()
    try:
        seed_admin(db)
        seed_catalog(db)
        backfill_capabilities(db)
        for attempt in range(30):
            res = sync_safe(db)
            if res.get("ok"):
                log.info("initial sync: %s", res)
                break
            time.sleep(3)
        if not db.scalar(select(ApiKey)):
            from .routers.keys import create_key
            try:
                create_key(db, KeyIn(name="default"))
                log.info("created default virtual key 'default'")
            except Exception:  # noqa: BLE001
                log.exception("could not create default key")
        try:  # internal virtual key used by the console Playground (requests count against it)
            from .routers.playground import ensure_playground_key
            ensure_playground_key(db)
        except Exception:  # noqa: BLE001
            log.exception("could not create playground key")
    finally:
        db.close()

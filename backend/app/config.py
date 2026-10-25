import os

# Values that must never be used as real secrets (copied straight from .env.example).
PLACEHOLDER_VALUES = {"", "change-me", "changeme", "sk-change-me", "secret", "password"}


def _secret(name: str, min_len: int = 16) -> str:
    """Read a required secret; refuse to start with a missing, placeholder or too-short value."""
    v = os.environ.get(name, "").strip()
    if v.lower() in PLACEHOLDER_VALUES or "change-me" in v.lower() or len(v) < min_len:
        raise RuntimeError(f"{name} is missing, a placeholder or shorter than {min_len} characters. "
                           f"Generate one (see .env.example / scripts/generate-secrets.sh).")
    return v


def _db_url(name: str) -> str:
    v = os.environ[name]
    if ":change-me@" in v:
        raise RuntimeError(f"{name} uses the placeholder Postgres password; set POSTGRES_PASSWORD in .env.")
    return v


class Settings:
    gateway_db_url = _db_url("GATEWAY_DB_URL")
    litellm_db_url = _db_url("LITELLM_DB_URL")
    litellm_url = os.environ.get("LITELLM_URL", "http://litellm:4000").rstrip("/")
    litellm_master_key = _secret("LITELLM_MASTER_KEY")
    jwt_secret = _secret("JWT_SECRET", 32)
    encryption_key = _secret("ENCRYPTION_KEY", 32)
    admin_username = os.environ.get("ADMIN_USERNAME", "admin") or "admin"
    admin_password = os.environ.get("ADMIN_PASSWORD", "")
    seed_together_key = os.environ.get("SEED_TOGETHER_API_KEY", "")
    public_host = os.environ.get("PUBLIC_HOST", "localhost")
    jwt_ttl_hours = int(os.environ.get("JWT_TTL_HOURS", "24"))


settings = Settings()

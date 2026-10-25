import base64
import hashlib
import time
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .db import User, get_db

_fernet = Fernet(settings.encryption_key.encode() if len(settings.encryption_key) == 44
                 else base64.urlsafe_b64encode(hashlib.sha256(settings.encryption_key.encode()).digest()))


def encrypt(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet.decrypt(value.encode()).decode()


def mask(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 10:
        return "••••"
    return f"{value[:6]}••••{value[-4:]}"


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def create_token(user: User) -> tuple[str, int]:
    exp = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_ttl_hours)
    payload = {"sub": str(user.id), "usr": user.username, "adm": user.is_admin, "exp": exp, "iat": int(time.time())}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256"), int(exp.timestamp())


_bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)) -> User:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    user = db.get(User, int(payload["sub"]))
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


# --- simple in-memory login throttling (per process) ---
_failures: dict[str, list[float]] = {}


def check_throttle(key: str):
    now = time.time()
    hits = [t for t in _failures.get(key, []) if now - t < 300]
    _failures[key] = hits
    if len(hits) >= 10:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed logins, try again in a few minutes")


def record_failure(key: str):
    _failures.setdefault(key, []).append(time.time())


def sha256_hex(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()

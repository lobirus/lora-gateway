from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import User, get_db, utcnow
from ..schemas import LoginIn, PasswordChangeIn
from ..security import (check_throttle, create_token, current_user, hash_password, record_failure,
                        verify_password)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    # Caddy appends the real client address as the last X-Forwarded-For hop; earlier hops are client-controlled.
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[-1].strip()
    check_throttle(ip)
    user = db.scalar(select(User).where(User.username == body.username.strip().lower()))
    if not user or not verify_password(body.password, user.password_hash):
        record_failure(ip)
        raise HTTPException(401, "Invalid username or password")
    user.last_login_at = utcnow()
    db.commit()
    token, exp = create_token(user)
    return {"access_token": token, "token_type": "bearer", "expires_at": exp,
            "user": {"id": user.id, "username": user.username, "is_admin": user.is_admin}}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "username": user.username, "is_admin": user.is_admin,
            "last_login_at": user.last_login_at}


@router.post("/password")
def change_password(body: PasswordChangeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    u = db.get(User, user.id)
    u.password_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True}

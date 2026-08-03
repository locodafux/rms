from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User, utcnow
from app.schemas import RefreshRequest, RegisterRequest, TokenResponse, UserOut
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

import os

router = APIRouter(prefix="/api/auth", tags=["auth"])
# Disabled under pytest so repeated logins in tests don't trip the limit.
limiter = Limiter(key_func=get_remote_address, enabled=os.getenv("DISABLE_RATE_LIMIT") != "1")


@router.post("/register", response_model=UserOut, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.execute(
        select(User).where(func.lower(User.email) == payload.email.lower())
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, detail="Email already registered.")
    # New accounts start INACTIVE and ROLELESS until an admin approves.
    user = User(
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=None,
        is_active=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.execute(
        select(User).where(func.lower(User.email) == form.username.lower())
    ).scalar_one_or_none()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(401, detail="Incorrect email or password.")
    if not user.is_active:
        raise HTTPException(403, detail="Account not yet activated by an admin.")
    user.last_login = user.last_seen = utcnow()
    db.commit()
    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    subject = decode_token(payload.refresh_token, "refresh")
    if subject is None:
        raise HTTPException(401, detail="Invalid refresh token.")
    user = db.get(User, int(subject))
    if not user or not user.is_active:
        raise HTTPException(401, detail="Invalid refresh token.")
    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user

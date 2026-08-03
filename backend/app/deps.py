from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.fields import Role
from app.models import User, as_utc, utcnow
from app.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    creds_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    subject = decode_token(token, "access")
    if subject is None:
        raise creds_error
    user = db.get(User, int(subject))
    if user is None:
        raise creds_error
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive.")
    # Presence heartbeat: this is the one place every authenticated request passes
    # through. ponytail: 60s throttle keeps it at ~1 UPDATE/user/min; move to Redis
    # or a real sessions table if this write ever shows up in latency.
    now = utcnow()
    seen = as_utc(user.last_seen)
    if seen is None or (now - seen).total_seconds() > 60:
        user.last_seen = now
        db.commit()
    return user


def current_role(user: User = Depends(get_current_user)) -> Role:
    if not user.role:
        raise HTTPException(status_code=403, detail="No role assigned to this account.")
    return Role(user.role)


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.admin.value:
        raise HTTPException(status_code=403, detail="Admin only.")
    return user

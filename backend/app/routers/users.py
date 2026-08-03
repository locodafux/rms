from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_admin
from app.models import User
from app.schemas import UserOut, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    return db.execute(select(User).order_by(User.created_at.desc())).scalars().all()


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, detail="User not found.")
    if payload.role is not None:
        user.role = payload.role.value
    if payload.is_active is not None:
        # Guard against an admin deactivating themselves and locking everyone out.
        if user.id == admin.id and payload.is_active is False:
            raise HTTPException(400, detail="You cannot deactivate your own account.")
        user.is_active = payload.is_active
    db.commit()
    db.refresh(user)
    return user

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import current_role, get_current_user
from app.fields import FIELDS, Role, keys_for_owner
from app.models import Record, User, as_utc, utcnow
from app.rbac import (
    ARCHIVE_DASHBOARD_ROLES,
    CREATE_ROLES,
    creatable_fields,
    editable_fields,
)
from app.schemas import OnlineUser
from app.stats import compute_stats

router = APIRouter(prefix="/api/meta", tags=["meta"])

# How long after their last request a user still counts as online. Tune here.
ONLINE_WINDOW_MINUTES = 5


@router.get("/stats")
def get_stats(
    db: Session = Depends(get_db),
    role: Role = Depends(current_role),
    _user: User = Depends(get_current_user),
    include_archived: bool = False,
):
    """Per-role workload summary (done / incoming / pending + percentages)."""
    stmt = select(Record)
    if not include_archived:
        stmt = stmt.where(Record.is_archived.is_(False))
    records = db.execute(stmt).scalars().all()
    result = compute_stats(records)
    if role not in ARCHIVE_DASHBOARD_ROLES:
        result["soon_to_archive"] = []
    return result


@router.get("/online", response_model=list[OnlineUser])
def get_online(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    """Who's active right now. Auth is stateless JWT, so there is no such thing as
    "logged in" server-side — this is last-activity presence, refreshed by the
    heartbeat in deps.get_current_user. Any role may call it; deliberately narrower
    than UserOut (no email, no account status) since it isn't admin-gated.
    """
    cutoff = utcnow() - timedelta(minutes=ONLINE_WINDOW_MINUTES)
    users = (
        db.execute(
            select(User)
            .where(User.is_active.is_(True), User.last_seen.is_not(None), User.last_seen >= cutoff)
            .order_by(User.last_seen.desc())
        )
        .scalars()
        .all()
    )
    return [
        OnlineUser(id=u.id, full_name=u.full_name, role=u.role, last_seen=as_utc(u.last_seen))
        for u in users
    ]


@router.get("/schema")
def get_schema(
    db: Session = Depends(get_db),
    role: Role = Depends(current_role),
    _user: User = Depends(get_current_user),
):
    """Field registry + the caller's own editable/creatable keys, so the UI can
    render forms and disable fields to match the server allow-list exactly.

    Every role sees every field; only `editable` varies by role.
    """
    editable = editable_fields(db, role)
    creatable = creatable_fields(role)
    # Same rule the write path enforces: a role must complete its own section
    # before saving. Admin owns everything and is exempt.
    required = frozenset() if role == Role.admin else keys_for_owner(role)
    fields = [
        {
            "key": f.key,
            "label": f.label,
            "section": f.section,
            "owner": f.owner if isinstance(f.owner, str) else f.owner.value,
            "type": f.type.value,
            "options": list(f.options),
            "editable": f.key in editable,
            "creatable": f.key in creatable,
            "required": f.key in required,
        }
        for f in FIELDS
    ]
    return {
        "role": role.value,
        "can_create": role in CREATE_ROLES,
        "can_import": role == Role.admin,
        "can_export": role == Role.admin,
        "can_manage_users": role == Role.admin,
        "fields": fields,
    }

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import current_role, get_current_user
from app.fields import Role
from app.models import Record, RecordEvent, User
from app.rbac import visible_fields
from app.schemas import HistoryItem, HistoryPage

router = APIRouter(prefix="/api/history", tags=["history"])

# The window the page opens on. Longer views are a query param away, but the
# default keeps the common case (what happened lately) off a 24k-row scan.
DEFAULT_DAYS = 90


@router.get("", response_model=HistoryPage)
def list_history(
    db: Session = Depends(get_db),
    role: Role = Depends(current_role),
    _user: User = Depends(get_current_user),
    search: str | None = None,
    days: int = Query(DEFAULT_DAYS, ge=0),  # 0 = all time
    kind: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """Imported filing / pullout / scanning events across every record.

    Read-scoped per record like the record list itself: a role that hasn't
    worked a unit sees only base + its own section, and the search matches only
    what the caller can already read — otherwise a probe would leak the rest.
    """
    stmt = select(RecordEvent, Record).join(Record, RecordEvent.record_id == Record.id)
    if days:
        # Undated events have no place in a date window; they surface at days=0.
        stmt = stmt.where(RecordEvent.event_date >= date.today() - timedelta(days=days))
    if kind:
        stmt = stmt.where(RecordEvent.kind == kind)
    stmt = stmt.order_by(
        RecordEvent.event_date.desc().nullslast(), RecordEvent.id.desc()
    )

    needle = (search or "").strip().lower()
    items: list[HistoryItem] = []
    for ev, record in db.execute(stmt).all():
        vis = visible_fields(role, record.data)
        data = {k: v for k, v in (ev.data or {}).items() if k in vis}
        if needle:
            hay = " ".join(
                [record.unit_code, ev.kind, str(ev.event_date or "")]
                + [str(v) for v in data.values()]
            ).lower()
            if needle not in hay:
                continue
        items.append(
            HistoryItem(
                id=ev.id,
                record_id=ev.record_id,
                unit_code=record.unit_code,
                kind=ev.kind,
                event_date=ev.event_date,
                data=data,
                source_job_id=ev.source_job_id,
            )
        )

    start = (page - 1) * page_size
    return HistoryPage(
        items=items[start : start + page_size],
        total=len(items),
        page=page,
        page_size=page_size,
    )

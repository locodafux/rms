from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import apply_changes
from app.database import get_db
from app.deps import current_role, get_current_user
from app.fields import ALL_KEYS, Role
from app.models import AuditLog, Record, RecordEvent, User
from app.rbac import (
    assert_can_archive,
    assert_can_create,
    assert_fields_allowed,
    assert_own_section_complete,
    visible_fields,
)
from app.schemas import (
    AuditOut,
    RecordCreate,
    RecordEventOut,
    RecordOut,
    RecordPage,
    RecordPatch,
)
from app.validation import validate_values

router = APIRouter(prefix="/api/records", tags=["records"])


def _out(record: Record, role: Role) -> RecordOut:
    """Serialize a record with the columns this role may not read stripped out."""
    out = RecordOut.model_validate(record)
    vis = visible_fields(role, record.data)
    out.data = {k: v for k, v in out.data.items() if k in vis}
    out.restricted = vis != ALL_KEYS
    return out


def _matches_filters(
    record: Record, search: str | None, filters: dict[str, str], role: Role
) -> bool:
    # Per record: a record this role has worked on is fully readable, a new one
    # is not. Matching on a value the caller can't read would leak it by probing.
    visible = visible_fields(role, record.data)
    if search:
        needle = search.lower()
        haystack = record.unit_code.lower() + " " + " ".join(
            str(v).lower()
            for k, v in (record.data or {}).items()
            if v is not None and k in visible
        )
        if needle not in haystack:
            return False
    for key, val in filters.items():
        cell = record.data.get(key) if record.data else None
        if key == "unit_code":
            cell = record.unit_code
        elif key not in visible:
            cell = None
        if cell is None or val.lower() not in str(cell).lower():
            return False
    return True


@router.get("", response_model=RecordPage)
def list_records(
    db: Session = Depends(get_db),
    role: Role = Depends(current_role),
    _user: User = Depends(get_current_user),
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    include_archived: bool = False,
    filter: list[str] = Query(default=[]),  # each "key:value"
    sort: str | None = None,   # field key or "unit_code"
    order: str = "asc",        # "asc" | "desc"
):
    """List records — every role reads every record. Columns are scoped per
    record: full access to the ones it has worked on, own section + base identity
    on the ones it hasn't (see rbac.visible_fields).

    Filtering/sorting is done in Python for portability; adequate for the v1
    small-team scale. Swap to SQL/JSONB predicates when the dataset grows.
    """
    filters: dict[str, str] = {}
    for raw in filter:
        if ":" in raw:
            k, v = raw.split(":", 1)
            if k in ALL_KEYS or k == "unit_code":
                filters[k] = v

    stmt = select(Record)
    if not include_archived:
        stmt = stmt.where(Record.is_archived.is_(False))
    all_records = db.execute(stmt).scalars().all()

    matched = [r for r in all_records if _matches_filters(r, search, filters, role)]

    # Sort across the whole result set so pagination stays correct.
    if sort and (sort in ALL_KEYS or sort == "unit_code"):
        def key_fn(r: Record):
            if sort == "unit_code":
                val = r.unit_code
            elif sort in visible_fields(role, r.data):
                val = (r.data or {}).get(sort)
            else:
                val = None  # sorts with the blanks; never reveals the hidden value
            # (has_value, lowercased string) keeps blanks last and sorts naturally.
            return (val is None or val == "", str(val).lower() if val is not None else "")
        matched.sort(key=key_fn, reverse=(order == "desc"))
    else:
        matched.sort(key=lambda r: r.updated_at, reverse=True)

    total = len(matched)
    start = (page - 1) * page_size
    return RecordPage(
        items=[_out(r, role) for r in matched[start : start + page_size]],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=RecordOut, status_code=201)
def create_record(
    payload: RecordCreate,
    db: Session = Depends(get_db),
    role: Role = Depends(current_role),
    user: User = Depends(get_current_user),
):
    assert_can_create(role)

    submitted = dict(payload.data or {})
    submitted.pop("unit_code", None)  # unit_code is the promoted column
    assert_fields_allowed(db, role, set(submitted), creating=True)

    existing = db.execute(
        select(Record).where(Record.unit_code == payload.unit_code)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, detail="A record with this Unit Code already exists.")

    clean = validate_values(submitted)
    record = Record(unit_code=payload.unit_code, data={}, created_by=user.id)
    db.add(record)
    db.flush()  # assign id for audit rows
    apply_changes(db, record, clean, user)
    db.commit()
    db.refresh(record)
    return _out(record, role)


@router.get("/{record_id}", response_model=RecordOut)
def get_record(
    record_id: int,
    db: Session = Depends(get_db),
    role: Role = Depends(current_role),
    _user: User = Depends(get_current_user),
):
    record = db.get(Record, record_id)
    if not record:
        raise HTTPException(404, detail="Record not found.")
    return _out(record, role)


@router.patch("/{record_id}", response_model=RecordOut)
def patch_record(
    record_id: int,
    payload: RecordPatch,
    db: Session = Depends(get_db),
    role: Role = Depends(current_role),
    user: User = Depends(get_current_user),
):
    record = db.get(Record, record_id)
    if not record:
        raise HTTPException(404, detail="Record not found.")

    submitted = dict(payload.data or {})
    submitted.pop("unit_code", None)  # unit_code is immutable after creation
    # Server-side allow-list: 403 naming any field outside the role's section.
    assert_fields_allowed(db, role, set(submitted))

    # Optimistic locking: reject if the client's version is stale.
    if payload.version is not None and payload.version != record.version:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Record was modified by someone else; reload and retry.",
                "current_version": record.version,
            },
        )

    clean = validate_values(submitted)
    # Judge the record as it would be after this save, not just the submitted
    # keys — a role's section is complete or it isn't.
    assert_own_section_complete(role, {**(record.data or {}), **clean})
    changed = apply_changes(db, record, clean, user)
    db.commit()
    db.refresh(record)
    if not changed:
        # Nothing actually changed; still a valid 200 with current state.
        pass
    return _out(record, role)


@router.post("/{record_id}/archive", response_model=RecordOut)
def archive_record(
    record_id: int,
    db: Session = Depends(get_db),
    role: Role = Depends(current_role),
    _user: User = Depends(get_current_user),
):
    assert_can_archive(role)
    record = db.get(Record, record_id)
    if not record:
        raise HTTPException(404, detail="Record not found.")
    record.is_archived = True
    db.commit()
    db.refresh(record)
    return _out(record, role)


@router.post("/{record_id}/unarchive", response_model=RecordOut)
def unarchive_record(
    record_id: int,
    db: Session = Depends(get_db),
    role: Role = Depends(current_role),
    _user: User = Depends(get_current_user),
):
    assert_can_archive(role)
    record = db.get(Record, record_id)
    if not record:
        raise HTTPException(404, detail="Record not found.")
    record.is_archived = False
    db.commit()
    db.refresh(record)
    return _out(record, role)


@router.get("/{record_id}/events", response_model=list[RecordEventOut])
def record_events(
    record_id: int,
    db: Session = Depends(get_db),
    role: Role = Depends(current_role),
    _user: User = Depends(get_current_user),
):
    """Imported filing/pullout/scanning history, newest first. Undated events
    sort last — the same order the importer replays them in, reversed."""
    record = db.get(Record, record_id)
    if not record:
        raise HTTPException(404, detail="Record not found.")
    vis = visible_fields(role, record.data)
    rows = (
        db.execute(
            select(RecordEvent)
            .where(RecordEvent.record_id == record_id)
            .order_by(RecordEvent.event_date.desc().nullslast(), RecordEvent.id.desc())
        )
        .scalars()
        .all()
    )
    out = []
    for ev in rows:
        item = RecordEventOut.model_validate(ev)
        # A field the caller may not read is no less sensitive inside history.
        item.data = {k: v for k, v in (ev.data or {}).items() if k in vis}
        out.append(item)
    return out


@router.get("/{record_id}/audit", response_model=list[AuditOut])
def record_audit(
    record_id: int,
    db: Session = Depends(get_db),
    role: Role = Depends(current_role),
    _user: User = Depends(get_current_user),
):
    record = db.get(Record, record_id)
    if not record:
        raise HTTPException(404, detail="Record not found.")
    rows = (
        db.execute(
            select(AuditLog)
            .where(
                AuditLog.record_id == record_id,
                # History of a column the caller can't read is just as sensitive.
                AuditLog.field_name.in_(visible_fields(role, record.data)),
            )
            .order_by(AuditLog.changed_at.desc())
        )
        .scalars()
        .all()
    )
    return rows

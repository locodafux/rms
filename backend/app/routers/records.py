from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import apply_changes
from app.database import get_db
from app.deps import current_role, get_current_user
from app.fields import ALL_KEYS, Role
from app.models import AuditLog, Record, User
from app.rbac import (
    assert_can_archive,
    assert_can_create,
    assert_fields_allowed,
    assert_own_section_complete,
)
from app.schemas import AuditOut, RecordCreate, RecordOut, RecordPage, RecordPatch
from app.validation import validate_values

router = APIRouter(prefix="/api/records", tags=["records"])


def _out(record: Record) -> RecordOut:
    return RecordOut.model_validate(record)


def _matches_filters(record: Record, search: str | None, filters: dict[str, str]) -> bool:
    if search:
        needle = search.lower()
        haystack = record.unit_code.lower() + " " + " ".join(
            str(v).lower() for v in (record.data or {}).values() if v is not None
        )
        if needle not in haystack:
            return False
    for key, val in filters.items():
        cell = record.data.get(key) if record.data else None
        if key == "unit_code":
            cell = record.unit_code
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
    """List records — every role can read every record and every column.

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

    matched = [r for r in all_records if _matches_filters(r, search, filters)]

    # Sort across the whole result set so pagination stays correct.
    if sort and (sort in ALL_KEYS or sort == "unit_code"):
        def key_fn(r: Record):
            val = r.unit_code if sort == "unit_code" else (r.data or {}).get(sort)
            # (has_value, lowercased string) keeps blanks last and sorts naturally.
            return (val is None or val == "", str(val).lower() if val is not None else "")
        matched.sort(key=key_fn, reverse=(order == "desc"))
    else:
        matched.sort(key=lambda r: r.updated_at, reverse=True)

    total = len(matched)
    start = (page - 1) * page_size
    return RecordPage(
        items=[_out(r) for r in matched[start : start + page_size]],
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
    return _out(record)


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
    return _out(record)


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
    return _out(record)


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
    return _out(record)


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
    return _out(record)


@router.get("/{record_id}/audit", response_model=list[AuditOut])
def record_audit(
    record_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    if not db.get(Record, record_id):
        raise HTTPException(404, detail="Record not found.")
    rows = (
        db.execute(
            select(AuditLog)
            .where(AuditLog.record_id == record_id)
            .order_by(AuditLog.changed_at.desc())
        )
        .scalars()
        .all()
    )
    return rows

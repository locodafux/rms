"""Role-based access control derived from the field registry.

The per-role editable-field allow-lists are computed from ``fields.py`` (the
single source of truth) and can be overridden at runtime by rows in the
``role_field_permissions`` table (seeded from these defaults). Enforcement is
server-side on every write path; the UI mirroring is convenience only.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.fields import (
    ALL_KEYS,
    BASE_KEYS,
    BUYER_KEYS,
    CHECKLIST_KEYS,
    FIELDS_BY_KEY,
    Role,
    keys_for_owner,
)
from app.models import RoleFieldPermission, User

# Roles allowed to create brand-new records.
CREATE_ROLES: frozenset[Role] = frozenset({Role.admin, Role.document_compliance})

# Every role may import; the upload is scoped to the columns that role owns
# (see services.importer), so a Scanning upload can only fill Scanning fields.
IMPORT_ROLES: frozenset[Role] = frozenset(Role)

# Admin-only capabilities.
EXPORT_ROLES: frozenset[Role] = frozenset({Role.admin})
MANAGE_USER_ROLES: frozenset[Role] = frozenset({Role.admin})
ARCHIVE_ROLES: frozenset[Role] = frozenset({Role.admin})

# Who can see the dashboard's "Archive" (soon-to-archive) widget.
ARCHIVE_DASHBOARD_ROLES: frozenset[Role] = frozenset({Role.admin, Role.filing})

# Every role sees every *record*; columns are scoped per role by visible_fields().


def visible_fields(role: Role, data: dict | None = None) -> frozenset[str]:
    """Fields a role may READ on one record.

    Always: the base unit/buyer identity plus the role's own section. A record
    the role has already worked on — its own section has at least one value —
    unlocks in full, since by then the team needs the whole account's history.
    Only records that haven't reached the role yet stay scoped. Admin reads all.

    Enforced on every read path: record payloads, search/filter/sort, audit log.
    """
    if role == Role.admin:
        return ALL_KEYS
    own = keys_for_owner(role)
    if data and any(data.get(k) not in (None, "") for k in own):
        return ALL_KEYS
    return BASE_KEYS | own


def default_editable_fields(role: Role) -> frozenset[str]:
    """Compile-time default allow-list for a role, from the field registry."""
    if role == Role.admin:
        return ALL_KEYS
    if role == Role.document_compliance:
        # Compliance also keeps the buyer's details current after creation.
        return keys_for_owner(Role.document_compliance) | BUYER_KEYS
    if role == Role.scanning:
        return keys_for_owner(Role.scanning)
    if role == Role.notary:
        return keys_for_owner(Role.notary)
    if role == Role.filing:
        return keys_for_owner(Role.filing)
    return frozenset()


def default_permission_rows() -> list[tuple[str, str]]:
    """(role, field_key) pairs to seed the role_field_permissions table."""
    rows: list[tuple[str, str]] = []
    for role in Role:
        for key in default_editable_fields(role):
            rows.append((role.value, key))
    return rows


def editable_fields(db: Session, role: Role) -> frozenset[str]:
    """Effective allow-list: table-driven if seeded, else registry defaults.

    Admin is always all-fields regardless of table contents.
    """
    if role == Role.admin:
        return ALL_KEYS
    rows = db.execute(
        select(RoleFieldPermission.field_name).where(
            RoleFieldPermission.role == role.value
        )
    ).scalars().all()
    if rows:
        return frozenset(rows) & ALL_KEYS
    return default_editable_fields(role)


def creatable_fields(role: Role) -> frozenset[str]:
    """Fields a role may set at record creation time."""
    if role == Role.admin:
        return ALL_KEYS
    if role == Role.document_compliance:
        # base sections + their own compliance fields
        return BASE_KEYS | keys_for_owner(Role.document_compliance)
    return frozenset()


def assigned_geos(user: User) -> frozenset[str]:
    """Geo areas this user covers. Empty means unrestricted, not uncovered.

    Admin is exempt like everywhere else in this module; an unassigned user keeps
    working exactly as before, matching the editable_fields fallback.
    """
    if user.role == Role.admin.value:
        return frozenset()
    return frozenset(user.geos or ())


def assert_can_create(role: Role) -> None:
    if role not in CREATE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{role.value}' may not create records.",
        )


def assert_can_import(role: Role) -> None:
    if role not in IMPORT_ROLES:
        raise HTTPException(status_code=403, detail="Import is not allowed for this role.")


def assert_can_export(role: Role) -> None:
    if role not in EXPORT_ROLES:
        raise HTTPException(status_code=403, detail="Export is Admin-only.")


def assert_can_manage_users(role: Role) -> None:
    if role not in MANAGE_USER_ROLES:
        raise HTTPException(status_code=403, detail="User management is Admin-only.")


def assert_can_archive(role: Role) -> None:
    if role not in ARCHIVE_ROLES:
        raise HTTPException(status_code=403, detail="Archiving is Admin-only.")


def required_fields(role: Role) -> frozenset[str]:
    """Fields a role must fill before it may save. Admin is exempt (owns all)."""
    if role == Role.admin:
        return frozenset()
    return keys_for_owner(role) - CHECKLIST_KEYS


def assert_own_section_complete(role: Role, data: dict) -> None:
    """A role may only save its section once every field it owns is filled.

    Admin is exempt: admin owns every field, so the rule would make an admin
    save impossible. Creation is exempt too (see records.create_record) — a
    record is born with unit/buyer info and filled in by each role in turn.
    """
    missing = sorted(k for k in required_fields(role) if data.get(k) in (None, ""))
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "message": (
                    f"Fill in every {role.value.replace('_', ' ')} field before saving "
                    f"({len(missing)} still empty)."
                ),
                "missing_fields": missing,
                "missing_labels": [FIELDS_BY_KEY[k].label for k in missing],
            },
        )


def assert_fields_allowed(
    db: Session, role: Role, submitted_keys: set[str], *, creating: bool = False
) -> None:
    """Reject a write touching any field outside the caller's allow-list.

    Raises 403 naming the offending fields. Unknown keys are also rejected.
    """
    unknown = submitted_keys - ALL_KEYS
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown field(s): {sorted(unknown)}",
        )
    allowed = creatable_fields(role) if creating else editable_fields(db, role)
    forbidden = submitted_keys - allowed
    if forbidden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": f"Role '{role.value}' may not write these fields.",
                "forbidden_fields": sorted(forbidden),
            },
        )

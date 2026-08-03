from __future__ import annotations

import json
from datetime import date

from sqlalchemy.orm import Session

from app.models import AuditLog, Record, User

# arch_accounts_status values that start the 90-day archive countdown
# (see Record.archive_countdown_days).
ARCHIVE_COUNTDOWN_STATUSES = {"fallout", "cancelled"}


def _stringify(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def apply_changes(
    db: Session, record: Record, changes: dict, user: User
) -> int:
    """Apply validated field changes to record.data, writing an audit row per
    field that actually changed. Returns the number of changed fields.

    Does not commit; caller controls the transaction.
    """
    data = dict(record.data or {})
    changed = 0
    for key, new_value in changes.items():
        old_value = data.get(key)
        if old_value == new_value:
            continue
        data[key] = new_value
        db.add(
            AuditLog(
                record_id=record.id,
                field_name=key,
                old_value=_stringify(old_value),
                new_value=_stringify(new_value),
                changed_by=user.id,
            )
        )
        changed += 1
        if key == "arch_accounts_status":
            if new_value in ARCHIVE_COUNTDOWN_STATUSES and old_value not in ARCHIVE_COUNTDOWN_STATUSES:
                data["arch_status_since"] = date.today().isoformat()
            elif new_value not in ARCHIVE_COUNTDOWN_STATUSES:
                data.pop("arch_status_since", None)
    if changed:
        record.data = data
        record.version += 1
    return changed

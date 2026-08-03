"""Server-side validation of domain field values against the registry."""

from __future__ import annotations

import re
from datetime import date, datetime

from fastapi import HTTPException

from app.fields import FIELDS_BY_KEY, FieldType

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _coerce_one(key: str, value, *, lenient: bool = False):
    """Validate/normalize a single field value. Returns the stored value.

    ``None``/empty is always allowed (fields are optional except unit_code,
    which the caller enforces separately). With ``lenient=True`` (used by bulk
    import of the historical workbook), format/enum mismatches fall back to the
    raw string instead of raising, so real rows are never dropped for a bad
    cell — interactive API writes stay strict.
    """
    field = FIELDS_BY_KEY[key]
    if value is None or value == "":
        return None

    t = field.type
    if t in (FieldType.text, FieldType.longtext):
        return str(value)

    if t == FieldType.email:
        s = str(value).strip()
        if not _EMAIL_RE.match(s):
            if lenient:
                return s
            raise HTTPException(422, detail=f"'{field.label}' is not a valid email.")
        return s

    if t == FieldType.date:
        if isinstance(value, (date, datetime)):
            return value.isoformat()[:10]
        s = str(value).strip()
        try:
            return datetime.fromisoformat(s[:10]).date().isoformat()
        except ValueError:
            if lenient:
                return s
            raise HTTPException(
                422, detail=f"'{field.label}' must be a date (YYYY-MM-DD)."
            )

    if t == FieldType.integer:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            if lenient:
                return str(value)
            raise HTTPException(422, detail=f"'{field.label}' must be a whole number.")

    if t == FieldType.number:
        try:
            return float(value)
        except (TypeError, ValueError):
            if lenient:
                return str(value)
            raise HTTPException(422, detail=f"'{field.label}' must be a number.")

    if t == FieldType.enum:
        s = str(value).strip()
        if s not in field.options:
            if lenient:
                return s
            raise HTTPException(
                422,
                detail=f"'{field.label}' must be one of {list(field.options)}.",
            )
        return s

    return value


def validate_values(values: dict, *, lenient: bool = False) -> dict:
    """Validate/normalize a {key: value} mapping. Assumes keys already exist."""
    return {key: _coerce_one(key, val, lenient=lenient) for key, val in values.items()}

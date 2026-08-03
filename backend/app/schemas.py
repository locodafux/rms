from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

import email_validator
from pydantic import BaseModel, ConfigDict, EmailStr, Field as PField, StringConstraints

from app.fields import Role

# Staff accounts live on the internal @records.local domain, which email-validator
# rejects by default as a special-use TLD. Everything else stays validated.
email_validator.SPECIAL_USE_DOMAIN_NAMES = [
    d for d in email_validator.SPECIAL_USE_DOMAIN_NAMES if d != "local"
]


# --- Auth / Users -----------------------------------------------------------
class RegisterRequest(BaseModel):
    email: EmailStr
    # No strength policy — any non-empty password is accepted (max_length caps hashing cost).
    password: str = PField(min_length=1, max_length=128)
    full_name: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str  # already validated at registration; str here allows internal domains
    full_name: str | None
    role: str | None
    is_active: bool
    is_superuser: bool
    created_at: datetime


class UserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


class OnlineUser(BaseModel):
    """Presence view of a user. Visible to every role, so no email or account status."""
    id: int
    full_name: str | None
    role: str | None
    last_seen: datetime


# --- Chat -------------------------------------------------------------------
class MessageIn(BaseModel):
    # Strip first, then length-check, so an all-whitespace message is a 422 and not
    # an empty bubble.
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class MessageOut(BaseModel):
    """Author name/role are denormalized so the client needs no user lookup."""
    id: int
    user_id: int | None
    full_name: str | None
    role: str | None
    body: str
    created_at: datetime


# --- Records ----------------------------------------------------------------
class RecordCreate(BaseModel):
    # Machine keys -> values. unit_code is required.
    unit_code: str = PField(min_length=1, max_length=128)
    data: dict[str, Any] = PField(default_factory=dict)


class RecordPatch(BaseModel):
    # Section-level PATCH: only the fields the role owns. Optimistic lock via version.
    data: dict[str, Any]
    version: int | None = None


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    record_id: int
    filename: str
    size: int
    mime_type: str
    uploaded_by: int | None
    uploaded_at: datetime


class RecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    unit_code: str
    data: dict[str, Any]
    is_archived: bool
    version: int
    created_by: int | None
    created_at: datetime
    updated_at: datetime
    attachments: list[AttachmentOut] = []
    archive_countdown_days: int | None = None


class RecordPage(BaseModel):
    items: list[RecordOut]
    total: int
    page: int
    page_size: int


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    record_id: int
    field_name: str
    old_value: str | None
    new_value: str | None
    changed_by: int | None
    changed_at: datetime


# --- Import / Export --------------------------------------------------------
class ImportPreview(BaseModel):
    mapped: dict[str, str]        # excel header -> canonical key
    unmapped: list[str]           # excel headers with no canonical match
    missing_unit_code: bool
    sample_rows: list[dict[str, Any]]
    total_rows: int


class ImportJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    filename: str
    total_rows: int
    processed_rows: int
    inserted: int
    updated: int
    errors: list[Any]
    created_at: datetime


class ExportJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    fmt: str
    row_count: int
    error: str | None
    created_at: datetime

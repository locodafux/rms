from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import Attachment, Record, User
from app.schemas import AttachmentOut

router = APIRouter(prefix="/api/records", tags=["attachments"])

ALLOWED_MIME = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/tiff",
    "image/webp",
}


@router.get("/{record_id}/attachments", response_model=list[AttachmentOut])
def list_attachments(
    record_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    if not db.get(Record, record_id):
        raise HTTPException(404, detail="Record not found.")
    return (
        db.execute(select(Attachment).where(Attachment.record_id == record_id))
        .scalars()
        .all()
    )


@router.post("/{record_id}/attachments", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    record_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """All roles may upload scan attachments. Append-only: no delete endpoint."""
    record = db.get(Record, record_id)
    if not record:
        raise HTTPException(404, detail="Record not found.")

    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(
            415, detail=f"Unsupported file type '{file.content_type}'. PDF/images only."
        )

    contents = await file.read()
    if len(contents) > settings.max_upload_bytes:
        raise HTTPException(
            413, detail=f"File exceeds the {settings.max_upload_mb}MB limit."
        )

    os.makedirs(settings.attachment_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1]
    stored_name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(settings.attachment_dir, stored_name)
    with open(path, "wb") as fh:
        fh.write(contents)

    attachment = Attachment(
        record_id=record.id,
        filename=file.filename or stored_name,
        storage_path=path,
        size=len(contents),
        mime_type=file.content_type,
        uploaded_by=user.id,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment


@router.get("/{record_id}/attachments/{attachment_id}/download")
def download_attachment(
    record_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    attachment = db.get(Attachment, attachment_id)
    if not attachment or attachment.record_id != record_id:
        raise HTTPException(404, detail="Attachment not found.")
    if not os.path.exists(attachment.storage_path):
        raise HTTPException(410, detail="File is missing from storage.")
    return FileResponse(
        attachment.storage_path,
        media_type=attachment.mime_type,
        filename=attachment.filename,
    )

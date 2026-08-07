from __future__ import annotations

import os
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import current_role, get_current_user
from app.fields import Role
from app.models import ExportJob, ImportJob, User
from app.rbac import assert_can_export, assert_can_import
from app.schemas import ExportJobOut, ImportFileOut, ImportJobOut, ImportPreview
from app.services.exporter import run_export
from app.services.importer import build_preview, run_import

router = APIRouter(prefix="/api", tags=["import-export"])

_ALLOWED_EXT = (".xlsx", ".xls", ".csv")


def _save_upload(file: UploadFile) -> str:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(415, detail="Upload must be .xlsx, .xls or .csv.")
    os.makedirs(settings.job_dir, exist_ok=True)
    path = os.path.join(settings.job_dir, f"upload_{uuid.uuid4().hex}{ext}")
    with open(path, "wb") as fh:
        fh.write(file.file.read())
    return path


# --- Import (Admin only) ----------------------------------------------------
@router.post("/import/preview", response_model=ImportPreview)
def import_preview(
    file: UploadFile = File(...),
    role: Role = Depends(current_role),
    _user: User = Depends(get_current_user),
):
    assert_can_import(role)
    path = _save_upload(file)
    try:
        return build_preview(path)
    finally:
        # Preview is stateless; drop the temp upload.
        if os.path.exists(path):
            os.remove(path)


def _import_as(db: Session, user: User, role: Role, as_user_id: int | None) -> User:
    """Resolve whose permissions the upload runs under.

    run_import scopes columns by ``job.created_by``'s role, so admin picking a
    target here is the whole per-user import feature. Validated before the file
    is saved, so a rejected request leaves no orphan in job_dir.
    """
    if as_user_id is None or as_user_id == user.id:
        return user
    if role != Role.admin:
        raise HTTPException(403, detail="Only an admin may import for another user.")
    target = db.get(User, as_user_id)
    if not target:
        raise HTTPException(404, detail="User not found.")
    if not target.is_active:
        raise HTTPException(400, detail="Cannot import for an inactive account.")
    if not target.role:
        # No role => no writable columns; the import would silently do nothing.
        raise HTTPException(400, detail="User has no role assigned.")
    return target


@router.post("/import", response_model=ImportJobOut, status_code=202)
def start_import(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    as_user_id: int | None = Form(None),
    db: Session = Depends(get_db),
    role: Role = Depends(current_role),
    user: User = Depends(get_current_user),
):
    assert_can_import(role)
    target = _import_as(db, user, role, as_user_id)
    path = _save_upload(file)
    job = ImportJob(
        status="pending",
        filename=file.filename or os.path.basename(path),
        source_path=path,
        created_by=target.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    background.add_task(run_import, job.id)
    return job


@router.get("/import", response_model=list[ImportFileOut])
def list_imports(
    db: Session = Depends(get_db),
    role: Role = Depends(current_role),
    user: User = Depends(get_current_user),
):
    """Every file ever uploaded through Import. Admin sees all, everyone else
    sees their own — the same scoping the import itself runs under."""
    q = (
        select(ImportJob, User)
        .outerjoin(User, ImportJob.created_by == User.id)
        .order_by(ImportJob.id.desc())
    )
    if role != Role.admin:
        q = q.where(ImportJob.created_by == user.id)
    out = []
    for job, owner in db.execute(q).all():
        row = ImportFileOut.model_validate(job)
        row.uploaded_by = (owner.full_name or owner.email) if owner else None
        row.uploaded_by_role = owner.role if owner else None
        row.file_available = bool(job.source_path) and os.path.exists(job.source_path)
        out.append(row)
    return out


def _import_job_for(db: Session, job_id: int, role: Role, user: User) -> ImportJob:
    job = db.get(ImportJob, job_id)
    if not job or (role != Role.admin and job.created_by != user.id):
        raise HTTPException(404, detail="Import job not found.")
    return job


@router.get("/import/{job_id}/download")
def import_download(
    job_id: int,
    db: Session = Depends(get_db),
    role: Role = Depends(current_role),
    user: User = Depends(get_current_user),
):
    """The original upload, straight from job_dir — the audit trail for what a
    number in the record actually came from."""
    job = _import_job_for(db, job_id, role, user)
    if not job.source_path or not os.path.exists(job.source_path):
        raise HTTPException(410, detail="The uploaded file is no longer on disk.")
    return FileResponse(
        job.source_path, filename=job.filename, media_type="application/octet-stream"
    )


@router.get("/import/{job_id}", response_model=ImportJobOut)
def import_status(
    job_id: int,
    db: Session = Depends(get_db),
    role: Role = Depends(current_role),
    _user: User = Depends(get_current_user),
):
    assert_can_import(role)
    job = db.get(ImportJob, job_id)
    if not job:
        raise HTTPException(404, detail="Import job not found.")
    return job


# --- Export (Admin only) ----------------------------------------------------
@router.post("/export", response_model=ExportJobOut, status_code=202)
def start_export(
    background: BackgroundTasks,
    fmt: str = Form("xlsx"),
    include_archived: bool = Form(False),
    db: Session = Depends(get_db),
    role: Role = Depends(current_role),
    user: User = Depends(get_current_user),
):
    assert_can_export(role)
    if fmt not in ("xlsx", "csv"):
        raise HTTPException(422, detail="fmt must be 'xlsx' or 'csv'.")
    job = ExportJob(status="pending", fmt=fmt, created_by=user.id)
    db.add(job)
    db.commit()
    db.refresh(job)
    background.add_task(run_export, job.id, include_archived)
    return job


@router.get("/export/{job_id}", response_model=ExportJobOut)
def export_status(
    job_id: int,
    db: Session = Depends(get_db),
    role: Role = Depends(current_role),
    _user: User = Depends(get_current_user),
):
    assert_can_export(role)
    job = db.get(ExportJob, job_id)
    if not job:
        raise HTTPException(404, detail="Export job not found.")
    return job


@router.get("/export/{job_id}/download")
def export_download(
    job_id: int,
    db: Session = Depends(get_db),
    role: Role = Depends(current_role),
    _user: User = Depends(get_current_user),
):
    assert_can_export(role)
    job = db.get(ExportJob, job_id)
    if not job:
        raise HTTPException(404, detail="Export job not found.")
    if job.status != "done" or not job.result_path:
        raise HTTPException(409, detail=f"Export not ready (status: {job.status}).")
    media = (
        "text/csv"
        if job.fmt == "csv"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return FileResponse(
        job.result_path, media_type=media, filename=f"docutrack_export.{job.fmt}"
    )

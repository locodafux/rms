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
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import current_role, get_current_user
from app.fields import Role
from app.models import ExportJob, ImportJob, User
from app.rbac import assert_can_export, assert_can_import
from app.schemas import ExportJobOut, ImportJobOut, ImportPreview
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


@router.post("/import", response_model=ImportJobOut, status_code=202)
def start_import(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    role: Role = Depends(current_role),
    user: User = Depends(get_current_user),
):
    assert_can_import(role)
    path = _save_upload(file)
    job = ImportJob(
        status="pending",
        filename=file.filename or os.path.basename(path),
        source_path=path,
        created_by=user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    background.add_task(run_import, job.id)
    return job


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

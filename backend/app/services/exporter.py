from __future__ import annotations

import os

import pandas as pd

from app.config import settings
from app.database import SessionLocal
from app.fields import FIELDS
from app.models import ExportJob, Record


def _row_dict(record: Record) -> dict:
    data = record.data or {}
    out: dict[str, object] = {}
    for f in FIELDS:
        if f.key == "unit_code":
            out[f.label] = record.unit_code
        else:
            out[f.label] = data.get(f.key)
    return out


def run_export(job_id: int, include_archived: bool = False) -> None:
    db = SessionLocal()
    try:
        job = db.get(ExportJob, job_id)
        if job is None:
            return
        job.status = "running"
        db.commit()

        q = db.query(Record)
        if not include_archived:
            q = q.filter(Record.is_archived.is_(False))
        records = q.order_by(Record.unit_code).all()

        # Preserve full 120-column order even when there are zero rows.
        columns = [f.label for f in FIELDS]
        df = pd.DataFrame([_row_dict(r) for r in records], columns=columns)

        os.makedirs(settings.job_dir, exist_ok=True)
        result_path = os.path.join(settings.job_dir, f"export_{job.id}.{job.fmt}")
        if job.fmt == "csv":
            df.to_csv(result_path, index=False)
        else:
            df.to_excel(result_path, index=False, sheet_name="DocuTrack Records")

        job.result_path = result_path
        job.row_count = len(records)
        job.status = "done"
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.get(ExportJob, job_id)
        if job:
            job.status = "error"
            job.error = str(exc)
            db.commit()
    finally:
        db.close()

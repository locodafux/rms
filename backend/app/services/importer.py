from __future__ import annotations

import pandas as pd

from app.database import SessionLocal
from app.fields import HEADER_LOOKUP, normalize_header
from app.models import ImportJob, Record
from app.validation import _coerce_one


def _read_frame(path: str) -> pd.DataFrame:
    if path.lower().endswith(".csv"):
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    return pd.read_excel(path, dtype=str, keep_default_na=False)


def map_headers(columns: list[str]) -> tuple[dict[str, str], list[str]]:
    """Return (excel_header -> canonical_key, unmapped_headers)."""
    mapped: dict[str, str] = {}
    unmapped: list[str] = []
    for col in columns:
        key = HEADER_LOOKUP.get(normalize_header(str(col)))
        if key:
            mapped[str(col)] = key
        else:
            unmapped.append(str(col))
    return mapped, unmapped


def build_preview(path: str, sample_size: int = 5) -> dict:
    df = _read_frame(path)
    mapped, unmapped = map_headers(list(df.columns))
    sample = []
    for _, row in df.head(sample_size).iterrows():
        sample.append(
            {mapped[col]: row[col] for col in df.columns if col in mapped}
        )
    return {
        "mapped": mapped,
        "unmapped": unmapped,
        "missing_unit_code": "unit_code" not in mapped.values(),
        "sample_rows": sample,
        "total_rows": int(len(df)),
    }


def run_import(job_id: int) -> None:
    """Background worker: upsert rows matched on unit_code. Per-row errors are
    collected without aborting the whole import."""
    db = SessionLocal()
    try:
        job = db.get(ImportJob, job_id)
        if job is None:
            return
        job.status = "running"
        db.commit()

        df = _read_frame(job.source_path)
        mapped, _ = map_headers(list(df.columns))
        job.total_rows = int(len(df))
        db.commit()

        if "unit_code" not in mapped.values():
            job.status = "error"
            job.errors = [{"row": None, "error": "No 'Unit Code' column found."}]
            db.commit()
            return

        inserted = updated = processed = 0
        errors: list[dict] = []
        # Cache unit_code -> Record for this run so repeated Unit Codes within a
        # batch (the real workbook has some) update the same row instead of
        # colliding on the unique constraint (autoflush is off, so a pending
        # insert would otherwise be invisible to a follow-up query).
        seen: dict[str, Record] = {}

        for idx, row in df.iterrows():
            processed += 1
            try:
                values: dict = {}
                for col, key in mapped.items():
                    raw = row[col]
                    if raw is None or str(raw).strip() == "":
                        continue
                    values[key] = _coerce_one(key, raw, lenient=True)

                unit_code = values.pop("unit_code", None)
                if not unit_code:
                    errors.append({"row": int(idx) + 2, "error": "Missing Unit Code."})
                    continue
                unit_code = str(unit_code)

                record = seen.get(unit_code)
                if record is None:
                    record = (
                        db.query(Record)
                        .filter(Record.unit_code == unit_code)
                        .one_or_none()
                    )
                if record is None:
                    record = Record(unit_code=unit_code, data=values, version=1)
                    db.add(record)
                    seen[unit_code] = record
                    inserted += 1
                else:
                    merged = dict(record.data or {})
                    merged.update(values)
                    record.data = merged
                    record.version = (record.version or 1) + 1
                    seen[unit_code] = record
                    updated += 1
            except Exception as exc:  # noqa: BLE001 - per-row isolation
                errors.append({"row": int(idx) + 2, "error": str(exc)})

            if processed % 500 == 0:
                job.processed_rows = processed
                db.commit()

        job.processed_rows = processed
        job.inserted = inserted
        job.updated = updated
        job.errors = errors
        job.status = "done"
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.get(ImportJob, job_id)
        if job:
            job.status = "error"
            job.errors = [{"row": None, "error": str(exc)}]
            db.commit()
    finally:
        db.close()

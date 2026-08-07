from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field as dc_field
from datetime import date
from typing import Iterator

import pandas as pd

from app.database import SessionLocal
from app.fields import HEADER_LOOKUP, Role, normalize_header
from app.models import ImportJob, Record, RecordEvent, User
from app.rbac import assigned_geos, creatable_fields, editable_fields
from app.validation import _coerce_one

_WRITE_LOCK = threading.Lock()

# How many rows from the top of a sheet to search for the header. The team
# workbooks put a title on row 2 and headers on row 3.
_HEADER_SCAN_ROWS = 10


# --- Sheet profiles ---------------------------------------------------------
# The team workbooks reuse the same header text for different fields: "AO" is
# the filing officer on the filing sheet and the scanning officer on the
# scanning sheet, and every sheet has its own "REMARKS" and "VERIFIED BY".
# A single global HEADER_LOOKUP cannot express that, so each sheet resolves its
# columns through the profile it matches.

# Columns every team sheet carries, meaning the same thing on all of them.
_SHARED: dict[str, str] = {
    "ref": "ref",
    "drdate": "dr_date",
    "no": "seq_no",
    "unitcode": "unit_code",
    "geo": "geo",
    "projectname": "project_name",
    "ph": "ph",
    "unitstatus": "unit_status",
    "csdate": "cs_date",
    "lastname": "last_name",
    "suffixname": "suffix_name",
    "firstname": "first_name",
}


@dataclass(frozen=True)
class SheetProfile:
    """A sheet is recognised by its signature headers, never by its name —
    sheet names vary between workbooks, column sets do not."""

    kind: str                       # filed | pullout | scanned
    signature: frozenset[str]       # normalised headers that identify the sheet
    headers: dict[str, str]         # normalised header -> canonical key
    date_key: str                   # which mapped key is the event date
    implied: dict[str, str] = dc_field(default_factory=dict)
    # canonical key -> normalised headers joined into it, blanks skipped
    joins: dict[str, tuple[str, ...]] = dc_field(default_factory=dict)


PROFILES: tuple[SheetProfile, ...] = (
    SheetProfile(
        kind="filed",
        signature=frozenset({"datefiled", "listofdocsfileddocket", "cabinetno"}),
        headers={
            **_SHARED,
            "ao": "filing_archiving_officer",
            "datereceivedfromnst": "date_received_filing",
            "datefiled": "date_filed",
            "listofdocsfileddocket": "filed_docs_list",
            "verifiedby": "filing_verified_by",
            "remarks": "filing_remarks",
        },
        date_key="date_filed",
        # Flat, not derived from the documents column: that column holds 3,881
        # distinct free-text values over 22k rows — an inventory, not a status
        # vocabulary. Any keyword rule would mis-assign the rows it misses.
        implied={"file_status": "On File - Complete"},
        joins={"filing_location": ("cabinetno", "layerno")},
    ),
    SheetProfile(
        kind="pullout",
        signature=frozenset({"requestdate", "datepulledout", "listofdocumentsforpullout"}),
        headers={
            **_SHARED,
            "ao": "filing_archiving_officer",
            "requestdate": "pullout_request_date",
            "requestedby": "pullout_requested_by",
            "datepulledout": "pullout_date_pullout",
            "listofdocumentsforpullout": "pullout_type_of_documents",
            # Text, not date: the column mixes real dates with "FOR TRANSMIT".
            "datereceivedbyrequestor": "pullout_returned_docs",
            "verifiedby": "pullout_verified_by",
            "remarks": "pullout_remarks",
        },
        date_key="pullout_date_pullout",
        # A pulled docket is out of the cabinet, awaiting return.
        implied={"file_status": "For Filing"},
    ),
    SheetProfile(
        kind="scanned",
        signature=frozenset({"datescanned", "submitteddocuments", "datereceivedfromnst"}),
        headers={
            **_SHARED,
            "ao": "scanning_ao",
            "datereceivedfromnst": "date_received_scanning",
            "datescanned": "date_scanned",
            "submitteddocuments": "scanning_submitted_documents",
            "verifiedby": "scanning_verified_by",
            "remarks": "scanning_remarks",
        },
        date_key="date_scanned",
    ),
)

# Below this many signature headers a sheet is not one of the team logs, so it
# falls back to the global HEADER_LOOKUP and behaves like an ordinary upload.
_SIGNATURE_MIN = 2


def match_profile(columns) -> SheetProfile | None:
    norms = {normalize_header(c) for c in columns}
    best = max(PROFILES, key=lambda p: len(p.signature & norms))
    return best if len(best.signature & norms) >= _SIGNATURE_MIN else None


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


def _sheet_mapping(
    columns: list[str], profile: SheetProfile | None
) -> tuple[dict[str, str], list[str], dict[str, list[str]]]:
    """(column -> key, unmapped columns, key -> columns joined into it)."""
    if profile is None:
        mapped, unmapped = map_headers(columns)
        return mapped, unmapped, {}
    mapped, unmapped = {}, []
    for col in columns:
        key = profile.headers.get(normalize_header(col))
        if key:
            mapped[col] = key
        else:
            unmapped.append(col)
    joins = {
        key: [c for c in columns if normalize_header(c) in norms]
        for key, norms in profile.joins.items()
    }
    return mapped, unmapped, {k: v for k, v in joins.items() if v}


def _unique(columns: list[str]) -> list[str]:
    """Real sheets repeat header text (and blanks). Duplicate labels would make
    row[col] return a frame instead of a value, so make them unique."""
    seen: dict[str, int] = {}
    out = []
    for c in columns:
        n = seen.get(c, 0)
        seen[c] = n + 1
        out.append(c if n == 0 else f"{c}__{n}")
    return out


def _header_row(raw: pd.DataFrame) -> int | None:
    """Index of the first row that looks like a header, i.e. carries Unit Code."""
    for i in range(min(_HEADER_SCAN_ROWS, len(raw))):
        for cell in raw.iloc[i]:
            if HEADER_LOOKUP.get(normalize_header(str(cell))) == "unit_code":
                return i
    return None


def _clean(df: pd.DataFrame, mapped: dict[str, str]) -> pd.DataFrame:
    """Drop non-rows. Real sheets carry trailing formatted-but-empty rows plus
    stray annotation columns under an unnamed header ("FOR ARCHIVING") whose
    text would keep dozens of non-rows alive and report every one as "Missing
    Unit Code". Index is preserved so error row numbers stay right."""
    cols = list(mapped)
    if not cols:
        return df[~(df == "").all(axis=1)]
    return df[~(df[cols] == "").all(axis=1)]


def read_sheets(path: str) -> Iterator[tuple[str, pd.DataFrame, SheetProfile | None]]:
    """Every sheet that has a Unit Code column, with its header row found and
    its profile resolved. Sheets without one (cover tabs, summaries) are skipped.
    """
    if path.lower().endswith(".csv"):
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        df.columns = _unique([str(c) for c in df.columns])
        profile = match_profile(df.columns)
        mapped, _, _ = _sheet_mapping(list(df.columns), profile)
        if "unit_code" in mapped.values():
            yield "", _clean(df, mapped), profile
        return

    xls = pd.ExcelFile(path)
    for name in xls.sheet_names:
        raw = xls.parse(name, header=None, dtype=str, keep_default_na=False)
        i = _header_row(raw)
        if i is None:
            continue
        df = raw.iloc[i + 1:].copy()
        df.columns = _unique([str(c) for c in raw.iloc[i]])
        profile = match_profile(df.columns)
        mapped, _, _ = _sheet_mapping(list(df.columns), profile)
        yield name, _clean(df, mapped), profile


def build_preview(path: str, sample_size: int = 5) -> dict:
    sheets = list(read_sheets(path))
    if not sheets:
        return {
            "mapped": {},
            "unmapped": [],
            "missing_unit_code": True,
            "sample_rows": [],
            "total_rows": 0,
        }
    name, df, profile = sheets[0]
    mapped, unmapped, _ = _sheet_mapping(list(df.columns), profile)
    sample = [
        {mapped[col]: row[col] for col in df.columns if col in mapped}
        for _, row in df.head(sample_size).iterrows()
    ]
    return {
        "mapped": mapped,
        "unmapped": unmapped,
        "missing_unit_code": "unit_code" not in mapped.values(),
        "sample_rows": sample,
        "total_rows": sum(len(d) for _, d, _ in sheets),
    }


def _unit_count(df: pd.DataFrame, profile: SheetProfile | None) -> int:
    """How many distinct units a sheet covers — its reach, not its row count."""
    mapped, _, _ = _sheet_mapping(list(df.columns), profile)
    col = next((c for c, k in mapped.items() if k == "unit_code"), None)
    return int(df[col].nunique()) if col else 0


def _as_date(value) -> date | None:
    """Dates are stored as ISO strings; a lenient import may leave junk."""
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _dedupe_key(unit_code: str, kind: str, event_date: date | None, data: dict) -> str:
    payload = "|".join(
        [unit_code, kind, str(event_date), repr(sorted(data.items()))]
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def run_import(job_id: int) -> None:
    """Background worker: upsert rows matched on unit_code. Per-row errors are
    collected without aborting the whole import.

    Jobs are serialised: the admin can start one import per user at once, and
    they queue here (staying "pending" until their turn).
    """
    # ponytail: SQLite allows a single writer, so parallel imports would just
    # trade "database is locked" errors. Drop the lock when this moves to Postgres.
    with _WRITE_LOCK:
        _run_import(job_id)


def _run_import(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(ImportJob, job_id)
        if job is None:
            return
        job.status = "running"
        db.commit()

        sheets = list(read_sheets(job.source_path))
        if not sheets:
            job.status = "error"
            job.errors = [{"row": None, "error": "No sheet with a 'Unit Code' column found."}]
            db.commit()
            return
        job.total_rows = sum(len(df) for _, df, _ in sheets)
        db.commit()

        # Widest sheet last. A workbook can carry the same status column on a
        # consolidated master sheet and on a narrower per-area copy that
        # disagrees with it (1,594 units in the real file), and the sheet
        # covering more units is the one to believe. Stable, so sheets of equal
        # reach keep workbook order. Profiled sheets are unaffected either way —
        # their conflicts resolve by event date, applied after every sheet.
        sheets.sort(key=lambda s: _unit_count(s[1], s[2]))

        # An upload writes only what its uploader could have typed by hand: the
        # role's own allow-list. Unit Code is the match key, never written as data.
        uploader = db.get(User, job.created_by) if job.created_by else None
        role = Role(uploader.role) if uploader and uploader.role else None
        may_update = editable_fields(db, role) if role else frozenset()
        may_create = creatable_fields(role) if role else frozenset()
        allowed = (may_update | may_create) - {"unit_code"}
        # Work areas the uploader covers. Empty = unrestricted (admin, unassigned).
        geos = assigned_geos(uploader) if uploader else frozenset()

        errors: list[dict] = []
        ignored: set[str] = set()
        inserted = updated = processed = out_of_area = events = 0
        # Cache unit_code -> Record for this run so repeated Unit Codes across
        # rows and sheets update the same row instead of colliding on the unique
        # constraint (autoflush is off, so a pending insert would otherwise be
        # invisible to a follow-up query).
        seen: dict[str, Record] = {}
        touched: dict[int, Record] = {}
        # ponytail: whole-table dedupe key set, ~64 bytes/event. Swap for a
        # per-unit query if the event table ever outgrows memory.
        known_keys: set[str] = {k for (k,) in db.query(RecordEvent.dedupe_key).all()}

        for sheet_name, df, profile in sheets:
            mapped, _, joins = _sheet_mapping(list(df.columns), profile)
            if "unit_code" not in mapped.values():
                continue
            geo_col = next((c for c, k in mapped.items() if k == "geo"), None)
            ignored |= {
                str(col) for col, key in mapped.items()
                if key != "unit_code" and key not in allowed
            }
            mapped = {
                col: key for col, key in mapped.items()
                if key == "unit_code" or key in allowed
            }
            sheet_rows = sheet_events = 0

            for idx, row in df.iterrows():
                processed += 1
                sheet_rows += 1
                try:
                    values: dict = {}
                    for col, key in mapped.items():
                        raw = row[col]
                        if raw is None or str(raw).strip() == "":
                            continue
                        values[key] = _coerce_one(key, str(raw).strip(), lenient=True)
                    if profile:
                        for key, cols in joins.items():
                            if key not in allowed:
                                continue
                            parts = [str(row[c]).strip() for c in cols if str(row[c]).strip()]
                            if parts:
                                values[key] = " / ".join(parts)
                        values.update(
                            {k: v for k, v in profile.implied.items() if k in allowed}
                        )

                    unit_code = values.pop("unit_code", None)
                    if not unit_code:
                        errors.append(_row_error(sheet_name, idx, "Missing Unit Code."))
                        continue
                    unit_code = str(unit_code)

                    record = seen.get(unit_code)
                    if record is None:
                        record = (
                            db.query(Record)
                            .filter(Record.unit_code == unit_code)
                            .one_or_none()
                        )

                    # A file dropped in the wrong zone must not rewrite someone
                    # else's area. An existing record gates on its STORED geo, so
                    # a file with no Geo column still gates, and a wrong file
                    # cannot claim an area by asserting one. New records gate on
                    # the file's own value.
                    if geos:
                        row_geo = (
                            (record.data or {}).get("geo")
                            if record is not None
                            else (str(row[geo_col]).strip() if geo_col else None)
                        )
                        if row_geo not in geos:
                            out_of_area += 1
                            continue

                    if record is None:
                        if not may_create:
                            errors.append(_row_error(
                                sheet_name, idx,
                                f"Unit Code '{unit_code}' not found and role "
                                f"'{role.value if role else 'none'}' may not create records.",
                            ))
                            continue
                        record = Record(
                            unit_code=unit_code,
                            data={k: v for k, v in values.items() if k in may_create},
                            version=1,
                        )
                        db.add(record)
                        db.flush()  # need the id for events
                        seen[unit_code] = record
                        inserted += 1
                    else:
                        merged = dict(record.data or {})
                        merged.update({k: v for k, v in values.items() if k in may_update})
                        record.data = merged
                        seen[unit_code] = record
                        updated += 1
                    touched[record.id] = record

                    if profile:
                        ev_date = _as_date(values.get(profile.date_key))
                        key = _dedupe_key(unit_code, profile.kind, ev_date, values)
                        if key not in known_keys:
                            known_keys.add(key)
                            db.add(RecordEvent(
                                record_id=record.id,
                                kind=profile.kind,
                                event_date=ev_date,
                                data=values,
                                source_job_id=job.id,
                                dedupe_key=key,
                            ))
                            events += 1
                            sheet_events += 1
                except Exception as exc:  # noqa: BLE001 - per-row isolation
                    errors.append(_row_error(sheet_name, idx, str(exc)))

                if processed % 500 == 0:
                    job.processed_rows = processed
                    db.commit()

            if profile:
                errors.append({"row": None, "error": (
                    f"{sheet_name or 'file'} ({profile.kind}): {sheet_rows:,} row(s) "
                    f"→ {sheet_events:,} event(s)."
                )})

        db.flush()
        # Current state is derived from the events, not from the last row read:
        # a unit appears on both the filed and pullout sheets, and only the
        # event dates say which happened last.
        for record in touched.values():
            _apply_events(db, record, may_update | may_create)
            record.version = (record.version or 1) + 1

        if ignored:
            names = sorted(ignored)
            errors.insert(0, {"row": None, "error": (
                f"{len(names)} column(s) skipped — not writable by role "
                f"'{role.value if role else 'none'}': {', '.join(names[:10])}"
                + ("…" if len(names) > 10 else "")
            )})
        if out_of_area:
            # One aggregate line, not N row errors: a master file dropped in one
            # person's zone would otherwise report thousands of them.
            errors.append({"row": None, "error": (
                f"{out_of_area:,} row(s) outside {', '.join(sorted(geos))} — skipped."
            )})

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


def _row_error(sheet: str, idx, message: str) -> dict:
    """Row numbers are only unique within a sheet, so errors carry theirs.
    ``idx`` is the 0-based sheet row, so +1 gives the spreadsheet's own number."""
    return {"row": int(idx) + 1, "sheet": sheet or None, "error": message}


def _apply_events(db, record: Record, allowed: frozenset[str]) -> None:
    """Replay this unit's events oldest-first onto its current state, so the
    latest event wins per field. Undated events sort oldest and never displace
    a dated one."""
    # ponytail: one query per touched record (~3.4k on the real workbook). Batch
    # by record_id chunks if an import ever spends real time here.
    events = (
        db.query(RecordEvent).filter(RecordEvent.record_id == record.id).all()
    )
    if not events:
        return
    merged = dict(record.data or {})
    for ev in sorted(
        events, key=lambda e: (e.event_date is not None, e.event_date or date.min, e.id)
    ):
        merged.update({k: v for k, v in (ev.data or {}).items() if k in allowed})
    record.data = merged

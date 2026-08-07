# Capturing team work from imported workbooks — design

Date: 2026-08-06

## Context

Importing a team member's workbook currently captures almost none of their work.
Job #7 — Arnold (Filing) uploading his own workbook — reported "206 updated" while
writing **zero** field values. Four separate causes, verified against the stored
upload `storage/jobs/upload_8090bea7f6014c5c97cc80b0deed817f.xlsx`:

**1. Header rows are not found.** `_has_unit_code`
([importer.py:25](../../../backend/app/services/importer.py#L25)) inspects only row 1 of
each sheet. Both filing sheets carry a title on row 2 and headers on row 3, so
neither was recognised as data.

**2. Only one sheet is imported.** `_read_frame` picks a single sheet. Arnold's
workbook holds three, two of which are his actual work:

| Sheet | Header row | Rows | Status today |
|---|---|---|---|
| `Filed Dockets & Docs` | 3 | 22,165 | never read |
| `Pulled-out Dockets & Docs` | 3 | 6,549 | never read |
| `DOCKET & COMPLIANCE SCANNED` | 1 | 237 | imported — but it is Scanning's sheet |

**3. Work columns map to nothing.** 13-14 columns per sheet fail `HEADER_LOOKUP`,
including columns that match fields already in the registry — `REQUEST DATE`,
`REQUESTED BY`, `DATE PULLED OUT`, `AO`, `REMARKS`. Because the only sheet read
was Scanning's, Filing's RBAC then dropped all six mapped columns, leaving
`unit_code` alone: 206 version bumps, no data.

**4. The sheets are event logs; `Record` is a unit register.** The filing sheet's
22,164 rows describe 3,407 units — a median of 5 filing events each, maximum 38.
Unit `B007L001` alone has 38 events with distinct dates, documents and cabinet
locations, tracking relocations over months. Today's merge keeps only the last
row, discarding ~18,700 filing and ~4,000 pullout events.

Intended outcome: every row of every work sheet is captured, the fields the
dashboard depends on are populated, and repeat events become history rather than
overwrites.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Header detection | Scan the first 10 rows per sheet | Title rows above headers are normal in these workbooks. |
| Sheet selection | Import every sheet with a Unit Code | Two of three sheets are the user's actual work. |
| Header mapping | Per-sheet profiles | `AO` and `REMARKS` mean different fields on different sheets; a global dict cannot express that. |
| Homeless columns | Add registry fields for all of them | User's explicit choice — nothing from the source file is lost. |
| Filed sheet status | `file_status = "On File - Complete"`, flat | See *Why not derived* below. |
| Pullout sheet status | `file_status = "For Filing"` | A pulled docket is out of the cabinet, awaiting return. |
| Scanned sheet status | unchanged | User's choice; the sheet fills dates, AO and remarks only. |
| Repeat rows | `record_events` history table | The only option that captures all the work. |

### Why not derived

The user initially asked for `file_status` to be derived from the documents
column. The data does not support it: `LIST OF DOCS FILED / DOCKET` holds **3,881
distinct free-text values** over 22,164 rows — a document inventory, not a status
vocabulary. Discriminating keywords barely occur: `RDU` in 34 rows (0.2%), `LACK`
in 1, `COMPLETE` in 7. Any rule would mis-assign the ~77% of rows no keyword
reaches. A flat value plus the documents list captured verbatim in its own field
loses nothing and invents nothing.

## Data model

### `record_events`

```python
class RecordEvent(Base):
    """One filing / pullout / scanning event. Sheets are event logs: a unit is
    filed, relocated and pulled out repeatedly, and each row is a real event."""

    __tablename__ = "record_events"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_event_dedupe"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("records.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)   # filed|pullout|scanned
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)      # canonical keys
    source_job_id: Mapped[int | None] = mapped_column(ForeignKey("import_jobs.id"), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
```

**`dedupe_key` is required, not a nicety.** Re-importing a workbook — which will
happen, these are living files — must not double every event. It is
`sha256(unit_code | kind | event_date | sorted data items)`, so an identical row
imported twice is one event, while a genuinely new event on the same day with
different documents is its own row.

`event_date` comes from the profile's date column (`DATE FILED`,
`DATE PULLED OUT`, `DATE SCANNED`) and may be null when that cell is blank.

### Current state

`Record.data` continues to hold current state, so the dashboard, record list and
export are unchanged. But it is now **derived from the latest event by
`event_date`**, per kind — not from the last row processed.

This matters: `Filed` sets `On File - Complete` and `Pullout` sets `For Filing`,
and a unit appears on both sheets. Ordering by event date gives the right answer
regardless of sheet order or import order. Null-dated events sort oldest so they
never displace a dated one.

### Registry fields

13 new fields in [fields.py](../../../backend/app/fields.py), taking the registry
from 120 to 133.

**Base** (identity/reference columns present on all three sheets):
`ref`, `dr_date`, `seq_no`, `ph`, `cs_date`, `suffix_name`.

**Filing-owned:** `filed_docs_list` (longtext), `filing_verified_by` (text),
`filing_remarks` (longtext), `date_received_filing` (date),
`pullout_verified_by` (text).

**Scanning-owned:** `scanning_submitted_documents` (longtext),
`scanning_verified_by` (text).

Adding fields changes `default_editable_fields` output, so `seed_permissions`
must be re-run — it already reconciles by deleting stale rows and adding missing
ones ([seed.py:19](../../../backend/scripts/seed.py#L19)).

## Sheet profiles

A profile identifies a sheet by **signature headers**, not by name — sheet names
vary between workbooks, column sets do not.

```python
@dataclass(frozen=True)
class SheetProfile:
    kind: str                      # filed | pullout | scanned
    signature: frozenset[str]      # normalised headers that identify this sheet
    headers: dict[str, str]        # normalised header -> canonical key
    date_key: str                  # which mapped key is the event date
    implied: dict[str, str]        # fields set by presence on this sheet
```

A sheet matches the profile with the highest signature overlap; below a threshold
it falls back to the existing global `HEADER_LOOKUP` so ordinary single-sheet
uploads keep working exactly as they do now.

### Profile mappings

**filed** — signature `{DATE FILED, LIST OF DOCS FILED / DOCKET, CABINET NO.}`

| Column | Field |
|---|---|
| `AO` | `filing_archiving_officer` |
| `DATE FILED` | `date_filed` *(event date)* |
| `CABINET NO.` + `LAYER NO.` | `filing_location` — joined, blanks skipped |
| `LIST OF DOCS FILED / DOCKET` | `filed_docs_list` |
| `VERIFIED BY` | `filing_verified_by` |
| `REMARKS` | `filing_remarks` |
| `DATE RECEIVED FROM NST` | `date_received_filing` |
| implied | `file_status = "On File - Complete"` |

**pullout** — signature `{REQUEST DATE, DATE PULLED OUT, LIST OF DOCUMENTS FOR PULLOUT}`

| Column | Field |
|---|---|
| `AO` | `filing_archiving_officer` |
| `REQUEST DATE` | `pullout_request_date` |
| `REQUESTED BY` | `pullout_requested_by` |
| `DATE PULLED OUT` | `pullout_date_pullout` *(event date)* |
| `LIST OF DOCUMENTS FOR PULLOUT` | `pullout_type_of_documents` |
| `DATE RECEIVED BY REQUESTOR` | `pullout_returned_docs` |
| `REMARKS` | `pullout_remarks` |
| `VERIFIED BY` | `pullout_verified_by` |
| implied | `file_status = "For Filing"` |

`pullout_returned_docs` is a **text** field, which is what that column needs — it
mixes real dates with `FOR TRANSMIT` and `TO RECEIVED`.

**scanned** — signature `{DATE SCANNED, SUBMITTED DOCUMENTS, DATE RECEIVED FROM NST}`

| Column | Field |
|---|---|
| `AO` | `scanning_ao` |
| `DATE RECEIVED FROM NST` | `date_received_scanning` |
| `DATE SCANNED` | `date_scanned` *(event date)* |
| `SUBMITTED DOCUMENTS` | `scanning_submitted_documents` |
| `VERIFIED BY` | `scanning_verified_by` |
| `REMARKS` | `scanning_remarks` |
| implied | *(none)* |

All three profiles also map the shared base columns (`REF`, `DR DATE`, `NO.`,
`PH`, `CS DATE`, `Suffix Name`) plus the identity columns already mapped today.

RBAC still applies on top: a Scanning user importing a sheet with `CABINET NO.`
cannot write `filing_location`, and the existing job-level "columns skipped" note
reports it.

## Importer changes

`run_import` becomes: for each sheet with a detected header and a Unit Code
column, resolve its profile, then run the existing row loop with that profile's
mapping. Preserved as-is: the `seen` cache (now shared across sheets), per-row
error isolation, the 500-row commit checkpoint, and the geo gating from the
companion spec.

Changes needed:
- `total_rows` is the sum across sheets.
- Row errors gain the sheet name — `Filed Dockets & Docs row 1429` — since row
  numbers are no longer unique within a job.
- Each row writes a `RecordEvent` and contributes to current state; the
  insert/update counters keep counting **records**, with a separate event count
  reported.

Volume: ~29,000 rows for this one workbook, ~6.5 events per unit. Within reach for
SQLite; the existing checkpoint cadence covers progress reporting.

## Frontend

- **Record detail** — a `History` section listing that unit's events newest first:
  date, kind, officer, documents, location, remarks. Read-scoped by the existing
  `visible_fields` rules.
- **Import page** — per-sheet results in the job card (`Filed Dockets & Docs:
  22,164 rows → 3,407 records, 22,164 events`), so a skipped sheet is visible
  rather than silent.

## Testing

| Area | Test |
|---|---|
| Header detection | A sheet with two title rows above the header is found. |
| Multi-sheet | A workbook with three sheets imports all three; counts are summed. |
| Profiles | `AO` maps to `filing_archiving_officer` on the filed sheet and `scanning_ao` on the scanned sheet, from the same workbook. |
| Dedupe | Importing the same workbook twice yields the same event count. |
| Current state | Events out of date order still leave the latest one's values on the record. |
| Implied status | Filed sets `On File - Complete`; a later pullout event sets `For Filing`. |
| Regression | The existing single-sheet tests in `test_import_export.py` pass unchanged via the `HEADER_LOOKUP` fallback. |

## Relationship to the geo spec

Build this first. [2026-08-06-geo-work-areas-design.md](2026-08-06-geo-work-areas-design.md)
adds per-user geo assignments, import gating and the dashboard coverage matrix —
all of which are more useful once the data they summarise is actually being
captured. The two touch `run_import` in different places (gating vs sheet
handling) and do not conflict.

That spec's claim that "the tagging already works — no import change needed"
remains true: `project_name` and `geo` are still set by the admin's master import
and merged, never blanked.

## Out of scope

- Editing events through the UI — they are import-derived; corrections go on the
  record's current-state fields.
- Backfilling events from the three already-completed import jobs.
- Deriving `file_status` from document contents (see *Why not derived*).
- Any change to `project_name` handling.

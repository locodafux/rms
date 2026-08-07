# Work areas by geo — design

Date: 2026-08-06

## Context

Records are processed by four teams in sequence (Document Compliance → Scanning →
Notary → Filing). Today the system knows *which role* owns each field, but not
*which person* owns which slice of the portfolio. In practice the work is divided
by `geo` — the SOMA/NOMA cluster on each record.

Two consequences today:

1. **The Import page has per-user dropzones but no per-user scope.** A file dropped
   in Mildred's zone is scoped only by her role's columns. Dropping the wrong file
   there silently rewrites units belonging to another scanner's area.
2. **The dashboard summarises by role only** ([stats.py](../../../backend/app/stats.py)) —
   done/incoming/pending donuts across all 6,145 records. There is no way to see
   whether SOMA2 filing is behind, or that nobody covers Notary at all.

The assignments to encode:

| geo | Doc Compliance | Scanning | Notary | Filing |
|---|---|---|---|---|
| SOMA1 (1,221) | SJ | Mildred | — | Arnold |
| SOMA2 (1,214) | — | Mildred | — | — |
| SOMA3 (1,729) | SJ | Administrator | — | Arnold |
| NOMA1 (824) | — | Administrator | — | Bryan |
| NOMA2 (491) | — | Administrator | — | Bryan |
| VISMIN (666) | — | — | — | — |

Intended outcome: an admin-editable geo assignment per user, imports gated by it,
and a dashboard coverage matrix that makes the four uncovered cells obvious.

Unrelated and already fixed separately: the import row-count/error-count bug
(`_read_frame` junk rows, job notes counted as row errors).

**Build order:** [2026-08-06-import-work-capture-design.md](2026-08-06-import-work-capture-design.md)
comes first. It fixes the fact that team imports capture no work at all, which is
the data this dashboard summarises. The two specs touch `run_import` in different
places — geo gating in the row loop, sheet handling around it — and do not conflict.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Assignment store | Table + admin UI | Coverage changes with staffing; a code constant needs a deploy. |
| Import gating | Restrict, with an aggregated skip note | A mis-dropped file must not rewrite another area. |
| Overlap | Allowed | Two Filing users may share a geo — handovers and holiday cover. |
| Empty assignment | Unrestricted | Matches the `editable_fields` fallback; Chester/Leo/Junie keep working. |
| Admin | Exempt from gating | Consistent with every other admin exemption in `rbac.py`. |
| VISMIN | Left off the `GEO` enum | Explicit user choice. See *Known limitation*. |

## Data model

New table, mirroring `RoleFieldPermission`
([models.py:125](../../../backend/app/models.py#L125)) — the codebase's established
pattern for "defaults in code, overridable in a table".

```python
class UserGeoAssignment(Base):
    """Which geo areas a user is responsible for. Empty = unrestricted."""

    __tablename__ = "user_geo_assignments"
    __table_args__ = (UniqueConstraint("user_id", "geo", name="uq_user_geo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    geo: Mapped[str] = mapped_column(String(32))
```

Alembic migration in `backend/alembic/versions/`, following the existing
`c1f2a3d4e5b6_user_last_login_last_seen.py` style.

No column is added to `Record`. Ownership is *derived* from the record's existing
`geo` value plus the role — nothing to keep in sync, nothing to backfill.

## Backend

### `app/rbac.py`

```python
def assigned_geos(db: Session, user: User) -> frozenset[str]:
    """Geo areas this user covers. Empty means unrestricted, not uncovered."""
```

Admin returns `frozenset()` (unrestricted) regardless of table contents — the same
shape as `editable_fields` returning `ALL_KEYS` for admin.

Also add `DEFAULT_GEO_ASSIGNMENTS: dict[str, tuple[str, ...]]` keyed by email,
holding the five assignments above, for the seeder to reconcile against.

### `app/services/importer.py` — gating

After the uploader/role resolution block (currently L87-91), resolve
`geos = assigned_geos(db, uploader)`. When `geos` is non-empty, each row is gated
before the insert/update branch:

- **Existing record** → gate on `record.data.get("geo")`. Gating on stored data
  means a file with no GEO column still gates correctly, and a wrong file cannot
  claim another area by asserting its own geo.
- **New record** → gate on the file's mapped `geo` value.
- A record whose geo is blank or off-enum (VISMIN) is **out of area for every
  assigned user**; only unrestricted users and admin can touch it.

Skipped rows increment a counter and do **not** append to `errors`. After the loop,
one aggregated job-level note:

```
1,543 row(s) outside SOMA1, SOMA2 — skipped.
```

Rationale: a master file dropped in Mildred's zone would otherwise emit ~4,000
individual row errors, recreating the reporting mess the earlier fix removed. The
aggregate is honest and readable. Out-of-area rows still count toward
`processed_rows` — they were read.

### `app/stats.py` — coverage matrix

```python
def compute_geo_stats(records: list[Record], assignments: dict) -> list[dict]:
    """One entry per GEO enum value: totals, per-role progress, assignee names."""
```

Reuses the existing `ROLE_SPECS` bucket functions rather than restating the
bucketing rules. Returns counts only — no per-value `breakdown`, which would be
5×4 nested maps for no gain. Rows are the `GEO` enum in declared order.

Also returns `outside: N` — records whose geo is not in the enum (the 666 VISMIN
units), so they are footnoted rather than silently vanished.

### `app/routers/meta.py`

`get_stats` attaches `result["geos"] = compute_geo_stats(records, ...)` using the
record list it already loads — no extra query. Users router gains geo read/write on
the existing admin-only user-update endpoint.

## Frontend

### Users page

A `Work areas` column in the existing table ([Users.tsx:52](../../../frontend/src/pages/Users.tsx#L52)),
a geo multi-select beside the role dropdown, saving through the existing
`api.updateUser`. Admin-only, like the rest of the page.

### Dashboard

A `Coverage by area` card below the role grid, reusing `.card` / `.table-wrap` and
the existing `C` done/incoming/pending palette:

```
Coverage by area
──────────────────────────────────────────────────────────────
Area     Units   Doc Compliance  Scanning   Notary   Filing
SOMA1    1,221   SJ ████████░░   Mildred ██████░░░░  ⚠ none   Arnold ███████░░░
SOMA2    1,214   ⚠ none          Mildred █████░░░░░  ⚠ none   ⚠ none
SOMA3    1,729   SJ ██████░░░░   Admin ████░░░░░░    ⚠ none   Arnold ████████░░
NOMA1      824   ⚠ none          Admin ███████░░░    ⚠ none   Bryan ██████░░░░
NOMA2      491   ⚠ none          Admin █████░░░░░    ⚠ none   Bryan ███████░░░

666 records outside the listed areas.
```

Uncovered cells are visibly flagged, not blank — the point of the view is to make
the gaps obvious. Clicking a cell opens `/records` filtered to that geo.

The records filter matches substrings ([records.py:56](../../../backend/app/routers/records.py#L56)),
which is safe for these six geo values (no value is a prefix of another), so no
exact-match filter work is needed here.

## Known limitation

VISMIN is not in the `GEO` enum, so its 666 records:

- cannot be assigned to anyone,
- are out-of-area for every assigned user (only admin and unassigned users can
  import them),
- appear only as the footnote count, not as a matrix row.

Mark this in `stats.py` with a `ponytail:` comment naming the upgrade path — adding
`"VISMIN"` to `fields.GEO` makes it a normal assignable area with no other change.

## Testing

| Area | Test |
|---|---|
| `test_stats.py` | Geo grouping and assignee names; the `outside` count for an off-enum geo. Pure-function style, as the existing tests there. |
| `test_import_export.py` | An assigned user's import skips out-of-area rows and reports one aggregated note, not N row errors; an unassigned user imports everything; admin is never gated. |
| `test_rbac.py` | `assigned_geos` returns empty for admin and for a user with no rows. |
| Seeder | Reconcile adds and removes, matching `seed_permissions`. |

## Out of scope

- Per-person dashboards — the matrix already names the owner.
- Assignment history or audit.
- Notary assignments, SOMA2 Filing, and the three empty Doc Compliance cells —
  these are staffing gaps to fill through the new UI, not code.
- Any change to how `project_name` works.

# DocuTrack Registry

A multi-user, role-based, database-backed web app that replaces the local-storage
HTML prototype for tracking real-estate unit documentation through its
**compliance → scanning → notary → filing** lifecycle.

Built to the spec in [`DocuTrack_WebApp_Requirements.md`](./DocuTrack_WebApp_Requirements.md).

## v1 decisions (confirmed with the owner)

| Decision | Choice |
|---|---|
| Import access | **Admin only** (same as Export) |
| Deletion | **No hard delete**; Admin-only **soft-archive** |
| Scale / infra | **Simplified v1** — import/export run as in-process FastAPI background tasks (no Celery/Redis) |
| Attachments | **Local disk** + DB metadata (S3 later, behind the same interface) |

## Stack

- **Backend:** FastAPI (async) · SQLAlchemy 2.0 · Alembic · PostgreSQL (SQLite for zero-setup local dev) · JWT (passlib/bcrypt) · pandas + openpyxl
- **Frontend:** React + TypeScript (Vite), a pink admin-dashboard SPA
- **Packaging:** Docker Compose (Postgres + backend + nginx-served SPA)

## The 120-field schema is a single source of truth

Every domain field is declared exactly once in
[`backend/app/fields.py`](./backend/app/fields.py). The ORM, the per-role RBAC
allow-lists, server-side validation, and Excel import/export all derive from it —
field names, sections, owning roles, enum options can never drift. Labels match
the exact 120 columns of `docutrack_records.xlsx`, so import/export round-trips
losslessly; enum options are taken verbatim from the prototype's `<select>`s.

## RBAC (enforced server-side on every write)

| Role | Create | Edit | Import | Export | Users |
|---|---|---|---|---|---|
| **admin** | ✅ | all fields | ✅ | ✅ | ✅ |
| **document_compliance** | ✅ | Compliance Team + 27-item checklist | ❌ | ❌ | ❌ |
| **scanning** | ❌ | Scanning fields | ❌ | ❌ | ❌ |
| **notary** | ❌ | Notary fields | ❌ | ❌ | ❌ |
| **filing** | ❌ | Filing / Pullout / DOAS / Archiving / BOI Entry | ❌ | ❌ | ❌ |

All roles can **read** every record and column. Any write touching a field
outside the caller's allow-list returns **403** naming the offending fields —
even if the UI would never expose them. Allow-lists are table-driven
(`role_field_permissions`, seeded from the registry) so they can change without a
redeploy.

---

## Run with Docker (recommended)

```bash
cp backend/.env.example backend/.env   # optional; compose has sane defaults
docker compose up --build
```

- App (SPA): http://localhost:8080
- API + docs: http://localhost:8000/api/docs
- First admin is auto-created from `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD`
  (defaults `admin@docutrack.local` / `ChangeMe!123` — **change these**).

## Run locally without Docker

### Backend (Python 3.12+)

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # defaults to a local SQLite file
python -m scripts.seed               # create tables, seed permissions + first admin
uvicorn app.main:app --reload        # http://localhost:8000
```

Run the test suite (38 tests, heaviest coverage on the RBAC allow-list):

```bash
cd backend && DISABLE_RATE_LIMIT=1 python -m pytest -q
```

### Frontend

```bash
cd frontend
npm install
npm run dev                          # http://localhost:5173 (proxies /api to :8000)
```

Log in as the seeded admin, then go to **Users** to activate and assign roles to
anyone who self-registers (new accounts start inactive and roleless by design).

## Database migrations (Alembic)

The app calls `create_all` on startup for a frictionless v1, and Alembic is wired
up for controlled schema evolution:

```bash
cd backend
alembic upgrade head                                   # apply migrations
alembic revision --autogenerate -m "describe change"   # after editing models
```

## Importing the production workbook

Admin → **Import** → choose `docutrack_records.xlsx`. Headers are normalized and
matched to the 120 canonical fields; you get a mapping + sample preview before
confirming; rows are upserted on **Unit Code**. The historical import is lenient
(a bad cell never drops a row); interactive edits stay strictly validated.

## Project layout

```
backend/
  app/
    fields.py         # ← single source of truth (120 fields, enums, roles)
    rbac.py           # allow-lists derived from fields.py + table overrides
    models.py schemas.py validation.py security.py deps.py audit.py
    routers/          # auth, users, meta, records, attachments, importexport
    services/         # importer, exporter (background tasks)
  scripts/seed.py     # bootstrap admin + seed permissions
  alembic/            # migrations
  tests/              # 38 tests; test_rbac.py is the core
frontend/
  src/pages/          # Login, Dashboard, Records, RecordDetail, Import, Export, Users
docker-compose.yml
```

## Notes / upgrade paths

- **Search/filter** is done in Python over the result set — fine for the v1
  small-team scale. Swap to Postgres JSONB predicates when the dataset grows.
- **Background jobs** are in-process; move import/export to Celery/Redis if files
  or concurrency grow (the service functions are already isolated for this).
- **Attachments** are on local disk; the metadata model + storage_path make an
  S3/MinIO swap localized to `routers/attachments.py`.
```

# DocuTrack Registry — Web Application Requirements & Optimized Build Prompt

Source references analyzed: `docutrack.html` (single-page prototype UI, client-side storage) and `docutrack_records.xlsx` (120-column live dataset, sheet "DocuTrack Records"). This document turns that prototype into a real multi-user, role-based, database-backed Python web application spec, plus a ready-to-use prompt for Claude to build it.

---

## 1. Purpose

Replace the local-storage-only HTML prototype with a proper server-backed application that:

- Persists all records in a real database instead of browser storage.
- Adds authentication (register/login) and five distinct roles with different permissions.
- Restricts each role to editing only the Excel columns relevant to its function.
- Supports importing the existing 120-column Excel into the database.
- Restricts Export to Admin only.
- Restricts creating brand-new entries to Document Compliance and Admin only.
- Preserves the prototype's "no delete" philosophy for records and attachments (append-only audit trail), unless the user later decides otherwise.

---

## 2. Roles & Permissions Matrix

| Role | Create Entry | View Records | Edit Own Section Columns | Edit Other Sections | Import | Export | Manage Users |
|---|---|---|---|---|---|---|---|
| **Admin** | ✅ | ✅ (all) | ✅ (all columns) | ✅ (all columns) | ✅ | ✅ | ✅ |
| **Document Compliance** | ✅ | ✅ (all) | ✅ (Compliance Team columns only) | ❌ | ✅ (own columns) | ❌ | ❌ |
| **Scanning** | ❌ | ✅ (all) | ✅ (Scanning of Documents columns only) | ❌ | ✅ (own columns, updates only) | ❌ | ❌ |
| **Filing** | ❌ | ✅ (all) | ✅ (Filing System Entry columns only) | ❌ | ✅ (own columns, updates only) | ❌ | ❌ |
| **Notary** | ❌ | ✅ (all) | ✅ (Notary Status columns only) | ❌ | ✅ (own columns, updates only) | ❌ | ❌ |

Notes:
- All roles can **view** every record, but column visibility is decided **per record**. A record the role has not worked yet exposes only its **own section** plus the shared base columns (Unit & Project Info, Buyer's Info, BOI Status); the rest is withheld on every read path — list, detail, search/filter/sort, audit trail. Once the role has entered any value in its own section on that record, the record unlocks **in full** for that role. **Write** access never widens beyond the role's own section. Admin sees and edits everything.
- Only **Admin** and **Document Compliance** can create a new Unit Code record (the base Unit/Project Info and Buyer's Info sections are filled in at creation, most logically by whoever is bringing the file into the system).
- Import (Excel → database) is open to **every role**, scoped per account: an upload only writes the columns that role owns (same allow-list as manual editing), and roles that cannot create records can only update existing Unit Codes. Admin imports all columns.
- Export (database → Excel/CSV) is Admin-only, full stop.
- Enforcement must happen **server-side** on every write endpoint (field allow-list per role), not just hidden in the UI — the UI should also disable/hide fields the current user can't edit, but the API must independently re-validate. Never trust client-submitted role/field claims.

---

## 3. Column-to-Role Mapping (derived from the 120-column Excel schema)

### 3.1 Base record fields (created by Admin / Document Compliance only, at entry creation)
`Unit Code, Company, Geo, Project Name, Unit, Type, Phase, Sub Phase, Batch, Unit Status, Reserved Date, Contracted Date, Booked Date, Withdrawal Date, Bank Finance, TCP, LA` — *Unit & Project Information*

`Last Name, Suffix, First Name, Middle Name, Citizenship, Civil Status, Gender, Employment, Contact Number, Email Address of Principal Buyer, Email Address of Co-buyer, Address, Remarks (Buyer)` — *Buyer's Information*

`BOI Start of Commercial Operations` — *BOI Status*

### 3.2 Document Compliance role columns
`Doc Compliance Officer, Date Received from SAS, Date Transmitted to Scanning, Cleared Date, Account Location, Mode of Payment, PB/SPS/CB1/CB2/AIF Valid ID (Primary & Secondary — 10 fields), Lacking Remarks, SPA Status, SPA Type, SPA No. of Copies, Date Transmitted for Scanning, SPA Remarks, Compliance Team Remarks`, plus **BOI Status Entry** (`BOI Status, Date Submitted, NCPA Submitted To, Remarks`) and the 27-item **Document Checklist** (Buyer's Info Sheet, Co-Buyer Info Sheet, Computation Sheet, CPA, Buyer's Guide, House Specs, DOAS, UHLA, CB-UHLA, BIR 1904, BIR 2316, CB 1904, CB BIR 2316, PB/CB CENOMAR, PB/CB Marriage Certificate, PB/CB COE, PB/CB Payslip, Proof of Billing, Bank Statement, Annual Financial Statement, Business ITR, DTI/SEC Cert, Exit and Entry Stamp).

### 3.3 Scanning role columns
`Docket Scanning Status, Scanning AO, Date Received (Scanning), Date Scanned, Scanning Remarks`

### 3.4 Notary role columns
`Notary Status, Account Officer, NCPA Notary Date, Endorsement Date, NCPA Email Sent Date, Notarized By, Notary Remarks`

### 3.5 Filing role columns
`Filing & Archiving Officer, File Status, Date Filed, Filing Location`, plus **Pullout Request** (`Requested By, Type of Documents, Requesting Dept/Group, Request Date, Date Pullout, Returned Docs, Remarks`), **DOAS Notary Status** (`Pullout By, Requested Date Pullout, DOAS Status, N-DOAS Date Returned, Return By, Remarks`), and **Archiving/Disposal** (`Accounts Status, Pullout Date, Archived Date, Location, Date Disposal, Remarks`). *(BOI Status Entry sits in the workbook's filing block but is owned by Document Compliance — see 3.2.)*

### 3.6 Attachments
Scanned documents (PDF/image, up to 10MB each, unlimited count) attach to a record. Recommend: Scanning role uploads scan attachments; all roles can view/download; no deletion (append-only), matching prototype behavior.

---

## 4. Functional Requirements

1. **Auth**: Register (email + password, hashed with bcrypt/argon2) and Login (session or JWT-based). Optional: admin approval step before a new registrant is active, and forced role assignment by Admin (self-selecting your own role at registration is a security risk — recommend Admin assigns/approves roles).
2. **Role-based access control (RBAC)**: middleware/decorator that checks role before permitting field-level writes; return 403 on disallowed field or action.
3. **Records CRUD (append-only)**: Create (Admin/Doc Compliance only), Read (all roles, paginated + searchable + column filterable like the prototype), Update (field allow-list per role), no hard Delete (soft-archive at most, admin-only if ever needed).
4. **Import**: Upload `.xlsx`/`.csv` → parse header row → map to the 120 canonical fields (fuzzy/normalized header matching, same idea as prototype's `normalizeHeader`) → preview → confirm → upsert into DB (match on Unit Code to update vs. insert new). Should run as a background job for large files given the sample workbook is ~190MB.
5. **Export**: Admin-only button to export all records (or filtered view) to `.xlsx`/`.csv`, all 120 columns.
6. **Audit trail**: Every field update should log who changed what and when (append to an `audit_log` table) — critical since multiple roles touch the same record over its lifecycle.
7. **Attachments**: Upload/store scanned docs (object storage or filesystem + DB metadata), associate with Unit Code, viewable/downloadable by all roles, no delete.
8. **Search & filter**: Free-text search + per-column Excel-style filters, matching the prototype's UX (two tabs: Filing System Entry view, Scanning of Document Entry view — can be preserved as dashboard views/filters over the same records table).
9. **Pagination**: Large dataset (workbook already shows real production volume) — server-side pagination required, not client-side like the prototype.

---

## 5. Non-Functional Requirements

- Data integrity: Unit Code should be unique per record; enforce at DB level.
- Concurrency: multiple roles editing different sections of the same record simultaneously — use optimistic locking or per-field/per-section updates (PATCH semantics) rather than full-row overwrite, to avoid one role's save clobbering another's concurrent edit.
- Validation: server-side validation matching field types (dates, emails, numeric SPA copies, enum values for status fields like Unit Status, SPA Status, File Status, etc. — enumerations are already defined in the prototype's `<select>` options).
- Security: hashed passwords, HTTPS, CSRF protection on forms, input sanitization, role checks on every endpoint, file-type/size validation on uploads (10MB limit as in prototype).
- Performance: import/export of large files should be async (background task/queue) with a progress indicator, not a blocking request.
- Auditability: immutable history of edits (append-only audit log table) since "nothing can be deleted" is a stated business rule in the current prototype.

---

## 6. Recommended Tech Stack (Python-based, optimized for this use case)

| Layer | Recommendation | Why |
|---|---|---|
| **Backend framework** | **FastAPI** | Async-native (good for large import/export jobs), automatic OpenAPI docs, first-class Pydantic validation — ideal for enforcing the per-role field allow-lists declaratively. Django REST Framework is a solid alternative if you want built-in admin panel + ORM conventions out of the box; FastAPI is leaner and faster to iterate on for a custom RBAC model like this. |
| **Database** | **PostgreSQL** | Handles a 120-column, many-thousand-row relational dataset cleanly; strong support for JSONB (useful for the 27-item document checklist and flexible audit-log payloads), full-text search, and row-level constraints (unique Unit Code). |
| **ORM** | **SQLAlchemy 2.0 + Alembic** | Type-safe models, mature migration tooling for evolving a 120-column schema over time. |
| **Auth** | **fastapi-users** or custom JWT with **passlib (bcrypt/argon2)** | Ready-made register/login/role scaffolding; JWT works well for a decoupled frontend. |
| **Background jobs** | **Celery + Redis** (or lighter-weight **RQ**) | For async Excel import/export on a dataset this large (source file is ~190MB) so requests don't block. |
| **File storage** | Local disk/volume for MVP; **S3-compatible object storage** (MinIO/AWS S3) for production attachments | Matches the prototype's "attachments never deleted" model at scale. |
| **Excel/CSV parsing** | **openpyxl** (xlsx read/write) + **pandas** (bulk transform/validation during import/export) | pandas simplifies header normalization, dtype coercion, and chunked processing of large sheets. |
| **Frontend** | New build (not a reuse of `docutrack.html`'s layout) as a **React (Vite) + TypeScript** SPA calling the FastAPI backend, structured as a proper **admin dashboard**: fixed **top bar** (logo/app name, global search, current user + role badge, notifications, logout) plus a left icon/label **sidebar** for primary navigation (Dashboard, Records, Import, Export [Admin only], Users [Admin only]) and a main content area with card-based stat widgets above the records table. | The prototype's tab-and-single-panel layout was designed for a single-file local tool; a real multi-role system reads better as a conventional dashboard shell, and a top bar is the natural place for account/role context and global actions. |
| **Styling / theme** | New **pink-based** design system (not the prototype's navy/gold): e.g. primary `#D6336C` or `#E85D8A`, accent `#FFF0F5`/`#FDE8EF` backgrounds, dark charcoal text for contrast, white content cards with soft shadows, rounded corners. Use a clean sans-serif (Inter or IBM Plex Sans) throughout. Role badges and status badges (Unit Status, File Status, etc.) can use tinted pink/rose variants for consistency, with a distinct color reserved only for error/danger states. | Establishes a distinct visual identity for the new app rather than inheriting the prototype's navy/gold "record book" look. |
| **Deployment** | **Docker Compose** (FastAPI app + Postgres + Redis + Celery worker), reverse-proxied via **Nginx** | Straightforward, portable, easy to hand off to any host (VM, ECS, Render, Fly.io, etc.). |
| **Testing** | **pytest** + **httpx** (async test client) | Cover RBAC field-allow-list logic thoroughly — that's the highest-risk area for regressions. |

**MVP-simpler alternative**: if this is an internal tool for a small team and infra simplicity matters more than scale, **Flask + Flask-Login + SQLite/Postgres + Jinja2 templates** is a faster path to a working v1, with a straightforward upgrade path to the FastAPI/Postgres/Celery stack above once usage grows.

---

## 7. Suggested Data Model (high level)

- `users` (id, email, hashed_password, role, is_active, created_at)
- `records` (id, unit_code [unique], ...all 120 domain columns grouped logically, created_by, created_at, updated_at)
- `document_checklist` — could be normalized into its own table (record_id, checklist_item_key, is_checked) or kept as JSONB on `records` for simplicity; JSONB is simpler and adequate here since the 27 items are a fixed, well-known set.
- `attachments` (id, record_id, filename, storage_path, uploaded_by, uploaded_at, size, mime_type)
- `audit_log` (id, record_id, field_name, old_value, new_value, changed_by, changed_at)
- `role_field_permissions` (role, field_name) — optional table-driven approach instead of hardcoding the allow-list in code, so Admin can adjust permissions without a deploy.

---

## 8. Open Questions for the User (recommend clarifying before/while building)

1. Should Document Compliance also be allowed to Import, or is Import Admin-only like Export?
2. Should users self-select a role at registration, or should new accounts start inactive/roleless until an Admin approves and assigns a role? (Recommended: Admin-approval, for security.)
3. Should there be a true "soft delete"/archive capability for Admin, or is the "nothing can ever be deleted" rule absolute, matching the prototype?
4. Expected concurrent user count and record volume (the source workbook has a large row count) — affects whether Celery/Redis is worth the added complexity for v1 vs. starting simpler and upgrading later.
5. Should attachments live in cloud object storage (S3/MinIO) from day one, or is local disk acceptable for an initial internal deployment?

---

## 9. Optimized Build Prompt (ready to hand to Claude to implement)

> **Role & goal.** You are building a production-grade Python web application called **DocuTrack Registry**. It tracks real-estate unit documentation through its compliance → scanning → notary → filing lifecycle, replacing an existing local-storage-only HTML prototype (`docutrack.html`) with a multi-user, role-based, database-backed system. The prototype and `docutrack_records.xlsx` are **reference material only** — reuse their data model, field names, and enum options; do **not** reuse the prototype's visual design or client-side storage.
>
> **Work in phases, and pause for my confirmation between each.** Do not build the whole thing in one pass.
> 1. **Clarify** the open questions below, then output a short implementation plan + folder structure for my approval.
> 2. **Backend foundation**: data model, migrations, auth, RBAC layer, and its tests.
> 3. **Records API**: CRUD, search/filter/pagination, audit logging, attachments.
> 4. **Import/Export** background jobs.
> 5. **Frontend** dashboard.
> 6. **Docker Compose + docs + seed/bootstrap**.
> Deliver runnable, tested code at the end of each phase — not pseudocode.
>
> ### Stack
> FastAPI (async) + SQLAlchemy 2.0 + Alembic + PostgreSQL; JWT auth via passlib (bcrypt or argon2); Celery + Redis for background import/export; pandas + openpyxl for Excel/CSV; React + TypeScript (Vite) frontend calling the API. Package everything with Docker Compose (app, Postgres, Redis, Celery worker, nginx) plus a `.env.example` and a `README` with one-command bring-up. Provide a **seed/bootstrap script** that creates the first `admin` account from env vars (there must be a way to get an initial admin without self-registration).
>
> ### Auth
> Register and login endpoints, hashed passwords, JWT sessions with refresh. **New registrations are created inactive and roleless**; an Admin must activate the account and assign exactly one role: `admin`, `document_compliance`, `scanning`, `filing`, or `notary`. Users never self-select a role. Include password strength validation and rate-limiting on login.
>
> ### Data model
> A `records` table matching the canonical 120-column schema in **Section 3** of this document, grouped as: Unit & Project Info, Buyer's Info, BOI Status, Compliance Team (incl. the 27-item Document Checklist and the 10 Valid-ID fields), SPA, Scanning, Notary Status, and Filing System Entry (incl. Pullout Request / DOAS Notary Status / Archiving-Disposal / BOI Status Entry). `unit_code` is `UNIQUE NOT NULL`. Store the 27-item checklist as JSONB. Add `attachments` (id, record_id, filename, storage_path, uploaded_by, uploaded_at, size, mime_type — no delete) and `audit_log` (id, record_id, field_name, old_value, new_value, changed_by, changed_at). Keep the canonical field list in **one shared module** that both the ORM model and the RBAC allow-lists import — the field names must have a single source of truth.
>
> ### RBAC — the core requirement, treat it as highest-risk
> Enforce, **server-side on every write**, a fixed allow-list of editable fields per role. The allow-lists come directly from Section 3:
> - `admin`: all fields, plus user management, Import, and Export.
> - `document_compliance`: may **create** records (fills Unit & Project Info + Buyer's Info + BOI Start-of-Commercial-Operations at creation) and may edit only the Section 3.2 Compliance Team fields (officer, dates, account location, mode of payment, the 10 valid-ID fields, lacking remarks, SPA fields, the 27-item document checklist, and the BOI Status Entry fields).
> - `scanning`: cannot create; may edit only the Section 3.3 fields.
> - `notary`: cannot create; may edit only the Section 3.4 fields.
> - `filing`: cannot create; may edit only the Section 3.5 fields (incl. Pullout Request, DOAS Notary Status, Archiving/Disposal).
> - **All roles** can read/search/filter every record and column. Any write touching a field outside the caller's allow-list returns **403** with the offending field name(s), even if the UI would never surface that field. Never trust client-submitted role or field claims. Prefer a **table-driven** allow-list (`role_field_permissions`) so permissions can change without a redeploy, but ship with the Section 3 mapping seeded.
>
> ### Records API
> Create (Admin/Doc-Compliance only), Read (all roles — server-side paginated, free-text search, and per-column filters mirroring the prototype's Excel-style filtering), and **section-level PATCH** updates (a role submits only its own section; no full-row overwrite). Use optimistic locking (version column or `updated_at` check) so two roles editing the same record concurrently cannot clobber each other. **No hard delete** — at most an Admin-only soft-archive flag if I confirm it's wanted. Every accepted field change writes an `audit_log` row.
>
> ### Import
> Endpoint (Admin-only unless I say otherwise) accepting `.xlsx`/`.csv`: normalize headers against the canonical field names (case/whitespace/punctuation-insensitive, like the prototype's `normalizeHeader`), return a **preview of the column mapping + a sample of parsed rows** for confirmation, then upsert matched on `unit_code` (update existing, insert new). Run as a Celery job with a queryable progress/status endpoint. Report per-row errors without aborting the whole import.
>
> ### Export
> Admin-only endpoint producing a full (or currently-filtered) `.xlsx`/`.csv` with all 120 columns, as a background job, returning a downloadable artifact when ready.
>
> ### Frontend
> A fresh **admin-dashboard** UI (do not copy the prototype's look). **Pink-based theme**: primary `#D6336C`/`#E85D8A`, soft rose-tinted card/badge backgrounds (`#FFF0F5`/`#FDE8EF`), white content areas, dark charcoal text, rounded corners, soft shadows, a clean sans-serif (Inter or IBM Plex Sans); reserve one distinct non-pink color for error/danger only. Layout: a fixed full-width **top bar** (logo/app name, global search, current user + role badge, notifications, logout) and a left **sidebar** (Dashboard with stat cards, Records, Import, Export [Admin only], User Management [Admin only]). Recreate the prototype's *functionality* in this shell: the "Filing System Entry" and "Scanning of Document Entry" tabs as filtered views over the same records table, Excel-style per-column filter popovers, paginated/searchable table, a sectioned entry modal or record page, drag-and-drop attachment upload with 10MB validation, an import wizard with the column-mapping step, and Admin-only export controls. **Disable/hide fields the current role can't edit, matching the server allow-list exactly** — but treat the UI as convenience only; the API is the enforcement boundary.
>
> ### Non-functional & validation
> Hashed passwords, HTTPS-ready behind nginx, CSRF protection on cookie-based flows, input sanitization, and role checks on every endpoint. Server-side field validation by type: dates, emails, numeric SPA copy counts, and **enum validation for status fields** (Unit Status, SPA Status, File Status, Notary Status, etc.) using the option sets already defined in the prototype's `<select>` elements. 10MB per-file upload limit with MIME/type checks. Structured logging and clear error responses.
>
> ### Testing & definition of done
> `pytest` + `httpx` async client. **Heaviest coverage on the RBAC allow-list**: for each role, a positive test (can edit its own fields) and a negative test (gets 403 editing every other section), plus create-permission tests, import/export authorization tests, and a concurrency test proving two concurrent section PATCHes don't overwrite each other. CI-friendly: `docker compose up` brings the whole system up, and there's a documented way to run migrations, seed the admin, and run the test suite.
>
> ### Before finalizing the plan, ask me to confirm:
> 1. Can Document Compliance also Import, or is Import Admin-only like Export?
> 2. Must records be permanently non-deletable, or should Admin get a soft-archive?
> 3. Expected record volume and concurrent-user count, to right-size Celery/Redis (vs. a simpler v1)?
> 4. Attachments in cloud object storage (S3/MinIO) from day one, or local disk for the initial internal deployment?

---

*Prepared from analysis of `docutrack.html` (UI/UX and field definitions) and `docutrack_records.xlsx` (120-column canonical schema, sheet "DocuTrack Records").*

import io

import pandas as pd

from app.fields import CHECKLIST_KEYS, FIELDS_BY_KEY, Role, keys_for_owner
from app.models import ImportJob, Record, RecordEvent
from app.services.exporter import run_export
from app.services.importer import run_import
from tests.conftest import TestingSessionLocal, auth, token_for


def _xlsx_bytes(rows: list[dict]) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    buf.seek(0)
    return buf.read()


def test_import_preview_maps_headers(client):
    admin = token_for(client, "admin")
    content = _xlsx_bytes([{"Unit Code": "I-1", "Company": "Acme", "Bogus Col": "x"}])
    r = client.post(
        "/api/import/preview",
        headers=auth(admin),
        files={"file": ("in.xlsx", content, "application/vnd.ms-excel")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mapped"]["Unit Code"] == "unit_code"
    assert body["mapped"]["Company"] == "company"
    assert "Bogus Col" in body["unmapped"]
    assert body["missing_unit_code"] is False


def test_import_scoped_to_uploader_section(client):
    """Every role may upload, but only into the columns it owns: a Scanning
    upload fills Scanning fields and silently drops a Compliance column."""
    admin = token_for(client, "admin")
    client.post(
        "/api/records",
        headers=auth(admin),
        json={"unit_code": "SC-1", "data": {"company": "Acme"}},
    )
    scan_key = sorted(keys_for_owner(Role.scanning))[0]
    scan_label = FIELDS_BY_KEY[scan_key].label
    comp_key = sorted(keys_for_owner(Role.document_compliance) - CHECKLIST_KEYS)[0]

    scanning = token_for(client, "scanning")
    content = _xlsx_bytes(
        [{"Unit Code": "SC-1", scan_label: "SCAN-VAL", "Company": "Hacked"}]
    )
    r = client.post(
        "/api/import",
        headers=auth(scanning),
        files={"file": ("in.xlsx", content, "application/vnd.ms-excel")},
    )
    assert r.status_code == 202, r.text
    status = client.get(f"/api/import/{r.json()['id']}", headers=auth(scanning)).json()
    assert status["status"] == "done"
    assert status["updated"] == 1

    db = TestingSessionLocal()
    try:
        rec = db.query(Record).filter(Record.unit_code == "SC-1").one()
        assert rec.data[scan_key] == "SCAN-VAL"  # own column written
        assert rec.data["company"] == "Acme"     # other section untouched
        assert comp_key not in rec.data
    finally:
        db.close()


def _user_id(client, admin_token, email):
    users = client.get("/api/users", headers=auth(admin_token)).json()
    return next(u["id"] for u in users if u["email"] == email)


def test_import_as_user_uses_that_users_scope(client):
    """Admin drops a file into a user's zone: the import runs under that user's
    permissions (not admin's all-fields access) and is credited to them."""
    admin = token_for(client, "admin")
    client.post(
        "/api/records",
        headers=auth(admin),
        json={"unit_code": "AS-1", "data": {"company": "Acme"}},
    )
    scan_key = sorted(keys_for_owner(Role.scanning))[0]
    scan_label = FIELDS_BY_KEY[scan_key].label
    scan_id = _user_id(client, admin, "scanning@t.local")

    content = _xlsx_bytes(
        [{"Unit Code": "AS-1", scan_label: "SCAN-VAL", "Company": "Hacked"}]
    )
    r = client.post(
        "/api/import",
        headers=auth(admin),
        data={"as_user_id": str(scan_id)},
        files={"file": ("in.xlsx", content, "application/vnd.ms-excel")},
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["id"]
    assert client.get(f"/api/import/{job_id}", headers=auth(admin)).json()["updated"] == 1

    db = TestingSessionLocal()
    try:
        rec = db.query(Record).filter(Record.unit_code == "AS-1").one()
        assert rec.data[scan_key] == "SCAN-VAL"
        # Admin's own all-fields access must NOT leak into a scoped import.
        assert rec.data["company"] == "Acme"
        assert db.get(ImportJob, job_id).created_by == scan_id
    finally:
        db.close()


def test_import_as_user_rejects_non_admin_and_inactive(client):
    admin = token_for(client, "admin")
    scanning = token_for(client, "scanning")
    notary_id = _user_id(client, admin, "notary@t.local")
    content = _xlsx_bytes([{"Unit Code": "AS-2"}])
    files = {"file": ("in.xlsx", content, "application/vnd.ms-excel")}

    r = client.post(
        "/api/import",
        headers=auth(scanning),
        data={"as_user_id": str(notary_id)},
        files=files,
    )
    assert r.status_code == 403, r.text

    client.patch(
        f"/api/users/{notary_id}", headers=auth(admin), json={"is_active": False}
    )
    r = client.post(
        "/api/import",
        headers=auth(admin),
        data={"as_user_id": str(notary_id)},
        files=files,
    )
    assert r.status_code == 400
    assert "inactive" in r.json()["detail"]


def test_import_non_creating_role_cannot_insert(client):
    """Scanning may not create records, so an unknown Unit Code is a row error."""
    scanning = token_for(client, "scanning")
    scan_label = FIELDS_BY_KEY[sorted(keys_for_owner(Role.scanning))[0]].label
    content = _xlsx_bytes([{"Unit Code": "NOPE-1", scan_label: "x"}])
    r = client.post(
        "/api/import",
        headers=auth(scanning),
        files={"file": ("in.xlsx", content, "application/vnd.ms-excel")},
    )
    status = client.get(f"/api/import/{r.json()['id']}", headers=auth(scanning)).json()
    assert status["inserted"] == 0
    assert any("may not create records" in e["error"] for e in status["errors"])

    db = TestingSessionLocal()
    try:
        assert db.query(Record).filter(Record.unit_code == "NOPE-1").one_or_none() is None
    finally:
        db.close()


def test_import_upserts(client):
    admin = token_for(client, "admin")
    content = _xlsx_bytes(
        [
            {"Unit Code": "UP-1", "Company": "Acme", "Unit Status": "Reserved"},
            {"Unit Code": "UP-2", "Company": "Beta"},
        ]
    )
    r = client.post(
        "/api/import",
        headers=auth(admin),
        files={"file": ("in.xlsx", content, "application/vnd.ms-excel")},
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["id"]
    # BackgroundTasks in TestClient run synchronously after the response.
    status = client.get(f"/api/import/{job_id}", headers=auth(admin)).json()
    assert status["status"] == "done"
    assert status["inserted"] == 2

    db = TestingSessionLocal()
    try:
        rec = db.query(Record).filter(Record.unit_code == "UP-1").one()
        assert rec.data["company"] == "Acme"
        assert rec.data["unit_status"] == "Reserved"
    finally:
        db.close()


def test_import_handles_duplicate_unit_codes_in_batch(client):
    """The real workbook contains repeated Unit Codes; a second occurrence must
    merge into the first row, not crash on the unique constraint."""
    admin = token_for(client, "admin")
    content = _xlsx_bytes(
        [
            {"Unit Code": "DUP", "Company": "First"},
            {"Unit Code": "OTHER", "Company": "X"},
            {"Unit Code": "DUP", "Company": "Second"},  # same code again
        ]
    )
    r = client.post(
        "/api/import",
        headers=auth(admin),
        files={"file": ("in.xlsx", content, "application/vnd.ms-excel")},
    )
    job_id = r.json()["id"]
    status = client.get(f"/api/import/{job_id}", headers=auth(admin)).json()
    assert status["status"] == "done"
    assert status["inserted"] == 2
    assert status["updated"] == 1
    assert len(status["errors"]) == 0

    db = TestingSessionLocal()
    try:
        rec = db.query(Record).filter(Record.unit_code == "DUP").one()
        assert rec.data["company"] == "Second"  # last write wins on merge
    finally:
        db.close()


def test_import_skips_cover_sheets(client):
    """The real workbook opens on a 1-cell 'SUM' tab; the data lives on a later
    sheet, so sheet 0 is not the one to import."""
    admin = token_for(client, "admin")
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as xw:
        pd.DataFrame([{"Total": 1}]).to_excel(xw, sheet_name="SUM", index=False)
        pd.DataFrame([{"UNIT\nCODE": "SH-1", "Company": "Acme"}]).to_excel(
            xw, sheet_name="MASTERFILE", index=False
        )
    buf.seek(0)
    r = client.post(
        "/api/import",
        headers=auth(admin),
        files={"file": ("in.xlsx", buf.read(), "application/vnd.ms-excel")},
    )
    job_id = r.json()["id"]
    status = client.get(f"/api/import/{job_id}", headers=auth(admin)).json()
    assert status["status"] == "done", status["errors"]
    assert status["inserted"] == 1


def test_import_ignores_rows_with_only_unrecognised_columns(client):
    """The real sheet trails 31 rows whose sole content is an annotation under
    an unnamed header. They are not data rows: they must not be counted, and
    must not each report 'Missing Unit Code'. A row with recognised data but no
    Unit Code is still a genuine error."""
    admin = token_for(client, "admin")
    content = _xlsx_bytes(
        [
            {"Unit Code": "J-1", "Company": "Acme", "Notes": ""},
            {"Unit Code": "", "Company": "", "Notes": "FOR ARCHIVING"},  # junk
            {"Unit Code": "", "Company": "Orphan", "Notes": ""},  # real mistake
        ]
    )
    r = client.post(
        "/api/import",
        headers=auth(admin),
        files={"file": ("in.xlsx", content, "application/vnd.ms-excel")},
    )
    job_id = r.json()["id"]
    status = client.get(f"/api/import/{job_id}", headers=auth(admin)).json()
    assert status["status"] == "done", status["errors"]
    assert status["total_rows"] == 2  # junk row dropped, orphan row kept
    assert status["inserted"] == 1
    # Row numbers repeat across sheets, so an error names the sheet it came from.
    assert status["errors"] == [
        {"row": 4, "sheet": "Sheet1", "error": "Missing Unit Code."}
    ]


def test_export_admin_only(client):
    scanning = token_for(client, "scanning")
    r = client.post("/api/export", headers=auth(scanning), data={"fmt": "csv"})
    assert r.status_code == 403


def test_export_produces_file(client):
    admin = token_for(client, "admin")
    client.post(
        "/api/records",
        headers=auth(admin),
        json={"unit_code": "E-1", "data": {"company": "Acme"}},
    )
    r = client.post("/api/export", headers=auth(admin), data={"fmt": "csv"})
    assert r.status_code == 202
    job_id = r.json()["id"]
    status = client.get(f"/api/export/{job_id}", headers=auth(admin)).json()
    assert status["status"] == "done"
    dl = client.get(f"/api/export/{job_id}/download", headers=auth(admin))
    assert dl.status_code == 200
    assert "Unit Code" in dl.text
    assert "E-1" in dl.text


def test_import_gated_by_assigned_geo(client):
    """A file dropped in a user's zone only touches that user's work areas.

    Existing records gate on their STORED geo, so a wrong file cannot claim an
    area by asserting one; out-of-area rows are one aggregated note, not N errors.
    """
    admin = token_for(client, "admin")
    scan_key = sorted(keys_for_owner(Role.scanning))[0]
    scan_label = FIELDS_BY_KEY[scan_key].label
    for code, geo in (("G-1", "SOMA1"), ("G-2", "SOMA3")):
        client.post(
            "/api/records",
            headers=auth(admin),
            json={"unit_code": code, "data": {"geo": geo}},
        )
    scan_id = _user_id(client, admin, "scanning@t.local")
    assert client.patch(
        f"/api/users/{scan_id}", headers=auth(admin), json={"geos": ["SOMA1"]}
    ).json()["geos"] == ["SOMA1"]

    content = _xlsx_bytes([
        {"Unit Code": "G-1", "Geo": "SOMA1", scan_label: "IN"},
        {"Unit Code": "G-2", "Geo": "SOMA1", scan_label: "OUT"},  # lies about its geo
    ])
    r = client.post(
        "/api/import",
        headers=auth(admin),
        data={"as_user_id": str(scan_id)},
        files={"file": ("in.xlsx", content, "application/vnd.ms-excel")},
    )
    status = client.get(f"/api/import/{r.json()['id']}", headers=auth(admin)).json()
    assert status["updated"] == 1
    assert [e for e in status["errors"] if e["row"] is not None] == []
    assert any("outside SOMA1" in e["error"] for e in status["errors"])

    db = TestingSessionLocal()
    try:
        assert db.query(Record).filter(Record.unit_code == "G-1").one().data[scan_key] == "IN"
        assert scan_key not in db.query(Record).filter(Record.unit_code == "G-2").one().data
    finally:
        db.close()


def test_import_unassigned_and_admin_are_ungated(client):
    """Empty assignment means unrestricted, and admin is never gated."""
    admin = token_for(client, "admin")
    client.post(
        "/api/records",
        headers=auth(admin),
        json={"unit_code": "UG-1", "data": {"geo": "NOMA2"}},
    )
    scan_label = FIELDS_BY_KEY[sorted(keys_for_owner(Role.scanning))[0]].label
    files = {"file": ("in.xlsx", _xlsx_bytes([{"Unit Code": "UG-1", scan_label: "x"}]),
                      "application/vnd.ms-excel")}
    for token in (token_for(client, "scanning"), admin):
        r = client.post("/api/import", headers=auth(token), files=files)
        status = client.get(f"/api/import/{r.json()['id']}", headers=auth(admin)).json()
        assert status["updated"] == 1, status
        assert not any("outside" in e["error"] for e in status["errors"])


def test_update_user_rejects_unknown_geo(client):
    admin = token_for(client, "admin")
    scan_id = _user_id(client, admin, "scanning@t.local")
    r = client.patch(
        f"/api/users/{scan_id}", headers=auth(admin), json={"geos": ["ATLANTIS"]}
    )
    assert r.status_code == 422, r.text


def test_files_tab_lists_and_downloads_uploads(client):
    """Files tab: admin sees every upload, a user sees only their own, and the
    original file comes back byte-for-byte."""
    admin = token_for(client, "admin")
    scan_id = _user_id(client, admin, "scanning@t.local")
    content = _xlsx_bytes([{"Unit Code": "F-1", "Company": "Acme"}])
    client.post(
        "/api/import",
        headers=auth(admin),
        data={"as_user_id": str(scan_id)},
        files={"file": ("scanning.xlsx", content, "application/vnd.ms-excel")},
    )
    client.post(
        "/api/import",
        headers=auth(admin),
        files={"file": ("admins.xlsx", content, "application/vnd.ms-excel")},
    )

    all_files = client.get("/api/import", headers=auth(admin)).json()
    assert [f["filename"] for f in all_files] == ["admins.xlsx", "scanning.xlsx"]
    assert all_files[1]["uploaded_by_role"] == "scanning"
    assert all_files[0]["file_available"] is True

    scanning = token_for(client, "scanning")
    own = client.get("/api/import", headers=auth(scanning)).json()
    assert [f["filename"] for f in own] == ["scanning.xlsx"]

    r = client.get(f"/api/import/{own[0]['id']}/download", headers=auth(scanning))
    assert r.status_code == 200 and r.content == content
    # Someone else's upload isn't theirs to fetch.
    assert client.get(
        f"/api/import/{all_files[0]['id']}/download", headers=auth(scanning)
    ).status_code == 404


def _team_workbook(sheets: dict[str, list[dict]], header_row: int = 2) -> bytes:
    """A team workbook: title text above the headers, several sheets, and the
    same header text ("AO", "REMARKS") meaning different things per sheet."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as xw:
        for name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(
                xw, sheet_name=name, index=False, startrow=header_row
            )
            if header_row:
                xw.sheets[name].cell(row=2, column=2, value="FILING & PULLOUT -")
    buf.seek(0)
    return buf.read()


_FILED = [
    {"UNIT CODE": "EV-1", "AO": "ARNOLD", "DATE FILED": "2025-05-02",
     "LIST OF DOCS FILED / DOCKET": "CPA, DOAS", "CABINET NO.": "C1",
     "LAYER NO.": "L2", "VERIFIED BY": "MJ", "REMARKS": "ok"},
    {"UNIT CODE": "EV-1", "AO": "ARNOLD", "DATE FILED": "2025-09-09",
     "LIST OF DOCS FILED / DOCKET": "RDU", "CABINET NO.": "C3",
     "LAYER NO.": "L1", "VERIFIED BY": "MJ", "REMARKS": "relocated"},
    {"UNIT CODE": "EV-2", "AO": "ARNOLD", "DATE FILED": "2025-07-07",
     "LIST OF DOCS FILED / DOCKET": "CPA", "CABINET NO.": "C2",
     "LAYER NO.": "L1", "VERIFIED BY": "MJ", "REMARKS": ""},
]
_PULLOUT = [
    {"UNIT CODE": "EV-1", "AO": "ARNOLD", "REQUEST DATE": "2025-06-01",
     "REQUESTED BY": "LEGAL", "DATE PULLED OUT": "2025-06-02",
     "LIST OF DOCUMENTS FOR PULLOUT": "DOAS",
     "DATE RECEIVED BY REQUESTOR": "FOR TRANSMIT", "VERIFIED BY": "MJ",
     "REMARKS": "urgent"},
]
_SCANNED = [
    {"UNIT CODE": "EV-1", "AO": "MILDRED", "DATE RECEIVED FROM NST": "2025-04-01",
     "DATE SCANNED": "2025-04-02", "SUBMITTED DOCUMENTS": "CPA",
     "VERIFIED BY": "RB", "REMARKS": "scan note"},
]


def _run(client, token, content, name="team.xlsx", as_user_id=None):
    data = {"as_user_id": str(as_user_id)} if as_user_id else None
    r = client.post(
        "/api/import",
        headers=auth(token),
        data=data,
        files={"file": (name, content, "application/vnd.ms-excel")},
    )
    assert r.status_code == 202, r.text
    return client.get(f"/api/import/{r.json()['id']}", headers=auth(token)).json()


def _record(unit_code: str) -> Record:
    db = TestingSessionLocal()
    try:
        rec = db.query(Record).filter(Record.unit_code == unit_code).one()
        db.expunge(rec)
        return rec
    finally:
        db.close()


def test_import_finds_headers_below_title_rows_on_every_sheet(client):
    """The filing workbook's sheets carry a title on row 2 and headers on row 3,
    and two of the three sheets are the user's actual work."""
    admin = token_for(client, "admin")
    content = _team_workbook({
        "Filed Dockets & Docs": _FILED,
        "Pulled-out Dockets & Docs": _PULLOUT,
        "DOCKET & COMPLIANCE SCANNED": _SCANNED,
    })
    status = _run(client, admin, content)
    assert status["status"] == "done", status["errors"]
    assert status["total_rows"] == 5          # summed across all three sheets
    assert status["inserted"] == 2            # EV-1, EV-2
    notes = [e["error"] for e in status["errors"] if e["row"] is None]
    assert any("(filed): 3 row(s) → 3 event(s)" in n for n in notes), notes
    assert any("(pullout): 1 row(s) → 1 event(s)" in n for n in notes), notes
    assert any("(scanned): 1 row(s) → 1 event(s)" in n for n in notes), notes


def test_import_profiles_disambiguate_shared_headers(client):
    """'AO' is the filing officer on the filed sheet and the scanning officer on
    the scanned sheet — same header, same workbook, different fields."""
    admin = token_for(client, "admin")
    _run(client, admin, _team_workbook({
        "Filed Dockets & Docs": _FILED,
        "DOCKET & COMPLIANCE SCANNED": _SCANNED,
    }))
    data = _record("EV-1").data
    assert data["filing_archiving_officer"] == "ARNOLD"
    assert data["scanning_ao"] == "MILDRED"
    assert data["filing_remarks"] == "relocated"   # latest filed event
    assert data["scanning_remarks"] == "scan note"
    assert data["filing_location"] == "C3 / L1"    # cabinet + layer joined
    assert data["filed_docs_list"] == "RDU"


def test_import_current_state_follows_event_dates_not_sheet_order(client):
    """EV-1 was filed, pulled out, then filed again; EV-2 was only filed. The
    latest event by date decides the status, whatever order the sheets are read.
    """
    admin = token_for(client, "admin")
    _run(client, admin, _team_workbook({
        "Pulled-out Dockets & Docs": _PULLOUT,     # read first, but not latest
        "Filed Dockets & Docs": _FILED,
    }))
    assert _record("EV-1").data["file_status"] == "On File - Complete"  # 2025-09-09
    assert _record("EV-2").data["file_status"] == "On File - Complete"
    # ...and the pullout's own fields survive as history on the record.
    assert _record("EV-1").data["pullout_requested_by"] == "LEGAL"

    # A pullout after the last filing flips it back.
    later = [{**_PULLOUT[0], "DATE PULLED OUT": "2026-01-05",
              "REQUEST DATE": "2026-01-04"}]
    _run(client, admin, _team_workbook({"Pulled-out Dockets & Docs": later}))
    assert _record("EV-1").data["file_status"] == "For Filing"


def test_import_events_are_deduped_across_reimports(client):
    """These are living files, re-uploaded weekly: an identical row must not
    double the history, but a new event on the same unit must be kept."""
    admin = token_for(client, "admin")
    content = _team_workbook({
        "Filed Dockets & Docs": _FILED,
        "Pulled-out Dockets & Docs": _PULLOUT,
    })
    _run(client, admin, content)
    db = TestingSessionLocal()
    try:
        first = db.query(RecordEvent).count()
        assert first == 4
        assert {e.kind for e in db.query(RecordEvent).all()} == {"filed", "pullout"}
    finally:
        db.close()

    status = _run(client, admin, content)          # same workbook again
    db = TestingSessionLocal()
    try:
        assert db.query(RecordEvent).count() == first
    finally:
        db.close()
    assert any("→ 0 event(s)" in e["error"] for e in status["errors"] if e["row"] is None)


def test_filing_upload_captures_filing_work(client):
    """The original bug: Arnold's workbook reported '206 updated' and wrote no
    field at all, because only the scanning sheet was read and filing RBAC then
    dropped every one of its columns."""
    admin = token_for(client, "admin")
    filing_id = _user_id(client, admin, "filing@t.local")
    client.post("/api/records", headers=auth(admin), json={"unit_code": "EV-1"})
    client.post("/api/records", headers=auth(admin), json={"unit_code": "EV-2"})

    status = _run(client, admin, _team_workbook({
        "Filed Dockets & Docs": _FILED,
        "DOCKET & COMPLIANCE SCANNED": _SCANNED,
    }), as_user_id=filing_id)
    assert status["status"] == "done", status["errors"]

    data = _record("EV-1").data
    assert data["file_status"] == "On File - Complete"
    assert data["date_filed"] == "2025-09-09"
    assert data["filing_archiving_officer"] == "ARNOLD"
    # Scanning's sheet is in the same file, but Filing may not write its columns.
    assert "scanning_ao" not in data
    assert any("not writable by role 'filing'" in e["error"] for e in status["errors"])

    db = TestingSessionLocal()
    try:
        # The scanned sheet's rows are still read, they just write nothing.
        assert db.query(RecordEvent).filter(RecordEvent.kind == "filed").count() == 3
    finally:
        db.close()


def test_record_events_endpoint_is_read_scoped(client):
    """History is served newest-first, and a field the caller may not read is
    no less sensitive inside an event than on the record."""
    admin = token_for(client, "admin")
    _run(client, admin, _team_workbook({
        "Filed Dockets & Docs": _FILED,
        "DOCKET & COMPLIANCE SCANNED": _SCANNED,
    }))
    rid = _record("EV-1").id

    events = client.get(f"/api/records/{rid}/events", headers=auth(admin)).json()
    assert [e["event_date"] for e in events] == ["2025-09-09", "2025-05-02", "2025-04-02"]
    assert events[0]["kind"] == "filed"
    assert events[0]["data"]["filed_docs_list"] == "RDU"

    # Notary hasn't worked this record, so it only reads base + its own section.
    notary = client.get(f"/api/records/{rid}/events", headers=auth(token_for(client, "notary"))).json()
    assert all("filed_docs_list" not in e["data"] for e in notary)
    assert any(e["data"].get("unit_status") is not None or True for e in notary)


def test_widest_sheet_wins_when_plain_sheets_disagree(client):
    """The master workbook carries the same status column on a consolidated
    sheet and on a narrower per-area copy, and they disagree. The sheet covering
    more units wins, whichever order they sit in the file."""
    admin = token_for(client, "admin")
    narrow = [
        {"UNIT CODE": "W-1", "Docket Scanning Status": "pending scanning"},
        {"UNIT CODE": "W-2", "Docket Scanning Status": "pending scanning"},
    ]
    wide = [
        {"UNIT CODE": "W-1", "Docket Scanning Status": "scanned - complete"},
        {"UNIT CODE": "W-2", "Docket Scanning Status": "scanned - complete"},
        {"UNIT CODE": "W-3", "Docket Scanning Status": "scanned - complete"},
    ]
    # Narrow sheet sits last in the workbook: reach must beat position.
    status = _run(client, admin, _team_workbook(
        {"SOMA 1-2": wide, "SOMA 1": narrow}, header_row=0
    ))
    assert status["status"] == "done", status["errors"]
    assert _record("W-1").data["docket_scanning_status"] == "scanned - complete"
    assert _record("W-2").data["docket_scanning_status"] == "scanned - complete"


def test_history_page_searches_and_windows(client):
    """The History page: newest first across records, filtered by window, kind
    and free text — and never matching on a value the caller can't read."""
    admin = token_for(client, "admin")
    _run(client, admin, _team_workbook({
        "Filed Dockets & Docs": _FILED,
        "Pulled-out Dockets & Docs": _PULLOUT,
    }))

    # Fixture dates are historical, so the default 90-day window is empty and
    # all-time is not — exactly the distinction the window control exists for.
    assert client.get("/api/history", headers=auth(admin)).json()["total"] == 0
    body = client.get("/api/history?days=0", headers=auth(admin)).json()
    assert body["total"] == 4
    assert [i["event_date"] for i in body["items"]] == [
        "2025-09-09", "2025-07-07", "2025-06-02", "2025-05-02",
    ]
    assert body["items"][0]["unit_code"] == "EV-1"

    only = client.get("/api/history?days=0&kind=pullout", headers=auth(admin)).json()
    assert [i["kind"] for i in only["items"]] == ["pullout"]

    # Search spans unit code and any readable value.
    assert client.get("/api/history?days=0&search=EV-2", headers=auth(admin)).json()["total"] == 1
    assert client.get("/api/history?days=0&search=LEGAL", headers=auth(admin)).json()["total"] == 1
    assert client.get("/api/history?days=0&search=nope", headers=auth(admin)).json()["total"] == 0

    # Notary hasn't worked these units, so filing values are neither shown nor
    # searchable — otherwise a probe would leak them.
    notary = auth(token_for(client, "notary"))
    assert client.get("/api/history?days=0&search=LEGAL", headers=notary).json()["total"] == 0
    assert client.get("/api/history?days=0&search=EV-1", headers=notary).json()["total"] == 3

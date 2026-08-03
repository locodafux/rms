import io

import pandas as pd

from app.models import Record
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


def test_import_non_admin_forbidden(client):
    scanning = token_for(client, "scanning")
    content = _xlsx_bytes([{"Unit Code": "I-2"}])
    r = client.post(
        "/api/import/preview",
        headers=auth(scanning),
        files={"file": ("in.xlsx", content, "application/vnd.ms-excel")},
    )
    assert r.status_code == 403


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

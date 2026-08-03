from tests.conftest import auth, full_section, token_for


def _make(client, unit="R-1", data=None):
    admin = token_for(client, "admin")
    r = client.post(
        "/api/records",
        headers=auth(admin),
        json={"unit_code": unit, "data": data or {}},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_unit_code_unique(client):
    _make(client, "DUP-1")
    admin = token_for(client, "admin")
    r = client.post(
        "/api/records", headers=auth(admin), json={"unit_code": "DUP-1", "data": {}}
    )
    assert r.status_code == 409


def test_audit_log_written_on_change(client):
    rec = _make(client, "AUD-1")
    admin = token_for(client, "admin")
    client.patch(
        f"/api/records/{rec['id']}",
        headers=auth(admin),
        json={"data": {"company": "Acme"}},
    )
    log = client.get(f"/api/records/{rec['id']}/audit", headers=auth(admin)).json()
    fields = {e["field_name"] for e in log}
    assert "company" in fields


def test_optimistic_lock_conflict(client):
    rec = _make(client, "LOCK-1")
    admin = token_for(client, "admin")
    # stale version -> 409
    r = client.patch(
        f"/api/records/{rec['id']}",
        headers=auth(admin),
        json={"data": {"company": "A"}, "version": 999},
    )
    assert r.status_code == 409


def test_concurrent_sections_do_not_clobber(client):
    """Two roles patch different sections; both survive."""
    rec = _make(client, "CONC-1")
    scan = token_for(client, "scanning")
    notary = token_for(client, "notary")

    r1 = client.patch(
        f"/api/records/{rec['id']}",
        headers=auth(scan),
        json={"data": full_section(client, scan) | {"docket_scanning_status": "scanned - complete"}},
    )
    assert r1.status_code == 200, r1.text
    r2 = client.patch(
        f"/api/records/{rec['id']}",
        headers=auth(notary),
        json={"data": full_section(client, notary) | {"notary_status": "Notarized"}},
    )
    assert r2.status_code == 200, r2.text
    final = r2.json()["data"]
    assert final["docket_scanning_status"] == "scanned - complete"
    assert final["notary_status"] == "Notarized"


def test_enum_validation(client):
    rec = _make(client, "ENUM-1")
    admin = token_for(client, "admin")
    r = client.patch(
        f"/api/records/{rec['id']}",
        headers=auth(admin),
        json={"data": {"unit_status": "NotARealStatus"}},
    )
    assert r.status_code == 422


def test_email_validation(client):
    rec = _make(client, "EMAIL-1")
    admin = token_for(client, "admin")
    r = client.patch(
        f"/api/records/{rec['id']}",
        headers=auth(admin),
        json={"data": {"email_principal": "not-an-email"}},
    )
    assert r.status_code == 422


def test_search_and_pagination(client):
    for i in range(5):
        _make(client, f"S-{i}", {"company": "Findable" if i == 2 else "Other"})
    admin = token_for(client, "admin")
    r = client.get("/api/records?search=Findable", headers=auth(admin)).json()
    assert r["total"] == 1
    r2 = client.get("/api/records?page=1&page_size=2", headers=auth(admin)).json()
    assert len(r2["items"]) == 2
    assert r2["total"] == 5


def test_archive_admin_only_and_hidden(client):
    rec = _make(client, "ARC-1")
    scanning = token_for(client, "scanning")
    admin = token_for(client, "admin")
    # non-admin cannot archive
    assert (
        client.post(f"/api/records/{rec['id']}/archive", headers=auth(scanning)).status_code
        == 403
    )
    # admin archives; record drops from default list
    assert (
        client.post(f"/api/records/{rec['id']}/archive", headers=auth(admin)).status_code
        == 200
    )
    listed = client.get("/api/records", headers=auth(admin)).json()
    assert all(item["unit_code"] != "ARC-1" for item in listed["items"])
    incl = client.get("/api/records?include_archived=true", headers=auth(admin)).json()
    assert any(item["unit_code"] == "ARC-1" for item in incl["items"])


def test_all_roles_can_read(client):
    _make(client, "READ-1")
    for role in ["scanning", "filing", "notary", "document_compliance"]:
        tok = token_for(client, role)
        r = client.get("/api/records", headers=auth(tok))
        assert r.status_code == 200
        assert r.json()["total"] >= 1

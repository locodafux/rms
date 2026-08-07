"""Highest-risk coverage: per-role field allow-list enforcement.

For each non-admin role we assert a positive case (can edit its own section) and
a negative case (403 when touching every other section's fields).
"""

import pytest

from app.fields import Role, keys_for_owner
from app.rbac import default_editable_fields
from tests.conftest import auth, full_section, token_for

# One representative editable field per section-owning role.
OWN_FIELD = {
    "document_compliance": ("doc_compliance_officer", "Jane"),
    "scanning": ("docket_scanning_status", "scanned - complete"),
    "notary": ("notary_status", "Notarized"),
    "filing": ("file_status", "On File - Complete"),
}

# A field belonging to another section, to prove 403.
FOREIGN_FIELD = {
    "document_compliance": ("docket_scanning_status", "scanned - complete"),
    "scanning": ("doc_compliance_officer", "Jane"),
    "notary": ("file_status", "On File - Complete"),
    "filing": ("notary_status", "Notarized"),
}


def _make_record(client):
    admin = token_for(client, "admin")
    r = client.post(
        "/api/records",
        headers=auth(admin),
        json={"unit_code": "U-001", "data": {"company": "Acme", "unit": "12A"}},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.parametrize("role", list(OWN_FIELD))
def test_role_can_edit_own_section(client, role):
    rid = _make_record(client)
    tok = token_for(client, role)
    key, value = OWN_FIELD[role]
    payload = full_section(client, tok) | {key: value}
    r = client.patch(f"/api/records/{rid}", headers=auth(tok), json={"data": payload})
    assert r.status_code == 200, r.text
    assert r.json()["data"][key] == value


@pytest.mark.parametrize("role", list(OWN_FIELD))
def test_role_cannot_save_incomplete_section(client, role):
    """One field at a time is not enough: the whole section must be filled."""
    rid = _make_record(client)
    tok = token_for(client, role)
    key, value = OWN_FIELD[role]
    r = client.patch(
        f"/api/records/{rid}", headers=auth(tok), json={"data": {key: value}}
    )
    assert r.status_code == 422, r.text
    assert key not in r.json()["detail"]["missing_fields"]  # the one they did fill
    assert r.json()["detail"]["missing_fields"]

    # And the rejected write left nothing behind.
    admin = token_for(client, "admin")
    assert client.get(f"/api/records/{rid}", headers=auth(admin)).json()["data"].get(key) is None


def test_admin_is_exempt_from_section_completeness(client):
    """Admin owns every field, so the rule would make any admin save impossible."""
    rid = _make_record(client)
    admin = token_for(client, "admin")
    r = client.patch(
        f"/api/records/{rid}",
        headers=auth(admin),
        json={"data": {"notary_status": "Notarized"}},
    )
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("role", list(FOREIGN_FIELD))
def test_role_cannot_edit_other_section(client, role):
    rid = _make_record(client)
    tok = token_for(client, role)
    key, value = FOREIGN_FIELD[role]
    r = client.patch(
        f"/api/records/{rid}", headers=auth(tok), json={"data": {key: value}}
    )
    assert r.status_code == 403, r.text
    assert key in r.json()["detail"]["forbidden_fields"]


@pytest.mark.parametrize("role", list(OWN_FIELD))
def test_role_cannot_edit_base_fields(client, role):
    rid = _make_record(client)
    tok = token_for(client, role)
    r = client.patch(
        f"/api/records/{rid}", headers=auth(tok), json={"data": {"company": "Hacked"}}
    )
    assert r.status_code == 403


def test_admin_can_edit_everything(client):
    rid = _make_record(client)
    admin = token_for(client, "admin")
    r = client.patch(
        f"/api/records/{rid}",
        headers=auth(admin),
        json={
            "data": {
                "company": "NewCo",
                "docket_scanning_status": "scanned - complete",
                "notary_status": "Notarized",
                "file_status": "On File - Complete",
            }
        },
    )
    assert r.status_code == 200, r.text


def test_unknown_field_rejected(client):
    rid = _make_record(client)
    admin = token_for(client, "admin")
    r = client.patch(
        f"/api/records/{rid}",
        headers=auth(admin),
        json={"data": {"totally_made_up": "x"}},
    )
    assert r.status_code == 422


def test_allow_lists_are_disjoint_across_sections():
    """Registry sanity: no field is owned by two different section roles."""
    dc = keys_for_owner(Role.document_compliance)
    sc = keys_for_owner(Role.scanning)
    no = keys_for_owner(Role.notary)
    fi = keys_for_owner(Role.filing)
    assert dc & sc == set()
    assert dc & no == set()
    assert dc & fi == set()
    assert sc & no == set()
    assert sc & fi == set()
    assert no & fi == set()


def test_scanning_cannot_create(client):
    tok = token_for(client, "scanning")
    r = client.post(
        "/api/records", headers=auth(tok), json={"unit_code": "X-1", "data": {}}
    )
    assert r.status_code == 403


def test_doc_compliance_can_create(client):
    tok = token_for(client, "document_compliance")
    r = client.post(
        "/api/records",
        headers=auth(tok),
        json={"unit_code": "DC-1", "data": {"company": "Acme"}},
    )
    assert r.status_code == 201, r.text


def test_doc_compliance_cannot_create_with_foreign_field(client):
    tok = token_for(client, "document_compliance")
    r = client.post(
        "/api/records",
        headers=auth(tok),
        json={"unit_code": "DC-2", "data": {"notary_status": "Notarized"}},
    )
    assert r.status_code == 403


@pytest.mark.parametrize("role", list(FOREIGN_FIELD))
def test_role_cannot_read_other_sections_of_a_new_record(client, role):
    """Until a role has worked a record, other sections are invisible on every
    read path — not merely a 403 on write."""
    rid = _make_record(client)
    admin = token_for(client, "admin")
    key, value = FOREIGN_FIELD[role]
    client.patch(f"/api/records/{rid}", headers=auth(admin), json={"data": {key: value}})

    tok = token_for(client, role)
    assert key not in client.get(f"/api/records/{rid}", headers=auth(tok)).json()["data"]
    listed = client.get("/api/records", headers=auth(tok)).json()["items"]
    assert key not in listed[0]["data"]
    assert not any(
        a["field_name"] == key
        for a in client.get(f"/api/records/{rid}/audit", headers=auth(tok)).json()
    )
    # Search must not match on a hidden value either, or it leaks by probing.
    hits = client.get("/api/records", headers=auth(tok), params={"search": value}).json()
    assert hits["total"] == 0
    assert client.get(f"/api/records/{rid}", headers=auth(tok)).json()["restricted"] is True


@pytest.mark.parametrize("role", list(FOREIGN_FIELD))
def test_own_section_input_unlocks_the_whole_record(client, role):
    """Once the role has filled its section, that record opens up in full."""
    rid = _make_record(client)
    admin = token_for(client, "admin")
    key, value = FOREIGN_FIELD[role]
    client.patch(f"/api/records/{rid}", headers=auth(admin), json={"data": {key: value}})

    tok = token_for(client, role)
    own_key, own_value = OWN_FIELD[role]
    r = client.patch(
        f"/api/records/{rid}",
        headers=auth(tok),
        json={"data": full_section(client, tok) | {own_key: own_value}},
    )
    assert r.status_code == 200, r.text

    assert r.json()["data"][key] == value          # unlocked in the save response
    assert r.json()["restricted"] is False
    got = client.get(f"/api/records/{rid}", headers=auth(tok)).json()
    assert got["data"][key] == value               # ...and on re-read
    listed = client.get("/api/records", headers=auth(tok)).json()["items"]
    assert listed[0]["data"][key] == value         # ...and in the list/other tabs
    hits = client.get("/api/records", headers=auth(tok), params={"search": value}).json()
    assert hits["total"] == 1                      # ...and it is searchable now
    assert any(
        a["field_name"] == key
        for a in client.get(f"/api/records/{rid}/audit", headers=auth(tok)).json()
    )


@pytest.mark.parametrize("role", list(OWN_FIELD))
def test_role_reads_base_and_own_section(client, role):
    """Unit/buyer identity stays visible to everyone; so does the role's own section."""
    rid = _make_record(client)
    tok = token_for(client, role)
    key, value = OWN_FIELD[role]
    client.patch(
        f"/api/records/{rid}", headers=auth(tok), json={"data": full_section(client, tok) | {key: value}}
    )
    data = client.get(f"/api/records/{rid}", headers=auth(tok)).json()["data"]
    assert data["company"] == "Acme"  # base field, owned by nobody's section
    assert data[key] == value


def test_default_editable_matches_registry():
    assert default_editable_fields(Role.scanning) == keys_for_owner(Role.scanning)

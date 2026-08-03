from tests.conftest import auth, token_for


def test_register_creates_inactive_roleless(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "new@example.com", "password": "Secret123", "full_name": "New"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["is_active"] is False
    assert body["role"] is None


def test_register_accepts_any_password(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "weak@t.example.com", "password": "a"},
    )
    assert r.status_code == 201, r.text


def test_inactive_user_cannot_login(client):
    client.post(
        "/api/auth/register",
        json={"email": "pending@t.example.com", "password": "Secret123"},
    )
    r = client.post(
        "/api/auth/login",
        data={"username": "pending@t.example.com", "password": "Secret123"},
    )
    assert r.status_code == 403


def test_admin_activates_and_assigns_role(client):
    client.post(
        "/api/auth/register",
        json={"email": "pending2@t.example.com", "password": "Secret123"},
    )
    admin = token_for(client, "admin")
    users = client.get("/api/users", headers=auth(admin)).json()
    uid = next(u["id"] for u in users if u["email"] == "pending2@t.example.com")
    r = client.patch(
        f"/api/users/{uid}",
        headers=auth(admin),
        json={"role": "scanning", "is_active": True},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "scanning"
    assert r.json()["is_active"] is True
    # now they can log in
    login = client.post(
        "/api/auth/login",
        data={"username": "pending2@t.example.com", "password": "Secret123"},
    )
    assert login.status_code == 200


def test_non_admin_cannot_manage_users(client):
    scanning = token_for(client, "scanning")
    assert client.get("/api/users", headers=auth(scanning)).status_code == 403


def test_register_accepts_internal_local_domain(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "leo.phirst@records.local", "password": "abc123"},
    )
    assert r.status_code == 201, r.text


def test_online_lists_caller_for_any_role(client):
    """Presence is visible to every role, not just admin, and logging in puts
    you on the list immediately."""
    scanning = token_for(client, "scanning")
    r = client.get("/api/meta/online", headers=auth(scanning))
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [u["role"] for u in rows] == ["scanning"]
    assert set(rows[0]) == {"id", "full_name", "role", "last_seen"}  # no email leak

    # a second user shows up for the first
    token_for(client, "notary")
    roles = {u["role"] for u in client.get("/api/meta/online", headers=auth(scanning)).json()}
    assert roles == {"scanning", "notary"}


def test_online_excludes_users_idle_past_the_window(client):
    from datetime import timedelta

    from app.models import User, utcnow
    from app.routers.meta import ONLINE_WINDOW_MINUTES
    from tests.conftest import TestingSessionLocal

    admin = token_for(client, "admin")
    db = TestingSessionLocal()
    stale = utcnow() - timedelta(minutes=ONLINE_WINDOW_MINUTES + 1)
    for u in db.query(User).all():
        u.last_seen = stale
    db.commit()
    db.close()

    # The admin's own request re-stamps them, so only they come back.
    assert [u["role"] for u in client.get("/api/meta/online", headers=auth(admin)).json()] == [
        "admin"
    ]

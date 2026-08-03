from __future__ import annotations

from tests.conftest import auth, token_for


def test_post_and_read_shared_room(client):
    """One room every role can read and write, with the author denormalized in."""
    scanning = token_for(client, "scanning")
    notary = token_for(client, "notary")

    r = client.post("/api/chat", headers=auth(scanning), json={"body": "unit 4021 scanned"})
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["role"] == "scanning"

    client.post("/api/chat", headers=auth(notary), json={"body": "notarized"})

    rows = client.get("/api/chat", headers=auth(notary)).json()
    assert [m["body"] for m in rows] == ["unit 4021 scanned", "notarized"]  # oldest first

    # The poll path: nothing new after the last message the client holds.
    assert client.get("/api/chat?after=" + str(rows[-1]["id"]), headers=auth(scanning)).json() == []
    after_first = client.get(f"/api/chat?after={first['id']}", headers=auth(scanning)).json()
    assert [m["body"] for m in after_first] == ["notarized"]


def test_chat_rejects_blank_and_unauthenticated(client):
    assert client.get("/api/chat").status_code == 401
    scanning = token_for(client, "scanning")
    assert client.post("/api/chat", headers=auth(scanning), json={"body": "   "}).status_code == 422

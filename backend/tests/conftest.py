from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Point config at a throwaway SQLite file BEFORE importing the app.
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["ATTACHMENT_DIR"] = f"{_tmp}/attachments"
os.environ["JOB_DIR"] = f"{_tmp}/jobs"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["DISABLE_RATE_LIMIT"] = "1"

from app import database  # noqa: E402
from app.database import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.models import RoleFieldPermission, User  # noqa: E402
from app.rbac import default_permission_rows  # noqa: E402
from app.security import hash_password  # noqa: E402

engine = create_engine(
    os.environ["DATABASE_URL"], connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# Rebind the app's session factory/engine to the test database.
database.engine = engine
database.SessionLocal = TestingSessionLocal


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[database.get_db] = _override_get_db


ROLES = ["admin", "document_compliance", "scanning", "filing", "notary"]


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        for role, field in default_permission_rows():
            db.add(RoleFieldPermission(role=role, field_name=field))
        for role in ROLES:
            db.add(
                User(
                    email=f"{role}@t.local",
                    hashed_password=hash_password("Passw0rd1"),
                    role=role,
                    is_active=True,
                    is_superuser=(role == "admin"),
                )
            )
        db.commit()
    finally:
        db.close()
    yield


@pytest.fixture
def client():
    return TestClient(app)


def token_for(client: TestClient, role: str) -> str:
    resp = client.post(
        "/api/auth/login",
        data={"username": f"{role}@t.local", "password": "Passw0rd1"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def auth(role_token: str) -> dict:
    return {"Authorization": f"Bearer {role_token}"}


def _sample_value(f: dict):
    """A valid value for one schema field, by type."""
    if f["type"] == "enum":
        return next(o for o in f["options"] if o)
    if f["type"] == "date":
        return "2026-01-15"
    if f["type"] in ("number", "integer"):
        return 1
    if f["type"] == "email":
        return "someone@example.com"
    return "x"


def full_section(client: TestClient, token: str) -> dict:
    """Every field the caller's role must fill, populated — a role can only
    save once its whole section is complete (rbac.assert_own_section_complete).
    """
    fields = client.get("/api/meta/schema", headers=auth(token)).json()["fields"]
    return {f["key"]: _sample_value(f) for f in fields if f["required"]}

"""Bootstrap the database: create tables, seed role_field_permissions, and
create the first admin from env vars (so an initial admin exists without
self-registration).

Run:  python -m scripts.seed
"""

from __future__ import annotations

from sqlalchemy import select

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import RoleFieldPermission, User
from app.rbac import default_permission_rows
from app.security import hash_password


def seed_permissions(db) -> tuple[int, int]:
    """Reconcile role_field_permissions with the registry defaults.

    Stale rows are deleted, not just missing ones added: when a field changes
    owner in fields.py, an insert-only seed would leave the old role still able
    to write it. Nothing but this script writes the table, so there are no
    hand-made rows to preserve.
    """
    rows = db.execute(select(RoleFieldPermission)).scalars().all()
    existing = {(r.role, r.field_name): r for r in rows}
    wanted = set(default_permission_rows())
    added = removed = 0
    for pair in wanted - set(existing):
        db.add(RoleFieldPermission(role=pair[0], field_name=pair[1]))
        added += 1
    for pair in set(existing) - wanted:
        db.delete(existing[pair])
        removed += 1
    db.commit()
    return added, removed


def seed_admin(db) -> str:
    email = settings.first_admin_email.lower()
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing:
        return f"Admin '{email}' already exists — skipped."
    admin = User(
        email=email,
        hashed_password=hash_password(settings.first_admin_password),
        full_name="Administrator",
        role="admin",
        is_active=True,
        is_superuser=True,
    )
    db.add(admin)
    db.commit()
    return f"Created admin '{email}'."


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        added, removed = seed_permissions(db)
        msg = seed_admin(db)
        print(f"Role-field permissions: +{added} / -{removed}.")
        print(msg)
    finally:
        db.close()


if __name__ == "__main__":
    main()

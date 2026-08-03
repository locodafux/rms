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


def seed_permissions(db) -> int:
    existing = {
        (r.role, r.field_name)
        for r in db.execute(select(RoleFieldPermission)).scalars().all()
    }
    added = 0
    for role, field_name in default_permission_rows():
        if (role, field_name) not in existing:
            db.add(RoleFieldPermission(role=role, field_name=field_name))
            added += 1
    db.commit()
    return added


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
        n = seed_permissions(db)
        msg = seed_admin(db)
        print(f"Seeded {n} role-field permission rows.")
        print(msg)
    finally:
        db.close()


if __name__ == "__main__":
    main()

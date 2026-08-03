"""Create one ACTIVE demo user per role for local testing.

Run:  python -m scripts.seed_demo
These are convenience accounts for development only — do not use in production.
"""

from __future__ import annotations

from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.fields import Role
from app.models import User
from app.security import hash_password

# email -> (role, password)
DEMO_USERS = {
    "sj.phirst@records.local": (Role.document_compliance, "compliance"),
    "mildred.phirst@records.local": (Role.scanning, "scanning"),
    "arnold.phirst@records.local": (Role.filing, "filing"),
    "chester.phirst@records.local": (Role.notary, "notary"),
}


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        for email, (role, password) in DEMO_USERS.items():
            exists = db.execute(
                select(User).where(User.email == email)
            ).scalar_one_or_none()
            if exists:
                print(f"· {email} already exists — skipped")
                continue
            db.add(
                User(
                    email=email,
                    hashed_password=hash_password(password),
                    full_name=role.value.replace("_", " ").title(),
                    role=role.value,
                    is_active=True,
                )
            )
            print(f"✓ created {email}  ({role.value})  password: {password}")
        db.commit()
    finally:
        db.close()

    print("\nDemo logins:")
    print("  ann.phirst@records.local    / annle             (admin)")
    for email, (role, password) in DEMO_USERS.items():
        print(f"  {email:<28}/ {password:<18}({role.value})")


if __name__ == "__main__":
    main()

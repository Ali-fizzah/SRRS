"""The two extra users the viva demo needs (task P8-T2). Safe to run any number of times.

A journal batch must be approved by someone other than whoever generated it (D13), so the demo
needs more than the admin. These passwords are in docs/demo-viva.md: this is for demonstrations
only, never for real data.

Run from backend/ so `app` is importable:
    python ../tools/seed_demo_users.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.audit import write_audit  # noqa: E402
from app.auth.passwords import hash_password  # noqa: E402
from app.models import Role, User, UserRole  # noqa: E402

DEMO_USERS = [
    ("accountant@revrec.local", "Asha Accountant", "Accountant-Viva1", "ACCOUNTANT"),
    ("approver@revrec.local", "Amir Approver", "Approver-Viva-01", "APPROVER"),
]


def seed_demo_users(db: Session) -> list[str]:
    """Add the demo users that are missing. Returns the emails created."""
    created = []
    for email, name, password, role_name in DEMO_USERS:
        if db.scalar(select(User.id).where(User.email == email)) is not None:
            continue
        role_id = db.scalar(select(Role.id).where(Role.name == role_name))
        if role_id is None:
            raise SystemExit(f"{role_name} role missing: run `make migrate` first")
        user = User(email=email, full_name=name, password_hash=hash_password(password))
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=role_id))
        write_audit(
            db,
            user_id=None,
            action="USER_SEEDED",
            entity_type="user",
            entity_id=user.id,
            after={"email": email, "full_name": name, "roles": [role_name]},
        )
        created.append(email)
    return created


def main() -> int:
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        created = seed_demo_users(db)
        db.commit()
    print(f"demo users created: {', '.join(created) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

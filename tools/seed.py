"""Seed reference data (`make seed`). Safe to run any number of times.

Run from backend/ so `app` is importable:
    python ../tools/seed.py

P1-T3: the first ADMIN user (REVREC_ADMIN_EMAIL / REVREC_ADMIN_PASSWORD).
P1-T4 adds the chart of accounts, default GL mappings and accounting periods.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.audit import write_audit  # noqa: E402
from app.auth.passwords import hash_password  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.models import Role, User, UserRole  # noqa: E402


def seed_admin(db: Session, settings: Settings) -> bool:
    """Create the admin user unless that email exists. Returns True if created."""
    email = settings.admin_email.lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        return False
    admin_role = db.scalar(select(Role.id).where(Role.name == "ADMIN"))
    if admin_role is None:
        raise SystemExit("ADMIN role missing: run `make migrate` first")
    user = User(
        email=email,
        full_name=settings.admin_name,
        password_hash=hash_password(settings.admin_password),
    )
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=admin_role))
    write_audit(
        db,
        user_id=None,
        action="USER_SEEDED",
        entity_type="user",
        entity_id=user.id,
        after={"email": email, "full_name": settings.admin_name, "roles": ["ADMIN"]},
    )
    return True


def main() -> int:
    from app.db.session import SessionLocal

    settings = get_settings()
    with SessionLocal() as db:
        created = seed_admin(db, settings)
        db.commit()
    print(f"admin {settings.admin_email}: {'created' if created else 'already exists'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

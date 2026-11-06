"""Seed reference data (`make seed`). Safe to run any number of times.

Run from backend/ so `app` is importable:
    python ../tools/seed.py

Creates only what is missing and never overwrites existing rows, so edits made in
the app and real period closes survive a re-run.

- the first ADMIN user (REVREC_ADMIN_EMAIL / REVREC_ADMIN_PASSWORD)       P1-T3
- the default chart of accounts (plan §5.7)                               P1-T4
- default GL mappings for the balance-sheet roles (D12)                   P1-T4
- accounting periods 2025-01..2028-12; the current one OPEN (D6)          P1-T4
  (REVREC_CURRENT_PERIOD, default: this month). Earlier months are
  CLOSED, later months FUTURE.
"""

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path.cwd()))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.audit import write_audit  # noqa: E402
from app.auth.passwords import hash_password  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.engine.periods import iter_periods, parse_period, period_bounds  # noqa: E402
from app.models import (  # noqa: E402
    AccountingPeriod,
    GlAccount,
    GlMapping,
    Role,
    User,
    UserRole,
)
from app.models.enums import AccountRole, GlAccountType, PeriodStatus  # noqa: E402

# Plan §5.7: default chart of accounts (seeded, editable).
CHART_OF_ACCOUNTS = [
    ("1100", "Accounts Receivable", GlAccountType.ASSET),
    ("1150", "Unbilled Receivable", GlAccountType.ASSET),
    ("2400", "Deferred Revenue", GlAccountType.LIABILITY),
    ("4100", "Subscription Revenue", GlAccountType.REVENUE),
    ("4200", "Print / Hardware Revenue", GlAccountType.REVENUE),
    ("4300", "Professional Services Revenue", GlAccountType.REVENUE),
]

# D12 default mappings (product and category both empty). REVENUE has no default:
# every product names its own revenue account (products template, plan §7).
DEFAULT_MAPPINGS = {
    AccountRole.AR: "1100",
    AccountRole.UNBILLED_AR: "1150",
    AccountRole.DEFERRED_REVENUE: "2400",
}

# P1-T4: periods 2025-01 -> 2028-12.
FIRST_PERIOD = "202501"
LAST_PERIOD = "202812"


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


def seed_accounts(db: Session) -> list[str]:
    """Add missing default accounts. Returns the account codes created."""
    existing = set(db.scalars(select(GlAccount.account_code)))
    created = []
    for code, name, account_type in CHART_OF_ACCOUNTS:
        if code not in existing:
            db.add(GlAccount(account_code=code, name=name, type=account_type))
            created.append(code)
    if created:
        db.flush()
        write_audit(
            db,
            user_id=None,
            action="GL_ACCOUNTS_SEEDED",
            entity_type="gl_account",
            entity_id=None,
            after={"created": created},
        )
    return created


def seed_gl_mappings(db: Session) -> list[str]:
    """Add missing default role mappings. Returns the roles created."""
    accounts = dict(db.execute(select(GlAccount.account_code, GlAccount.id)).tuples().all())
    has_default = set(
        db.scalars(
            select(GlMapping.account_role).where(
                GlMapping.product_id.is_(None), GlMapping.product_category.is_(None)
            )
        )
    )
    created = []
    for role, code in DEFAULT_MAPPINGS.items():
        if role in has_default:
            continue
        if code not in accounts:
            raise SystemExit(f"account {code} for the default {role} mapping does not exist")
        db.add(GlMapping(account_role=role, account_id=accounts[code]))
        created.append(role.value)
    if created:
        db.flush()
        write_audit(
            db,
            user_id=None,
            action="GL_MAPPINGS_SEEDED",
            entity_type="gl_mapping",
            entity_id=None,
            after={"created": {r: DEFAULT_MAPPINGS[AccountRole(r)] for r in created}},
        )
    return created


def seed_periods(db: Session, current: str) -> list[str]:
    """Add missing periods FIRST_PERIOD..LAST_PERIOD. Returns the keys created.

    The OPEN period already in the database wins over `current`, so a re-run never
    moves the current period. New periods before it are CLOSED, after it FUTURE.
    """
    parse_period(current)
    if not FIRST_PERIOD <= current <= LAST_PERIOD:
        raise SystemExit(
            f"REVREC_CURRENT_PERIOD {current} is outside {FIRST_PERIOD}..{LAST_PERIOD}"
        )
    existing = set(db.scalars(select(AccountingPeriod.period_key)))
    open_now = db.scalar(
        select(AccountingPeriod.period_key).where(AccountingPeriod.status == PeriodStatus.OPEN)
    )
    anchor = open_now or current

    created = []
    for key in iter_periods(FIRST_PERIOD, LAST_PERIOD):
        if key in existing:
            continue
        if key < anchor:
            status = PeriodStatus.CLOSED
        elif key == anchor and open_now is None:
            status = PeriodStatus.OPEN
        else:
            status = PeriodStatus.FUTURE
        start, end = period_bounds(key)
        db.add(AccountingPeriod(period_key=key, start_date=start, end_date=end, status=status))
        created.append(key)
    if created:
        db.flush()
        write_audit(
            db,
            user_id=None,
            action="PERIODS_SEEDED",
            entity_type="accounting_period",
            entity_id=None,
            after={"created": len(created), "first": created[0], "last": created[-1],
                   "open": anchor},
        )  # fmt: skip
    return created


def seed_all(db: Session, settings: Settings) -> dict[str, Any]:
    """Every seed step, in dependency order. The caller commits."""
    return {
        "admin": seed_admin(db, settings),
        "accounts": seed_accounts(db),
        "gl_mappings": seed_gl_mappings(db),
        "periods": seed_periods(db, settings.current_period),
    }


def main() -> int:
    from app.db.session import SessionLocal

    settings = get_settings()
    with SessionLocal() as db:
        result = seed_all(db, settings)
        db.commit()
        open_period = db.scalar(
            select(AccountingPeriod.period_key).where(AccountingPeriod.status == PeriodStatus.OPEN)
        )
    periods = result["periods"]
    print(f"admin {settings.admin_email}: {'created' if result['admin'] else 'already exists'}")
    print(f"gl accounts created: {', '.join(result['accounts']) or 'none'}")
    print(f"gl mappings created: {', '.join(result['gl_mappings']) or 'none'}")
    print(
        f"periods created: {len(periods)}"
        + (f" ({periods[0]}..{periods[-1]})" if periods else "")
        + f"; current OPEN period: {open_period}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

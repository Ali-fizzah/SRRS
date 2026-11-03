"""`make seed` (tools/seed.py): admin (P1-T3), accounts, mappings, periods (P1-T4).

Every test runs inside the rolled-back test transaction, so the seed starts from
an empty database each time.
"""

import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AccountingPeriod, AuditLog, GlAccount, GlMapping, User

REPO = Path(__file__).resolve().parents[3]


def _seed_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed", REPO / "tools" / "seed.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


seed = _seed_module()
SETTINGS = Settings(
    admin_email="Seed.Admin@test.local", admin_password="Seed-Pass-123", current_period="202611"
)


def _count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def _statuses(db: Session) -> dict[str, str]:
    rows = db.execute(select(AccountingPeriod.period_key, AccountingPeriod.status))
    return {key: status.value for key, status in rows}


# --------------------------------------------------------------------------- P1-T3


def test_seed_admin_is_idempotent_and_can_sign_in(client: TestClient, db: Session) -> None:
    assert seed.seed_admin(db, SETTINGS) is True
    assert seed.seed_admin(db, SETTINGS) is False  # second run changes nothing
    count = db.scalar(select(func.count()).where(User.email == "seed.admin@test.local"))
    assert count == 1

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "seed.admin@test.local", "password": "Seed-Pass-123"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["roles"] == ["ADMIN"]


# --------------------------------------------------------------------------- P1-T4


def test_seed_all_twice_creates_everything_once(db: Session) -> None:
    first = seed.seed_all(db, SETTINGS)
    assert first["accounts"] == ["1100", "1150", "2400", "4100", "4200", "4300"]
    assert sorted(first["gl_mappings"]) == ["AR", "DEFERRED_REVENUE", "UNBILLED_AR"]
    assert len(first["periods"]) == 48

    second = seed.seed_all(db, SETTINGS)
    assert second == {"admin": False, "accounts": [], "gl_mappings": [], "periods": []}
    assert _count(db, GlAccount) == 6
    assert _count(db, GlMapping) == 3
    assert _count(db, AccountingPeriod) == 48


def test_chart_of_accounts_matches_plan(db: Session) -> None:
    seed.seed_accounts(db)
    rows = db.execute(select(GlAccount.account_code, GlAccount.name, GlAccount.type))
    assert {(code, name, t.value) for code, name, t in rows} == {
        ("1100", "Accounts Receivable", "ASSET"),
        ("1150", "Unbilled Receivable", "ASSET"),
        ("2400", "Deferred Revenue", "LIABILITY"),
        ("4100", "Subscription Revenue", "REVENUE"),
        ("4200", "Print / Hardware Revenue", "REVENUE"),
        ("4300", "Professional Services Revenue", "REVENUE"),
    }


def test_default_mappings_point_at_balance_sheet_accounts(db: Session) -> None:
    seed.seed_accounts(db)
    seed.seed_gl_mappings(db)
    rows = db.execute(
        select(GlMapping.account_role, GlAccount.account_code, GlMapping.product_id).join(
            GlAccount, GlAccount.id == GlMapping.account_id
        )
    )
    assert {(role.value, code, product) for role, code, product in rows} == {
        ("AR", "1100", None),
        ("UNBILLED_AR", "1150", None),
        ("DEFERRED_REVENUE", "2400", None),
    }


def test_periods_closed_before_current_open_now_future_after(db: Session) -> None:
    seed.seed_periods(db, "202611")
    statuses = _statuses(db)
    assert sorted(statuses) == [
        f"{y}{m:02d}" for y in (2025, 2026, 2027, 2028) for m in range(1, 13)
    ]
    assert [k for k, s in statuses.items() if s == "OPEN"] == ["202611"]  # D6
    assert all(s == "CLOSED" for k, s in statuses.items() if k < "202611")
    assert all(s == "FUTURE" for k, s in statuses.items() if k > "202611")

    feb_2028 = db.scalar(select(AccountingPeriod).where(AccountingPeriod.period_key == "202802"))
    assert feb_2028 is not None
    assert (feb_2028.start_date, feb_2028.end_date) == (date(2028, 2, 1), date(2028, 2, 29))


def test_rerun_never_moves_the_current_period_or_overwrites_edits(db: Session) -> None:
    seed.seed_all(db, SETTINGS)
    # The team renames an account and closes November; December becomes current.
    db.execute(update(GlAccount).where(GlAccount.account_code == "4100").values(name="SaaS"))
    db.execute(
        update(AccountingPeriod)
        .where(AccountingPeriod.period_key == "202611")
        .values(status="CLOSED")
    )
    db.execute(
        update(AccountingPeriod)
        .where(AccountingPeriod.period_key == "202612")
        .values(status="OPEN")
    )
    seed.seed_all(db, SETTINGS)  # still says 202611
    assert db.scalar(select(GlAccount.name).where(GlAccount.account_code == "4100")) == "SaaS"
    assert [k for k, s in _statuses(db).items() if s == "OPEN"] == ["202612"]


def test_missing_periods_fill_in_around_the_open_one(db: Session) -> None:
    db.add(
        AccountingPeriod(
            period_key="202603",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 31),
            status="OPEN",
        )
    )
    db.flush()
    created = seed.seed_periods(db, "202611")
    assert len(created) == 47
    statuses = _statuses(db)
    assert statuses["202602"] == "CLOSED" and statuses["202603"] == "OPEN"
    assert statuses["202604"] == "FUTURE"


@pytest.mark.parametrize("bad", ["202412", "202901"])
def test_current_period_must_be_in_the_seeded_range(db: Session, bad: str) -> None:
    with pytest.raises(SystemExit):
        seed.seed_periods(db, bad)


def test_seed_steps_are_audited(db: Session) -> None:
    seed.seed_all(db, SETTINGS)
    actions = set(db.scalars(select(AuditLog.action)))
    assert {"USER_SEEDED", "GL_ACCOUNTS_SEEDED", "GL_MAPPINGS_SEEDED", "PERIODS_SEEDED"} <= actions


def test_database_allows_only_one_open_period(conn: Connection, db: Session) -> None:
    """D6, enforced by the uq_accounting_periods_one_open index."""
    seed.seed_periods(db, "202611")
    periods = AccountingPeriod.__table__
    with pytest.raises(IntegrityError), conn.begin_nested():
        conn.execute(
            insert(periods).values(
                period_key="202901",
                start_date=date(2029, 1, 1),
                end_date=date(2029, 1, 31),
                status="OPEN",
            )
        )


def test_new_period_defaults_to_future(conn: Connection) -> None:
    periods = AccountingPeriod.__table__
    status = conn.execute(
        insert(periods)
        .values(period_key="203001", start_date=date(2030, 1, 1), end_date=date(2030, 1, 31))
        .returning(periods.c.status)
    ).scalar_one()
    assert status == "FUTURE"

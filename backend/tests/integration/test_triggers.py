"""P1-T2: the database refuses to change posted or closed data (plan §6.3, §5.7).

Each test builds the rows it needs inside a transaction that the `conn` fixture rolls back.
A blocked statement runs in a savepoint so the test can keep using the connection.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Connection, Table, delete, insert, select, update
from sqlalchemy.exc import DBAPIError

import app.models  # noqa: F401  (registers every table)
from app.db.base import Base
from app.db.errors import DbRuleViolation

T = Base.metadata.tables


def add(conn: Connection, table: str, **values: Any) -> int:
    return int(
        conn.execute(insert(T[table]).values(**values).returning(T[table].c.id)).scalar_one()
    )


@contextmanager
def refused(conn: Connection, code: DbRuleViolation) -> Iterator[None]:
    """Expect the statements inside to be refused by a trigger with this SQLSTATE."""
    with pytest.raises(DBAPIError) as exc_info, conn.begin_nested():
        yield
    assert getattr(exc_info.value.orig, "sqlstate", None) == code.value, exc_info.value


def set_status(conn: Connection, table: str, row_id: int, status: str) -> None:
    t: Table = T[table]
    conn.execute(update(t).where(t.c.id == row_id).values(status=status))


# --------------------------------------------------------------------------- data builders


@pytest.fixture
def ids(conn: Connection) -> dict[str, int]:
    """Minimal graph: user, accounts, product, contract + version, open period."""
    out: dict[str, int] = {}
    out["user"] = add(conn, "users", email="t@example.com", full_name="Test", password_hash="x")
    out["ar"] = add(conn, "gl_accounts", account_code="1100", name="AR", type="ASSET")
    out["rev"] = add(conn, "gl_accounts", account_code="4100", name="Revenue", type="REVENUE")
    out["customer"] = add(conn, "customers", customer_code="C1", name="Cust", country="US")
    out["product"] = add(
        conn,
        "products",
        product_code="P1",
        name="Sub",
        list_price=Decimal("100.00"),
        recognition_method="RATABLE_MONTHLY",
        is_separate_obligation=True,
        revenue_account_id=out["rev"],
    )
    out["contract"] = add(conn, "contracts", contract_code="K1", customer_id=out["customer"])
    out["version"] = add(
        conn,
        "contract_versions",
        contract_id=out["contract"],
        version_no=1,
        event_type="NEW",
        effective_date=date(2026, 1, 1),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        transaction_price=Decimal("1200.00"),
        booked_period="202601",
    )
    out["period"] = add(
        conn,
        "accounting_periods",
        period_key="202601",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )
    return out


def make_batch(
    conn: Connection, ids: dict[str, int], debit: str = "100.00", credit: str = "100.00"
) -> dict[str, int]:
    """DRAFT batch with one entry: Dr AR `debit` / Cr Revenue `credit`."""
    batch = add(
        conn, "journal_batches", period_id=ids["period"], batch_no=1, generated_by=ids["user"]
    )
    entry = add(
        conn,
        "journal_entries",
        batch_id=batch,
        entry_type="INVOICE",
        entry_date=date(2026, 1, 31),
        contract_id=ids["contract"],
        contract_version_id=ids["version"],
        source_type="invoice",
    )
    dr = add(conn, "journal_lines", entry_id=entry, account_id=ids["ar"], debit=Decimal(debit))
    cr = add(conn, "journal_lines", entry_id=entry, account_id=ids["rev"], credit=Decimal(credit))
    return {"batch": batch, "entry": entry, "dr": dr, "cr": cr}


@pytest.fixture
def posted(conn: Connection, ids: dict[str, int]) -> dict[str, int]:
    rows = make_batch(conn, ids)
    set_status(conn, "journal_batches", rows["batch"], "POSTED")
    return rows


def make_schedule_line(conn: Connection, ids: dict[str, int]) -> int:
    line = add(
        conn,
        "contract_lines",
        contract_version_id=ids["version"],
        line_no=1,
        product_id=ids["product"],
        quantity=Decimal(1),
        unit_price=Decimal("1200.00"),
        net_price=Decimal("1200.00"),
        service_start=date(2026, 1, 1),
        service_end=date(2026, 12, 31),
    )
    po = add(
        conn,
        "performance_obligations",
        contract_version_id=ids["version"],
        contract_line_id=line,
        product_id=ids["product"],
        method="RATABLE_MONTHLY",
        ssp_amount=Decimal("1200.00"),
        allocated_amount=Decimal("1200.00"),
        service_start=date(2026, 1, 1),
        service_end=date(2026, 12, 31),
    )
    schedule = add(
        conn, "revenue_schedules", performance_obligation_id=po, contract_version_id=ids["version"]
    )
    return add(
        conn,
        "schedule_lines",
        schedule_id=schedule,
        service_period="202601",
        amount=Decimal("100.00"),
    )


# --------------------------------------------------------------------------- rule 1 + §5.7


def test_posted_entry_cannot_be_updated_or_deleted(
    conn: Connection, posted: dict[str, int]
) -> None:
    je = T["journal_entries"]
    with refused(conn, DbRuleViolation.POSTED_JOURNAL_READ_ONLY):
        conn.execute(update(je).where(je.c.id == posted["entry"]).values(description="edited"))
    with refused(conn, DbRuleViolation.POSTED_JOURNAL_READ_ONLY):
        conn.execute(delete(je).where(je.c.id == posted["entry"]))


def test_posted_line_cannot_be_updated_or_deleted(conn: Connection, posted: dict[str, int]) -> None:
    jl = T["journal_lines"]
    with refused(conn, DbRuleViolation.POSTED_JOURNAL_READ_ONLY):
        conn.execute(update(jl).where(jl.c.id == posted["dr"]).values(debit=Decimal("1.00")))
    with refused(conn, DbRuleViolation.POSTED_JOURNAL_READ_ONLY):
        conn.execute(delete(jl).where(jl.c.id == posted["cr"]))


def test_nothing_can_be_added_to_a_posted_batch(
    conn: Connection, ids: dict[str, int], posted: dict[str, int]
) -> None:
    with refused(conn, DbRuleViolation.POSTED_JOURNAL_READ_ONLY):
        add(conn, "journal_lines", entry_id=posted["entry"], account_id=ids["ar"], debit=Decimal(5))
    with refused(conn, DbRuleViolation.POSTED_JOURNAL_READ_ONLY):
        add(
            conn,
            "journal_entries",
            batch_id=posted["batch"],
            entry_type="ADJUSTMENT",
            entry_date=date(2026, 1, 31),
            contract_id=ids["contract"],
            contract_version_id=ids["version"],
            source_type="manual",
        )


def test_posted_batch_is_read_only(conn: Connection, posted: dict[str, int]) -> None:
    jb = T["journal_batches"]
    with refused(conn, DbRuleViolation.POSTED_JOURNAL_READ_ONLY):
        set_status(conn, "journal_batches", posted["batch"], "DRAFT")
    with refused(conn, DbRuleViolation.POSTED_JOURNAL_READ_ONLY):
        conn.execute(delete(jb).where(jb.c.id == posted["batch"]))


def test_draft_batch_can_be_edited_and_regenerated(conn: Connection, ids: dict[str, int]) -> None:
    """Plan §5.7: a DRAFT batch can be regenerated (deleted and rebuilt)."""
    rows = make_batch(conn, ids)
    jl, je, jb = T["journal_lines"], T["journal_entries"], T["journal_batches"]
    conn.execute(update(jl).where(jl.c.id == rows["dr"]).values(debit=Decimal("90.00")))
    conn.execute(delete(jl).where(jl.c.entry_id == rows["entry"]))
    conn.execute(delete(je).where(je.c.id == rows["entry"]))
    conn.execute(delete(jb).where(jb.c.id == rows["batch"]))
    assert conn.execute(select(jb.c.id).where(jb.c.id == rows["batch"])).first() is None


# --------------------------------------------------------------------------- rule 2


def test_unbalanced_batch_cannot_be_posted(conn: Connection, ids: dict[str, int]) -> None:
    rows = make_batch(conn, ids, debit="100.00", credit="99.99")
    with refused(conn, DbRuleViolation.BATCH_NOT_BALANCED):
        set_status(conn, "journal_batches", rows["batch"], "POSTED")


def test_balanced_batch_can_be_approved_and_posted(conn: Connection, ids: dict[str, int]) -> None:
    rows = make_batch(conn, ids)
    set_status(conn, "journal_batches", rows["batch"], "APPROVED")
    set_status(conn, "journal_batches", rows["batch"], "POSTED")
    jb = T["journal_batches"]
    status = conn.execute(select(jb.c.status).where(jb.c.id == rows["batch"])).scalar_one()
    assert status == "POSTED"


# --------------------------------------------------------------------------- rule 3


def test_no_batch_in_a_closed_period(conn: Connection, ids: dict[str, int]) -> None:
    set_status(conn, "accounting_periods", ids["period"], "CLOSED")
    with refused(conn, DbRuleViolation.PERIOD_CLOSED):
        add(conn, "journal_batches", period_id=ids["period"], batch_no=1, generated_by=ids["user"])


@pytest.mark.parametrize("status", ["OPEN", "CLOSING"])
def test_batch_allowed_in_open_or_closing_period(
    conn: Connection, ids: dict[str, int], status: str
) -> None:
    set_status(conn, "accounting_periods", ids["period"], status)
    add(conn, "journal_batches", period_id=ids["period"], batch_no=1, generated_by=ids["user"])


def test_batch_cannot_be_moved_into_a_closed_period(conn: Connection, ids: dict[str, int]) -> None:
    rows = make_batch(conn, ids)
    closed = add(
        conn,
        "accounting_periods",
        period_key="202512",
        start_date=date(2025, 12, 1),
        end_date=date(2025, 12, 31),
        status="CLOSED",
    )
    jb = T["journal_batches"]
    with refused(conn, DbRuleViolation.PERIOD_CLOSED):
        conn.execute(update(jb).where(jb.c.id == rows["batch"]).values(period_id=closed))


# --------------------------------------------------------------------------- rule 4


def test_posted_schedule_line_cannot_be_updated_or_deleted(
    conn: Connection, ids: dict[str, int]
) -> None:
    line = make_schedule_line(conn, ids)
    sl = T["schedule_lines"]
    conn.execute(  # PENDING -> POSTED is how posting works, so it is allowed
        update(sl).where(sl.c.id == line).values(status="POSTED", posting_period="202601")
    )
    with refused(conn, DbRuleViolation.POSTED_SCHEDULE_LINE):
        conn.execute(update(sl).where(sl.c.id == line).values(amount=Decimal("1.00")))
    with refused(conn, DbRuleViolation.POSTED_SCHEDULE_LINE):
        conn.execute(update(sl).where(sl.c.id == line).values(status="SUPERSEDED"))
    with refused(conn, DbRuleViolation.POSTED_SCHEDULE_LINE):
        conn.execute(delete(sl).where(sl.c.id == line))


def test_pending_schedule_line_can_be_superseded(conn: Connection, ids: dict[str, int]) -> None:
    """CLAUDE.md rule 4: contract events supersede PENDING lines."""
    line = make_schedule_line(conn, ids)
    set_status(conn, "schedule_lines", line, "SUPERSEDED")


# --------------------------------------------------------------------------- rule 5


def test_contract_versions_are_append_only(conn: Connection, ids: dict[str, int]) -> None:
    cv = T["contract_versions"]
    with refused(conn, DbRuleViolation.APPEND_ONLY):
        conn.execute(update(cv).where(cv.c.id == ids["version"]).values(booked_period="202602"))
    with refused(conn, DbRuleViolation.APPEND_ONLY):
        conn.execute(delete(cv).where(cv.c.id == ids["version"]))


def test_audit_log_is_append_only(conn: Connection, ids: dict[str, int]) -> None:
    row = add(conn, "audit_log", user_id=ids["user"], action="TEST", entity_type="test")
    al = T["audit_log"]
    with refused(conn, DbRuleViolation.APPEND_ONLY):
        conn.execute(update(al).where(al.c.id == row).values(reason="edited"))
    with refused(conn, DbRuleViolation.APPEND_ONLY):
        conn.execute(delete(al).where(al.c.id == row))

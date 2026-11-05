"""P4-T1, P4-T3, P4-T4: contract events, journal generation, lifecycle, reversal (plan §5.5-5.7)."""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.auth.roles import Role
from app.models import (
    AuditLog,
    Contract,
    ContractVersion,
    GlAccount,
    GlMapping,
    JournalBatch,
    JournalEntry,
    JournalLine,
    PerformanceObligation,
    RevenueSchedule,
    ScheduleLine,
)
from app.models.enums import (
    AccountRole,
    BatchStatus,
    ObligationStatus,
    ScheduleLineStatus,
)
from app.services.billing import balance_at, contract_balances
from app.services.journals import (
    JournalRuleError,
    approve_batch,
    generate_journals,
    post_batch,
    reverse_entry,
    send_back_batch,
)
from app.services.recognition_run import run_recognition
from tests.integration.conftest import make_user, sign_in
from tests.integration.test_catch_up_and_billing import accepted, next_month, seed, upload

PRODUCTS = (
    "SUB,Subscription,,1200.00,LIST_PRICE,,,RATABLE_MONTHLY,Y,4100,\n"
    "DAILY,Daily,,3650.00,LIST_PRICE,,,RATABLE_DAILY,Y,4100,\n"
    "PRINT,Print,,500.00,LIST_PRICE,,,POINT_IN_TIME,Y,4200,\n"
    "EXTRA,Extra,,1000.00,LIST_PRICE,,,RATABLE_DAILY,Y,4100,\n"
    "SETUP,Setup,,100.00,LIST_PRICE,,,POINT_IN_TIME,N,4300,"
)
YEAR = "2025-01-01,2025-12-31"


@pytest.fixture
def user_id(db: Session) -> int:
    seed.seed_accounts(db)
    seed.seed_gl_mappings(db)
    seed.seed_periods(db, "202501")
    uid = make_user(db, [Role.ACCOUNTANT]).id
    accepted(upload(db, uid, products=PRODUCTS, customers="C1,Acme,GB"))
    return uid


@pytest.fixture
def approver_id(db: Session) -> int:
    return make_user(db, [Role.APPROVER]).id


def new_contract(db: Session, uid: int, code: str, *lines: str, **files: str) -> int:
    accepted(
        upload(
            db,
            uid,
            contracts=f"{code},C1,{YEAR},NEW,2025-01-01",
            contract_lines="\n".join(f"{code},{line}" for line in lines),
            **files,
        )
    )
    contract_id = db.scalar(select(Contract.id).where(Contract.contract_code == code))
    assert contract_id is not None
    return contract_id


def book_month(db: Session, uid: int, approver: int, period: str) -> Any:
    """Recognition run, generate, approve and post one period, as the replay does."""
    run_recognition(db, uid, period_key=period)
    summary = generate_journals(db, period, uid)
    if summary.batch_id is not None:
        approve_batch(db, summary.batch_id, approver)
        post_batch(db, summary.batch_id, approver)
    return summary


def live_schedule(db: Session, contract_id: int) -> dict[str, Decimal]:
    """Amount per service period, without superseded lines."""
    rows = db.execute(
        select(ScheduleLine.service_period, func.sum(ScheduleLine.amount))
        .join(RevenueSchedule, RevenueSchedule.id == ScheduleLine.schedule_id)
        .join(ContractVersion, ContractVersion.id == RevenueSchedule.contract_version_id)
        .where(
            ContractVersion.contract_id == contract_id,
            ScheduleLine.status != ScheduleLineStatus.SUPERSEDED,
        )
        .group_by(ScheduleLine.service_period)
        .order_by(ScheduleLine.service_period)
    ).tuples()
    return dict(rows.all())


def entry_lines(db: Session, entry_type: str) -> list[tuple[str, Decimal, Decimal]]:
    rows = db.execute(
        select(GlAccount.account_code, JournalLine.debit, JournalLine.credit)
        .join(GlAccount, GlAccount.id == JournalLine.account_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(JournalEntry.entry_type == entry_type)
        .order_by(JournalLine.id)
    ).tuples()
    return list(rows.all())


D = Decimal


# --------------------------------------------------------------------------- P4-T1 events


def test_renewal_leaves_the_previous_version_untouched(db: Session, user_id: int) -> None:
    cid = new_contract(db, user_id, "K", f"1,SUB,1,1200.00,,{YEAR},")
    run_recognition(db, user_id)
    before = db.execute(select(ScheduleLine.id, ScheduleLine.amount, ScheduleLine.status)).all()

    accepted(
        upload(
            db,
            user_id,
            contracts="K,C1,2026-01-01,2026-12-31,RENEWAL,2026-01-01",
            contract_lines="K,1,SUB,1,2400.00,,2026-01-01,2026-12-31,",
        )
    )
    summary = run_recognition(db, user_id)

    assert summary.skipped == [] and summary.contracts_generated == 1
    assert summary.schedule_lines_created == 12
    after = db.execute(
        select(ScheduleLine.id, ScheduleLine.amount, ScheduleLine.status).where(
            ScheduleLine.id.in_([row[0] for row in before])
        )
    ).all()
    assert sorted(after) == sorted(before)
    schedule = live_schedule(db, cid)
    assert schedule["202512"] == D("100.00") and schedule["202601"] == D("200.00")
    assert len(schedule) == 24
    assert run_recognition(db, user_id).contracts_generated == 0  # idempotent


def test_cancellation_daily_stops_at_cumulative_days(db: Session, user_id: int) -> None:
    cid = new_contract(db, user_id, "K", f"1,DAILY,1,3650.00,,{YEAR},")
    run_recognition(db, user_id)
    accepted(upload(db, user_id, contracts=f"K,C1,{YEAR},CANCELLATION,2025-01-10"))
    summary = run_recognition(db, user_id)

    assert summary.events_applied == 1 and summary.skipped == []
    assert live_schedule(db, cid) == {"202501": D("100.00")}  # 10 days x 10.00
    status = db.scalar(select(PerformanceObligation.status))
    assert status == ObligationStatus.SUPERSEDED
    assert run_recognition(db, user_id).events_applied == 0  # idempotent
    assert live_schedule(db, cid) == {"202501": D("100.00")}


def test_cancellation_monthly_supersedes_only_lines_after_it(
    db: Session, user_id: int, approver_id: int
) -> None:
    cid = new_contract(db, user_id, "K", f"1,SUB,1,1200.00,,{YEAR},")
    book_month(db, user_id, approver_id, "202501")
    posted_before = db.execute(
        select(ScheduleLine.id, ScheduleLine.amount).where(
            ScheduleLine.status == ScheduleLineStatus.POSTED
        )
    ).all()
    assert len(posted_before) == 1

    accepted(upload(db, user_id, contracts=f"K,C1,{YEAR},CANCELLATION,2025-01-31"))
    run_recognition(db, user_id)

    assert live_schedule(db, cid) == {"202501": D("100.00")}
    still_posted = db.execute(
        select(ScheduleLine.id, ScheduleLine.amount).where(
            ScheduleLine.status == ScheduleLineStatus.POSTED
        )
    ).all()
    assert still_posted == posted_before  # P4-T1 acceptance: posted lines untouched


def test_cancellation_stops_unsatisfied_point_in_time(db: Session, user_id: int) -> None:
    cid = new_contract(db, user_id, "K", f"1,PRINT,1,500.00,,{YEAR},2025-06-30")
    accepted(upload(db, user_id, deliveries="D1,K,1,2025-01-15,0.2"))
    run_recognition(db, user_id)
    accepted(upload(db, user_id, contracts=f"K,C1,{YEAR},CANCELLATION,2025-01-20"))
    run_recognition(db, user_id)
    assert live_schedule(db, cid) == {"202501": D("100.00")}  # the 20% delivered, nothing more


def test_cancelling_before_the_first_run_builds_the_contract_first(
    db: Session, user_id: int
) -> None:
    cid = new_contract(db, user_id, "K", f"1,SUB,1,1200.00,,{YEAR},")
    accepted(upload(db, user_id, contracts=f"K,C1,{YEAR},CANCELLATION,2025-03-31"))
    summary = run_recognition(db, user_id)
    assert summary.contracts_generated == 1 and summary.events_applied == 1
    assert list(live_schedule(db, cid)) == ["202501", "202502", "202503"]


def test_event_that_would_change_posted_revenue_is_refused(
    db: Session, user_id: int, approver_id: int
) -> None:
    cid = new_contract(db, user_id, "K", f"1,DAILY,1,3650.00,,{YEAR},")
    book_month(db, user_id, approver_id, "202501")
    schedule_before = live_schedule(db, cid)

    accepted(upload(db, user_id, contracts=f"K,C1,{YEAR},CANCELLATION,2025-01-10"))
    summary = run_recognition(db, user_id, period_key="202501")

    assert [s.reason for s in summary.skipped] == ["EVENT_AFTER_POSTING"]
    assert live_schedule(db, cid) == schedule_before
    assert db.scalar(select(PerformanceObligation.status)) == ObligationStatus.ACTIVE


def test_upgrade_reallocates_the_pool_prospectively(db: Session, user_id: int) -> None:
    """§5.5 worked by hand. Line 1: 3,650 over 365 days = 10.00 a day, SSP 3,650. Effective 1 Jan
    + 100 days = 11 Apr. Earned through 10 Apr: 1,000.00; left 2,650.00. D8 basis: 3,650 x 265/365
    = 2,650.00. Added line 2: price 800, SSP 1,000. Pool 3,450 shared 2,650 : 1,000."""
    cid = new_contract(db, user_id, "K", f"1,DAILY,1,3650.00,,{YEAR},")
    run_recognition(db, user_id)
    accepted(
        upload(
            db,
            user_id,
            contracts=f"K,C1,{YEAR},UPGRADE,2025-04-11",
            contract_lines="K,2,EXTRA,1,800.00,,2025-04-11,2025-12-31,",
        )
    )
    summary = run_recognition(db, user_id)
    assert summary.events_applied == 1 and summary.skipped == []

    rows = db.execute(
        select(
            PerformanceObligation.id,
            PerformanceObligation.status,
            PerformanceObligation.ssp_amount,
            PerformanceObligation.allocated_amount,
            PerformanceObligation.carried_from_po_id,
        ).order_by(PerformanceObligation.id)
    ).all()
    old, carried, added = rows
    assert old.status == ObligationStatus.SUPERSEDED
    assert carried.carried_from_po_id == old.id and carried.ssp_amount == D("2650.00")
    assert carried.allocated_amount == D("2504.79")  # 3,450 x 2,650 / 3,650 = 2,504.7945
    assert added.allocated_amount == D("945.21")  # 3,450 x 1,000 / 3,650 = 945.2055
    assert carried.allocated_amount + added.allocated_amount == D("3450.00")

    schedule = live_schedule(db, cid)
    assert sum(schedule.values()) == D("1000.00") + D("3450.00")
    assert schedule["202501"] == D("310.00") and schedule["202503"] == D("310.00")


def test_upgrade_excludes_satisfied_point_in_time(db: Session, user_id: int) -> None:
    cid = new_contract(
        db,
        user_id,
        "K",
        f"1,DAILY,1,3650.00,,{YEAR},",
        "2,PRINT,1,500.00,,2025-01-01,2025-01-15,2025-01-15",
    )
    run_recognition(db, user_id)
    accepted(
        upload(
            db,
            user_id,
            contracts=f"K,C1,{YEAR},UPGRADE,2025-02-01",
            contract_lines="K,3,EXTRA,1,1000.00,,2025-02-01,2025-12-31,",
        )
    )
    assert run_recognition(db, user_id).skipped == []
    print_po = db.execute(
        select(PerformanceObligation.status, PerformanceObligation.allocated_amount)
        .where(PerformanceObligation.completion_date.is_not(None))
        .order_by(PerformanceObligation.id)
    ).all()
    assert print_po == [(ObligationStatus.ACTIVE, D("500.00"))]  # untouched, not carried
    assert live_schedule(db, cid)["202501"] >= D("500.00")


def test_upgrade_with_a_partly_delivered_item_is_refused(db: Session, user_id: int) -> None:
    new_contract(db, user_id, "K", f"1,PRINT,1,500.00,,{YEAR},2025-12-31")
    accepted(upload(db, user_id, deliveries="D1,K,1,2025-01-05,0.5"))
    run_recognition(db, user_id)
    accepted(
        upload(
            db,
            user_id,
            contracts=f"K,C1,{YEAR},UPGRADE,2025-01-20",
            contract_lines="K,2,EXTRA,1,800.00,,2025-01-20,2025-12-31,",
        )
    )
    summary = run_recognition(db, user_id)
    assert [s.reason for s in summary.skipped] == ["UPGRADE_PARTIAL_DELIVERY"]


def test_event_discards_a_draft_that_holds_its_lines(db: Session, user_id: int) -> None:
    cid = new_contract(db, user_id, "K", f"1,DAILY,1,3650.00,,{YEAR},")
    run_recognition(db, user_id)
    generate_journals(db, "202501", user_id)
    accepted(upload(db, user_id, contracts=f"K,C1,{YEAR},CANCELLATION,2025-01-10"))
    summary = run_recognition(db, user_id)
    assert summary.drafts_discarded == 1
    assert db.scalar(select(func.count()).select_from(JournalBatch)) == 0
    assert live_schedule(db, cid) == {"202501": D("100.00")}


def test_event_waits_for_an_approved_batch(db: Session, user_id: int, approver_id: int) -> None:
    cid = new_contract(db, user_id, "K", f"1,DAILY,1,3650.00,,{YEAR},")
    run_recognition(db, user_id)
    batch_id = generate_journals(db, "202501", user_id).batch_id
    assert batch_id is not None
    approve_batch(db, batch_id, approver_id)
    before = live_schedule(db, cid)
    accepted(upload(db, user_id, contracts=f"K,C1,{YEAR},CANCELLATION,2025-01-10"))
    summary = run_recognition(db, user_id)
    assert [s.reason for s in summary.skipped] == ["BATCH_IN_PROGRESS"]
    assert live_schedule(db, cid) == before


# --------------------------------------------------------------------------- P4-T3 generation


def test_invoice_in_advance_then_revenue(db: Session, user_id: int, approver_id: int) -> None:
    new_contract(
        db,
        user_id,
        "K",
        f"1,SUB,1,1200.00,,{YEAR},",
        invoices="I1,K,2025-01-01,1,1200.00",
    )
    summary = book_month(db, user_id, approver_id, "202501")
    assert summary.total_debit == summary.total_credit == "1300.00"
    assert entry_lines(db, "INVOICE") == [
        ("1100", D("1200.00"), D(0)),
        ("2400", D(0), D("1200.00")),
    ]
    assert entry_lines(db, "REVENUE") == [("2400", D("100.00"), D(0)), ("4100", D(0), D("100.00"))]
    posted = db.scalar(select(ScheduleLine.status).where(ScheduleLine.service_period == "202501"))
    assert posted == ScheduleLineStatus.POSTED


def test_recognition_before_invoice_uses_unbilled_then_reclasses(
    db: Session, user_id: int, approver_id: int
) -> None:
    new_contract(db, user_id, "K", f"1,SUB,1,1200.00,,{YEAR},")
    book_month(db, user_id, approver_id, "202501")
    assert entry_lines(db, "REVENUE") == [("1150", D("100.00"), D(0)), ("4100", D(0), D("100.00"))]

    next_month(db)
    accepted(upload(db, user_id, invoices="I1,K,2025-02-10,1,300.00"))
    book_month(db, user_id, approver_id, "202502")
    assert entry_lines(db, "INVOICE") == [
        ("1100", D("300.00"), D(0)),
        ("1150", D(0), D("100.00")),  # clears unbilled first
        ("2400", D(0), D("200.00")),
    ]
    assert entry_lines(db, "REVENUE")[-2:] == [
        ("2400", D("100.00"), D(0)),
        ("4100", D(0), D("100.00")),
    ]


def test_revenue_splits_across_deferred_and_unbilled(
    db: Session, user_id: int, approver_id: int
) -> None:
    new_contract(db, user_id, "K", f"1,SUB,1,1200.00,,{YEAR},", invoices="I1,K,2025-01-01,1,60.00")
    book_month(db, user_id, approver_id, "202501")
    assert entry_lines(db, "REVENUE") == [
        ("2400", D("60.00"), D(0)),
        ("1150", D("40.00"), D(0)),
        ("4100", D(0), D("100.00")),
    ]


def test_credit_note_debits_deferred_and_credits_ar(
    db: Session, user_id: int, approver_id: int
) -> None:
    new_contract(
        db, user_id, "K", f"1,SUB,1,1200.00,,{YEAR},", invoices="I1,K,2025-01-01,1,1200.00"
    )
    book_month(db, user_id, approver_id, "202501")
    next_month(db)
    accepted(upload(db, user_id, credit_notes="CN1,I1,2025-02-05,300.00,Correction"))
    book_month(db, user_id, approver_id, "202502")
    assert entry_lines(db, "CREDIT_NOTE") == [
        ("2400", D("300.00"), D(0)),
        ("1100", D(0), D("300.00")),
    ]


def test_catch_up_gets_its_own_entry_with_one_credit_per_obligation(
    db: Session, user_id: int, approver_id: int
) -> None:
    next_month(db)
    next_month(db)  # the contract arrives in March; January and February are catch-up
    new_contract(
        db,
        user_id,
        "K",
        f"1,SUB,1,1200.00,,{YEAR},",
        f"2,DAILY,1,3650.00,,{YEAR},",
        invoices="I1,K,2025-03-01,1,4850.00",
    )
    book_month(db, user_id, approver_id, "202503")
    catch_up = entry_lines(db, "REVENUE_CATCH_UP")
    assert [row for row in catch_up if row[0] == "4100" and row[2] > 0] == [
        ("4100", D(0), D("200.00")),
        ("4100", D(0), D("590.00")),
    ]
    assert (
        db.scalar(
            select(func.count())
            .select_from(JournalEntry)
            .where(JournalEntry.entry_type == "REVENUE")
        )
        == 1
    )


def test_gl_equals_sub_ledger_after_a_year_of_activity(
    db: Session, user_id: int, approver_id: int
) -> None:
    """§5.6 check (a): the rollforward equals the GL, month after month."""
    cid = new_contract(
        db, user_id, "K", f"1,DAILY,1,3650.00,,{YEAR},", invoices="I1,K,2025-01-01,1,500.00"
    )
    for month in range(1, 13):
        period = f"2025{month:02d}"
        if month == 6:
            accepted(upload(db, user_id, invoices="I2,K,2025-06-15,1,3150.00"))
        if month == 8:
            accepted(upload(db, user_id, credit_notes="CN1,I2,2025-08-01,100.00,Fix"))
        book_month(db, user_id, approver_id, period)
        gl = dict(
            db.execute(
                select(GlAccount.account_code, func.sum(JournalLine.credit - JournalLine.debit))
                .join(GlAccount, GlAccount.id == JournalLine.account_id)
                .group_by(GlAccount.account_code)
            )
            .tuples()
            .all()
        )
        deferred, unbilled = balance_at(contract_balances(db, cid), period)
        assert to_cents(gl.get("2400", D(0))) == deferred
        assert -to_cents(gl.get("1150", D(0))) == unbilled
        if month < 12:
            next_month(db)


def to_cents(value: Decimal) -> int:
    return int(value * 100)


def test_missing_mapping_is_reported_and_books_nothing(db: Session, user_id: int) -> None:
    new_contract(
        db, user_id, "BAD", f"1,SUB,1,1200.00,,{YEAR},", invoices="IB,BAD,2025-01-01,1,10.00"
    )
    db.execute(delete(GlMapping).where(GlMapping.account_role == AccountRole.DEFERRED_REVENUE))
    run_recognition(db, user_id)
    summary = generate_journals(db, "202501", user_id)
    assert [s.reason for s in summary.skipped] == ["MISSING_MAPPING"]
    assert summary.batch_id is None
    assert "DEFERRED_REVENUE" in summary.skipped[0].message


def test_credit_processed_before_its_invoice_is_reported_not_booked(
    db: Session, user_id: int
) -> None:
    """§5.6 orders by date then number, so on the same date "A-CN" comes before "B-INV"."""
    new_contract(
        db, user_id, "K", f"1,SUB,1,1200.00,,{YEAR},", invoices="B-INV,K,2025-01-05,1,500.00"
    )
    accepted(upload(db, user_id, credit_notes="A-CN,B-INV,2025-01-05,100.00,Fix"))
    run_recognition(db, user_id)
    summary = generate_journals(db, "202501", user_id)
    assert [s.reason for s in summary.skipped] == ["CREDIT_EXCEEDS_DEFERRED"]
    assert summary.batch_id is None


def test_regenerating_replaces_the_draft_and_releases_its_lines(db: Session, user_id: int) -> None:
    new_contract(
        db, user_id, "K", f"1,SUB,1,1200.00,,{YEAR},", invoices="I1,K,2025-01-01,1,1200.00"
    )
    run_recognition(db, user_id)
    first = generate_journals(db, "202501", user_id)
    second = generate_journals(db, "202501", user_id)
    assert second.drafts_replaced == 1
    assert first.batch_id != second.batch_id
    assert second.total_debit == first.total_debit
    assert db.scalar(select(func.count()).select_from(JournalBatch)) == 1
    assert db.scalar(select(func.count()).select_from(JournalEntry)) == 2


def test_later_work_in_the_same_period_gets_a_second_batch(
    db: Session, user_id: int, approver_id: int
) -> None:
    new_contract(db, user_id, "K", f"1,SUB,1,1200.00,,{YEAR},")
    first = book_month(db, user_id, approver_id, "202501")
    accepted(upload(db, user_id, invoices="I1,K,2025-01-20,1,1200.00"))
    second = generate_journals(db, "202501", user_id)
    assert (first.batch_no, second.batch_no) == (1, 2)
    assert second.entries == 1 and second.total_debit == "1200.00"
    assert generate_journals(db, "202501", user_id).drafts_replaced == 1


def test_generating_with_nothing_to_book_creates_no_batch(db: Session, user_id: int) -> None:
    summary = generate_journals(db, "202501", user_id)
    assert summary.batch_id is None and summary.entries == 0


# --------------------------------------------------------------------------- P4-T4 lifecycle


@pytest.fixture
def draft(db: Session, user_id: int) -> int:
    new_contract(
        db, user_id, "K", f"1,SUB,1,1200.00,,{YEAR},", invoices="I1,K,2025-01-01,1,1200.00"
    )
    run_recognition(db, user_id)
    batch_id = generate_journals(db, "202501", user_id).batch_id
    assert batch_id is not None
    return batch_id


def actions(db: Session) -> list[str]:
    return list(db.scalars(select(AuditLog.action).order_by(AuditLog.id)))


def test_generator_cannot_approve(db: Session, user_id: int, draft: int) -> None:
    with pytest.raises(JournalRuleError) as caught:
        approve_batch(db, draft, user_id)
    assert caught.value.code == "SEGREGATION_OF_DUTIES"
    assert db.get(JournalBatch, draft).status == BatchStatus.DRAFT  # type: ignore[union-attr]


def test_full_lifecycle_writes_the_audit_log(db: Session, approver_id: int, draft: int) -> None:
    approve_batch(db, draft, approver_id)
    send_back_batch(db, draft, approver_id, "Check the invoice")
    batch = db.get(JournalBatch, draft)
    assert batch is not None and batch.status == BatchStatus.DRAFT and batch.approved_by is None
    approve_batch(db, draft, approver_id)
    post_batch(db, draft, approver_id)
    assert batch.status == BatchStatus.POSTED and batch.posted_by == approver_id
    logged = actions(db)
    for action in (
        "JOURNALS_GENERATED",
        "JOURNAL_BATCH_APPROVED",
        "JOURNAL_BATCH_SENT_BACK",
        "JOURNAL_BATCH_POSTED",
    ):
        assert action in logged


@pytest.mark.parametrize(
    ("action", "code"),
    [(post_batch, "BATCH_WRONG_STATUS"), (send_back_batch, "BATCH_WRONG_STATUS")],
)
def test_wrong_order_is_refused(
    db: Session, approver_id: int, draft: int, action: Any, code: str
) -> None:
    args = (db, draft, approver_id, None) if action is send_back_batch else (db, draft, approver_id)
    with pytest.raises(JournalRuleError) as caught:
        action(*args)
    assert caught.value.code == code


def test_posted_batch_is_read_only_in_the_database(
    db: Session, approver_id: int, draft: int
) -> None:
    approve_batch(db, draft, approver_id)
    post_batch(db, draft, approver_id)
    db.flush()
    savepoint = db.begin_nested()
    with pytest.raises(DBAPIError, match="POSTED"):
        db.execute(update(JournalLine).values(debit=D("1.00")))
    savepoint.rollback()
    with pytest.raises(JournalRuleError):
        approve_batch(db, draft, approver_id)


def test_reversal_mirrors_the_entry_in_a_new_draft_batch(
    db: Session, user_id: int, approver_id: int, draft: int
) -> None:
    approve_batch(db, draft, approver_id)
    post_batch(db, draft, approver_id)
    invoice = db.scalar(select(JournalEntry).where(JournalEntry.entry_type == "INVOICE"))
    assert invoice is not None

    batch = reverse_entry(db, invoice.id, user_id, "Booked to the wrong customer")

    assert batch.status == BatchStatus.DRAFT and batch.batch_no == 2
    assert entry_lines(db, "REVERSAL") == [
        ("1100", D(0), D("1200.00")),
        ("2400", D("1200.00"), D(0)),
    ]
    with pytest.raises(JournalRuleError) as twice:
        reverse_entry(db, invoice.id, user_id, "Again")
    assert twice.value.code == "ALREADY_REVERSED"
    assert "JOURNAL_ENTRY_REVERSED" in actions(db)


def test_only_a_posted_entry_can_be_reversed(db: Session, user_id: int, draft: int) -> None:
    entry_id = db.scalar(select(JournalEntry.id).where(JournalEntry.batch_id == draft))
    assert entry_id is not None
    with pytest.raises(JournalRuleError) as caught:
        reverse_entry(db, entry_id, user_id, "Not yet posted")
    assert caught.value.code == "ENTRY_NOT_POSTED"


def test_regenerating_keeps_a_reversal_batch(
    db: Session, user_id: int, approver_id: int, draft: int
) -> None:
    approve_batch(db, draft, approver_id)
    post_batch(db, draft, approver_id)
    invoice = db.scalar(select(JournalEntry.id).where(JournalEntry.entry_type == "INVOICE"))
    assert invoice is not None
    reversal_batch = reverse_entry(db, invoice, user_id, "Mistake")
    summary = generate_journals(db, "202501", user_id)
    assert summary.drafts_replaced == 0
    assert db.get(JournalBatch, reversal_batch.id) is not None


def test_posted_reversal_keeps_gl_and_sub_ledger_equal(
    db: Session, user_id: int, approver_id: int, draft: int
) -> None:
    approve_batch(db, draft, approver_id)
    post_batch(db, draft, approver_id)
    revenue = db.scalar(select(JournalEntry.id).where(JournalEntry.entry_type == "REVENUE"))
    assert revenue is not None
    contract_id = db.scalar(select(Contract.id))
    assert contract_id is not None
    assert balance_at(contract_balances(db, contract_id), "202501") == (110000, 0)

    batch = reverse_entry(db, revenue, user_id, "Wrong month")
    assert balance_at(contract_balances(db, contract_id), "202501") == (110000, 0)  # still draft
    approve_batch(db, batch.id, approver_id)
    post_batch(db, batch.id, approver_id)

    assert balance_at(contract_balances(db, contract_id), "202501") == (120000, 0)
    deferred = db.scalar(
        select(func.sum(JournalLine.credit - JournalLine.debit))
        .join(GlAccount, GlAccount.id == JournalLine.account_id)
        .where(GlAccount.account_code == "2400")
    )
    assert deferred == D("1200.00")


# --------------------------------------------------------------------------- P4-T4 endpoints


def test_batch_endpoints_through_the_api(
    client: TestClient, db: Session, user_id: int, draft: int
) -> None:
    generator = db.get(JournalBatch, draft)
    assert generator is not None
    approver = make_user(db, [Role.APPROVER])
    sign_in(client, approver)

    listed = client.get("/api/v1/journal-batches").json()
    assert listed["total"] == 1 and listed["items"][0]["status"] == "DRAFT"
    assert listed["items"][0]["total_debit"] == "1300.00"
    assert listed["items"][0]["entry_count"] == 2

    detail = client.get(f"/api/v1/journal-batches/{draft}").json()
    assert detail["balanced"] is True and detail["total"] == 4
    assert detail["items"][0]["contract_code"] == "K"
    assert detail["items"][0]["first_of_entry"] is True
    assert detail["items"][1]["first_of_entry"] is False

    assert client.post(f"/api/v1/journal-batches/{draft}/post").status_code == 409
    assert client.post(f"/api/v1/journal-batches/{draft}/approve").json()["status"] == "APPROVED"
    back = client.post(f"/api/v1/journal-batches/{draft}/send-back", json={"reason": "Look again"})
    assert back.json()["status"] == "DRAFT"
    client.post(f"/api/v1/journal-batches/{draft}/approve")
    posted = client.post(f"/api/v1/journal-batches/{draft}/post").json()
    assert posted["status"] == "POSTED" and posted["posted_by_name"] == approver.full_name

    entry_id = detail["items"][0]["entry_id"]
    lines = client.get(f"/api/v1/journal-batches/{draft}").json()["items"]
    assert lines[0]["can_reverse"] is True
    assert client.post(f"/api/v1/journal-entries/{entry_id}/reverse", json={}).status_code == 422
    reversed_ = client.post(
        f"/api/v1/journal-entries/{entry_id}/reverse", json={"reason": "Booked twice"}
    )
    assert reversed_.status_code == 201
    new_batch = client.get(f"/api/v1/journal-batches/{reversed_.json()['batch_id']}").json()
    assert new_batch["items"][0]["entry_type"] == "REVERSAL"
    after = client.get(f"/api/v1/journal-batches/{draft}").json()["items"]
    assert after[0]["can_reverse"] is False


def test_generator_cannot_approve_through_the_api(
    client: TestClient, db: Session, user_id: int
) -> None:
    approver = make_user(db, [Role.APPROVER])
    new_contract(db, user_id, "K", f"1,SUB,1,1200.00,,{YEAR},")
    run_recognition(db, user_id)
    batch_id = generate_journals(db, "202501", approver.id).batch_id
    sign_in(client, approver)
    response = client.post(f"/api/v1/journal-batches/{batch_id}/approve")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SEGREGATION_OF_DUTIES"
    assert client.get(f"/api/v1/journal-batches/{batch_id}").json()["batch"]["status"] == "DRAFT"


def test_contract_journal_lines_tab_and_csv(
    client: TestClient, db: Session, user_id: int, draft: int
) -> None:
    sign_in(client, make_user(db, [Role.UPLOADER]))
    contract_id = db.scalar(select(Contract.id))
    page = client.get(f"/api/v1/contracts/{contract_id}/journal-lines").json()
    assert page["total"] == 4
    assert {line["account_code"] for line in page["items"]} == {"1100", "2400", "4100"}
    csv = client.get(f"/api/v1/contracts/{contract_id}/journal-lines?format=csv")
    assert csv.status_code == 200 and "account_code" in csv.text
    assert client.get("/api/v1/contracts/999999/journal-lines").status_code == 404


def test_cancelled_contract_shows_as_done_only_after_the_run(
    client: TestClient, db: Session, user_id: int
) -> None:
    new_contract(db, user_id, "K", f"1,SUB,1,1200.00,,{YEAR},")
    run_recognition(db, user_id)
    accepted(upload(db, user_id, contracts=f"K,C1,{YEAR},CANCELLATION,2025-03-31"))
    sign_in(client, make_user(db, [Role.UPLOADER]))
    assert client.get("/api/v1/contracts").json()["items"][0]["has_schedule"] is False
    run_recognition(db, user_id)
    item = client.get("/api/v1/contracts").json()["items"][0]
    assert item["has_schedule"] is True and item["status"] == "CANCELLED"

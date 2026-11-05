"""Per-contract billing and balances: loads from the database, calls the engine (plan §5.6)."""

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine.balances import BillingEvent, PeriodBalance, roll_forward
from app.engine.money import to_cents
from app.models import (
    ContractVersion,
    CreditNote,
    Invoice,
    RevenueSchedule,
    ScheduleLine,
    UploadFile,
)
from app.models.enums import ScheduleLineStatus
from app.services.journals import (
    all_reversal_effects,
    document_posting_period,
    reversal_effects,
)


def billing_events(db: Session, contract_id: int) -> list[BillingEvent]:
    events = [
        BillingEvent(
            document_posting_period(when, upload_period), when, number, "INVOICE", to_cents(amt)
        )
        for number, when, amt, upload_period in db.execute(
            select(
                Invoice.invoice_number,
                Invoice.invoice_date,
                Invoice.total_amount,
                UploadFile.period_key,
            )
            .outerjoin(UploadFile, UploadFile.id == Invoice.source_upload_id)
            .where(Invoice.contract_id == contract_id)
        ).tuples()
    ]
    events += [
        BillingEvent(
            document_posting_period(when, upload_period),
            when,
            number,
            "CREDIT_NOTE",
            to_cents(amt),
        )
        for number, when, amt, upload_period in db.execute(
            select(
                CreditNote.credit_note_number,
                CreditNote.credit_date,
                CreditNote.amount,
                UploadFile.period_key,
            )
            .join(Invoice, Invoice.id == CreditNote.invoice_id)
            .outerjoin(UploadFile, UploadFile.id == CreditNote.source_upload_id)
            .where(Invoice.contract_id == contract_id)
        ).tuples()
    ]
    return events


def recognised_by_period(db: Session, contract_id: int) -> dict[str, int]:
    """Revenue booked per posting period: every line with a posting period, not superseded."""
    rows = db.execute(
        select(ScheduleLine.posting_period, func.sum(ScheduleLine.amount))
        .join(RevenueSchedule, RevenueSchedule.id == ScheduleLine.schedule_id)
        .join(ContractVersion, ContractVersion.id == RevenueSchedule.contract_version_id)
        .where(
            ContractVersion.contract_id == contract_id,
            ScheduleLine.posting_period.is_not(None),
            ScheduleLine.status != ScheduleLineStatus.SUPERSEDED,
        )
        .group_by(ScheduleLine.posting_period)
    ).tuples()
    totals: dict[str, int] = defaultdict(int)
    for period, amount in rows:
        if period is not None:
            totals[period] += to_cents(amount)
    return dict(totals)


def contract_balances(db: Session, contract_id: int) -> list[PeriodBalance]:
    """The contract's deferred / unbilled rollforward, one row per period with activity."""
    return roll_forward(
        billing_events(db, contract_id),
        recognised_by_period(db, contract_id),
        reversal_effects(db, contract_id),
    )


def balance_at(rows: list[PeriodBalance], period: str) -> tuple[int, int]:
    """(deferred, unbilled) in cents at the end of a period."""
    earlier = [row for row in rows if row.period <= period]
    return (earlier[-1].closing_deferred, earlier[-1].closing_unbilled) if earlier else (0, 0)


def contract_position_cents(db: Session, contract_id: int) -> int:
    """Billed minus recognised so far: positive is the deferred balance (plan §5.6)."""
    rows = contract_balances(db, contract_id)
    return (rows[-1].closing_deferred - rows[-1].closing_unbilled) if rows else 0


def all_balances(
    db: Session, contract_ids: list[int] | None = None
) -> dict[int, list[PeriodBalance]]:
    """Every contract's rollforward in a few queries (plan §5.6, P5-T2): the same calculation as
    contract_balances. `contract_ids` narrows it; None means every contract."""
    events: dict[int, list[BillingEvent]] = defaultdict(list)
    invoices = select(
        Invoice.contract_id,
        Invoice.invoice_number,
        Invoice.invoice_date,
        Invoice.total_amount,
        UploadFile.period_key,
    ).outerjoin(UploadFile, UploadFile.id == Invoice.source_upload_id)
    credits_ = (
        select(
            Invoice.contract_id,
            CreditNote.credit_note_number,
            CreditNote.credit_date,
            CreditNote.amount,
            UploadFile.period_key,
        )
        .join(Invoice, Invoice.id == CreditNote.invoice_id)
        .outerjoin(UploadFile, UploadFile.id == CreditNote.source_upload_id)
    )
    revenue = (
        select(
            ContractVersion.contract_id,
            ScheduleLine.posting_period,
            func.sum(ScheduleLine.amount),
        )
        .join(RevenueSchedule, RevenueSchedule.id == ScheduleLine.schedule_id)
        .join(ContractVersion, ContractVersion.id == RevenueSchedule.contract_version_id)
        .where(
            ScheduleLine.posting_period.is_not(None),
            ScheduleLine.status != ScheduleLineStatus.SUPERSEDED,
        )
        .group_by(ContractVersion.contract_id, ScheduleLine.posting_period)
    )
    if contract_ids is not None:
        invoices = invoices.where(Invoice.contract_id.in_(contract_ids))
        credits_ = credits_.where(Invoice.contract_id.in_(contract_ids))
        revenue = revenue.where(ContractVersion.contract_id.in_(contract_ids))

    for contract_id, number, when, amount, upload_period in db.execute(invoices).tuples():
        events[contract_id].append(
            BillingEvent(
                document_posting_period(when, upload_period),
                when,
                number,
                "INVOICE",
                to_cents(amount),
            )
        )
    for contract_id, number, when, amount, upload_period in db.execute(credits_).tuples():
        events[contract_id].append(
            BillingEvent(
                document_posting_period(when, upload_period),
                when,
                number,
                "CREDIT_NOTE",
                to_cents(amount),
            )
        )
    recognised: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for contract_id, period, amount in db.execute(revenue).tuples():
        if period is not None:
            recognised[contract_id][period] += to_cents(amount)
    adjustments = all_reversal_effects(db, contract_ids)

    return {
        contract_id: roll_forward(
            events.get(contract_id, []),
            recognised.get(contract_id, {}),
            adjustments.get(contract_id, {}),
        )
        for contract_id in set(events) | set(recognised) | set(adjustments)
    }

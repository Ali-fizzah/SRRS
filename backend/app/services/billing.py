"""Per-contract billing and balances: loads from the database, calls the engine (plan §5.6)."""

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine.balances import BillingEvent, PeriodBalance, roll_forward
from app.engine.money import to_cents
from app.engine.periods import period_key
from app.models import (
    ContractVersion,
    CreditNote,
    Invoice,
    RevenueSchedule,
    ScheduleLine,
    UploadFile,
)
from app.models.enums import ScheduleLineStatus


def _posting_period(document_period: str, upload_period: str | None) -> str:
    """D6: a document dated in a closed period posts to the period open when it was uploaded."""
    return max(document_period, upload_period or document_period)


def billing_events(db: Session, contract_id: int) -> list[BillingEvent]:
    events = [
        BillingEvent(
            _posting_period(period_key(when), upload_period), when, number, "INVOICE", to_cents(amt)
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
            _posting_period(period_key(when), upload_period),
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
    return roll_forward(billing_events(db, contract_id), recognised_by_period(db, contract_id))


def balance_at(rows: list[PeriodBalance], period: str) -> tuple[int, int]:
    """(deferred, unbilled) in cents at the end of a period."""
    earlier = [row for row in rows if row.period <= period]
    return (earlier[-1].closing_deferred, earlier[-1].closing_unbilled) if earlier else (0, 0)


def contract_position_cents(db: Session, contract_id: int) -> int:
    """Billed minus recognised so far: positive is the deferred balance (plan §5.6)."""
    rows = contract_balances(db, contract_id)
    return (rows[-1].closing_deferred - rows[-1].closing_unbilled) if rows else 0

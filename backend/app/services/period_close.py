"""Period close: the checklist and the OPEN -> CLOSING -> CLOSED states (plan §5.8). Task P5-T1.

The plan requires a journal batch for every close. A month with nothing at all to book would then
never close, so such a month passes with "nothing to book" (flagged for M1).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.engine.money import from_cents, to_cents
from app.engine.periods import next_period
from app.models import (
    AccountingPeriod,
    AuditLog,
    Contract,
    GlMapping,
    JournalBatch,
    JournalEntry,
    JournalLine,
    RevenueSchedule,
    ScheduleLine,
    UploadFile,
)
from app.models.enums import (
    AccountRole,
    BatchStatus,
    ContractStatus,
    PeriodStatus,
    ScheduleLineStatus,
    ScheduleStatus,
    UploadStatus,
)
from app.services.billing import all_balances, balance_at
from app.services.journals import unbooked_count
from app.services.recognition_run import versions_to_process

ItemStatus = Literal["pass", "warn", "fail"]
_MAX_NAMED = 5


class PeriodRuleError(Exception):
    """A close rule said no. The API turns it into its error shape (plan §8)."""

    def __init__(self, status: int, code: str, message: str, details: object = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


@dataclass(frozen=True)
class ChecklistItem:
    id: str
    label: str
    status: ItemStatus
    detail: str


@dataclass(frozen=True)
class Checklist:
    period_key: str
    status: PeriodStatus
    items: list[ChecklistItem] = field(default_factory=list)

    @property
    def blocking(self) -> list[ChecklistItem]:
        """§5.8: close needs items 1-4 and 6. A warning does not stop it."""
        return [item for item in self.items if item.status == "fail"]


def _period(db: Session, key: str, lock: bool = False) -> AccountingPeriod:
    statement = select(AccountingPeriod).where(AccountingPeriod.period_key == key)
    period = db.scalar(statement.with_for_update() if lock else statement)
    if period is None:
        raise PeriodRuleError(404, "NOT_FOUND", f"Period {key} does not exist.")
    return period


# --------------------------------------------------------------------------- checklist


def build_checklist(db: Session, key: str) -> Checklist:
    """Plan §5.8, computed fresh each time."""
    period = _period(db, key)
    batches = db.execute(
        select(JournalBatch.id, JournalBatch.status).where(JournalBatch.period_id == period.id)
    ).all()
    unbooked = unbooked_count(db, key)
    return Checklist(
        key,
        period.status,
        [
            _uploads_final(db, key),
            _recognition_current(db, key),
            _batch_balanced(db, batches, unbooked),
            _rollforward_ties(db, key),
            _warnings(db, key),
            _batch_posted(batches, unbooked),
        ],
    )


def _uploads_final(db: Session, key: str) -> ChecklistItem:
    label = "All uploads are in a final state"
    open_uploads = db.scalar(
        select(func.count())
        .select_from(UploadFile)
        .where(
            UploadFile.period_key == key,
            UploadFile.status.in_([UploadStatus.RECEIVED, UploadStatus.VALIDATING]),
        )
    )
    if open_uploads:
        return ChecklistItem("uploads", label, "fail", f"{open_uploads} still being processed.")
    return ChecklistItem("uploads", label, "pass", "No upload is still being processed.")


def _recognition_current(db: Session, key: str) -> ChecklistItem:
    """Audit rows are numbered in order, so "after" holds even inside one transaction."""
    label = "A recognition run finished after the latest accepted upload"
    last_run = db.scalar(
        select(func.max(AuditLog.id)).where(
            AuditLog.action == "RECOGNITION_RUN",
            AuditLog.after["period_key"].astext == key,
        )
    )
    last_upload = db.scalar(
        select(func.max(AuditLog.id))
        .join(UploadFile, UploadFile.id == AuditLog.entity_id.cast(UploadFile.id.type))
        .where(
            AuditLog.action == "UPLOAD_PROCESSED",
            UploadFile.period_key == key,
            UploadFile.status.in_([UploadStatus.ACCEPTED, UploadStatus.PARTIAL]),
        )
    )
    if last_upload is not None and (last_run is None or last_run < last_upload):
        return ChecklistItem(
            "recognition", label, "fail", "Data arrived after the last run. Run recognition."
        )
    due = db.scalar(
        select(func.count())
        .select_from(ScheduleLine)
        .join(RevenueSchedule, RevenueSchedule.id == ScheduleLine.schedule_id)
        .where(
            ScheduleLine.status == ScheduleLineStatus.PENDING,
            ScheduleLine.posting_period.is_(None),
            ScheduleLine.service_period <= key,
            ScheduleLine.amount != 0,
            RevenueSchedule.status == ScheduleStatus.ACTIVE,
        )
    )
    if due:
        return ChecklistItem(
            "recognition", label, "fail", f"{due} schedule lines are due. Run recognition."
        )
    return ChecklistItem("recognition", label, "pass", "Recognition is up to date.")


def _batch_balanced(db: Session, batches: Sequence[Any], unbooked: int) -> ChecklistItem:
    label = "A journal batch exists and debits equal credits"
    if not batches:
        if unbooked:
            return ChecklistItem(
                "batch", label, "fail", f"{unbooked} items to book. Generate journals."
            )
        return ChecklistItem("batch", label, "pass", "Nothing to book in this period.")
    debit, credit = db.execute(
        select(
            func.coalesce(func.sum(JournalLine.debit), 0),
            func.coalesce(func.sum(JournalLine.credit), 0),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(JournalEntry.batch_id.in_([batch_id for batch_id, _ in batches]))
    ).one()
    if debit != credit:
        return ChecklistItem("batch", label, "fail", f"Debits {debit}, credits {credit}.")
    if unbooked:
        return ChecklistItem(
            "batch", label, "fail", f"{unbooked} items are in no batch. Generate journals."
        )
    return ChecklistItem("batch", label, "pass", f"Debits and credits are both {debit}.")


def gl_balances(db: Session, key: str) -> tuple[int, int]:
    """(deferred, unbilled) in the GL through this period, in cents, from POSTED lines only."""
    accounts: dict[AccountRole, set[int]] = {
        AccountRole.DEFERRED_REVENUE: set(),
        AccountRole.UNBILLED_AR: set(),
    }
    for role, account_id in db.execute(
        select(GlMapping.account_role, GlMapping.account_id).where(
            GlMapping.account_role.in_(list(accounts))
        )
    ).tuples():
        accounts[role].add(account_id)

    def net_credit(account_ids: set[int]) -> int:
        total = db.scalar(
            select(func.coalesce(func.sum(JournalLine.credit - JournalLine.debit), 0))
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .join(JournalBatch, JournalBatch.id == JournalEntry.batch_id)
            .join(AccountingPeriod, AccountingPeriod.id == JournalBatch.period_id)
            .where(
                JournalLine.account_id.in_(account_ids),
                JournalBatch.status == BatchStatus.POSTED,
                AccountingPeriod.period_key <= key,
            )
        )
        return to_cents(total if total is not None else Decimal(0))

    return (
        net_credit(accounts[AccountRole.DEFERRED_REVENUE]),
        -net_credit(accounts[AccountRole.UNBILLED_AR]),
    )


def sub_ledger_balances(db: Session, key: str) -> tuple[int, int]:
    """(deferred, unbilled) in the sub-ledger at the end of this period, in cents (§5.6)."""
    deferred = unbilled = 0
    for rows in all_balances(db).values():
        contract_deferred, contract_unbilled = balance_at(rows, key)
        deferred += contract_deferred
        unbilled += contract_unbilled
    return deferred, unbilled


def _rollforward_ties(db: Session, key: str) -> ChecklistItem:
    """§5.6 check (a). If only the total agrees, a reversal has moved an amount between deferred
    and unbilled: that is a warning for the accountant, not a difference in the books."""
    label = "The deferred revenue rollforward ties to the GL"
    gl_deferred, gl_unbilled = gl_balances(db, key)
    deferred, unbilled = sub_ledger_balances(db, key)
    text = (
        f"Sub-ledger deferred {from_cents(deferred)}, unbilled {from_cents(unbilled)}; "
        f"GL deferred {from_cents(gl_deferred)}, unbilled {from_cents(gl_unbilled)}."
    )
    if (gl_deferred, gl_unbilled) == (deferred, unbilled):
        return ChecklistItem("tie_out", label, "pass", text)
    if gl_deferred - gl_unbilled == deferred - unbilled:
        return ChecklistItem("tie_out", label, "warn", f"The total ties, but not the split. {text}")
    return ChecklistItem("tie_out", label, "fail", f"{text} Post the batch, or investigate.")


def _named(codes: list[str]) -> str:
    shown = ", ".join(codes[:_MAX_NAMED])
    return f"{shown} and {len(codes) - _MAX_NAMED} more" if len(codes) > _MAX_NAMED else shown


def _warnings(db: Session, key: str) -> ChecklistItem:
    """§5.8 item 5 (D7), and contract events the last run could not apply."""
    label = "No contract needs attention"
    notes = []
    cancelled = list(
        db.execute(
            select(Contract.id, Contract.contract_code).where(
                Contract.status == ContractStatus.CANCELLED
            )
        ).tuples()
    )
    if cancelled:
        balances = all_balances(db, [contract_id for contract_id, _ in cancelled])
        residual = [
            code
            for contract_id, code in cancelled
            if balance_at(balances.get(contract_id, []), key)[0] > 0
        ]
        if residual:
            notes.append(f"Cancelled with deferred revenue left (D7): {_named(residual)}.")
    waiting = [code for _, code in versions_to_process(db)]
    if waiting:
        notes.append(f"Contract versions not applied yet: {_named(sorted(set(waiting)))}.")
    if notes:
        return ChecklistItem("warnings", label, "warn", " ".join(notes))
    return ChecklistItem("warnings", label, "pass", "Nothing to report.")


def _batch_posted(batches: Sequence[Any], unbooked: int) -> ChecklistItem:
    label = "The batch is POSTED"
    if not batches:
        if unbooked:
            return ChecklistItem("posted", label, "fail", "There is no batch yet.")
        return ChecklistItem("posted", label, "pass", "Nothing to post in this period.")
    waiting = sum(1 for _, status in batches if status != BatchStatus.POSTED)
    if waiting:
        return ChecklistItem("posted", label, "fail", f"{waiting} batch(es) not posted yet.")
    return ChecklistItem("posted", label, "pass", f"{len(batches)} batch(es) posted.")


# --------------------------------------------------------------------------- state changes


def start_close(db: Session, key: str, user_id: int) -> AccountingPeriod:
    """§5.8: OPEN -> CLOSING. New uploads are blocked from here on."""
    period = _period(db, key, lock=True)
    if period.status != PeriodStatus.OPEN:
        raise PeriodRuleError(
            409, "PERIOD_WRONG_STATUS", f"Period {key} is {period.status.value}, not OPEN."
        )
    period.status = PeriodStatus.CLOSING
    write_audit(
        db,
        user_id=user_id,
        action="PERIOD_CLOSE_STARTED",
        entity_type="accounting_period",
        entity_id=key,
        before={"status": PeriodStatus.OPEN.value},
        after={"status": PeriodStatus.CLOSING.value},
    )
    db.flush()
    return period


def close_period(db: Session, key: str, user_id: int) -> AccountingPeriod:
    """§5.8: CLOSING -> CLOSED, once items 1-4 and 6 pass; the next period opens."""
    period = _period(db, key, lock=True)
    if period.status != PeriodStatus.CLOSING:
        raise PeriodRuleError(
            409, "PERIOD_WRONG_STATUS", f"Period {key} is {period.status.value}, not CLOSING."
        )
    checklist = build_checklist(db, key)
    if checklist.blocking:
        raise PeriodRuleError(
            409,
            "CHECKLIST_NOT_PASSED",
            f"Period {key} cannot close yet: " + " ".join(i.detail for i in checklist.blocking),
            [{"id": i.id, "detail": i.detail} for i in checklist.blocking],
        )
    following = _period_or_none(db, next_period(key))
    if following is None:
        raise PeriodRuleError(409, "NO_NEXT_PERIOD", f"The period after {key} does not exist.")

    period.status = PeriodStatus.CLOSED
    period.closed_by = user_id
    period.closed_at = datetime.now(UTC)
    db.flush()  # D6: one OPEN period at a time, so this one leaves before the next arrives
    following.status = PeriodStatus.OPEN
    write_audit(
        db,
        user_id=user_id,
        action="PERIOD_CLOSED",
        entity_type="accounting_period",
        entity_id=key,
        before={"status": PeriodStatus.CLOSING.value},
        after={"status": PeriodStatus.CLOSED.value, "next_open": following.period_key},
    )
    db.flush()
    return period


def _period_or_none(db: Session, key: str) -> AccountingPeriod | None:
    return db.scalar(
        select(AccountingPeriod).where(AccountingPeriod.period_key == key).with_for_update()
    )


def reopen_period(db: Session, key: str, user_id: int, reason: str) -> AccountingPeriod:
    """§5.8: only the latest CLOSED period, and only if the next period has no POSTED batch."""
    period = _period(db, key, lock=True)
    latest = db.scalar(
        select(func.max(AccountingPeriod.period_key)).where(
            AccountingPeriod.status == PeriodStatus.CLOSED
        )
    )
    if period.status != PeriodStatus.CLOSED or key != latest:
        raise PeriodRuleError(
            409, "NOT_LATEST_CLOSED", f"Only the latest closed period ({latest}) can be reopened."
        )
    following = _period_or_none(db, next_period(key))
    if following is not None:
        posted = db.scalar(
            select(func.count())
            .select_from(JournalBatch)
            .where(
                JournalBatch.period_id == following.id,
                JournalBatch.status == BatchStatus.POSTED,
            )
        )
        if posted:
            raise PeriodRuleError(
                409,
                "NEXT_PERIOD_HAS_POSTED_BATCH",
                f"Period {following.period_key} already has a posted batch.",
            )
        following.status = PeriodStatus.FUTURE
        db.flush()  # D6: the next period gives up OPEN first

    before = {"status": PeriodStatus.CLOSED.value, "closed_by": period.closed_by}
    period.status = PeriodStatus.OPEN
    period.closed_by = None
    period.closed_at = None
    write_audit(
        db,
        user_id=user_id,
        action="PERIOD_REOPENED",
        entity_type="accounting_period",
        entity_id=key,
        before=before,
        after={"status": PeriodStatus.OPEN.value},
        reason=reason,
    )
    db.flush()
    return period

"""Golden-case replay (plan §11.2, task P3-T7).

Replays a case month by month as a user would: open period -> upload that month's files ->
recognition run -> generate journals -> approve -> post -> next month, then compares the results
with expected/. postings.csv is compared with the posted journal lines themselves.

Close joins the replay in Phase 5; until then the runner moves the period on itself.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth.roles import Role
from app.engine.money import from_cents, to_cents
from app.engine.periods import iter_periods, next_period
from app.ingestion.loader import load_upload
from app.ingestion.templates import TEMPLATES
from app.models import (
    AccountingPeriod,
    Contract,
    ContractLine,
    ContractVersion,
    CreditNote,
    GlAccount,
    GlMapping,
    Invoice,
    InvoiceLine,
    JournalBatch,
    JournalEntry,
    JournalLine,
    PerformanceObligation,
    RevenueSchedule,
    ScheduleLine,
    UploadFile,
)
from app.models.enums import (
    AccountRole,
    BatchStatus,
    GlAccountType,
    JournalEntryType,
    ObligationStatus,
    PeriodStatus,
    ScheduleLineStatus,
    UploadTemplate,
)
from app.services.billing import balance_at, contract_balances
from app.services.journals import approve_batch, generate_journals, post_batch
from app.services.recognition_run import run_recognition

Key = tuple[str, ...]


@dataclass(frozen=True)
class Variance:
    case: str
    check: str
    key: str
    expected: Decimal
    actual: Decimal

    @property
    def difference(self) -> Decimal:
        return abs(self.actual - self.expected)


@dataclass
class CaseResult:
    case: str
    tolerance: Decimal
    compared: int = 0
    variances: list[Variance] = field(default_factory=list)  # every comparison
    problems: list[str] = field(default_factory=list)  # anything else that went wrong

    @property
    def max_variance(self) -> Decimal:
        return max((v.difference for v in self.variances), default=Decimal(0))

    @property
    def failures(self) -> list[Variance]:
        return [v for v in self.variances if v.difference > self.tolerance]

    @property
    def passed(self) -> bool:
        return not self.failures and not self.problems


def case_meta(case_dir: Path) -> dict[str, Any]:
    meta: dict[str, Any] = yaml.safe_load((case_dir / "case.yaml").read_text(encoding="utf-8"))
    return meta


def _read(path: Path) -> list[dict[str, str]]:
    import csv

    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _upload_month(db: Session, folder: Path, period: str, user_id: int, result: CaseResult) -> None:
    order = list(TEMPLATES)
    batch = []
    for path in sorted(folder.glob("*.csv"), key=lambda p: order.index(UploadTemplate(p.stem))):
        record = UploadFile(
            template=UploadTemplate(path.stem),
            original_filename=path.name,
            sha256="0" * 64,
            stored_path=str(path),
            uploaded_by=user_id,
            period_key=period,
        )
        db.add(record)
        batch.append((record, path.read_bytes()))
    db.flush()
    for summary in load_upload(db, batch, user_id):
        if summary.status != "ACCEPTED":
            result.problems.append(
                f"{period} {summary.template.value}: {summary.status.value}, "
                f"{summary.rejected_rows} rejected"
            )


def _advance(db: Session, period: str) -> None:
    db.execute(
        update(AccountingPeriod)
        .where(AccountingPeriod.period_key == period)
        .values(status=PeriodStatus.CLOSED)
    )
    db.execute(
        update(AccountingPeriod)
        .where(AccountingPeriod.period_key == next_period(period))
        .values(status=PeriodStatus.OPEN)
    )


def _compare(
    result: CaseResult, check: str, expected: dict[Key, Decimal], actual: dict[Key, Decimal]
) -> None:
    """A key on one side only counts as 0 on the other (expected files hold non-zero cells)."""
    for key in sorted(set(expected) | set(actual)):
        result.compared += 1
        result.variances.append(
            Variance(
                result.case,
                check,
                "/".join(key),
                expected.get(key, Decimal(0)),
                actual.get(key, Decimal(0)),
            )
        )


def _actual_lines(db: Session) -> list[Any]:
    return list(
        db.execute(
            select(
                Contract.contract_code,
                ContractLine.line_no,
                ScheduleLine.service_period,
                ScheduleLine.posting_period,
                ScheduleLine.is_catch_up,
                ScheduleLine.amount,
            )
            .join(RevenueSchedule, RevenueSchedule.id == ScheduleLine.schedule_id)
            .join(
                PerformanceObligation,
                PerformanceObligation.id == RevenueSchedule.performance_obligation_id,
            )
            .join(ContractLine, ContractLine.id == PerformanceObligation.contract_line_id)
            .join(ContractVersion, ContractVersion.id == RevenueSchedule.contract_version_id)
            .join(Contract, Contract.id == ContractVersion.contract_id)
            .where(ScheduleLine.status != ScheduleLineStatus.SUPERSEDED)
        )
    )


def replay(db: Session, case_dir: Path, seed: Any, user_factory: Any) -> CaseResult:
    """Run one case in the caller's transaction and compare it with expected/."""
    meta = case_meta(case_dir)
    result = CaseResult(case_dir.name, Decimal(meta["tolerance"]))
    first, last = meta["periods"]["from"], meta["periods"]["to"]

    seed.seed_accounts(db)
    seed.seed_gl_mappings(db)
    seed.seed_periods(db, meta["open_period"])
    user_id = user_factory(db, [Role.ACCOUNTANT], email=f"bench-{meta['id']}@test.local").id
    approver_id = user_factory(db, [Role.APPROVER], email=f"appr-{meta['id']}@test.local").id

    expected_balances = (
        _read(case_dir / "expected" / "balances.csv")
        if (case_dir / "expected" / "balances.csv").is_file()
        else []
    )
    actual_balances: dict[Key, Decimal] = {}

    for period in iter_periods(first, last):
        folder = case_dir / "inputs" / period
        if folder.is_dir():
            _upload_month(db, folder, period, user_id, result)
        summary = run_recognition(db, user_id, period_key=period)
        for skip in summary.skipped:
            result.problems.append(f"{period} {skip.contract_code}: {skip.reason} {skip.message}")
        journals = generate_journals(db, period, user_id)
        for skipped in journals.skipped:
            result.problems.append(
                f"{period} {skipped.contract_code}: {skipped.reason} {skipped.message}"
            )
        if journals.batch_id is not None:
            approve_batch(db, journals.batch_id, approver_id)
            post_batch(db, journals.batch_id, approver_id)
        db.flush()
        for row in expected_balances:
            if row["period"] == period:
                contract_id = db.scalar(
                    select(Contract.id).where(Contract.contract_code == row["contract_id"])
                )
                rows = contract_balances(db, contract_id) if contract_id else []
                deferred, unbilled = balance_at(rows, period)
                key = (period, row["contract_id"])
                actual_balances[(*key, "deferred")] = from_cents(deferred)
                actual_balances[(*key, "unbilled")] = from_cents(unbilled)
        if period != last:
            _advance(db, period)

    _compare_allocation(db, case_dir, result)
    lines = _actual_lines(db)
    _compare_schedule(case_dir, lines, result)
    _compare_postings(db, case_dir, result)
    _compare(
        result,
        "balances",
        {
            (r["period"], r["contract_id"], name): Decimal(r[name])
            for r in expected_balances
            for name in ("deferred", "unbilled")
        },
        actual_balances,
    )
    _check_schedule_equals_allocation(db, result)
    _check_ledger(db, last, result)
    return result


def _compare_allocation(db: Session, case_dir: Path, result: CaseResult) -> None:
    """Keyed by contract and line; event cases add a version_no column, because a renewal or an
    upgrade gives the same line number a new allocation in a later version (§5.5)."""
    expected_rows = _read(case_dir / "expected" / "allocation.csv")
    by_version = bool(expected_rows) and "version_no" in expected_rows[0]
    rows = db.execute(
        select(
            Contract.contract_code,
            ContractLine.line_no,
            ContractVersion.version_no,
            PerformanceObligation.allocated_amount,
        )
        .join(ContractLine, ContractLine.id == PerformanceObligation.contract_line_id)
        .join(ContractVersion, ContractVersion.id == PerformanceObligation.contract_version_id)
        .join(Contract, Contract.id == ContractVersion.contract_id)
    )
    _compare(
        result,
        "allocation",
        {
            (r["contract_id"], r["line_no"], *([r["version_no"]] if by_version else [])): Decimal(
                r["allocated_amount"]
            )
            for r in expected_rows
        },
        {
            (code, str(line_no), *([str(version_no)] if by_version else [])): amount
            for code, line_no, version_no, amount in rows
        },
    )


def _compare_schedule(case_dir: Path, lines: list[Any], result: CaseResult) -> None:
    actual: dict[Key, Decimal] = defaultdict(Decimal)
    for row in lines:
        if row.amount != 0:
            actual[(row.contract_code, str(row.line_no), row.service_period)] += row.amount
    _compare(
        result,
        "schedule",
        {
            (r["contract_id"], r["line_no"], r["service_period"]): Decimal(r["amount"])
            for r in _read(case_dir / "expected" / "schedule.csv")
        },
        dict(actual),
    )


def _compare_postings(db: Session, case_dir: Path, result: CaseResult) -> None:
    """§11.2: revenue credits and AR debits, read from posted journal lines. An invoice is keyed by
    its line number; a credit note names no line, so its rows use line_no 0."""
    actual: dict[Key, Decimal] = defaultdict(Decimal)
    posted = JournalBatch.status == BatchStatus.POSTED
    for period, code, line_no, entry_type, amount in db.execute(
        select(
            AccountingPeriod.period_key,
            Contract.contract_code,
            ContractLine.line_no,
            JournalEntry.entry_type,
            func.sum(JournalLine.credit - JournalLine.debit),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .join(JournalBatch, JournalBatch.id == JournalEntry.batch_id)
        .join(AccountingPeriod, AccountingPeriod.id == JournalBatch.period_id)
        .join(Contract, Contract.id == JournalEntry.contract_id)
        .join(GlAccount, GlAccount.id == JournalLine.account_id)
        .join(
            PerformanceObligation,
            PerformanceObligation.id == JournalLine.performance_obligation_id,
        )
        .join(ContractLine, ContractLine.id == PerformanceObligation.contract_line_id)
        .where(posted, GlAccount.type == GlAccountType.REVENUE)
        .group_by(
            AccountingPeriod.period_key,
            Contract.contract_code,
            ContractLine.line_no,
            JournalEntry.entry_type,
        )
    ):
        actual[(period, code, str(line_no), entry_type.value)] += amount

    for period, code, line_no, amount in db.execute(
        select(
            AccountingPeriod.period_key,
            Contract.contract_code,
            InvoiceLine.line_no,
            InvoiceLine.amount,
        )
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .join(
            JournalEntry,
            (JournalEntry.source_id == Invoice.id)
            & (JournalEntry.entry_type == JournalEntryType.INVOICE),
        )
        .join(JournalBatch, JournalBatch.id == JournalEntry.batch_id)
        .join(AccountingPeriod, AccountingPeriod.id == JournalBatch.period_id)
        .join(Contract, Contract.id == Invoice.contract_id)
        .where(posted, InvoiceLine.amount != 0)
    ):
        actual[(period, code, str(line_no), "INVOICE")] += amount

    for period, code, amount in db.execute(
        select(AccountingPeriod.period_key, Contract.contract_code, CreditNote.amount)
        .join(
            JournalEntry,
            (JournalEntry.source_id == CreditNote.id)
            & (JournalEntry.entry_type == JournalEntryType.CREDIT_NOTE),
        )
        .join(JournalBatch, JournalBatch.id == JournalEntry.batch_id)
        .join(AccountingPeriod, AccountingPeriod.id == JournalBatch.period_id)
        .join(Contract, Contract.id == JournalEntry.contract_id)
        .where(posted)
    ):
        actual[(period, code, "0", "CREDIT_NOTE")] += amount

    _compare(
        result,
        "postings",
        {
            (r["posting_period"], r["contract_id"], r["line_no"], r["entry_type"]): Decimal(
                r["amount"]
            )
            for r in _read(case_dir / "expected" / "postings.csv")
        },
        dict(actual),
    )


def _check_schedule_equals_allocation(db: Session, result: CaseResult) -> None:
    """Pass rule (§11.1): every live PO's schedule total EXACTLY equals its allocation. A PO an
    event stopped or replaced earned only part of its allocation, so it is left out."""
    rows = db.execute(
        select(
            Contract.contract_code,
            ContractLine.line_no,
            ContractVersion.version_no,
            PerformanceObligation.allocated_amount,
            func.coalesce(func.sum(ScheduleLine.amount), 0),
        )
        .join(ContractLine, ContractLine.id == PerformanceObligation.contract_line_id)
        .join(ContractVersion, ContractVersion.id == PerformanceObligation.contract_version_id)
        .join(Contract, Contract.id == ContractVersion.contract_id)
        .join(
            RevenueSchedule,
            RevenueSchedule.performance_obligation_id == PerformanceObligation.id,
        )
        .outerjoin(
            ScheduleLine,
            (ScheduleLine.schedule_id == RevenueSchedule.id)
            & (ScheduleLine.status != ScheduleLineStatus.SUPERSEDED),
        )
        .where(PerformanceObligation.status != ObligationStatus.SUPERSEDED)
        .group_by(
            Contract.contract_code,
            ContractLine.line_no,
            ContractVersion.version_no,
            PerformanceObligation.allocated_amount,
        )
    )
    for code, line_no, version_no, allocated, scheduled in rows:
        if scheduled != allocated:
            result.problems.append(
                f"{code} v{version_no} line {line_no}: schedule {scheduled} != "
                f"allocation {allocated}"
            )


def _check_ledger(db: Session, last_period: str, result: CaseResult) -> None:
    """Milestone: every entry balances, and the GL equals the sub-ledger per contract (§5.6)."""
    unbalanced = db.execute(
        select(JournalLine.entry_id)
        .group_by(JournalLine.entry_id)
        .having(func.sum(JournalLine.debit) != func.sum(JournalLine.credit))
    ).all()
    if unbalanced:
        result.problems.append(f"unbalanced entries: {[row[0] for row in unbalanced]}")

    defaults = dict(
        db.execute(
            select(GlMapping.account_role, GlMapping.account_id).where(
                GlMapping.product_id.is_(None), GlMapping.product_category.is_(None)
            )
        )
        .tuples()
        .all()
    )
    for contract_id, code in db.execute(select(Contract.id, Contract.contract_code)).tuples():
        balances: dict[int, int] = defaultdict(int)
        for account_id, net in db.execute(
            select(JournalLine.account_id, func.sum(JournalLine.credit - JournalLine.debit))
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .join(JournalBatch, JournalBatch.id == JournalEntry.batch_id)
            .where(JournalEntry.contract_id == contract_id, JournalBatch.status == "POSTED")
            .group_by(JournalLine.account_id)
        ).tuples():
            balances[account_id] = to_cents(net)
        deferred, unbilled = balance_at(contract_balances(db, contract_id), last_period)
        gl_deferred = balances[defaults[AccountRole.DEFERRED_REVENUE]]
        gl_unbilled = -balances[defaults[AccountRole.UNBILLED_AR]]
        if (gl_deferred, gl_unbilled) != (deferred, unbilled):
            result.problems.append(
                f"{code}: GL deferred/unbilled {gl_deferred}/{gl_unbilled} != "
                f"sub-ledger {deferred}/{unbilled} (cents)"
            )

"""Golden-case replay (plan §11.2, task P3-T7).

Replays a case month by month as a user would: open period -> upload that month's files ->
recognition run -> next month, then compares the results with expected/.

Journals, approval and close join the replay in Phases 4-5; until then the runner moves the
period on itself, and INVOICE rows of postings.csv are not compared (they are journal lines).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.roles import Role
from app.engine.money import from_cents
from app.engine.periods import iter_periods, next_period
from app.ingestion.loader import load_upload
from app.ingestion.templates import TEMPLATES
from app.models import (
    AccountingPeriod,
    Contract,
    ContractLine,
    ContractVersion,
    PerformanceObligation,
    RevenueSchedule,
    ScheduleLine,
    UploadFile,
)
from app.models.enums import PeriodStatus, ScheduleLineStatus, UploadTemplate
from app.services.billing import balance_at, contract_balances
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
    seed.seed_periods(db, meta["open_period"])
    user_id = user_factory(db, [Role.ACCOUNTANT], email=f"bench-{meta['id']}@test.local").id

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
    _compare_postings(case_dir, lines, result)
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
    _check_schedule_equals_allocation(db, lines, result)
    return result


def _compare_allocation(db: Session, case_dir: Path, result: CaseResult) -> None:
    rows = db.execute(
        select(Contract.contract_code, ContractLine.line_no, PerformanceObligation.allocated_amount)
        .join(ContractLine, ContractLine.id == PerformanceObligation.contract_line_id)
        .join(ContractVersion, ContractVersion.id == PerformanceObligation.contract_version_id)
        .join(Contract, Contract.id == ContractVersion.contract_id)
    )
    _compare(
        result,
        "allocation",
        {
            (r["contract_id"], r["line_no"]): Decimal(r["allocated_amount"])
            for r in _read(case_dir / "expected" / "allocation.csv")
        },
        {(code, str(line_no)): amount for code, line_no, amount in rows},
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


def _compare_postings(case_dir: Path, lines: list[Any], result: CaseResult) -> None:
    actual: dict[Key, Decimal] = defaultdict(Decimal)
    for row in lines:
        if row.posting_period is not None and row.amount != 0:
            entry_type = "REVENUE_CATCH_UP" if row.is_catch_up else "REVENUE"
            actual[(row.posting_period, row.contract_code, str(row.line_no), entry_type)] += (
                row.amount
            )
    _compare(
        result,
        "postings",
        {
            (r["posting_period"], r["contract_id"], r["line_no"], r["entry_type"]): Decimal(
                r["amount"]
            )
            for r in _read(case_dir / "expected" / "postings.csv")
            if r["entry_type"] in ("REVENUE", "REVENUE_CATCH_UP")
        },
        dict(actual),
    )


def _check_schedule_equals_allocation(db: Session, lines: list[Any], result: CaseResult) -> None:
    """Pass rule (§11.1): every PO's schedule total EXACTLY equals its allocation."""
    totals: dict[tuple[str, int], Decimal] = defaultdict(Decimal)
    for row in lines:
        totals[(row.contract_code, row.line_no)] += row.amount
    rows = db.execute(
        select(Contract.contract_code, ContractLine.line_no, PerformanceObligation.allocated_amount)
        .join(ContractLine, ContractLine.id == PerformanceObligation.contract_line_id)
        .join(ContractVersion, ContractVersion.id == PerformanceObligation.contract_version_id)
        .join(Contract, Contract.id == ContractVersion.contract_id)
    )
    for code, line_no, allocated in rows:
        if totals[(code, line_no)] != allocated:
            result.problems.append(
                f"{code} line {line_no}: schedule {totals[(code, line_no)]} != "
                f"allocation {allocated}"
            )

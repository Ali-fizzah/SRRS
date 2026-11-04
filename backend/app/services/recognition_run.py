"""Recognition run: generate and save revenue schedules (plan §5.2-5.4, task P2-T3).

For every contract whose current version has no performance obligations yet: resolve SSP,
call the pure engine, and save obligations, schedules and PENDING schedule lines. Running it
again generates nothing twice.

Assigning posting periods and catch-up (§5.4) is task P3-T4. Contracts the engine cannot
handle yet are reported and left untouched, so a later run picks them up.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.engine.allocation import (
    AllocationLine,
    MultipleObligationsError,
    NoSeparateObligationError,
    allocate,
)
from app.engine.methods import ScheduleAmount, ratable_monthly
from app.engine.money import from_cents, to_cents
from app.models import (
    Contract,
    ContractLine,
    ContractVersion,
    PerformanceObligation,
    Product,
    RevenueSchedule,
    ScheduleLine,
    SspRule,
)
from app.models.enums import ContractEventType, RecognitionMethod, SspSource

CENT = Decimal("0.01")


@dataclass(frozen=True)
class SkippedContract:
    contract_code: str
    reason: str  # MULTIPLE_OBLIGATIONS, UNSUPPORTED_METHOD, UNSUPPORTED_EVENT, ...
    message: str


@dataclass
class RunSummary:
    contracts_generated: int = 0
    obligations_created: int = 0
    schedule_lines_created: int = 0
    skipped: list[SkippedContract] = field(default_factory=list)


class _SkipContractError(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def unit_ssp(rule: SspRule, list_price: Decimal) -> Decimal:
    """SSP per unit by the rule's source (plan §5.2)."""
    if rule.ssp_source == SspSource.FIXED:
        assert rule.ssp_value is not None  # guaranteed by a CHECK constraint
        return rule.ssp_value
    if rule.ssp_source == SspSource.LIST_PRICE:
        return list_price
    assert rule.ssp_pct is not None  # guaranteed by a CHECK constraint
    return list_price * rule.ssp_pct / 100


def rule_on(rules: list[SspRule], when: date) -> SspRule | None:
    """The rule in force on a date: the latest valid_from not after it (plan §5.2)."""
    in_force = [
        rule
        for rule in rules
        if rule.valid_from <= when and (rule.valid_to is None or when <= rule.valid_to)
    ]
    return max(in_force, key=lambda rule: (rule.valid_from, rule.id), default=None)


def run_recognition(
    db: Session, user_id: int | None = None, job_id: int | None = None
) -> RunSummary:
    """Generate schedules for every contract that needs them. The caller commits."""
    versions = list(
        db.execute(
            select(ContractVersion, Contract.contract_code)
            .join(
                Contract,
                (Contract.id == ContractVersion.contract_id)
                & (Contract.current_version_no == ContractVersion.version_no),
            )
            .where(
                ~select(PerformanceObligation.id)
                .where(PerformanceObligation.contract_version_id == ContractVersion.id)
                .exists()
            )
            .order_by(Contract.contract_code)
        ).tuples()
    )
    lines_of, rules_of = _load_lines_and_rules(db, [version.id for version, _ in versions])

    summary = RunSummary()
    for version, code in versions:
        try:
            plan = _plan_contract(version, lines_of[version.id], rules_of)
        except _SkipContractError as skip:
            summary.skipped.append(SkippedContract(code, skip.reason, skip.message))
            continue
        for line, product, ssp_cents, allocated, schedule in plan:
            _save(db, version, line, product, ssp_cents, allocated, schedule, job_id)
            summary.obligations_created += 1
            summary.schedule_lines_created += len(schedule)
        summary.contracts_generated += 1
    db.flush()

    write_audit(
        db,
        user_id=user_id,
        action="RECOGNITION_RUN",
        entity_type="recognition_run",
        entity_id=job_id,
        after={
            "contracts_generated": summary.contracts_generated,
            "obligations_created": summary.obligations_created,
            "schedule_lines_created": summary.schedule_lines_created,
            "skipped": [{"contract": s.contract_code, "reason": s.reason} for s in summary.skipped],
        },
    )
    return summary


def _load_lines_and_rules(
    db: Session, version_ids: list[int]
) -> tuple[dict[int, list[tuple[ContractLine, Product]]], dict[int, list[SspRule]]]:
    lines_of: dict[int, list[tuple[ContractLine, Product]]] = defaultdict(list)
    rules_of: dict[int, list[SspRule]] = defaultdict(list)
    if not version_ids:
        return lines_of, rules_of
    for line, product in db.execute(
        select(ContractLine, Product)
        .join(Product, Product.id == ContractLine.product_id)
        .where(ContractLine.contract_version_id.in_(version_ids))
        .order_by(ContractLine.contract_version_id, ContractLine.line_no)
    ).tuples():
        lines_of[line.contract_version_id].append((line, product))
    product_ids = {product.id for rows in lines_of.values() for _, product in rows}
    for rule in db.scalars(select(SspRule).where(SspRule.product_id.in_(product_ids))):
        rules_of[rule.product_id].append(rule)
    return lines_of, rules_of


def _plan_contract(
    version: ContractVersion,
    lines: list[tuple[ContractLine, Product]],
    rules_of: dict[int, list[SspRule]],
) -> list[tuple[ContractLine, Product, int, int, list[ScheduleAmount]]]:
    """Work out one contract in memory, so a skipped contract writes nothing."""
    if version.event_type != ContractEventType.NEW:
        raise _SkipContractError(
            "UNSUPPORTED_EVENT", f"{version.event_type.value} versions are built in task P4-T1."
        )

    ssp_cents: dict[int, int] = {}
    for line, product in lines:
        if not product.is_separate_obligation:
            continue
        rule = rule_on(rules_of[product.id], version.effective_date)
        if rule is None:
            raise _SkipContractError(
                "NO_SSP_RULE",
                f"Product {product.product_code} has no SSP rule on {version.effective_date}.",
            )
        ssp = unit_ssp(rule, product.list_price) * line.quantity
        ssp_cents[line.id] = to_cents(ssp.quantize(CENT, ROUND_HALF_UP))  # D2

    try:
        allocations = allocate(
            [
                AllocationLine(
                    line_no=line.line_no,
                    net_cents=to_cents(line.net_price),
                    is_separate=product.is_separate_obligation,
                    ssp_cents=ssp_cents.get(line.id, 0),
                )
                for line, product in lines
            ]
        )
    except NoSeparateObligationError as exc:
        raise _SkipContractError("NO_SEPARATE_OBLIGATION", f"{exc.code}: {exc}") from exc
    except MultipleObligationsError as exc:
        raise _SkipContractError("MULTIPLE_OBLIGATIONS", str(exc)) from exc

    by_line_no = {line.line_no: (line, product) for line, product in lines}
    plan = []
    for allocation in allocations:
        line, product = by_line_no[allocation.line_no]
        if product.recognition_method != RecognitionMethod.RATABLE_MONTHLY:
            raise _SkipContractError(
                "UNSUPPORTED_METHOD",
                f"{product.recognition_method.value} schedules are built in task P3-T3.",
            )
        try:
            schedule = ratable_monthly(
                allocation.allocated_cents, line.service_start, line.service_end
            )
        except ValueError as exc:
            raise _SkipContractError("ENGINE_REFUSED", str(exc)) from exc
        plan.append((line, product, ssp_cents[line.id], allocation.allocated_cents, schedule))
    return plan


def _save(
    db: Session,
    version: ContractVersion,
    line: ContractLine,
    product: Product,
    ssp_cents: int,
    allocated_cents: int,
    schedule: list[ScheduleAmount],
    job_id: int | None,
) -> None:
    obligation = PerformanceObligation(
        contract_version_id=version.id,
        contract_line_id=line.id,
        product_id=product.id,
        method=product.recognition_method,
        ssp_amount=from_cents(ssp_cents),
        allocated_amount=from_cents(allocated_cents),
        service_start=line.service_start,
        service_end=line.service_end,
        completion_date=line.completion_date,
    )
    db.add(obligation)
    db.flush()
    revenue_schedule = RevenueSchedule(
        performance_obligation_id=obligation.id,
        contract_version_id=version.id,
        generated_by_job_id=job_id,
    )
    db.add(revenue_schedule)
    db.flush()
    db.add_all(
        ScheduleLine(
            schedule_id=revenue_schedule.id,
            service_period=amount.service_period,
            amount=from_cents(amount.amount_cents),
        )
        for amount in schedule
    )

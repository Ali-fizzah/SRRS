"""Recognition run (plan §5.2-5.4, §10). Tasks P2-T3, P3-T2, P3-T3, P3-T4.

For period P:
1. Generate obligations, schedules and PENDING lines for contracts whose current version has
   none yet: resolve SSP, allocate, and call the recognition method (all pure engine code).
2. Rebuild point-in-time schedules when deliveries arrived after they were generated (D3).
3. Assign posting period P to every unassigned PENDING line earned in P or earlier; lines
   earned before P are catch-up (D5, §5.4). Later lines stay PENDING.

Running it again changes nothing that has not changed. Contracts it cannot handle yet are
reported and left untouched, so a later run picks them up.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.engine.allocation import AllocationLine, NoSeparateObligationError, allocate
from app.engine.methods import (
    DeliveryTranche,
    ScheduleAmount,
    point_in_time,
    ratable_daily,
    ratable_monthly,
)
from app.engine.money import from_cents, to_cents, to_scaled
from app.engine.ssp import SspRuleData, line_ssp_cents, rule_on
from app.models import (
    AccountingPeriod,
    Contract,
    ContractLine,
    ContractVersion,
    Delivery,
    PerformanceObligation,
    Product,
    RevenueSchedule,
    ScheduleLine,
    SspRule,
)
from app.models.enums import (
    ContractEventType,
    ObligationStatus,
    PeriodStatus,
    RecognitionMethod,
    ScheduleLineStatus,
    ScheduleStatus,
)


@dataclass(frozen=True)
class SkippedContract:
    contract_code: str
    reason: str  # UNSUPPORTED_EVENT, NO_SSP_RULE, NO_SEPARATE_OBLIGATION, ...
    message: str


@dataclass
class RunSummary:
    contracts_generated: int = 0
    obligations_created: int = 0
    schedule_lines_created: int = 0
    schedules_rebuilt: int = 0
    lines_booked: int = 0
    catch_up_lines: int = 0
    skipped: list[SkippedContract] = field(default_factory=list)


class _SkipContractError(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class _PlannedObligation:
    line: ContractLine
    product: Product
    ssp_cents: int
    allocated_cents: int
    schedule: list[ScheduleAmount]


def run_recognition(
    db: Session,
    user_id: int | None = None,
    job_id: int | None = None,
    report: Callable[[int], None] = lambda progress: None,
    period_key: str | None = None,
) -> RunSummary:
    """Run for `period_key`, by default the OPEN period (D6). The caller commits.

    `report` receives the percentage done after each stage (plan §10).
    """
    if period_key is None:
        period_key = db.scalar(
            select(AccountingPeriod.period_key).where(AccountingPeriod.status == PeriodStatus.OPEN)
        )

    summary = RunSummary()
    _generate(db, summary, job_id)
    report(50)
    _rebuild_for_deliveries(db, summary)
    report(70)
    if period_key is not None:
        _assign_posting_period(db, summary, period_key)
    db.flush()
    report(90)

    write_audit(
        db,
        user_id=user_id,
        action="RECOGNITION_RUN",
        entity_type="recognition_run",
        entity_id=job_id,
        after={
            "period_key": period_key,
            "contracts_generated": summary.contracts_generated,
            "obligations_created": summary.obligations_created,
            "schedule_lines_created": summary.schedule_lines_created,
            "schedules_rebuilt": summary.schedules_rebuilt,
            "lines_booked": summary.lines_booked,
            "catch_up_lines": summary.catch_up_lines,
            "skipped": [{"contract": s.contract_code, "reason": s.reason} for s in summary.skipped],
        },
    )
    return summary


# --------------------------------------------------------------------------- 1. generate


def _generate(db: Session, summary: RunSummary, job_id: int | None) -> None:
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
    lines_of, rules_of, deliveries_of = _load_inputs(db, [version.id for version, _ in versions])
    for version, code in versions:
        try:
            plan = _plan_contract(version, lines_of[version.id], rules_of, deliveries_of)
        except _SkipContractError as skip:
            summary.skipped.append(SkippedContract(code, skip.reason, skip.message))
            continue
        for planned in plan:
            _save(db, version, planned, job_id)
            summary.obligations_created += 1
            summary.schedule_lines_created += len(planned.schedule)
        summary.contracts_generated += 1
    db.flush()


def _load_inputs(
    db: Session, version_ids: list[int]
) -> tuple[
    dict[int, list[tuple[ContractLine, Product]]],
    dict[int, list[SspRuleData]],
    dict[int, list[DeliveryTranche]],
]:
    lines_of: dict[int, list[tuple[ContractLine, Product]]] = defaultdict(list)
    rules_of: dict[int, list[SspRuleData]] = defaultdict(list)
    if not version_ids:
        return lines_of, rules_of, {}
    for line, product in db.execute(
        select(ContractLine, Product)
        .join(Product, Product.id == ContractLine.product_id)
        .where(ContractLine.contract_version_id.in_(version_ids))
        .order_by(ContractLine.contract_version_id, ContractLine.line_no)
    ).tuples():
        lines_of[line.contract_version_id].append((line, product))
    product_ids = {product.id for rows in lines_of.values() for _, product in rows}
    for rule in db.scalars(select(SspRule).where(SspRule.product_id.in_(product_ids))):
        rules_of[rule.product_id].append(
            SspRuleData(
                source=rule.ssp_source.value,
                valid_from=rule.valid_from,
                valid_to=rule.valid_to,
                value_cents=None if rule.ssp_value is None else to_cents(rule.ssp_value),
                pct_e4=None if rule.ssp_pct is None else to_scaled(rule.ssp_pct, 4),
                sequence=rule.id,
            )
        )
    line_ids = [line.id for rows in lines_of.values() for line, _ in rows]
    return lines_of, rules_of, _load_deliveries(db, line_ids)


def _load_deliveries(db: Session, line_ids: list[int]) -> dict[int, list[DeliveryTranche]]:
    deliveries_of: dict[int, list[DeliveryTranche]] = defaultdict(list)
    for delivery in db.scalars(
        select(Delivery).where(Delivery.contract_line_id.in_(line_ids)).order_by(Delivery.id)
    ):
        deliveries_of[delivery.contract_line_id].append(
            DeliveryTranche(delivery.delivery_date, to_scaled(delivery.units_fraction, 6))
        )
    return deliveries_of


def _plan_contract(
    version: ContractVersion,
    lines: list[tuple[ContractLine, Product]],
    rules_of: dict[int, list[SspRuleData]],
    deliveries_of: dict[int, list[DeliveryTranche]],
) -> list[_PlannedObligation]:
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
        ssp_cents[line.id] = line_ssp_cents(
            rule, to_cents(product.list_price), to_scaled(line.quantity, 4)
        )

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

    by_line_no = {line.line_no: (line, product) for line, product in lines}
    plan = []
    for allocation in allocations:
        line, product = by_line_no[allocation.line_no]
        try:
            schedule = _schedule_for(
                product.recognition_method,
                allocation.allocated_cents,
                line.service_start,
                line.service_end,
                line.completion_date,
                deliveries_of.get(line.id, []),
            )
        except ValueError as exc:
            raise _SkipContractError("ENGINE_REFUSED", str(exc)) from exc
        plan.append(
            _PlannedObligation(
                line, product, ssp_cents[line.id], allocation.allocated_cents, schedule
            )
        )
    return plan


def _schedule_for(
    method: RecognitionMethod,
    allocated_cents: int,
    service_start: date,
    service_end: date,
    completion_date: date | None,
    deliveries: list[DeliveryTranche],
) -> list[ScheduleAmount]:
    """Plan §5.3. The completion date defaults to service_end."""
    if method == RecognitionMethod.RATABLE_MONTHLY:
        return ratable_monthly(allocated_cents, service_start, service_end)
    if method == RecognitionMethod.RATABLE_DAILY:
        return ratable_daily(allocated_cents, service_start, service_end)
    return point_in_time(allocated_cents, completion_date or service_end, deliveries)


def _save(
    db: Session, version: ContractVersion, planned: _PlannedObligation, job_id: int | None
) -> None:
    line, product = planned.line, planned.product
    obligation = PerformanceObligation(
        contract_version_id=version.id,
        contract_line_id=line.id,
        product_id=product.id,
        method=product.recognition_method,
        ssp_amount=from_cents(planned.ssp_cents),
        allocated_amount=from_cents(planned.allocated_cents),
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
        for amount in planned.schedule
    )


# --------------------------------------------------------------------------- 2. deliveries


def _rebuild_for_deliveries(db: Session, summary: RunSummary) -> None:
    """Deliveries can arrive after the schedule was generated (D3). Booked lines stay; lines not
    booked yet are superseded (CLAUDE.md rule 4) and replaced so the schedule still equals A."""
    rows = list(
        db.execute(
            select(PerformanceObligation, RevenueSchedule.id, Contract.contract_code)
            .join(
                RevenueSchedule,
                RevenueSchedule.performance_obligation_id == PerformanceObligation.id,
            )
            .join(ContractVersion, ContractVersion.id == PerformanceObligation.contract_version_id)
            .join(Contract, Contract.id == ContractVersion.contract_id)
            .where(
                PerformanceObligation.method == RecognitionMethod.POINT_IN_TIME,
                PerformanceObligation.status == ObligationStatus.ACTIVE,
                RevenueSchedule.status == ScheduleStatus.ACTIVE,
                select(Delivery.id)
                .where(Delivery.contract_line_id == PerformanceObligation.contract_line_id)
                .exists(),
            )
        ).tuples()
    )
    if not rows:
        return
    deliveries_of = _load_deliveries(db, [po.contract_line_id for po, _, _ in rows])
    for obligation, schedule_id, code in rows:
        lines = db.scalars(
            select(ScheduleLine).where(
                ScheduleLine.schedule_id == schedule_id,
                ScheduleLine.status != ScheduleLineStatus.SUPERSEDED,
            )
        ).all()
        booked: dict[str, int] = defaultdict(int)
        open_lines: dict[str, int] = defaultdict(int)
        for line in lines:
            is_open = line.status == ScheduleLineStatus.PENDING and line.posting_period is None
            (open_lines if is_open else booked)[line.service_period] += to_cents(line.amount)

        try:
            desired = point_in_time(
                to_cents(obligation.allocated_amount),
                obligation.completion_date or obligation.service_end,
                deliveries_of[obligation.contract_line_id],
            )
        except ValueError as exc:
            summary.skipped.append(SkippedContract(code, "ENGINE_REFUSED", str(exc)))
            continue

        target = {a.service_period: a.amount_cents - booked[a.service_period] for a in desired}
        for period, amount in booked.items():
            target.setdefault(period, -amount)
        target = {period: amount for period, amount in target.items() if amount != 0}
        if target == {period: amt for period, amt in open_lines.items() if amt != 0}:
            continue
        if any(amount < 0 for amount in target.values()):
            # The plan does not define reversing revenue already booked for a late delivery.
            summary.skipped.append(
                SkippedContract(
                    code,
                    "DELIVERY_AFTER_BOOKING",
                    f"Line {obligation.contract_line_id}: a delivery changes revenue that is "
                    "already booked, so the schedule was left as it is.",
                )
            )
            continue

        for line in lines:
            if line.status == ScheduleLineStatus.PENDING and line.posting_period is None:
                line.status = ScheduleLineStatus.SUPERSEDED
        db.add_all(
            ScheduleLine(schedule_id=schedule_id, service_period=period, amount=from_cents(amount))
            for period, amount in sorted(target.items())
        )
        summary.schedules_rebuilt += 1
    db.flush()


# --------------------------------------------------------------------------- 3. posting period


def _assign_posting_period(db: Session, summary: RunSummary, period_key: str) -> None:
    """Plan §5.4. A line keeps the first period it was booked in."""
    active_schedules = select(RevenueSchedule.id).where(
        RevenueSchedule.status == ScheduleStatus.ACTIVE
    )
    catch_up_flags = db.scalars(
        update(ScheduleLine)
        .where(
            ScheduleLine.status == ScheduleLineStatus.PENDING,
            ScheduleLine.posting_period.is_(None),
            ScheduleLine.service_period <= period_key,
            ScheduleLine.schedule_id.in_(active_schedules),
        )
        .values(posting_period=period_key, is_catch_up=ScheduleLine.service_period < period_key)
        .returning(ScheduleLine.is_catch_up)
        .execution_options(synchronize_session="fetch")
    ).all()
    summary.lines_booked += len(catch_up_flags)
    summary.catch_up_lines += sum(1 for flag in catch_up_flags if flag)

"""Recognition run (plan §5.2-5.5, §10). Tasks P2-T3, P3-T2, P3-T3, P3-T4, P4-T1.

For period P:
1. Handle each contract version not handled yet, oldest first: NEW and RENEWAL generate
   obligations, schedules and PENDING lines; UPGRADE and CANCELLATION change the schedules
   already there (contract_events.py).
2. Rebuild point-in-time schedules when deliveries arrived after they were generated (D3).
3. Assign posting period P to every unassigned PENDING line earned in P or earlier; lines
   earned before P are catch-up (D5, §5.4). Later lines stay PENDING.

Running it again changes nothing that has not changed. Contracts it cannot handle yet are
reported and left untouched, so a later run picks them up.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import select, update
from sqlalchemy.orm import Session, aliased

from app.audit import write_audit
from app.engine.allocation import AllocationLine, NoSeparateObligationError, allocate
from app.engine.methods import DeliveryTranche, point_in_time
from app.engine.money import from_cents, to_cents, to_scaled
from app.engine.ssp import SspRuleData
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
from app.services.contract_events import (
    PlannedObligation,
    SkipContractError,
    apply_cancellation,
    apply_upgrade,
    line_ssp,
    load_deliveries,
    save_obligation,
    schedule_for,
)


@dataclass(frozen=True)
class SkippedContract:
    contract_code: str
    reason: str  # NO_SSP_RULE, NO_SEPARATE_OBLIGATION, EVENT_AFTER_POSTING, ...
    message: str


@dataclass
class RunSummary:
    contracts_generated: int = 0
    obligations_created: int = 0
    schedule_lines_created: int = 0
    schedules_rebuilt: int = 0
    events_applied: int = 0
    drafts_discarded: int = 0
    lines_booked: int = 0
    catch_up_lines: int = 0
    skipped: list[SkippedContract] = field(default_factory=list)


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
    _generate(db, summary, job_id, user_id)
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
            "events_applied": summary.events_applied,
            "drafts_discarded": summary.drafts_discarded,
            "lines_booked": summary.lines_booked,
            "catch_up_lines": summary.catch_up_lines,
            "skipped": [{"contract": s.contract_code, "reason": s.reason} for s in summary.skipped],
        },
    )
    return summary


# --------------------------------------------------------------------------- 1. generate


def _generate(db: Session, summary: RunSummary, job_id: int | None, user_id: int | None) -> None:
    """Handle every version still to do, oldest first per contract (§5.5). If a version is
    refused, that contract's later versions wait too: they build on it."""
    versions = versions_to_process(db)
    lines_of, rules_of, deliveries_of = _load_inputs(db, [version.id for version, _ in versions])
    blocked: set[str] = set()
    for version, code in versions:
        if code in blocked:
            continue
        try:
            if version.event_type == ContractEventType.CANCELLATION:
                applied, discarded = apply_cancellation(db, version, user_id)
                summary.drafts_discarded += discarded
                summary.events_applied += int(applied)
            elif version.event_type == ContractEventType.UPGRADE:
                plan, discarded = apply_upgrade(
                    db,
                    version,
                    lines_of[version.id],
                    rules_of,
                    deliveries_of,
                    job_id,
                    user_id,
                )
                summary.drafts_discarded += discarded
                summary.events_applied += 1
                summary.obligations_created += len(plan)
                summary.schedule_lines_created += sum(len(p.schedule) for p in plan)
            else:
                plan = _plan_contract(version, lines_of[version.id], rules_of, deliveries_of)
                for planned in plan:
                    save_obligation(db, version.id, planned, job_id)
                    summary.obligations_created += 1
                    summary.schedule_lines_created += len(planned.schedule)
                summary.contracts_generated += 1
        except SkipContractError as skip:
            summary.skipped.append(SkippedContract(code, skip.reason, skip.message))
            blocked.add(code)
    db.flush()


def versions_to_process(db: Session) -> list[tuple[ContractVersion, str]]:
    """NEW, RENEWAL and UPGRADE versions without obligations yet, and CANCELLATION versions whose
    contract still has obligations to stop or versions to build first."""
    older = aliased(ContractVersion)
    active_obligation = (
        select(PerformanceObligation.id)
        .join(older, older.id == PerformanceObligation.contract_version_id)
        .where(
            older.contract_id == ContractVersion.contract_id,
            PerformanceObligation.status == ObligationStatus.ACTIVE,
        )
        .exists()
    )
    no_obligations = ~(
        select(PerformanceObligation.id)
        .where(PerformanceObligation.contract_version_id == ContractVersion.id)
        .exists()
    )
    older_to_build = (
        select(older.id)
        .where(
            older.contract_id == ContractVersion.contract_id,
            older.version_no < ContractVersion.version_no,
            older.event_type != ContractEventType.CANCELLATION,
            ~select(PerformanceObligation.id)
            .where(PerformanceObligation.contract_version_id == older.id)
            .exists(),
        )
        .exists()
    )
    is_cancellation = ContractVersion.event_type == ContractEventType.CANCELLATION
    return list(
        db.execute(
            select(ContractVersion, Contract.contract_code)
            .join(Contract, Contract.id == ContractVersion.contract_id)
            .where(
                (~is_cancellation & no_obligations)
                | (is_cancellation & (active_obligation | older_to_build))
            )
            .order_by(Contract.contract_code, ContractVersion.version_no)
        ).tuples()
    )


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
    return lines_of, rules_of, load_deliveries(db, line_ids)


def _plan_contract(
    version: ContractVersion,
    lines: list[tuple[ContractLine, Product]],
    rules_of: dict[int, list[SspRuleData]],
    deliveries_of: dict[int, list[DeliveryTranche]],
) -> list[PlannedObligation]:
    """NEW and RENEWAL (§5.5): allocate and schedule in memory, so a skipped contract writes
    nothing. A renewal has its own TP and allocation; the previous version is not touched."""
    ssp_cents = {
        line.id: line_ssp(line, product, rules_of, version.effective_date)
        for line, product in lines
        if product.is_separate_obligation
    }
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
        raise SkipContractError("NO_SEPARATE_OBLIGATION", f"{exc.code}: {exc}") from exc

    by_line_no = {line.line_no: (line, product) for line, product in lines}
    plan = []
    for allocation in allocations:
        line, product = by_line_no[allocation.line_no]
        try:
            schedule = schedule_for(
                product.recognition_method,
                allocation.allocated_cents,
                line.service_start,
                line.service_end,
                line.completion_date,
                deliveries_of.get(line.id, []),
            )
        except ValueError as exc:
            raise SkipContractError("ENGINE_REFUSED", str(exc)) from exc
        plan.append(
            PlannedObligation(
                contract_line_id=line.id,
                product_id=product.id,
                method=product.recognition_method,
                ssp_cents=ssp_cents[line.id],
                allocated_cents=allocation.allocated_cents,
                service_start=line.service_start,
                service_end=line.service_end,
                completion_date=line.completion_date,
                schedule=schedule,
            )
        )
    return plan


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
    deliveries_of = load_deliveries(db, [po.contract_line_id for po, _, _ in rows])
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
        if any(amount < 0 and booked[period] != 0 for period, amount in target.items()):
            # The plan does not define reversing revenue already booked for a late delivery. A
            # negative month with nothing booked is fine: tranches round half up, so 50% + 50% of
            # an odd amount leaves a remainder of -0.01 in the completion month (§5.3, D3).
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

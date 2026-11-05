"""Contract events on existing obligations (plan §5.5, D8). Task P4-T1.

Posted schedule lines are never changed; only PENDING lines are superseded (CLAUDE.md rule 4). A
contract is worked out completely before anything is written, so a refused event writes nothing.

The plan does not say what happens when an event would change revenue that is already POSTED, or
what SSP a partly delivered point-in-time obligation carries into an upgrade. Those events are
refused and reported (EVENT_AFTER_POSTING, UPGRADE_PARTIAL_DELIVERY) until M1 decides.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.allocation import AllocationLine, NoSeparateObligationError, allocate
from app.engine.methods import (
    DeliveryTranche,
    ScheduleAmount,
    point_in_time,
    point_in_time_through,
    ratable_daily,
    ratable_daily_through,
    ratable_monthly,
    ratable_monthly_through,
    remaining_ssp_basis,
)
from app.engine.money import from_cents, to_cents, to_scaled
from app.engine.periods import period_key
from app.engine.ssp import SspRuleData, line_ssp_cents, rule_on
from app.models import (
    ContractLine,
    ContractVersion,
    Delivery,
    JournalBatch,
    JournalEntry,
    JournalLine,
    PerformanceObligation,
    Product,
    RevenueSchedule,
    ScheduleLine,
)
from app.models.enums import (
    BatchStatus,
    ContractEventType,
    ObligationStatus,
    RecognitionMethod,
    ScheduleLineStatus,
    ScheduleStatus,
)
from app.services.journals import discard_batch


class SkipContractError(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class PlannedObligation:
    contract_line_id: int
    product_id: int
    method: RecognitionMethod
    ssp_cents: int
    allocated_cents: int
    service_start: date
    service_end: date
    completion_date: date | None
    schedule: list[ScheduleAmount]
    carried_from_po_id: int | None = None


LineWithProduct = tuple[ContractLine, Product]


def load_deliveries(db: Session, line_ids: Sequence[int]) -> dict[int, list[DeliveryTranche]]:
    deliveries_of: dict[int, list[DeliveryTranche]] = defaultdict(list)
    for delivery in db.scalars(
        select(Delivery).where(Delivery.contract_line_id.in_(line_ids)).order_by(Delivery.id)
    ):
        deliveries_of[delivery.contract_line_id].append(
            DeliveryTranche(delivery.delivery_date, to_scaled(delivery.units_fraction, 6))
        )
    return deliveries_of


def schedule_for(
    method: RecognitionMethod,
    allocated_cents: int,
    service_start: date,
    service_end: date,
    completion_date: date | None,
    deliveries: Sequence[DeliveryTranche],
) -> list[ScheduleAmount]:
    """Plan §5.3. The completion date defaults to service_end."""
    if method == RecognitionMethod.RATABLE_MONTHLY:
        return ratable_monthly(allocated_cents, service_start, service_end)
    if method == RecognitionMethod.RATABLE_DAILY:
        return ratable_daily(allocated_cents, service_start, service_end)
    return point_in_time(allocated_cents, completion_date or service_end, deliveries)


def line_ssp(
    line: ContractLine,
    product: Product,
    rules_of: Mapping[int, list[SspRuleData]],
    on_date: date,
) -> int:
    """§5.2: the line's SSP, using the rule in force on `on_date`."""
    rule = rule_on(rules_of[product.id], on_date)
    if rule is None:
        raise SkipContractError(
            "NO_SSP_RULE", f"Product {product.product_code} has no SSP rule on {on_date}."
        )
    return line_ssp_cents(rule, to_cents(product.list_price), to_scaled(line.quantity, 4))


def save_obligation(
    db: Session, version_id: int, planned: PlannedObligation, job_id: int | None
) -> None:
    obligation = PerformanceObligation(
        contract_version_id=version_id,
        contract_line_id=planned.contract_line_id,
        product_id=planned.product_id,
        method=planned.method,
        ssp_amount=from_cents(planned.ssp_cents),
        allocated_amount=from_cents(planned.allocated_cents),
        service_start=planned.service_start,
        service_end=planned.service_end,
        completion_date=planned.completion_date,
        carried_from_po_id=planned.carried_from_po_id,
    )
    db.add(obligation)
    db.flush()
    revenue_schedule = RevenueSchedule(
        performance_obligation_id=obligation.id,
        contract_version_id=version_id,
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


# --------------------------------------------------------------------------- stopping a schedule


def _earned_through(
    obligation: PerformanceObligation, tranches: Sequence[DeliveryTranche], as_of: date
) -> list[ScheduleAmount]:
    allocated = to_cents(obligation.allocated_amount)
    try:
        if obligation.method == RecognitionMethod.RATABLE_MONTHLY:
            return ratable_monthly_through(
                allocated, obligation.service_start, obligation.service_end, as_of
            )
        if obligation.method == RecognitionMethod.RATABLE_DAILY:
            return ratable_daily_through(
                allocated, obligation.service_start, obligation.service_end, as_of
            )
        return point_in_time_through(
            allocated, obligation.completion_date or obligation.service_end, tranches, as_of
        )
    except ValueError as exc:
        raise SkipContractError("ENGINE_REFUSED", str(exc)) from exc


@dataclass
class _Stop:
    """How one obligation's schedule changes so it earns only what it had earned by a date."""

    obligation: PerformanceObligation
    schedule_id: int
    earned_cents: int
    supersede: list[ScheduleLine]
    add: list[tuple[str, int]]


def _plan_stop(
    db: Session,
    obligation: PerformanceObligation,
    tranches: Sequence[DeliveryTranche],
    as_of: date,
) -> _Stop:
    schedule_id = db.scalar(
        select(RevenueSchedule.id).where(
            RevenueSchedule.performance_obligation_id == obligation.id,
            RevenueSchedule.status == ScheduleStatus.ACTIVE,
        )
    )
    if schedule_id is None:
        raise SkipContractError(
            "ENGINE_REFUSED", f"Obligation {obligation.id} has no active schedule."
        )
    earned = _earned_through(obligation, tranches, as_of)
    desired = {amount.service_period: amount.amount_cents for amount in earned}

    posted: dict[str, int] = defaultdict(int)
    pending: dict[str, list[ScheduleLine]] = defaultdict(list)
    for line in db.scalars(
        select(ScheduleLine).where(
            ScheduleLine.schedule_id == schedule_id,
            ScheduleLine.status != ScheduleLineStatus.SUPERSEDED,
        )
    ):
        if line.status == ScheduleLineStatus.POSTED:
            posted[line.service_period] += to_cents(line.amount)
        else:
            pending[line.service_period].append(line)

    stop_period = period_key(as_of)
    supersede: list[ScheduleLine] = []
    add: list[tuple[str, int]] = []
    for period in sorted(set(desired) | set(posted) | set(pending)):
        target = desired.get(period, 0) - posted.get(period, 0)
        if target < 0 and posted.get(period, 0) != 0:
            raise SkipContractError(
                "EVENT_AFTER_POSTING",
                f"The event takes effect on {as_of + timedelta(days=1)}, but revenue for "
                f"{period} is already posted and would have to be reversed. The plan does not "
                "define this, so the contract was left as it is.",
            )
        pending_lines = pending.get(period, [])
        pending_total = sum(to_cents(line.amount) for line in pending_lines)
        if target != pending_total or (period > stop_period and pending_lines):
            supersede.extend(pending_lines)
            if target != 0:
                add.append((period, target))
    return _Stop(
        obligation, schedule_id, sum(amount.amount_cents for amount in earned), supersede, add
    )


def _release_from_drafts(db: Session, stops: Sequence[_Stop], user_id: int | None) -> int:
    """§5.7: a DRAFT batch can be rebuilt, so one holding a line about to change is discarded; an
    APPROVED batch must be sent back first. Returns the number of batches discarded."""
    line_ids = [
        line.journal_line_id
        for stop in stops
        for line in stop.supersede
        if line.journal_line_id is not None
    ]
    if not line_ids:
        return 0
    batches = db.execute(
        select(JournalBatch.id, JournalBatch.status)
        .join(JournalEntry, JournalEntry.batch_id == JournalBatch.id)
        .join(JournalLine, JournalLine.entry_id == JournalEntry.id)
        .where(JournalLine.id.in_(line_ids))
        .distinct()
    ).all()
    for batch_id, status in batches:
        if status != BatchStatus.DRAFT:
            raise SkipContractError(
                "BATCH_IN_PROGRESS",
                f"Journal batch {batch_id} is {status.value} and holds lines this event changes. "
                "Send it back, then run recognition again.",
            )
    for batch_id, _ in batches:
        discard_batch(db, batch_id, user_id, "A contract event changed its lines.")
    db.expire_all()
    return len(batches)


def _apply_stop(db: Session, stop: _Stop) -> None:
    for line in stop.supersede:
        line.status = ScheduleLineStatus.SUPERSEDED
    db.add_all(
        ScheduleLine(schedule_id=stop.schedule_id, service_period=period, amount=from_cents(amount))
        for period, amount in stop.add
    )
    fully_earned = stop.earned_cents == to_cents(stop.obligation.allocated_amount)
    stop.obligation.status = (
        ObligationStatus.SATISFIED if fully_earned else ObligationStatus.SUPERSEDED
    )


def _active_obligations(db: Session, version_ids: Sequence[int]) -> list[PerformanceObligation]:
    return list(
        db.scalars(
            select(PerformanceObligation)
            .where(
                PerformanceObligation.contract_version_id.in_(version_ids),
                PerformanceObligation.status == ObligationStatus.ACTIVE,
            )
            .order_by(PerformanceObligation.id)
        )
    )


# --------------------------------------------------------------------------- cancellation


def apply_cancellation(
    db: Session, version: ContractVersion, user_id: int | None
) -> tuple[bool, int]:
    """§5.5: recognise through the cancellation date and supersede every PENDING line after it.

    Returns (applied, draft batches discarded). Applied is False when no obligation is active,
    which is also how running it twice changes nothing.
    """
    version_ids = list(
        db.scalars(
            select(ContractVersion.id).where(ContractVersion.contract_id == version.contract_id)
        )
    )
    obligations = _active_obligations(db, version_ids)
    if not obligations:
        return False, 0
    deliveries_of = load_deliveries(db, [po.contract_line_id for po in obligations])
    stops = [
        _plan_stop(db, po, deliveries_of.get(po.contract_line_id, []), version.effective_date)
        for po in obligations
    ]
    discarded = _release_from_drafts(db, stops, user_id)
    for stop in stops:
        _apply_stop(db, stop)
    db.flush()
    return True, discarded


# --------------------------------------------------------------------------- upgrade


def _obligations_in_force(db: Session, version: ContractVersion) -> list[PerformanceObligation]:
    """Those of the latest NEW/RENEWAL version and later upgrades; an earlier term stays as it is
    (§5.5 RENEWAL: previous version untouched)."""
    term_start = db.scalar(
        select(ContractVersion.version_no)
        .where(
            ContractVersion.contract_id == version.contract_id,
            ContractVersion.version_no < version.version_no,
            ContractVersion.event_type.in_([ContractEventType.NEW, ContractEventType.RENEWAL]),
        )
        .order_by(ContractVersion.version_no.desc())
        .limit(1)
    )
    version_ids = list(
        db.scalars(
            select(ContractVersion.id).where(
                ContractVersion.contract_id == version.contract_id,
                ContractVersion.version_no >= (term_start or 1),
                ContractVersion.version_no < version.version_no,
            )
        )
    )
    return _active_obligations(db, version_ids)


def apply_upgrade(
    db: Session,
    version: ContractVersion,
    added: Sequence[LineWithProduct],
    rules_of: Mapping[int, list[SspRuleData]],
    deliveries_of: Mapping[int, list[DeliveryTranche]],
    job_id: int | None,
    user_id: int | None,
) -> tuple[list[PlannedObligation], int]:
    """§5.5 prospective upgrade, D8.

    pool = Σ (alloc - recognised through E-1) over continuing obligations + TP of added lines,
    shared by relative SSP across continuing and added obligations. Satisfied point-in-time
    obligations and ratable ones that have already ended stay out of it.
    """
    effective = version.effective_date
    day_before = effective - timedelta(days=1)
    in_force = _obligations_in_force(db, version)
    all_tranches = load_deliveries(db, [po.contract_line_id for po in in_force])
    line_of = {
        line.id: line
        for line in db.scalars(
            select(ContractLine).where(
                ContractLine.id.in_([po.contract_line_id for po in in_force])
            )
        )
    }

    continuing: list[tuple[PerformanceObligation, _Stop, int]] = []
    for po in in_force:
        tranches = all_tranches.get(po.contract_line_id, [])
        if po.method == RecognitionMethod.POINT_IN_TIME:
            if (po.completion_date or po.service_end) < effective:
                continue  # D8: satisfied, so excluded from reallocation
            if any(tranche.delivery_date < effective for tranche in tranches):
                raise SkipContractError(
                    "UPGRADE_PARTIAL_DELIVERY",
                    f"Line {line_of[po.contract_line_id].line_no} is partly delivered. D8 does "
                    "not define its SSP for the remaining part, so the upgrade was not applied.",
                )
            basis = to_cents(po.ssp_amount)
        else:
            if po.service_end < effective:
                continue
            basis = remaining_ssp_basis(
                to_cents(po.ssp_amount), po.service_start, po.service_end, effective
            )
        continuing.append((po, _plan_stop(db, po, tranches, day_before), basis))

    added_ssp = {
        line.id: line_ssp(line, product, rules_of, effective)
        for line, product in added
        if product.is_separate_obligation
    }
    remaining = {
        po.id: to_cents(po.allocated_amount) - stop.earned_cents for po, stop, _ in continuing
    }
    try:
        allocations = allocate(
            [
                *(
                    AllocationLine(
                        line_no=line_of[po.contract_line_id].line_no,
                        net_cents=remaining[po.id],
                        is_separate=True,
                        ssp_cents=basis,
                    )
                    for po, _, basis in continuing
                ),
                *(
                    AllocationLine(
                        line_no=line.line_no,
                        net_cents=to_cents(line.net_price),
                        is_separate=product.is_separate_obligation,
                        ssp_cents=added_ssp.get(line.id, 0),
                    )
                    for line, product in added
                ),
            ]
        )
    except NoSeparateObligationError as exc:
        raise SkipContractError("NO_SEPARATE_OBLIGATION", f"{exc.code}: {exc}") from exc
    except ValueError as exc:
        raise SkipContractError("ENGINE_REFUSED", str(exc)) from exc
    allocated = {allocation.line_no: allocation.allocated_cents for allocation in allocations}

    plan: list[PlannedObligation] = []
    try:
        for po, _, basis in continuing:
            cents = allocated[line_of[po.contract_line_id].line_no]
            start = max(effective, po.service_start)
            plan.append(
                PlannedObligation(
                    contract_line_id=po.contract_line_id,
                    product_id=po.product_id,
                    method=po.method,
                    ssp_cents=basis,
                    allocated_cents=cents,
                    service_start=start,
                    service_end=po.service_end,
                    completion_date=po.completion_date,
                    schedule=schedule_for(
                        po.method,
                        cents,
                        start,
                        po.service_end,
                        po.completion_date,
                        all_tranches.get(po.contract_line_id, []),
                    ),
                    carried_from_po_id=po.id,
                )
            )
        for line, product in added:
            if not product.is_separate_obligation:
                continue
            plan.append(
                PlannedObligation(
                    contract_line_id=line.id,
                    product_id=product.id,
                    method=product.recognition_method,
                    ssp_cents=added_ssp[line.id],
                    allocated_cents=allocated[line.line_no],
                    service_start=line.service_start,
                    service_end=line.service_end,
                    completion_date=line.completion_date,
                    schedule=schedule_for(
                        product.recognition_method,
                        allocated[line.line_no],
                        line.service_start,
                        line.service_end,
                        line.completion_date,
                        deliveries_of.get(line.id, []),
                    ),
                )
            )
    except ValueError as exc:
        raise SkipContractError("ENGINE_REFUSED", str(exc)) from exc

    stops = [stop for _, stop, _ in continuing]
    discarded = _release_from_drafts(db, stops, user_id)
    for stop in stops:
        _apply_stop(db, stop)
    for planned in plan:
        save_obligation(db, version.id, planned, job_id)
    db.flush()
    return plan, discarded

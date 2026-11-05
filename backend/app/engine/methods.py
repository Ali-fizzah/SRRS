"""Recognition methods (plan §5.3). Pure functions: integer cents in, integer cents out."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.engine.money import round_half_up_div
from app.engine.periods import iter_periods, period_bounds, period_key


@dataclass(frozen=True)
class ScheduleAmount:
    """Revenue earned in one service period (D5)."""

    service_period: str  # YYYYMM (D14)
    amount_cents: int


@dataclass(frozen=True)
class DeliveryTranche:
    """D3: a partial delivery of a point-in-time obligation."""

    delivery_date: date
    fraction_e6: int  # units_fraction in millionths (NUMERIC(9,6)): 0.25 = 250000


def _check_window(allocated_cents: int, service_start: date, service_end: date) -> None:
    if allocated_cents < 0:
        raise ValueError(f"allocated amount must not be negative, got {allocated_cents}")
    if service_end < service_start:
        raise ValueError(f"service_end {service_end} is before service_start {service_start}")


def ratable_monthly(
    allocated_cents: int, service_start: date, service_end: date
) -> list[ScheduleAmount]:
    """Plan §5.3 RATABLE_MONTHLY: equal months; the last month absorbs the difference.

    monthly = round_half_up(A / M); periods 1..M-1 get monthly; period M gets
    A - monthly x (M - 1). The window must start on the 1st and end on a month end
    (uploads check this as E012; the engine refuses it too).
    """
    _check_window(allocated_cents, service_start, service_end)
    last_period = period_key(service_end)
    if service_start.day != 1 or service_end != period_bounds(last_period)[1]:
        raise ValueError(
            f"RATABLE_MONTHLY needs whole months, got {service_start} to {service_end}"
        )

    periods = list(iter_periods(period_key(service_start), last_period))
    months = len(periods)
    monthly = round_half_up_div(allocated_cents, months)
    amounts = [ScheduleAmount(period, monthly) for period in periods[:-1]]
    amounts.append(ScheduleAmount(last_period, allocated_cents - monthly * (months - 1)))
    return amounts


def ratable_daily(
    allocated_cents: int, service_start: date, service_end: date
) -> list[ScheduleAmount]:
    """Plan §5.3 RATABLE_DAILY, cumulative rounding (D2).

    cum_k = round_half_up(A x D_k / D); amount_k = cum_k - cum_(k-1). D_k is the service days
    through the end of period k, capped at service_end. The last cum equals A exactly, so no
    plug is needed and every period is within 0.01 of its unrounded amount.
    """
    _check_window(allocated_cents, service_start, service_end)
    total_days = (service_end - service_start).days + 1
    amounts = []
    previous = 0
    for period in iter_periods(period_key(service_start), period_key(service_end)):
        through = min(period_bounds(period)[1], service_end)
        days = (through - service_start).days + 1
        cumulative = round_half_up_div(allocated_cents * days, total_days)
        amounts.append(ScheduleAmount(period, cumulative - previous))
        previous = cumulative
    return amounts


def point_in_time(
    allocated_cents: int,
    completion_date: date,
    deliveries: Sequence[DeliveryTranche] = (),
) -> list[ScheduleAmount]:
    """Plan §5.3 POINT_IN_TIME, with partial deliveries (D3).

    Each delivery recognises round_half_up(A x units_fraction) in the delivery month; the
    remainder A - Σ tranches is recognised in the completion month. Months that earn nothing
    get no line.
    """
    if allocated_cents < 0:
        raise ValueError(f"allocated amount must not be negative, got {allocated_cents}")
    if sum(delivery.fraction_e6 for delivery in deliveries) > 1_000_000:
        raise ValueError("deliveries add up to more than the whole obligation")

    by_period: dict[str, int] = defaultdict(int)
    delivered = 0
    for delivery in deliveries:
        if delivery.delivery_date > completion_date:
            raise ValueError(
                f"delivery on {delivery.delivery_date} is after completion on {completion_date}"
            )
        tranche = round_half_up_div(allocated_cents * delivery.fraction_e6, 1_000_000)
        by_period[period_key(delivery.delivery_date)] += tranche
        delivered += tranche
    by_period[period_key(completion_date)] += allocated_cents - delivered
    return [
        ScheduleAmount(period, by_period[period])
        for period in sorted(by_period)
        if by_period[period] != 0
    ]

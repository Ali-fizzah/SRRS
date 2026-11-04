"""Recognition methods (plan §5.3). Pure functions: integer cents in, integer cents out."""

from dataclasses import dataclass
from datetime import date

from app.engine.money import round_half_up_div
from app.engine.periods import iter_periods, period_bounds, period_key


@dataclass(frozen=True)
class ScheduleAmount:
    """Revenue earned in one service period (D5)."""

    service_period: str  # YYYYMM (D14)
    amount_cents: int


def ratable_monthly(
    allocated_cents: int, service_start: date, service_end: date
) -> list[ScheduleAmount]:
    """Plan §5.3 RATABLE_MONTHLY: equal months; the last month absorbs the difference.

    monthly = round_half_up(A / M); periods 1..M-1 get monthly; period M gets
    A - monthly x (M - 1). The window must start on the 1st and end on a month end
    (uploads check this as E012; the engine refuses it too).
    """
    if allocated_cents < 0:
        raise ValueError(f"allocated amount must not be negative, got {allocated_cents}")
    if service_end < service_start:
        raise ValueError(f"service_end {service_end} is before service_start {service_start}")
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

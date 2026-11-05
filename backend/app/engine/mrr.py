"""MRR and ARR, non-GAAP (plan §5.9). Pure: integer cents, exact until the last step."""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from app.engine.money import round_half_up_div
from app.engine.periods import iter_periods, next_period, period_bounds, period_key


@dataclass(frozen=True)
class MrrLine:
    net_cents: int
    service_start: date
    service_end: date
    stopped_on: date | None = None  # a cancellation ends the recurring revenue early


def term_months(service_start: date, service_end: date) -> int:
    """§5.9: the service window in months, rounded to the nearest whole month (never below 1).

    15 Mar to 14 Mar next year is exactly 12. A part month counts by its share of that month.
    """
    after = service_end + timedelta(days=1)
    whole = (after.year - service_start.year) * 12 + after.month - service_start.month
    day_difference = after.day - service_start.day
    if day_difference < 0:
        whole -= 1
        previous_month_end = after.replace(day=1) - timedelta(days=1)
        day_difference += previous_month_end.day
    days_in_month = period_bounds(period_key(after))[1].day
    # round half up: whole + days / days_in_month
    return max(round_half_up_div(whole * days_in_month + day_difference, days_in_month), 1)


def _sum_of_quotients(cents_by_term: Mapping[int, int]) -> int:
    """Σ cents / term, exact until one final rounding: all over one common denominator."""
    denominator = 1
    for term in cents_by_term:
        denominator *= term
    numerator = sum(cents * (denominator // term) for term, cents in cents_by_term.items())
    return round_half_up_div(numerator, denominator)


def mrr_by_period(lines: Iterable[MrrLine], first: str, last: str) -> dict[str, int]:
    """§5.9: for each month, Σ net_price / term_months over lines whose window covers month end.

    Rounded once per month, after adding up exactly. Amounts are grouped by term, so the work does
    not grow with lines x months.
    """
    changes: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for line in lines:
        end = min(line.service_end, line.stopped_on or line.service_end)
        if end < line.service_start:
            continue
        last_covered = period_key(end)
        if end != period_bounds(last_covered)[1]:
            last_covered = period_key(period_bounds(last_covered)[0] - timedelta(days=1))
        first_covered = period_key(line.service_start)
        if last_covered < first_covered:
            continue
        term = term_months(line.service_start, line.service_end)
        changes[first_covered][term] += line.net_cents
        changes[next_period(last_covered)][term] -= line.net_cents

    running: dict[int, int] = defaultdict(int)
    result: dict[str, int] = {}
    starts = sorted(changes)
    position = 0
    for period in iter_periods(first, last):
        while position < len(starts) and starts[position] <= period:
            for term, change in changes[starts[position]].items():
                running[term] += change
            position += 1
        result[period] = _sum_of_quotients(running)
    return result

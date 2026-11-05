"""P4-T1: what an obligation has earned by a date, and the D8 SSP basis (plan §5.5)."""

from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

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

JAN1, DEC31 = date(2025, 1, 1), date(2025, 12, 31)


def as_dict(amounts: list[ScheduleAmount]) -> dict[str, int]:
    return {a.service_period: a.amount_cents for a in amounts}


def test_monthly_stops_at_a_month_end() -> None:
    earned = ratable_monthly_through(120000, JAN1, DEC31, date(2025, 5, 31))
    assert as_dict(earned) == {f"20250{m}": 10000 for m in range(1, 6)}


def test_monthly_refuses_a_date_inside_a_month() -> None:
    with pytest.raises(ValueError, match="month end"):
        ratable_monthly_through(120000, JAN1, DEC31, date(2025, 5, 15))


def test_monthly_before_the_start_earned_nothing() -> None:
    assert ratable_monthly_through(120000, JAN1, DEC31, date(2024, 12, 31)) == []


def test_monthly_at_or_after_the_end_is_the_whole_schedule() -> None:
    whole = ratable_monthly(100000, JAN1, DEC31)
    assert ratable_monthly_through(100000, JAN1, DEC31, DEC31) == whole
    assert ratable_monthly_through(100000, JAN1, DEC31, date(2026, 3, 1)) == whole


def test_daily_stops_mid_month_with_cumulative_days() -> None:
    earned = ratable_daily_through(36500, JAN1, DEC31, date(2025, 2, 10))  # 100 cents a day
    assert as_dict(earned) == {"202501": 3100, "202502": 1000}


def test_daily_month_end_matches_the_full_schedule() -> None:
    whole = ratable_daily(123457, JAN1, DEC31)
    earned = ratable_daily_through(123457, JAN1, DEC31, date(2025, 6, 30))
    assert earned == whole[:6]


@given(
    st.integers(min_value=0, max_value=10**9),
    st.integers(min_value=0, max_value=364),
)
def test_daily_through_never_exceeds_the_allocation_and_keeps_rounding(
    allocated: int, offset: int
) -> None:
    through = JAN1 + timedelta(days=offset)
    earned = ratable_daily_through(allocated, JAN1, DEC31, through)
    total = sum(a.amount_cents for a in earned)
    assert 0 <= total <= allocated
    exact = allocated * (offset + 1) / 365
    assert abs(total - exact) <= 1


def test_point_in_time_counts_deliveries_made_by_the_date() -> None:
    tranches = [
        DeliveryTranche(date(2025, 2, 10), 250000),
        DeliveryTranche(date(2025, 8, 10), 250000),
    ]
    earned = point_in_time_through(100000, date(2025, 12, 31), tranches, date(2025, 6, 30))
    assert as_dict(earned) == {"202502": 25000}


def test_point_in_time_not_completed_recognises_nothing_further() -> None:
    assert point_in_time_through(100000, date(2025, 12, 31), [], date(2025, 6, 30)) == []


def test_point_in_time_completed_by_the_date_is_the_whole_schedule() -> None:
    tranches = [DeliveryTranche(date(2025, 2, 10), 250000)]
    completion = date(2025, 5, 31)
    assert point_in_time_through(100000, completion, tranches, date(2025, 6, 30)) == point_in_time(
        100000, completion, tranches
    )


def test_d8_basis_prorates_by_remaining_days() -> None:
    # 170 of 365 days remain from 15 Jul: 400,000 x 170 / 365 = 186,301.37 -> 186,301.
    assert remaining_ssp_basis(400000, JAN1, DEC31, date(2025, 7, 15)) == 186301


def test_d8_basis_is_the_whole_ssp_before_the_service_starts() -> None:
    assert remaining_ssp_basis(400000, JAN1, DEC31, date(2024, 6, 1)) == 400000
    assert remaining_ssp_basis(400000, JAN1, DEC31, JAN1) == 400000


def test_d8_basis_on_the_last_day_is_one_day() -> None:
    assert remaining_ssp_basis(36500, JAN1, DEC31, DEC31) == 100

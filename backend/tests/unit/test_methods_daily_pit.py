"""P3-T3: ratable_daily and point_in_time with deliveries (plan §5.3, D2, D3)."""

from datetime import date, timedelta
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engine.methods import (
    DeliveryTranche,
    ScheduleAmount,
    point_in_time,
    ratable_daily,
)
from app.engine.periods import period_bounds, period_key


def amounts(schedule: list[ScheduleAmount]) -> list[int]:
    return [line.amount_cents for line in schedule]


# --------------------------------------------------------------------------- ratable daily


def test_u02_mid_month_start_uses_cumulative_rounding() -> None:
    """1,000.00 over 15 Mar 2025 - 14 Mar 2026 (365 days)."""
    schedule = ratable_daily(100_000, date(2025, 3, 15), date(2026, 3, 14))
    assert [line.service_period for line in schedule][0] == "202503"
    assert schedule[-1].service_period == "202603"
    assert len(schedule) == 13
    # March has 17 service days: 100,000 x 17 / 365 = 4,657.53 -> 46.58
    assert schedule[0].amount_cents == 4_658
    # April: cum(47 days) = 12,876.71 -> 12,877, minus 4,658 = 8,219
    assert schedule[1].amount_cents == 8_219
    assert sum(amounts(schedule)) == 100_000


def test_exact_half_day_rounds_up() -> None:
    # 1 cent over 2 days across a month end: cum(1 day) = 0.5 -> 1, then 1 - 1 = 0.
    schedule = ratable_daily(1, date(2025, 1, 31), date(2025, 2, 1))
    assert schedule == [ScheduleAmount("202501", 1), ScheduleAmount("202502", 0)]


def test_single_day_and_single_month() -> None:
    assert ratable_daily(500, date(2025, 3, 3), date(2025, 3, 3)) == [ScheduleAmount("202503", 500)]
    assert ratable_daily(500, date(2025, 3, 3), date(2025, 3, 20)) == [
        ScheduleAmount("202503", 500)
    ]


def test_leap_year_february_counts_29_days() -> None:
    schedule = ratable_daily(36_600, date(2028, 1, 1), date(2028, 12, 31))
    assert schedule[1] == ScheduleAmount("202802", 2_900)


def test_zero_allocation_and_bad_input() -> None:
    assert amounts(ratable_daily(0, date(2025, 1, 15), date(2025, 2, 14))) == [0, 0]
    with pytest.raises(ValueError, match="before service_start"):
        ratable_daily(100, date(2025, 2, 1), date(2025, 1, 1))
    with pytest.raises(ValueError, match="negative"):
        ratable_daily(-1, date(2025, 1, 1), date(2025, 1, 31))


@given(
    allocated=st.integers(0, 10**13),
    start_offset=st.integers(0, 3_000),
    length=st.integers(0, 1_500),
)
def test_daily_adds_up_and_every_period_is_within_a_cent(
    allocated: int, start_offset: int, length: int
) -> None:
    """Plan §11.1, §5.3: the total is exact; each period is within 0.01 of its unrounded amount."""
    start = date(2020, 1, 1) + timedelta(days=start_offset)
    end = start + timedelta(days=length)
    schedule = ratable_daily(allocated, start, end)
    assert sum(amounts(schedule)) == allocated
    total_days = length + 1
    assert all(line.amount_cents >= 0 for line in schedule)
    for line in schedule:
        first, last = period_bounds(line.service_period)
        days = (min(last, end) - max(first, start)).days + 1
        assert abs(line.amount_cents - Fraction(allocated * days, total_days)) <= 1
    assert schedule[0].service_period == period_key(start)
    assert schedule[-1].service_period == period_key(end)


# --------------------------------------------------------------------------- point in time


def test_u03_full_amount_in_the_completion_month() -> None:
    assert point_in_time(50_000, date(2025, 3, 20)) == [ScheduleAmount("202503", 50_000)]


def test_b01_training_on_15_january() -> None:
    assert point_in_time(140_000, date(2025, 1, 15)) == [ScheduleAmount("202501", 140_000)]


def test_deliveries_recognise_tranches_and_the_remainder_at_completion() -> None:
    """D3, as in X01: 18.90 with two quarter deliveries."""
    schedule = point_in_time(
        1_890,
        date(2027, 12, 31),
        [
            DeliveryTranche(date(2025, 3, 31), 250_000),
            DeliveryTranche(date(2026, 3, 31), 250_000),
        ],
    )
    assert schedule == [
        ScheduleAmount("202503", 473),  # 4.725 rounds up
        ScheduleAmount("202603", 473),
        ScheduleAmount("202712", 944),  # what is left, so the total stays exact
    ]


def test_fully_delivered_leaves_no_line_at_completion() -> None:
    schedule = point_in_time(
        666,
        date(2027, 12, 31),
        [DeliveryTranche(date(2025, 3, 31), 500_000), DeliveryTranche(date(2026, 3, 31), 500_000)],
    )
    assert schedule == [ScheduleAmount("202503", 333), ScheduleAmount("202603", 333)]


def test_deliveries_in_one_month_become_one_line() -> None:
    schedule = point_in_time(
        1_000,
        date(2025, 12, 31),
        [DeliveryTranche(date(2025, 3, 1), 100_000), DeliveryTranche(date(2025, 3, 31), 100_000)],
    )
    assert schedule == [ScheduleAmount("202503", 200), ScheduleAmount("202512", 800)]


def test_delivery_in_the_completion_month_merges_with_the_remainder() -> None:
    schedule = point_in_time(
        1_000, date(2025, 3, 31), [DeliveryTranche(date(2025, 3, 15), 250_000)]
    )
    assert schedule == [ScheduleAmount("202503", 1_000)]


def test_zero_allocation_gives_no_lines() -> None:
    assert point_in_time(0, date(2025, 3, 31)) == []


def test_e009_conditions_are_refused() -> None:
    """§5.3: Σ units_fraction > 1, or a delivery after the completion date."""
    with pytest.raises(ValueError, match="more than the whole"):
        point_in_time(
            100,
            date(2025, 12, 31),
            [
                DeliveryTranche(date(2025, 1, 1), 600_000),
                DeliveryTranche(date(2025, 2, 1), 400_001),
            ],
        )
    with pytest.raises(ValueError, match="after completion"):
        point_in_time(100, date(2025, 3, 1), [DeliveryTranche(date(2025, 3, 2), 100_000)])
    with pytest.raises(ValueError, match="negative"):
        point_in_time(-1, date(2025, 3, 1))


@given(
    allocated=st.integers(0, 10**13),
    fractions=st.lists(st.integers(1, 200_000), max_size=5),
    offsets=st.lists(st.integers(0, 720), min_size=5, max_size=5),
)
def test_point_in_time_always_adds_up_to_the_allocation(
    allocated: int, fractions: list[int], offsets: list[int]
) -> None:
    """P3-T3 property test: Σ schedule = allocation for random inputs."""
    start = date(2025, 1, 1)
    deliveries = [
        DeliveryTranche(start + timedelta(days=offsets[i]), f) for i, f in enumerate(fractions)
    ]
    schedule = point_in_time(allocated, date(2027, 12, 31), deliveries)
    assert sum(amounts(schedule)) == allocated
    assert all(line.amount_cents != 0 for line in schedule)
    assert [line.service_period for line in schedule] == sorted(
        line.service_period for line in schedule
    )

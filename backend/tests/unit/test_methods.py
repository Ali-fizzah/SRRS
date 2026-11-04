"""P2-T1: ratable_monthly in integer cents (plan §5.3, golden cases U01 and B01)."""

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engine.methods import ScheduleAmount, ratable_monthly
from app.engine.money import from_cents, round_half_up_div, to_cents
from app.engine.periods import next_period, period_bounds

JAN_1 = date(2025, 1, 1)
DEC_31 = date(2025, 12, 31)


def amounts(schedule: list[ScheduleAmount]) -> list[int]:
    return [line.amount_cents for line in schedule]


# --------------------------------------------------------------------------- acceptance


def test_b01_subscription_line_933_33_then_933_37() -> None:
    """Proposal §4.4: 11,200.00 over 12 months."""
    schedule = ratable_monthly(1_120_000, JAN_1, DEC_31)
    assert amounts(schedule) == [93_333] * 11 + [93_337]
    assert sum(amounts(schedule)) == 1_120_000


def test_u01_twelve_equal_months() -> None:
    """U01: 1,200.00, 1 Jan to 31 Dec: 100.00 x 12."""
    assert ratable_monthly(120_000, JAN_1, DEC_31) == [
        ScheduleAmount(f"2025{month:02d}", 10_000) for month in range(1, 13)
    ]


# --------------------------------------------------------------------------- the rule


def test_periods_cross_a_year_end_and_keep_their_order() -> None:
    schedule = ratable_monthly(30_000, date(2025, 11, 1), date(2026, 1, 31))
    assert [line.service_period for line in schedule] == ["202511", "202512", "202601"]


def test_one_month_gets_the_whole_amount() -> None:
    assert ratable_monthly(12_345, date(2028, 2, 1), date(2028, 2, 29)) == [
        ScheduleAmount("202802", 12_345)
    ]


def test_exact_half_rounds_up_and_the_last_month_absorbs_the_difference() -> None:
    # 100 cents over 8 months = 12.5 -> 13 (half up; banker's rounding would give 12).
    schedule = ratable_monthly(100, JAN_1, date(2025, 8, 31))
    assert amounts(schedule) == [13] * 7 + [9]


def test_rounding_down_puts_the_extra_in_the_last_month() -> None:
    # 100 cents over 3 months = 33.33 -> 33; the last month takes 34.
    assert amounts(ratable_monthly(100, JAN_1, date(2025, 3, 31))) == [33, 33, 34]


def test_zero_allocation_still_gives_every_month() -> None:
    assert amounts(ratable_monthly(0, JAN_1, date(2025, 3, 31))) == [0, 0, 0]


def test_very_large_amounts_stay_exact() -> None:
    allocated = 10**15 + 1  # a float could not hold every cent of this exactly
    schedule = ratable_monthly(allocated, JAN_1, date(2025, 3, 31))
    assert sum(amounts(schedule)) == allocated
    # 333,333,333,333,333.67 rounds up, so the last month takes what is left.
    assert amounts(schedule) == [333_333_333_333_334, 333_333_333_333_334, 333_333_333_333_333]


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2025, 1, 15), DEC_31),  # does not start on the 1st
        (JAN_1, date(2025, 12, 30)),  # does not end on a month end
        (date(2025, 2, 1), date(2025, 2, 27)),
        (date(2024, 2, 1), date(2024, 2, 28)),  # 2024 is a leap year: 29 is the month end
    ],
)
def test_windows_that_are_not_whole_months_are_refused(start: date, end: date) -> None:
    with pytest.raises(ValueError, match="whole months"):
        ratable_monthly(1_000, start, end)


def test_end_before_start_and_negative_amount_are_refused() -> None:
    with pytest.raises(ValueError, match="before service_start"):
        ratable_monthly(1_000, date(2025, 3, 1), date(2025, 1, 31))
    with pytest.raises(ValueError, match="negative"):
        ratable_monthly(-1, JAN_1, DEC_31)


def test_small_amount_gives_a_negative_last_month_as_the_formula_says() -> None:
    """The §5.3 formula, unchanged. 7 cents over 12 months: 0.58 -> 1, so the last month is
    7 - 11 = -4. Happens only for tiny amounts (at most 0.54 over 12 months, 5.94 over 36).
    Raised with M1: the plan does not say whether this is acceptable."""
    assert amounts(ratable_monthly(7, JAN_1, DEC_31)) == [1] * 11 + [-4]


# --------------------------------------------------------------------------- properties


@given(
    allocated=st.integers(min_value=0, max_value=10**15),
    first_year=st.integers(min_value=2020, max_value=2035),
    first_month=st.integers(min_value=1, max_value=12),
    months=st.integers(min_value=1, max_value=120),
)
def test_any_schedule_adds_up_to_the_allocation(
    allocated: int, first_year: int, first_month: int, months: int
) -> None:
    """Pass rule (plan §11.1): every PO's schedule total exactly equals its allocation."""
    first = f"{first_year:04d}{first_month:02d}"
    last = first
    for _ in range(months - 1):
        last = next_period(last)
    schedule = ratable_monthly(allocated, period_bounds(first)[0], period_bounds(last)[1])

    assert sum(amounts(schedule)) == allocated
    assert len(schedule) == months
    assert schedule[0].service_period == first and schedule[-1].service_period == last
    assert len({line.amount_cents for line in schedule[:-1]}) <= 1  # equal months


@given(
    numerator=st.integers(min_value=0, max_value=10**18),
    denominator=st.integers(min_value=1, max_value=10**6),
)
def test_round_half_up_div_is_within_half_of_the_true_value(
    numerator: int, denominator: int
) -> None:
    result = round_half_up_div(numerator, denominator)
    # Compare with exact integers: |result - n/d| <= 1/2, and a tie goes up.
    assert -denominator < 2 * (result * denominator - numerator) <= denominator


@given(cents=st.integers(min_value=-(10**15), max_value=10**15))
def test_cents_and_decimal_money_convert_exactly_both_ways(cents: int) -> None:
    money = from_cents(cents)
    assert money.as_tuple().exponent == -2
    assert to_cents(money) == cents


def test_money_conversion_examples_and_refusal() -> None:
    assert to_cents(Decimal("933.37")) == 93_337
    assert to_cents(Decimal("100")) == 10_000
    assert str(from_cents(93_337)) == "933.37"
    assert str(from_cents(5)) == "0.05"
    with pytest.raises(ValueError, match="whole number of cents"):
        to_cents(Decimal("1.005"))


def test_round_half_up_div_refuses_what_it_does_not_define() -> None:
    with pytest.raises(ValueError):
        round_half_up_div(-1, 2)
    with pytest.raises(ValueError):
        round_half_up_div(1, 0)

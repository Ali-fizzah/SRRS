"""Period key helpers (plan D14)."""

from datetime import date

import pytest

from app.engine.periods import iter_periods, next_period, parse_period, period_bounds, period_key


def test_bounds_handle_month_lengths_and_leap_years() -> None:
    assert period_bounds("202501") == (date(2025, 1, 1), date(2025, 1, 31))
    assert period_bounds("202502") == (date(2025, 2, 1), date(2025, 2, 28))
    assert period_bounds("202802") == (date(2028, 2, 1), date(2028, 2, 29))
    assert period_bounds("202504") == (date(2025, 4, 1), date(2025, 4, 30))


def test_next_period_rolls_over_the_year() -> None:
    assert next_period("202511") == "202512"
    assert next_period("202512") == "202601"


def test_iter_periods_is_inclusive() -> None:
    keys = list(iter_periods("202501", "202812"))
    assert len(keys) == 48
    assert keys[0] == "202501" and keys[-1] == "202812"
    assert list(iter_periods("202503", "202503")) == ["202503"]
    assert list(iter_periods("202504", "202503")) == []


def test_period_key_of_a_date() -> None:
    assert period_key(date(2026, 11, 3)) == "202611"


@pytest.mark.parametrize("bad", ["2025-01", "202513", "202500", "25001", "abcdef", ""])
def test_invalid_keys_are_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_period(bad)

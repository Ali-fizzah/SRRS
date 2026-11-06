"""P3-T1: SSP resolution, one test per source, and history by effective date (plan §5.2)."""

from datetime import date

import pytest

from app.engine.ssp import SspRuleData, line_ssp_cents, rule_on

D = date(2025, 1, 1)


def test_fixed_uses_the_value_not_the_list_price() -> None:
    rule = SspRuleData("FIXED", D, value_cents=9_025)
    assert line_ssp_cents(rule, 10_000, 10_000) == 9_025


def test_list_price_uses_the_list_price() -> None:
    rule = SspRuleData("LIST_PRICE", D)
    assert line_ssp_cents(rule, 10_000, 10_000) == 10_000


def test_percent_of_list() -> None:
    rule = SspRuleData("PCT_OF_LIST", D, pct_e4=805_000)  # 80.5%
    assert line_ssp_cents(rule, 10_000, 10_000) == 8_050


@pytest.mark.parametrize(
    ("rule", "list_price", "quantity_e4", "expected"),
    [
        (SspRuleData("FIXED", D, value_cents=1_000), 0, 25_000, 2_500),  # 2.5 units
        (SspRuleData("LIST_PRICE", D), 3_333, 15_000, 5_000),  # 49.995 rounds up
        (SspRuleData("PCT_OF_LIST", D, pct_e4=500_000), 3_333, 10_000, 1_667),  # 16.665 rounds up
        (SspRuleData("FIXED", D, value_cents=0), 100, 10_000, 0),
    ],
    ids=["fractional quantity", "half up", "percent half up", "zero"],
)
def test_ssp_is_unit_ssp_times_quantity_rounded_half_up(
    rule: SspRuleData, list_price: int, quantity_e4: int, expected: int
) -> None:
    assert line_ssp_cents(rule, list_price, quantity_e4) == expected


def test_rounding_happens_once_at_the_end() -> None:
    # 33.33 x 12.5% = 4.16625 per unit. Rounded first: 4.17 x 3 = 12.51. Rounded last: 12.50.
    rule = SspRuleData("PCT_OF_LIST", D, pct_e4=125_000)
    assert line_ssp_cents(rule, 3_333, 30_000) == 1_250


def test_a_rule_without_its_value_is_refused() -> None:
    with pytest.raises(ValueError):
        line_ssp_cents(SspRuleData("FIXED", D), 100, 10_000)
    with pytest.raises(ValueError):
        line_ssp_cents(SspRuleData("PCT_OF_LIST", D), 100, 10_000)


def history() -> list[SspRuleData]:
    return [
        SspRuleData("FIXED", date(2024, 1, 1), value_cents=100, sequence=1),
        SspRuleData("FIXED", date(2025, 1, 1), date(2025, 6, 30), value_cents=200, sequence=2),
        SspRuleData("FIXED", date(2026, 1, 1), value_cents=300, sequence=3),
    ]


@pytest.mark.parametrize(
    ("when", "value"),
    [
        (date(2024, 6, 1), 100),
        (date(2025, 1, 1), 200),  # the first day counts
        (date(2025, 6, 30), 200),  # the last day counts
        (date(2025, 7, 1), 100),  # the 2025 rule has ended; the 2024 one has no end
        (date(2026, 1, 1), 300),
    ],
)
def test_history_gives_the_rule_in_force_on_the_date(when: date, value: int) -> None:
    rule = rule_on(history(), when)
    assert rule is not None and rule.value_cents == value


def test_no_rule_before_the_first_one() -> None:
    assert rule_on(history(), date(2023, 12, 31)) is None
    assert rule_on([], D) is None


def test_the_later_rule_wins_a_tie_on_valid_from() -> None:
    rules = [
        SspRuleData("FIXED", D, value_cents=1, sequence=2),
        SspRuleData("FIXED", D, value_cents=2, sequence=1),
    ]
    rule = rule_on(rules, D)
    assert rule is not None and rule.value_cents == 1

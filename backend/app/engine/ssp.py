"""Standalone selling price (plan §5.2). Pure: integers in, integer cents out."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.engine.money import round_half_up_div

SspSource = Literal["FIXED", "LIST_PRICE", "PCT_OF_LIST"]


@dataclass(frozen=True)
class SspRuleData:
    source: SspSource
    valid_from: date
    valid_to: date | None = None
    value_cents: int | None = None  # FIXED
    pct_e4: int | None = None  # PCT_OF_LIST, in ten-thousandths of a percent: 80.5% = 805000
    sequence: int = 0  # later rules win a tie on valid_from


def rule_on(rules: Sequence[SspRuleData], when: date) -> SspRuleData | None:
    """The rule in force on a date: the latest valid_from not after it (history is kept, §5.2)."""
    in_force = [
        rule
        for rule in rules
        if rule.valid_from <= when and (rule.valid_to is None or when <= rule.valid_to)
    ]
    return max(in_force, key=lambda rule: (rule.valid_from, rule.sequence), default=None)


def line_ssp_cents(rule: SspRuleData, list_price_cents: int, quantity_e4: int) -> int:
    """SSP of a line = unit SSP x quantity (§5.2), rounded half up once, at the end (D2).

    `quantity_e4` is the quantity in ten-thousandths (NUMERIC(12,4)): 1.5 = 15000.
    """
    if rule.source == "FIXED":
        if rule.value_cents is None:
            raise ValueError("a FIXED rule needs a value")
        return round_half_up_div(rule.value_cents * quantity_e4, 10_000)
    if rule.source == "LIST_PRICE":
        return round_half_up_div(list_price_cents * quantity_e4, 10_000)
    if rule.pct_e4 is None:
        raise ValueError("a PCT_OF_LIST rule needs a percentage")
    # list price x (pct_e4 / 10^4) / 100 x (quantity_e4 / 10^4)
    return round_half_up_div(list_price_cents * rule.pct_e4 * quantity_e4, 100 * 10_000 * 10_000)

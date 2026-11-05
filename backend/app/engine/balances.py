"""Deferred revenue and unbilled receivables of one contract (plan §5.6). Pure: integer cents.

At any time a contract has one or the other, never both: billed > recognised is deferred
revenue; recognised > billed is an unbilled receivable. Inside a posting period, invoices and
credit notes come first (by document date, then number), then revenue.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal


@dataclass(frozen=True)
class BillingEvent:
    posting_period: str
    document_date: date
    number: str
    kind: Literal["INVOICE", "CREDIT_NOTE"]
    amount_cents: int


@dataclass(frozen=True)
class PeriodBalance:
    period: str
    opening_deferred: int
    opening_unbilled: int
    billings: int
    credit_notes: int
    recognised: int
    recognised_from_deferred: int
    closing_deferred: int
    closing_unbilled: int
    # Credit beyond the deferred balance. Uploads refuse this (E009, §5.6), so it should stay 0.
    credit_excess: int = 0
    # Posted reversal entries (§5.7): + raises the position, - lowers it. It keeps this rollforward
    # equal to the GL, because a reversal changes the GL but not the billing documents or schedule.
    adjustments: int = 0
    # The part of billings that cleared unbilled (§5.6), so it never reached deferred revenue.
    billed_to_unbilled: int = 0


def roll_forward(
    events: Sequence[BillingEvent],
    revenue_by_period: Mapping[str, int],
    adjustments_by_period: Mapping[str, int] | None = None,
) -> list[PeriodBalance]:
    """One row per period with activity:
    opening + billings - cleared + adjustments - credit notes - recognised = closing.

    The whole calculation is one running figure, billed minus recognised: positive is deferred
    revenue, negative is unbilled. It gives the §5.6 rules directly: an invoice clears unbilled
    first and the rest is deferred; revenue uses deferred first and the rest is unbilled.
    """
    adjustments = adjustments_by_period or {}
    periods = sorted(
        {event.posting_period for event in events} | set(revenue_by_period) | set(adjustments)
    )
    rows = []
    position = 0
    for period in periods:
        opening = position
        billings = credit_notes = credit_excess = 0
        in_period = [event for event in events if event.posting_period == period]
        for event in sorted(in_period, key=lambda e: (e.document_date, e.number)):
            if event.kind == "INVOICE":
                billings += event.amount_cents
                position += event.amount_cents
            else:
                credit_notes += event.amount_cents
                credit_excess += max(event.amount_cents - max(position, 0), 0)
                position -= event.amount_cents
        position += adjustments.get(period, 0)
        before_revenue = position
        recognised = revenue_by_period.get(period, 0)
        position -= recognised
        recognised_from_deferred = max(before_revenue, 0) - max(position, 0)
        adjustment = adjustments.get(period, 0)
        # Whatever else moved the deferred balance in the period went to or from unbilled.
        billed_to_unbilled = (
            max(opening, 0)
            + billings
            - credit_notes
            + adjustment
            - recognised_from_deferred
            - max(position, 0)
        )
        rows.append(
            PeriodBalance(
                period=period,
                opening_deferred=max(opening, 0),
                opening_unbilled=max(-opening, 0),
                billings=billings,
                credit_notes=credit_notes,
                recognised=recognised,
                recognised_from_deferred=recognised_from_deferred,
                closing_deferred=max(position, 0),
                closing_unbilled=max(-position, 0),
                credit_excess=credit_excess,
                adjustments=adjustment,
                billed_to_unbilled=billed_to_unbilled,
            )
        )
    return rows

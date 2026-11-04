"""Allocation of the transaction price (plan §5.2). Pure: integer cents in and out.

This is the single-obligation version (task P2-T2). Relative-SSP allocation across several
obligations, with the rounding plug, arrives in task P3-T2.
"""

from collections.abc import Sequence
from dataclasses import dataclass


class NoSeparateObligationError(ValueError):
    """Σ SSP = 0: the contract is rejected (plan §5.2)."""

    code = "E014"


class MultipleObligationsError(NotImplementedError):
    """Several separate obligations need the relative-SSP allocation of task P3-T2."""


@dataclass(frozen=True)
class AllocationLine:
    line_no: int
    net_cents: int  # quantity x unit price - discount
    is_separate: bool  # D4: non-separate lines add to TP but get no allocation
    ssp_cents: int  # unit SSP x quantity; discounts do not reduce it (§5.2)


@dataclass(frozen=True)
class Allocation:
    line_no: int
    allocated_cents: int


def transaction_price(lines: Sequence[AllocationLine]) -> int:
    """TP = Σ over all lines of quantity x unit price - discount (plan §5.1)."""
    return sum(line.net_cents for line in lines)


def allocate(lines: Sequence[AllocationLine]) -> list[Allocation]:
    """Plan §5.2 for a contract with one separate obligation: it receives the whole TP."""
    for line in lines:
        if line.net_cents < 0 or line.ssp_cents < 0:
            raise ValueError(f"line {line.line_no} has a negative amount")

    obligations = [line for line in lines if line.is_separate]
    if sum(line.ssp_cents for line in obligations) == 0:
        raise NoSeparateObligationError("the contract has no separate obligation with an SSP")
    if len(obligations) > 1:
        raise MultipleObligationsError(
            f"{len(obligations)} separate obligations: allocation across several is task P3-T2"
        )
    return [Allocation(obligations[0].line_no, transaction_price(lines))]

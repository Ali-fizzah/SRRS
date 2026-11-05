"""Allocation of the transaction price by relative SSP (plan §5.2). Pure: integer cents."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.engine.money import round_half_up_div


class NoSeparateObligationError(ValueError):
    """Σ SSP = 0: the contract is rejected (plan §5.2)."""

    code = "E014"


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
    """Plan §5.2.

    alloc_i = round_half_up(TP x SSP_i / Σ SSP); the rounding difference goes to the obligation
    with the largest SSP (tie: lowest line number), so allocations always add up to TP exactly.
    """
    for line in lines:
        if line.net_cents < 0 or line.ssp_cents < 0:
            raise ValueError(f"line {line.line_no} has a negative amount")

    obligations = sorted((line for line in lines if line.is_separate), key=lambda x: x.line_no)
    total_ssp = sum(line.ssp_cents for line in obligations)
    if total_ssp == 0:
        raise NoSeparateObligationError("the contract has no separate obligation with an SSP")

    tp = transaction_price(lines)
    amounts = {
        line.line_no: round_half_up_div(tp * line.ssp_cents, total_ssp) for line in obligations
    }
    largest = min(obligations, key=lambda line: (-line.ssp_cents, line.line_no))
    amounts[largest.line_no] += tp - sum(amounts.values())
    return [Allocation(line.line_no, amounts[line.line_no]) for line in obligations]

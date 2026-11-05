"""P2-T2 and P3-T2: allocation by relative SSP with the rounding plug (plan §5.2, D4)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engine.allocation import (
    Allocation,
    AllocationLine,
    NoSeparateObligationError,
    allocate,
    transaction_price,
)


def po(line_no: int, net: int, ssp: int) -> AllocationLine:
    return AllocationLine(line_no, net, is_separate=True, ssp_cents=ssp)


def fee(line_no: int, net: int) -> AllocationLine:
    return AllocationLine(line_no, net, is_separate=False, ssp_cents=0)


def test_u01_allocation_equals_the_transaction_price() -> None:
    """U01: one 1,200.00 subscription."""
    lines = [po(1, 120_000, 120_000)]
    assert transaction_price(lines) == 120_000
    assert allocate(lines) == [Allocation(1, 120_000)]


def test_b01_proposal_worked_example() -> None:
    """Plan §5.2: TP 12,600; SSP 12,000 + 1,500 = 13,500 -> 11,200.00 and 1,400.00."""
    lines = [po(1, 1_110_000, 1_200_000), po(2, 150_000, 150_000)]
    assert transaction_price(lines) == 1_260_000
    assert allocate(lines) == [Allocation(1, 1_120_000), Allocation(2, 140_000)]


def test_plug_goes_to_the_largest_ssp() -> None:
    lines = [po(1, 10, 1), po(2, 0, 1), po(3, 0, 1), po(4, 0, 3)]
    # 10 x 1/6 = 1.67 -> 2; 2; 2; 10 x 3/6 = 5 -> Σ = 11, so -1 goes to line 4, the largest.
    assert allocate(lines) == [
        Allocation(1, 2),
        Allocation(2, 2),
        Allocation(3, 2),
        Allocation(4, 4),
    ]


def test_tie_on_largest_ssp_goes_to_the_lowest_line_number() -> None:
    """B02: three equal SSPs, TP 1,000.00: 333.33 each, 0.01 left over goes to line 1."""
    lines = [po(3, 30_000, 120_000), po(1, 30_000, 120_000), po(2, 40_000, 120_000)]
    assert allocate(lines) == [
        Allocation(1, 33_334),
        Allocation(2, 33_333),
        Allocation(3, 33_333),
    ]


def test_setup_fee_adds_to_tp_but_gets_no_allocation() -> None:
    """D4: 1,200.00 subscription + 500.00 setup fee: the subscription carries all 1,700.00."""
    lines = [fee(1, 50_000), po(2, 120_000, 120_000)]
    assert transaction_price(lines) == 170_000
    assert allocate(lines) == [Allocation(2, 170_000)]


def test_excel_bundle_shape() -> None:
    """X01: 30.00 on a header line with SSP 0, shared by relative SSP of 18.90 and 11.10."""
    lines = [fee(1, 3_000), po(2, 0, 1_890), po(3, 0, 1_110)]
    assert allocate(lines) == [Allocation(2, 1_890), Allocation(3, 1_110)]


def test_discounts_reduce_the_allocation_not_the_ssp() -> None:
    assert allocate([po(1, 90_000, 120_000)]) == [Allocation(1, 90_000)]


def test_zero_price_allocates_zero() -> None:
    assert allocate([po(1, 0, 120_000), po(2, 0, 10_000)]) == [Allocation(1, 0), Allocation(2, 0)]


def test_an_obligation_with_zero_ssp_gets_nothing_while_others_have_ssp() -> None:
    assert allocate([po(1, 100, 100), po(2, 0, 0)]) == [Allocation(1, 100), Allocation(2, 0)]


@pytest.mark.parametrize(
    "lines",
    [
        [],
        [fee(1, 50_000)],
        [po(1, 120_000, 0)],
        [po(1, 60_000, 0), po(2, 60_000, 0), fee(3, 100)],
    ],
    ids=["no lines", "no separate line", "ssp is zero", "all ssp zero"],
)
def test_sum_of_ssp_zero_is_e014(lines: list[AllocationLine]) -> None:
    with pytest.raises(NoSeparateObligationError) as error:
        allocate(lines)
    assert error.value.code == "E014"


@pytest.mark.parametrize(
    "line",
    [po(1, -1, 100), po(1, 100, -1), fee(2, -1)],
    ids=["negative net", "negative ssp", "negative fee"],
)
def test_negative_amounts_are_refused(line: AllocationLine) -> None:
    with pytest.raises(ValueError, match="negative"):
        allocate([po(9, 100, 100), line])


@given(
    obligations=st.lists(
        st.tuples(st.integers(0, 10**12), st.integers(1, 10**12)), min_size=1, max_size=8
    ),
    fees=st.lists(st.integers(0, 10**10), max_size=3),
)
def test_allocations_always_add_up_to_the_tp(
    obligations: list[tuple[int, int]], fees: list[int]
) -> None:
    lines = [po(i + 1, net, ssp) for i, (net, ssp) in enumerate(obligations)]
    lines += [fee(100 + i, cents) for i, cents in enumerate(fees)]
    result = allocate(lines)
    assert sum(a.allocated_cents for a in result) == transaction_price(lines)
    assert [a.line_no for a in result] == [line.line_no for line in lines if line.is_separate]

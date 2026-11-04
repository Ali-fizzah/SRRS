"""P2-T2: allocation for contracts with one separate obligation (plan §5.2, D4)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engine.allocation import (
    Allocation,
    AllocationLine,
    MultipleObligationsError,
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


def test_setup_fee_adds_to_tp_but_gets_no_allocation() -> None:
    """D4: 1,200.00 subscription + 500.00 setup fee: the subscription carries all 1,700.00."""
    lines = [fee(1, 50_000), po(2, 120_000, 120_000)]
    assert transaction_price(lines) == 170_000
    assert allocate(lines) == [Allocation(2, 170_000)]


def test_bundle_header_carries_the_price_of_the_single_obligation() -> None:
    """The Excel shape: the price is on a header line with SSP 0 (D4)."""
    lines = [fee(1, 3_000), po(2, 0, 1_890)]
    assert allocate(lines) == [Allocation(2, 3_000)]


def test_allocation_differs_from_ssp_when_the_price_does() -> None:
    """Discounts reduce TP, not SSP (§5.2): the obligation gets what was actually charged."""
    assert allocate([po(1, 90_000, 120_000)]) == [Allocation(1, 90_000)]


def test_zero_price_with_an_ssp_allocates_zero() -> None:
    assert allocate([po(1, 0, 120_000)]) == [Allocation(1, 0)]


@pytest.mark.parametrize(
    "lines",
    [
        [],
        [fee(1, 50_000)],  # only a setup fee
        [po(1, 120_000, 0)],  # a separate line whose SSP is 0
        [po(1, 60_000, 0), po(2, 60_000, 0), fee(3, 100)],
    ],
    ids=["no lines", "no separate line", "ssp is zero", "all ssp zero"],
)
def test_sum_of_ssp_zero_is_e014(lines: list[AllocationLine]) -> None:
    with pytest.raises(NoSeparateObligationError) as error:
        allocate(lines)
    assert error.value.code == "E014"


def test_several_obligations_wait_for_p3_t2_instead_of_guessing() -> None:
    """B01's bundle: refused now; P3-T2 must give 11,200.00 and 1,400.00."""
    lines = [po(1, 1_260_000, 1_200_000), po(2, 0, 150_000)]
    with pytest.raises(MultipleObligationsError, match="P3-T2"):
        allocate(lines)


@pytest.mark.parametrize(
    "line",
    [po(1, -1, 100), po(1, 100, -1), fee(2, -1)],
    ids=["negative net", "negative ssp", "negative fee"],
)
def test_negative_amounts_are_refused(line: AllocationLine) -> None:
    with pytest.raises(ValueError, match="negative"):
        allocate([po(9, 100, 100), line])


@given(
    net=st.integers(min_value=0, max_value=10**15),
    ssp=st.integers(min_value=1, max_value=10**15),
    fees=st.lists(st.integers(min_value=0, max_value=10**12), max_size=5),
)
def test_the_single_obligation_always_receives_exactly_the_tp(
    net: int, ssp: int, fees: list[int]
) -> None:
    lines = [po(1, net, ssp), *(fee(i + 2, cents) for i, cents in enumerate(fees))]
    (allocation,) = allocate(lines)
    assert allocation.line_no == 1
    assert allocation.allocated_cents == net + sum(fees) == transaction_price(lines)

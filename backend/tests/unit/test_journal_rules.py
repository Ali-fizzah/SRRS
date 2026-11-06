"""P4-T2, P4-T3: posting split, position effects and the GL mapping resolver (plan §5.6, D12)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engine.journal_rules import (
    GlResolver,
    MappingRow,
    MissingMappingError,
    ProductAccounts,
    position_effect,
    split_invoice,
    split_revenue,
)

CENTS = st.integers(min_value=0, max_value=10**10)
POSITION = st.integers(min_value=-(10**10), max_value=10**10)
PRODUCT = ProductAccounts(7, "SUB", "Digital", revenue_account_id=41)


def resolver(*rows: MappingRow) -> GlResolver:
    return GlResolver(rows, {1, 2, 3, 4, 41})


@pytest.mark.parametrize(
    ("position", "amount", "expected"),
    [
        (0, 100, (0, 100)),  # billed in advance: all deferred
        (-30, 100, (30, 70)),  # clears unbilled first
        (-100, 100, (100, 0)),
        (-500, 100, (100, 0)),
        (50, 100, (0, 100)),
    ],
)
def test_invoice_clears_unbilled_first(
    position: int, amount: int, expected: tuple[int, int]
) -> None:
    assert split_invoice(position, amount) == expected


@pytest.mark.parametrize(
    ("position", "amount", "expected"),
    [
        (500, 100, (100, 0)),  # already billed
        (30, 100, (30, 70)),  # deferred first, then unbilled
        (0, 100, (0, 100)),
        (-50, 100, (0, 100)),
    ],
)
def test_revenue_uses_deferred_first(position: int, amount: int, expected: tuple[int, int]) -> None:
    assert split_revenue(position, amount) == expected


@given(POSITION, CENTS)
def test_splits_always_add_up(position: int, amount: int) -> None:
    assert sum(split_invoice(position, amount)) == amount
    assert sum(split_revenue(position, amount)) == amount


@pytest.mark.parametrize(
    ("entry_type", "reversed_type", "total", "revenue_net", "effect"),
    [
        ("INVOICE", None, 100, 0, 100),
        ("CREDIT_NOTE", None, 100, 0, -100),
        ("REVENUE", None, 100, 100, -100),
        ("REVENUE_CATCH_UP", None, 100, 100, -100),
        ("REVERSAL", "INVOICE", 100, 0, -100),
        ("REVERSAL", "CREDIT_NOTE", 100, 0, 100),
        ("REVERSAL", "REVENUE", 100, -100, 100),
        ("REVERSAL", "REVENUE_CATCH_UP", 100, -100, 100),
    ],
)
def test_position_effect(
    entry_type: str, reversed_type: str | None, total: int, revenue_net: int, effect: int
) -> None:
    assert position_effect(entry_type, reversed_type, total, revenue_net) == effect


def test_an_entry_and_its_reversal_cancel_out() -> None:
    for kind, net in (("INVOICE", 0), ("CREDIT_NOTE", 0), ("REVENUE", 100)):
        assert (
            position_effect(kind, None, 100, net) + position_effect("REVERSAL", kind, 100, -net)
            == 0
        )


def test_precedence_is_product_then_category_then_default() -> None:
    default = MappingRow("AR", None, None, 1)
    category = MappingRow("AR", None, "Digital", 2)
    by_product = MappingRow("AR", 7, None, 3)
    assert resolver(default).account("AR", PRODUCT) == 1
    assert resolver(default, category).account("AR", PRODUCT) == 2
    assert resolver(default, category, by_product).account("AR", PRODUCT) == 3


def test_another_categorys_or_products_mapping_does_not_apply() -> None:
    rows = (
        MappingRow("AR", None, None, 1),
        MappingRow("AR", None, "Print", 2),
        MappingRow("AR", 99, None, 3),
    )
    assert resolver(*rows).account("AR", PRODUCT) == 1


def test_mappings_are_per_role() -> None:
    with pytest.raises(MissingMappingError) as caught:
        resolver(MappingRow("AR", None, None, 1)).account("DEFERRED_REVENUE", PRODUCT)
    assert caught.value.role == "DEFERRED_REVENUE"
    assert caught.value.product_code == "SUB"


def test_a_document_without_a_product_uses_the_default() -> None:
    assert resolver(MappingRow("AR", None, None, 1)).account("AR", None) == 1
    with pytest.raises(MissingMappingError):
        resolver().account("AR", None)


def test_revenue_uses_the_products_own_account_unless_mapped_for_that_product() -> None:
    assert resolver().account("REVENUE", PRODUCT) == 41
    # The product's own account outranks category and default mappings...
    rows = (MappingRow("REVENUE", None, None, 1), MappingRow("REVENUE", None, "Digital", 2))
    assert resolver(*rows).account("REVENUE", PRODUCT) == 41
    # ...and a mapping written for that exact product outranks it.
    assert resolver(*rows, MappingRow("REVENUE", 7, None, 3)).account("REVENUE", PRODUCT) == 3


def test_an_inactive_account_is_an_error_not_a_silent_fallback() -> None:
    rows = [MappingRow("AR", None, None, 1), MappingRow("AR", 7, None, 9)]
    with pytest.raises(MissingMappingError, match="inactive"):
        GlResolver(rows, {1}).account("AR", PRODUCT)

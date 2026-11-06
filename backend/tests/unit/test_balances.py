"""P3-T5: deferred revenue and unbilled receivables per contract (plan §5.6)."""

from datetime import date

from hypothesis import given
from hypothesis import strategies as st

from app.engine.balances import BillingEvent, PeriodBalance, roll_forward


def invoice(period: str, cents: int, number: str = "I1", day: int = 1) -> BillingEvent:
    when = date(int(period[:4]), int(period[4:]), day)
    return BillingEvent(period, when, number, "INVOICE", cents)


def credit(period: str, cents: int, number: str = "C1", day: int = 1) -> BillingEvent:
    when = date(int(period[:4]), int(period[4:]), day)
    return BillingEvent(period, when, number, "CREDIT_NOTE", cents)


def test_b01_end_of_january_deferred_is_10266_67() -> None:
    """Plan §11.3: 12,600.00 billed; 933.33 + 1,400.00 = 2,333.33 recognised in January."""
    (january,) = roll_forward([invoice("202501", 1_260_000)], {"202501": 233_333})
    assert january == PeriodBalance(
        period="202501",
        opening_deferred=0,
        opening_unbilled=0,
        billings=1_260_000,
        credit_notes=0,
        recognised=233_333,
        recognised_from_deferred=233_333,
        closing_deferred=1_026_667,
        closing_unbilled=0,
    )


def test_invoice_in_advance_then_monthly_recognition_rolls_forward() -> None:
    rows = roll_forward(
        [invoice("202501", 120_000)], {"202501": 10_000, "202502": 10_000, "202503": 10_000}
    )
    assert [r.closing_deferred for r in rows] == [110_000, 100_000, 90_000]
    assert [r.opening_deferred for r in rows] == [0, 110_000, 100_000]


def test_recognition_before_invoice_builds_unbilled_then_the_invoice_clears_it() -> None:
    """J03: revenue with nothing billed is unbilled; the invoice clears it, the rest is deferred."""
    first, second = roll_forward([invoice("202502", 50_000)], {"202501": 10_000, "202502": 10_000})
    assert (first.closing_unbilled, first.closing_deferred) == (10_000, 0)
    assert first.recognised_from_deferred == 0
    assert (second.opening_unbilled, second.billings) == (10_000, 50_000)
    assert (second.closing_unbilled, second.closing_deferred) == (0, 30_000)
    assert second.recognised_from_deferred == 10_000


def test_revenue_uses_deferred_first_and_the_rest_becomes_unbilled() -> None:
    (row,) = roll_forward([invoice("202501", 5_000)], {"202501": 8_000})
    assert row.recognised_from_deferred == 5_000
    assert (row.closing_deferred, row.closing_unbilled) == (0, 3_000)


def test_credit_note_reduces_deferred() -> None:
    """J02."""
    (row,) = roll_forward([invoice("202501", 10_000), credit("202501", 4_000, day=2)], {})
    assert (row.credit_notes, row.closing_deferred, row.credit_excess) == (4_000, 6_000, 0)


def test_documents_come_before_revenue_inside_a_period() -> None:
    """§5.6: otherwise this revenue would look unbilled for no reason."""
    (row,) = roll_forward([invoice("202501", 10_000)], {"202501": 10_000})
    assert (row.closing_deferred, row.closing_unbilled) == (0, 0)
    assert row.recognised_from_deferred == 10_000


def test_documents_are_ordered_by_date_then_number() -> None:
    """A credit dated before its invoice in the same period would otherwise look excessive."""
    events = [
        credit("202501", 4_000, "C1", day=20),
        invoice("202501", 10_000, "I2", day=10),
        invoice("202501", 1_000, "I1", day=10),
    ]
    (row,) = roll_forward(events, {})
    assert (row.billings, row.credit_excess, row.closing_deferred) == (11_000, 0, 7_000)


def test_credit_beyond_deferred_is_flagged_not_hidden() -> None:
    """Uploads refuse this with E009; if it ever reached here the excess is visible."""
    (row,) = roll_forward([invoice("202501", 1_000), credit("202501", 3_000, day=2)], {})
    assert row.credit_excess == 2_000


def test_nothing_gives_no_rows() -> None:
    assert roll_forward([], {}) == []


@given(
    movements=st.lists(
        st.tuples(
            st.sampled_from(["202501", "202502", "202503", "202504"]),
            st.integers(0, 10**9),
            st.integers(0, 10**9),
        ),
        max_size=12,
    )
)
def test_balances_never_both_and_always_reconcile(movements: list[tuple[str, int, int]]) -> None:
    """§5.6: deferred or unbilled, never both; opening + billings - recognised = closing."""
    events = []
    revenue: dict[str, int] = {}
    for index, (period, billed, earned) in enumerate(movements):
        events.append(invoice(period, billed, f"I{index}"))
        revenue[period] = revenue.get(period, 0) + earned
    previous = 0
    for row in roll_forward(events, revenue):
        assert row.closing_deferred == 0 or row.closing_unbilled == 0
        assert row.opening_deferred - row.opening_unbilled == previous
        closing = row.closing_deferred - row.closing_unbilled
        assert closing == previous + row.billings - row.credit_notes - row.recognised
        previous = closing

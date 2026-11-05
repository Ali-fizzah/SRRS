"""P5-T7: MRR and ARR (plan §5.9), and the rollforward footing that the report relies on (§5.6)."""

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engine.balances import BillingEvent, roll_forward
from app.engine.mrr import MrrLine, mrr_by_period, term_months

JAN1, DEC31 = date(2025, 1, 1), date(2025, 12, 31)


@pytest.mark.parametrize(
    ("start", "end", "months"),
    [
        (JAN1, DEC31, 12),
        (date(2025, 3, 15), date(2026, 3, 14), 12),
        (JAN1, date(2025, 1, 31), 1),
        (date(2025, 1, 1), date(2025, 1, 10), 1),  # a part month never rounds to zero
        (date(2025, 1, 1), date(2025, 2, 14), 2),  # 1.5 rounds up
        (date(2025, 1, 1), date(2025, 2, 10), 1),  # 1.36 rounds down
        (date(2024, 2, 29), date(2025, 2, 28), 12),
    ],
)
def test_term_is_the_nearest_whole_month(start: date, end: date, months: int) -> None:
    assert term_months(start, end) == months


def test_a_year_at_1200_is_100_a_month() -> None:
    result = mrr_by_period([MrrLine(120000, JAN1, DEC31)], "202412", "202601")
    assert result["202412"] == 0
    assert all(result[f"2025{m:02d}"] == 10000 for m in range(1, 13))
    assert result["202601"] == 0


def test_only_months_whose_end_is_inside_the_window_count() -> None:
    """15 Mar to 14 Mar: March's end is in, the next March's end is out."""
    line = MrrLine(120000, date(2025, 3, 15), date(2026, 3, 14))
    result = mrr_by_period([line], "202502", "202603")
    assert result["202502"] == 0
    assert result["202503"] == 10000
    assert result["202602"] == 10000
    assert result["202603"] == 0


def test_rounds_once_after_adding_up() -> None:
    """1,000 / 12 = 83.33333 twice: 166.67 together, not 83.33 + 83.33 = 166.66."""
    lines = [MrrLine(100000, JAN1, DEC31), MrrLine(100000, JAN1, DEC31)]
    assert mrr_by_period(lines, "202501", "202501")["202501"] == 16667


def test_a_cancellation_stops_mrr_but_keeps_the_original_term() -> None:
    line = MrrLine(120000, JAN1, DEC31, stopped_on=date(2025, 5, 31))
    result = mrr_by_period([line], "202505", "202506")
    assert result == {"202505": 10000, "202506": 0}


def test_cancelled_before_the_start_never_counts() -> None:
    line = MrrLine(120000, date(2025, 6, 1), DEC31, stopped_on=date(2025, 3, 31))
    assert set(mrr_by_period([line], "202501", "202512").values()) == {0}


def _invoice(period: str, cents: int, number: str = "I") -> BillingEvent:
    return BillingEvent(period, date(int(period[:4]), int(period[4:]), 1), number, "INVOICE", cents)


def test_billed_to_unbilled_is_what_cleared_unbilled() -> None:
    """J03: 200.00 unbilled, then a 300.00 invoice clears it and 100.00 becomes deferred."""
    rows = roll_forward(
        [_invoice("202503", 30000)], {"202501": 10000, "202502": 10000, "202503": 10000}
    )
    march = rows[-1]
    assert march.billed_to_unbilled == 20000
    assert march.recognised_from_deferred == 10000
    assert (march.closing_deferred, march.closing_unbilled) == (0, 0)


@given(
    st.lists(st.integers(min_value=0, max_value=10**7), min_size=6, max_size=6),
    st.lists(st.integers(min_value=0, max_value=10**7), min_size=6, max_size=6),
)
def test_the_rollforward_always_foots(invoices: list[int], revenue: list[int]) -> None:
    periods = [f"20250{m}" for m in range(1, 7)]
    events = [
        _invoice(period, cents, f"I{period}")
        for period, cents in zip(periods, invoices, strict=True)
    ]
    rows = roll_forward(events, dict(zip(periods, revenue, strict=True)))
    for row in rows:
        assert row.closing_deferred == (
            row.opening_deferred
            + row.billings
            - row.billed_to_unbilled
            - row.credit_notes
            + row.adjustments
            - row.recognised_from_deferred
        )
        assert row.closing_deferred == 0 or row.closing_unbilled == 0

"""Money arithmetic on integer cents (plan D1, D2). No float anywhere."""

from decimal import Decimal


def to_scaled(amount: Decimal, places: int) -> int:
    """A Decimal as a whole number of 10^-places units. Refuses anything finer."""
    scaled = amount.scaleb(places)
    if scaled != scaled.to_integral_value():
        raise ValueError(f"{amount} has more than {places} decimal places")
    return int(scaled)


def to_cents(amount: Decimal) -> int:
    """Decimal money from the database -> integer cents. Refuses anything finer than a cent."""
    cents = amount * 100
    if cents != cents.to_integral_value():
        raise ValueError(f"{amount} is not a whole number of cents")
    return int(cents)


def from_cents(cents: int) -> Decimal:
    """Integer cents -> Decimal money with two places, for NUMERIC(18,2)."""
    return Decimal(cents).scaleb(-2)


def round_half_up_div(numerator: int, denominator: int) -> int:
    """numerator / denominator rounded half up to a whole number, for numerator >= 0 (D2).

    Integer arithmetic only: (2n + d) // 2d, as written in plan §5.3.
    """
    if numerator < 0:
        raise ValueError(f"numerator must not be negative, got {numerator}")
    if denominator <= 0:
        raise ValueError(f"denominator must be positive, got {denominator}")
    return (2 * numerator + denominator) // (2 * denominator)

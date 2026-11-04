"""Money arithmetic on integer cents (plan D1, D2). No float anywhere."""


def round_half_up_div(numerator: int, denominator: int) -> int:
    """numerator / denominator rounded half up to a whole number, for numerator >= 0 (D2).

    Integer arithmetic only: (2n + d) // 2d, as written in plan §5.3.
    """
    if numerator < 0:
        raise ValueError(f"numerator must not be negative, got {numerator}")
    if denominator <= 0:
        raise ValueError(f"denominator must be positive, got {denominator}")
    return (2 * numerator + denominator) // (2 * denominator)

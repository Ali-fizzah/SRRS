"""Accounting period keys `YYYYMM` (plan D14). Pure functions: no DB, no clock."""

import calendar
import re
from collections.abc import Iterator
from datetime import date

_KEY = re.compile(r"^(\d{4})(0[1-9]|1[0-2])$")
_PARSED: dict[str, tuple[int, int]] = {}


def parse_period(key: str) -> tuple[int, int]:
    """'202501' -> (2025, 1). Raises ValueError for anything else."""
    known = _PARSED.get(key)
    if known is not None:
        return known
    match = _KEY.match(key)
    if match is None:
        raise ValueError(f"period key must be YYYYMM, got {key!r}")
    parsed = int(match.group(1)), int(match.group(2))
    _PARSED[key] = parsed  # the same few dozen months come up hundreds of thousands of times
    return parsed


def period_key(d: date) -> str:
    """The period containing `d`."""
    return f"{d.year:04d}{d.month:02d}"


def period_bounds(key: str) -> tuple[date, date]:
    """First and last calendar day of the period."""
    year, month = parse_period(key)
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def next_period(key: str) -> str:
    year, month = parse_period(key)
    return f"{year + 1:04d}01" if month == 12 else f"{year:04d}{month + 1:02d}"


def iter_periods(first: str, last: str) -> Iterator[str]:
    """Every period from `first` to `last`, inclusive, in order."""
    parse_period(last)
    key = first
    parse_period(key)
    while key <= last:
        yield key
        key = next_period(key)

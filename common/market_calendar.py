"""
US market (NYSE/NASDAQ) trading calendar.

Provides holiday-aware trading day logic for rebalance scheduling,
backtest date alignment, and catalyst timing calculations.

Holidays follow the NYSE observed holiday schedule. Handles:
- Fixed holidays (New Year's, Independence Day, Christmas, Juneteenth)
- Floating holidays (MLK, Presidents' Day, Good Friday, Memorial Day,
  Labor Day, Thanksgiving)
- Weekend/Friday/Monday observation rules

Usage:
    from common.market_calendar import is_trading_day, next_trading_day

    if not is_trading_day(date(2026, 12, 25)):
        d = next_trading_day(date(2026, 12, 25))
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List


def _easter(year: int) -> date:
    """Compute Easter Sunday via the Anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _observed(d: date) -> date:
    """Apply NYSE observation rule: Saturday→Friday, Sunday→Monday."""
    if d.weekday() == 5:  # Saturday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday
        return d + timedelta(days=1)
    return d


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the nth occurrence of a weekday in a given month.

    Args:
        weekday: 0=Monday ... 6=Sunday
        n: 1-based (1=first, 2=second, etc.)
    """
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """Return the last occurrence of a weekday in a given month."""
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)
    offset = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=offset)


def nyse_holidays(year: int) -> List[date]:
    """Return the list of NYSE market holidays for a given year.

    Covers all standard NYSE holidays from 2020 onward including
    Juneteenth (observed since 2022).
    """
    holidays = []

    # New Year's Day — Jan 1
    holidays.append(_observed(date(year, 1, 1)))

    # Martin Luther King Jr. Day — 3rd Monday in January
    holidays.append(_nth_weekday(year, 1, 0, 3))

    # Presidents' Day — 3rd Monday in February
    holidays.append(_nth_weekday(year, 2, 0, 3))

    # Good Friday — Friday before Easter Sunday
    easter = _easter(year)
    holidays.append(easter - timedelta(days=2))

    # Memorial Day — Last Monday in May
    holidays.append(_last_weekday(year, 5, 0))

    # Juneteenth — June 19 (NYSE observed since 2022)
    if year >= 2022:
        holidays.append(_observed(date(year, 6, 19)))

    # Independence Day — July 4
    holidays.append(_observed(date(year, 7, 4)))

    # Labor Day — 1st Monday in September
    holidays.append(_nth_weekday(year, 9, 0, 1))

    # Thanksgiving Day — 4th Thursday in November
    holidays.append(_nth_weekday(year, 11, 3, 4))

    # Christmas Day — Dec 25
    holidays.append(_observed(date(year, 12, 25)))

    return sorted(holidays)


# Cache holidays per year to avoid recomputation
_holiday_cache: dict[int, frozenset[date]] = {}


def _get_holidays(year: int) -> frozenset[date]:
    if year not in _holiday_cache:
        _holiday_cache[year] = frozenset(nyse_holidays(year))
    return _holiday_cache[year]


def is_trading_day(d: date) -> bool:
    """Return True if d is a NYSE trading day (not weekend, not holiday)."""
    if d.weekday() >= 5:
        return False
    return d not in _get_holidays(d.year)


def next_trading_day(d: date) -> date:
    """Return the next NYSE trading day strictly after d."""
    candidate = d + timedelta(days=1)
    while not is_trading_day(candidate):
        candidate += timedelta(days=1)
    return candidate


def prev_trading_day(d: date) -> date:
    """Return the most recent NYSE trading day strictly before d."""
    candidate = d - timedelta(days=1)
    while not is_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


def nearest_trading_day(d: date) -> date:
    """Return d if it's a trading day, otherwise the next trading day."""
    if is_trading_day(d):
        return d
    return next_trading_day(d)


def add_trading_days(d: date, n: int) -> date:
    """Add n trading days to d (negative n subtracts)."""
    step = 1 if n >= 0 else -1
    remaining = abs(n)
    current = d
    while remaining > 0:
        current += timedelta(days=step)
        if is_trading_day(current):
            remaining -= 1
    return current

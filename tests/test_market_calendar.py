"""Tests for common.market_calendar module."""

from __future__ import annotations

from datetime import date

from common.market_calendar import (
    add_trading_days,
    is_trading_day,
    nearest_trading_day,
    next_trading_day,
    nyse_holidays,
    prev_trading_day,
)


class TestNYSEHolidays:
    def test_2026_holiday_count(self):
        holidays = nyse_holidays(2026)
        assert len(holidays) == 10  # 9 standard + Juneteenth

    def test_christmas_2026_observed_on_friday(self):
        # Dec 25, 2026 is Friday
        holidays = nyse_holidays(2026)
        assert date(2026, 12, 25) in holidays

    def test_july_4_2026_observed(self):
        # July 4, 2026 is Saturday → observed Friday July 3
        holidays = nyse_holidays(2026)
        assert date(2026, 7, 3) in holidays

    def test_new_years_2027_observed(self):
        # Jan 1, 2027 is Friday
        holidays = nyse_holidays(2027)
        assert date(2027, 1, 1) in holidays

    def test_good_friday_2026(self):
        # Easter 2026 is April 5, Good Friday is April 3
        holidays = nyse_holidays(2026)
        assert date(2026, 4, 3) in holidays

    def test_juneteenth_not_before_2022(self):
        holidays = nyse_holidays(2021)
        june_19_observed = [h for h in holidays if h.month == 6 and 17 <= h.day <= 21]
        assert len(june_19_observed) == 0

    def test_juneteenth_from_2022(self):
        holidays = nyse_holidays(2022)
        june_obs = [h for h in holidays if h.month == 6 and 17 <= h.day <= 21]
        assert len(june_obs) == 1

    def test_thanksgiving_2026(self):
        # 4th Thursday in Nov 2026 = Nov 26
        holidays = nyse_holidays(2026)
        assert date(2026, 11, 26) in holidays


class TestIsTradingDay:
    def test_regular_weekday(self):
        assert is_trading_day(date(2026, 4, 7)) is True  # Tuesday

    def test_weekend_saturday(self):
        assert is_trading_day(date(2026, 4, 4)) is False

    def test_weekend_sunday(self):
        assert is_trading_day(date(2026, 4, 5)) is False

    def test_christmas(self):
        assert is_trading_day(date(2026, 12, 25)) is False

    def test_good_friday(self):
        assert is_trading_day(date(2026, 4, 3)) is False


class TestNextTradingDay:
    def test_regular(self):
        assert next_trading_day(date(2026, 4, 7)) == date(2026, 4, 8)

    def test_friday_to_monday(self):
        # April 10 (Fri) → April 13 (Mon)
        assert next_trading_day(date(2026, 4, 10)) == date(2026, 4, 13)

    def test_before_holiday(self):
        # April 2 (Thu) → April 6 (Mon) skipping Good Friday Apr 3
        assert next_trading_day(date(2026, 4, 2)) == date(2026, 4, 6)


class TestPrevTradingDay:
    def test_regular(self):
        assert prev_trading_day(date(2026, 4, 8)) == date(2026, 4, 7)

    def test_monday_to_friday(self):
        assert prev_trading_day(date(2026, 4, 13)) == date(2026, 4, 10)

    def test_after_holiday(self):
        # April 6 (Mon) → April 2 (Thu) skipping Good Friday Apr 3
        assert prev_trading_day(date(2026, 4, 6)) == date(2026, 4, 2)


class TestNearestTradingDay:
    def test_on_trading_day(self):
        assert nearest_trading_day(date(2026, 4, 7)) == date(2026, 4, 7)

    def test_on_weekend(self):
        assert nearest_trading_day(date(2026, 4, 4)) == date(2026, 4, 6)


class TestAddTradingDays:
    def test_add_positive(self):
        assert add_trading_days(date(2026, 4, 7), 3) == date(2026, 4, 10)

    def test_add_negative(self):
        assert add_trading_days(date(2026, 4, 10), -3) == date(2026, 4, 7)

    def test_add_zero(self):
        assert add_trading_days(date(2026, 4, 7), 0) == date(2026, 4, 7)

    def test_add_across_weekend(self):
        # Fri Apr 10 + 1 = Mon Apr 13
        assert add_trading_days(date(2026, 4, 10), 1) == date(2026, 4, 13)

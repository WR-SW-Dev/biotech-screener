"""Tests for common.price_store.PriceStore."""

import os
import textwrap

import pytest

from common.price_store import PriceStore


@pytest.fixture()
def csv_file(tmp_path):
    """Write a small price CSV and return its path."""
    p = tmp_path / "price_history.csv"
    p.write_text(
        textwrap.dedent(
            """\
            date,ticker,close,open,high,low,volume
            2024-01-02,AAAA,10.5,,,,
            2024-01-03,AAAA,11.0,,,,
            2024-01-02,BBBB,20.0,,,,
            2024-01-03,BBBB,21.5,,,,
            2024-01-04,BBBB,22.0,,,,
            2024-01-02,CCCC,,,,,
        """
        )
    )
    return str(p)


@pytest.fixture()
def store(tmp_path, csv_file):
    """Build a PriceStore from the fixture CSV."""
    db = str(tmp_path / "test_prices.db")
    s = PriceStore(db)
    s.build_from_csv(csv_file)
    yield s
    s.close()


class TestBuildFromCSV:
    def test_creates_database(self, tmp_path, csv_file):
        db = str(tmp_path / "new.db")
        assert not os.path.exists(db)
        s = PriceStore(db)
        n = s.build_from_csv(csv_file)
        s.close()
        assert os.path.exists(db)
        assert n == 5  # CCCC row has no close -> skipped

    def test_row_count(self, store):
        assert store.ticker_count() == 2  # AAAA, BBBB (CCCC skipped)


class TestGetPrice:
    def test_returns_correct_value(self, store):
        assert store.get_price("AAAA", "2024-01-02") == pytest.approx(10.5)
        assert store.get_price("BBBB", "2024-01-04") == pytest.approx(22.0)

    def test_missing_ticker_returns_none(self, store):
        assert store.get_price("ZZZZ", "2024-01-02") is None

    def test_missing_date_returns_none(self, store):
        assert store.get_price("AAAA", "2099-01-01") is None


class TestGetPriceRange:
    def test_returns_sorted(self, store):
        rows = store.get_price_range("BBBB", "2024-01-02", "2024-01-04")
        assert len(rows) == 3
        dates = [r[0] for r in rows]
        assert dates == sorted(dates)

    def test_respects_bounds(self, store):
        rows = store.get_price_range("BBBB", "2024-01-03", "2024-01-04")
        assert len(rows) == 2
        assert rows[0] == ("2024-01-03", pytest.approx(21.5))

    def test_empty_range(self, store):
        rows = store.get_price_range("AAAA", "2099-01-01", "2099-12-31")
        assert rows == []


class TestGetLatestDate:
    def test_latest_date(self, store):
        assert store.get_latest_date() == "2024-01-04"

    def test_empty_store(self, tmp_path):
        s = PriceStore(str(tmp_path / "empty.db"))
        assert s.get_latest_date() is None
        s.close()

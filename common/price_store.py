"""SQLite-based price storage — opt-in alternative to reading price_history.csv directly.

Usage:
    from common.price_store import PriceStore
    store = PriceStore("data/prices.db")
    store.build_from_csv("price_history.csv")
    price = store.get_price("BIIB", "2024-01-05")

CLI:
    python3 -m common.price_store build [--csv price_history.csv] [--db data/prices.db]
"""

from __future__ import annotations

import argparse
import csv
import os
import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    close REAL NOT NULL,
    PRIMARY KEY (date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_ticker_date ON prices (ticker, date);
"""

_INSERT = "INSERT OR REPLACE INTO prices (date, ticker, close) VALUES (?, ?, ?)"


class PriceStore:
    """Thin SQLite wrapper over (date, ticker, close) triples."""

    def __init__(self, db_path: str | Path = "data/prices.db") -> None:
        self._db_path = str(db_path)
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------
    def build_from_csv(self, csv_path: str | Path = "price_history.csv") -> int:
        """Read *price_history.csv* and upsert all rows. Returns row count."""
        cur = self._conn.cursor()
        cur.execute("DELETE FROM prices")
        count = 0
        with open(csv_path, newline="") as fh:
            reader = csv.DictReader(fh)
            batch: list[tuple] = []
            for row in reader:
                close_raw = row.get("close", "")
                if not close_raw:
                    continue
                try:
                    close = float(close_raw)
                except ValueError:
                    continue
                batch.append((row["date"], row["ticker"], close))
                if len(batch) >= 50_000:
                    cur.executemany(_INSERT, batch)
                    count += len(batch)
                    batch.clear()
            if batch:
                cur.executemany(_INSERT, batch)
                count += len(batch)
        self._conn.commit()
        return count

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def get_price(self, ticker: str, date: str) -> Optional[float]:
        """Return the close price for *ticker* on *date*, or None."""
        row = self._conn.execute(
            "SELECT close FROM prices WHERE ticker = ? AND date = ?",
            (ticker, date),
        ).fetchone()
        return row[0] if row else None

    def get_price_range(self, ticker: str, start_date: str, end_date: str) -> List[Tuple[str, float]]:
        """Return [(date, close), ...] sorted by date for the given range."""
        rows = self._conn.execute(
            "SELECT date, close FROM prices WHERE ticker = ? AND date >= ? AND date <= ? ORDER BY date",
            (ticker, start_date, end_date),
        ).fetchall()
        return rows

    def get_latest_date(self) -> Optional[str]:
        """Return the most recent date string in the store, or None if empty."""
        row = self._conn.execute("SELECT MAX(date) FROM prices").fetchone()
        return row[0] if row and row[0] else None

    def ticker_count(self) -> int:
        """Return the number of unique tickers."""
        row = self._conn.execute("SELECT COUNT(DISTINCT ticker) FROM prices").fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------
    def close(self) -> None:
        self._conn.close()

    def _ensure_schema(self) -> None:
        cur = self._conn.cursor()
        for stmt in _SCHEMA.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
        self._conn.commit()


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def _cli() -> None:
    parser = argparse.ArgumentParser(description="Price store CLI")
    sub = parser.add_subparsers(dest="command")
    build_p = sub.add_parser("build", help="Rebuild SQLite from CSV")
    build_p.add_argument("--csv", default="price_history.csv")
    build_p.add_argument("--db", default="data/prices.db")
    args = parser.parse_args()

    if args.command == "build":
        store = PriceStore(args.db)
        n = store.build_from_csv(args.csv)
        latest = store.get_latest_date()
        tickers = store.ticker_count()
        print(f"Loaded {n:,} rows | {tickers} tickers | latest date: {latest}")
        store.close()
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()

"""Tests for the price-feed fix + hard-gate canary (2026-07-08 'only AARD' failure).

Root cause: extend_price_csv_safe -> safe_download_per_ticker used yf.download,
which returns MultiIndex columns; the long-format parser read row.get("Close")
(a tuple key under MultiIndex), dropped ~every row, and appended ~1 ticker/day.
Fix: flatten columns at the source + per-ticker start dates. Guardrail:
check_price_append_health hard-fails a silently broken append.
"""

from __future__ import annotations

import csv

import pandas as pd

import scripts.yfinance_safe as yfs
from scripts.yfinance_safe import _flatten_yf_columns
from tools.run_daily_production import check_price_append_health


# --- column flattening -----------------------------------------------------
def test_flatten_field_ticker_order():
    cols = pd.MultiIndex.from_tuples([("Close", "AARD"), ("Open", "AARD"), ("Volume", "AARD")])
    df = pd.DataFrame([[1.0, 2.0, 100]], index=pd.to_datetime(["2026-07-08"]), columns=cols)
    assert list(_flatten_yf_columns(df).columns) == ["Close", "Open", "Volume"]


def test_flatten_ticker_field_order():
    cols = pd.MultiIndex.from_tuples([("AARD", "Close"), ("AARD", "Open")])
    df = pd.DataFrame([[1.0, 2.0]], index=pd.to_datetime(["2026-07-08"]), columns=cols)
    assert list(_flatten_yf_columns(df).columns) == ["Close", "Open"]


def test_flatten_noop_on_flat():
    df = pd.DataFrame({"Close": [1.0], "Open": [2.0]})
    assert list(_flatten_yf_columns(df).columns) == ["Close", "Open"]


# --- safe_download_per_ticker: flatten + per-ticker starts ------------------
def test_safe_download_flattens_and_uses_per_ticker_starts(monkeypatch):
    calls = {}

    def fake_download(ticker, start, end, progress=False):
        calls[ticker] = start
        cols = pd.MultiIndex.from_tuples(
            [("Close", ticker), ("Open", ticker), ("High", ticker), ("Low", ticker), ("Volume", ticker)]
        )
        return pd.DataFrame([[10.0, 9.0, 11.0, 8.0, 1000]], index=pd.to_datetime(["2026-07-08"]), columns=cols)

    monkeypatch.setattr(yfs.yf, "download", fake_download)
    res = yfs.safe_download_per_ticker(
        ["AARD", "ABCL"],
        start="2026-01-01",
        end="2026-07-09",
        delay_sec=0,
        starts={"AARD": "2026-07-08", "ABCL": "2026-07-05"},
    )
    # each ticker fetched from its OWN start (the bug used one shared start)
    assert calls == {"AARD": "2026-07-08", "ABCL": "2026-07-05"}
    data = res["data"]
    assert "Close" in data.columns and "ticker" in data.columns
    assert set(data["ticker"]) == {"AARD", "ABCL"}


# --- extend_price_csv_safe: parser now consumes flat rows for ALL tickers ---
def test_extend_appends_all_tickers(monkeypatch, tmp_path):
    import scripts.backtest_signal_robustness as bsr

    csv_path = tmp_path / "ph.csv"
    csv_path.write_text(
        "date,ticker,close,open,high,low,volume\n"
        "2026-07-07,AARD,5,5,5,5,10\n"
        "2026-07-07,ABCL,6,6,6,6,20\n"
        "2026-07-07,XBI,100,100,100,100,50\n"
    )

    def fake_safe(ticker_list, start, end, delay_sec=1.5, max_retries=3, starts=None):
        rows = [{"Close": 9.0, "Open": 9.0, "High": 9.0, "Low": 9.0, "Volume": 100, "ticker": t} for t in ticker_list]
        df = pd.DataFrame(rows, index=pd.DatetimeIndex([pd.Timestamp("2026-07-08")] * len(ticker_list)))
        return {"data": df, "failed_tickers": [], "successful_tickers": len(ticker_list), "rate_limit_hits": 0}

    # extend_price_csv_safe re-imports the symbol from scripts.yfinance_safe inside
    # the function, so patch it at the source module.
    monkeypatch.setattr("scripts.yfinance_safe.safe_download_per_ticker", fake_safe)

    stats = bsr.extend_price_csv_safe(csv_path, through_date="2026-07-08", tickers=["AARD", "ABCL"], include_xbi=True)
    assert stats["n_rows_appended"] == 3  # AARD, ABCL, XBI each get 2026-07-08

    dates = {}
    with open(csv_path) as f:
        for r in csv.DictReader(f):
            dates.setdefault(r["ticker"], set()).add(r["date"])
    for t in ["AARD", "ABCL", "XBI"]:
        assert "2026-07-08" in dates[t]


# --- hard-gate canary ------------------------------------------------------
def test_canary_fails_on_broken_append():
    g = check_price_append_health({"n_extended": 346, "n_rows_appended": 1, "n_already_current": 2})
    assert g.status == "FAIL"


def test_canary_passes_on_healthy_append():
    g = check_price_append_health({"n_extended": 346, "n_rows_appended": 340, "n_already_current": 2})
    assert g.status == "PASS"


def test_canary_not_applicable_when_little_fetch_needed():
    # weekend / already-current re-run: few tickers needed fetch -> not a signal
    g = check_price_append_health({"n_extended": 3, "n_rows_appended": 0, "n_already_current": 345})
    assert g.status == "PASS"

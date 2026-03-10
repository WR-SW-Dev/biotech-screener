"""Tests for fill-adjusted P&L in live_shadow_portfolio.py."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import (
    _load_fill_data,
    compute_execution_quality_metrics,
    compute_performance,
    render_execution_quality_md,
)
from tools.record_fills import FILLS_COLUMNS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_price_csv(path, prices):
    """Write minimal price_history.csv.

    prices: list of (ticker, date, close) tuples.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "date", "open", "high", "low", "close", "volume"])
        w.writeheader()
        for ticker, date, close in prices:
            w.writerow(
                {
                    "ticker": ticker,
                    "date": date,
                    "open": str(close),
                    "high": str(close),
                    "low": str(close),
                    "close": str(close),
                    "volume": "1000",
                }
            )


def _write_fills_csv(path, fills):
    """Write fills.csv from list of dicts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FILLS_COLUMNS)
        w.writeheader()
        w.writerows(fills)


def _make_positions(tickers_and_buckets, dollars=10000):
    """Create position dicts from (ticker, bucket) pairs."""
    return [
        {
            "ticker": t,
            "bucket": b,
            "target_dollars": dollars,
            "gap_risk": "",
            "price_coverage": "OK",
            "actionable_rank": i + 1,
        }
        for i, (t, b) in enumerate(tickers_and_buckets)
    ]


def _make_fill(ticker, action, target_usd, fill_price, fill_shares, status="FILLED"):
    fill_usd = round(fill_price * fill_shares, 2)
    # Slippage for BUY: positive = worse (paid more than target)
    slip = round((fill_usd / abs(target_usd) - 1.0) * 10000, 2) if abs(target_usd) > 0.01 else 0.0
    return {
        "ticker": ticker,
        "action": action,
        "target_usd": str(round(abs(target_usd), 2)),
        "fill_price": str(round(fill_price, 4)),
        "fill_shares": str(round(fill_shares, 4)),
        "fill_usd": str(fill_usd),
        "slippage_bps": str(slip),
        "fill_date": "2026-03-10",
        "status": status,
    }


# ---------------------------------------------------------------------------
# 1. No fills path — entry_price_source="CLOSE", performance unchanged
# ---------------------------------------------------------------------------


class TestNoFillsPath:
    def test_no_fills_uses_close_prices(self, tmp_path):
        """When no fills exist, performance uses close prices only."""
        price_csv = tmp_path / "prices.csv"
        _write_price_csv(
            price_csv,
            [
                ("ACME", "2026-03-03", 10.0),
                ("ACME", "2026-03-10", 11.0),
                ("XBI", "2026-03-03", 100.0),
                ("XBI", "2026-03-10", 101.0),
            ],
        )

        prior = _make_positions([("ACME", "binary_91_180")])
        current = _make_positions([("ACME", "binary_91_180")])

        perf = compute_performance(
            prior,
            current,
            "2026-03-03",
            "2026-03-10",
            price_path=price_csv,
            trades_root=tmp_path / "trades",  # No fills dir
        )

        assert perf["total_pnl"] == pytest.approx(1000.0, abs=0.01)
        assert perf["pnl_pct"] == pytest.approx(10.0, abs=0.01)
        # No fill data in perf
        assert perf.get("execution_quality") is None

    def test_load_fill_data_empty_when_no_files(self, tmp_path):
        fills = _load_fill_data("2026-03-03", fills_root=tmp_path / "fills", trades_root=tmp_path / "trades")
        assert fills == []


# ---------------------------------------------------------------------------
# 2. Fills applied — entry price uses fill VWAP
# ---------------------------------------------------------------------------


class TestFillsApplied:
    def test_fill_price_overrides_close_for_buy(self, tmp_path):
        """BUY fill VWAP should override close price for entry cost basis."""
        price_csv = tmp_path / "prices.csv"
        # Close on 03-03 was $10, but we filled at $10.50
        _write_price_csv(
            price_csv,
            [
                ("ACME", "2026-03-03", 10.0),
                ("ACME", "2026-03-10", 11.0),
                ("XBI", "2026-03-03", 100.0),
                ("XBI", "2026-03-10", 101.0),
            ],
        )

        # Write fills in the fills root (canonical path)
        fills_dir = tmp_path / "fills" / "2026-03-03"
        _write_fills_csv(
            fills_dir / "fills.csv",
            [_make_fill("ACME", "BUY", 10000, 10.50, 952.38)],
        )

        prior = _make_positions([("ACME", "binary_91_180")])
        current = _make_positions([("ACME", "binary_91_180")])

        perf = compute_performance(
            prior,
            current,
            "2026-03-03",
            "2026-03-10",
            price_path=price_csv,
            fills_root=tmp_path / "fills",
            trades_root=tmp_path / "trades",
        )

        # Entry at fill VWAP $10.50, exit at close $11.00
        # Return = (11/10.50 - 1) = 4.76% on $10k = $476.19
        expected_ret = 11.0 / 10.50 - 1.0
        expected_pnl = 10000 * expected_ret
        assert perf["total_pnl"] == pytest.approx(expected_pnl, abs=1.0)

    def test_slippage_sign_buy_positive_is_worse(self, tmp_path):
        """For BUY: fill above ref → positive slippage (worse)."""
        price_csv = tmp_path / "prices.csv"
        _write_price_csv(
            price_csv,
            [
                ("ACME", "2026-03-03", 10.0),
                ("ACME", "2026-03-10", 11.0),
            ],
        )

        fills_dir = tmp_path / "fills" / "2026-03-03"
        # Filled at $10.20, ref close was $10.00 → +200 bps slippage
        _write_fills_csv(
            fills_dir / "fills.csv",
            [_make_fill("ACME", "BUY", 10000, 10.20, 980.39)],
        )

        fill_data = _load_fill_data("2026-03-03", fills_root=tmp_path / "fills", trades_root=tmp_path / "trades")
        ref_prices = {"ACME": 10.0}

        metrics = compute_execution_quality_metrics(fill_data, ref_prices)

        buy_trades = [t for t in metrics["per_trade"] if t["side"] == "BUY"]
        assert len(buy_trades) == 1
        # BUY at $10.20 vs ref $10.00 → +200 bps (positive = worse for buyer)
        assert buy_trades[0]["slippage_vs_ref_bps"] == pytest.approx(200.0, abs=1.0)

    def test_slippage_sign_sell_positive_is_worse(self, tmp_path):
        """For SELL: fill below ref → positive slippage (worse)."""
        price_csv = tmp_path / "prices.csv"
        _write_price_csv(
            price_csv,
            [
                ("ACME", "2026-03-03", 10.0),
                ("ACME", "2026-03-10", 9.0),
            ],
        )

        fills_dir = tmp_path / "fills" / "2026-03-03"
        # SELL filled at $9.80, ref close was $10.00 → +200 bps slippage (worse for seller)
        _write_fills_csv(
            fills_dir / "fills.csv",
            [_make_fill("ACME", "SELL", 10000, 9.80, 1020.41)],
        )

        fill_data = _load_fill_data("2026-03-03", fills_root=tmp_path / "fills", trades_root=tmp_path / "trades")
        ref_prices = {"ACME": 10.0}

        metrics = compute_execution_quality_metrics(fill_data, ref_prices)

        sell_trades = [t for t in metrics["per_trade"] if t["side"] == "SELL"]
        assert len(sell_trades) == 1
        # SELL at $9.80 vs ref $10.00 → positive slippage (worse for seller)
        assert sell_trades[0]["slippage_vs_ref_bps"] == pytest.approx(200.0, abs=1.0)


# ---------------------------------------------------------------------------
# 3. Partial fills — mixed sources, coverage < 100%
# ---------------------------------------------------------------------------


class TestPartialFills:
    def test_partial_fill_mixed_sources(self, tmp_path):
        """One ticker filled, one not → mixed price sources, no crash."""
        price_csv = tmp_path / "prices.csv"
        _write_price_csv(
            price_csv,
            [
                ("ACME", "2026-03-03", 10.0),
                ("ACME", "2026-03-10", 11.0),
                ("BETA", "2026-03-03", 20.0),
                ("BETA", "2026-03-10", 22.0),
                ("XBI", "2026-03-03", 100.0),
                ("XBI", "2026-03-10", 101.0),
            ],
        )

        fills_dir = tmp_path / "fills" / "2026-03-03"
        # Only ACME has fills; BETA does not
        _write_fills_csv(
            fills_dir / "fills.csv",
            [
                _make_fill("ACME", "BUY", 10000, 10.50, 952.38),
                _make_fill("BETA", "BUY", 10000, 0, 0, status="SKIPPED"),
            ],
        )

        prior = _make_positions([("ACME", "binary_91_180"), ("BETA", "binary_31_90")])
        current = _make_positions([("ACME", "binary_91_180"), ("BETA", "binary_31_90")])

        perf = compute_performance(
            prior,
            current,
            "2026-03-03",
            "2026-03-10",
            price_path=price_csv,
            fills_root=tmp_path / "fills",
            trades_root=tmp_path / "trades",
        )

        # ACME: entry at fill $10.50, exit $11.00 → (11/10.50-1)*10000 = $476.19
        # BETA: entry at close $20.00, exit $22.00 → (22/20-1)*10000 = $1000.00
        assert perf["total_pnl"] == pytest.approx(476.19 + 1000.0, abs=5.0)

        # Execution quality should show partial coverage
        eq = perf.get("execution_quality")
        assert eq is not None
        assert eq["fill_coverage_pct"] < 100.0

    def test_fill_coverage_pct(self, tmp_path):
        """fill_coverage_pct = filled_notional / total_intended."""
        fills_dir = tmp_path / "fills" / "2026-03-03"
        _write_fills_csv(
            fills_dir / "fills.csv",
            [
                _make_fill("ACME", "BUY", 10000, 10.0, 1000),  # FILLED: $10k notional
                _make_fill("BETA", "BUY", 10000, 0, 0, status="SKIPPED"),  # SKIPPED
            ],
        )

        fill_data = _load_fill_data("2026-03-03", fills_root=tmp_path / "fills", trades_root=tmp_path / "trades")
        ref_prices = {"ACME": 10.0, "BETA": 20.0}

        metrics = compute_execution_quality_metrics(fill_data, ref_prices)
        # Intended: $10k + $10k = $20k. Filled: $10k. Coverage = 50%
        assert metrics["fill_coverage_pct"] == pytest.approx(50.0, abs=1.0)


# ---------------------------------------------------------------------------
# 4. Attribution rollups — bucket/family slippage totals
# ---------------------------------------------------------------------------


class TestAttributionRollups:
    def test_bucket_slippage_sums_to_total(self, tmp_path):
        """Per-bucket slippage $ must sum to portfolio total."""
        fills_dir = tmp_path / "fills" / "2026-03-03"
        _write_fills_csv(
            fills_dir / "fills.csv",
            [
                _make_fill("ACME", "BUY", 10000, 10.20, 980.39),  # binary_91_180
                _make_fill("BETA", "BUY", 10000, 20.40, 490.20),  # binary_31_90
            ],
        )

        fill_data = _load_fill_data("2026-03-03", fills_root=tmp_path / "fills", trades_root=tmp_path / "trades")

        # Annotate with buckets
        fill_data[0]["bucket"] = "binary_91_180"
        fill_data[1]["bucket"] = "binary_31_90"

        ref_prices = {"ACME": 10.0, "BETA": 20.0}
        metrics = compute_execution_quality_metrics(fill_data, ref_prices)

        # Check per-bucket
        by_bucket = metrics.get("by_bucket", {})
        total_slip_usd = metrics["total_slippage_usd"]

        bucket_sum = sum(v["slippage_usd"] for v in by_bucket.values())
        assert bucket_sum == pytest.approx(total_slip_usd, abs=0.01)

    def test_family_slippage_sums_to_total(self, tmp_path):
        """Per-family slippage $ must sum to portfolio total."""
        fills_dir = tmp_path / "fills" / "2026-03-03"
        _write_fills_csv(
            fills_dir / "fills.csv",
            [
                _make_fill("ACME", "BUY", 10000, 10.20, 980.39),
                _make_fill("BETA", "BUY", 10000, 20.40, 490.20),
            ],
        )

        fill_data = _load_fill_data("2026-03-03", fills_root=tmp_path / "fills", trades_root=tmp_path / "trades")

        fill_data[0]["effective_family"] = "REGULATORY"
        fill_data[1]["effective_family"] = "CLINICAL"

        ref_prices = {"ACME": 10.0, "BETA": 20.0}
        metrics = compute_execution_quality_metrics(fill_data, ref_prices)

        by_family = metrics.get("by_family", {})
        total_slip_usd = metrics["total_slippage_usd"]

        family_sum = sum(v["slippage_usd"] for v in by_family.values())
        assert family_sum == pytest.approx(total_slip_usd, abs=0.01)


# ---------------------------------------------------------------------------
# 5. Weekly summary rendering
# ---------------------------------------------------------------------------


class TestWeeklySummaryExecQuality:
    def test_render_execution_quality_md_includes_top_worst(self, tmp_path):
        """Rendered markdown includes top 5 worst slippage trades."""
        per_trade = [
            {
                "ticker": f"T{i}",
                "side": "BUY",
                "qty": 100,
                "vwap": 10.0 + i * 0.1,
                "ref_price": 10.0,
                "slippage_vs_ref_bps": i * 50,
                "notional": 1000,
            }
            for i in range(7)
        ]
        metrics = {
            "fill_coverage_pct": 85.7,
            "total_traded_usd": 7000,
            "total_slippage_usd": 35.0,
            "total_slippage_bps": 50.0,
            "per_trade": per_trade,
            "by_bucket": {},
            "by_family": {},
        }
        lines = render_execution_quality_md(metrics)
        text = "\n".join(lines)

        assert "Execution Quality" in text
        assert "85.7%" in text
        assert "T6" in text  # worst slippage trade

    def test_render_empty_when_no_metrics(self):
        """No execution quality → no output."""
        lines = render_execution_quality_md(None)
        assert lines == []


# ---------------------------------------------------------------------------
# 6. Entry annotations in positions JSON
# ---------------------------------------------------------------------------


class TestEntryAnnotationsNoFills:
    def test_annotations_close_when_no_fills(self, tmp_path):
        """No fills → entry_price_source='CLOSE', fill_* is None."""
        price_csv = tmp_path / "prices.csv"
        _write_price_csv(
            price_csv,
            [
                ("ACME", "2026-03-03", 10.0),
                ("ACME", "2026-03-10", 11.0),
            ],
        )

        prior = _make_positions([("ACME", "binary_91_180")])
        current = _make_positions([("ACME", "binary_91_180")])

        perf = compute_performance(
            prior,
            current,
            "2026-03-03",
            "2026-03-10",
            price_path=price_csv,
            trades_root=tmp_path / "trades",
        )

        ann = perf.get("entry_annotations", {})
        assert "ACME" in ann
        assert ann["ACME"]["entry_price_source"] == "CLOSE"
        assert ann["ACME"]["entry_price"] == 10.0
        assert ann["ACME"]["fill_qty"] is None
        assert ann["ACME"]["fill_vwap"] is None
        assert ann["ACME"]["fill_notional"] is None


class TestEntryAnnotationsWithFills:
    def test_annotations_fill_when_fills_exist(self, tmp_path):
        """Fills present → entry_price_source='FILL', fill_* populated."""
        price_csv = tmp_path / "prices.csv"
        _write_price_csv(
            price_csv,
            [
                ("ACME", "2026-03-03", 10.0),
                ("ACME", "2026-03-10", 11.0),
            ],
        )

        fills_dir = tmp_path / "fills" / "2026-03-03"
        _write_fills_csv(
            fills_dir / "fills.csv",
            [_make_fill("ACME", "BUY", 10000, 10.50, 952.38)],
        )

        prior = _make_positions([("ACME", "binary_91_180")])
        current = _make_positions([("ACME", "binary_91_180")])

        perf = compute_performance(
            prior,
            current,
            "2026-03-03",
            "2026-03-10",
            price_path=price_csv,
            fills_root=tmp_path / "fills",
            trades_root=tmp_path / "trades",
        )

        ann = perf["entry_annotations"]["ACME"]
        assert ann["entry_price_source"] == "FILL"
        assert ann["entry_price"] == pytest.approx(10.50, abs=0.01)
        assert ann["fill_vwap"] == pytest.approx(10.50, abs=0.01)
        assert ann["fill_qty"] == pytest.approx(952.38, abs=0.01)
        assert ann["fill_notional"] is not None


class TestEntryAnnotationsMixed:
    def test_mixed_fill_and_close_annotations(self, tmp_path):
        """One ticker filled, one not → correct per-ticker annotations."""
        price_csv = tmp_path / "prices.csv"
        _write_price_csv(
            price_csv,
            [
                ("ACME", "2026-03-03", 10.0),
                ("ACME", "2026-03-10", 11.0),
                ("BETA", "2026-03-03", 20.0),
                ("BETA", "2026-03-10", 22.0),
            ],
        )

        fills_dir = tmp_path / "fills" / "2026-03-03"
        _write_fills_csv(
            fills_dir / "fills.csv",
            [
                _make_fill("ACME", "BUY", 10000, 10.50, 952.38),
                _make_fill("BETA", "BUY", 10000, 0, 0, status="SKIPPED"),
            ],
        )

        prior = _make_positions([("ACME", "binary_91_180"), ("BETA", "binary_31_90")])
        current = _make_positions([("ACME", "binary_91_180"), ("BETA", "binary_31_90")])

        perf = compute_performance(
            prior,
            current,
            "2026-03-03",
            "2026-03-10",
            price_path=price_csv,
            fills_root=tmp_path / "fills",
            trades_root=tmp_path / "trades",
        )

        ann = perf["entry_annotations"]

        # ACME: filled
        assert ann["ACME"]["entry_price_source"] == "FILL"
        assert ann["ACME"]["entry_price"] == pytest.approx(10.50, abs=0.01)

        # BETA: skipped fill → falls back to close
        assert ann["BETA"]["entry_price_source"] == "CLOSE"
        assert ann["BETA"]["entry_price"] == 20.0
        assert ann["BETA"]["fill_qty"] is None

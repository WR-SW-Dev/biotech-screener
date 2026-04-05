"""Regression tests for forward harness integrity.

Tests dedup guards, immutability, date consistency, and
correct parsing of forward monitoring artifacts.

These tests document bugs found during the 2026-04-05 forward harness audit.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# IC dashboard history.jsonl dedup guard
# ---------------------------------------------------------------------------


class TestICDashboardHistoryDedup:
    """Regression: IC dashboard appended duplicate date rows (audit finding #8)."""

    def test_dedup_prevents_duplicate_dates(self, tmp_path):
        from tools.build_ic_dashboard import build_ic_dashboard

        snap_dir = tmp_path / "snapshots"
        price_csv = tmp_path / "prices.csv"
        artifacts_dir = tmp_path / "artifacts"

        # Create minimal test data: 5 snapshots + prices
        tickers = [f"T{i:03d}" for i in range(20)]
        for i, d in enumerate(["2026-01-01", "2026-01-15", "2026-02-01", "2026-02-15", "2026-03-01"]):
            sd = snap_dir / d
            sd.mkdir(parents=True, exist_ok=True)
            with open(sd / "rankings.csv", "w", newline="") as f:
                w = csv.DictWriter(
                    f,
                    fieldnames=[
                        "ticker",
                        "actionable_rank",
                        "eligible",
                        "score_rank_pct",
                        "inst_delta_z",
                        "clinical_optionality_pct_dev",
                        "clinical_score_v2_z",
                    ],
                )
                w.writeheader()
                for j, t in enumerate(tickers):
                    w.writerow(
                        {
                            "ticker": t,
                            "actionable_rank": j + 1,
                            "eligible": "1",
                            "score_rank_pct": f"{(j+1)/100}",
                            "inst_delta_z": "0.5",
                            "clinical_optionality_pct_dev": "0.3",
                            "clinical_score_v2_z": "0.1",
                        }
                    )

        # Write prices
        price_csv.parent.mkdir(parents=True, exist_ok=True)
        with open(price_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["ticker", "date", "close"])
            w.writeheader()
            for t in tickers:
                for d in [
                    "2026-01-01",
                    "2026-01-15",
                    "2026-02-01",
                    "2026-02-15",
                    "2026-03-01",
                    "2026-03-15",
                    "2026-04-01",
                ]:
                    w.writerow({"ticker": t, "date": d, "close": "10.0"})

        # Run twice for the same date
        for _ in range(3):
            build_ic_dashboard(
                "2026-03-15",
                snapshots_dir=snap_dir,
                price_csv=price_csv,
                artifacts_dir=artifacts_dir,
                lookback=5,
                horizon=5,
            )

        # Check history.jsonl has exactly 1 entry
        history = artifacts_dir / "ic_dashboard" / "history.jsonl"
        lines = [line.strip() for line in history.read_text().splitlines() if line.strip()]
        dates = [json.loads(line)["date"] for line in lines]
        assert dates.count("2026-03-15") == 1, f"Expected 1 entry for 2026-03-15, got {dates.count('2026-03-15')}"


# ---------------------------------------------------------------------------
# Calibration ledger dedup guard
# ---------------------------------------------------------------------------


class TestCalibrationLedgerDedup:
    """Regression: calibration ledger had no dedup guard (audit finding #9)."""

    def test_dedup_prevents_duplicate_prediction_date(self, tmp_path):
        # Temporarily redirect ledger
        import tools.compute_timing_hazard as th_mod
        from tools.compute_timing_hazard import append_calibration_ledger

        original_ledger = th_mod.CALIBRATION_LEDGER
        original_output_dir = th_mod.OUTPUT_DIR
        th_mod.CALIBRATION_LEDGER = tmp_path / "ledger.jsonl"
        th_mod.OUTPUT_DIR = tmp_path

        try:
            result = {
                "snapshot_date": "2026-04-03",
                "catalysts": [
                    {
                        "ticker": "AAAA",
                        "catalyst_days": 30,
                        "catalyst_event_type": "PDUFA",
                        "catalyst_family": "REGULATORY",
                        "is_hard_catalyst": True,
                        "on_time_prob": 0.85,
                        "on_time_prob_logistic": 0.80,
                        "slip_prob_30d": 0.08,
                        "slip_prob_60d_plus": 0.07,
                        "timing_confidence_bucket": "HIGH",
                        "execution_warning_flag": False,
                    },
                ],
                "probability_method": "rolling_base_rate_90d",
            }

            # Append three times
            append_calibration_ledger(result)
            append_calibration_ledger(result)
            append_calibration_ledger(result)

            lines = [line for line in (tmp_path / "ledger.jsonl").read_text().splitlines() if line.strip()]
            assert len(lines) == 1, f"Expected 1 entry, got {len(lines)} (dedup failed)"
        finally:
            th_mod.CALIBRATION_LEDGER = original_ledger
            th_mod.OUTPUT_DIR = original_output_dir


# ---------------------------------------------------------------------------
# Post-promotion monitor CSV parsing
# ---------------------------------------------------------------------------


class TestPostPromotionCSVParsing:
    """Regression: post-promotion monitor used positional CSV indexing (audit finding #1-2)."""

    def test_load_perf_csv_uses_header_names(self, tmp_path):
        from tools.post_promotion_monitor import load_perf_csv

        # Write a performance CSV with the real schema
        perf_csv = tmp_path / "performance.csv"
        with open(perf_csv, "w", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "schema_version",
                    "date",
                    "prior_date",
                    "total_pnl",
                    "pnl_pct",
                    "xbi_return_pct",
                    "excess_vs_xbi_pct",
                    "n_held",
                    "turnover",
                    "gap_risk_high_count",
                    "n_missing_price",
                    "sleeve_binary_0_30_pnl",
                    "sleeve_binary_31_90_pnl",
                    "sleeve_binary_91_180_pnl",
                    "sleeve_less_binary_pnl",
                    "ruleset_id",
                ],
            )
            w.writeheader()
            w.writerow(
                {
                    "schema_version": "live_shadow_perf.v1",
                    "date": "2026-04-01",
                    "prior_date": "2026-03-31",
                    "total_pnl": "1000",
                    "pnl_pct": "2.5",
                    "xbi_return_pct": "1.0",
                    "excess_vs_xbi_pct": "1.5",
                    "n_held": "30",
                    "turnover": "0.1",
                    "gap_risk_high_count": "0",
                    "n_missing_price": "0",
                    "sleeve_binary_0_30_pnl": "100",
                    "sleeve_binary_31_90_pnl": "200",
                    "sleeve_binary_91_180_pnl": "300",
                    "sleeve_less_binary_pnl": "400",
                    "ruleset_id": "abc123",
                }
            )

        rows = load_perf_csv(perf_csv, "2026-04-01")
        assert len(rows) == 1
        assert rows[0]["date"] == "2026-04-01"
        assert rows[0]["pnl_pct"] == 2.5
        assert rows[0]["xbi_pct"] == 1.0
        assert rows[0]["excess"] == 1.5
        assert rows[0]["n_held"] == 30
        assert rows[0]["turnover"] == 0.1

    def test_header_row_not_parsed_as_data(self, tmp_path):
        from tools.post_promotion_monitor import load_perf_csv

        perf_csv = tmp_path / "performance.csv"
        with open(perf_csv, "w", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "schema_version",
                    "date",
                    "prior_date",
                    "total_pnl",
                    "pnl_pct",
                    "xbi_return_pct",
                    "excess_vs_xbi_pct",
                    "n_held",
                    "turnover",
                    "gap_risk_high_count",
                    "n_missing_price",
                ],
            )
            w.writeheader()

        rows = load_perf_csv(perf_csv, "2000-01-01")
        assert len(rows) == 0, "Header row should not be parsed as data"


# ---------------------------------------------------------------------------
# Production monitor ranker shadow path
# ---------------------------------------------------------------------------


class TestProductionMonitorRankerPath:
    """Regression: production monitor looked in wrong dir for ranker shadow (finding #6)."""

    def test_loads_from_snapshot_dir(self, tmp_path):
        from tools.build_production_monitor import load_ranker_shadow

        snapshots_dir = tmp_path / "snapshots"
        artifacts_dir = tmp_path / "artifacts"

        # Write ranker shadow in snapshot dir (where run_screen.py puts it)
        snap = snapshots_dir / "2026-04-03"
        snap.mkdir(parents=True, exist_ok=True)
        comparison = {"overlap_count": 25, "n_pairwise": 30, "n_clinical": 30}
        (snap / "ranker_shadow_comparison.json").write_text(json.dumps(comparison))

        result = load_ranker_shadow("2026-04-03", artifacts_dir, snapshots_dir)
        assert result is not None
        assert result["overlap_count"] == 25


# ---------------------------------------------------------------------------
# Live shadow performance dedup
# ---------------------------------------------------------------------------


class TestLiveShadowPerformanceDedup:
    """Verify the existing dedup guard in append_performance works."""

    def test_no_duplicate_rows_on_rerun(self, tmp_path):
        from tools.live_shadow_portfolio import append_performance

        perf_csv = tmp_path / "performance.csv"
        perf = {
            "prior_date": "2026-04-02",
            "total_pnl": 1000,
            "pnl_pct": 2.5,
            "xbi_return_pct": 1.0,
            "excess_vs_xbi_pct": 1.5,
            "n_prior": 30,
            "turnover": 0.1,
            "gap_risk_high_count": 0,
            "n_missing_price": 0,
            "sleeve_attribution": {},
        }

        # Append twice
        append_performance("2026-04-03", perf, "abc", perf_csv=perf_csv)
        append_performance("2026-04-03", perf, "abc", perf_csv=perf_csv)

        with open(perf_csv) as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 1, f"Expected 1 row, got {len(rows)} (dedup failed)"


# ---------------------------------------------------------------------------
# Coinvest shadow history.csv dedup
# ---------------------------------------------------------------------------


class TestCoinvestShadowHistoryDedup:
    """Verify coinvest shadow history.csv dedup guard works."""

    def test_no_duplicate_history_rows(self, tmp_path):
        import tools.coinvest_shadow_tracker as cs_mod
        from tools.coinvest_shadow_tracker import append_history

        original_csv = cs_mod.HISTORY_CSV
        original_dir = cs_mod.SHADOW_DIR
        cs_mod.SHADOW_DIR = tmp_path
        cs_mod.HISTORY_CSV = tmp_path / "history.csv"

        try:
            result = {
                "as_of_date": "2026-04-03",
                "days_since_start": 0,
                "regime": "bear",
                "n_eligible": 188,
                "strategies": {},
                "xbi_ret_5d": None,
                "xbi_ret_20d": None,
            }

            append_history(result)
            append_history(result)
            append_history(result)

            with open(cs_mod.HISTORY_CSV) as f:
                rows = list(csv.DictReader(f))

            assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
        finally:
            cs_mod.HISTORY_CSV = original_csv
            cs_mod.SHADOW_DIR = original_dir

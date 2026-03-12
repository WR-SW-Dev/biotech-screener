"""Tests for sleeve filtering in scripts/research/run_alpha_experiment.py.

Covers:
- Sleeve filter reduces rows (binary/core filter out opposite sleeve)
- Sleeve "all" is identity (no rows removed)
- Binary sleeve rows have short catalyst_days (≤ 90)
- Core sleeve rows have long catalyst_days (> 90) or no event
- Matrix report structure
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_action_lists import classify_action_bucket
from tools.live_shadow_portfolio import SLEEVE_MAP

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row(
    ticker: str,
    catalyst_days: str = "90",
    catalyst_mode: str = "specific_days",
    eligible: str = "1",
    **overrides: str,
) -> Dict[str, str]:
    """Create a minimal rankings row for sleeve testing."""
    row = {
        "ticker": ticker,
        "eligible": eligible,
        "alpha_cohort_pct": "0.5",
        "composite_rank": "10",
        "de_beta_xbi_60d": "1.0",
        "de_drawdown": "-0.10",
        "de_rsi_14d": "50.0",
        "de_vol_60d": "0.80",
        "de_drawdown_rel_xbi": "-0.10",
        "market_cap_bucket": "small",
        "archetype": "drug_developer",
        "tier_dev": "B",
        "actionable_rank": "1",
        "clinical_optionality_pct_dev": "0.5",
        "catalyst_days": catalyst_days,
        "catalyst_mode": catalyst_mode,
        "catalyst_event_type": "",
        "catalyst_source": "",
        "mom_state": "neutral",
        "sponsor_tier1_count": "0",
        "coinvest_score_z": "0",
        "clinical_score_z_tier": "0",
        "inst_delta_z": "0",
        "stage_bucket": "mid",
        "missingness_penalty": "0",
        "missing_components": "",
        "alpha_cohort_raw": "0.5",
        "commercial_quality_pct": "",
    }
    row.update(overrides)
    return row


def _make_mixed_rows() -> List[Dict[str, str]]:
    """Create rows spanning both binary and core sleeves."""
    rows = []
    # Binary: 0-30 days → binary_0_30 → binary sleeve
    for i in range(5):
        rows.append(
            _make_row(
                ticker=f"BIN0_{i}",
                catalyst_days=str(5 + i * 5),
                catalyst_mode="specific_days",
            )
        )
    # Binary: 31-90 days → binary_31_90 → binary sleeve
    for i in range(5):
        rows.append(
            _make_row(
                ticker=f"BIN1_{i}",
                catalyst_days=str(40 + i * 10),
                catalyst_mode="specific_days",
            )
        )
    # Core: 91-180 days → binary_91_180 → core sleeve
    for i in range(5):
        rows.append(
            _make_row(
                ticker=f"CORE0_{i}",
                catalyst_days=str(100 + i * 15),
                catalyst_mode="specific_days",
            )
        )
    # Core: no catalyst → less_binary → core sleeve
    for i in range(5):
        rows.append(
            _make_row(
                ticker=f"CORE1_{i}",
                catalyst_days="",
                catalyst_mode="",
            )
        )
    return rows


def _filter_by_sleeve(rows: List[Dict[str, str]], sleeve: str) -> List[Dict[str, str]]:
    """Apply the same sleeve filter logic as run_experiment."""
    if sleeve == "all":
        return rows
    return [r for r in rows if SLEEVE_MAP.get(classify_action_bucket(r), "core") == sleeve]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSleeveFilterReducesRows:
    def test_binary_removes_core_rows(self):
        rows = _make_mixed_rows()
        filtered = _filter_by_sleeve(rows, "binary")
        assert len(filtered) < len(rows)
        # Only binary tickers remain
        tickers = {r["ticker"] for r in filtered}
        assert all(t.startswith("BIN") for t in tickers)

    def test_core_removes_binary_rows(self):
        rows = _make_mixed_rows()
        filtered = _filter_by_sleeve(rows, "core")
        assert len(filtered) < len(rows)
        # Only core tickers remain
        tickers = {r["ticker"] for r in filtered}
        assert all(t.startswith("CORE") for t in tickers)


class TestSleeveAllIsIdentity:
    def test_all_returns_same_count(self):
        rows = _make_mixed_rows()
        filtered = _filter_by_sleeve(rows, "all")
        assert len(filtered) == len(rows)

    def test_all_returns_same_tickers(self):
        rows = _make_mixed_rows()
        filtered = _filter_by_sleeve(rows, "all")
        orig_tickers = [r["ticker"] for r in rows]
        filt_tickers = [r["ticker"] for r in filtered]
        assert orig_tickers == filt_tickers


class TestSleeveContent:
    def test_binary_has_short_catalyst_days(self):
        rows = _make_mixed_rows()
        filtered = _filter_by_sleeve(rows, "binary")
        for r in filtered:
            days_str = r.get("catalyst_days", "").strip()
            assert days_str, f"{r['ticker']} has no catalyst_days"
            days = int(days_str)
            assert days <= 90, f"{r['ticker']} has catalyst_days={days} > 90"

    def test_core_has_long_or_missing_catalyst(self):
        rows = _make_mixed_rows()
        filtered = _filter_by_sleeve(rows, "core")
        for r in filtered:
            days_str = r.get("catalyst_days", "").strip()
            if days_str:
                days = int(days_str)
                assert days > 90, f"{r['ticker']} has catalyst_days={days} ≤ 90"
            # else: no catalyst_days → less_binary → core — valid


class TestSleevePartition:
    def test_binary_plus_core_equals_all(self):
        """Binary and core are a complete partition of all rows."""
        rows = _make_mixed_rows()
        binary = _filter_by_sleeve(rows, "binary")
        core = _filter_by_sleeve(rows, "core")
        assert len(binary) + len(core) == len(rows)

    def test_no_overlap(self):
        rows = _make_mixed_rows()
        binary_tickers = {r["ticker"] for r in _filter_by_sleeve(rows, "binary")}
        core_tickers = {r["ticker"] for r in _filter_by_sleeve(rows, "core")}
        assert not (binary_tickers & core_tickers)


class TestMatrixReportStructure:
    def test_report_has_expected_sections(self):
        """Matrix report output has expected section headers."""
        # Build minimal results
        from scripts.research.run_alpha_experiment import ExperimentResult
        from scripts.research.run_sleeve_neutral_matrix import generate_matrix_report

        def _make_result(name: str, horizons: List[int]) -> ExperimentResult:
            r = ExperimentResult(
                name=name,
                mode="baseline",
                horizons=horizons,
                top_k=20,
                exposure_names=["beta", "vol"],
                ruleset_id="test",
            )
            r.n_dates = 3
            r.n_skipped = 0
            r.mean_ic = {h: 0.05 for h in horizons}
            r.mean_gross = {h: 0.01 for h in horizons}
            r.mean_exposure_topk = {"beta": 1.0, "vol": 0.5}
            return r

        results = []
        for sleeve in ("all", "binary", "core"):
            for univ in ("current", "price_available"):
                h = [5, 20, 63] if sleeve == "all" else [5, 20, 84] if sleeve == "binary" else [84, 126]
                bl = _make_result(f"bl_{sleeve}_{univ}", h)
                nl = _make_result(f"nl_{sleeve}_{univ}", h)
                nl.mode = "neutralized"
                results.append(
                    {
                        "sleeve": sleeve,
                        "universe_mode": univ,
                        "horizons": h,
                        "baseline": bl,
                        "neutralized": nl,
                        "overlap": {"mean_jaccard": 0.80, "min_jaccard": 0.60, "n_dates": 3},
                    }
                )

        report = generate_matrix_report(results, "test_matrix", ["beta", "vol"], 30)

        assert "## 1. Summary" in report
        assert "## 2. IC Comparison" in report
        assert "## 3. Top-K Churn Impact" in report
        assert "## 4. Exposure Reduction" in report
        assert "## 5. Net Returns After Costs" in report
        assert "## 6. Go/No-Go Recommendation" in report
        assert "**Combined:" in report

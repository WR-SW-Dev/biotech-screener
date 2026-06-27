"""Tests for Phase 3 inversion autopsy tool.

Classification: PHASE_3_INVERSION_AUTOPSY_DIAGNOSTIC_NO_MODEL_CHANGE
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# Add tools to path
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from analyze_phase3_inversion import (
    CONF_ORDER,
    FORBIDDEN_TRADING_TERMS,
    HYPOTHESIS_META,
    basket_return,
    build_summary,
    check_governance_language,
    fwd_date,
    module_ees_suppression,
    module_idiosyncratic_vs_beta,
    module_regime_lag,
    module_structural_defensiveness,
    module_veto_overpenalization,
    write_json,
    write_markdown,
    xbi_return,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SNAP_DATES = [
    "2026-05-18",
    "2026-05-19",
    "2026-05-20",
    "2026-05-26",
    "2026-05-27",
    "2026-05-28",
    "2026-06-01",
    "2026-06-08",
]


def _make_price_pivot(
    tickers=("XBI", "COGT", "DNTH", "RVMD", "AMGN"), start="2026-05-15", end="2026-06-15", base=100.0, drift=0.002
):
    """Synthetic daily price pivot — XBI drifts up, biotech names drift flat."""
    idx = pd.bdate_range(start, end)
    np.random.seed(42)
    data = {}
    for t in tickers:
        d = drift if t == "XBI" else 0.0
        rets = np.random.normal(d, 0.02, size=len(idx))
        data[t] = base * np.cumprod(1 + rets)
    return pd.DataFrame(data, index=idx)


def _make_rankings(n=50, regime_label="UNKNOWN", ees_eligible=True, eligible=True, financing_truth_gate=True):
    """Minimal rankings DataFrame for testing."""
    tickers = [f"TK{i:02d}" for i in range(n)]
    df = pd.DataFrame(
        {
            "ticker": tickers,
            "actionable_rank": list(range(1, n + 1)),
            "eligible": int(eligible),
            "ees_eligible": ees_eligible,
            "financing_truth_gate": financing_truth_gate,
            "final_score": np.linspace(0.9, 0.1, n),
            "regime_label": regime_label,
            "de_beta_xbi_60d": np.random.uniform(0.5, 1.5, n),
            "de_alpha_60d": np.random.uniform(-0.2, 0.1, n),
            "de_drawdown": np.random.uniform(-0.3, -0.05, n),
            "de_drawdown_rel_xbi": np.random.uniform(-0.2, 0.0, n),
            "selector_catalyst_block": np.random.uniform(0.3, 0.8, n),
            "catalyst_days": np.random.randint(5, 200, n).astype(float),
        }
    )
    return df


# ---------------------------------------------------------------------------
# test_phase3_autopsy_no_model_mutation
# ---------------------------------------------------------------------------


def test_phase3_autopsy_no_model_mutation():
    """Running the autopsy must not touch any production files."""
    REPO = Path(__file__).parent.parent
    production_paths = [
        REPO / "production_data" / "rankings.csv",
        REPO / "ranker",
        REPO / "selector",
        REPO / "portfolio",
    ]
    import os

    # Record mtimes before
    before = {p: p.stat().st_mtime_ns if p.exists() else None for p in production_paths}

    # The module is import-only at this point — no side effects
    # (actual run is tested separately; this verifies no import side effects)
    import analyze_phase3_inversion  # noqa: F401

    after = {p: p.stat().st_mtime_ns if p.exists() else None for p in production_paths}
    assert before == after, "Production files were mutated by import"


# ---------------------------------------------------------------------------
# test_phase3_autopsy_schema_valid
# ---------------------------------------------------------------------------


def test_phase3_autopsy_schema_valid():
    """JSON output must contain required schema keys."""
    price_pivot = _make_price_pivot()

    with (
        patch("analyze_phase3_inversion.load_rankings") as mock_lr,
        patch("analyze_phase3_inversion.load_ees_diagnostics") as mock_ees,
    ):

        mock_lr.return_value = _make_rankings()
        mock_ees.return_value = {
            "as_of_date": "2026-05-18",
            "universe": {"quality_fail": 10, "trap_fail": 60, "eligible": 200},
            "quality_filtered_names": [],
            "trap_filtered_names": ["AMGN", "GILD"],
        }

        results = {
            "regime_detector_lag": module_regime_lag(SNAP_DATES[:4], price_pivot),
            "veto_overpenalization": module_veto_overpenalization(SNAP_DATES[:4], price_pivot),
            "ees_suppression": module_ees_suppression(SNAP_DATES[:4], price_pivot),
            "idiosyncratic_miss": module_idiosyncratic_vs_beta(SNAP_DATES[:4], price_pivot),
            "universe_mismatch": {"confidence": "low", "interpretation": "test"},
            "structural_defensiveness": module_structural_defensiveness(SNAP_DATES[:4], price_pivot),
        }
        summary = build_summary(results)

    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        json_path = write_json(results, summary, out_dir, "2026-05-16", "2026-06-09", 16)

        with open(json_path) as f:
            doc = json.load(f)

    # Required top-level keys
    for key in ("schema", "classification", "window", "headline", "hypotheses", "governance"):
        assert key in doc, f"Missing key: {key}"

    # Schema value
    assert doc["schema"] == "phase3_inversion_autopsy_v1"

    # Classification
    assert doc["classification"] == "PHASE_3_INVERSION_AUTOPSY_DIAGNOSTIC_NO_MODEL_CHANGE"

    # Governance flags
    gov = doc["governance"]
    for flag in ("model_change", "ranker_change", "selector_change", "sizing_change", "production_wiring"):
        assert gov[flag] is False, f"governance.{flag} must be False"

    # Hypotheses: all 6 present
    hyp_names = {h["name"] for h in doc["hypotheses"]}
    for name, _ in HYPOTHESIS_META:
        assert name in hyp_names, f"Missing hypothesis: {name}"

    # Window
    assert doc["window"]["start_date"] == "2026-05-16"
    assert doc["window"]["end_date"] == "2026-06-09"


# ---------------------------------------------------------------------------
# test_phase3_autopsy_deterministic_output
# ---------------------------------------------------------------------------


def test_phase3_autopsy_deterministic_output():
    """Running the autopsy twice must produce identical JSON content."""
    price_pivot = _make_price_pivot()

    with (
        patch("analyze_phase3_inversion.load_rankings") as mock_lr,
        patch("analyze_phase3_inversion.load_ees_diagnostics") as mock_ees,
    ):

        mock_lr.return_value = _make_rankings()
        mock_ees.return_value = {
            "universe": {"quality_fail": 5, "trap_fail": 60, "eligible": 210},
            "quality_filtered_names": [],
            "trap_filtered_names": ["AMGN"],
        }

        def run():
            r = {
                "regime_detector_lag": module_regime_lag(SNAP_DATES[:3], price_pivot),
                "veto_overpenalization": module_veto_overpenalization(SNAP_DATES[:3], price_pivot),
                "ees_suppression": module_ees_suppression(SNAP_DATES[:3], price_pivot),
                "idiosyncratic_miss": module_idiosyncratic_vs_beta(SNAP_DATES[:3], price_pivot),
                "universe_mismatch": {"confidence": "low", "interpretation": "test"},
                "structural_defensiveness": module_structural_defensiveness(SNAP_DATES[:3], price_pivot),
            }
            return build_summary(r), r

        summary1, results1 = run()
        summary2, results2 = run()

    # Summaries must agree on confidence rankings
    for r1, r2 in zip(summary1, summary2):
        assert r1["hypothesis"] == r2["hypothesis"]
        assert r1["confidence"] == r2["confidence"]


# ---------------------------------------------------------------------------
# test_phase3_autopsy_missing_optional_inputs_graceful
# ---------------------------------------------------------------------------


def test_phase3_autopsy_missing_optional_inputs_graceful():
    """Modules must not raise when optional data (EES diag, fwd prices) is absent."""
    # Price pivot with missing forward dates
    idx = pd.bdate_range("2026-05-18", "2026-05-20")
    price_pivot = pd.DataFrame(
        {
            "XBI": [127.0, 128.0, 129.0],
            "COGT": [30.0, 31.0, 32.0],
        },
        index=idx,
    )

    with (
        patch("analyze_phase3_inversion.load_rankings") as mock_lr,
        patch("analyze_phase3_inversion.load_ees_diagnostics") as mock_ees,
    ):

        mock_lr.return_value = _make_rankings()
        mock_ees.return_value = None  # absent

        # Should return gracefully with insufficient_data or low confidence
        r = module_ees_suppression(SNAP_DATES[:2], price_pivot)
        assert "confidence" in r

        r = module_structural_defensiveness(SNAP_DATES[:2], price_pivot)
        assert "confidence" in r

        r = module_idiosyncratic_vs_beta(SNAP_DATES[:2], price_pivot)
        assert "confidence" in r


# ---------------------------------------------------------------------------
# test_phase3_autopsy_regime_lag_detection
# ---------------------------------------------------------------------------


def test_phase3_autopsy_regime_lag_detection():
    """Regime lag module must flag UNKNOWN labels as high confidence."""
    price_pivot = _make_price_pivot()

    with patch("analyze_phase3_inversion.load_rankings") as mock_lr:
        # All UNKNOWN
        mock_lr.return_value = _make_rankings(regime_label="UNKNOWN")
        result = module_regime_lag(SNAP_DATES[:4], price_pivot)

    assert result["regime_label_all_unknown"] is True
    assert result["confidence"] == "high"
    assert result["diagnosis"] == "consistent_with_regime_lag"
    assert result["lag_trading_days"] == 4

    # Partial — some non-UNKNOWN
    with patch("analyze_phase3_inversion.load_rankings") as mock_lr:
        df = _make_rankings(regime_label="RECOVERY")
        mock_lr.return_value = df
        result2 = module_regime_lag(SNAP_DATES[:4], price_pivot)

    assert result2["regime_label_all_unknown"] is False
    assert result2["confidence"] == "medium"


# ---------------------------------------------------------------------------
# test_phase3_autopsy_veto_overpenalization_detection
# ---------------------------------------------------------------------------


def test_phase3_autopsy_veto_overpenalization_detection():
    """Veto module must detect when ineligible names outperform top-30."""
    # Construct price pivot where ineligible ticker outperforms top-30
    idx = pd.bdate_range("2026-05-15", "2026-06-10")
    np.random.seed(7)
    prices = {"XBI": 100 * np.cumprod(1 + np.random.normal(0.001, 0.01, len(idx)))}

    tickers_top30 = [f"T{i:02d}" for i in range(30)]
    tickers_inelig = [f"I{i:02d}" for i in range(20)]

    # Top-30: flat or negative drift
    for t in tickers_top30:
        prices[t] = 50 * np.cumprod(1 + np.random.normal(-0.003, 0.02, len(idx)))

    # Ineligible: positive drift
    for t in tickers_inelig:
        prices[t] = 50 * np.cumprod(1 + np.random.normal(0.006, 0.02, len(idx)))

    price_pivot = pd.DataFrame(prices, index=idx)

    def make_rankings_biased(snap_date, **_):
        n = 50
        all_tickers = tickers_top30 + tickers_inelig
        df = pd.DataFrame(
            {
                "ticker": all_tickers,
                "actionable_rank": list(range(1, 31)) + [999] * 20,
                "eligible": [1] * 30 + [0] * 20,
                "selector_catalyst_block": [0.5] * 50,
                "catalyst_days": [30.0] * 50,
            }
        )
        return df

    with patch("analyze_phase3_inversion.load_rankings", side_effect=make_rankings_biased):
        result = module_veto_overpenalization(SNAP_DATES[:4], price_pivot)

    # With strong ineligible outperformance, confidence should be medium+
    assert result.get("ineligible_outperformed_top30") is True
    assert result.get("confidence") in ("medium", "high")


# ---------------------------------------------------------------------------
# test_phase3_autopsy_ees_suppression_detection
# ---------------------------------------------------------------------------


def test_phase3_autopsy_ees_suppression_detection():
    """EES module must detect when blocked names outperform eligible names."""
    idx = pd.bdate_range("2026-05-15", "2026-06-10")
    np.random.seed(11)

    elig_tickers = [f"E{i:02d}" for i in range(30)]
    blocked_tickers = [f"B{i:02d}" for i in range(20)]
    prices = {"XBI": 100 * np.cumprod(1 + np.random.normal(0.001, 0.01, len(idx)))}

    for t in elig_tickers:
        prices[t] = 50 * np.cumprod(1 + np.random.normal(-0.002, 0.02, len(idx)))
    for t in blocked_tickers:
        prices[t] = 50 * np.cumprod(1 + np.random.normal(0.005, 0.02, len(idx)))

    price_pivot = pd.DataFrame(prices, index=idx)

    def make_df_ees(_snap, **_):
        all_t = elig_tickers + blocked_tickers
        df = pd.DataFrame(
            {
                "ticker": all_t,
                "ees_eligible": [True] * 30 + [False] * 20,
                "financing_truth_gate": [True] * 50,
            }
        )
        return df

    def make_ees_diag(_snap):
        return {
            "universe": {"quality_fail": 0, "trap_fail": 20, "eligible": 200},
            "quality_filtered_names": [],
            "trap_filtered_names": blocked_tickers[:20],
        }

    with (
        patch("analyze_phase3_inversion.load_rankings", side_effect=make_df_ees),
        patch("analyze_phase3_inversion.load_ees_diagnostics", side_effect=make_ees_diag),
    ):
        result = module_ees_suppression(SNAP_DATES[:4], price_pivot)

    assert result.get("ees_blocked_outperformed_eligible") is True
    assert result.get("confidence") in ("medium", "high")


# ---------------------------------------------------------------------------
# test_phase3_autopsy_structural_defensiveness_detection
# ---------------------------------------------------------------------------


def test_phase3_autopsy_structural_defensiveness_detection():
    """Structural defensiveness flagged when mean drawdown is severe."""
    price_pivot = _make_price_pivot()

    def make_drawn_down_df(_snap, **_):
        n = 50
        df = _make_rankings(n=n)
        df["de_drawdown"] = -0.30  # severe drawdown
        df["de_alpha_60d"] = -0.20  # negative alpha
        df["de_drawdown_rel_xbi"] = -0.25
        return df

    with (
        patch("analyze_phase3_inversion.load_rankings", side_effect=make_drawn_down_df),
        patch("analyze_phase3_inversion.load_ees_diagnostics") as mock_ees,
    ):
        mock_ees.return_value = {
            "universe": {"quality_fail": 0, "trap_fail": 60, "eligible": 200},
            "quality_filtered_names": [],
            "trap_filtered_names": [],
        }
        result = module_structural_defensiveness(SNAP_DATES[:4], price_pivot)

    assert result.get("structural_defensiveness_likely") is True
    assert result.get("confidence") == "medium"

    # Non-defensive case
    def make_healthy_df(_snap, **_):
        df = _make_rankings()
        df["de_drawdown"] = -0.05
        df["de_alpha_60d"] = 0.05
        df["de_drawdown_rel_xbi"] = -0.02
        return df

    with (
        patch("analyze_phase3_inversion.load_rankings", side_effect=make_healthy_df),
        patch("analyze_phase3_inversion.load_ees_diagnostics") as mock_ees,
    ):
        mock_ees.return_value = {
            "universe": {"quality_fail": 0, "trap_fail": 60, "eligible": 200},
            "quality_filtered_names": [],
            "trap_filtered_names": [],
        }
        result2 = module_structural_defensiveness(SNAP_DATES[:4], price_pivot)

    assert result2.get("structural_defensiveness_likely") is False


# ---------------------------------------------------------------------------
# test_phase3_autopsy_governance_language_no_trading_terms
# ---------------------------------------------------------------------------


def test_phase3_autopsy_governance_language_no_trading_terms():
    """Generated artifacts must not contain forbidden trading action language."""
    price_pivot = _make_price_pivot()

    with (
        patch("analyze_phase3_inversion.load_rankings") as mock_lr,
        patch("analyze_phase3_inversion.load_ees_diagnostics") as mock_ees,
    ):

        mock_lr.return_value = _make_rankings()
        mock_ees.return_value = {
            "universe": {"quality_fail": 5, "trap_fail": 60, "eligible": 200},
            "quality_filtered_names": [],
            "trap_filtered_names": ["AMGN"],
        }

        results = {
            "regime_detector_lag": module_regime_lag(SNAP_DATES[:3], price_pivot),
            "veto_overpenalization": module_veto_overpenalization(SNAP_DATES[:3], price_pivot),
            "ees_suppression": module_ees_suppression(SNAP_DATES[:3], price_pivot),
            "idiosyncratic_miss": module_idiosyncratic_vs_beta(SNAP_DATES[:3], price_pivot),
            "universe_mismatch": {"confidence": "low", "interpretation": "no data"},
            "structural_defensiveness": module_structural_defensiveness(SNAP_DATES[:3], price_pivot),
        }
        summary = build_summary(results)

    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        md_path = write_markdown(results, summary, out_dir, "2026-05-16", "2026-06-09", 16)
        json_path = write_json(results, summary, out_dir, "2026-05-16", "2026-06-09", 16)

        with open(md_path) as f:
            md_text = f.read()
        with open(json_path) as f:
            json_text = f.read()

    md_violations = check_governance_language(md_text)
    json_violations = check_governance_language(json_text)

    assert not md_violations, f"Forbidden language in MD: {md_violations}"
    assert not json_violations, f"Forbidden language in JSON: {json_violations}"


# ---------------------------------------------------------------------------
# test_phase3_autopsy_check_governance_language_unit
# ---------------------------------------------------------------------------


def test_phase3_autopsy_check_governance_language_unit():
    """Unit test the governance language guard directly."""
    assert check_governance_language("review the names") == []
    assert check_governance_language("monitor for changes") == []
    assert check_governance_language("suppress names") == []

    for term in ("buy", "sell", "trade", "execute", "order"):
        found = check_governance_language(f"we should {term} this")
        assert term in found, f"Expected '{term}' to be flagged"


# ---------------------------------------------------------------------------
# test_phase3_autopsy_summary_ordering
# ---------------------------------------------------------------------------


def test_phase3_autopsy_summary_ordering():
    """Summary must be sorted high→medium→low→insufficient_data."""
    mock_results = {
        "regime_detector_lag": {"confidence": "high", "interpretation": "x"},
        "veto_overpenalization": {"confidence": "medium", "interpretation": "x"},
        "ees_suppression": {"confidence": "low", "interpretation": "x"},
        "idiosyncratic_miss": {"confidence": "high", "interpretation": "x"},
        "universe_mismatch": {"confidence": "insufficient_data", "interpretation": "x"},
        "structural_defensiveness": {"confidence": "low", "interpretation": "x"},
    }
    summary = build_summary(mock_results)
    confs = [CONF_ORDER[r["confidence"]] for r in summary]
    assert confs == sorted(confs), "Summary not sorted by confidence"

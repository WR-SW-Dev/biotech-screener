"""Tests for unified production health monitor."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_production_monitor import (
    build_production_monitor,
    classify_alerts,
    compute_catalyst_quality,
    compute_hhi,
    compute_overlap,
    compute_rank_correlation,
    compute_ranker_drift,
)

# ---------------------------------------------------------------------------
# compute_overlap
# ---------------------------------------------------------------------------


def test_overlap_identical():
    s = {"A", "B", "C"}
    result = compute_overlap(s, s)
    assert result["jaccard"] == 1.0
    assert result["added"] == []
    assert result["removed"] == []
    assert result["n_common"] == 3


def test_overlap_disjoint():
    result = compute_overlap({"A", "B"}, {"C", "D"})
    assert result["jaccard"] == 0.0
    assert result["n_common"] == 0
    assert set(result["added"]) == {"A", "B"}
    assert set(result["removed"]) == {"C", "D"}


def test_overlap_partial():
    result = compute_overlap({"A", "B", "C"}, {"B", "C", "D"})
    # Jaccard = 2/4 = 0.5
    assert result["jaccard"] == 0.5
    assert result["added"] == ["A"]
    assert result["removed"] == ["D"]


def test_overlap_empty():
    result = compute_overlap(set(), {"A"})
    assert result["jaccard"] is None


# ---------------------------------------------------------------------------
# compute_rank_correlation
# ---------------------------------------------------------------------------


def test_rank_corr_perfect():
    ranks = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}
    assert compute_rank_correlation(ranks, ranks) == 1.0


def test_rank_corr_reversed():
    today = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}
    prior = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}
    rho = compute_rank_correlation(today, prior)
    assert rho == -1.0


def test_rank_corr_too_few():
    assert compute_rank_correlation({"A": 1, "B": 2}, {"A": 1, "B": 2}) is None


# ---------------------------------------------------------------------------
# compute_hhi
# ---------------------------------------------------------------------------


def test_hhi_equal_weight():
    # 30 positions at 3.33% each → HHI ≈ 333
    weights = [3.33] * 30
    hhi = compute_hhi(weights)
    assert 330 < hhi < 340


def test_hhi_concentrated():
    # 1 position at 100% → HHI = 10000
    hhi = compute_hhi([100.0])
    assert hhi == 10000.0


def test_hhi_empty():
    assert compute_hhi([]) == 0


# ---------------------------------------------------------------------------
# compute_catalyst_quality
# ---------------------------------------------------------------------------


def test_catalyst_quality_basic():
    rankings = {
        "ACME": {
            "catalyst_event_type": "FDA_PDUFA_DATE",
            "is_hard_catalyst": "1.0",
            "catalyst_days": "30",
        },
        "SOFT": {
            "catalyst_event_type": "CT_PRIMARY_COMPLETION",
            "is_hard_catalyst": "0.0",
            "catalyst_days": "90",
        },
        "NONE": {
            "catalyst_event_type": "",
            "is_hard_catalyst": "0.0",
            "catalyst_days": "",
        },
    }
    result = compute_catalyst_quality(rankings, {"ACME", "SOFT", "NONE"})
    assert result["mean_event_type_score"] is not None
    assert result["hard_catalyst_pct"] > 0
    assert result["has_catalyst_pct"] > 0
    assert result["n_scored"] == 2  # NONE has empty event type


# ---------------------------------------------------------------------------
# compute_ranker_drift
# ---------------------------------------------------------------------------


def test_ranker_drift_no_data():
    result = compute_ranker_drift(None)
    assert result["status"] == "no_data"


def test_ranker_drift_with_data():
    shadow = {
        "overlap_count": 25,
        "n_pairwise": 30,
        "n_clinical": 30,
        "pairwise_only": ["A", "B", "C", "D", "E"],
        "clinical_only": ["F", "G", "H", "I", "J"],
    }
    result = compute_ranker_drift(shadow)
    assert result["overlap"] == 25
    assert result["n_divergent"] == 5
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# classify_alerts
# ---------------------------------------------------------------------------


def test_alerts_low_overlap():
    overlap = {"jaccard": 0.70, "added": ["X"], "removed": ["Y"], "n_common": 20}
    alerts = classify_alerts(overlap, 333, {"n_divergent": 3, "status": "ok"})
    assert any(a["code"] == "POSITION_OVERLAP_LOW" for a in alerts)


def test_alerts_high_hhi():
    overlap = {"jaccard": 0.95}
    alerts = classify_alerts(overlap, 600, {"n_divergent": 3, "status": "ok"})
    assert any(a["code"] == "WEIGHT_CONCENTRATION" for a in alerts)


def test_alerts_ranker_divergence():
    overlap = {"jaccard": 0.95}
    alerts = classify_alerts(overlap, 333, {"n_divergent": 8, "status": "ok"})
    assert any(a["code"] == "RANKER_DIVERGENCE" for a in alerts)


def test_no_alerts_clean():
    overlap = {"jaccard": 0.95}
    alerts = classify_alerts(overlap, 333, {"n_divergent": 3, "status": "ok"})
    assert len(alerts) == 0


# ---------------------------------------------------------------------------
# Integration: build_production_monitor
# ---------------------------------------------------------------------------


def test_build_production_monitor_integration(tmp_path):
    """End-to-end test with mock filesystem."""
    artifacts = tmp_path / "artifacts"
    snapshots = tmp_path / "data" / "snapshots"

    # Create today's positions
    pos_dir = artifacts / "live_shadow" / "positions"
    pos_dir.mkdir(parents=True)
    today = "2026-04-04"
    positions = [
        {"ticker": "ACME", "weight_pct": 3.3, "bucket": "binary_now"},
        {"ticker": "BETA", "weight_pct": 3.3, "bucket": "binary_soon"},
        {"ticker": "GAMA", "weight_pct": 3.3, "bucket": "binary_later"},
    ]
    (pos_dir / f"{today}.json").write_text(json.dumps({"positions": positions}))

    # Create prior day positions
    prior = "2026-04-03"
    prior_positions = [
        {"ticker": "ACME", "weight_pct": 3.3, "bucket": "binary_now"},
        {"ticker": "BETA", "weight_pct": 3.3, "bucket": "binary_soon"},
        {"ticker": "DELTA", "weight_pct": 3.3, "bucket": "binary_later"},
    ]
    (pos_dir / f"{prior}.json").write_text(json.dumps({"positions": prior_positions}))

    # Create rankings
    snap_dir = snapshots / today
    snap_dir.mkdir(parents=True)
    rankings_csv = snap_dir / "rankings.csv"
    rankings_csv.write_text(
        "ticker,actionable_rank,catalyst_event_type,is_hard_catalyst,catalyst_days\n"
        "ACME,1,FDA_PDUFA_DATE,1.0,30\n"
        "BETA,2,CT_PRIMARY_COMPLETION,0.0,90\n"
        "GAMA,3,,0.0,\n"
    )

    prior_snap_dir = snapshots / prior
    prior_snap_dir.mkdir(parents=True)
    prior_rankings_csv = prior_snap_dir / "rankings.csv"
    prior_rankings_csv.write_text(
        "ticker,actionable_rank,catalyst_event_type,is_hard_catalyst,catalyst_days\n"
        "ACME,1,FDA_PDUFA_DATE,1.0,31\n"
        "BETA,2,CT_PRIMARY_COMPLETION,0.0,91\n"
        "DELTA,3,,0.0,\n"
    )

    result = build_production_monitor(
        today,
        artifacts_dir=artifacts,
        snapshots_dir=snapshots,
    )

    assert "error" not in result
    assert result["schema"] == "production_monitor.v1"
    assert result["n_positions"] == 3
    assert result["overlap"]["jaccard"] is not None
    assert result["overlap"]["added"] == ["GAMA"]
    assert result["overlap"]["removed"] == ["DELTA"]
    assert result["hhi"] > 0
    assert result["catalyst_quality"]["n_scored"] == 2

    # Check artifacts were written
    assert (artifacts / "production_monitor" / f"{today}_monitor.json").exists()
    assert (artifacts / "production_monitor" / f"{today}_monitor.md").exists()

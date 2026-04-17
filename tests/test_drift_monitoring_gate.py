"""Tests for drift monitoring gate in run_daily_production.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from run_daily_production import (
    DriftThresholds,
    _compute_drift_metrics,
    _find_prior_snapshot,
    check_drift_monitoring,
)

# Thresholds with FAIL disabled — for tests that only check WARN behavior
WARN_ONLY_THRESHOLDS = DriftThresholds(
    fail_top20_overlap_pct=-1.0,
    fail_top60_overlap_pct=-1.0,
    fail_rank_spearman_rho=-2.0,
    fail_mean_abs_rank_delta_top60=9999.0,
    fail_tier_migration_count=9999,
    fail_eligibility_change_count=9999,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HEADER = [
    "ticker",
    "actionable_rank",
    "tier_dev",
    "eligible",
    "composite_rank",
    "composite_score",
]


def _write_rankings(path: Path, rows: list[dict]) -> None:
    """Write a minimal rankings.csv with the given rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)


def _make_tickers(n: int, start: int = 1) -> list[dict]:
    """Generate n ticker rows ranked 1..n."""
    return [
        {
            "ticker": f"TICK{i}",
            "actionable_rank": str(i),
            "tier_dev": "A" if i <= n // 4 else "B",
            "eligible": "True",
            "composite_rank": str(i),
            "composite_score": str(round(1.0 - i / (n + 1), 4)),
        }
        for i in range(start, start + n)
    ]


# ---------------------------------------------------------------------------
# DriftThresholds dataclass tests
# ---------------------------------------------------------------------------


class TestDriftThresholds:
    def test_thresholds_id_stable(self):
        """Default thresholds always produce the same hash."""
        t1 = DriftThresholds()
        t2 = DriftThresholds()
        assert t1.thresholds_id == t2.thresholds_id
        assert len(t1.thresholds_id) == 8

    def test_thresholds_id_changes_with_values(self):
        t1 = DriftThresholds()
        t2 = DriftThresholds(warn_top20_overlap_pct=50.0)
        assert t1.thresholds_id != t2.thresholds_id

    def test_thresholds_from_json(self, tmp_path):
        """Load + round-trip preserves values."""
        original = DriftThresholds(
            warn_top20_overlap_pct=65.0,
            warn_tier_migration_count=5,
        )
        path = tmp_path / "thresholds.json"
        with open(path, "w") as f:
            json.dump(original.to_json(), f)

        loaded = DriftThresholds.from_json(path)
        assert loaded.warn_top20_overlap_pct == 65.0
        assert loaded.warn_tier_migration_count == 5
        assert loaded.thresholds_id == original.thresholds_id

    def test_to_json_includes_id(self):
        t = DriftThresholds()
        d = t.to_json()
        assert "thresholds_id" in d
        assert d["warn_top20_overlap_pct"] == 70.0

    def test_from_json_ignores_extra_keys(self, tmp_path):
        path = tmp_path / "thresholds.json"
        with open(path, "w") as f:
            json.dump({"warn_top20_overlap_pct": 60.0, "unknown_field": 999}, f)
        loaded = DriftThresholds.from_json(path)
        assert loaded.warn_top20_overlap_pct == 60.0


# ---------------------------------------------------------------------------
# _find_prior_snapshot tests
# ---------------------------------------------------------------------------


class TestFindPriorSnapshot:
    def test_finds_correct_prior(self, tmp_path):
        """Discovers the most recent prior date with valid rankings.csv."""
        for d in ["2026-02-17", "2026-02-18", "2026-02-19"]:
            _write_rankings(tmp_path / d / "rankings.csv", _make_tickers(10))

        result = _find_prior_snapshot(tmp_path, "2026-02-19")
        assert result is not None
        assert result.name == "2026-02-18"

    def test_skips_dirs_without_tier_dev(self, tmp_path):
        """Skips snapshots with rankings.csv lacking tier_dev column."""
        # Good prior
        _write_rankings(tmp_path / "2026-02-17" / "rankings.csv", _make_tickers(10))

        # Bad prior — no tier_dev column
        bad_dir = tmp_path / "2026-02-18"
        bad_dir.mkdir(parents=True)
        with open(bad_dir / "rankings.csv", "w") as f:
            f.write("ticker,actionable_rank\n")
            f.write("TICK1,1\n")

        # Current
        _write_rankings(tmp_path / "2026-02-19" / "rankings.csv", _make_tickers(10))

        result = _find_prior_snapshot(tmp_path, "2026-02-19")
        assert result is not None
        assert result.name == "2026-02-17"

    def test_no_prior_returns_none(self, tmp_path):
        _write_rankings(tmp_path / "2026-02-19" / "rankings.csv", _make_tickers(10))
        result = _find_prior_snapshot(tmp_path, "2026-02-19")
        assert result is None

    def test_skips_non_date_dirs(self, tmp_path):
        """Ignores directories that don't match YYYY-MM-DD pattern."""
        _write_rankings(tmp_path / "2026-02-18" / "rankings.csv", _make_tickers(10))
        _write_rankings(tmp_path / "2026-02-19" / "rankings.csv", _make_tickers(10))
        (tmp_path / "not_a_date").mkdir()
        (tmp_path / "2026-02-19__pre_backup").mkdir()

        result = _find_prior_snapshot(tmp_path, "2026-02-19")
        assert result is not None
        assert result.name == "2026-02-18"

    def test_current_date_not_in_list(self, tmp_path):
        """Handles case where current_date dir doesn't exist yet."""
        _write_rankings(tmp_path / "2026-02-17" / "rankings.csv", _make_tickers(10))
        _write_rankings(tmp_path / "2026-02-18" / "rankings.csv", _make_tickers(10))

        result = _find_prior_snapshot(tmp_path, "2026-02-19")
        assert result is not None
        assert result.name == "2026-02-18"


# ---------------------------------------------------------------------------
# check_drift_monitoring tests
# ---------------------------------------------------------------------------


class TestCheckDriftMonitoring:
    def test_no_prior_snapshot_pass(self, tmp_path):
        """No prior → PASS, detail says skipped."""
        staging = tmp_path / "staging" / "2026-02-19"
        _write_rankings(staging / "rankings.csv", _make_tickers(30))
        snapshot_dir = tmp_path / "snapshots"
        snapshot_dir.mkdir()

        gate = check_drift_monitoring(staging, snapshot_dir, "2026-02-19", DriftThresholds())
        assert gate.status == "PASS"
        assert "skipped" in gate.detail.lower()

    def test_identical_snapshots_pass(self, tmp_path):
        """Identical data → PASS, 100% overlap, rho=1.0."""
        rows = _make_tickers(30)
        snapshot_dir = tmp_path / "snapshots"
        _write_rankings(snapshot_dir / "2026-02-18" / "rankings.csv", rows)

        staging = tmp_path / "staging" / "2026-02-19"
        _write_rankings(staging / "rankings.csv", rows)

        gate = check_drift_monitoring(staging, snapshot_dir, "2026-02-19", DriftThresholds())
        assert gate.status == "PASS"
        assert gate.value["top20_overlap_pct"] == 100.0
        assert gate.value["rank_spearman_rho"] == 1.0

    def test_moderate_drift_pass(self, tmp_path):
        """Moderate drift within thresholds → PASS."""
        rows_prior = _make_tickers(30)
        # Swap positions 1 and 2 — small change
        rows_current = [dict(r) for r in rows_prior]
        rows_current[0]["actionable_rank"] = "2"
        rows_current[0]["composite_rank"] = "2"
        rows_current[1]["actionable_rank"] = "1"
        rows_current[1]["composite_rank"] = "1"

        snapshot_dir = tmp_path / "snapshots"
        _write_rankings(snapshot_dir / "2026-02-18" / "rankings.csv", rows_prior)

        staging = tmp_path / "staging" / "2026-02-19"
        _write_rankings(staging / "rankings.csv", rows_current)

        gate = check_drift_monitoring(staging, snapshot_dir, "2026-02-19", DriftThresholds())
        assert gate.status == "PASS"

    def test_high_drift_warn(self, tmp_path):
        """50% top-20 overlap → WARN."""
        # Prior: TICK1..TICK30
        rows_prior = _make_tickers(30)
        # Current: completely different top-20 (shift by 15)
        rows_current = _make_tickers(30, start=16)  # TICK16..TICK45

        snapshot_dir = tmp_path / "snapshots"
        _write_rankings(snapshot_dir / "2026-02-18" / "rankings.csv", rows_prior)

        staging = tmp_path / "staging" / "2026-02-19"
        _write_rankings(staging / "rankings.csv", rows_current)

        gate = check_drift_monitoring(staging, snapshot_dir, "2026-02-19", WARN_ONLY_THRESHOLDS)
        assert gate.status == "WARN"
        assert any("warn_top20_overlap_pct" in r for r in gate.detail.split(";"))

    def test_low_spearman_warn(self, tmp_path):
        """Reversed ranks → rho drops below threshold → WARN."""
        rows_prior = _make_tickers(30)
        # Reverse all ranks
        rows_current = []
        for i, r in enumerate(rows_prior):
            row = dict(r)
            row["actionable_rank"] = str(30 - i)
            row["composite_rank"] = str(30 - i)
            rows_current.append(row)

        snapshot_dir = tmp_path / "snapshots"
        _write_rankings(snapshot_dir / "2026-02-18" / "rankings.csv", rows_prior)

        staging = tmp_path / "staging" / "2026-02-19"
        _write_rankings(staging / "rankings.csv", rows_current)

        gate = check_drift_monitoring(staging, snapshot_dir, "2026-02-19", WARN_ONLY_THRESHOLDS)
        assert gate.status == "WARN"
        assert any("warn_rank_spearman_rho" in r for r in gate.detail.split(";"))

    def test_tier_migration_warn(self, tmp_path):
        """15 tier changes → WARN (threshold is 10)."""
        rows_prior = _make_tickers(30)
        rows_current = [dict(r) for r in rows_prior]
        # Change 15 tickers from A to B or vice versa
        for i in range(15):
            old = rows_current[i]["tier_dev"]
            rows_current[i]["tier_dev"] = "B" if old == "A" else "A"

        snapshot_dir = tmp_path / "snapshots"
        _write_rankings(snapshot_dir / "2026-02-18" / "rankings.csv", rows_prior)

        staging = tmp_path / "staging" / "2026-02-19"
        _write_rankings(staging / "rankings.csv", rows_current)

        gate = check_drift_monitoring(staging, snapshot_dir, "2026-02-19", DriftThresholds())
        assert gate.status == "WARN"
        assert "warn_tier_migration_count" in gate.detail

    def test_eligibility_change_warn(self, tmp_path):
        """12 eligibility changes → WARN (threshold is 10)."""
        rows_prior = _make_tickers(30)
        rows_current = [dict(r) for r in rows_prior]
        for i in range(12):
            rows_current[i]["eligible"] = "False"

        snapshot_dir = tmp_path / "snapshots"
        _write_rankings(snapshot_dir / "2026-02-18" / "rankings.csv", rows_prior)

        staging = tmp_path / "staging" / "2026-02-19"
        _write_rankings(staging / "rankings.csv", rows_current)

        gate = check_drift_monitoring(staging, snapshot_dir, "2026-02-19", DriftThresholds())
        assert gate.status == "WARN"
        assert "warn_eligibility_change_count" in gate.detail

    def test_multiple_warn_reasons(self, tmp_path):
        """Several thresholds breached → all reasons listed."""
        rows_prior = _make_tickers(30)
        # Completely different universe — triggers overlap + migration + eligibility
        rows_current = _make_tickers(30, start=16)

        snapshot_dir = tmp_path / "snapshots"
        _write_rankings(snapshot_dir / "2026-02-18" / "rankings.csv", rows_prior)

        staging = tmp_path / "staging" / "2026-02-19"
        _write_rankings(staging / "rankings.csv", rows_current)

        gate = check_drift_monitoring(staging, snapshot_dir, "2026-02-19", WARN_ONLY_THRESHOLDS)
        assert gate.status == "WARN"
        # At least overlap should be triggered
        assert "warn_top20_overlap_pct" in gate.detail

    def test_extreme_drift_fails(self, tmp_path):
        """Extreme drift (0% overlap) → status is FAIL (blocks promotion)."""
        rows_prior = _make_tickers(30)
        # Totally different universe
        rows_current = _make_tickers(30, start=100)

        snapshot_dir = tmp_path / "snapshots"
        _write_rankings(snapshot_dir / "2026-02-18" / "rankings.csv", rows_prior)

        staging = tmp_path / "staging" / "2026-02-19"
        _write_rankings(staging / "rankings.csv", rows_current)

        gate = check_drift_monitoring(staging, snapshot_dir, "2026-02-19", DriftThresholds())
        assert gate.status == "FAIL"

    def test_extreme_drift_with_disabled_fail_thresholds(self, tmp_path):
        """With FAIL thresholds disabled, extreme drift only WARNs."""
        rows_prior = _make_tickers(30)
        rows_current = _make_tickers(30, start=100)

        snapshot_dir = tmp_path / "snapshots"
        _write_rankings(snapshot_dir / "2026-02-18" / "rankings.csv", rows_prior)

        staging = tmp_path / "staging" / "2026-02-19"
        _write_rankings(staging / "rankings.csv", rows_current)

        # Disable FAIL by setting impossibly permissive thresholds
        permissive = DriftThresholds(
            fail_top20_overlap_pct=0.0,
            fail_top60_overlap_pct=0.0,
            fail_rank_spearman_rho=0.0,
            fail_mean_abs_rank_delta_top60=999.0,
            fail_tier_migration_count=999,
            fail_eligibility_change_count=999,
        )
        gate = check_drift_monitoring(staging, snapshot_dir, "2026-02-19", permissive)
        assert gate.status in ("PASS", "WARN")
        assert gate.status != "FAIL"

    def test_drift_report_json_written(self, tmp_path):
        """drift_report.json exists in snapshot dir."""
        rows = _make_tickers(30)
        snapshot_dir = tmp_path / "snapshots"
        _write_rankings(snapshot_dir / "2026-02-18" / "rankings.csv", rows)

        staging = tmp_path / "staging" / "2026-02-19"
        _write_rankings(staging / "rankings.csv", rows)

        check_drift_monitoring(staging, snapshot_dir, "2026-02-19", DriftThresholds())
        assert (staging / "drift_report.json").exists()

    def test_drift_report_md_written(self, tmp_path):
        """drift_report.md exists in snapshot dir."""
        rows = _make_tickers(30)
        snapshot_dir = tmp_path / "snapshots"
        _write_rankings(snapshot_dir / "2026-02-18" / "rankings.csv", rows)

        staging = tmp_path / "staging" / "2026-02-19"
        _write_rankings(staging / "rankings.csv", rows)

        check_drift_monitoring(staging, snapshot_dir, "2026-02-19", DriftThresholds())
        assert (staging / "drift_report.md").exists()

    def test_drift_report_schema(self, tmp_path):
        """JSON report has required keys: version, thresholds_id, metrics, status."""
        rows = _make_tickers(30)
        snapshot_dir = tmp_path / "snapshots"
        _write_rankings(snapshot_dir / "2026-02-18" / "rankings.csv", rows)

        staging = tmp_path / "staging" / "2026-02-19"
        _write_rankings(staging / "rankings.csv", rows)

        check_drift_monitoring(staging, snapshot_dir, "2026-02-19", DriftThresholds())

        with open(staging / "drift_report.json") as f:
            report = json.load(f)

        assert report["version"] in ("1.0.0", "1.1.0", "1.2.0")
        assert "thresholds_id" in report
        assert "metrics" in report
        assert "status" in report
        assert "current_date" in report
        assert "prior_date" in report
        assert "warn_reasons" in report
        assert "fail_reasons" in report

        metrics = report["metrics"]
        assert "top20_overlap_pct" in metrics
        assert "top60_overlap_pct" in metrics
        assert "rank_spearman_rho" in metrics
        assert "tier_migration_count" in metrics
        assert "eligibility_change_count" in metrics

    def test_actionable_rank_fallback(self, tmp_path):
        """Falls back to composite_rank for old-format CSV."""
        # Write prior with only composite_rank (no actionable_rank)
        prior_dir = tmp_path / "snapshots" / "2026-02-18"
        prior_dir.mkdir(parents=True)
        with open(prior_dir / "rankings.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["ticker", "composite_rank", "tier_dev", "eligible"])
            writer.writeheader()
            for i in range(1, 31):
                writer.writerow(
                    {
                        "ticker": f"TICK{i}",
                        "composite_rank": str(i),
                        "tier_dev": "A" if i <= 7 else "B",
                        "eligible": "True",
                    }
                )

        staging = tmp_path / "staging" / "2026-02-19"
        _write_rankings(staging / "rankings.csv", _make_tickers(30))

        gate = check_drift_monitoring(
            staging,
            tmp_path / "snapshots",
            "2026-02-19",
            DriftThresholds(),
        )
        assert gate.status in ("PASS", "WARN")
        assert gate.value["rank_column_prior"] == "composite_rank"
        assert gate.value["rank_column_current"] == "actionable_rank"

    def test_mean_abs_rank_delta_warn(self, tmp_path):
        """Large rank shuffles in top-60 → WARN on mean_abs_rank_delta_top60."""
        rows_prior = _make_tickers(60)
        # Shuffle: shift every rank by 20
        rows_current = []
        for r in rows_prior:
            row = dict(r)
            old_rank = int(row["actionable_rank"])
            new_rank = ((old_rank + 19) % 60) + 1
            row["actionable_rank"] = str(new_rank)
            row["composite_rank"] = str(new_rank)
            rows_current.append(row)

        snapshot_dir = tmp_path / "snapshots"
        _write_rankings(snapshot_dir / "2026-02-18" / "rankings.csv", rows_prior)

        staging = tmp_path / "staging" / "2026-02-19"
        _write_rankings(staging / "rankings.csv", rows_current)

        gate = check_drift_monitoring(staging, snapshot_dir, "2026-02-19", WARN_ONLY_THRESHOLDS)
        assert gate.status == "WARN"
        assert "warn_mean_abs_rank_delta_top60" in gate.detail


# ---------------------------------------------------------------------------
# Institutional drift metrics tests
# ---------------------------------------------------------------------------

import pandas as pd
from run_drift_report import DriftGuardrails, _institutional_metrics, evaluate_guardrails


def _make_inst_rankings(n: int = 30, nonzero_z_pct: float = 50.0) -> pd.DataFrame:
    """Build a minimal DataFrame with institutional delta columns."""
    import numpy as np

    rows = []
    n_nonzero = int(n * nonzero_z_pct / 100)
    for i in range(n):
        z = round(np.random.default_rng(i).standard_normal(), 4) if i < n_nonzero else 0.0
        rows.append(
            {
                "ticker": f"TICK{i+1}",
                "archetype": "drug_developer",
                "actionable_rank": str(i + 1),
                "inst_delta_z": z,
                "inst_delta_net": 1 if z > 0 else 0,
            }
        )
    return pd.DataFrame(rows)


class TestInstitutionalMetrics:
    """_institutional_metrics() helper tests."""

    def test_inst_metrics_present(self):
        """Metrics returned when columns exist with nonzero values."""
        df = _make_inst_rankings(30, nonzero_z_pct=50.0)
        result = _institutional_metrics(df)
        assert result is not None
        assert "inst_delta_z_std" in result
        assert "inst_delta_z_mean" in result
        assert "inst_delta_nonzero_pct" in result
        assert result["inst_delta_nonzero_pct"] > 0

    def test_inst_metrics_absent(self):
        """Returns None when columns missing (old snapshots)."""
        df = pd.DataFrame(
            {
                "ticker": ["TICK1"],
                "archetype": ["drug_developer"],
                "actionable_rank": ["1"],
            }
        )
        result = _institutional_metrics(df)
        assert result is None

    def test_inst_metrics_all_zero(self):
        """All-zero z still returns metrics (nonzero_pct = 0)."""
        df = _make_inst_rankings(10, nonzero_z_pct=0.0)
        result = _institutional_metrics(df)
        assert result is not None
        assert result["inst_delta_nonzero_pct"] == 0.0
        assert result["inst_delta_z_std"] == 0.0

    def test_inst_warn_low_coverage(self):
        """WARN when nonzero_pct < threshold."""
        g = DriftGuardrails(warn_inst_delta_nonzero_low=50.0)
        # Metrics with 10% nonzero → should WARN
        metrics = {
            "current": {"inst_delta_nonzero_pct": 3.0},
            "rolling": {},
            "snapshots": [],
        }
        status, reasons, _, _ = evaluate_guardrails(metrics, g)
        assert status == "WARN"
        assert any("inst_delta_nonzero_pct" in r for r in reasons)

    def test_guardrails_id_updated(self):
        """New DriftGuardrails field changes the guardrails_id."""
        g1 = DriftGuardrails()
        g2 = DriftGuardrails(warn_inst_delta_nonzero_low=99.0)
        assert g1.guardrails_id != g2.guardrails_id


# ---------------------------------------------------------------------------
# Stability plumbing diagnostics (v1.2.0)
# ---------------------------------------------------------------------------


STABILITY_HEADER = [
    "ticker",
    "actionable_rank",
    "tier_dev",
    "eligible",
    "composite_rank",
    "composite_score",
    "selector_score",
    "final_score",
    "coinvest_score_z",
    "inst_delta_z",
]


def _write_stability_rankings(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=STABILITY_HEADER)
        writer.writeheader()
        writer.writerows(rows)


def _make_stability_tickers(n: int, start: int = 1, *, spread: float = 0.01) -> list[dict]:
    """Rankings with non-trivial selector_score/final_score and two feature cols."""
    rows = []
    for i in range(start, start + n):
        idx = i - start  # 0..n-1
        sel = round(1.0 - idx * spread, 6)
        fin = round(0.9 - idx * spread, 6)
        rows.append(
            {
                "ticker": f"TICK{i}",
                "actionable_rank": str(idx + 1),
                "tier_dev": "A" if idx < 10 else ("B" if idx < 30 else "C"),
                "eligible": "True",
                "composite_rank": str(idx + 1),
                "composite_score": str(sel),
                "selector_score": str(sel),
                "final_score": str(fin),
                "coinvest_score_z": str(round(0.5 - 0.01 * idx, 4)),
                "inst_delta_z": str(round(0.3 + 0.005 * idx, 4)),
            }
        )
    return rows


class TestActionTransitionMatrix:
    def test_identical_has_zero_off_diagonal(self, tmp_path):
        rows = _make_stability_tickers(40)
        cur = tmp_path / "cur.csv"
        pri = tmp_path / "pri.csv"
        _write_stability_rankings(cur, rows)
        _write_stability_rankings(pri, rows)

        m = _compute_drift_metrics(cur, pri)
        assert m["action_change_count"] == 0
        assert m["action_change_pct"] == 0.0
        # Diagonal sums to n_common
        matrix = m["action_transition_matrix"]
        off_diag = sum(
            cnt
            for ft, row in matrix.items()
            for tt, cnt in row.items()
            if ft != tt
        )
        assert off_diag == 0

    def test_counts_tier_transitions(self, tmp_path):
        prior_rows = _make_stability_tickers(40)
        cur_rows = [dict(r) for r in prior_rows]
        # Flip 5 A's to B, 3 B's to C
        flipped = 0
        for r in cur_rows:
            if r["tier_dev"] == "A" and flipped < 5:
                r["tier_dev"] = "B"
                flipped += 1
        flipped_b = 0
        for r in cur_rows:
            if r["tier_dev"] == "B" and flipped_b < 3:
                # Careful: don't re-flip freshly moved A→B; check via rank
                # The first 5 A-flips occupied first 5 positions; move 3 from position 20..22
                pass
        # Simpler: explicitly transition last 3 B's to C
        b_indices = [i for i, r in enumerate(cur_rows) if r["tier_dev"] == "B"]
        for i in b_indices[-3:]:
            cur_rows[i]["tier_dev"] = "C"

        cur = tmp_path / "cur.csv"
        pri = tmp_path / "pri.csv"
        _write_stability_rankings(cur, cur_rows)
        _write_stability_rankings(pri, prior_rows)

        m = _compute_drift_metrics(cur, pri)
        matrix = m["action_transition_matrix"]
        assert matrix.get("A", {}).get("B", 0) == 5
        assert matrix.get("B", {}).get("C", 0) == 3
        assert m["action_change_count"] == 8
        assert m["action_change_pct"] == 20.0  # 8/40


class TestScoreDeltaStats:
    def test_identical_scores_zero_delta(self, tmp_path):
        rows = _make_stability_tickers(30)
        cur = tmp_path / "cur.csv"
        pri = tmp_path / "pri.csv"
        _write_stability_rankings(cur, rows)
        _write_stability_rankings(pri, rows)

        m = _compute_drift_metrics(cur, pri)
        stats = m["score_delta_stats"]
        assert "selector_score" in stats
        assert stats["selector_score"]["mean_abs_delta"] == 0.0
        assert stats["selector_score"]["p95_abs_delta"] == 0.0

    def test_shifted_scores_measured(self, tmp_path):
        prior_rows = _make_stability_tickers(30)
        cur_rows = [dict(r) for r in prior_rows]
        for r in cur_rows:
            r["selector_score"] = str(float(r["selector_score"]) + 0.05)
            r["final_score"] = str(float(r["final_score"]) + 0.05)

        cur = tmp_path / "cur.csv"
        pri = tmp_path / "pri.csv"
        _write_stability_rankings(cur, cur_rows)
        _write_stability_rankings(pri, prior_rows)

        m = _compute_drift_metrics(cur, pri)
        sel = m["score_delta_stats"]["selector_score"]
        assert abs(sel["mean_abs_delta"] - 0.05) < 1e-6
        assert abs(sel["p95_abs_delta"] - 0.05) < 1e-6

    def test_warn_fires_on_large_selector_delta(self, tmp_path):
        prior_rows = _make_stability_tickers(30)
        cur_rows = [dict(r) for r in prior_rows]
        for r in cur_rows:
            r["selector_score"] = str(float(r["selector_score"]) + 0.20)

        snapshot_dir = tmp_path / "snapshots"
        _write_stability_rankings(snapshot_dir / "2026-02-18" / "rankings.csv", prior_rows)
        staging = tmp_path / "staging" / "2026-02-19"
        _write_stability_rankings(staging / "rankings.csv", cur_rows)

        gate = check_drift_monitoring(staging, snapshot_dir, "2026-02-19", WARN_ONLY_THRESHOLDS)
        assert gate.status == "WARN"
        assert "warn_mean_abs_selector_score_delta" in gate.detail


class TestFeatureCoverageDelta:
    def test_coverage_drop_detected(self, tmp_path):
        prior_rows = _make_stability_tickers(30)
        # Blank coinvest_score_z for 15 of 30 in current (50pp drop: 100% → 50%)
        cur_rows = [dict(r) for r in prior_rows]
        for i, r in enumerate(cur_rows):
            if i < 15:
                r["coinvest_score_z"] = ""

        cur = tmp_path / "cur.csv"
        pri = tmp_path / "pri.csv"
        _write_stability_rankings(cur, cur_rows)
        _write_stability_rankings(pri, prior_rows)

        m = _compute_drift_metrics(cur, pri)
        delta = m["coverage_delta"]
        assert delta["coinvest_score_z"] == -50.0
        assert m["max_coverage_drop_feature"] == "coinvest_score_z"
        assert m["max_coverage_drop_pp"] == 50.0
        assert any(d["feature"] == "coinvest_score_z" for d in m["coverage_drops_top5"])

    def test_no_drop_when_identical(self, tmp_path):
        rows = _make_stability_tickers(30)
        cur = tmp_path / "cur.csv"
        pri = tmp_path / "pri.csv"
        _write_stability_rankings(cur, rows)
        _write_stability_rankings(pri, rows)

        m = _compute_drift_metrics(cur, pri)
        assert m["max_coverage_drop_pp"] == 0.0
        assert m["max_coverage_drop_feature"] is None
        assert m["coverage_drops_top5"] == []

    def test_warn_fires_on_coverage_drop(self, tmp_path):
        prior_rows = _make_stability_tickers(40)
        cur_rows = [dict(r) for r in prior_rows]
        for i, r in enumerate(cur_rows):
            if i < 8:  # 20pp drop on inst_delta_z (8/40=20%)
                r["inst_delta_z"] = ""

        snapshot_dir = tmp_path / "snapshots"
        _write_stability_rankings(snapshot_dir / "2026-02-18" / "rankings.csv", prior_rows)
        staging = tmp_path / "staging" / "2026-02-19"
        _write_stability_rankings(staging / "rankings.csv", cur_rows)

        gate = check_drift_monitoring(staging, snapshot_dir, "2026-02-19", WARN_ONLY_THRESHOLDS)
        assert gate.status == "WARN"
        assert "warn_feature_coverage_drop_pct" in gate.detail


class TestNearMissFragility:
    def test_near_miss_counts_spread_scores(self, tmp_path):
        # Wide spread → tight tolerances catch few names
        rows = _make_stability_tickers(40, spread=0.01)
        cur = tmp_path / "cur.csv"
        pri = tmp_path / "pri.csv"
        _write_stability_rankings(cur, rows)
        _write_stability_rankings(pri, rows)

        m = _compute_drift_metrics(cur, pri)
        nm = m["near_miss"]
        assert "selector_score" in nm
        assert "K30" in nm["selector_score"]
        k30 = nm["selector_score"]["K30"]
        assert "cutoff_score" in k30
        eps = k30["eps_counts"]
        # With spread=0.01, the rank-30 score differs from rank-29 by 0.01, so
        # within 10bps (0.001) catches only itself (1).
        assert eps["within_10bps"] == 1

    def test_near_miss_counts_clumped_scores(self, tmp_path):
        # Clumped scores → many near-misses at cutoff
        rows = _make_stability_tickers(40, spread=0.0001)
        cur = tmp_path / "cur.csv"
        pri = tmp_path / "pri.csv"
        _write_stability_rankings(cur, rows)
        _write_stability_rankings(pri, rows)

        m = _compute_drift_metrics(cur, pri)
        k30 = m["near_miss"]["selector_score"]["K30"]
        eps = k30["eps_counts"]
        # Scores span 0.0001 * 39 = 0.0039 — within 50bps of cutoff catches many
        assert eps["within_50bps"] >= 20
        # Near-miss share within 25bps of K30 cutoff is non-trivial
        assert m["near_miss_share_pct"] > 0.0

    def test_warn_fires_on_high_near_miss_share(self, tmp_path):
        # Extremely tight spread → ~100% of top-30 within 25bps of cutoff
        rows = _make_stability_tickers(40, spread=1e-6)
        snapshot_dir = tmp_path / "snapshots"
        _write_stability_rankings(snapshot_dir / "2026-02-18" / "rankings.csv", rows)
        staging = tmp_path / "staging" / "2026-02-19"
        _write_stability_rankings(staging / "rankings.csv", rows)

        gate = check_drift_monitoring(staging, snapshot_dir, "2026-02-19", WARN_ONLY_THRESHOLDS)
        assert gate.status == "WARN"
        assert "warn_near_miss_share_pct" in gate.detail


class TestStabilitySchemaV12:
    def test_report_has_v12_keys(self, tmp_path):
        rows = _make_stability_tickers(30)
        snapshot_dir = tmp_path / "snapshots"
        _write_stability_rankings(snapshot_dir / "2026-02-18" / "rankings.csv", rows)
        staging = tmp_path / "staging" / "2026-02-19"
        _write_stability_rankings(staging / "rankings.csv", rows)

        check_drift_monitoring(staging, snapshot_dir, "2026-02-19", DriftThresholds())
        with open(staging / "drift_report.json") as f:
            report = json.load(f)

        assert report["version"] == "1.2.0"
        metrics = report["metrics"]
        for key in (
            "action_transition_matrix",
            "action_change_pct",
            "score_delta_stats",
            "coverage_delta",
            "max_coverage_drop_pp",
            "near_miss",
            "near_miss_share_pct",
        ):
            assert key in metrics

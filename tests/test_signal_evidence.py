"""Tests for scripts/run_signal_evidence.py — signal evidence packet harness.

Uses synthetic fixtures only; no network, no archive extraction.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "research"))

from run_signal_evidence import (
    SCHEMA_VERSION,
    _validate_pit,
    compute_deltas,
    compute_recommendation,
    load_date_manifest,
    run_evidence,
)

# ---------------------------------------------------------------------------
# Fixtures — 5 synthetic tickers, minimal columns
# ---------------------------------------------------------------------------

TICKERS = ["AAAA", "BBBB", "CCCC", "DDDD", "EEEE"]
RANKING_COLUMNS = [
    "ticker",
    "actionable_rank",
    "composite_score",
    "final_tier",
    "eligible",
    "archetype",
]


def _make_rankings_rows(seed: int = 0) -> List[Dict[str, str]]:
    """Create minimal rankings rows for 5 tickers."""
    rows = []
    for i, t in enumerate(TICKERS):
        rows.append(
            {
                "ticker": t,
                "actionable_rank": str(i + 1 + seed),
                "composite_score": str(round(0.9 - i * 0.1, 2)),
                "final_tier": "b0_30",
                "eligible": "True",
                "archetype": "CLINICAL",
            }
        )
    return rows


def _write_snapshot(
    root: Path,
    date: str,
    rows: Optional[List[Dict[str, str]]] = None,
    as_of_date: Optional[str] = None,
) -> None:
    """Write a minimal snapshot directory (rankings.csv + metadata.json)."""
    snap_dir = root / date
    snap_dir.mkdir(parents=True, exist_ok=True)

    if rows is None:
        rows = _make_rankings_rows()

    with open(snap_dir / "rankings.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RANKING_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    meta = {
        "as_of_date": as_of_date if as_of_date is not None else date,
        "ruleset_id": "test",
        "generated_at": f"{date}T00:00:00Z",
    }
    (snap_dir / "metadata.json").write_text(json.dumps(meta))


def _write_manifest(path: Path, dates: List[str]) -> None:
    """Write a one-date-per-line manifest file."""
    path.write_text("\n".join(dates) + "\n")


def _write_price_csv(path: Path, dates: List[str]) -> None:
    """Write minimal price_history.csv covering TICKERS across dates + horizons."""
    from datetime import datetime, timedelta

    all_dates_dt = sorted(datetime.strptime(d, "%Y-%m-%d") for d in dates)
    # Extend date range to cover forward horizons (up to 100 trading days)
    start = all_dates_dt[0] - timedelta(days=5)
    end = all_dates_dt[-1] + timedelta(days=200)

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker", "date", "close", "volume"])
        current = start
        day_idx = 0
        while current <= end:
            # Skip weekends
            if current.weekday() < 5:
                for i, t in enumerate(TICKERS):
                    price = 10.0 + i + day_idx * 0.01
                    writer.writerow([t, current.strftime("%Y-%m-%d"), f"{price:.2f}", "100000"])
                # XBI benchmark
                writer.writerow(["XBI", current.strftime("%Y-%m-%d"), f"{80.0 + day_idx * 0.01:.2f}", "5000000"])
                day_idx += 1
            current += timedelta(days=1)


def _build_test_env(
    tmp_path: Path,
    dates: List[str],
    *,
    skip_dates: Optional[List[str]] = None,
    pit_mismatch_dates: Optional[Dict[str, str]] = None,
) -> Tuple[Path, Path, Path, Path]:
    """Build a complete test environment.

    Returns (baseline_root, candidate_root, manifest_path, price_csv_path).
    """
    base_root = tmp_path / "snapshots_base"
    cand_root = tmp_path / "snapshots_cand"
    manifest_path = tmp_path / "manifest.txt"
    price_path = tmp_path / "price_history.csv"

    skip_set = set(skip_dates or [])
    pit_mismatches = pit_mismatch_dates or {}

    for d in dates:
        if d not in skip_set:
            as_of = pit_mismatches.get(d, d)
            _write_snapshot(base_root, d, as_of_date=as_of)
            _write_snapshot(cand_root, d, as_of_date=as_of)

    _write_manifest(manifest_path, dates)
    _write_price_csv(price_path, dates)

    return base_root, cand_root, manifest_path, price_path


# ---------------------------------------------------------------------------
# Fake evaluate() — replaces real eval_forward_returns.evaluate()
# ---------------------------------------------------------------------------

# We mock evaluate() to avoid pulling in the full data pipeline.
# The mock returns realistic EvalSummary shapes.

_CALL_LOG: List[Dict[str, Any]] = []


def _make_fake_eval_summary(
    horizons: List[int],
    top_k: int,
    cost_bps: float,
    benchmark: str,
    allowed_dates: Optional[Set[str]],
    snapshot_root: Path,
    *,
    ic_offset: float = 0.0,
    return_offset: float = 0.0,
) -> Any:
    """Build a fake EvalSummary dataclass."""
    from eval_forward_returns import EvalSummary

    # Count available snapshot dates
    available = set()
    if snapshot_root.exists():
        for p in snapshot_root.iterdir():
            if p.is_dir() and len(p.name) == 10:
                available.add(p.name)

    if allowed_dates:
        evaluated_dates = available & allowed_dates
    else:
        evaluated_dates = available

    skipped_dates = (allowed_dates or set()) - available

    by_horizon = {}
    for h in horizons:
        by_horizon[h] = {
            "n_dates": len(evaluated_dates),
            "mean_ic": round(0.15 + ic_offset, 6),
            "median_ic": round(0.14 + ic_offset, 6),
            "std_ic": 0.08,
            "mean_gross_return": round(0.02 + return_offset, 6),
            "mean_net_return": round(0.018 + return_offset, 6),
            "cumulative_gross": round(0.06 + return_offset * 3, 6),
            "cumulative_net": round(0.054 + return_offset * 3, 6),
            "mean_turnover": 0.25,
            "mean_bottom_k_return": -0.01,
            "sign_mismatches": 0,
            "mean_excess_return": round(0.01 + return_offset, 6),
            "cumulative_excess": round(0.03 + return_offset * 3, 6),
            "mean_hedged_return": round(0.012 + return_offset, 6),
            "cumulative_hedged": round(0.036 + return_offset * 3, 6),
        }

    summary = EvalSummary(
        horizons=horizons,
        top_k=top_k,
        cost_bps=cost_bps,
        n_dates=len(evaluated_dates) + len(skipped_dates),
        n_evaluated=len(evaluated_dates),
        n_skipped=len(skipped_dates),
        by_horizon=by_horizon,
        benchmark=benchmark,
        anchor_mode="next_trading_day",
    )

    skips = [{"date": d, "reason": "snapshot dir missing"} for d in sorted(skipped_dates)]
    return summary, [], skips


def _fake_evaluate(
    snapshot_root: Path,
    price_csv: Path,
    horizons: List[int],
    top_k: int = 20,
    cost_bps: float = 30,
    allowed_dates: Optional[Set[str]] = None,
    benchmark: str = "none",
    anchor_mode: str = "exact",
    **kwargs,
) -> Any:
    """Mock replacement for eval_forward_returns.evaluate()."""
    _CALL_LOG.append(
        {
            "snapshot_root": str(snapshot_root),
            "allowed_dates": sorted(allowed_dates) if allowed_dates else None,
        }
    )
    return _make_fake_eval_summary(
        horizons=horizons,
        top_k=top_k,
        cost_bps=cost_bps,
        benchmark=benchmark,
        allowed_dates=allowed_dates,
        snapshot_root=snapshot_root,
    )


def _fake_evaluate_with_offset(ic_offset: float, return_offset: float):
    """Factory for fake evaluate with candidate offsets.

    Returns a callable that uses offsets only when the snapshot_root
    contains 'cand' in its path.
    """

    def _eval(
        snapshot_root: Path,
        price_csv: Path,
        horizons: List[int],
        top_k: int = 20,
        cost_bps: float = 30,
        allowed_dates: Optional[Set[str]] = None,
        benchmark: str = "none",
        anchor_mode: str = "exact",
        **kwargs,
    ) -> Any:
        is_candidate = "cand" in str(snapshot_root)
        return _make_fake_eval_summary(
            horizons=horizons,
            top_k=top_k,
            cost_bps=cost_bps,
            benchmark=benchmark,
            allowed_dates=allowed_dates,
            snapshot_root=snapshot_root,
            ic_offset=ic_offset if is_candidate else 0.0,
            return_offset=return_offset if is_candidate else 0.0,
        )

    return _eval


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

EVAL_MODULE = "run_signal_evidence"
MANIFEST_DATES = ["2025-06-01", "2025-07-01", "2025-08-01"]


class TestDeterministicOutput:
    """Test 1: same manifest + same inputs → identical JSON packet."""

    def test_deterministic_output(self, tmp_path):
        base_root, cand_root, manifest, price_csv = _build_test_env(
            tmp_path,
            MANIFEST_DATES,
        )

        out1 = tmp_path / "out1"
        out2 = tmp_path / "out2"

        with patch(f"{EVAL_MODULE}.evaluate", side_effect=_fake_evaluate):
            p1 = run_evidence(
                baseline_root=base_root,
                candidate_root=cand_root,
                date_manifest=manifest,
                price_csv=price_csv,
                horizons=[20, 63],
                top_k=20,
                cost_bps=30,
                benchmark="xbi",
                candidate_id="test_cand",
                baseline_id="test_base",
                out_dir=out1,
            )

        with patch(f"{EVAL_MODULE}.evaluate", side_effect=_fake_evaluate):
            p2 = run_evidence(
                baseline_root=base_root,
                candidate_root=cand_root,
                date_manifest=manifest,
                price_csv=price_csv,
                horizons=[20, 63],
                top_k=20,
                cost_bps=30,
                benchmark="xbi",
                candidate_id="test_cand",
                baseline_id="test_base",
                out_dir=out2,
            )

        # Compare everything except generated_at timestamp
        for key in p1:
            if key == "generated_at":
                continue
            assert p1[key] == p2[key], f"Mismatch on key {key}"

        # JSON files are identical after removing generated_at
        j1 = json.loads((out1 / "signal_evidence.json").read_text())
        j2 = json.loads((out2 / "signal_evidence.json").read_text())
        j1.pop("generated_at")
        j2.pop("generated_at")
        assert json.dumps(j1, sort_keys=True) == json.dumps(j2, sort_keys=True)


class TestIdentityDelta:
    """Test 2: candidate == baseline (same root) → all deltas ≈ 0.0."""

    def test_identity_delta(self, tmp_path):
        base_root, _, manifest, price_csv = _build_test_env(
            tmp_path,
            MANIFEST_DATES,
        )

        out = tmp_path / "out"
        with patch(f"{EVAL_MODULE}.evaluate", side_effect=_fake_evaluate):
            packet = run_evidence(
                baseline_root=base_root,
                candidate_root=base_root,  # same root!
                date_manifest=manifest,
                price_csv=price_csv,
                horizons=[20, 63, 84],
                top_k=20,
                cost_bps=30,
                benchmark="xbi",
                candidate_id="same",
                baseline_id="same",
                out_dir=out,
            )

        for h_str, deltas in packet["delta"]["by_horizon"].items():
            for metric, value in deltas.items():
                if value is not None:
                    assert abs(value) < 1e-6, f"Horizon {h_str}, metric {metric}: expected ~0, got {value}"


class TestMissingSnapshotFails:
    """Test 3: manifest includes date with no snapshot → fail-closed."""

    def test_missing_snapshot_counted_as_skip(self, tmp_path):
        dates = ["2025-06-01", "2025-07-01", "2025-08-01"]
        base_root, cand_root, manifest, price_csv = _build_test_env(
            tmp_path,
            dates,
            skip_dates=["2025-07-01"],
        )

        out = tmp_path / "out"
        with patch(f"{EVAL_MODULE}.evaluate", side_effect=_fake_evaluate):
            packet = run_evidence(
                baseline_root=base_root,
                candidate_root=cand_root,
                date_manifest=manifest,
                price_csv=price_csv,
                horizons=[20],
                top_k=20,
                cost_bps=30,
                benchmark="xbi",
                candidate_id="c1",
                baseline_id="b1",
                out_dir=out,
            )

        # The mock should report 2025-07-01 as skipped
        cov = packet["coverage"]
        assert cov["manifest_dates"] == 3
        # Both baseline and candidate should skip the missing date
        assert cov["both_evaluated"] < 3

    def test_empty_manifest_raises(self, tmp_path):
        manifest = tmp_path / "empty.txt"
        manifest.write_text("")
        with pytest.raises(ValueError, match="empty"):
            load_date_manifest(manifest)

    def test_missing_manifest_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_date_manifest(tmp_path / "nonexistent.txt")


class TestLowCoverageFails:
    """Test 4: < 50% manifest dates evaluable → NEEDS_MORE + coverage warning."""

    def test_low_coverage_needs_more(self, tmp_path):
        dates = ["2025-06-01", "2025-07-01", "2025-08-01", "2025-09-01", "2025-10-01"]
        # Skip 3 of 5 dates → 40% coverage
        base_root, cand_root, manifest, price_csv = _build_test_env(
            tmp_path,
            dates,
            skip_dates=["2025-07-01", "2025-08-01", "2025-09-01"],
        )

        out = tmp_path / "out"
        with patch(f"{EVAL_MODULE}.evaluate", side_effect=_fake_evaluate):
            packet = run_evidence(
                baseline_root=base_root,
                candidate_root=cand_root,
                date_manifest=manifest,
                price_csv=price_csv,
                horizons=[20, 63, 84],
                top_k=20,
                cost_bps=30,
                benchmark="xbi",
                candidate_id="c1",
                baseline_id="b1",
                out_dir=out,
            )

        assert packet["recommendation"] == "NEEDS_MORE"
        assert (
            "coverage" in packet["recommendation_detail"].lower() or "below" in packet["recommendation_detail"].lower()
        )


class TestPitValidationPropagates:
    """Test 5: metadata.as_of_date mismatch → reported in pit_validation."""

    def test_pit_mismatch_reported(self, tmp_path):
        dates = ["2025-06-01", "2025-07-01"]
        base_root, cand_root, manifest, price_csv = _build_test_env(
            tmp_path,
            dates,
            pit_mismatch_dates={"2025-07-01": "2025-06-30"},  # wrong as_of_date
        )

        out = tmp_path / "out"
        with patch(f"{EVAL_MODULE}.evaluate", side_effect=_fake_evaluate):
            packet = run_evidence(
                baseline_root=base_root,
                candidate_root=cand_root,
                date_manifest=manifest,
                price_csv=price_csv,
                horizons=[20],
                top_k=20,
                cost_bps=30,
                benchmark="xbi",
                candidate_id="c1",
                baseline_id="b1",
                out_dir=out,
            )

        pit = packet["pit_validation"]
        assert not pit["baseline_ok"]
        assert len(pit["mismatches"]) > 0
        mismatch_dates = [m["date"] for m in pit["mismatches"]]
        assert "2025-07-01" in mismatch_dates


class TestManifestHonoredExactly:
    """Test 6: only manifest dates evaluated, never implicit discovery."""

    def test_only_manifest_dates(self, tmp_path):
        manifest_dates = ["2025-06-01", "2025-07-01"]
        extra_date = "2025-08-01"

        base_root, cand_root, manifest, price_csv = _build_test_env(
            tmp_path,
            manifest_dates,
        )
        # Write an extra snapshot NOT in the manifest
        _write_snapshot(base_root, extra_date)
        _write_snapshot(cand_root, extra_date)

        _CALL_LOG.clear()

        out = tmp_path / "out"
        with patch(f"{EVAL_MODULE}.evaluate", side_effect=_fake_evaluate):
            run_evidence(
                baseline_root=base_root,
                candidate_root=cand_root,
                date_manifest=manifest,
                price_csv=price_csv,
                horizons=[20],
                top_k=20,
                cost_bps=30,
                benchmark="xbi",
                candidate_id="c1",
                baseline_id="b1",
                out_dir=out,
            )

        # Verify evaluate() was called with allowed_dates matching manifest
        assert len(_CALL_LOG) >= 2
        for call in _CALL_LOG:
            if call["allowed_dates"] is not None:
                assert extra_date not in call["allowed_dates"]
                for d in manifest_dates:
                    assert d in call["allowed_dates"]


class TestRecommendationThresholds:
    """Test 7: verify PROMISING/REJECT/NEEDS_MORE logic."""

    def test_promising(self):
        delta = {
            84: {"hedged_pp": 0.25, "ic": 0.01, "net_pp": 0.20, "turnover": 0.0, "excess_pp": 0.20},
            63: {"hedged_pp": 0.10, "ic": 0.01, "net_pp": 0.10, "turnover": 0.0, "excess_pp": 0.10},
            20: {"hedged_pp": 0.05, "ic": 0.01, "net_pp": 0.05, "turnover": 0.0, "excess_pp": 0.05},
        }
        rec, detail = compute_recommendation(delta, [20, 63, 84], coverage_fraction=0.8)
        assert rec == "PROMISING"

    def test_reject(self):
        delta = {
            84: {"hedged_pp": -0.10, "ic": -0.02, "net_pp": -0.10, "turnover": 0.0, "excess_pp": -0.10},
            63: {"hedged_pp": -0.05, "ic": -0.01, "net_pp": -0.05, "turnover": 0.0, "excess_pp": -0.05},
            20: {"hedged_pp": -0.02, "ic": 0.0, "net_pp": -0.02, "turnover": 0.0, "excess_pp": -0.02},
        }
        rec, detail = compute_recommendation(delta, [20, 63, 84], coverage_fraction=0.8)
        assert rec == "REJECT"

    def test_needs_more_below_threshold(self):
        delta = {
            84: {"hedged_pp": 0.10, "ic": 0.01, "net_pp": 0.10, "turnover": 0.0, "excess_pp": 0.10},
            63: {"hedged_pp": 0.05, "ic": 0.01, "net_pp": 0.05, "turnover": 0.0, "excess_pp": 0.05},
            20: {"hedged_pp": 0.02, "ic": 0.01, "net_pp": 0.02, "turnover": 0.0, "excess_pp": 0.02},
        }
        rec, detail = compute_recommendation(delta, [20, 63, 84], coverage_fraction=0.8)
        assert rec == "NEEDS_MORE"

    def test_needs_more_guardrail_violation(self):
        """Promising primary but a guardrail horizon < -0.05pp."""
        delta = {
            84: {"hedged_pp": 0.30, "ic": 0.02, "net_pp": 0.30, "turnover": 0.0, "excess_pp": 0.30},
            63: {"hedged_pp": -0.10, "ic": -0.01, "net_pp": -0.10, "turnover": 0.0, "excess_pp": -0.10},
            20: {"hedged_pp": 0.05, "ic": 0.01, "net_pp": 0.05, "turnover": 0.0, "excess_pp": 0.05},
        }
        rec, detail = compute_recommendation(delta, [20, 63, 84], coverage_fraction=0.8)
        assert rec == "NEEDS_MORE"
        assert "guardrail" in detail.lower()

    def test_low_coverage_overrides(self):
        """Even with great deltas, low coverage → NEEDS_MORE."""
        delta = {
            84: {"hedged_pp": 0.50, "ic": 0.05, "net_pp": 0.50, "turnover": 0.0, "excess_pp": 0.50},
        }
        rec, detail = compute_recommendation(delta, [84], coverage_fraction=0.3)
        assert rec == "NEEDS_MORE"
        assert "coverage" in detail.lower()

    def test_threshold_boundary_promising(self):
        """Exactly at +0.20pp threshold → PROMISING."""
        delta = {
            84: {"hedged_pp": 0.20, "ic": 0.01, "net_pp": 0.20, "turnover": 0.0, "excess_pp": 0.20},
        }
        rec, _ = compute_recommendation(delta, [84], coverage_fraction=0.8)
        assert rec == "PROMISING"

    def test_threshold_boundary_reject(self):
        """Just below -0.05pp → REJECT; exactly -0.05pp → NEEDS_MORE (strict <)."""
        delta_below = {
            84: {"hedged_pp": -0.06, "ic": -0.01, "net_pp": -0.06, "turnover": 0.0, "excess_pp": -0.06},
        }
        rec, _ = compute_recommendation(delta_below, [84], coverage_fraction=0.8)
        assert rec == "REJECT"

        # Exactly at boundary → not rejected (strict < comparison)
        delta_exact = {
            84: {"hedged_pp": -0.05, "ic": -0.01, "net_pp": -0.05, "turnover": 0.0, "excess_pp": -0.05},
        }
        rec2, _ = compute_recommendation(delta_exact, [84], coverage_fraction=0.8)
        assert rec2 == "NEEDS_MORE"


class TestLoadDateManifest:
    """Supplemental tests for manifest loading edge cases."""

    def test_csv_manifest(self, tmp_path):
        path = tmp_path / "manifest.csv"
        path.write_text("date,label\n2025-06-01,a\n2025-07-01,b\n")
        dates = load_date_manifest(path)
        assert dates == ["2025-06-01", "2025-07-01"]

    def test_text_manifest_with_comments(self, tmp_path):
        path = tmp_path / "manifest.txt"
        path.write_text("# comment\n2025-06-01\n\n2025-07-01\n")
        dates = load_date_manifest(path)
        assert dates == ["2025-06-01", "2025-07-01"]

    def test_deduplicates(self, tmp_path):
        path = tmp_path / "manifest.txt"
        path.write_text("2025-06-01\n2025-06-01\n2025-07-01\n")
        dates = load_date_manifest(path)
        assert dates == ["2025-06-01", "2025-07-01"]

    def test_invalid_date_raises(self, tmp_path):
        path = tmp_path / "manifest.txt"
        path.write_text("2025-13-01\n")
        with pytest.raises(ValueError, match="Invalid date"):
            load_date_manifest(path)


class TestComputeDeltas:
    """Unit tests for delta computation."""

    def test_none_propagation(self):
        """If a metric is missing from one side, delta is None."""
        from eval_forward_returns import EvalSummary

        base = EvalSummary(horizons=[20], by_horizon={20: {"mean_ic": 0.1}})
        cand = EvalSummary(horizons=[20], by_horizon={20: {"mean_ic": 0.15}})
        deltas = compute_deltas(base, cand, [20])
        assert deltas[20]["ic"] == pytest.approx(0.05, abs=1e-6)
        # hedged_pp should be None since neither has mean_hedged_return
        assert deltas[20]["hedged_pp"] is None


class TestValidatePit:
    """Unit tests for PIT validation."""

    def test_ok_when_matching(self, tmp_path):
        _write_snapshot(tmp_path, "2025-06-01", as_of_date="2025-06-01")
        ok, mismatches = _validate_pit(tmp_path, ["2025-06-01"])
        assert ok
        assert mismatches == []

    def test_mismatch_detected(self, tmp_path):
        _write_snapshot(tmp_path, "2025-06-01", as_of_date="2025-05-31")
        ok, mismatches = _validate_pit(tmp_path, ["2025-06-01"])
        assert not ok
        assert len(mismatches) == 1
        assert mismatches[0]["date"] == "2025-06-01"

    def test_missing_snapshot_skipped(self, tmp_path):
        ok, mismatches = _validate_pit(tmp_path, ["2025-06-01"])
        assert ok
        assert mismatches == []


class TestOutputFiles:
    """Verify output files are written correctly."""

    def test_json_and_md_written(self, tmp_path):
        base_root, cand_root, manifest, price_csv = _build_test_env(
            tmp_path,
            MANIFEST_DATES,
        )
        out = tmp_path / "out"
        with patch(f"{EVAL_MODULE}.evaluate", side_effect=_fake_evaluate):
            run_evidence(
                baseline_root=base_root,
                candidate_root=cand_root,
                date_manifest=manifest,
                price_csv=price_csv,
                horizons=[20],
                top_k=20,
                cost_bps=30,
                benchmark="xbi",
                candidate_id="c1",
                baseline_id="b1",
                out_dir=out,
            )

        assert (out / "signal_evidence.json").exists()
        assert (out / "signal_evidence.md").exists()

        # JSON is valid
        packet = json.loads((out / "signal_evidence.json").read_text())
        assert packet["schema"] == SCHEMA_VERSION
        assert "provenance" in packet
        assert "delta" in packet

        # MD contains key sections
        md = (out / "signal_evidence.md").read_text()
        assert "Signal Evidence Report" in md
        assert "Coverage" in md
        assert "Deltas" in md

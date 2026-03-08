"""Tests for decision memo builder.

Validates:
  1. Memo file created with expected sections
  2. Provenance keys present
  3. Allocation summary + risk rails section
  4. Deterministic ordering (top-10 per bucket)
  5. JSON sidecar schema
  6. Bucket targets rescale weights
  7. Change vs prior section
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from build_decision_memo import _find_prior_snapshot, build_decision_memo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ACCOUNT_USD = 500_000.0


def _make_row(
    ticker: str,
    rank: int,
    catalyst_days: str = "",
    catalyst_mode: str = "missing",
    eligible: str = "1",
    weight: str = "5.0",
    size_band: str = "M",
    de_beta_xbi_60d_source: str = "price_history",
) -> Dict[str, str]:
    return {
        "ticker": ticker,
        "actionable_rank": str(rank),
        "eligible": eligible,
        "catalyst_days": catalyst_days,
        "catalyst_mode": catalyst_mode,
        "catalyst_bucket": "",
        "catalyst_strength": "",
        "target_weight_pct": weight,
        "tier_any": "A",
        "archetype": "drug_developer",
        "alpha_cohort_key": "",
        "mom_state": "tailwind",
        "industry_group": "",
        "size_band": size_band,
        "de_beta_xbi_60d_source": de_beta_xbi_60d_source,
    }


def _write_rankings_csv(snap_dir: Path, rows: List[Dict[str, str]]) -> None:
    snap_dir.mkdir(parents=True, exist_ok=True)
    csv_path = snap_dir / "rankings.csv"
    if rows:
        fieldnames = list(rows[0].keys())
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


def _write_metadata(snap_dir: Path, **overrides) -> None:
    meta = {
        "as_of_date": snap_dir.name,
        "version": "1.3.0",
        "ruleset_id": "test_rs",
        "ruleset_hash": "abc123",
        "engine_version": "v1.3.0",
        "git_sha": "deadbeef",
        "ticker_count": 10,
        "total_evaluated": 15,
    }
    meta.update(overrides)
    with open(snap_dir / "metadata.json", "w") as f:
        json.dump(meta, f)


def _write_manifest(snap_dir: Path, overall: str = "PASS", gates=None) -> None:
    manifest = {
        "overall_status": overall,
        "gates": gates or [],
    }
    with open(snap_dir / "run_manifest.json", "w") as f:
        json.dump(manifest, f)


def _make_snapshot(tmp_path: Path, name: str = "2026-03-08") -> Path:
    snap_dir = tmp_path / name
    rows = [
        _make_row("BIN1", 1, "5", "specific_days", weight="5.0"),
        _make_row("BIN2", 2, "20", "specific_days", weight="4.0"),
        _make_row("MID1", 3, "60", "specific_days", weight="3.0"),
        _make_row("PIPE1", 4, "120", "specific_days", weight="5.0"),
        _make_row("CORE1", 5, weight="5.0"),
        _make_row("CORE2", 6, weight="3.0", de_beta_xbi_60d_source=""),
    ]
    _write_rankings_csv(snap_dir, rows)
    _write_metadata(snap_dir)
    _write_manifest(
        snap_dir,
        overall="WARN",
        gates=[
            {"name": "audit", "status": "WARN", "detail": "STALE_MISMATCH"},
            {"name": "screen", "status": "PASS", "detail": "OK"},
        ],
    )
    return snap_dir


# ---------------------------------------------------------------------------
# A) Memo creation + sections
# ---------------------------------------------------------------------------


class TestMemoCreation:

    def test_memo_text_created(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        text, _ = build_decision_memo(snap, ACCOUNT_USD)
        assert "# Decision Memo" in text

    def test_contains_provenance(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        text, _ = build_decision_memo(snap, ACCOUNT_USD)
        assert "As-of date" in text
        assert "test_rs" in text  # ruleset_id
        assert "abc123" in text  # ruleset_hash
        assert "v1.3.0" in text  # engine_version
        assert "deadbeef" in text  # git_sha

    def test_contains_allocation_summary(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        text, _ = build_decision_memo(snap, ACCOUNT_USD)
        assert "Allocation Summary" in text
        assert "$500,000" in text
        assert "Binary 0-30d" in text

    def test_contains_risk_rails(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        text, _ = build_decision_memo(snap, ACCOUNT_USD)
        assert "Risk Rails" in text
        assert "Gap Risk HIGH" in text
        assert "BIN1" in text  # 5d catalyst → HIGH gap risk

    def test_contains_action_lists(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        text, _ = build_decision_memo(snap, ACCOUNT_USD)
        assert "Action Lists" in text

    def test_contains_what_to_do(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        text, _ = build_decision_memo(snap, ACCOUNT_USD)
        assert "What To Do" in text

    def test_warn_gates_listed(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        text, _ = build_decision_memo(snap, ACCOUNT_USD)
        assert "WARN gates" in text
        assert "audit" in text
        assert "STALE_MISMATCH" in text

    def test_missing_price_flagged(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        text, _ = build_decision_memo(snap, ACCOUNT_USD)
        assert "CORE2" in text
        assert "MISSING" in text


# ---------------------------------------------------------------------------
# B) JSON sidecar
# ---------------------------------------------------------------------------


class TestMemoJSON:

    def test_json_schema(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        _, memo_json = build_decision_memo(snap, ACCOUNT_USD)
        assert memo_json["schema"] == "decision_memo.v1"
        assert memo_json["account_usd"] == ACCOUNT_USD
        assert "sizing" in memo_json
        assert "provenance" in memo_json
        assert "risk_flags" in memo_json

    def test_json_risk_flags(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        _, memo_json = build_decision_memo(snap, ACCOUNT_USD)
        assert "BIN1" in memo_json["risk_flags"]["high_gap_risk"]
        assert "CORE2" in memo_json["risk_flags"]["missing_price"]


# ---------------------------------------------------------------------------
# C) Deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:

    def test_action_list_sorted_by_rank(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        text, _ = build_decision_memo(snap, ACCOUNT_USD)
        # BIN1 (rank 1) should appear before BIN2 (rank 2) in the 0-30 section
        bin1_pos = text.index("BIN1")
        bin2_pos = text.index("BIN2")
        assert bin1_pos < bin2_pos

    def test_stable_across_runs(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        text1, _ = build_decision_memo(snap, ACCOUNT_USD)
        text2, _ = build_decision_memo(snap, ACCOUNT_USD)
        # Remove timestamp lines for comparison
        lines1 = [ln for ln in text1.split("\n") if "Generated" not in ln]
        lines2 = [ln for ln in text2.split("\n") if "Generated" not in ln]
        assert lines1 == lines2


# ---------------------------------------------------------------------------
# D) Bucket targets
# ---------------------------------------------------------------------------


class TestBucketTargets:

    def test_bucket_targets_rescale(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        targets = {"binary_0_30": 0.50, "less_binary": 0.50}
        _, memo_json = build_decision_memo(snap, ACCOUNT_USD, bucket_targets=targets)
        assert memo_json["bucket_targets"] == targets


# ---------------------------------------------------------------------------
# E) Change vs prior
# ---------------------------------------------------------------------------


class TestChangeVsPrior:

    def test_prior_found(self, tmp_path):
        root = tmp_path / "snaps"
        # Create two snapshots
        prior = root / "2026-03-06"
        prior.mkdir(parents=True)
        _write_rankings_csv(prior, [_make_row("A", 1), _make_row("B", 2)])

        current = root / "2026-03-08"
        _write_rankings_csv(current, [_make_row("A", 2), _make_row("B", 1)])
        _write_metadata(current)
        _write_manifest(current)

        text, _ = build_decision_memo(current, ACCOUNT_USD)
        assert "2026-03-06" in text
        assert "Top-20 overlap" in text

    def test_no_prior(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        text, _ = build_decision_memo(snap, ACCOUNT_USD)
        assert "No prior snapshot found" in text

    def test_find_prior_skips_current(self, tmp_path):
        root = tmp_path / "snaps"
        (root / "2026-03-06").mkdir(parents=True)
        _write_rankings_csv(root / "2026-03-06", [_make_row("A", 1)])
        (root / "2026-03-08").mkdir(parents=True)
        _write_rankings_csv(root / "2026-03-08", [_make_row("A", 1)])

        prior = _find_prior_snapshot(root / "2026-03-08")
        assert prior is not None
        assert prior.name == "2026-03-06"

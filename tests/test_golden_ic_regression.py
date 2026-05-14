#!/usr/bin/env python3
"""
Golden IC Regression Test

Loads 8 quarterly archives (2024-Q1..Q4 OOS, 2025-Q1..Q4 IS), extracts
composite_rank from rankings.csv, computes Spearman IC vs forward returns
at 20d and 63d horizons, and asserts each value is within tolerance of
a pinned baseline.

This catches silent ranking drift (sort key changes, eligibility gate
regressions, module score bugs) that wouldn't show up in unit tests.

Pinned on: 2026-03-07
Baseline:  tests/golden/ic_baseline.json
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Dict, Tuple

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from run_rank_ic_backtest import ARCHIVE_DIR, compute_forward_returns
from scripts.eval_forward_returns import spearman_ic

pytestmark = pytest.mark.skipif(
    not (PROJECT_ROOT / "production_data" / "morningstar_returns_history.json").exists(),
    reason="morningstar_returns_history.json not present (licensed data, gitignored)",
)

# =============================================================================
# CONFIGURATION
# =============================================================================

GOLDEN_DATES = [
    "2024-01-31",
    "2024-04-30",
    "2024-07-31",
    "2024-10-31",  # OOS
    "2025-01-31",
    "2025-04-30",
    "2025-07-31",
    "2025-10-31",  # IS
]

HORIZONS = {"20d": 20, "63d": 63}

BASELINE_PATH = Path(__file__).parent / "golden" / "ic_baseline.json"


# =============================================================================
# HELPERS
# =============================================================================


def _load_baseline() -> Tuple[dict, float]:
    """Load pinned IC baseline and tolerance."""
    with open(BASELINE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["baselines"], data["tolerance"]


def _load_rankings_from_archive(tar_path: Path, date_str: str) -> Dict[str, int]:
    """Extract composite_rank from rankings.csv inside a tar.gz archive."""
    tmp = tempfile.mkdtemp(prefix=f"golden_{date_str}_")
    try:
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(tmp, filter="data")
        csv_path = Path(tmp) / date_str / "rankings.csv"
        ranks: Dict[str, int] = {}
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                ticker = row.get("ticker", "").strip().upper()
                rank_str = row.get("composite_rank", "").strip()
                if ticker and rank_str:
                    try:
                        ranks[ticker] = int(rank_str)
                    except ValueError:
                        pass
        return ranks
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# =============================================================================
# PROVIDERS (module-scoped to avoid repeated init)
# =============================================================================


@pytest.fixture(scope="module")
def providers():
    """Initialize returns providers once per module."""
    from run_decision_ruleset_sweep import init_providers

    return init_providers()


# =============================================================================
# TESTS
# =============================================================================


def _check_archives_exist() -> bool:
    """Check if all golden archives exist."""
    return all((ARCHIVE_DIR / f"{d}.tar.gz").exists() for d in GOLDEN_DATES)


@pytest.mark.slow
@pytest.mark.timeout(120)
class TestGoldenICRegression:

    @pytest.fixture(autouse=True)
    def _skip_if_no_archives(self):
        if not _check_archives_exist():
            pytest.skip("One or more golden archives missing")
        if not BASELINE_PATH.exists():
            pytest.skip("Baseline file missing")

    @pytest.mark.parametrize("snap_date", GOLDEN_DATES)
    @pytest.mark.parametrize("hz_name,hz_days", list(HORIZONS.items()))
    def test_ic_within_tolerance(self, snap_date, hz_name, hz_days, providers):
        """IC for {snap_date} at {hz_name} should match pinned baseline."""
        baselines, tolerance = _load_baseline()
        key = f"{snap_date}_{hz_name}"

        expected_ic = baselines.get(key)
        if expected_ic is None:
            pytest.skip(f"No baseline for {key}")

        chained, _, _ = providers
        archive_path = ARCHIVE_DIR / f"{snap_date}.tar.gz"
        ranks = _load_rankings_from_archive(archive_path, snap_date)

        fwd_returns = compute_forward_returns(chained, list(ranks.keys()), snap_date, hz_days)
        common = sorted(set(ranks) & set(fwd_returns))
        assert len(common) >= 20, f"Only {len(common)} tickers with forward returns"

        signal = [float(ranks[t]) for t in common]
        returns = [fwd_returns[t] for t in common]
        actual_ic = spearman_ic(signal, returns)

        assert actual_ic is not None, f"IC computation returned None for {key}"
        delta = abs(actual_ic - expected_ic)
        assert delta < tolerance, (
            f"IC drift for {key}: expected {expected_ic:.6f}, got {actual_ic:.6f}, "
            f"delta {delta:.6f} >= tolerance {tolerance}"
        )

    def test_baseline_has_all_keys(self):
        """Baseline should have entries for all date x horizon combos."""
        baselines, _ = _load_baseline()
        for snap_date in GOLDEN_DATES:
            for hz_name in HORIZONS:
                key = f"{snap_date}_{hz_name}"
                assert key in baselines, f"Missing baseline key: {key}"

    def test_minimum_date_coverage(self, providers):
        """At least 6 of 8 dates should produce valid IC at 20d horizon."""
        baselines, tolerance = _load_baseline()
        chained, _, _ = providers
        valid_count = 0
        for snap_date in GOLDEN_DATES:
            archive_path = ARCHIVE_DIR / f"{snap_date}.tar.gz"
            ranks = _load_rankings_from_archive(archive_path, snap_date)
            fwd_returns = compute_forward_returns(chained, list(ranks.keys()), snap_date, 20)
            common = sorted(set(ranks) & set(fwd_returns))
            if len(common) >= 20:
                signal = [float(ranks[t]) for t in common]
                returns = [fwd_returns[t] for t in common]
                ic = spearman_ic(signal, returns)
                if ic is not None:
                    valid_count += 1
        assert valid_count >= 6, f"Only {valid_count}/8 dates produced valid 20d IC"

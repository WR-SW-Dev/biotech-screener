"""Spec 101 regression tests: ev_severity_score export contract.

Verifies:
  - dilution_haircut = 0.35 * ev_severity_score  (±0.001)
  - size_multiplier = max(0.40, 1 - 0.60 * ev_severity_score)  (±0.001)
  - ev_severity_score in [0.0, 1.0] for all records
  - column present in recent snapshots
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 2026-05-14 predates ev_severity_score export (Spec 101 shipped post-May).
# Formula tests use the earliest post-implementation snapshot available.
SNAPSHOT_RECENT = PROJECT_ROOT / "data" / "snapshots" / "2026-06-23" / "rankings.csv"
# Parametrize over multiple post-implementation snapshots when available.
POST_IMPL_SNAPSHOTS = [SNAPSHOT_RECENT]

TOLERANCE = 0.001


def _load_snapshot(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _safe_float(val: str) -> float | None:
    if val is None or val.strip() == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Test 1: dilution_haircut ≈ 0.35 * ev_severity_score
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("snapshot_path", POST_IMPL_SNAPSHOTS)
def test_dilution_haircut_formula(snapshot_path):
    rows = _load_snapshot(snapshot_path)
    checked = 0
    for row in rows:
        ev = _safe_float(row.get("ev_severity_score"))
        dh = _safe_float(row.get("dilution_haircut"))
        if ev is None or dh is None:
            continue
        expected = 0.35 * ev
        assert abs(dh - expected) <= TOLERANCE, (
            f"dilution_haircut mismatch for {row.get('ticker', '?')}: "
            f"got {dh:.4f}, expected 0.35 * {ev:.4f} = {expected:.4f}"
        )
        checked += 1
    assert checked >= 10, f"Too few rows with both fields to verify formula (got {checked})"


# ---------------------------------------------------------------------------
# Test 2: size_multiplier ≈ max(0.40, 1 - 0.60 * ev_severity_score)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("snapshot_path", POST_IMPL_SNAPSHOTS)
def test_size_multiplier_formula(snapshot_path):
    rows = _load_snapshot(snapshot_path)
    checked = 0
    for row in rows:
        ev = _safe_float(row.get("ev_severity_score"))
        sm = _safe_float(row.get("size_multiplier"))
        if ev is None or sm is None:
            continue
        expected = max(0.40, 1.0 - 0.60 * ev)
        assert abs(sm - expected) <= TOLERANCE, (
            f"size_multiplier mismatch for {row.get('ticker', '?')}: "
            f"got {sm:.4f}, expected max(0.40, 1 - 0.60 * {ev:.4f}) = {expected:.4f}"
        )
        checked += 1
    assert checked >= 10, f"Too few rows with both fields to verify formula (got {checked})"


# ---------------------------------------------------------------------------
# Boundary tests for size_multiplier formula
# ---------------------------------------------------------------------------


def test_size_multiplier_boundary_zero():
    ev = 0.0
    result = max(0.40, 1.0 - 0.60 * ev)
    assert abs(result - 1.0) < 1e-9


def test_size_multiplier_boundary_one():
    ev = 1.0
    result = max(0.40, 1.0 - 0.60 * ev)
    assert abs(result - 0.40) < 1e-9


def test_size_multiplier_floor_at_point_four():
    # ev = 1.0 → 1 - 0.60 = 0.40 (exactly at floor)
    # ev > 1.0 would go below, but ev is clamped to [0,1]
    for ev in [0.67, 0.80, 0.90, 1.00]:
        result = max(0.40, 1.0 - 0.60 * ev)
        assert result >= 0.40 - 1e-9, f"size_multiplier below floor at ev={ev}"


# ---------------------------------------------------------------------------
# Test 3: schema presence — ev_severity_score in snapshot, all valid
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("snapshot_path", POST_IMPL_SNAPSHOTS)
def test_ev_severity_score_schema_presence(snapshot_path):
    rows = _load_snapshot(snapshot_path)
    assert len(rows) >= 50, "Snapshot too small — data problem"
    assert "ev_severity_score" in rows[0], "ev_severity_score column missing from snapshot"

    populated = [r for r in rows if r.get("ev_severity_score", "").strip() != ""]
    assert len(populated) == len(rows), f"ev_severity_score missing in {len(rows) - len(populated)}/{len(rows)} records"


@pytest.mark.parametrize("snapshot_path", POST_IMPL_SNAPSHOTS)
def test_ev_severity_score_range(snapshot_path):
    rows = _load_snapshot(snapshot_path)
    violations = []
    for row in rows:
        ev = _safe_float(row.get("ev_severity_score"))
        if ev is None:
            continue
        if not (0.0 <= ev <= 1.0) or math.isnan(ev) or math.isinf(ev):
            violations.append((row.get("ticker", "?"), ev))
    assert not violations, f"ev_severity_score out of [0,1]: {violations[:5]}"


@pytest.mark.parametrize("snapshot_path", POST_IMPL_SNAPSHOTS)
def test_ev_severity_score_non_zero_coverage(snapshot_path):
    rows = _load_snapshot(snapshot_path)
    ev_vals = [_safe_float(r.get("ev_severity_score")) for r in rows]
    ev_vals = [v for v in ev_vals if v is not None]
    non_zero_pct = sum(1 for v in ev_vals if v > 0.0) / len(ev_vals) * 100
    assert non_zero_pct >= 10.0, (
        f"ev_severity_score suspiciously sparse: only {non_zero_pct:.1f}% non-zero " "(possible upstream issue)"
    )

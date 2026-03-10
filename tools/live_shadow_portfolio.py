#!/usr/bin/env python3
"""Live Shadow Portfolio — point-in-time position ledger + performance tracker.

Reads a promoted snapshot and portfolio policy, then:
  1. Selects top-K names per bucket respecting policy caps
  2. Writes a PIT positions artifact (tickers, weights, $, bucket, risk flags)
  3. Computes performance vs prior positions using price_history.csv
  4. Appends to an append-only performance.csv
  5. Generates a weekly summary markdown

Output:
    artifacts/live_shadow/positions/YYYY-MM-DD.json
    artifacts/live_shadow/performance.csv           (append-only)
    artifacts/live_shadow/weekly_summary.md          (overwritten each run)

Usage:
    python3 tools/live_shadow_portfolio.py --as-of-date 2026-03-08
    python3 tools/live_shadow_portfolio.py --as-of-date 2026-03-08 --policy production_data/portfolio_policy.json
    python3 tools/live_shadow_portfolio.py --as-of-date 2026-03-08 --account-usd 500000
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_action_lists import classify_action_bucket

SNAPSHOTS_ROOT = PROJECT_ROOT / "data" / "snapshots"
SHADOW_ROOT = PROJECT_ROOT / "artifacts" / "live_shadow"
POSITIONS_DIR = SHADOW_ROOT / "positions"
PERFORMANCE_CSV = SHADOW_ROOT / "performance.csv"
WEEKLY_SUMMARY = SHADOW_ROOT / "weekly_summary.md"
DEFAULT_POLICY_PATH = PROJECT_ROOT / "production_data" / "portfolio_policy.json"
PRICE_HISTORY_PATH = PROJECT_ROOT / "production_data" / "price_history.csv"

SCHEMA_VERSION = "live_shadow_positions.v1"
PERF_SCHEMA_VERSION = "live_shadow_perf.v1"

# Production-path constants for guard checks
_PRODUCTION_PATHS = {
    "out_dir": POSITIONS_DIR,
    "positions_dir": POSITIONS_DIR,
    "perf_csv": PERFORMANCE_CSV,
    "out_path": WEEKLY_SUMMARY,
    "price_path": PRICE_HISTORY_PATH,
    "shadow_root": SHADOW_ROOT,
}


def _assert_not_production_default(name: str, value: Path, production_default: Path) -> None:
    """Raise AssertionError if a test uses a production default path.

    Only active when PYTEST_CURRENT_TEST is set; no-op in production.
    """
    if "PYTEST_CURRENT_TEST" in os.environ and value == production_default:
        raise AssertionError(f"Tests must pass `{name}` explicitly — got production default {production_default}")


# Bucket display names (same as action lists)
BUCKET_DISPLAY = {
    "binary_0_30": "Binary 0-30d",
    "binary_31_90": "Binary 31-90d",
    "binary_91_180": "Binary 91-180d",
    "less_binary": "Less Binary",
}

BUCKET_NAMES = ["binary_0_30", "binary_31_90", "binary_91_180", "less_binary"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _sort_key(row: Dict[str, str]) -> Tuple[float, str]:
    rank = _safe_float(row.get("actionable_rank", ""), 9999.0)
    return (rank, row.get("ticker", ""))


# ---------------------------------------------------------------------------
# Policy loading
# ---------------------------------------------------------------------------


def load_policy(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load portfolio policy JSON. Returns defaults if file not found."""
    p = path or DEFAULT_POLICY_PATH
    if p.is_file():
        with open(p) as f:
            return json.load(f)
    # Sensible defaults
    return {
        "schema": "portfolio_policy.v1",
        "account_usd": 500_000,
        "bucket_targets": {
            "binary_91_180": 0.55,
            "binary_31_90": 0.25,
            "binary_0_30": 0.10,
            "less_binary": 0.10,
        },
        "bucket_top_k": {
            "binary_91_180": 20,
            "binary_31_90": 15,
            "binary_0_30": 10,
            "less_binary": 15,
        },
        "bucket_name_caps": {
            "binary_91_180": 3.0,
            "binary_31_90": 2.0,
            "binary_0_30": 1.0,
            "less_binary": 2.0,
        },
        "family_overrides": {},
        "family_targets": {},
        "family_filter_mode": "primary",
        "gap_risk": {"high_days": 7, "high_cap_pct": 0.5},
        "regulatory_ladder_enabled": False,
        "regulatory_day_buckets": DEFAULT_REG_DAY_BUCKETS,
        "regulatory_bucket_caps_pct": {},
        "regulatory_bucket_weights": {},
        "regulatory_quality_tilt_enabled": False,
        "regulatory_quality_clip_lo": 0.30,
        "regulatory_quality_clip_hi": 1.00,
        "regulatory_resolution_enabled": False,
        "rebalance_buffer_ranks": 30,
        "bucket_hysteresis_days": 7,
    }


# ---------------------------------------------------------------------------
# Snapshot reading
# ---------------------------------------------------------------------------


def load_rankings(snap_dir: Path) -> List[Dict[str, str]]:
    """Load rankings.csv from snapshot, return eligible rows sorted by rank."""
    csv_path = snap_dir / "rankings.csv"
    if not csv_path.is_file():
        raise FileNotFoundError(f"rankings.csv not found in {snap_dir}")
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    eligible = [r for r in rows if r.get("eligible") == "1"]
    eligible.sort(key=_sort_key)
    return eligible


def load_metadata(snap_dir: Path) -> Dict[str, Any]:
    meta_path = snap_dir / "metadata.json"
    if meta_path.is_file():
        with open(meta_path) as f:
            return json.load(f)
    return {}


# ---------------------------------------------------------------------------
# Portfolio construction (policy-driven)
# ---------------------------------------------------------------------------


# Regulatory time-ladder sub-buckets
REG_LADDER_NAMES = ["reg_0_14", "reg_15_45", "reg_46_90", "reg_91_180"]

REG_LADDER_DISPLAY = {
    "reg_0_14": "Reg 0-14d",
    "reg_15_45": "Reg 15-45d",
    "reg_46_90": "Reg 46-90d",
    "reg_91_180": "Reg 91-180d",
}

# Default ladder boundaries (upper bounds)
DEFAULT_REG_DAY_BUCKETS = [14, 45, 90, 180]


def _reg_sub_bucket(regulatory_days: str) -> str:
    """Classify a regulatory position into a ladder sub-bucket.

    Uses regulatory_days (not catalyst_days) to place the name.
    Returns one of REG_LADDER_NAMES or '' if not classifiable.
    """
    try:
        days = float(regulatory_days)
    except (ValueError, TypeError):
        return ""
    if days <= 0:
        return ""
    if days <= 14:
        return "reg_0_14"
    if days <= 45:
        return "reg_15_45"
    if days <= 90:
        return "reg_46_90"
    if days <= 180:
        return "reg_91_180"
    return ""


def _is_regulatory_resolved(row: Dict[str, str]) -> bool:
    """Check if a regulatory catalyst has resolved (event date passed).

    A REGULATORY name is RESOLVED when regulatory_days <= 0, meaning
    the event date is today or in the past. These names should be demoted
    to 0% target at the next rebalance.
    """
    rd = row.get("regulatory_days", "")
    if not rd:
        return False
    try:
        return float(rd) <= 0
    except (ValueError, TypeError):
        return False


def _apply_gap_risk(
    wt: float,
    row: Dict[str, str],
    bucket_name: str,
    gap_high_days: float,
    gap_high_cap: float,
) -> Tuple[float, str]:
    """Apply gap-risk cap for binary_0_30. Returns (capped_wt, gap_risk_label)."""
    if bucket_name != "binary_0_30":
        return wt, ""
    cat_days = _safe_float(row.get("catalyst_days", ""), float("inf"))
    cat_mode = (row.get("catalyst_mode") or "").strip().lower()
    if cat_mode in ("specific_days", "blended_window"):
        if cat_days <= gap_high_days:
            return min(wt, gap_high_cap), "HIGH"
        if cat_days <= 30:
            return wt, "MODERATE"
    return wt, ""


def _make_position(
    row: Dict[str, str],
    bucket_name: str,
    fam: str,
    wt: float,
    gap_risk: str,
    source: str,
    acct: float,
    is_secondary_reg: bool,
    reg_sub: str = "",
) -> Dict[str, Any]:
    """Build a position dict from a ranking row."""
    return {
        "ticker": row.get("ticker", ""),
        "bucket": bucket_name,
        "catalyst_family": fam,
        "effective_family": fam,
        "actionable_rank": int(_safe_float(row.get("actionable_rank", ""), 9999)),
        "tier": row.get("tier_any", ""),
        "size_band": row.get("size_band", ""),
        "catalyst_days": row.get("catalyst_days", ""),
        "catalyst_mode": row.get("catalyst_mode", ""),
        "mom_state": row.get("mom_state", ""),
        "weight_pct": round(wt, 4),
        "target_dollars": round(acct * wt / 100.0, 2),
        "gap_risk": gap_risk,
        "price_coverage": "OK" if source else "MISSING",
        "regulatory_days": row.get("regulatory_days", ""),
        "regulatory_event_type": row.get("regulatory_event_type", ""),
        "has_regulatory_upcoming_180d": row.get("has_regulatory_upcoming_180d", "0"),
        "regulatory_quality": row.get("regulatory_quality", "0"),
        "regulatory_is_secondary": is_secondary_reg,
        "reg_sub_bucket": reg_sub,
    }


def _effective_family(row: Dict[str, str], mode: str = "primary") -> str:
    """Determine effective catalyst family for a row.

    In 'secondary' mode, a ticker with has_regulatory_upcoming_180d=1 is
    treated as REGULATORY even if its primary (nearest) catalyst is clinical.
    """
    if mode == "secondary" and row.get("has_regulatory_upcoming_180d") == "1":
        return "REGULATORY"
    return (row.get("catalyst_family") or "OTHER").upper() or "OTHER"


def _quality_weights(
    rows: List[Dict[str, str]],
    q_lo: float = 0.30,
    q_hi: float = 1.00,
) -> List[float]:
    """Compute quality-proportional weights for a list of rows.

    Reads ``regulatory_quality`` from each row, clips to [q_lo, q_hi],
    and returns normalized weights that sum to 1.0.  If all qualities are
    zero/missing, falls back to equal weight.
    """
    raw = []
    for row in rows:
        q = _safe_float(row.get("regulatory_quality", ""), 0.0)
        raw.append(max(q_lo, min(q, q_hi)))
    total = sum(raw)
    if total <= 0:
        n = len(rows)
        return [1.0 / n] * n
    return [r / total for r in raw]


def _allocate_sub_bucket_quality(
    sb_rows: List[Dict[str, str]],
    sb_frac: float,
    cap: float,
    bucket_name: str,
    gap_high_days: float,
    gap_high_cap: float,
    acct: float,
    sb: str,
    quality_tilt: bool,
    q_lo: float,
    q_hi: float,
) -> List[Dict[str, Any]]:
    """Allocate within one ladder sub-bucket, optionally quality-weighted.

    When quality_tilt is True, dollars are proportional to clipped
    regulatory_quality.  Cap-overflow is redistributed to uncapped names
    in the same sub-bucket (up to 3 reflow passes to converge).
    """
    fn = len(sb_rows)
    if fn == 0:
        return []

    budget_pct = sb_frac * 100.0

    if quality_tilt:
        q_weights = _quality_weights(sb_rows, q_lo, q_hi)
    else:
        q_weights = [1.0 / fn] * fn

    # Iterative cap-overflow reflow (converges in ≤ fn passes)
    assigned = [0.0] * fn
    capped = [False] * fn
    remaining_budget = budget_pct
    for _ in range(fn + 1):
        uncapped_indices = [i for i in range(fn) if not capped[i]]
        if not uncapped_indices:
            break
        uc_total_q = sum(q_weights[i] for i in uncapped_indices)
        if uc_total_q <= 0:
            break
        overflow = 0.0
        for i in uncapped_indices:
            share = (q_weights[i] / uc_total_q) * remaining_budget
            if share > cap:
                assigned[i] = cap
                overflow += share - cap
                capped[i] = True
            else:
                assigned[i] = share
        if overflow <= 0:
            break
        # Recalculate remaining budget for uncapped names
        remaining_budget = sum(assigned[i] for i in range(fn) if not capped[i]) + overflow
        # Reset uncapped assignments so next pass re-distributes
        for i in range(fn):
            if not capped[i]:
                assigned[i] = 0.0

    result: List[Dict[str, Any]] = []
    for i, row in enumerate(sb_rows):
        wt = assigned[i]
        wt, gap_risk = _apply_gap_risk(wt, row, bucket_name, gap_high_days, gap_high_cap)
        source = (row.get("de_beta_xbi_60d_source") or "").strip()
        is_secondary_reg = (
            row.get("has_regulatory_upcoming_180d") == "1"
            and (row.get("catalyst_family") or "").upper() != "REGULATORY"
        )
        result.append(
            _make_position(
                row,
                bucket_name,
                "REGULATORY",
                wt,
                gap_risk,
                source,
                acct,
                is_secondary_reg,
                reg_sub=sb,
            )
        )
    return result


def _allocate_regulatory_ladder(
    reg_rows: List[Dict[str, str]],
    fam_frac: float,
    eff_cap: float,
    bucket_name: str,
    gap_high_days: float,
    gap_high_cap: float,
    acct: float,
    ladder_caps: Dict[str, float],
    bucket_ladder_weights: Dict[str, float],
    quality_tilt: bool = False,
    quality_clip_lo: float = 0.30,
    quality_clip_hi: float = 1.00,
) -> List[Dict[str, Any]]:
    """Allocate REGULATORY family budget across time-ladder sub-buckets.

    Each reg row is placed into reg_0_14 / reg_15_45 / reg_46_90 / reg_91_180
    based on regulatory_days. Budget is split by bucket_ladder_weights (or equal
    if absent). Unused sub-bucket share reflows in priority order:
    reg_15_45 → reg_46_90 → reg_91_180 → reg_0_14.

    When quality_tilt=True, within-sub-bucket allocation is proportional to
    regulatory_quality (clipped to [quality_clip_lo, quality_clip_hi]).
    """
    REFLOW_PRIORITY = ["reg_15_45", "reg_46_90", "reg_91_180", "reg_0_14"]

    # Classify rows into sub-buckets
    by_sub: Dict[str, List[Dict[str, str]]] = {sb: [] for sb in REG_LADDER_NAMES}
    unclassified: List[Dict[str, str]] = []
    for row in reg_rows:
        rd = row.get("regulatory_days", "")
        sb = _reg_sub_bucket(rd)
        if sb:
            by_sub[sb].append(row)
        else:
            unclassified.append(row)

    # Compute target weight per sub-bucket
    if bucket_ladder_weights:
        sub_targets = {sb: bucket_ladder_weights.get(sb, 0) for sb in REG_LADDER_NAMES}
    else:
        # Equal weight across sub-buckets that have names
        active_subs = [sb for sb in REG_LADDER_NAMES if by_sub[sb]]
        n_active = len(active_subs)
        sub_targets = {sb: (1.0 / n_active if sb in active_subs else 0) for sb in REG_LADDER_NAMES}

    # Reflow: move inactive sub-bucket share to active ones in priority order
    inactive_share = 0.0
    for sb in REG_LADDER_NAMES:
        if not by_sub[sb] and sub_targets[sb] > 0:
            inactive_share += sub_targets[sb]
            sub_targets[sb] = 0

    if inactive_share > 0:
        for sb in REFLOW_PRIORITY:
            if by_sub[sb] and sub_targets[sb] > 0:
                sub_targets[sb] += inactive_share
                inactive_share = 0
                break
        if inactive_share > 0:
            active_subs = [sb for sb in REG_LADDER_NAMES if by_sub[sb]]
            if active_subs:
                per = inactive_share / len(active_subs)
                for sb in active_subs:
                    sub_targets[sb] += per

    # Allocate within each sub-bucket (quality-weighted or equal)
    result: List[Dict[str, Any]] = []
    for sb in REG_LADDER_NAMES:
        sb_rows = by_sub[sb]
        sb_share = sub_targets.get(sb, 0)
        if not sb_rows or sb_share <= 0:
            continue
        sb_frac = fam_frac * sb_share
        ladder_cap = ladder_caps.get(sb)
        cap = min(eff_cap, ladder_cap) if ladder_cap is not None else eff_cap
        result.extend(
            _allocate_sub_bucket_quality(
                sb_rows,
                sb_frac,
                cap,
                bucket_name,
                gap_high_days,
                gap_high_cap,
                acct,
                sb,
                quality_tilt,
                quality_clip_lo,
                quality_clip_hi,
            )
        )

    # Unclassified regulatory names (no regulatory_days): flat allocation from residual
    if unclassified:
        total_allocated_pct = sum(p["weight_pct"] for p in result)
        remaining_pct = max(0, fam_frac * 100.0 - total_allocated_pct)
        if remaining_pct > 0:
            fn = len(unclassified)
            equal_wt = remaining_pct / fn
            for row in unclassified:
                wt = min(equal_wt, eff_cap)
                wt, gap_risk = _apply_gap_risk(wt, row, bucket_name, gap_high_days, gap_high_cap)
                source = (row.get("de_beta_xbi_60d_source") or "").strip()
                is_secondary_reg = (
                    row.get("has_regulatory_upcoming_180d") == "1"
                    and (row.get("catalyst_family") or "").upper() != "REGULATORY"
                )
                result.append(
                    _make_position(
                        row,
                        bucket_name,
                        "REGULATORY",
                        wt,
                        gap_risk,
                        source,
                        acct,
                        is_secondary_reg,
                    )
                )

    return result


def build_positions(
    rankings: List[Dict[str, str]],
    policy: Dict[str, Any],
    account_usd: Optional[float] = None,
) -> Dict[str, Any]:
    """Select top-K per bucket, apply caps, compute $ sizing.

    Supports family-targeted allocation via ``family_targets`` in policy:
    each bucket can specify a dollar-weight split by family (e.g.
    ``{"REGULATORY": 0.70, "CLINICAL": 0.30}``).  When a family has
    fewer names than its allocation allows, unused dollars reflow to
    other families in the same bucket (no cash drag).

    Returns a dict with:
        positions: list of position dicts
        summary: allocation summary
    """
    acct = account_usd or policy.get("account_usd", 500_000)
    bucket_targets = policy.get("bucket_targets", {})
    bucket_top_k = policy.get("bucket_top_k", {})
    bucket_name_caps = policy.get("bucket_name_caps", {})
    family_overrides = policy.get("family_overrides", {})
    family_targets = policy.get("family_targets", {})
    family_mode = policy.get("family_filter_mode", "primary")
    gap_cfg = policy.get("gap_risk", {})
    gap_high_days = gap_cfg.get("high_days", 7)
    gap_high_cap = gap_cfg.get("high_cap_pct", 0.5)
    ladder_enabled = policy.get("regulatory_ladder_enabled", False)
    ladder_caps = policy.get("regulatory_bucket_caps_pct", {})
    ladder_weights = policy.get("regulatory_bucket_weights", {})
    quality_tilt = policy.get("regulatory_quality_tilt_enabled", False)
    quality_clip_lo = policy.get("regulatory_quality_clip_lo", 0.30)
    quality_clip_hi = policy.get("regulatory_quality_clip_hi", 1.00)
    resolution_enabled = policy.get("regulatory_resolution_enabled", False)

    # Classify into buckets, compute effective family
    buckets: Dict[str, List[Dict[str, str]]] = {b: [] for b in BUCKET_NAMES}
    resolved_rows: List[Dict[str, str]] = []
    for row in rankings:
        bucket = classify_action_bucket(row)
        # Stamp effective_family for downstream use
        row["_effective_family"] = _effective_family(row, family_mode)
        # Filter resolved regulatory names (event date passed)
        if resolution_enabled and row["_effective_family"] == "REGULATORY" and _is_regulatory_resolved(row):
            resolved_rows.append(row)
            continue
        buckets[bucket].append(row)

    # Select top-K per bucket, respecting family-level max_k limits
    selected: Dict[str, List[Dict[str, str]]] = {}
    for bucket_name in BUCKET_NAMES:
        k = bucket_top_k.get(bucket_name, 20)
        bucket_rows = buckets[bucket_name][:k]
        fam_cfg = family_overrides.get(bucket_name, {})
        if fam_cfg:
            # Apply per-family max_k: group by effective family, cap each
            by_family: Dict[str, List[Dict[str, str]]] = {}
            for row in bucket_rows:
                fam = row["_effective_family"]
                by_family.setdefault(fam, []).append(row)
            capped: List[Dict[str, str]] = []
            for fam, fam_rows in by_family.items():
                fam_k = fam_cfg.get(fam, {}).get("max_k")
                if fam_k is not None:
                    fam_rows = fam_rows[:fam_k]
                capped.extend(fam_rows)
            capped.sort(
                key=lambda r: (
                    _safe_float(r.get("actionable_rank", ""), 9999),
                    r.get("ticker", ""),
                )
            )
            selected[bucket_name] = capped
        else:
            selected[bucket_name] = bucket_rows

    # Compute target weight per position
    positions = []
    for bucket_name in BUCKET_NAMES:
        target_frac = bucket_targets.get(bucket_name, 0.25)
        bucket_cap = bucket_name_caps.get(bucket_name, 5.0)
        fam_cfg = family_overrides.get(bucket_name, {})
        fam_tgt = family_targets.get(bucket_name, {})
        rows = selected[bucket_name]
        n = len(rows)
        if n == 0:
            continue

        if fam_tgt:
            # --- Family-targeted allocation ---
            # Group rows by effective family
            by_family: Dict[str, List[Dict[str, str]]] = {}
            for row in rows:
                fam = row["_effective_family"]
                by_family.setdefault(fam, []).append(row)

            # Compute per-family budget as fraction of bucket allocation
            # Reflow: if a targeted family has 0 names, redistribute its
            # share proportionally to families that have names.
            active_targets: Dict[str, float] = {}
            inactive_share = 0.0
            for fam_name, fam_share in fam_tgt.items():
                if by_family.get(fam_name):
                    active_targets[fam_name] = fam_share
                else:
                    inactive_share += fam_share
            # Names in families not listed in targets get the residual
            unlisted_fams = [f for f in by_family if f not in fam_tgt]
            residual = 1.0 - sum(fam_tgt.values())
            if unlisted_fams:
                for f in unlisted_fams:
                    active_targets[f] = residual / len(unlisted_fams)
            # Redistribute inactive share proportionally
            if inactive_share > 0 and active_targets:
                total_active = sum(active_targets.values())
                if total_active > 0:
                    for f in active_targets:
                        active_targets[f] += inactive_share * (active_targets[f] / total_active)

            # Now allocate within each family slice
            for fam_name, fam_rows in by_family.items():
                fam_share = active_targets.get(fam_name, 0)
                if fam_share <= 0 or not fam_rows:
                    continue
                fam_frac = target_frac * fam_share
                fam_cap_cfg = fam_cfg.get(fam_name, {})
                fam_name_cap = fam_cap_cfg.get("name_cap_pct")
                eff_cap = fam_name_cap if fam_name_cap is not None else bucket_cap

                # --- Regulatory ladder ---
                use_ladder = ladder_enabled and fam_name == "REGULATORY"
                if use_ladder:
                    positions.extend(
                        _allocate_regulatory_ladder(
                            fam_rows,
                            fam_frac,
                            eff_cap,
                            bucket_name,
                            gap_high_days,
                            gap_high_cap,
                            acct,
                            ladder_caps,
                            ladder_weights.get(bucket_name, {}),
                            quality_tilt=quality_tilt,
                            quality_clip_lo=quality_clip_lo,
                            quality_clip_hi=quality_clip_hi,
                        )
                    )
                else:
                    fn = len(fam_rows)
                    equal_wt = (fam_frac * 100.0) / fn
                    for row in fam_rows:
                        wt = min(equal_wt, eff_cap)
                        wt, gap_risk = _apply_gap_risk(wt, row, bucket_name, gap_high_days, gap_high_cap)
                        source = (row.get("de_beta_xbi_60d_source") or "").strip()
                        is_secondary_reg = (
                            fam_name == "REGULATORY"
                            and row.get("has_regulatory_upcoming_180d") == "1"
                            and (row.get("catalyst_family") or "").upper() != "REGULATORY"
                        )
                        positions.append(
                            _make_position(
                                row,
                                bucket_name,
                                fam_name,
                                wt,
                                gap_risk,
                                source,
                                acct,
                                is_secondary_reg,
                            )
                        )
        else:
            # --- Flat allocation (no family targets) ---
            equal_wt = (target_frac * 100.0) / n
            for row in rows:
                fam = row["_effective_family"]
                fam_cap = fam_cfg.get(fam, {}).get("name_cap_pct")
                eff_cap = fam_cap if fam_cap is not None else bucket_cap
                wt = min(equal_wt, eff_cap)
                wt, gap_risk = _apply_gap_risk(wt, row, bucket_name, gap_high_days, gap_high_cap)
                source = (row.get("de_beta_xbi_60d_source") or "").strip()
                positions.append(
                    _make_position(
                        row,
                        bucket_name,
                        fam,
                        wt,
                        gap_risk,
                        source,
                        acct,
                        False,
                    )
                )

    # Trim overage if total > account
    total = sum(p["target_dollars"] for p in positions)
    if total > acct and positions:
        trim_order = sorted(
            range(len(positions)),
            key=lambda i: (-positions[i]["target_dollars"], positions[i]["ticker"]),
        )
        overage = total - acct
        for idx in trim_order:
            if overage <= 0:
                break
            reduce = min(positions[idx]["target_dollars"], overage)
            positions[idx]["target_dollars"] = round(positions[idx]["target_dollars"] - reduce, 2)
            overage -= reduce

    # Summary
    total_alloc = sum(p["target_dollars"] for p in positions)
    per_bucket: Dict[str, Dict[str, Any]] = {}
    for b in BUCKET_NAMES:
        b_pos = [p for p in positions if p["bucket"] == b]
        per_bucket[b] = {
            "count": len(b_pos),
            "total_dollars": sum(p["target_dollars"] for p in b_pos),
            "weight_pct": sum(p["weight_pct"] for p in b_pos),
        }

    # Per-(bucket × family) breakdown
    per_bucket_family: Dict[str, Dict[str, Any]] = {}
    for b in BUCKET_NAMES:
        b_pos = [p for p in positions if p["bucket"] == b]
        fam_groups: Dict[str, List[Dict[str, Any]]] = {}
        for p in b_pos:
            fam = p.get("catalyst_family", "OTHER")
            fam_groups.setdefault(fam, []).append(p)
        for fam, fps in fam_groups.items():
            key = f"{b}__{fam}"
            per_bucket_family[key] = {
                "count": len(fps),
                "total_dollars": sum(fp["target_dollars"] for fp in fps),
            }

    gap_high = [p["ticker"] for p in positions if p["gap_risk"] == "HIGH"]
    missing_price = [p["ticker"] for p in positions if p["price_coverage"] == "MISSING"]

    summary = {
        "total_positions": len(positions),
        "total_allocated": round(total_alloc, 2),
        "residual_cash": round(acct - total_alloc, 2),
        "per_bucket": per_bucket,
        "per_bucket_family": per_bucket_family,
        "gap_risk_high": gap_high,
        "missing_price": missing_price,
        "resolved_regulatory": [
            {
                "ticker": r.get("ticker", ""),
                "regulatory_days": r.get("regulatory_days", ""),
                "regulatory_event_type": r.get("regulatory_event_type", ""),
            }
            for r in resolved_rows
        ],
    }

    return {"positions": positions, "summary": summary}


# ---------------------------------------------------------------------------
# Price lookup for performance
# ---------------------------------------------------------------------------


def load_price_map(
    price_path: Path,
    date: str,
) -> Dict[str, float]:
    """Load closing prices for a specific date from price_history.csv.

    Returns ticker → close price mapping.
    """
    prices: Dict[str, float] = {}
    if not price_path.is_file():
        return prices
    with open(price_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("date") == date:
                close = _safe_float(row.get("close", ""))
                if close > 0:
                    prices[row.get("ticker", "")] = close
    return prices


def load_xbi_price(price_path: Path, date: str) -> Optional[float]:
    """Load XBI closing price for a specific date."""
    if not price_path.is_file():
        return None
    with open(price_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("date") == date and row.get("ticker") == "XBI":
                close = _safe_float(row.get("close", ""))
                return close if close > 0 else None
    return None


# ---------------------------------------------------------------------------
# Fill-price helpers
# ---------------------------------------------------------------------------


def _load_fill_prices(trade_date: str, trades_root: Optional[Path] = None) -> Dict[str, float]:
    """If fills.csv exists for trade_date, return {ticker: fill_price}.

    Fill prices override the close-price cost basis in performance computation,
    giving a more accurate P&L when real execution data is available.
    """
    if trades_root is None:
        trades_root = SHADOW_ROOT / "trades"
    fills_csv = trades_root / trade_date / "fills.csv"
    if not fills_csv.is_file():
        return {}
    result: Dict[str, float] = {}
    with open(fills_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("status") not in ("FILLED", "PARTIAL"):
                continue
            ticker = row.get("ticker", "")
            price_str = row.get("fill_price", "")
            if not ticker or not price_str:
                continue
            try:
                price = float(price_str)
                if price > 0:
                    result[ticker] = price
            except (ValueError, TypeError):
                continue
    return result


# ---------------------------------------------------------------------------
# Performance computation
# ---------------------------------------------------------------------------


def compute_performance(
    prior_positions: List[Dict[str, Any]],
    current_positions: List[Dict[str, Any]],
    prior_date: str,
    current_date: str,
    price_path: Path = PRICE_HISTORY_PATH,
    trades_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Compute realized P&L between two position snapshots.

    Returns dict with total_pnl, pnl_pct, excess_vs_xbi, sleeve attribution,
    turnover metrics.

    If fills.csv exists for prior_date, fill prices override close prices
    for the entry cost basis.
    """
    _assert_not_production_default("price_path", price_path, PRICE_HISTORY_PATH)
    prior_prices = load_price_map(price_path, prior_date)
    current_prices = load_price_map(price_path, current_date)

    # Override entry cost basis with fill prices when available
    fill_prices = _load_fill_prices(prior_date, trades_root=trades_root)
    if fill_prices:
        for ticker, fp in fill_prices.items():
            prior_prices[ticker] = fp
    xbi_prior = load_xbi_price(price_path, prior_date)
    xbi_current = load_xbi_price(price_path, current_date)

    # XBI return (compute early — needed for contributors)
    xbi_return = None
    if xbi_prior and xbi_current and xbi_prior > 0:
        xbi_return = (xbi_current / xbi_prior) - 1.0

    # Weighted return of prior portfolio at current prices
    total_pnl = 0.0
    total_weight = 0.0
    sleeve_pnl: Dict[str, float] = {b: 0.0 for b in BUCKET_NAMES}
    sleeve_weight: Dict[str, float] = {b: 0.0 for b in BUCKET_NAMES}
    contributors: List[Dict[str, Any]] = []
    n_priced = 0
    n_missing = 0

    for pos in prior_positions:
        ticker = pos["ticker"]
        dollars = pos.get("target_dollars", 0.0)
        bucket = pos.get("bucket", "less_binary")
        p0 = prior_prices.get(ticker)
        p1 = current_prices.get(ticker)

        if p0 and p1 and p0 > 0 and dollars > 0:
            ret = (p1 / p0) - 1.0
            pnl = dollars * ret
            total_pnl += pnl
            total_weight += dollars
            sleeve_pnl[bucket] = sleeve_pnl.get(bucket, 0.0) + pnl
            sleeve_weight[bucket] = sleeve_weight.get(bucket, 0.0) + dollars
            n_priced += 1

            contrib: Dict[str, Any] = {
                "ticker": ticker,
                "bucket": bucket,
                "dollars": dollars,
                "return_pct": round(ret * 100, 4),
                "pnl": round(pnl, 2),
            }
            if xbi_return is not None:
                contrib["excess_vs_xbi_pct"] = round((ret - xbi_return) * 100, 4)
                contrib["excess_pnl"] = round(dollars * (ret - xbi_return), 2)
            contributors.append(contrib)
        else:
            n_missing += 1

    # Portfolio return
    pnl_pct = (total_pnl / total_weight) if total_weight > 0 else 0.0
    excess = (pnl_pct - xbi_return) if xbi_return is not None else None

    # Sleeve attribution (with excess vs XBI)
    xbi_return_pct_val = round(xbi_return * 100, 4) if xbi_return is not None else None
    sleeve_attr = {}
    for b in BUCKET_NAMES:
        sw = sleeve_weight[b]
        ret_pct = round(sleeve_pnl[b] / sw * 100, 4) if sw > 0 else 0.0
        entry: Dict[str, Any] = {
            "pnl": round(sleeve_pnl[b], 2),
            "return_pct": ret_pct,
            "weight": round(sw, 2),
        }
        if xbi_return is not None:
            entry["excess_vs_xbi_pct"] = round(ret_pct - xbi_return_pct_val, 4)
            entry["excess_pnl"] = round(sleeve_pnl[b] - sw * xbi_return, 2)
        sleeve_attr[b] = entry

    # Turnover: fraction of prior tickers NOT in current portfolio
    prior_tickers = {p["ticker"] for p in prior_positions}
    current_tickers = {p["ticker"] for p in current_positions}
    overlap = prior_tickers & current_tickers
    turnover = 1.0 - (len(overlap) / len(prior_tickers)) if prior_tickers else 0.0

    # Sort contributors by $ P&L descending for easy access
    contributors.sort(key=lambda c: -c["pnl"])

    return {
        "prior_date": prior_date,
        "current_date": current_date,
        "total_pnl": round(total_pnl, 2),
        "pnl_pct": round(pnl_pct * 100, 4),
        "xbi_return_pct": round(xbi_return * 100, 4) if xbi_return is not None else None,
        "excess_vs_xbi_pct": round(excess * 100, 4) if excess is not None else None,
        "sleeve_attribution": sleeve_attr,
        "contributors": contributors,
        "n_priced": n_priced,
        "n_missing_price": n_missing,
        "turnover": round(turnover, 4),
        "n_prior": len(prior_tickers),
        "n_current": len(current_tickers),
        "overlap": len(overlap),
        "gap_risk_high_count": sum(1 for p in current_positions if p.get("gap_risk") == "HIGH"),
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save_positions(
    as_of_date: str,
    positions_data: Dict[str, Any],
    metadata: Dict[str, Any],
    out_dir: Path = POSITIONS_DIR,
) -> Path:
    """Write positions JSON artifact."""
    _assert_not_production_default("out_dir", out_dir, POSITIONS_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{as_of_date}.json"
    doc = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ruleset_id": metadata.get("ruleset_id", ""),
        "engine_version": metadata.get("version", ""),
        **positions_data,
    }
    with open(path, "w") as f:
        json.dump(doc, f, indent=2)
    return path


def load_prior_positions(
    as_of_date: str,
    positions_dir: Path = POSITIONS_DIR,
) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
    """Find and load the most recent positions file before as_of_date.

    Returns (prior_date, positions_list) or None.
    """
    _assert_not_production_default("positions_dir", positions_dir, POSITIONS_DIR)
    if not positions_dir.is_dir():
        return None

    candidates = []
    for p in positions_dir.iterdir():
        if p.suffix == ".json" and p.stem < as_of_date:
            candidates.append(p)
    if not candidates:
        return None

    latest = max(candidates, key=lambda p: p.stem)
    with open(latest) as f:
        doc = json.load(f)
    return (doc.get("as_of_date", latest.stem), doc.get("positions", []))


PERF_COLUMNS = [
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
]


def append_performance(
    as_of_date: str,
    perf: Dict[str, Any],
    ruleset_id: str = "",
    perf_csv: Path = PERFORMANCE_CSV,
) -> None:
    """Append a row to the append-only performance CSV."""
    _assert_not_production_default("perf_csv", perf_csv, PERFORMANCE_CSV)
    perf_csv.parent.mkdir(parents=True, exist_ok=True)
    write_header = not perf_csv.is_file()

    sleeve = perf.get("sleeve_attribution", {})
    row = {
        "schema_version": PERF_SCHEMA_VERSION,
        "date": as_of_date,
        "prior_date": perf.get("prior_date", ""),
        "total_pnl": perf.get("total_pnl", ""),
        "pnl_pct": perf.get("pnl_pct", ""),
        "xbi_return_pct": perf.get("xbi_return_pct", ""),
        "excess_vs_xbi_pct": perf.get("excess_vs_xbi_pct", ""),
        "n_held": perf.get("n_prior", ""),
        "turnover": perf.get("turnover", ""),
        "gap_risk_high_count": perf.get("gap_risk_high_count", ""),
        "n_missing_price": perf.get("n_missing_price", ""),
        "sleeve_binary_0_30_pnl": sleeve.get("binary_0_30", {}).get("pnl", ""),
        "sleeve_binary_31_90_pnl": sleeve.get("binary_31_90", {}).get("pnl", ""),
        "sleeve_binary_91_180_pnl": sleeve.get("binary_91_180", {}).get("pnl", ""),
        "sleeve_less_binary_pnl": sleeve.get("less_binary", {}).get("pnl", ""),
        "ruleset_id": ruleset_id,
    }

    with open(perf_csv, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PERF_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


# ---------------------------------------------------------------------------
# Enhanced summary helpers
# ---------------------------------------------------------------------------


def _compute_hit_rate_by_bucket(contributors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return [{bucket, names, positive, hit_rate}] for non-empty buckets."""
    from collections import defaultdict

    buckets: Dict[str, List[Dict]] = defaultdict(list)
    for c in contributors:
        buckets[c.get("bucket", "")].append(c)
    result = []
    for b in BUCKET_NAMES:
        if b not in buckets:
            continue
        items = buckets[b]
        pos = sum(1 for c in items if c.get("return_pct", 0) > 0)
        result.append(
            {
                "bucket": b,
                "names": len(items),
                "positive": pos,
                "hit_rate": round(pos / len(items) * 100, 2) if items else 0.0,
            }
        )
    return result


def _compute_alpha_leaders(
    contributors: List[Dict[str, Any]], n: int = 5, bucket_filter: str = None
) -> Tuple[List[Dict], List[Dict]]:
    """Return (top_n, bottom_n) sorted by excess_pnl."""
    filtered = contributors
    if bucket_filter:
        filtered = [c for c in contributors if c.get("bucket") == bucket_filter]
    by_excess = sorted(filtered, key=lambda c: c.get("excess_pnl", 0), reverse=True)
    top = by_excess[:n]
    bottom = by_excess[-n:] if len(by_excess) > n else by_excess[n:]
    bottom = sorted(bottom, key=lambda c: c.get("excess_pnl", 0))
    return top, bottom


def _compute_signal_diagnostics(
    positions: List[Dict[str, Any]], prior_positions: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Return signal diagnostics: catalyst_days avg, bucket movers, gap risk."""
    cat_days = []
    gap_high_usd = 0.0
    total_usd = 0.0
    for p in positions:
        cd = p.get("catalyst_days", "")
        if cd and cd != "":
            try:
                cat_days.append(float(cd))
            except (ValueError, TypeError):
                pass
        dollars = _safe_float(p.get("target_dollars", 0))
        total_usd += dollars
        if p.get("gap_risk") == "HIGH":
            gap_high_usd += dollars

    current_tickers = {p.get("ticker") for p in positions}
    prior_tickers = {p.get("ticker") for p in prior_positions}

    return {
        "avg_catalyst_days": round(sum(cat_days) / len(cat_days), 1) if cat_days else 0.0,
        "bucket_movers_in": len(current_tickers - prior_tickers),
        "bucket_movers_out": len(prior_tickers - current_tickers),
        "gap_high_weight": round(gap_high_usd / total_usd * 100, 1) if total_usd > 0 else 0.0,
        "gap_high_usd": round(gap_high_usd, 2),
    }


def _compute_regulatory_coverage(
    positions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute secondary regulatory coverage metrics from positions.

    Returns dict with: n_eligible, n_regulatory, coverage_pct, top_imminent.
    """
    eligible = [p for p in positions if p.get("ticker")]
    reg = [p for p in eligible if p.get("has_regulatory_upcoming_180d") == "1"]
    n_eligible = len(eligible)
    n_reg = len(reg)

    # Top 10 by smallest regulatory_days, then ticker for stable sort
    def _sort_key(p):
        rd = p.get("regulatory_days", "")
        try:
            return (float(rd), p.get("ticker", ""))
        except (ValueError, TypeError):
            return (9999, p.get("ticker", ""))

    top_imminent = sorted(reg, key=_sort_key)[:10]

    return {
        "n_eligible": n_eligible,
        "n_regulatory": n_reg,
        "coverage_pct": round(n_reg / n_eligible * 100, 1) if n_eligible > 0 else 0.0,
        "top_imminent": top_imminent,
    }


def _compute_expected_vs_realized(
    positions: List[Dict[str, Any]],
    contributors: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute expected vs realized return diagnostics.

    'Expected' proxied by: tier (A > B), catalyst proximity (nearer > farther),
    momentum state (tailwind > neutral > headwind).

    Returns dict with per-bucket and per-factor breakdowns.
    """
    from collections import defaultdict

    # Build contributor lookup by ticker
    contrib_by_ticker: Dict[str, Dict[str, Any]] = {}
    for c in contributors:
        contrib_by_ticker[c.get("ticker", "")] = c

    # Build position lookup by ticker (for factor fields)
    pos_by_ticker: Dict[str, Dict[str, Any]] = {}
    for p in positions:
        pos_by_ticker[p.get("ticker", "")] = p

    # Collect matched records: each has position fields + return_pct from contributor
    matched: List[Dict[str, Any]] = []
    for ticker, contrib in contrib_by_ticker.items():
        pos = pos_by_ticker.get(ticker)
        if pos is None:
            continue
        matched.append(
            {
                "ticker": ticker,
                "bucket": pos.get("bucket", ""),
                "tier": pos.get("tier", ""),
                "mom_state": pos.get("mom_state", ""),
                "catalyst_days": pos.get("catalyst_days", ""),
                "gap_risk": pos.get("gap_risk", ""),
                "actionable_rank": pos.get("actionable_rank", 9999),
                "return_pct": contrib.get("return_pct", 0.0),
            }
        )

    def _group_stats(items: List[Dict[str, Any]], key: str) -> Dict[str, Dict[str, Any]]:
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in items:
            groups[item[key]].append(item)
        result: Dict[str, Dict[str, Any]] = {}
        for k, group in groups.items():
            if not k:
                continue
            returns = [g["return_pct"] for g in group]
            n = len(returns)
            mean_ret = sum(returns) / n if n else 0.0
            hit = sum(1 for r in returns if r > 0)
            result[k] = {
                "n": n,
                "mean_return_pct": round(mean_ret, 4),
                "hit_rate": round(hit / n, 4) if n else 0.0,
            }
        return result

    # By bucket
    by_bucket = _group_stats(matched, "bucket")

    # By tier
    by_tier = _group_stats(matched, "tier")

    # By momentum
    by_momentum: Dict[str, Dict[str, Any]] = {}
    mom_groups: Dict[str, List[float]] = defaultdict(list)
    for m in matched:
        state = m.get("mom_state", "")
        if state:
            mom_groups[state].append(m["return_pct"])
    for state, returns in mom_groups.items():
        n = len(returns)
        by_momentum[state] = {
            "n": n,
            "mean_return_pct": round(sum(returns) / n, 4) if n else 0.0,
        }

    # By catalyst proximity: near (<=90), mid (91-180), far (>180 or empty)
    cat_groups: Dict[str, List[float]] = defaultdict(list)
    for m in matched:
        cd = m.get("catalyst_days", "")
        try:
            cd_val = float(cd)
            if cd_val <= 90:
                cat_groups["near"].append(m["return_pct"])
            elif cd_val <= 180:
                cat_groups["mid"].append(m["return_pct"])
            else:
                cat_groups["far"].append(m["return_pct"])
        except (ValueError, TypeError):
            cat_groups["far"].append(m["return_pct"])
    by_catalyst_proximity: Dict[str, Dict[str, Any]] = {}
    for band, returns in cat_groups.items():
        n = len(returns)
        by_catalyst_proximity[band] = {
            "n": n,
            "mean_return_pct": round(sum(returns) / n, 4) if n else 0.0,
        }

    # By gap risk: HIGH vs other
    gap_high_returns = [m["return_pct"] for m in matched if m.get("gap_risk") == "HIGH"]
    gap_other_returns = [m["return_pct"] for m in matched if m.get("gap_risk") != "HIGH"]
    by_gap_risk: Dict[str, Dict[str, Any]] = {}
    if gap_high_returns:
        n_h = len(gap_high_returns)
        by_gap_risk["HIGH"] = {
            "n": n_h,
            "mean_return_pct": round(sum(gap_high_returns) / n_h, 4),
        }
    if gap_other_returns:
        n_o = len(gap_other_returns)
        by_gap_risk["other"] = {
            "n": n_o,
            "mean_return_pct": round(sum(gap_other_returns) / n_o, 4),
        }

    # Top-5 gap: rank-vs-return surprise
    if matched:
        max_rank = max(m["actionable_rank"] for m in matched) or 1
        # Normalize returns to [0, 1] range for gap computation
        abs_returns = [abs(m["return_pct"]) for m in matched]
        max_abs_return = max(abs_returns) if abs_returns else 1.0
        if max_abs_return == 0:
            max_abs_return = 1.0

        gap_entries = []
        for m in matched:
            expected_signal = 1.0 - (m["actionable_rank"] / max_rank) if max_rank > 0 else 0.0
            normalized_realized = (m["return_pct"] / max_abs_return + 1.0) / 2.0
            gap = abs(expected_signal - normalized_realized)
            gap_entries.append(
                {
                    "ticker": m["ticker"],
                    "bucket": m["bucket"],
                    "rank": m["actionable_rank"],
                    "return_pct": round(m["return_pct"], 4),
                    "gap": round(gap, 4),
                }
            )
        gap_entries.sort(key=lambda g: g["gap"], reverse=True)
        top5_gap = gap_entries[:5]
    else:
        top5_gap = []

    return {
        "by_bucket": by_bucket,
        "by_tier": by_tier,
        "by_momentum": by_momentum,
        "by_catalyst_proximity": by_catalyst_proximity,
        "by_gap_risk": by_gap_risk,
        "top5_gap": top5_gap,
    }


def _write_diagnostics_json(
    diag: Dict[str, Any],
    as_of_date: str,
    out_dir: Path,
) -> Path:
    """Write diagnostics JSON sidecar at out_dir/{date}.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "expected_vs_realized.v1",
        "as_of_date": as_of_date,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **diag,
    }
    out_file = out_dir / f"{as_of_date}.json"
    with open(out_file, "w") as f:
        json.dump(payload, f, indent=2)
    return out_file


# ---------------------------------------------------------------------------
# Weekly summary markdown
# ---------------------------------------------------------------------------


def write_weekly_summary(
    as_of_date: str,
    positions_data: Dict[str, Any],
    perf: Optional[Dict[str, Any]],
    policy: Dict[str, Any],
    metadata: Dict[str, Any],
    out_path: Path = WEEKLY_SUMMARY,
) -> Path:
    """Write a human-readable weekly summary markdown."""
    _assert_not_production_default("out_path", out_path, WEEKLY_SUMMARY)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    positions = positions_data.get("positions", [])
    summary = positions_data.get("summary", {})
    per_bucket = summary.get("per_bucket", {})

    lines = []
    lines.append("# Weekly Shadow Portfolio Summary")
    lines.append("")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"**As-of date**: {as_of_date}")
    lines.append(f"**Generated**: {ts}")
    rs_id = metadata.get("ruleset_id", "?")
    lines.append(f"**Ruleset**: {rs_id}")
    acct = policy.get("account_usd", 500_000)
    lines.append(f"**Account**: ${acct:,.0f}")
    lines.append("")

    # Policy vs Actual
    lines.append("## Policy vs Actual")
    lines.append("")
    lines.append("| Bucket | Policy | Actual | Actual $ | Names |")
    lines.append("|--------|--------|--------|----------|-------|")
    bucket_targets = policy.get("bucket_targets", {})
    for b in BUCKET_NAMES:
        bdata = per_bucket.get(b, {})
        target_pct = bucket_targets.get(b, 0) * 100
        actual_pct = (bdata.get("total_dollars", 0) / acct * 100) if acct > 0 else 0
        lines.append(
            f"| {BUCKET_DISPLAY.get(b, b)} | {target_pct:.0f}% "
            f"| {actual_pct:.1f}% | ${bdata.get('total_dollars', 0):,.0f} "
            f"| {bdata.get('count', 0)} |"
        )
    lines.append("")
    lines.append(
        f"**Total allocated**: ${summary.get('total_allocated', 0):,.0f} "
        f"| **Cash**: ${summary.get('residual_cash', 0):,.0f}"
    )
    lines.append("")

    # Family Allocation (bucket × family breakdown)
    per_bucket_family = summary.get("per_bucket_family", {})
    if per_bucket_family:
        lines.append("## Family Allocation")
        lines.append("")
        lines.append("| Bucket × Family | Names | $ |")
        lines.append("|-----------------|-------|---|")
        for key in sorted(per_bucket_family.keys()):
            bf = per_bucket_family[key]
            lines.append(f"| {key} | {bf['count']} | ${bf['total_dollars']:,.0f} |")
        lines.append("")

    # Risk
    gap_high = summary.get("gap_risk_high", [])
    missing = summary.get("missing_price", [])
    lines.append("## Risk Flags")
    lines.append("")
    if gap_high:
        lines.append(f"**Gap Risk HIGH** ({len(gap_high)} names): {', '.join(gap_high)}")
    else:
        lines.append("**Gap Risk HIGH**: none")
    if missing:
        lines.append(f"**Missing Price** ({len(missing)} names): {', '.join(missing)}")
    else:
        lines.append("**Missing Price**: none")
    lines.append("")

    # Performance (if available)
    if perf:
        lines.append("## Performance vs Prior")
        lines.append("")
        lines.append(f"**Period**: {perf.get('prior_date', '?')} → {as_of_date}")
        pnl = perf.get("total_pnl", 0)
        pnl_pct = perf.get("pnl_pct", 0)
        xbi_ret = perf.get("xbi_return_pct")
        excess = perf.get("excess_vs_xbi_pct")
        lines.append(f"**Total P&L**: ${pnl:,.2f} ({pnl_pct:+.2f}%)")
        if xbi_ret is not None:
            lines.append(f"**XBI return**: {xbi_ret:+.2f}%")
        if excess is not None:
            lines.append(f"**Excess vs XBI**: {excess:+.2f}%")
        lines.append(f"**Turnover**: {perf.get('turnover', 0):.1%}")
        lines.append("")

        # Sleeve attribution (expanded with excess vs XBI)
        sleeve = perf.get("sleeve_attribution", {})
        xbi_pct = perf.get("xbi_return_pct")
        has_xbi = xbi_pct is not None
        lines.append("### Sleeve Attribution")
        lines.append("")
        if has_xbi:
            lines.append("| Bucket | Weight $ | P&L $ | Return % | XBI % | Excess % | Excess $ |")
            lines.append("|--------|----------|-------|----------|-------|----------|----------|")
        else:
            lines.append("| Bucket | Weight $ | P&L $ | Return % |")
            lines.append("|--------|----------|-------|----------|")
        for b in BUCKET_NAMES:
            s = sleeve.get(b, {})
            ret_pct = s.get("return_pct", 0)
            label = BUCKET_DISPLAY.get(b, b)
            if b == "binary_91_180":
                label = f"**{label}**"
            if has_xbi:
                exc_pct = s.get("excess_vs_xbi_pct", ret_pct - xbi_pct)
                exc_pnl = s.get("excess_pnl", 0)
                lines.append(
                    f"| {label} "
                    f"| ${s.get('weight', 0):,.0f} "
                    f"| ${s.get('pnl', 0):,.2f} "
                    f"| {ret_pct:+.2f}% "
                    f"| {xbi_pct:+.2f}% "
                    f"| {exc_pct:+.2f}% "
                    f"| ${exc_pnl:,.2f} |"
                )
            else:
                lines.append(
                    f"| {label} " f"| ${s.get('weight', 0):,.0f} " f"| ${s.get('pnl', 0):,.2f} " f"| {ret_pct:+.2f}% |"
                )
        lines.append("")

        # Binary vs Less-binary rollup
        binary_buckets = ["binary_0_30", "binary_31_90", "binary_91_180"]
        bin_pnl = sum(sleeve.get(b, {}).get("pnl", 0) for b in binary_buckets)
        bin_wt = sum(sleeve.get(b, {}).get("weight", 0) for b in binary_buckets)
        bin_ret = (bin_pnl / bin_wt * 100) if bin_wt > 0 else 0.0
        lb = sleeve.get("less_binary", {})
        lb_pnl = lb.get("pnl", 0)
        lb_wt = lb.get("weight", 0)
        lb_ret = (lb_pnl / lb_wt * 100) if lb_wt > 0 else 0.0

        lines.append("### Rollup")
        lines.append("")
        lines.append(f"- **Binary (all)**: ${bin_pnl:,.2f} P&L ({bin_ret:+.2f}%) on ${bin_wt:,.0f}")
        lines.append(f"- **Less-binary**: ${lb_pnl:,.2f} P&L ({lb_ret:+.2f}%) on ${lb_wt:,.0f}")
        if has_xbi:
            s91 = sleeve.get("binary_91_180", {})
            s91_exc = s91.get("excess_vs_xbi_pct", 0)
            lines.append(f"- **Binary 91-180 Excess vs XBI: {s91_exc:+.2f}%** (primary sleeve)")
        lines.append("")

        # Trailing Alpha Dashboard (1w / 4w)
        try:
            from tools.build_trade_plan import compute_trailing_metrics, load_performance_rows

            _perf_rows = load_performance_rows()
            if len(_perf_rows) >= 2:
                t4 = compute_trailing_metrics(_perf_rows, min(4, len(_perf_rows)))
                lines.append("### Trailing Alpha Dashboard")
                lines.append("")
                lines.append("| Bucket | 4w Avg P&L | 4w Hit Rate | 4w Worst |")
                lines.append("|--------|------------|-------------|----------|")
                for _b in BUCKET_NAMES:
                    _label = BUCKET_DISPLAY.get(_b, _b)
                    if _b == "binary_91_180":
                        _label = f"**{_label}**"
                    _t4b = t4.get("buckets", {}).get(_b, {})
                    _avg = f"${_t4b['avg_pnl']:+,.0f}" if _t4b.get("avg_pnl") is not None else "—"
                    _hr = f"{_t4b['hit_rate']:.0%}" if _t4b.get("hit_rate") is not None else "—"
                    _worst = f"${_t4b['worst_week']:+,.0f}" if _t4b.get("worst_week") is not None else "—"
                    lines.append(f"| {_label} | {_avg} | {_hr} | {_worst} |")
                lines.append("")
                _p4 = t4.get("portfolio", {})
                if _p4.get("excess_vs_xbi") is not None:
                    lines.append(f"**Trailing avg excess vs XBI**: {_p4['excess_vs_xbi']:+.2f}%")
                    lines.append("")
        except Exception:
            pass  # Trailing metrics are best-effort

        # What Drove the Week — top/bottom contributors
        contributors = perf.get("contributors", [])
        if contributors:
            lines.append("### What Drove the Week")
            lines.append("")
            has_excess = "excess_pnl" in contributors[0]
            if has_excess:
                hdr = "| Ticker | Bucket | Prior $ | Return % | P&L $ | Excess $ |"
                sep = "|--------|--------|---------|----------|-------|----------|"
            else:
                hdr = "| Ticker | Bucket | Prior $ | Return % | P&L $ |"
                sep = "|--------|--------|---------|----------|-------|"

            top5 = contributors[:5]
            bot5 = list(reversed(contributors[-5:])) if len(contributors) > 5 else []
            # Deduplicate if overlap
            top_tickers = {c["ticker"] for c in top5}
            bot5 = [c for c in bot5 if c["ticker"] not in top_tickers]

            def _contrib_row(c: dict) -> str:
                row = (
                    f"| {c['ticker']} "
                    f"| {BUCKET_DISPLAY.get(c['bucket'], c['bucket'])} "
                    f"| ${c['dollars']:,.0f} "
                    f"| {c['return_pct']:+.2f}% "
                    f"| ${c['pnl']:,.2f} "
                )
                if has_excess:
                    row += f"| ${c.get('excess_pnl', 0):,.2f} |"
                else:
                    row += "|"
                return row

            lines.append("**Top 5 contributors**")
            lines.append("")
            lines.append(hdr)
            lines.append(sep)
            for c in top5:
                lines.append(_contrib_row(c))
            lines.append("")

            if bot5:
                lines.append("**Bottom 5 contributors**")
                lines.append("")
                lines.append(hdr)
                lines.append(sep)
                for c in bot5:
                    lines.append(_contrib_row(c))
                lines.append("")
        else:
            lines.append("### What Drove the Week")
            lines.append("")
            lines.append("No priced prior positions to attribute.")
            lines.append("")
    else:
        lines.append("## Performance vs Prior")
        lines.append("")
        lines.append("No prior positions found — first snapshot.")
        lines.append("")

    # --- Hit Rate by Bucket ---
    if perf:
        contributors = perf.get("contributors", [])
        if contributors:
            hit_rates = _compute_hit_rate_by_bucket(contributors)
            if hit_rates:
                lines.append("## Hit Rate by Bucket")
                lines.append("")
                lines.append("| Bucket | Names | Positive | Hit Rate |")
                lines.append("|--------|-------|----------|----------|")
                for hr in hit_rates:
                    lines.append(
                        f"| {BUCKET_DISPLAY.get(hr['bucket'], hr['bucket'])} "
                        f"| {hr['names']} | {hr['positive']} | {hr['hit_rate']:.1f}% |"
                    )
                lines.append("")

            # --- Alpha Leaders ---
            has_excess = any("excess_pnl" in c for c in contributors)
            if has_excess:
                lines.append("## Alpha Leaders")
                lines.append("")

                def _alpha_table(items: list, label: str) -> None:
                    lines.append(f"### {label}")
                    lines.append("")
                    lines.append("| Ticker | Bucket | Return | Excess $ |")
                    lines.append("|--------|--------|--------|----------|")
                    for c in items:
                        lines.append(
                            f"| {c['ticker']} "
                            f"| {BUCKET_DISPLAY.get(c['bucket'], c['bucket'])} "
                            f"| {c.get('return_pct', 0):+.2f}% "
                            f"| ${c.get('excess_pnl', 0):,.2f} |"
                        )
                    lines.append("")

                top_all, bot_all = _compute_alpha_leaders(contributors, n=5)
                _alpha_table(top_all, "Top-5 Alpha (Overall)")
                if bot_all:
                    _alpha_table(bot_all, "Bottom-5 Alpha (Overall)")

                # binary_91_180 specific
                top_b91, bot_b91 = _compute_alpha_leaders(contributors, n=5, bucket_filter="binary_91_180")
                if top_b91:
                    _alpha_table(top_b91, "Top-5 Alpha (binary_91_180)")
                if bot_b91:
                    _alpha_table(bot_b91, "Bottom-5 Alpha (binary_91_180)")

    # --- Signal Diagnostics ---
    prior_pos_for_diag: List[Dict[str, Any]] = []
    if perf:
        # Try to load prior positions for mover detection
        try:
            _prior_result = load_prior_positions(as_of_date)
            if _prior_result:
                _, prior_pos_for_diag = _prior_result
        except Exception:
            pass

    if positions:
        diag = _compute_signal_diagnostics(positions, prior_pos_for_diag)
        lines.append("## Signal Diagnostics")
        lines.append("")
        lines.append(f"- Avg catalyst_days (held): {diag['avg_catalyst_days']:.1f}")
        lines.append(
            f"- Bucket movers (entered/exited this week): {diag['bucket_movers_in']} entered, {diag['bucket_movers_out']} exited"
        )
        lines.append(f"- Gap-risk HIGH weight: {diag['gap_high_weight']:.1f}% (${diag['gap_high_usd']:,.0f})")
        lines.append("")

    # --- Expected vs Realized ---
    if perf and contributors:
        evr = _compute_expected_vs_realized(positions, contributors)

        lines.append("## Expected vs Realized")
        lines.append("")

        # By Bucket
        lines.append("### Return by Bucket")
        lines.append("")
        lines.append("| Bucket | N | Mean Return | Hit Rate |")
        lines.append("|--------|---|-------------|----------|")
        for b in BUCKET_NAMES:
            bd = evr["by_bucket"].get(b, {})
            if bd.get("n", 0) > 0:
                lines.append(
                    f"| {BUCKET_DISPLAY.get(b, b)} | {bd['n']} "
                    f"| {bd['mean_return_pct']:+.2f}% | {bd['hit_rate']:.0%} |"
                )
        lines.append("")

        # By Tier
        lines.append("### Return by Tier")
        lines.append("")
        lines.append("| Tier | N | Mean Return | Hit Rate |")
        lines.append("|------|---|-------------|----------|")
        for tier in ["A", "B", "C", "D"]:
            td = evr["by_tier"].get(tier, {})
            if td.get("n", 0) > 0:
                lines.append(f"| {tier} | {td['n']} " f"| {td['mean_return_pct']:+.2f}% | {td['hit_rate']:.0%} |")
        lines.append("")

        # By Momentum
        lines.append("### Return by Momentum")
        lines.append("")
        lines.append("| State | N | Mean Return |")
        lines.append("|-------|---|-------------|")
        for state in ["tailwind", "neutral", "headwind"]:
            md = evr["by_momentum"].get(state, {})
            if md.get("n", 0) > 0:
                lines.append(f"| {state} | {md['n']} | {md['mean_return_pct']:+.2f}% |")
        lines.append("")

        # By Catalyst Proximity
        lines.append("### Return by Catalyst Proximity")
        lines.append("")
        lines.append("| Band | N | Mean Return |")
        lines.append("|------|---|-------------|")
        for band in ["near", "mid", "far"]:
            cd = evr["by_catalyst_proximity"].get(band, {})
            if cd.get("n", 0) > 0:
                lines.append(f"| {band} | {cd['n']} | {cd['mean_return_pct']:+.2f}% |")
        lines.append("")

        # Top-5 Biggest Gaps
        top5 = evr.get("top5_gap", [])
        if top5:
            lines.append("### Top-5 Model Surprises (largest rank vs return gap)")
            lines.append("")
            lines.append("| Ticker | Bucket | Rank | Return | Gap Score |")
            lines.append("|--------|--------|------|--------|-----------|")
            for g in top5:
                lines.append(
                    f"| {g['ticker']} "
                    f"| {BUCKET_DISPLAY.get(g['bucket'], g['bucket'])} "
                    f"| {g['rank']} | {g['return_pct']:+.2f}% | {g['gap']:.3f} |"
                )
            lines.append("")

        # Write diagnostics sidecar
        _diag_dir = out_path.parent / "diagnostics"
        _write_diagnostics_json(evr, as_of_date, _diag_dir)

    # --- Secondary Regulatory Coverage ---
    reg_cov = _compute_regulatory_coverage(positions)
    lines.append("## Secondary Regulatory Coverage")
    lines.append("")
    lines.append(
        f"**Regulatory names**: {reg_cov['n_regulatory']} / {reg_cov['n_eligible']} "
        f"eligible ({reg_cov['coverage_pct']:.1f}%)"
    )
    lines.append("")

    # Per-bucket regulatory vs clinical breakdown
    _fam_mode = policy.get("family_filter_mode", "primary")
    _fam_targets = policy.get("family_targets", {})
    if _fam_mode == "secondary" or _fam_targets:
        lines.append("### Regulatory Sleeve by Bucket")
        lines.append("")
        lines.append("| Bucket | Reg Names | Reg $ | Clin Names | Clin $ | Reg Target | Reg Actual |")
        lines.append("|--------|-----------|-------|------------|--------|------------|------------|")
        for b in BUCKET_NAMES:
            b_pos = [p for p in positions if p["bucket"] == b]
            if not b_pos:
                continue
            reg_pos = [p for p in b_pos if p.get("effective_family") == "REGULATORY"]
            clin_pos = [p for p in b_pos if p.get("effective_family") != "REGULATORY"]
            reg_dollars = sum(p["target_dollars"] for p in reg_pos)
            clin_dollars = sum(p["target_dollars"] for p in clin_pos)
            total_dollars = reg_dollars + clin_dollars
            reg_actual_pct = (reg_dollars / total_dollars * 100) if total_dollars > 0 else 0.0
            tgt = _fam_targets.get(b, {})
            reg_target_pct = tgt.get("REGULATORY", 0) * 100 if tgt else 0.0
            reg_target_str = f"{reg_target_pct:.0f}%" if tgt else "—"
            lines.append(
                f"| {BUCKET_DISPLAY.get(b, b)} "
                f"| {len(reg_pos)} | ${reg_dollars:,.0f} "
                f"| {len(clin_pos)} | ${clin_dollars:,.0f} "
                f"| {reg_target_str} | {reg_actual_pct:.1f}% |"
            )
        lines.append("")

        # Avg regulatory_days for held regulatory names
        reg_days_vals = []
        for p in positions:
            if p.get("effective_family") == "REGULATORY":
                rd = p.get("regulatory_days", "")
                if rd:
                    try:
                        reg_days_vals.append(float(rd))
                    except (ValueError, TypeError):
                        pass
        if reg_days_vals:
            avg_rd = sum(reg_days_vals) / len(reg_days_vals)
            lines.append(f"**Avg regulatory days (held)**: {avg_rd:.0f}d across {len(reg_days_vals)} names")
        else:
            lines.append("**Avg regulatory days (held)**: —")
        lines.append("")

    # Regulatory Ladder breakdown (if ladder enabled)
    _ladder_enabled = policy.get("regulatory_ladder_enabled", False)
    reg_positions_with_sub = [p for p in positions if p.get("reg_sub_bucket")]
    if _ladder_enabled and reg_positions_with_sub:
        lines.append("### Regulatory Ladder")
        lines.append("")
        lines.append("| Sub-bucket | Names | $ | Avg Days | Avg Quality | Min Q | Max Q | Cap |")
        lines.append("|------------|-------|---|----------|-------------|-------|-------|-----|")
        _ladder_caps = policy.get("regulatory_bucket_caps_pct", {})
        for sb in REG_LADDER_NAMES:
            sb_pos = [p for p in reg_positions_with_sub if p.get("reg_sub_bucket") == sb]
            if not sb_pos:
                continue
            sb_dollars = sum(p["target_dollars"] for p in sb_pos)
            sb_days = []
            sb_quals = []
            for p in sb_pos:
                rd = p.get("regulatory_days", "")
                if rd:
                    try:
                        sb_days.append(float(rd))
                    except (ValueError, TypeError):
                        pass
                rq = _safe_float(p.get("regulatory_quality", ""), 0.0)
                sb_quals.append(rq)
            avg_d = sum(sb_days) / len(sb_days) if sb_days else 0.0
            avg_q = sum(sb_quals) / len(sb_quals) if sb_quals else 0.0
            min_q = min(sb_quals) if sb_quals else 0.0
            max_q = max(sb_quals) if sb_quals else 0.0
            cap_str = f"{_ladder_caps[sb]:.2f}%" if sb in _ladder_caps else "—"
            lines.append(
                f"| {REG_LADDER_DISPLAY.get(sb, sb)} "
                f"| {len(sb_pos)} | ${sb_dollars:,.0f} "
                f"| {avg_d:.0f}d | {avg_q:.2f} | {min_q:.2f} | {max_q:.2f} | {cap_str} |"
            )
        lines.append("")

        # Top 5 per ladder bucket
        for sb in REG_LADDER_NAMES:
            sb_pos = [p for p in reg_positions_with_sub if p.get("reg_sub_bucket") == sb]
            if not sb_pos:
                continue
            sb_pos_sorted = sorted(sb_pos, key=lambda p: p["target_dollars"], reverse=True)[:5]
            lines.append(f"**{REG_LADDER_DISPLAY.get(sb, sb)} — top {len(sb_pos_sorted)}:**")
            lines.append("")
            lines.append("| Ticker | Days | Event | Quality | $ | Secondary? |")
            lines.append("|--------|------|-------|---------|---|------------|")
            for p in sb_pos_sorted:
                rd = p.get("regulatory_days", "—")
                ret = p.get("regulatory_event_type", "—")
                rq = _safe_float(p.get("regulatory_quality", ""), 0.0)
                is_sec = "yes" if p.get("regulatory_is_secondary") else "no"
                lines.append(f"| {p['ticker']} | {rd} | {ret} | {rq:.2f} | ${p['target_dollars']:,.0f} | {is_sec} |")
            lines.append("")

    if reg_cov["top_imminent"]:
        lines.append("**Top imminent regulatory catalysts:**")
        lines.append("")
        lines.append("| Ticker | Event | Days | Bucket | Secondary? |")
        lines.append("|--------|-------|------|--------|------------|")
        for p in reg_cov["top_imminent"]:
            rd = p.get("regulatory_days", "—")
            ret = p.get("regulatory_event_type", "—")
            bkt = BUCKET_DISPLAY.get(p.get("bucket", ""), p.get("bucket", ""))
            is_sec = "yes" if p.get("regulatory_is_secondary") else "no"
            lines.append(f"| {p['ticker']} | {ret} | {rd} | {bkt} | {is_sec} |")
        lines.append("")
    else:
        lines.append("No positions with upcoming regulatory catalysts within 180d.")
        lines.append("")

    # --- Resolved Regulatory ---
    resolved_reg = summary.get("resolved_regulatory", [])
    if resolved_reg:
        lines.append("## Resolved Regulatory (Demoted to 0%)")
        lines.append("")
        lines.append(
            f"**{len(resolved_reg)} name(s)** had regulatory event pass — " f"auto-demoted to 0% target this rebalance."
        )
        lines.append("")
        lines.append("| Ticker | Event | Days |")
        lines.append("|--------|-------|------|")
        for r in resolved_reg:
            lines.append(f"| {r['ticker']} | {r['regulatory_event_type'] or '—'} " f"| {r['regulatory_days'] or '—'} |")
        lines.append("")

    # --- Fill Annotation ---
    try:
        _fills_csv = SHADOW_ROOT / "trades" / as_of_date / "fills.csv"
        if _fills_csv.is_file():
            from tools.record_fills import compute_execution_quality

            _eq = compute_execution_quality(_fills_csv)
            n_filled = _eq.get("n_filled", 0)
            n_total = _eq.get("total", 0)
            avg_slip = _eq.get("mean_slippage_bps", 0)
            lines.append(f"**Fills**: {n_filled}/{n_total} filled, avg slippage {avg_slip:.0f}bps")
            lines.append("")
        else:
            lines.append("**Fills**: no fills imported")
            lines.append("")
    except Exception:
        pass

    # --- Reg Calendar Health ---
    try:
        from common.regulatory_calendar import get_calendar_telemetry, load_and_validate

        _cal_records, _cal_errors = load_and_validate(as_of_date=as_of_date)
        _cal_tel = get_calendar_telemetry(_cal_records)
        lines.append("## Reg Calendar Health")
        lines.append("")
        _cal_n = _cal_tel.get("manual_calendar_n_records", 0)
        lines.append(f"**PIT-eligible records**: {_cal_n}")
        if _cal_tel.get("manual_calendar_by_event_type"):
            lines.append(f"**By event type**: {_cal_tel['manual_calendar_by_event_type']}")
        if _cal_tel.get("manual_calendar_by_confidence"):
            lines.append(f"**By confidence**: {_cal_tel['manual_calendar_by_confidence']}")
        # Freshness: newest disclosed_at
        if _cal_records:
            _newest = max(
                (r.get("as_of_disclosed_at", "") for r in _cal_records),
                default="",
            )
            if _newest:
                lines.append(f"**Newest disclosed_at**: {_newest}")
            # Soonest upcoming
            _upcoming = []
            for r in _cal_records:
                rd = r.get("pdufa_date", "")
                if rd > as_of_date:
                    _upcoming.append(r)
            _upcoming.sort(key=lambda r: r.get("pdufa_date", ""))
            if _upcoming:
                lines.append(
                    f"**Soonest upcoming**: {_upcoming[0]['ticker']} "
                    f"{_upcoming[0].get('event_type', 'PDUFA')} "
                    f"on {_upcoming[0]['pdufa_date']}"
                )
        if _cal_errors:
            lines.append(f"**Validation errors**: {len(_cal_errors)}")
        lines.append("")
    except Exception:
        pass  # Calendar health is best-effort

    # Top holdings
    lines.append("## Top 10 Holdings")
    lines.append("")
    lines.append("| Rank | Ticker | Bucket | Weight | $ | Gap Risk |")
    lines.append("|------|--------|--------|--------|---|----------|")
    top10 = sorted(positions, key=lambda p: (-p["target_dollars"], p["ticker"]))[:10]
    for p in top10:
        lines.append(
            f"| {p['actionable_rank']} | {p['ticker']} "
            f"| {BUCKET_DISPLAY.get(p['bucket'], p['bucket'])} "
            f"| {p['weight_pct']:.2f}% | ${p['target_dollars']:,.0f} "
            f"| {p['gap_risk'] or '-'} |"
        )
    lines.append("")

    text = "\n".join(lines)
    with open(out_path, "w") as f:
        f.write(text)
    return out_path


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def run_shadow_portfolio(
    snap_dir: Path,
    *,
    policy_path: Optional[Path] = None,
    account_usd: Optional[float] = None,
    price_path: Path = PRICE_HISTORY_PATH,
    shadow_root: Path = SHADOW_ROOT,
) -> Dict[str, Any]:
    """Main entry point: build positions, compute performance, write outputs.

    Returns dict with positions_path, performance, summary.
    """
    _assert_not_production_default("price_path", price_path, PRICE_HISTORY_PATH)
    _assert_not_production_default("shadow_root", shadow_root, SHADOW_ROOT)
    policy = load_policy(policy_path)
    if account_usd is not None:
        policy["account_usd"] = account_usd

    rankings = load_rankings(snap_dir)
    metadata = load_metadata(snap_dir)
    as_of_date = metadata.get("as_of_date", snap_dir.name)

    # Build positions
    positions_data = build_positions(rankings, policy, account_usd)

    # Save positions
    pos_dir = shadow_root / "positions"
    pos_path = save_positions(as_of_date, positions_data, metadata, pos_dir)

    # Compute performance vs prior
    perf = None
    prior = load_prior_positions(as_of_date, pos_dir)
    if prior:
        prior_date, prior_positions = prior
        perf = compute_performance(
            prior_positions,
            positions_data["positions"],
            prior_date,
            as_of_date,
            price_path,
        )
        perf_csv = shadow_root / "performance.csv"
        append_performance(as_of_date, perf, metadata.get("ruleset_id", ""), perf_csv)

    # Weekly summary
    summary_path = shadow_root / "weekly_summary.md"
    write_weekly_summary(as_of_date, positions_data, perf, policy, metadata, summary_path)

    return {
        "positions_path": str(pos_path),
        "summary": positions_data["summary"],
        "performance": perf,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Live shadow portfolio tracker")
    parser.add_argument("--as-of-date", type=str, help="Snapshot date (YYYY-MM-DD)")
    parser.add_argument("--snapshot-dir", type=str, help="Snapshot directory path")
    parser.add_argument("--policy", type=str, help="Portfolio policy JSON path")
    parser.add_argument("--account-usd", type=float, help="Account value in USD")
    parser.add_argument("--price-history", type=str, help="Price history CSV path")
    parser.add_argument("--out-dir", type=str, help="Output directory")
    args = parser.parse_args()

    if args.snapshot_dir:
        snap_dir = Path(args.snapshot_dir)
    elif args.as_of_date:
        snap_dir = SNAPSHOTS_ROOT / args.as_of_date
    else:
        # Find latest snapshot
        candidates = sorted(
            (d for d in SNAPSHOTS_ROOT.iterdir() if d.is_dir() and len(d.name) == 10),
            key=lambda d: d.name,
        )
        if not candidates:
            print("ERROR: No snapshots found", file=sys.stderr)
            sys.exit(1)
        snap_dir = candidates[-1]

    if not snap_dir.is_dir():
        print(f"ERROR: Snapshot directory not found: {snap_dir}", file=sys.stderr)
        sys.exit(1)

    policy_path = Path(args.policy) if args.policy else None
    price_path = Path(args.price_history) if args.price_history else PRICE_HISTORY_PATH
    shadow_root = Path(args.out_dir) if args.out_dir else SHADOW_ROOT

    result = run_shadow_portfolio(
        snap_dir,
        policy_path=policy_path,
        account_usd=args.account_usd,
        price_path=price_path,
        shadow_root=shadow_root,
    )

    summary = result["summary"]
    print(f"Shadow portfolio: {summary['total_positions']} positions")
    print(f"Allocated: ${summary['total_allocated']:,.0f}")
    print(f"Cash: ${summary['residual_cash']:,.0f}")

    if result["performance"]:
        perf = result["performance"]
        print(f"\nP&L: ${perf['total_pnl']:,.2f} ({perf['pnl_pct']:+.2f}%)")
        if perf.get("excess_vs_xbi_pct") is not None:
            print(f"Excess vs XBI: {perf['excess_vs_xbi_pct']:+.2f}%")
        print(f"Turnover: {perf['turnover']:.1%}")
    else:
        print("\nFirst snapshot — no prior for performance comparison.")

    print(f"\nPositions: {result['positions_path']}")


if __name__ == "__main__":
    main()

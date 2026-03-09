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
        "gap_risk": {"high_days": 7, "high_cap_pct": 0.5},
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


def build_positions(
    rankings: List[Dict[str, str]],
    policy: Dict[str, Any],
    account_usd: Optional[float] = None,
) -> Dict[str, Any]:
    """Select top-K per bucket, apply caps, compute $ sizing.

    Returns a dict with:
        positions: list of position dicts
        summary: allocation summary
    """
    acct = account_usd or policy.get("account_usd", 500_000)
    bucket_targets = policy.get("bucket_targets", {})
    bucket_top_k = policy.get("bucket_top_k", {})
    bucket_name_caps = policy.get("bucket_name_caps", {})
    family_overrides = policy.get("family_overrides", {})
    gap_cfg = policy.get("gap_risk", {})
    gap_high_days = gap_cfg.get("high_days", 7)
    gap_high_cap = gap_cfg.get("high_cap_pct", 0.5)

    # Classify into buckets
    buckets: Dict[str, List[Dict[str, str]]] = {b: [] for b in BUCKET_NAMES}
    for row in rankings:
        bucket = classify_action_bucket(row)
        buckets[bucket].append(row)

    # Select top-K per bucket, respecting family-level max_k limits
    selected: Dict[str, List[Dict[str, str]]] = {}
    for bucket_name in BUCKET_NAMES:
        k = bucket_top_k.get(bucket_name, 20)
        bucket_rows = buckets[bucket_name][:k]
        fam_cfg = family_overrides.get(bucket_name, {})
        if fam_cfg:
            # Apply per-family max_k: group by family, cap each, reassemble
            by_family: Dict[str, List[Dict[str, str]]] = {}
            for row in bucket_rows:
                fam = (row.get("catalyst_family") or "OTHER").upper()
                by_family.setdefault(fam, []).append(row)
            capped: List[Dict[str, str]] = []
            for fam, fam_rows in by_family.items():
                fam_k = fam_cfg.get(fam, {}).get("max_k")
                if fam_k is not None:
                    fam_rows = fam_rows[:fam_k]
                capped.extend(fam_rows)
            # Re-sort by actionable_rank to maintain deterministic order
            capped.sort(key=lambda r: (_safe_float(r.get("actionable_rank", ""), 9999), r.get("ticker", "")))
            selected[bucket_name] = capped
        else:
            selected[bucket_name] = bucket_rows

    # Compute target weight per position
    positions = []
    for bucket_name in BUCKET_NAMES:
        target_frac = bucket_targets.get(bucket_name, 0.25)
        bucket_cap = bucket_name_caps.get(bucket_name, 5.0)
        fam_cfg = family_overrides.get(bucket_name, {})
        rows = selected[bucket_name]
        n = len(rows)
        if n == 0:
            continue

        # Equal weight within bucket, then cap
        equal_wt = (target_frac * 100.0) / n
        for row in rows:
            fam = (row.get("catalyst_family") or "OTHER").upper()
            # Family-level name cap overrides bucket-level cap
            fam_cap = fam_cfg.get(fam, {}).get("name_cap_pct")
            eff_cap = fam_cap if fam_cap is not None else bucket_cap
            wt = min(equal_wt, eff_cap)

            # Gap-risk cap for binary_0_30
            cat_days = _safe_float(row.get("catalyst_days", ""), float("inf"))
            cat_mode = (row.get("catalyst_mode") or "").strip().lower()
            gap_risk = ""
            if bucket_name == "binary_0_30":
                if cat_mode in ("specific_days", "blended_window"):
                    if cat_days <= gap_high_days:
                        gap_risk = "HIGH"
                        wt = min(wt, gap_high_cap)
                    elif cat_days <= 30:
                        gap_risk = "MODERATE"

            # Price coverage
            source = (row.get("de_beta_xbi_60d_source") or "").strip()
            price_coverage = "OK" if source else "MISSING"

            dollars = round(acct * wt / 100.0, 2)

            positions.append(
                {
                    "ticker": row.get("ticker", ""),
                    "bucket": bucket_name,
                    "catalyst_family": fam,
                    "actionable_rank": int(_safe_float(row.get("actionable_rank", ""), 9999)),
                    "tier": row.get("tier_any", ""),
                    "size_band": row.get("size_band", ""),
                    "catalyst_days": row.get("catalyst_days", ""),
                    "catalyst_mode": row.get("catalyst_mode", ""),
                    "mom_state": row.get("mom_state", ""),
                    "weight_pct": round(wt, 4),
                    "target_dollars": dollars,
                    "gap_risk": gap_risk,
                    "price_coverage": price_coverage,
                }
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
# Performance computation
# ---------------------------------------------------------------------------


def compute_performance(
    prior_positions: List[Dict[str, Any]],
    current_positions: List[Dict[str, Any]],
    prior_date: str,
    current_date: str,
    price_path: Path = PRICE_HISTORY_PATH,
) -> Dict[str, Any]:
    """Compute realized P&L between two position snapshots.

    Returns dict with total_pnl, pnl_pct, excess_vs_xbi, sleeve attribution,
    turnover metrics.
    """
    prior_prices = load_price_map(price_path, prior_date)
    current_prices = load_price_map(price_path, current_date)
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

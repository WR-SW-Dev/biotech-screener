#!/usr/bin/env python3
"""Build Decision Memo — 1-page IC-style output from a promoted snapshot.

Reads a snapshot's rankings.csv, metadata.json, run_manifest.json, and
optionally compares to the previous promoted snapshot.  Produces a
DECISION_MEMO.md (and optional .json) that serves as the "human interface"
for a repeatable weekly/daily action loop.

Sections:
    1. Provenance header (date, ruleset, engine, gates)
    2. Allocation summary (per-bucket and per-band dollar amounts)
    3. Risk rails (gap risk, price coverage)
    4. Action lists (top 10 per bucket)
    5. Change vs prior snapshot (overlap, biggest movers)
    6. "What to do" bullets

Usage:
    python3 tools/build_decision_memo.py --as-of-date 2026-03-08 --account-usd 500000
    python3 tools/build_decision_memo.py --snapshot-dir data/snapshots/2026-03-08 \\
        --account-usd 500000 --bucket-targets binary_0_30=0.10,binary_91_180=0.50
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
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from build_action_lists import (
    BUCKET_DISPLAY,
    BUCKET_NAMES,
    GAP_RISK_IMMINENT_DAYS,
    apply_account_sizing,
    apply_bucket_targets,
    apply_risk_rails,
    build_action_lists,
)

SNAPSHOTS_ROOT = PROJECT_ROOT / "data" / "snapshots"


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


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _find_prior_snapshot(snap_dir: Path) -> Optional[Path]:
    """Find the most recent promoted snapshot before snap_dir."""
    parent = snap_dir.parent
    current = snap_dir.name
    candidates = []
    for d in parent.iterdir():
        if not d.is_dir():
            continue
        name = d.name
        if len(name) == 10 and name[4] == "-" and name[7] == "-" and name < current:
            if (d / "rankings.csv").is_file():
                candidates.append(name)
    if not candidates:
        return None
    return parent / max(candidates)


def _load_rankings(snap_dir: Path) -> List[Dict[str, str]]:
    csv_path = snap_dir / "rankings.csv"
    if not csv_path.is_file():
        return []
    with open(csv_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _build_provenance(
    snap_dir: Path,
    metadata: Optional[Dict[str, Any]],
    manifest: Optional[Dict[str, Any]],
) -> List[str]:
    lines = ["# Decision Memo", ""]
    date = metadata.get("as_of_date", snap_dir.name) if metadata else snap_dir.name
    lines.append(f"**As-of date**: {date}")
    lines.append(f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    if metadata:
        lines.append(f"**Ruleset**: {metadata.get('ruleset_id', '?')} " f"(hash: {metadata.get('ruleset_hash', '?')})")
        ev = metadata.get("engine_version", metadata.get("version", "?"))
        ev_str = ev if ev.startswith("v") else f"v{ev}"
        lines.append(f"**Engine**: {ev_str}")
        lines.append(f"**Git SHA**: {metadata.get('git_sha', 'n/a')}")
        lines.append(
            f"**Universe**: {metadata.get('ticker_count', '?')} ranked "
            f"/ {metadata.get('total_evaluated', '?')} evaluated"
        )

    if manifest:
        overall = manifest.get("overall_status", "?")
        lines.append(f"**Snapshot status**: {overall}")
        gates = manifest.get("gates", [])
        warns = [g for g in gates if g.get("status") == "WARN"]
        fails = [g for g in gates if g.get("status") == "FAIL"]
        if fails:
            lines.append("")
            lines.append(f"**FAIL gates ({len(fails)}):**")
            for g in fails:
                lines.append(f"- `{g['name']}`: {g.get('detail', '')[:80]}")
        if warns:
            lines.append("")
            lines.append(f"**WARN gates ({len(warns)}):**")
            for g in warns:
                lines.append(f"- `{g['name']}`: {g.get('detail', '')[:80]}")

    lines.append("")
    return lines


def _build_allocation(
    buckets: Dict[str, List[Dict[str, str]]],
    sizing_summary: Dict[str, Any],
) -> List[str]:
    lines = ["## Allocation Summary", ""]
    acct = sizing_summary["account_usd"]
    alloc = sizing_summary["total_allocated"]
    cash = sizing_summary["residual_cash"]
    lines.append(
        f"**Account**: ${acct:,.0f} | "
        f"**Allocated**: ${alloc:,.2f} | "
        f"**Cash**: ${cash:,.2f} ({cash / acct * 100:.1f}%)"
    )
    lines.append("")

    # Bucket table
    lines.append("| Bucket | Names | Weight | Allocated | % of Account |")
    lines.append("|--------|-------|--------|-----------|-------------|")
    for b in BUCKET_NAMES:
        rows = buckets.get(b, [])
        n = len(rows)
        wt = sum(_safe_float(r.get("weight_pct_capped", r.get("target_weight_pct", ""))) for r in rows)
        dollars = sizing_summary["per_bucket"].get(b, 0.0)
        pct = dollars / acct * 100 if acct > 0 else 0
        display = BUCKET_DISPLAY.get(b, b)
        lines.append(f"| {display} | {n} | {wt:.1f}% | ${dollars:,.0f} | {pct:.1f}% |")
    lines.append("")

    # Band table
    lines.append("| Band | Allocated | % of Account |")
    lines.append("|------|-----------|-------------|")
    for band in sorted(sizing_summary["per_band"].keys()):
        dollars = sizing_summary["per_band"][band]
        pct = dollars / acct * 100 if acct > 0 else 0
        lines.append(f"| {band} | ${dollars:,.0f} | {pct:.1f}% |")
    lines.append("")
    return lines


def _build_risk_rails(
    buckets: Dict[str, List[Dict[str, str]]],
) -> List[str]:
    lines = ["## Risk Rails", ""]

    high_gap = [r for r in buckets.get("binary_0_30", []) if r.get("gap_risk") == "HIGH"]
    if high_gap:
        lines.append(f"**Gap Risk HIGH** ({len(high_gap)} names, catalyst <= {GAP_RISK_IMMINENT_DAYS}d):")
        lines.append("")
        lines.append("| Ticker | Days | Weight | $ |")
        lines.append("|--------|------|--------|---|")
        for r in high_gap:
            lines.append(
                f"| {r.get('ticker', '')} "
                f"| {r.get('catalyst_days', '')} "
                f"| {_safe_float(r.get('weight_pct_capped', r.get('target_weight_pct', ''))):.2f}% "
                f"| ${_safe_float(r.get('target_dollars', '')):,.0f} |"
            )
        lines.append("")
    else:
        lines.append("- Gap risk HIGH: none")
        lines.append("")

    all_rows = [r for rows in buckets.values() for r in rows]
    missing_price = [r for r in all_rows if r.get("price_coverage") == "MISSING"]
    if missing_price:
        tickers = ", ".join(r.get("ticker", "") for r in missing_price)
        lines.append(f"**Price coverage MISSING** ({len(missing_price)} names): {tickers}")
    else:
        lines.append("- Price coverage: all names OK")
    lines.append("")
    return lines


def _build_action_lists(
    buckets: Dict[str, List[Dict[str, str]]],
    top_n: int = 10,
) -> List[str]:
    lines = ["## Action Lists (top 10 per bucket)", ""]

    for b in BUCKET_NAMES:
        rows = buckets.get(b, [])
        display = BUCKET_DISPLAY.get(b, b)
        lines.append(f"### {display} ({len(rows)} names)")
        lines.append("")
        if not rows:
            lines.append("*(empty)*")
            lines.append("")
            continue
        lines.append("| Rank | Ticker | Days | Tier | Mom | Weight | $ |")
        lines.append("|------|--------|------|------|-----|--------|---|")
        for r in rows[:top_n]:
            lines.append(
                f"| {r.get('actionable_rank', '')} "
                f"| {r.get('ticker', '')} "
                f"| {r.get('catalyst_days', '')} "
                f"| {r.get('tier_any', '')} "
                f"| {r.get('mom_state', '')} "
                f"| {_safe_float(r.get('weight_pct_capped', r.get('target_weight_pct', ''))):.2f}% "
                f"| ${_safe_float(r.get('target_dollars', '')):,.0f} |"
            )
        if len(rows) > top_n:
            lines.append(f"| ... | *{len(rows) - top_n} more* | | | | | |")
        lines.append("")
    return lines


def _build_change_vs_prior(
    snap_dir: Path,
    buckets: Dict[str, List[Dict[str, str]]],
) -> List[str]:
    prior_dir = _find_prior_snapshot(snap_dir)
    if not prior_dir:
        return ["## Change vs Prior Snapshot", "", "*No prior snapshot found.*", ""]

    prior_rankings = _load_rankings(prior_dir)
    current_rankings = _load_rankings(snap_dir)

    # Build rank maps (ticker → actionable_rank)
    def _rank_map(rankings):
        m = {}
        for r in rankings:
            t = r.get("ticker", "")
            rank = r.get("actionable_rank", "")
            if t and rank:
                try:
                    m[t] = int(float(rank))
                except (ValueError, TypeError):
                    pass
        return m

    prev_ranks = _rank_map(prior_rankings)
    curr_ranks = _rank_map(current_rankings)

    # Top-20 overlap
    prev_top20 = set(sorted(prev_ranks, key=lambda t: prev_ranks[t])[:20])
    curr_top20 = set(sorted(curr_ranks, key=lambda t: curr_ranks[t])[:20])
    overlap = prev_top20 & curr_top20
    overlap_pct = len(overlap) / 20 * 100 if prev_top20 else 0

    lines = ["## Change vs Prior Snapshot", ""]
    lines.append(f"**Prior**: {prior_dir.name}")
    lines.append(f"**Top-20 overlap**: {len(overlap)}/20 ({overlap_pct:.0f}%)")
    lines.append("")

    # Biggest movers (rank delta)
    deltas: List[Tuple[str, int]] = []
    for ticker in set(prev_ranks) & set(curr_ranks):
        delta = prev_ranks[ticker] - curr_ranks[ticker]  # positive = improved
        deltas.append((ticker, delta))

    if deltas:
        deltas.sort(key=lambda x: -x[1])
        top_up = deltas[:10]
        top_down = deltas[-10:]
        top_down.reverse()

        lines.append("### Biggest improvers (rank up)")
        lines.append("")
        lines.append("| Ticker | Prev Rank | Curr Rank | Delta |")
        lines.append("|--------|-----------|-----------|-------|")
        for t, d in top_up:
            if d <= 0:
                break
            lines.append(f"| {t} | {prev_ranks[t]} | {curr_ranks[t]} | +{d} |")
        lines.append("")

        lines.append("### Biggest decliners (rank down)")
        lines.append("")
        lines.append("| Ticker | Prev Rank | Curr Rank | Delta |")
        lines.append("|--------|-----------|-----------|-------|")
        for t, d in top_down:
            if d >= 0:
                break
            lines.append(f"| {t} | {prev_ranks[t]} | {curr_ranks[t]} | {d} |")
        lines.append("")

    # New entries / exits
    new_tickers = set(curr_ranks) - set(prev_ranks)
    exited_tickers = set(prev_ranks) - set(curr_ranks)
    if new_tickers:
        lines.append(
            f"**New entries**: {', '.join(sorted(new_tickers)[:10])}"
            + (f" (+{len(new_tickers) - 10} more)" if len(new_tickers) > 10 else "")
        )
    if exited_tickers:
        lines.append(
            f"**Exited**: {', '.join(sorted(exited_tickers)[:10])}"
            + (f" (+{len(exited_tickers) - 10} more)" if len(exited_tickers) > 10 else "")
        )
    lines.append("")
    return lines


def _build_action_bullets(
    buckets: Dict[str, List[Dict[str, str]]],
    sizing_summary: Dict[str, Any],
) -> List[str]:
    lines = ["## What To Do", ""]
    acct = sizing_summary["account_usd"]

    # Gap risk
    high_gap = [r for r in buckets.get("binary_0_30", []) if r.get("gap_risk") == "HIGH"]
    if high_gap:
        gap_dollars = sum(_safe_float(r.get("target_dollars", "")) for r in high_gap)
        lines.append(
            f"- **Binary 0-30 has {len(high_gap)} HIGH gap-risk names** "
            f"(${gap_dollars:,.0f} / {gap_dollars / acct * 100:.1f}% of account). "
            f"Consider halving position size or waiting for post-event entry."
        )

    # Price coverage
    all_rows = [r for rows in buckets.values() for r in rows]
    missing_price = [r for r in all_rows if r.get("price_coverage") == "MISSING"]
    if missing_price:
        lines.append(
            f"- **{len(missing_price)} names missing price coverage** "
            f"({', '.join(r['ticker'] for r in missing_price)}). "
            f"No beta/drawdown metrics — size conservatively or skip."
        )

    # Concentration check
    for b in BUCKET_NAMES:
        bucket_alloc = sizing_summary["per_bucket"].get(b, 0.0)
        pct = bucket_alloc / acct * 100 if acct > 0 else 0
        if pct > 40:
            display = BUCKET_DISPLAY.get(b, b)
            lines.append(
                f"- **{display} is {pct:.0f}% of account** — "
                f"consider --bucket-targets to rebalance toward your 90-180d objective."
            )

    # Cash
    cash = sizing_summary["residual_cash"]
    if cash > acct * 0.10:
        lines.append(
            f"- **{cash / acct * 100:.0f}% cash** (${cash:,.0f}). " f"High residual — check if band caps are too tight."
        )
    elif cash < 0:
        lines.append(f"- **Overage**: ${-cash:,.0f} over account — should not happen with trim logic.")

    if not lines[2:]:
        lines.append("- No immediate action flags. Review top-10 per bucket and proceed.")

    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def build_decision_memo(
    snap_dir: Path,
    account_usd: float,
    *,
    band_caps: Optional[Dict[str, float]] = None,
    bucket_targets: Optional[Dict[str, float]] = None,
    top_n: int = 10,
) -> Tuple[str, Dict[str, Any]]:
    """Build the full decision memo.

    Returns (memo_md_text, memo_json_dict).
    """
    metadata = _load_json(snap_dir / "metadata.json")
    manifest = _load_json(snap_dir / "run_manifest.json")

    # Build action lists
    buckets = build_action_lists(snap_dir)

    # Apply bucket targets if specified
    if bucket_targets:
        apply_bucket_targets(buckets, bucket_targets)

    # Risk rails
    apply_risk_rails(buckets)

    # Account sizing
    sizing_summary = apply_account_sizing(buckets, account_usd, band_caps)

    # Build memo sections
    sections: List[str] = []
    sections.extend(_build_provenance(snap_dir, metadata, manifest))
    sections.extend(_build_allocation(buckets, sizing_summary))
    sections.extend(_build_risk_rails(buckets))
    sections.extend(_build_action_lists(buckets, top_n))
    sections.extend(_build_change_vs_prior(snap_dir, buckets))
    sections.extend(_build_action_bullets(buckets, sizing_summary))

    memo_text = "\n".join(sections)

    # JSON sidecar
    memo_json: Dict[str, Any] = {
        "schema": "decision_memo.v1",
        "as_of_date": metadata.get("as_of_date", snap_dir.name) if metadata else snap_dir.name,
        "account_usd": account_usd,
        "sizing": sizing_summary,
        "bucket_targets": bucket_targets,
        "provenance": {
            "ruleset_id": metadata.get("ruleset_id") if metadata else None,
            "ruleset_hash": metadata.get("ruleset_hash") if metadata else None,
            "engine_version": metadata.get("engine_version", metadata.get("version")) if metadata else None,
            "overall_status": manifest.get("overall_status") if manifest else None,
        },
        "risk_flags": {
            "high_gap_risk": [
                r.get("ticker", "") for r in buckets.get("binary_0_30", []) if r.get("gap_risk") == "HIGH"
            ],
            "missing_price": [
                r.get("ticker", "")
                for r in [r for rows in buckets.values() for r in rows]
                if r.get("price_coverage") == "MISSING"
            ],
        },
    }

    return memo_text, memo_json


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Build a 1-page decision memo from a promoted snapshot.",
    )
    parser.add_argument("--snapshot-dir", type=Path, default=None)
    parser.add_argument("--as-of-date", default=None)
    parser.add_argument("--account-usd", type=float, default=500_000.0)
    parser.add_argument(
        "--out-path", type=Path, default=None, help="Output path (default: DECISION_MEMO.md in snapshot dir)"
    )
    parser.add_argument("--band-caps", default=None, help="Per-name max weight by band (KEY=VAL,...)")
    parser.add_argument("--bucket-targets", default=None, help="Bucket target fractions (KEY=VAL,...)")
    parser.add_argument("--top-n", type=int, default=10, help="Names per bucket in action list section")
    args = parser.parse_args()

    if args.snapshot_dir:
        snap_dir = args.snapshot_dir
    elif args.as_of_date:
        snap_dir = SNAPSHOTS_ROOT / args.as_of_date
    else:
        # Find latest
        candidates = [d.name for d in SNAPSHOTS_ROOT.iterdir() if d.is_dir() and len(d.name) == 10 and d.name[4] == "-"]
        if not candidates:
            print("ERROR: No snapshots found.", file=sys.stderr)
            sys.exit(1)
        snap_dir = SNAPSHOTS_ROOT / max(candidates)

    if not snap_dir.is_dir():
        print(f"ERROR: {snap_dir} not found.", file=sys.stderr)
        sys.exit(1)

    band_caps = None
    if args.band_caps:
        band_caps = {}
        for pair in args.band_caps.split(","):
            k, v = pair.strip().split("=")
            band_caps[k.strip()] = float(v.strip())

    bucket_targets = None
    if args.bucket_targets:
        bucket_targets = {}
        for pair in args.bucket_targets.split(","):
            k, v = pair.strip().split("=")
            bucket_targets[k.strip()] = float(v.strip())

    memo_text, memo_json = build_decision_memo(
        snap_dir,
        args.account_usd,
        band_caps=band_caps,
        bucket_targets=bucket_targets,
        top_n=args.top_n,
    )

    out_path = args.out_path or (snap_dir / "DECISION_MEMO.md")
    out_path.write_text(memo_text, encoding="utf-8")

    json_path = out_path.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(memo_json, f, indent=2, default=str)

    print(f"Decision memo → {out_path}")
    print(f"Decision JSON → {json_path}")


if __name__ == "__main__":
    main()

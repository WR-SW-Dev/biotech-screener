#!/usr/bin/env python3
"""Weekly Attribution Packet — position-level P&L explanation + signal alignment.

Outputs:
    artifacts/live_shadow/attribution/{YYYY-MM-DD}/ATTRIBUTION_PACKET.json
    artifacts/live_shadow/attribution/{YYYY-MM-DD}/ATTRIBUTION_PACKET.md

Sections:
  1. Top Contributors — top/bottom 10 by realized P&L
  2. Signal Alignment — Spearman rank vs next-week returns
  3. Why We Held These — top 3 sort contributions per position per bucket
  4. Event Proximity Rails — regulatory + clinical proximity band heatmap
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import BUCKET_DISPLAY, BUCKET_NAMES, POSITIONS_DIR, SHADOW_ROOT, SNAPSHOTS_ROOT

ATTRIBUTION_ROOT = SHADOW_ROOT / "attribution"
SCHEMA_VERSION = "attribution_packet.v1"

# Minimum positions for correlation to be meaningful
MIN_POSITIONS_FOR_CORRELATION = 5

# Proximity bands (days)
PROXIMITY_BANDS = [
    ("0-7", 0, 7),
    ("8-14", 8, 14),
    ("15-45", 15, 45),
    ("46-90", 46, 90),
    ("91-180", 91, 180),
    (">180/NA", 181, 999999),
]


# ---------------------------------------------------------------------------
# Production-path guards
# ---------------------------------------------------------------------------

_PRODUCTION_PATHS = {
    "attribution_root": ATTRIBUTION_ROOT,
    "positions_dir": POSITIONS_DIR,
    "snap_root": SNAPSHOTS_ROOT,
}


def _in_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ


def _assert_not_production_default(name: str, value: Path, production_default: Path) -> None:
    if _in_pytest() and value == production_default:
        raise AssertionError(f"Tests must pass `{name}` explicitly — got production default {production_default}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_top_3_drivers(raw: str) -> List[Dict[str, Any]]:
    """Parse 'name:+value;name:-value;...' into list of {name, value}."""
    if not raw or not raw.strip():
        return []
    parts = raw.strip().split(";")
    result = []
    for part in parts[:3]:
        if ":" not in part:
            continue
        name, val_str = part.split(":", 1)
        try:
            val = float(val_str)
        except (ValueError, TypeError):
            val = 0.0
        result.append({"name": name.strip(), "value": round(val, 2)})
    return result


def _classify_proximity_band(days: Optional[float]) -> str:
    """Map days-to-event to a proximity band label."""
    if days is None or (isinstance(days, float) and math.isnan(days)):
        return ">180/NA"
    try:
        d = float(days)
    except (ValueError, TypeError):
        return ">180/NA"
    for label, lo, hi in PROXIMITY_BANDS:
        if lo <= d <= hi:
            return label
    return ">180/NA"


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        f = float(val)
        return f if math.isfinite(f) else default
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Section 1: Top Contributors
# ---------------------------------------------------------------------------


def build_top_contributors(
    contributors: List[Dict[str, Any]],
    entry_annotations: Optional[Dict[str, Dict[str, Any]]],
    close_prices: Dict[str, float],
    fill_prices: Dict[str, float],
    current_prices: Dict[str, float],
    xbi_return: Optional[float],
    portfolio_notional: float,
    n: int = 10,
) -> Dict[str, Any]:
    """Build top/bottom N contributors with realized vs theoretical P&L.

    Args:
        contributors: From compute_performance() — sorted by P&L desc.
        entry_annotations: Per-ticker {entry_price_source, entry_price, ...}.
        close_prices: Close prices for prior date.
        fill_prices: Fill VWAP prices for prior date (empty if no fills).
        current_prices: Close prices for current date.
        xbi_return: XBI return for the period (decimal, not %).
        portfolio_notional: Total portfolio notional (for hedged contribution).
        n: Number of top/bottom contributors.
    """
    enriched = []
    ann = entry_annotations or {}

    for c in contributors:
        ticker = c["ticker"]
        dollars = c.get("dollars", 0)
        bucket = c.get("bucket", "")
        family = c.get("effective_family", c.get("family", ""))

        # Entry annotation
        a = ann.get(ticker, {})
        source = a.get("entry_price_source", "CLOSE")

        # Realized P&L (already in contributor — uses fill prices when available)
        realized_pnl = c.get("pnl", 0)
        realized_ret = c.get("return_pct", 0)

        # Theoretical P&L (close-based)
        p_close = close_prices.get(ticker)
        p_current = current_prices.get(ticker)
        if p_close and p_current and p_close > 0 and dollars > 0:
            theo_ret = (p_current / p_close - 1.0) * 100
            theo_pnl = dollars * (p_current / p_close - 1.0)
        else:
            theo_ret = realized_ret
            theo_pnl = realized_pnl

        # Weight
        weight_pct = (dollars / portfolio_notional * 100) if portfolio_notional > 0 else 0

        # Hedged contribution (excess * weight * notional)
        hedged = 0.0
        if xbi_return is not None:
            excess_ret = realized_ret / 100.0 - xbi_return
            hedged = excess_ret * dollars

        enriched.append(
            {
                "ticker": ticker,
                "bucket": bucket,
                "family": family,
                "weight_pct": round(weight_pct, 2),
                "entry_price_source": source,
                "pnl_usd_realized": round(realized_pnl, 2),
                "ret_pct_realized": round(realized_ret, 4),
                "pnl_usd_theoretical": round(theo_pnl, 2),
                "ret_pct_theoretical": round(theo_ret, 4),
                "hedged_contrib_usd_realized": round(hedged, 2),
            }
        )

    # Sort by realized P&L desc, then by ticker for deterministic ties
    enriched.sort(key=lambda x: (-x["pnl_usd_realized"], x["ticker"]))

    top_n = enriched[:n]
    bottom_n = list(reversed(enriched[-n:])) if len(enriched) > n else []
    # Remove overlap
    top_tickers = {e["ticker"] for e in top_n}
    bottom_n = [e for e in bottom_n if e["ticker"] not in top_tickers]

    return {
        "top": top_n,
        "bottom": bottom_n,
        "n_total": len(enriched),
    }


# ---------------------------------------------------------------------------
# Section 2: Signal Alignment
# ---------------------------------------------------------------------------


def build_signal_alignment(
    positions: List[Dict[str, Any]],
    returns_realized: Dict[str, float],
    returns_theoretical: Dict[str, float],
    rankings_data: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compute Spearman rank IC for held positions vs next-week returns.

    Args:
        positions: Current positions list.
        returns_realized: {ticker: realized_return_pct} (fill-adjusted).
        returns_theoretical: {ticker: theoretical_return_pct} (close-based).
        rankings_data: {ticker: {actionable_rank, score_rank_pct, ...}} from rankings CSV.
    """
    from backtest.metrics_m1 import spearman_rank_ic

    ranks_data = rankings_data or {}
    pairs_realized = []
    pairs_theoretical = []

    for pos in positions:
        ticker = pos["ticker"]
        rank_info = ranks_data.get(ticker, {})
        a_rank = _safe_float(rank_info.get("actionable_rank", pos.get("actionable_rank")))
        if a_rank <= 0:
            continue

        r_real = returns_realized.get(ticker)
        r_theo = returns_theoretical.get(ticker)

        if r_real is not None:
            pairs_realized.append((a_rank, r_real))
        if r_theo is not None:
            pairs_theoretical.append((a_rank, r_theo))

    n_positions = len(pairs_realized)

    if n_positions < MIN_POSITIONS_FOR_CORRELATION:
        return {
            "n_positions": n_positions,
            "spearman_rank_vs_realized": "UNKNOWN",
            "spearman_rank_vs_theoretical": "UNKNOWN",
            "reason": f"Fewer than {MIN_POSITIONS_FOR_CORRELATION} positions with returns",
        }

    ranks_r, rets_r = zip(*pairs_realized)
    # Negate ranks: lower rank = better → should have higher return
    # spearman_rank_ic expects higher score = better, but actionable_rank
    # is 1=best. So negate ranks to make correlation positive when signal works.
    neg_ranks_r = [-r for r in ranks_r]
    ic_realized = spearman_rank_ic(list(neg_ranks_r), list(rets_r))

    ic_theoretical = float("nan")
    if len(pairs_theoretical) >= MIN_POSITIONS_FOR_CORRELATION:
        ranks_t, rets_t = zip(*pairs_theoretical)
        neg_ranks_t = [-r for r in ranks_t]
        ic_theoretical = spearman_rank_ic(list(neg_ranks_t), list(rets_t))

    return {
        "n_positions": n_positions,
        "spearman_rank_vs_realized": round(ic_realized, 4) if math.isfinite(ic_realized) else "UNKNOWN",
        "spearman_rank_vs_theoretical": round(ic_theoretical, 4) if math.isfinite(ic_theoretical) else "UNKNOWN",
    }


# ---------------------------------------------------------------------------
# Section 3: Why We Held These
# ---------------------------------------------------------------------------


def build_why_held(
    positions: List[Dict[str, Any]],
    rankings_data: Optional[Dict[str, Dict[str, Any]]] = None,
    top_n_per_bucket: int = 5,
) -> Dict[str, List[Dict[str, Any]]]:
    """For each bucket, list top N held names with their sort contributions.

    Returns {bucket_name: [{ticker, weight_pct, drivers: [{name, value}]}]}.
    """
    ranks_data = rankings_data or {}

    # Group by bucket
    by_bucket: Dict[str, List[Dict[str, Any]]] = {}
    for pos in positions:
        bucket = pos.get("bucket", "less_binary")
        by_bucket.setdefault(bucket, []).append(pos)

    result = {}
    for bucket in BUCKET_NAMES:
        bucket_positions = by_bucket.get(bucket, [])
        # Sort by weight desc, then actionable_rank asc, then ticker for determinism
        bucket_positions.sort(
            key=lambda p: (
                -p.get("target_dollars", 0),
                _safe_float(p.get("actionable_rank", 999)),
                p["ticker"],
            )
        )

        entries = []
        for pos in bucket_positions[:top_n_per_bucket]:
            ticker = pos["ticker"]
            weight_pct = pos.get("weight_pct", 0)
            rank_row = ranks_data.get(ticker, {})
            raw_drivers = rank_row.get("top_3_drivers", "")
            drivers = _parse_top_3_drivers(raw_drivers)
            if not drivers:
                drivers = [{"name": "UNKNOWN", "value": 0.0}]

            entries.append(
                {
                    "ticker": ticker,
                    "weight_pct": round(_safe_float(weight_pct), 2),
                    "actionable_rank": int(_safe_float(pos.get("actionable_rank", 0))),
                    "drivers": drivers,
                }
            )

        if entries:
            result[bucket] = entries

    return result


# ---------------------------------------------------------------------------
# Section 4: Event Proximity Rails
# ---------------------------------------------------------------------------


def build_proximity_rails(
    positions: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Compute proximity-band heatmap for regulatory + clinical events.

    Returns:
        {
            "regulatory": {band_label: {count, total_weight_pct}},
            "clinical": {band_label: {count, total_weight_pct}},
        }
    """
    total_dollars = sum(_safe_float(p.get("target_dollars")) for p in positions) or 1.0

    reg_bands: Dict[str, Dict[str, float]] = {b[0]: {"count": 0, "total_weight_pct": 0.0} for b in PROXIMITY_BANDS}
    clin_bands: Dict[str, Dict[str, float]] = {b[0]: {"count": 0, "total_weight_pct": 0.0} for b in PROXIMITY_BANDS}

    for pos in positions:
        dollars = _safe_float(pos.get("target_dollars"))
        weight_pct = dollars / total_dollars * 100

        # Regulatory proximity
        reg_days = pos.get("regulatory_days")
        if reg_days is not None and reg_days != "":
            band = _classify_proximity_band(reg_days)
            reg_bands[band]["count"] += 1
            reg_bands[band]["total_weight_pct"] += weight_pct

        # Clinical proximity (only for CLINICAL family)
        family = pos.get("effective_family", "")
        cat_days = pos.get("catalyst_days")
        if family == "CLINICAL" and cat_days is not None and cat_days != "":
            band = _classify_proximity_band(cat_days)
            clin_bands[band]["count"] += 1
            clin_bands[band]["total_weight_pct"] += weight_pct

    # Round weights
    for bands in (reg_bands, clin_bands):
        for b in bands.values():
            b["total_weight_pct"] = round(b["total_weight_pct"], 1)

    return {"regulatory": reg_bands, "clinical": clin_bands}


# ---------------------------------------------------------------------------
# Packet builder
# ---------------------------------------------------------------------------


def load_rankings_as_dict(snap_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Load rankings.csv as {ticker: row_dict}."""
    rankings_path = snap_dir / "rankings.csv"
    if not rankings_path.is_file():
        return {}
    result = {}
    with open(rankings_path, newline="") as f:
        for row in csv.DictReader(f):
            result[row["ticker"]] = row
    return result


def build_attribution_packet(
    as_of_date: str,
    positions: List[Dict[str, Any]],
    perf: Dict[str, Any],
    policy: Dict[str, Any],
    *,
    snap_dir: Optional[Path] = None,
    snap_root: Path = SNAPSHOTS_ROOT,
    attribution_root: Path = ATTRIBUTION_ROOT,
) -> Dict[str, Any]:
    """Build the complete attribution packet.

    Args:
        as_of_date: Current date string.
        positions: Current positions list.
        perf: Performance dict from compute_performance().
        policy: Portfolio policy dict.
        snap_dir: Snapshot directory (defaults to snap_root / as_of_date).
        snap_root: Snapshot root directory.
        attribution_root: Output root directory.
    """
    _assert_not_production_default("attribution_root", attribution_root, ATTRIBUTION_ROOT)

    if snap_dir is None:
        snap_dir = snap_root / as_of_date

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    contributors = perf.get("contributors", [])
    entry_annotations = perf.get("entry_annotations")
    xbi_return = perf.get("xbi_return_pct")
    if xbi_return is not None:
        xbi_return = xbi_return / 100.0  # convert to decimal

    portfolio_notional = _safe_float(policy.get("account_usd", 500_000))

    prior_date = perf.get("prior_date", "")
    # Best-effort: price maps empty unless caller populates them
    close_prices: Dict[str, float] = {}
    current_prices: Dict[str, float] = {}
    fill_prices: Dict[str, float] = {}

    # Extract returns from contributors for signal alignment
    returns_realized: Dict[str, float] = {}
    returns_theoretical: Dict[str, float] = {}
    for c in contributors:
        ticker = c["ticker"]
        returns_realized[ticker] = c.get("return_pct", 0)
        returns_theoretical[ticker] = c.get("return_pct", 0)

    # Load rankings data for sort contributions + alignment
    rankings_data = load_rankings_as_dict(snap_dir)

    # Section 1: Top Contributors
    top_contributors = build_top_contributors(
        contributors,
        entry_annotations,
        close_prices,
        fill_prices,
        current_prices,
        xbi_return,
        portfolio_notional,
    )

    # Section 2: Signal Alignment
    signal_alignment = build_signal_alignment(
        positions,
        returns_realized,
        returns_theoretical,
        rankings_data,
    )

    # Section 3: Why We Held These
    why_held = build_why_held(positions, rankings_data)

    # Section 4: Proximity Rails
    proximity_rails = build_proximity_rails(positions)

    packet = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "prior_date": prior_date,
        "generated_at": ts,
        "top_contributors": top_contributors,
        "signal_alignment": signal_alignment,
        "why_held": why_held,
        "proximity_rails": proximity_rails,
    }

    return packet


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_attribution_packet_md(packet: Dict[str, Any]) -> str:
    """Render attribution packet as markdown string."""
    lines = []
    as_of = packet.get("as_of_date", "?")
    prior = packet.get("prior_date", "?")
    ts = packet.get("generated_at", "?")

    lines.append(f"# Attribution Packet — {as_of}")
    lines.append("")
    lines.append(f"**Period**: {prior} → {as_of}")
    lines.append(f"**Generated**: {ts}")
    lines.append("")

    # Section 1: Top Contributors
    tc = packet.get("top_contributors", {})
    lines.append("## Top Contributors (Realized P&L)")
    lines.append("")
    lines.append(f"*{tc.get('n_total', 0)} positions total*")
    lines.append("")

    def _contrib_table(items: List[Dict], label: str) -> None:
        if not items:
            return
        lines.append(f"### {label}")
        lines.append("")
        lines.append("| Ticker | Bucket | Family | Wt% | Source | Real P&L | Real % | Theo P&L | Theo % | Hedged $ |")
        lines.append("|--------|--------|--------|-----|--------|----------|--------|----------|--------|----------|")
        for e in items:
            lines.append(
                f"| {e['ticker']}"
                f" | {BUCKET_DISPLAY.get(e['bucket'], e['bucket'])}"
                f" | {e.get('family', '')}"
                f" | {e['weight_pct']:.1f}%"
                f" | {e['entry_price_source']}"
                f" | ${e['pnl_usd_realized']:,.2f}"
                f" | {e['ret_pct_realized']:+.2f}%"
                f" | ${e['pnl_usd_theoretical']:,.2f}"
                f" | {e['ret_pct_theoretical']:+.2f}%"
                f" | ${e['hedged_contrib_usd_realized']:,.2f} |"
            )
        lines.append("")

    _contrib_table(tc.get("top", []), "Top 10 Positive")
    _contrib_table(tc.get("bottom", []), "Top 10 Negative")

    # Section 2: Signal Alignment
    sa = packet.get("signal_alignment", {})
    lines.append("## Signal Alignment (Held-Only)")
    lines.append("")
    lines.append(f"- **N positions**: {sa.get('n_positions', 0)}")
    ic_r = sa.get("spearman_rank_vs_realized", "UNKNOWN")
    ic_t = sa.get("spearman_rank_vs_theoretical", "UNKNOWN")
    if ic_r != "UNKNOWN":
        lines.append(f"- **Spearman IC (rank vs realized)**: {ic_r:+.4f}")
    else:
        lines.append("- **Spearman IC (rank vs realized)**: UNKNOWN")
    if ic_t != "UNKNOWN":
        lines.append(f"- **Spearman IC (rank vs theoretical)**: {ic_t:+.4f}")
    else:
        lines.append("- **Spearman IC (rank vs theoretical)**: UNKNOWN")
    if "reason" in sa:
        lines.append(f"- *{sa['reason']}*")
    lines.append("")

    # Section 3: Why We Held These
    wh = packet.get("why_held", {})
    lines.append("## Why We Held These")
    lines.append("")
    for bucket in BUCKET_NAMES:
        entries = wh.get(bucket, [])
        if not entries:
            continue
        lines.append(f"### {BUCKET_DISPLAY.get(bucket, bucket)}")
        lines.append("")
        lines.append("| Ticker | Wt% | Rank | Driver 1 | Driver 2 | Driver 3 |")
        lines.append("|--------|-----|------|----------|----------|----------|")
        for e in entries:
            drivers = e.get("drivers", [])
            d1 = f"{drivers[0]['name']}:{drivers[0]['value']:+.1f}" if len(drivers) > 0 else "—"
            d2 = f"{drivers[1]['name']}:{drivers[1]['value']:+.1f}" if len(drivers) > 1 else "—"
            d3 = f"{drivers[2]['name']}:{drivers[2]['value']:+.1f}" if len(drivers) > 2 else "—"
            lines.append(
                f"| {e['ticker']}" f" | {e['weight_pct']:.1f}%" f" | {e['actionable_rank']}" f" | {d1} | {d2} | {d3} |"
            )
        lines.append("")

    # Section 4: Proximity Rails
    pr = packet.get("proximity_rails", {})
    lines.append("## Event Proximity Rails")
    lines.append("")

    for event_type in ("regulatory", "clinical"):
        bands = pr.get(event_type, {})
        if not any(b.get("count", 0) > 0 for b in bands.values()):
            continue
        lines.append(f"### {event_type.title()}")
        lines.append("")
        lines.append("| Band | Count | Weight % |")
        lines.append("|------|-------|----------|")
        for label, _, _ in PROXIMITY_BANDS:
            bd = bands.get(label, {"count": 0, "total_weight_pct": 0})
            if bd["count"] > 0:
                lines.append(f"| {label} | {bd['count']} | {bd['total_weight_pct']:.1f}% |")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Write packet
# ---------------------------------------------------------------------------


def write_attribution_packet(
    packet: Dict[str, Any],
    out_dir: Path,
) -> Tuple[Path, Path]:
    """Write ATTRIBUTION_PACKET.json and .md to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "ATTRIBUTION_PACKET.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(packet, f, indent=2, default=str)

    md_path = out_dir / "ATTRIBUTION_PACKET.md"
    md_content = render_attribution_packet_md(packet)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return json_path, md_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build weekly attribution packet")
    parser.add_argument("--as-of-date", required=True, help="Date (YYYY-MM-DD)")
    args = parser.parse_args()

    from tools.build_trade_deltas import find_prior_positions, load_positions_json
    from tools.live_shadow_portfolio import compute_performance, load_policy

    as_of = args.as_of_date
    pos_path = POSITIONS_DIR / f"{as_of}.json"
    if not pos_path.is_file():
        print(f"No positions file for {as_of}")
        sys.exit(1)

    _, current_pos = load_positions_json(pos_path)
    prior_path = find_prior_positions(as_of, POSITIONS_DIR)
    if not prior_path:
        print(f"No prior positions for {as_of}")
        sys.exit(1)

    prior_date, prior_pos = load_positions_json(prior_path)

    perf = compute_performance(
        prior_pos,
        current_pos,
        prior_date,
        as_of,
    )

    snap_dir = SNAPSHOTS_ROOT / as_of
    policy = load_policy()

    packet = build_attribution_packet(
        as_of,
        current_pos,
        perf,
        policy,
        snap_dir=snap_dir,
    )

    out_dir = ATTRIBUTION_ROOT / as_of
    json_path, md_path = write_attribution_packet(packet, out_dir)
    print(f"Written: {json_path}")
    print(f"Written: {md_path}")


if __name__ == "__main__":
    main()

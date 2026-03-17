#!/usr/bin/env python3
"""
Spec 025: Long Call Candidate Selector

Post-screen execution artifact that identifies the best long-call candidates
among top-ranked names and recommends specific primary + backup contracts.

Usage:
    python scripts/research/build_long_call_candidates.py \
        --snapshot-dir data/snapshots/2026-03-16

    # Override filters:
    python scripts/research/build_long_call_candidates.py \
        --snapshot-dir data/snapshots/2026-03-16 \
        --min-tier C \
        --catalyst-window 15-180 \
        --include-soft-catalysts
"""

import argparse
import csv
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("long_call_candidates")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCHEMA_VERSION = "long_call_candidates.v2"

# Filter defaults — expanded for auto-report (Spec 025 v2)
# Name selection is inclusive; contract selection stays strict.
DEFAULT_TIERS = {"A", "B", "C"}
DEFAULT_CAT_WINDOW = (15, 180)
STRONG_RR_THRESHOLD = 0.15

# --- Hard liquidity guards ---
MIN_OI = 50  # hard reject below this
MIN_VOLUME_UNLESS_HIGH_OI = 10  # hard reject if vol < 10 AND OI < 500
MAX_SPREAD_RATIO = 0.30  # bid-ask / mid; used only if bid/ask available

# --- Hard DTE / expiry guards ---
MAX_DTE = 180  # hard reject any contract beyond this
MAX_DAYS_PAST_CATALYST = 120  # reject if expiry > 120d after catalyst

TARGET_POST_EVENT_CUSHION = (14, 35)  # calendar days after catalyst
TIGHT_POST_EVENT_CUSHION = (7, 21)  # for catalyst_days 21-45


def _try_parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _safe_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _safe_int(v: Any) -> Optional[int]:
    f = _safe_float(v)
    return int(f) if f is not None else None


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_rankings(snapshot_dir: Path) -> List[Dict[str, Any]]:
    path = snapshot_dir / "rankings.csv"
    if not path.exists():
        raise FileNotFoundError(f"rankings.csv not found in {snapshot_dir}")
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_chains(snapshot_dir: Path, ticker: str) -> List[Dict[str, Any]]:
    path = snapshot_dir / "chains" / f"{ticker}.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_price_history(data_dir: Path, tickers: set, as_of_date: str) -> Dict[str, float]:
    """Load latest close price per ticker from price_history.csv."""
    path = data_dir / "price_history.csv"
    prices: Dict[str, float] = {}
    if not path.exists():
        return prices
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t = row.get("ticker", "")
            if t not in tickers:
                continue
            d = row.get("date", "")
            if d > as_of_date:
                continue
            close = _safe_float(row.get("close"))
            if close is not None and close > 0:
                prices[t] = close
    return prices


# ---------------------------------------------------------------------------
# Candidate filter cascade (Spec 025 §Candidate filter cascade)
# ---------------------------------------------------------------------------


def apply_candidate_filters(
    rankings: List[Dict[str, Any]],
    *,
    allowed_tiers: set,
    catalyst_window: Tuple[int, int],
    require_hard_catalyst: bool,
    require_positive_rr: bool,
) -> List[Dict[str, Any]]:
    """Apply the 6-step filter cascade, returning surviving rows."""
    candidates = []
    for r in rankings:
        tier = r.get("tier_any", "")
        # 1. Rank / conviction
        if tier not in allowed_tiers:
            continue

        # 2. Hard catalyst
        is_hard = r.get("is_hard_catalyst", "0")
        if require_hard_catalyst and str(is_hard) != "1":
            continue

        # 3. Catalyst timing window
        cat_days = _safe_int(r.get("catalyst_days"))
        if cat_days is None:
            continue
        if cat_days < catalyst_window[0] or cat_days > catalyst_window[1]:
            continue

        # 4. Bullish directional filter
        rr = _safe_float(r.get("opt_rr_25d"))
        if require_positive_rr and (rr is None or rr <= 0):
            continue

        # 5/6 are soft — applied as scoring, not hard rejection
        candidates.append(r)

    return candidates


# ---------------------------------------------------------------------------
# Contract selection (Spec 025 §Contract selection rules)
# ---------------------------------------------------------------------------


def select_contracts(
    chain: List[Dict[str, Any]],
    *,
    catalyst_days: int,
    as_of_date: str,
    stock_price: float,
    tier: str,
    iv_level: Optional[float],
) -> Dict[str, Any]:
    """Select primary + backup call contracts from chain data."""
    result: Dict[str, Any] = {
        "primary": None,
        "backup": None,
        "no_trade": False,
        "no_trade_reason": None,
        "spread_unavailable_proxy_used": True,  # no bid/ask in chain schema
    }

    calls = [
        c
        for c in chain
        if c.get("contract_type") == "call" and c.get("delta") is not None and c.get("expiration_date") is not None
    ]
    if not calls:
        result["no_trade"] = True
        result["no_trade_reason"] = "no_call_contracts_in_chain"
        return result

    # Parse dates
    try:
        base_date = datetime.strptime(as_of_date, "%Y-%m-%d")
    except ValueError:
        result["no_trade"] = True
        result["no_trade_reason"] = "invalid_as_of_date"
        return result

    catalyst_date = base_date + timedelta(days=catalyst_days)

    # Determine post-event cushion window
    if 21 <= catalyst_days <= 45:
        cushion_min, cushion_max = TIGHT_POST_EVENT_CUSHION
    else:
        cushion_min, cushion_max = TARGET_POST_EVENT_CUSHION

    # Determine delta band based on conviction / IV
    if tier == "A":
        delta_min, delta_max = 0.35, 0.55
    elif iv_level is not None and iv_level > 2.0:
        delta_min, delta_max = 0.25, 0.45
    else:
        delta_min, delta_max = 0.30, 0.50

    # Step 1: Find eligible expiries (after catalyst + cushion, within hard caps)
    expiry_set = sorted(set(c["expiration_date"] for c in calls))
    eligible_expiries = []
    for exp_str in expiry_set:
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
        except ValueError:
            continue
        dte = (exp_date - base_date).days
        days_after_catalyst = (exp_date - catalyst_date).days
        # Hard guard: DTE cap
        if dte > MAX_DTE:
            continue
        # Hard guard: expiry distance from catalyst
        if days_after_catalyst > MAX_DAYS_PAST_CATALYST:
            continue
        if days_after_catalyst < cushion_min:
            continue
        eligible_expiries.append((exp_str, exp_date, days_after_catalyst))

    if not eligible_expiries:
        # Fallback: allow any expiry after catalyst date (no cushion),
        # still subject to hard DTE and distance caps
        for exp_str in expiry_set:
            try:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
            except ValueError:
                continue
            dte = (exp_date - base_date).days
            days_after_catalyst = (exp_date - catalyst_date).days
            if dte > MAX_DTE:
                continue
            if days_after_catalyst > MAX_DAYS_PAST_CATALYST:
                continue
            if exp_date > catalyst_date:
                eligible_expiries.append((exp_str, exp_date, days_after_catalyst))
        if not eligible_expiries:
            # Chain sanity: distinguish "no chain near term" from "no expiry at all"
            any_post_catalyst = any(
                datetime.strptime(e, "%Y-%m-%d") > catalyst_date for e in expiry_set if _try_parse_date(e) is not None
            )
            result["no_trade"] = True
            result["no_trade_reason"] = (
                "no_near_term_chain_insufficient" if any_post_catalyst else "no_expiry_after_catalyst"
            )
            return result

    # Sort expiries: prefer those within cushion range, then nearest
    def expiry_sort_key(item):
        _, _, days_after = item
        in_ideal = cushion_min <= days_after <= cushion_max
        return (0 if in_ideal else 1, days_after)

    eligible_expiries.sort(key=expiry_sort_key)

    # Step 2-5: Score contracts across eligible expiries
    scored = []
    for exp_str, exp_date, days_after_catalyst in eligible_expiries:
        dte = (exp_date - base_date).days
        exp_calls = [c for c in calls if c["expiration_date"] == exp_str and c.get("delta") is not None]
        for c in exp_calls:
            delta = c["delta"]
            oi = c.get("open_interest") or 0
            vol = c.get("day_volume") or 0
            close_price = c.get("day_close")
            strike = c["strike_price"]
            iv = c.get("implied_volatility")
            be = c.get("break_even_price")

            # Delta filter
            if delta < delta_min * 0.8 or delta > delta_max * 1.2:
                continue

            # Hard liquidity guards
            if oi < MIN_OI:
                continue
            if vol < MIN_VOLUME_UNLESS_HIGH_OI and oi < 500:
                continue

            # Price must exist
            if close_price is None or close_price <= 0:
                # Try break_even - strike as premium proxy
                if be is not None and strike is not None and be > strike:
                    close_price = be - strike
                else:
                    continue

            # Breakeven move
            if stock_price > 0 and be is not None:
                breakeven_move_pct = (be / stock_price - 1) * 100
            elif stock_price > 0:
                breakeven_move_pct = ((strike + close_price) / stock_price - 1) * 100
            else:
                breakeven_move_pct = None

            # Score: prefer in-band delta, higher OI, ideal cushion, lower premium
            in_delta_band = delta_min <= delta <= delta_max
            ideal_cushion = cushion_min <= days_after_catalyst <= cushion_max

            # Composite score (higher = better)
            score = 0.0
            score += 3.0 if in_delta_band else 0.0
            score += 2.0 if ideal_cushion else 0.0
            score += min(oi / 100, 3.0)  # OI contribution capped at 3
            score += min(vol / 50, 1.0)  # Volume contribution capped at 1
            # Penalize very OTM (low delta)
            if delta < 0.25:
                score -= 1.0

            scored.append(
                {
                    "expiry": exp_str,
                    "dte": dte,
                    "strike": strike,
                    "option_type": "CALL",
                    "delta": round(delta, 4),
                    "premium_or_mid": round(close_price, 2),
                    "open_interest": oi,
                    "volume": vol,
                    "spread_or_liquidity_proxy": f"OI={oi},vol={vol}",
                    "breakeven_move_pct": round(breakeven_move_pct, 2) if breakeven_move_pct is not None else None,
                    "implied_volatility": round(iv, 4) if iv is not None else None,
                    "days_after_catalyst": days_after_catalyst,
                    "_score": score,
                }
            )

    if not scored:
        result["no_trade"] = True
        result["no_trade_reason"] = "no_contracts_pass_filters"
        return result

    scored.sort(key=lambda x: -x["_score"])

    primary = scored[0]
    # Backup: different strike or expiry from primary
    backup = None
    for s in scored[1:]:
        if s["strike"] != primary["strike"] or s["expiry"] != primary["expiry"]:
            backup = s
            break
    # If no different contract, take second-best
    if backup is None and len(scored) > 1:
        backup = scored[1]

    def _clean(contract):
        c = dict(contract)
        c.pop("_score", None)
        c["why_this_contract"] = _build_reason(c, catalyst_days)
        return c

    result["primary"] = _clean(primary)
    result["backup"] = _clean(backup) if backup else None
    return result


def _build_reason(contract: dict, catalyst_days: int) -> str:
    parts = []
    parts.append(f"DTE={contract['dte']}")
    parts.append(f"delta={contract['delta']:.2f}")
    parts.append(f"OI={contract['open_interest']}")
    if contract.get("days_after_catalyst") is not None:
        parts.append(f"{contract['days_after_catalyst']}d post-catalyst cushion")
    if contract.get("breakeven_move_pct") is not None:
        parts.append(f"BE={contract['breakeven_move_pct']:+.1f}%")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Candidate scoring & assembly
# ---------------------------------------------------------------------------


def build_candidates(
    rankings: List[Dict[str, Any]],
    snapshot_dir: Path,
    data_dir: Path,
    as_of_date: str,
    *,
    allowed_tiers: set = DEFAULT_TIERS,
    catalyst_window: Tuple[int, int] = DEFAULT_CAT_WINDOW,
    require_hard_catalyst: bool = False,
    require_positive_rr: bool = False,
) -> List[Dict[str, Any]]:
    """Full pipeline: filter → contract select → assemble output.

    Default filters are inclusive at the name level (soft catalysts allowed,
    negative RR allowed). Contract-level guards remain strict.
    """
    filtered = apply_candidate_filters(
        rankings,
        allowed_tiers=allowed_tiers,
        catalyst_window=catalyst_window,
        require_hard_catalyst=require_hard_catalyst,
        require_positive_rr=require_positive_rr,
    )

    if not filtered:
        logger.warning("No candidates survived filter cascade")
        return []

    # Load stock prices
    tickers = {r["ticker"] for r in filtered}
    prices = load_price_history(data_dir, tickers, as_of_date)

    # Sort by opt_rr_25d descending (bullish first)
    def sort_key(r):
        rr = _safe_float(r.get("opt_rr_25d"))
        return -(rr if rr is not None else -999)

    filtered.sort(key=sort_key)

    results = []
    for r in filtered:
        ticker = r["ticker"]
        tier = r.get("tier_any", "")
        cat_days = _safe_int(r.get("catalyst_days"))
        rr = _safe_float(r.get("opt_rr_25d"))
        stock_price = prices.get(ticker, 0)
        iv_level = _safe_float(r.get("opt_atm_iv"))

        # Load chain
        chain = load_chains(snapshot_dir, ticker)

        # Select contracts
        if chain and stock_price > 0 and cat_days is not None:
            contracts = select_contracts(
                chain,
                catalyst_days=cat_days,
                as_of_date=as_of_date,
                stock_price=stock_price,
                tier=tier,
                iv_level=iv_level,
            )
        else:
            contracts = {
                "primary": None,
                "backup": None,
                "no_trade": True,
                "no_trade_reason": (
                    "no_chain_data" if not chain else "no_stock_price" if stock_price <= 0 else "missing_catalyst_days"
                ),
                "spread_unavailable_proxy_used": True,
            }

        # Build thesis
        cat_event = r.get("catalyst_event_type", "")
        cat_family = r.get("catalyst_family", "")
        rr_str = f"RR={rr:+.2f}" if rr is not None else "RR=N/A"
        thesis = f"Tier {tier}, {cat_family} {cat_event} in {cat_days}d. {rr_str}."

        # Classify
        surface_ext = r.get("surface_move_extreme", "")
        if rr is not None and rr >= STRONG_RR_THRESHOLD and surface_ext != "high":
            category = "strongest_directional"
        elif rr is not None and rr > 0:
            category = "acceptable"
        elif rr is not None and rr <= 0:
            category = "bearish_rr_caution"
        else:
            category = "missing_rr_data"

        entry = {
            "ticker": ticker,
            "tier": tier,
            "actionable_rank": r.get("actionable_rank", ""),
            "composite_score": r.get("composite_score", ""),
            "catalyst": f"{cat_family}:{cat_event}",
            "catalyst_days": cat_days,
            "stock_price": round(stock_price, 2) if stock_price else None,
            "thesis_summary": thesis,
            "opt_rr_25d": rr,
            "rr_trend_flag": r.get("rr_trend_flag", ""),
            "surface_move_extreme": surface_ext,
            "actual_implied_move_pctile": r.get("actual_implied_move_pctile", ""),
            "iv_crush_breakeven_pct": r.get("iv_crush_breakeven_pct", ""),
            "crush_adjusted_implied_move": r.get("crush_adjusted_implied_move", ""),
            "category": category,
            # Contract fields
            "no_trade": contracts["no_trade"],
            "no_trade_reason": contracts.get("no_trade_reason"),
            "spread_unavailable_proxy_used": contracts.get("spread_unavailable_proxy_used", False),
        }

        # Flatten primary/backup contracts
        for prefix, key in [("primary", "primary"), ("backup", "backup")]:
            c = contracts.get(key)
            if c:
                for field in [
                    "expiry",
                    "dte",
                    "strike",
                    "option_type",
                    "delta",
                    "premium_or_mid",
                    "open_interest",
                    "volume",
                    "spread_or_liquidity_proxy",
                    "breakeven_move_pct",
                    "why_this_contract",
                ]:
                    entry[f"{prefix}_{field}"] = c.get(field)
            else:
                for field in [
                    "expiry",
                    "dte",
                    "strike",
                    "option_type",
                    "delta",
                    "premium_or_mid",
                    "open_interest",
                    "volume",
                    "spread_or_liquidity_proxy",
                    "breakeven_move_pct",
                    "why_this_contract",
                ]:
                    entry[f"{prefix}_{field}"] = None

        results.append(entry)

    return results


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def write_csv(candidates: List[Dict[str, Any]], path: Path) -> None:
    if not candidates:
        path.write_text("# No long-call candidates\n", encoding="utf-8")
        return
    fieldnames = list(candidates[0].keys())
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(candidates)
    logger.info(f"Wrote {len(candidates)} candidates to {path}")


def write_json(candidates: List[Dict[str, Any]], path: Path, as_of_date: str) -> None:
    obj = {
        "schema_version": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "n_candidates": len(candidates),
        "n_tradeable": sum(1 for c in candidates if not c.get("no_trade")),
        "n_no_trade": sum(1 for c in candidates if c.get("no_trade")),
        "filter_note": (
            "hard_catalyst+positive_rr"
            if any(c.get("opt_rr_25d") and c["opt_rr_25d"] > 0 for c in candidates)
            else "relaxed_filters"
        ),
        "candidates": candidates,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)
    logger.info(f"Wrote JSON to {path}")


def write_markdown(candidates: List[Dict[str, Any]], path: Path, as_of_date: str) -> None:
    lines = [
        f"# Long Call Candidates — {as_of_date}",
        "",
        f"**Schema**: `{SCHEMA_VERSION}`",
        f"**Total candidates**: {len(candidates)}",
        f"**Tradeable**: {sum(1 for c in candidates if not c.get('no_trade'))}",
        f"**No-trade**: {sum(1 for c in candidates if c.get('no_trade'))}",
        "",
        "**Limitations**: bid/ask spread unavailable; liquidity assessed via OI + volume proxy only.",
        "",
    ]

    # Group by category
    groups = {
        "strongest_directional": "Strongest Directional Candidates",
        "acceptable": "Acceptable Setups",
        "bearish_rr_caution": "Bearish RR — Caution",
        "missing_rr_data": "Missing RR Data",
    }

    for cat_key, cat_title in groups.items():
        group = [c for c in candidates if c.get("category") == cat_key]
        if not group:
            continue
        lines.append(f"## {cat_title}")
        lines.append("")

        for c in group:
            ticker = c["ticker"]
            lines.append(f"### {ticker} (Tier {c['tier']}, rank {c.get('actionable_rank', '?')})")
            lines.append("")
            lines.append(f"- **Catalyst**: {c['catalyst']} in {c['catalyst_days']}d")
            lines.append(f"- **Stock price**: ${c.get('stock_price', '?')}")
            rr = c.get("opt_rr_25d")
            lines.append(f"- **RR 25d**: {rr:+.4f}" if rr is not None else "- **RR 25d**: N/A")
            lines.append(f"- **Surface extreme**: {c.get('surface_move_extreme', 'N/A')}")
            crush = c.get("crush_adjusted_implied_move", "")
            lines.append(f"- **Crush-adj move**: {crush}" if crush else "- **Crush-adj move**: N/A")
            lines.append(f"- **Thesis**: {c['thesis_summary']}")
            lines.append("")

            if c.get("no_trade"):
                lines.append(f"**NO_TRADE**: {c.get('no_trade_reason', 'unknown')}")
                lines.append("")
                continue

            # Primary contract
            if c.get("primary_expiry"):
                lines.append("**Primary contract**:")
                lines.append(f"- Expiry: {c['primary_expiry']} (DTE={c['primary_dte']})")
                lines.append(f"- Strike: ${c['primary_strike']} CALL")
                lines.append(f"- Delta: {c['primary_delta']}")
                lines.append(f"- Premium: ${c['primary_premium_or_mid']}")
                lines.append(f"- Liquidity: {c['primary_spread_or_liquidity_proxy']}")
                be = c.get("primary_breakeven_move_pct")
                lines.append(f"- Breakeven move: {be:+.1f}%" if be is not None else "- Breakeven move: N/A")
                lines.append(f"- Rationale: {c.get('primary_why_this_contract', '')}")
                lines.append("")

            # Backup contract
            if c.get("backup_expiry"):
                lines.append("**Backup contract**:")
                lines.append(f"- Expiry: {c['backup_expiry']} (DTE={c['backup_dte']})")
                lines.append(f"- Strike: ${c['backup_strike']} CALL")
                lines.append(f"- Delta: {c['backup_delta']}")
                lines.append(f"- Premium: ${c['backup_premium_or_mid']}")
                lines.append(f"- Liquidity: {c['backup_spread_or_liquidity_proxy']}")
                be = c.get("backup_breakeven_move_pct")
                lines.append(f"- Breakeven move: {be:+.1f}%" if be is not None else "- Breakeven move: N/A")
                lines.append(f"- Rationale: {c.get('backup_why_this_contract', '')}")
                lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Wrote markdown to {path}")


# ---------------------------------------------------------------------------
# Entry point for run_screen.py auto-report
# ---------------------------------------------------------------------------


def run_from_screen(
    snapshot_dir: Path,
    data_dir: Path,
    as_of_date: str,
) -> Optional[int]:
    """Auto-report entry point called from run_screen.py after snapshot.

    Returns number of candidates written, or None on failure.
    Gracefully handles missing prerequisites without raising.
    """
    rankings_path = snapshot_dir / "rankings.csv"
    if not rankings_path.exists():
        logger.warning("[LONG_CALL] rankings.csv not found in %s — skipping", snapshot_dir)
        return None

    try:
        rankings = load_rankings(snapshot_dir)
    except Exception as exc:
        logger.warning("[LONG_CALL] Failed to load rankings: %s — skipping", exc)
        return None

    if not rankings:
        logger.warning("[LONG_CALL] Empty rankings — skipping")
        return None

    try:
        candidates = build_candidates(
            rankings,
            snapshot_dir,
            data_dir,
            as_of_date,
        )
        write_csv(candidates, snapshot_dir / "long_call_candidates.csv")
        write_json(candidates, snapshot_dir / "long_call_candidates.json", as_of_date)
        write_markdown(candidates, snapshot_dir / "long_call_candidates.md", as_of_date)

        n_trade = sum(1 for c in candidates if not c.get("no_trade"))
        n_strong = sum(1 for c in candidates if c.get("category") == "strongest_directional")
        logger.info(
            "[LONG_CALL] %d candidates (%d tradeable, %d strongest) — %s",
            len(candidates),
            n_trade,
            n_strong,
            snapshot_dir / "long_call_candidates.md",
        )
        return len(candidates)
    except Exception as exc:
        logger.warning("[LONG_CALL] Report generation failed: %s — skipping", exc)
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Spec 025: Long Call Candidate Selector (post-screen)",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        required=True,
        help="Snapshot directory (e.g. data/snapshots/2026-03-16)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "production_data",
        help="Production data directory (for price_history.csv)",
    )
    parser.add_argument(
        "--as-of-date",
        type=str,
        default=None,
        help="Override as-of date (default: inferred from snapshot dir name)",
    )
    parser.add_argument(
        "--min-tier",
        type=str,
        default="C",
        choices=["A", "B", "C", "D"],
        help="Minimum tier to include (default: C → includes A+B+C)",
    )
    parser.add_argument(
        "--catalyst-window",
        type=str,
        default="15-180",
        help="Catalyst days window as MIN-MAX (default: 15-180)",
    )
    parser.add_argument(
        "--hard-catalysts-only",
        action="store_true",
        help="Only include names with is_hard_catalyst=1 (default: include soft)",
    )
    parser.add_argument(
        "--positive-rr-only",
        action="store_true",
        help="Only include names with positive opt_rr_25d (default: include all)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Infer as_of_date from snapshot dir name if not provided
    as_of_date = args.as_of_date or args.snapshot_dir.name
    logger.info(f"Building long-call candidates for {as_of_date}")

    # Parse tier set
    tier_order = ["A", "B", "C", "D"]
    min_idx = tier_order.index(args.min_tier)
    allowed_tiers = set(tier_order[: min_idx + 1])

    # Parse catalyst window
    cat_parts = args.catalyst_window.split("-")
    catalyst_window = (int(cat_parts[0]), int(cat_parts[1]))

    # Load rankings
    rankings = load_rankings(args.snapshot_dir)
    logger.info(f"Loaded {len(rankings)} rows from rankings.csv")

    # Build candidates
    candidates = build_candidates(
        rankings,
        args.snapshot_dir,
        args.data_dir,
        as_of_date,
        allowed_tiers=allowed_tiers,
        catalyst_window=catalyst_window,
        require_hard_catalyst=args.hard_catalysts_only,
        require_positive_rr=args.positive_rr_only,
    )

    logger.info(f"Final candidates: {len(candidates)}")

    # Write outputs
    write_csv(candidates, args.snapshot_dir / "long_call_candidates.csv")
    write_json(candidates, args.snapshot_dir / "long_call_candidates.json", as_of_date)
    write_markdown(candidates, args.snapshot_dir / "long_call_candidates.md", as_of_date)

    # Summary
    n_trade = sum(1 for c in candidates if not c.get("no_trade"))
    n_notrade = sum(1 for c in candidates if c.get("no_trade"))
    n_strong = sum(1 for c in candidates if c.get("category") == "strongest_directional")
    print(f"\n{'='*60}")
    print(f"LONG CALL CANDIDATES — {as_of_date}")
    print(f"{'='*60}")
    print(f"Total candidates:     {len(candidates)}")
    print(f"Tradeable:            {n_trade}")
    print(f"No-trade:             {n_notrade}")
    print(f"Strongest directional: {n_strong}")
    if candidates:
        print("\nTop candidates:")
        for c in candidates[:5]:
            rr = c.get("opt_rr_25d")
            rr_s = f"RR={rr:+.2f}" if rr is not None else "RR=N/A"
            trade = "TRADE" if not c.get("no_trade") else f"NO_TRADE({c.get('no_trade_reason', '')})"
            strike_s = f"${c['primary_strike']}C {c['primary_expiry']}" if c.get("primary_strike") else ""
            print(f"  {c['ticker']:<6} Tier {c['tier']}  {c['catalyst_days']:>3}d  {rr_s:<12} {trade:<20} {strike_s}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

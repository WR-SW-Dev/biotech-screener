#!/usr/bin/env python3
"""Top-30 asymmetry score — within-bucket ranking by upside skew.

Second-stage ranker: given that DEM already selected these names, which
have the highest asymmetric return potential relative to what the options
market is already pricing?

Score components (all within top-30 only):
  1. cheap_surface  — implied move looks cheap vs historical (cheap_vol_score)
  2. event_loading  — market is pricing a large event (high EPR = more optionality)
  3. skew_lean      — skew/RR suggests directional mispricing
  4. iv_momentum    — IV building into catalyst (pre-event ramp)
  5. liquidity_gate — liquid chains only get full weight; thin/absent penalized
  6. quality_gate   — EPD quality must be 'full' for score to count

The score rewards names where:
  - DEM already likes them (they're in top-30)
  - The market is underpricing the catalyst (cheap surface)
  - OR the market is pricing a large event AND skew suggests they're wrong
  - Chain is liquid enough to act on

Usage:
    python3 scripts/research/top30_asymmetry_score.py --as-of-date 2026-04-02
    python3 scripts/research/top30_asymmetry_score.py --as-of-date 2026-04-02 --backtest
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
OUTPUT_DIR = PROJECT_ROOT / "output" / "ranker_eval"
SCHEMA = "top30_asymmetry.v2"


def _sf(v, default=float("nan")):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Score computation v2 — pricing-aware EV model
# ---------------------------------------------------------------------------

# Component weights
W_MISPRICING = 0.30  # implied vs realized: is the market wrong?
W_CHEAP_SURFACE = 0.20  # cheap_vol_score z-scored within top-30
W_EVENT_LOADING = 0.15  # event premium ratio (optionality)
W_SKEW_LEAN = 0.15  # directional skew mispricing
W_IV_MOMENTUM = 0.10  # pre-event IV ramp
W_CATALYST_PRIOR = 0.10  # catalyst type × hard bonus

# Liquidity penalties
LIQ_MULT = {
    "liquid": 1.0,
    "thin": 0.5,
    "absent": 0.0,
    "": 0.0,
}

# Catalyst type EV priors: (hit_rate, median_abs_move)
# From CRT resolutions + historical calibration
CATALYST_PRIORS = {
    "FDA_PDUFA_DATE": (0.65, 0.20),  # regulatory: higher hit rate, large moves
    "FDA_ADCOM": (0.55, 0.25),
    "FDA_CRL": (0.30, 0.15),
    "DATA_READOUT": (0.50, 0.20),  # clinical phase 3: coin flip, big moves
    "CT_PRIMARY_COMPLETION": (0.45, 0.10),  # softer signal, smaller moves
    "CT_STUDY_COMPLETION": (0.40, 0.08),
    "CT_RESULTS_POSTED": (0.45, 0.10),
    "SAFETY_SIGNAL": (0.20, 0.12),
    "CLINICAL_HOLD": (0.15, 0.15),
}
DEFAULT_PRIOR = (0.40, 0.10)

# Cohort labels
REGULATORY_TYPES = frozenset({"FDA_PDUFA_DATE", "FDA_ADCOM", "FDA_CRL"})


def _cross_sectional_z(values: List[float]) -> List[float]:
    """Z-score a list of values, returning NaN for NaN inputs."""
    valid = [v for v in values if not math.isnan(v)]
    if len(valid) < 3:
        return [0.0 if not math.isnan(v) else float("nan") for v in values]
    mu = statistics.mean(valid)
    sd = statistics.stdev(valid)
    if sd < 1e-9:
        return [0.0 if not math.isnan(v) else float("nan") for v in values]
    return [(v - mu) / sd if not math.isnan(v) else float("nan") for v in values]


def compute_asymmetry_scores(
    ranking_rows: List[Dict[str, str]],
    epd_lookup: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Score a batch of top-30 names with cross-sectional normalization.

    Takes the full batch so cheap_vol_score can be z-scored within top-30.
    """
    # --- Cross-sectional z-score cheap_vol_score ---
    raw_cheap = [_sf(r.get("cheap_vol_score")) for r in ranking_rows]
    cheap_z = _cross_sectional_z(raw_cheap)

    results = []
    for i, ranking_row in enumerate(ranking_rows):
        result = _score_single(ranking_row, epd_lookup.get(ranking_row.get("ticker", ""), {}), cheap_z[i])
        results.append(result)
    return results


def compute_asymmetry_score(
    ranking_row: Dict[str, str],
    epd_row: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Score a single name (backward-compatible entry point)."""
    return _score_single(ranking_row, epd_row or {}, 0.0)


def _score_single(
    ranking_row: Dict[str, str],
    epd_row: Dict[str, Any],
    cheap_vol_z: float,
) -> Dict[str, Any]:
    ticker = ranking_row.get("ticker", "")
    result: Dict[str, Any] = {"ticker": ticker}

    # --- Extract fields ---
    liq_state = ranking_row.get("opt_liquidity_state", "")
    is_hard = str(ranking_row.get("is_hard_catalyst", "0")).strip() == "1"
    catalyst_days = _sf(ranking_row.get("catalyst_days"))
    catalyst_type = ranking_row.get("catalyst_event_type", "")

    # EPD fields
    epr_z = _sf(epd_row.get("epd_event_premium_ratio_z"))
    skew_z = _sf(epd_row.get("epd_skew_richness_z"))
    iv_mom_z = _sf(epd_row.get("epd_iv_momentum_z"))
    ivr = _sf(epd_row.get("epd_implied_vs_realized_ratio"))
    regime = epd_row.get("epd_surface_regime", "")
    quality = epd_row.get("epd_quality", "")

    # Cohort classification
    is_regulatory = catalyst_type in REGULATORY_TYPES
    cohort = (
        "hard_liquid"
        if is_hard and liq_state == "liquid"
        else ("regulatory" if is_regulatory else ("hard" if is_hard else "clinical"))
    )

    result["opt_liquidity_state"] = liq_state
    result["is_hard_catalyst"] = is_hard
    result["catalyst_type"] = catalyst_type
    result["cohort"] = cohort
    result["catalyst_days"] = catalyst_days if not math.isnan(catalyst_days) else None
    result["epd_quality"] = quality
    result["epd_surface_regime"] = regime
    result["implied_vs_realized"] = round(ivr, 2) if not math.isnan(ivr) else None

    # --- Liquidity gate ---
    liq_mult = LIQ_MULT.get(liq_state, 0.0)
    result["liquidity_mult"] = liq_mult

    # --- Quality gate ---
    quality_ok = quality in ("full", "partial") or not quality
    result["quality_ok"] = quality_ok

    if liq_mult == 0.0:
        result["asymmetry_score"] = None
        result["score_components"] = {}
        result["gated_out"] = True
        result["gate_reason"] = "absent_chain"
        return result

    result["gated_out"] = False
    result["gate_reason"] = None

    # --- Component 1: MISPRICING (implied_vs_realized) ---
    # ivr < 1.0 = market underpricing (good), ivr > 1.0 = overpricing (bad)
    # Score: 1.0 when ivr=0 (max underpriced), 0.5 at ivr=1.0, 0.0 at ivr>=2.0
    if not math.isnan(ivr) and ivr > 0:
        c_mispricing = max(0.0, min(1.0, 1.0 - 0.5 * ivr))
    else:
        c_mispricing = 0.5  # neutral when missing

    # --- Component 2: CHEAP SURFACE (z-scored within top-30) ---
    if not math.isnan(cheap_vol_z):
        c_cheap = max(0.0, min(1.0, 0.5 + 0.2 * cheap_vol_z))
    else:
        c_cheap = 0.5

    # --- Component 3: EVENT LOADING (tent function on EPR z) ---
    if not math.isnan(epr_z):
        if epr_z <= 0:
            c_event = max(0.0, 0.3 + 0.2 * epr_z)
        elif epr_z <= 1.5:
            c_event = 0.3 + 0.47 * epr_z
        else:
            c_event = max(0.3, 1.0 - 0.2 * (epr_z - 1.5))
        c_event = max(0.0, min(1.0, c_event))
    else:
        c_event = 0.5

    # --- Component 4: SKEW LEAN (contrarian: low skew = upside) ---
    if not math.isnan(skew_z):
        c_skew = max(0.0, min(1.0, 0.5 - 0.25 * skew_z))
    else:
        c_skew = 0.5

    # --- Component 5: IV MOMENTUM ---
    if not math.isnan(iv_mom_z):
        c_iv_mom = max(0.0, min(1.0, 0.5 + 0.25 * iv_mom_z))
    else:
        c_iv_mom = 0.5

    # --- Component 6: CATALYST PRIOR (type-specific hit rate × move) ---
    hit_rate, med_move = CATALYST_PRIORS.get(catalyst_type, DEFAULT_PRIOR)
    # EV prior = hit_rate * med_move (normalized to [0, 1])
    ev_prior = hit_rate * med_move
    # Scale: FDA_PDUFA at 0.65*0.20=0.13 is high, SAFETY_SIGNAL at 0.20*0.12=0.024 is low
    c_prior = max(0.0, min(1.0, ev_prior / 0.15))  # normalize so ~0.15 = 1.0
    # Hard catalyst gets extra boost
    if is_hard:
        c_prior = min(1.0, c_prior * 1.3)

    # --- Composite ---
    raw_score = (
        W_MISPRICING * c_mispricing
        + W_CHEAP_SURFACE * c_cheap
        + W_EVENT_LOADING * c_event
        + W_SKEW_LEAN * c_skew
        + W_IV_MOMENTUM * c_iv_mom
        + W_CATALYST_PRIOR * c_prior
    )

    # Apply liquidity multiplier
    final_score = round(raw_score * liq_mult, 4)

    result["score_components"] = {
        "mispricing": round(c_mispricing, 4),
        "cheap_surface": round(c_cheap, 4),
        "event_loading": round(c_event, 4),
        "skew_lean": round(c_skew, 4),
        "iv_momentum": round(c_iv_mom, 4),
        "catalyst_prior": round(c_prior, 4),
    }
    result["catalyst_prior_detail"] = {
        "hit_rate": hit_rate,
        "med_move": med_move,
        "ev_prior": round(ev_prior, 4),
    }
    result["raw_score"] = round(raw_score, 4)
    result["asymmetry_score"] = final_score

    return result


# ---------------------------------------------------------------------------
# Snapshot scorer
# ---------------------------------------------------------------------------


def score_snapshot(snap_date: str, top_n: int = 30) -> Dict[str, Any]:
    """Score a single snapshot's top-N names."""
    rankings_path = SNAPSHOTS_DIR / snap_date / "rankings.csv"
    epd_path = SNAPSHOTS_DIR / snap_date / "event_premium_decomp.json"

    if not rankings_path.exists():
        return {"error": f"No rankings.csv for {snap_date}"}

    # Load rankings
    with open(rankings_path) as f:
        rows = list(csv.DictReader(f))

    top_rows = []
    for r in rows:
        try:
            rank = int(float(r.get("actionable_rank", "9999")))
        except ValueError:
            rank = 9999
        if rank <= top_n:
            top_rows.append(r)

    # Load EPD if available
    epd_lookup: Dict[str, Dict] = {}
    if epd_path.exists():
        epd_data = json.loads(epd_path.read_text())
        for entry in epd_data.get("names", []):
            t = entry.get("ticker", "")
            if t:
                epd_lookup[t] = entry

    # Score batch (cross-sectional z-scoring for cheap_vol)
    scored = compute_asymmetry_scores(top_rows, epd_lookup)

    # Sort by asymmetry_score descending (None at bottom)
    scored.sort(key=lambda x: x.get("asymmetry_score") or -999, reverse=True)

    # Add asymmetry rank
    rank = 1
    for s in scored:
        if s.get("asymmetry_score") is not None:
            s["asymmetry_rank"] = rank
            rank += 1
        else:
            s["asymmetry_rank"] = None

    n_scored = sum(1 for s in scored if s.get("asymmetry_score") is not None)
    n_gated = sum(1 for s in scored if s.get("gated_out"))

    return {
        "schema": SCHEMA,
        "as_of_date": snap_date,
        "n_top": len(top_rows),
        "n_scored": n_scored,
        "n_gated_out": n_gated,
        "has_epd": bool(epd_lookup),
        "names": scored,
    }


# ---------------------------------------------------------------------------
# Backtest mode
# ---------------------------------------------------------------------------


def run_backtest(top_n: int, start: str, horizons: List[int]) -> Dict[str, Any]:
    """Run asymmetry score backtest across historical snapshots."""
    from scripts.research.ranker_evaluation_harness import (
        dedupe_monthly,
        forward_return,
        get_snapshot_dates,
        load_prices,
        spearman_ic,
    )

    prices = load_prices()
    xbi_prices = prices.get("XBI", {})

    all_dates = get_snapshot_dates(start)
    eval_dates = dedupe_monthly(all_dates)

    # Only dates with EPD
    eval_dates = [d for d in eval_dates if (SNAPSHOTS_DIR / d / "event_premium_decomp.json").exists()]
    print(f"Dates with EPD: {len(eval_dates)}")

    if not eval_dates:
        return {"error": "No snapshots with event_premium_decomp.json"}

    monthly_records = []
    ic_by_horizon: Dict[int, List[float]] = {h: [] for h in horizons}

    for snap_date in eval_dates:
        result = score_snapshot(snap_date, top_n)
        scored = [s for s in result["names"] if s.get("asymmetry_score") is not None]

        if len(scored) < 5:
            continue

        record: Dict[str, Any] = {
            "date": snap_date,
            "n_scored": len(scored),
        }

        for horizon in horizons:
            h_key = f"h{horizon}"

            # IC: asymmetry_score vs forward return
            pairs = []
            for s in scored:
                ret = forward_return(prices.get(s["ticker"], {}), snap_date, horizon)
                if ret is not None:
                    pairs.append((s["asymmetry_score"], ret))

            if len(pairs) < 5:
                continue

            sigs, rets = zip(*pairs)
            ic = spearman_ic(list(sigs), list(rets))
            if ic is not None:
                ic_by_horizon[horizon].append(ic)
                record[f"{h_key}_ic"] = round(ic, 4)

            # Top half vs bottom half returns
            sorted_pairs = sorted(pairs, key=lambda x: x[0], reverse=True)
            mid = len(sorted_pairs) // 2
            top_half_rets = [r for _, r in sorted_pairs[:mid]]
            bot_half_rets = [r for _, r in sorted_pairs[mid:]]

            if top_half_rets and bot_half_rets:
                top_mean = statistics.mean(top_half_rets)
                bot_mean = statistics.mean(bot_half_rets)
                record[f"{h_key}_top_half"] = round(top_mean * 100, 2)
                record[f"{h_key}_bot_half"] = round(bot_mean * 100, 2)
                record[f"{h_key}_spread"] = round((top_mean - bot_mean) * 100, 2)

            # EW top-30 vs XBI
            all_rets = [r for _, r in pairs]
            ew_mean = statistics.mean(all_rets)
            xbi_ret = forward_return(xbi_prices, snap_date, horizon)
            if xbi_ret is not None:
                record[f"{h_key}_ew_excess"] = round((ew_mean - xbi_ret) * 100, 2)

        monthly_records.append(record)

    # Aggregate
    backtest_result = {
        "schema": SCHEMA,
        "mode": "backtest",
        "n_months": len(monthly_records),
        "start": start,
        "horizons": {},
        "monthly_records": monthly_records,
    }

    print(f"\n{'='*70}")
    print(f"ASYMMETRY SCORE BACKTEST — Top-{top_n}")
    print(f"{'='*70}")
    print(f"Months with EPD: {len(monthly_records)}")

    for horizon in horizons:
        ics = ic_by_horizon[horizon]
        spreads = [r[f"h{horizon}_spread"] for r in monthly_records if f"h{horizon}_spread" in r]

        h_result: Dict[str, Any] = {}

        if ics:
            mean_ic = statistics.mean(ics)
            std_ic = statistics.stdev(ics) if len(ics) > 1 else 0
            t_stat = mean_ic / (std_ic / len(ics) ** 0.5) if std_ic > 0 else 0
            hit = sum(1 for x in ics if x > 0) / len(ics)
            print(f"\n--- {horizon}d horizon ---")
            print(f"  IC: mean={mean_ic:+.4f}, t={t_stat:+.2f}, hit={hit:.0%}, N={len(ics)}")
            h_result["ic_mean"] = round(mean_ic, 4)
            h_result["ic_t_stat"] = round(t_stat, 2)
            h_result["ic_hit_rate"] = round(hit, 2)

        if spreads:
            mean_spread = statistics.mean(spreads)
            cum_spread = sum(spreads)
            print(f"  Top/bot half spread: mean={mean_spread:+.2f}pp, cum={cum_spread:+.1f}pp")
            h_result["half_spread_mean"] = round(mean_spread, 2)
            h_result["half_spread_cum"] = round(cum_spread, 1)

        backtest_result["horizons"][str(horizon)] = h_result

    return backtest_result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Top-30 asymmetry score")
    parser.add_argument("--as-of-date", default=None, help="Score a single date")
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--backtest", action="store_true", help="Run backtest across all dates with EPD")
    parser.add_argument("--start", default="2024-01-01", help="Backtest start date")
    parser.add_argument("--horizons", default="20,63")
    args = parser.parse_args()

    if args.backtest:
        horizons = [int(h) for h in args.horizons.split(",")]
        result = run_backtest(args.top_n, args.start, horizons)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_DIR / "asymmetry_score_backtest.json"
        out_path.write_text(json.dumps(result, indent=2, default=str))
        print(f"\nSaved: {out_path}")
        return

    # Single-date scoring
    if not args.as_of_date:
        # Use latest snapshot
        dates = sorted(
            d.name
            for d in SNAPSHOTS_DIR.iterdir()
            if d.is_dir() and not d.name.startswith("_") and (d / "rankings.csv").exists()
        )
        args.as_of_date = dates[-1] if dates else None

    if not args.as_of_date:
        print("No snapshot dates found")
        return

    result = score_snapshot(args.as_of_date, args.top_n)

    print(f"\n{'='*70}")
    print(f"ASYMMETRY SCORE — {args.as_of_date} (Top-{args.top_n})")
    print(f"{'='*70}")
    print(
        f"  Scored: {result['n_scored']}/{result['n_top']} "
        f"(gated out: {result['n_gated_out']}, EPD: {'yes' if result['has_epd'] else 'no'})"
    )

    print(
        f"\n  {'Rk':>3s}  {'Ticker':6s}  {'Score':>6s}  {'Mispr':>5s}  {'Cheap':>5s}  {'Event':>5s}  "
        f"{'Skew':>5s}  {'IVmo':>4s}  {'Prior':>5s}  {'IvR':>5s}  {'Coh':7s}  {'Liq':>6s}"
    )
    print("  " + "-" * 85)

    for s in result["names"]:
        sc = s.get("score_components", {})
        r = s.get("asymmetry_rank")
        rank_str = f"{r:3d}" if r else "  -"
        score_str = f"{s['asymmetry_score']:.3f}" if s.get("asymmetry_score") is not None else "gated"
        ivr = s.get("implied_vs_realized")
        ivr_str = f"{ivr:.1f}" if ivr is not None else "—"
        print(
            f"  {rank_str}  {s['ticker']:6s}  {score_str:>6s}  "
            f"{sc.get('mispricing', 0):5.2f}  {sc.get('cheap_surface', 0):5.2f}  "
            f"{sc.get('event_loading', 0):5.2f}  {sc.get('skew_lean', 0):5.2f}  "
            f"{sc.get('iv_momentum', 0):4.2f}  {sc.get('catalyst_prior', 0):5.2f}  "
            f"{ivr_str:>5s}  {s.get('cohort', '?'):7s}  "
            f"{s.get('opt_liquidity_state', '?'):>6s}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"asymmetry_score_{args.as_of_date}.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Full Historical Backtest — Current Transmitted Model vs Prior Variants.

Runs the EV engine at historical snapshot dates, matches predictions
to CRT resolutions and price history, and compares four stack variants:

  A. Baseline (old prior, no clinical layers)
  B. Prior-only (recalibrated Phase 2, no clinical layers)
  C. Full stack without transmission
  D. Current full model (recalibrated + transmitted clinical stack)

Usage:
    python research/full_current_model_backtest.py
    python research/full_current_model_backtest.py --start 2026-03-01 --end 2026-04-15
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("backtest")

RESOLUTIONS_DIR = REPO_ROOT / "data" / "snapshots" / "resolutions"


def _load_all_resolutions() -> Dict[str, List[Dict]]:
    """Load all CRT resolutions keyed by ticker."""
    result: Dict[str, List[Dict]] = defaultdict(list)
    if not RESOLUTIONS_DIR.exists():
        return result
    for f in RESOLUTIONS_DIR.rglob("*.json"):
        try:
            rec = json.loads(f.read_text())
            if isinstance(rec, dict) and "ticker" in rec and rec.get("outcome") in ("HIT", "MISS"):
                result[rec["ticker"]].append(rec)
        except (json.JSONDecodeError, OSError):
            continue
    return result


def _load_prices():
    """Load price store."""
    try:
        from common.price_store import PriceStore

        db = REPO_ROOT / "data" / "prices.db"
        store = PriceStore(str(db))
        if store.ticker_count() > 0:
            return store
    except Exception:
        pass
    return None


def _find_valid_backtest_dates(start: str, end: str, resolutions: Dict) -> List[str]:
    """Find snapshot dates where at least one resolution exists within 60 days."""
    snap_dir = REPO_ROOT / "data" / "snapshots"
    valid = []
    for d in sorted(snap_dir.iterdir()):
        if not d.is_dir() or len(d.name) != 10:
            continue
        if d.name < start or d.name > end:
            continue
        if not (d / "rankings.csv").exists():
            continue
        valid.append(d.name)
    return valid


def _run_ev_at_date(
    as_of_str: str,
    phase2_prior: float,
    inject_clinical: bool,
) -> List[Dict[str, Any]]:
    """Run EV scoring at a historical date."""
    from event_ev.ev_calculator import EventEVCalculator
    from event_ev.loaders import load_catalyst_graph, load_market_features, split_context_features
    from event_ev.outcome_model import LITERATURE_PHASE_READOUT_PRIORS, OutcomeModel

    as_of = date.fromisoformat(as_of_str)
    prod = REPO_ROOT / "production_data"
    data = REPO_ROOT / "data"

    custom_priors = dict(LITERATURE_PHASE_READOUT_PRIORS)
    custom_priors["2"] = phase2_prior
    model = OutcomeModel(phase_readout_priors=custom_priors)

    try:
        graph = load_catalyst_graph(as_of, prod, data)
    except Exception:
        return []
    mf = load_market_features(as_of, data / "snapshots")
    cf = split_context_features(mf)

    if inject_clinical:
        try:
            trials = json.loads((prod / "trial_records.json").read_text())
            from common.biomarker_context import compute_biomarker_context_score
            from common.endpoint_quality import compute_endpoint_quality
            from common.protocol_quality import compute_protocol_quality

            pq = compute_protocol_quality(trials, as_of_str)
            bm = compute_biomarker_context_score(trials, as_of_str, protocol_quality=pq)
            ep = compute_endpoint_quality(trials, as_of_str)
            for tk in cf:
                if tk in pq:
                    cf[tk]["protocol_quality_score"] = pq[tk]["protocol_quality_score"]
                if tk in bm:
                    cf[tk]["biomarker_context_score"] = bm[tk]["biomarker_context_score"]
                if tk in ep:
                    cf[tk]["endpoint_quality_score"] = ep[tk]["endpoint_quality_score"]
        except Exception as e:
            logger.debug("Clinical injection failed at %s: %s", as_of_str, e)

    calc = EventEVCalculator(as_of_date=as_of, outcome_model=model, max_days=180, min_days=0)
    try:
        results = calc.run_from_graph(graph, market_features=mf, context_features=cf)
    except Exception:
        return []

    rows = []
    for rank, ev in enumerate(results, 1):
        tx = ev.outcome.features_used.get("clinical_transmission", {})
        rows.append(
            {
                "rank": rank,
                "ticker": ev.node.ticker,
                "event_type": ev.node.event_type,
                "phase": ev.node.phase,
                "p_hit": round(ev.outcome.p_hit, 4),
                "scenario_ev": round(ev.scenario_ev, 4),
                "ds_adj_ev": round(ev.payoff.downside_adjusted_ev, 4),
                "actionable": ev.actionable,
                "days_to_event": ev.node.days_to_event(as_of),
                "tx_clamped": round(tx.get("tx_clamped", 0), 4),
            }
        )
    return rows


def _get_price_pit_safe(prices: Any, ticker: str, target_date: str, max_lookback: int = 5) -> Optional[float]:
    """Get closing price on or BEFORE target_date only (PIT-safe).

    Looks backward up to max_lookback days for weekends/holidays.
    NEVER looks forward — that would be a PIT violation for entry prices.
    """
    from datetime import timedelta as _td

    dt = date.fromisoformat(target_date)
    for offset in range(max_lookback + 1):
        d = (dt - _td(days=offset)).isoformat()
        val = prices.get_price(ticker, d)
        if val is not None:
            return val
    return None


def _get_price_post_event(prices: Any, ticker: str, target_date: str, max_forward: int = 5) -> Optional[float]:
    """Get closing price on or AFTER target_date (for exit / realized returns).

    This is NOT a PIT violation because it measures realized outcomes,
    not decision inputs. Looks forward up to max_forward days for
    weekends/holidays after the event date.
    """
    from datetime import timedelta as _td

    dt = date.fromisoformat(target_date)
    for offset in range(max_forward + 1):
        d = (dt + _td(days=offset)).isoformat()
        val = prices.get_price(ticker, d)
        if val is not None:
            return val
    return None


def _match_outcomes(
    predictions: Dict[str, List[Dict]],
    resolutions: Dict[str, List[Dict]],
    prices: Any,
) -> List[Dict[str, Any]]:
    """Match predictions to realized outcomes."""
    matched = []
    for snap_date, rows in predictions.items():
        for row in rows:
            if not row["actionable"]:
                continue
            ticker = row["ticker"]
            # Find first resolution after snap_date
            recs = resolutions.get(ticker, [])
            outcome = None
            res_date = None
            for rec in recs:
                rd = rec.get("resolution_date", rec.get("catalyst_date", ""))
                if rd and rd >= snap_date:
                    o = rec.get("outcome", "")
                    if o == "HIT":
                        outcome = 1
                    elif o == "MISS":
                        outcome = 0
                    res_date = rd
                    break

            # Find return: entry price PIT-safe (backward only),
            # exit price post-event (forward OK for realized return)
            ret_1d = None
            if prices and res_date:
                try:
                    pre = _get_price_pit_safe(prices, ticker, snap_date)
                    post = _get_price_post_event(prices, ticker, res_date)
                    if pre and post and pre > 0:
                        ret_1d = round((post - pre) / pre, 6)
                except Exception:
                    pass

            matched.append(
                {
                    "snap_date": snap_date,
                    "ticker": ticker,
                    "phase": row["phase"],
                    "rank": row["rank"],
                    "p_hit": row["p_hit"],
                    "scenario_ev": row["scenario_ev"],
                    "tx_clamped": row.get("tx_clamped", 0),
                    "realized_outcome": outcome,
                    "realized_return": ret_1d,
                    "resolution_date": res_date,
                }
            )
    return matched


def _compute_metrics(matched: List[Dict], label: str) -> Dict[str, Any]:
    """Compute backtest metrics for a variant."""
    total = len(matched)
    with_outcome = [r for r in matched if r["realized_outcome"] is not None]
    with_return = [r for r in matched if r["realized_return"] is not None]

    outcomes = [r["realized_outcome"] for r in with_outcome]
    p_hits = [r["p_hit"] for r in with_outcome]
    returns = [r["realized_return"] for r in with_return]

    hit_rate = round(sum(outcomes) / len(outcomes), 4) if outcomes else None

    # Brier
    brier = None
    if p_hits and outcomes:
        brier = round(sum((p - o) ** 2 for p, o in zip(p_hits, outcomes)) / len(outcomes), 6)

    # Returns
    mean_ret = round(sum(returns) / len(returns), 6) if returns else None
    median_ret = round(sorted(returns)[len(returns) // 2], 6) if returns else None

    # Directional accuracy
    evs = [r["scenario_ev"] for r in with_return]
    directional = None
    if evs and returns:
        correct = sum(1 for e, r in zip(evs, returns) if (e > 0) == (r > 0))
        directional = round(correct / len(evs), 4)

    # By phase
    by_phase = {}
    for phase in ("1", "2", "3"):
        ph_rows = [r for r in with_outcome if r["phase"] == phase]
        if ph_rows:
            ph_out = [r["realized_outcome"] for r in ph_rows]
            by_phase[phase] = {
                "n": len(ph_rows),
                "hit_rate": round(sum(ph_out) / len(ph_out), 4),
            }

    return {
        "label": label,
        "n_actionable": total,
        "n_with_outcome": len(with_outcome),
        "n_with_return": len(with_return),
        "hit_rate": hit_rate,
        "brier": brier,
        "mean_return": mean_ret,
        "median_return": median_ret,
        "directional_accuracy": directional,
        "by_phase": by_phase,
    }


def run_backtest(
    start: str = "2026-03-01",
    end: str = "2026-04-15",
    sample_every: int = 7,
) -> Dict[str, Any]:
    """Run full historical backtest."""
    print("Full Historical Backtest — Current Transmitted Model")
    print(f"Window: {start} to {end}, sample every {sample_every} days")
    print("=" * 60)

    resolutions = _load_all_resolutions()
    prices = _load_prices()
    logger.info("Loaded %d tickers with resolutions", len(resolutions))

    dates = _find_valid_backtest_dates(start, end, resolutions)
    # Sample every N days to keep runtime manageable
    sampled = dates[::sample_every] if sample_every > 1 else dates
    logger.info("Backtest dates: %d (sampled from %d)", len(sampled), len(dates))

    variants = {
        "A_baseline": {"phase2_prior": 0.310, "inject_clinical": False},
        "B_prior_only": {"phase2_prior": 0.420, "inject_clinical": False},
        "C_full_no_tx": {"phase2_prior": 0.420, "inject_clinical": False},
        "D_current_full": {"phase2_prior": 0.420, "inject_clinical": True},
    }

    all_predictions: Dict[str, Dict[str, List[Dict]]] = {v: {} for v in variants}

    for snap_date in sampled:
        print(f"  {snap_date}...", end="", flush=True)
        for vname, kwargs in variants.items():
            rows = _run_ev_at_date(snap_date, **kwargs)
            all_predictions[vname][snap_date] = rows
        print(f" {len(all_predictions['A_baseline'].get(snap_date, []))} events")

    # Match outcomes
    print("\nMatching outcomes...")
    variant_matched = {}
    for vname, preds in all_predictions.items():
        variant_matched[vname] = _match_outcomes(preds, resolutions, prices)

    # Compute metrics
    print("\nComputing metrics...")
    metrics = {}
    for vname, matched in variant_matched.items():
        metrics[vname] = _compute_metrics(matched, vname)

    # Decision change analysis: D vs A
    changed = _analyze_decision_changes(
        all_predictions["A_baseline"],
        all_predictions["D_current_full"],
        resolutions,
        prices,
    )

    # Print summary
    print(f"\n{'='*60}")
    print("BACKTEST SUMMARY")
    print(f"{'='*60}")
    print(f"{'Variant':>20s} {'N_act':>6s} {'N_out':>6s} {'Hit%':>6s} {'Brier':>8s} {'MeanR':>8s} {'Dir%':>5s}")
    print("-" * 65)
    for vname, m in metrics.items():
        hr = f"{m['hit_rate']:.1%}" if m["hit_rate"] is not None else "-"
        br = f"{m['brier']:.4f}" if m["brier"] is not None else "-"
        mr = f"{m['mean_return']:.4f}" if m["mean_return"] is not None else "-"
        da = f"{m['directional_accuracy']:.0%}" if m["directional_accuracy"] is not None else "-"
        print(f"{vname:>20s} {m['n_actionable']:>6d} {m['n_with_outcome']:>6d} {hr:>6s} {br:>8s} {mr:>8s} {da:>5s}")

    # Phase breakdown
    print("\nPHASE BREAKDOWN (current full model):")
    for ph, stats in metrics.get("D_current_full", {}).get("by_phase", {}).items():
        print(f"  Phase {ph}: n={stats['n']} hit_rate={stats['hit_rate']:.1%}")

    # Decision changes
    print("\nDECISION CHANGES (D vs A):")
    print(f"  Dropped: {changed['n_dropped']} (hit rate: {changed.get('dropped_hit_rate', '-')})")
    print(f"  Gained: {changed['n_gained']} (hit rate: {changed.get('gained_hit_rate', '-')})")

    # Recommendation
    rec = _recommend(metrics, changed)
    print(f"\n{'='*60}")
    print(f"RECOMMENDATION: {rec['verdict']}")
    print(f"  {rec['reasoning']}")

    output = {
        "window": {"start": start, "end": end, "sample_every": sample_every},
        "n_dates": len(sampled),
        "metrics": metrics,
        "decision_changes": changed,
        "recommendation": rec,
    }

    out_path = REPO_ROOT / "artifacts" / "full_model_backtest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nReport: {out_path}")

    return output


def _analyze_decision_changes(
    base_preds: Dict[str, List[Dict]],
    full_preds: Dict[str, List[Dict]],
    resolutions: Dict,
    prices: Any,
) -> Dict[str, Any]:
    """Analyze decisions that changed between baseline and full model."""
    dropped = []
    gained = []

    for snap_date in base_preds:
        if snap_date not in full_preds:
            continue
        base_act = {r["ticker"] for r in base_preds[snap_date] if r["actionable"]}
        full_act = {r["ticker"] for r in full_preds[snap_date] if r["actionable"]}

        for tk in base_act - full_act:
            outcome = None
            recs = resolutions.get(tk, [])
            for rec in recs:
                rd = rec.get("resolution_date", "")
                if rd and rd >= snap_date:
                    outcome = 1 if rec.get("outcome") == "HIT" else 0
                    break
            dropped.append({"ticker": tk, "date": snap_date, "outcome": outcome})

        for tk in full_act - base_act:
            outcome = None
            recs = resolutions.get(tk, [])
            for rec in recs:
                rd = rec.get("resolution_date", "")
                if rd and rd >= snap_date:
                    outcome = 1 if rec.get("outcome") == "HIT" else 0
                    break
            gained.append({"ticker": tk, "date": snap_date, "outcome": outcome})

    d_resolved = [d for d in dropped if d["outcome"] is not None]
    g_resolved = [g for g in gained if g["outcome"] is not None]

    return {
        "n_dropped": len(dropped),
        "n_gained": len(gained),
        "dropped_resolved": len(d_resolved),
        "gained_resolved": len(g_resolved),
        "dropped_hit_rate": (round(sum(d["outcome"] for d in d_resolved) / len(d_resolved), 4) if d_resolved else None),
        "gained_hit_rate": (round(sum(g["outcome"] for g in g_resolved) / len(g_resolved), 4) if g_resolved else None),
    }


def _recommend(metrics: Dict, changed: Dict) -> Dict[str, str]:
    """Generate backtest recommendation."""
    base = metrics.get("A_baseline", {})
    full = metrics.get("D_current_full", {})

    base_brier = base.get("brier")
    full_brier = full.get("brier")
    base_hr = base.get("hit_rate")
    full_hr = full.get("hit_rate")

    n_outcomes = full.get("n_with_outcome", 0)
    if n_outcomes < 10:
        return {
            "verdict": "INSUFFICIENT DATA",
            "reasoning": f"Only {n_outcomes} resolved outcomes. Need ≥10 for backtest conclusion.",
        }

    improvements = []
    regressions = []

    if full_brier is not None and base_brier is not None:
        if full_brier < base_brier:
            improvements.append(f"calibration (Brier {base_brier:.4f}→{full_brier:.4f})")
        else:
            regressions.append(f"calibration (Brier {base_brier:.4f}→{full_brier:.4f})")

    if full_hr is not None and base_hr is not None:
        if full_hr > base_hr:
            improvements.append(f"hit rate ({base_hr:.1%}→{full_hr:.1%})")
        elif full_hr < base_hr - 0.03:
            regressions.append(f"hit rate ({base_hr:.1%}→{full_hr:.1%})")

    dropped_hr = changed.get("dropped_hit_rate")
    if dropped_hr is not None and dropped_hr < 0.40:
        improvements.append(f"dropped names weak ({dropped_hr:.0%} hit rate)")

    if improvements and not regressions:
        return {
            "verdict": "PROMOTE current model",
            "reasoning": f"Improvements: {'; '.join(improvements)}. No regressions.",
        }
    elif improvements and regressions:
        return {
            "verdict": "PROMOTE behind flag",
            "reasoning": f"Improvements: {'; '.join(improvements)}. Regressions: {'; '.join(regressions)}.",
        }
    else:
        return {
            "verdict": "HOLD — no clear improvement",
            "reasoning": f"Regressions: {'; '.join(regressions)}." if regressions else "No measurable change.",
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Full Model Historical Backtest")
    parser.add_argument("--start", default="2026-03-01")
    parser.add_argument("--end", default="2026-04-15")
    parser.add_argument("--sample-every", type=int, default=7)
    args = parser.parse_args()
    run_backtest(start=args.start, end=args.end, sample_every=args.sample_every)

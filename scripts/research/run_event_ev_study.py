#!/usr/bin/env python3
"""Event EV Engine — Research Evaluation Harness (Spec 057).

Runs the full Event EV pipeline on historical data and evaluates:
- Timing model accuracy
- Outcome model calibration
- EV ranking quality
- Portfolio-level comparison vs production baseline

Usage:
    python scripts/research/run_event_ev_study.py --as-of 2026-04-04
    python scripts/research/run_event_ev_study.py --backtest --start 2025-01-01 --end 2026-03-31
    python scripts/research/run_event_ev_study.py --scenario-examples ACAD PVLA TBPH

Output:
    artifacts/event_ev/
        {date}_event_ev_results.json    — full pipeline output
        {date}_summary_table.json       — compact summary
        {date}_timing_eval.json         — timing model diagnostics
        {date}_outcome_eval.json        — outcome calibration
        {date}_portfolio_comparison.json — vs production baseline
        {date}_operator_memo.md         — blunt assessment
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List

# Add project root to path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from event_ev.catalyst_graph import CatalystGraph
from event_ev.data_contracts import EventEV
from event_ev.ev_calculator import EventEVCalculator
from event_ev.outcome_model import OutcomeModel
from event_ev.timing_hazard import TimingHazardModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

ARTIFACTS_DIR = _PROJECT_ROOT / "artifacts" / "event_ev"
PROD_DATA = _PROJECT_ROOT / "production_data"
CACHE_DIR = _PROJECT_ROOT / "cache"
DATA_DIR = _PROJECT_ROOT / "data"


def load_catalyst_graph(as_of: date) -> CatalystGraph:
    """Load catalyst graph from available repo data sources."""
    graph = CatalystGraph()

    # 1. Load PDUFA dates
    pdufa_path = PROD_DATA / "pdufa_dates.json"
    if pdufa_path.exists():
        pdufa = json.loads(pdufa_path.read_text())
        entries = pdufa if isinstance(pdufa, list) else pdufa.get("entries", pdufa.get("dates", []))
        # Normalize field names: pdufa_date → date, as_of_disclosed_at → disclosed_at
        for e in entries:
            if "pdufa_date" in e and "date" not in e:
                e["date"] = e["pdufa_date"]
            if "as_of_disclosed_at" in e and "disclosed_at" not in e:
                e["disclosed_at"] = e["as_of_disclosed_at"]
        n = graph.load_from_pdufa(entries, as_of)
        logger.info("PDUFA: %d nodes", n)

    # 2. Load catalyst events (find most recent snapshot <= as_of)
    cat_files = sorted(PROD_DATA.glob("catalyst_events_*.json"))
    best_file = None
    for f in cat_files:
        try:
            fdate = f.stem.replace("catalyst_events_", "")
            if date.fromisoformat(fdate) <= as_of:
                best_file = f
        except (ValueError, TypeError):
            continue

    if best_file:
        data = json.loads(best_file.read_text())
        summaries = data.get("summaries", [])
        n = graph.load_from_catalyst_events(summaries, as_of)
        logger.info("Catalyst events (%s): %d nodes", best_file.name, n)

    # 3. Load event ledger if available
    ledger_path = DATA_DIR / "catalyst_history" / "catalyst_history_events.jsonl"
    if ledger_path.exists():
        entries = []
        for line in ledger_path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    entry = json.loads(line)
                    # Normalize: pit_available_at → disclosed_at
                    if "pit_available_at" in entry and "disclosed_at" not in entry:
                        entry["disclosed_at"] = entry["pit_available_at"]
                    # Normalize: source_uid from event_id or dedupe_key
                    if "source_uid" not in entry:
                        entry["source_uid"] = entry.get("event_id", entry.get("dedupe_key", ""))
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue
        n = graph.load_from_ledger_entries(entries, as_of)
        logger.info("Event ledger: %d nodes", n)

    # 4. Apply CRT resolutions
    resolutions_dir = DATA_DIR / "snapshots" / "resolutions"
    if resolutions_dir.exists():
        recs = []
        for f in resolutions_dir.rglob("*.json"):
            try:
                data = json.loads(f.read_text())
                # Individual resolution files are dicts with ticker, catalyst_date, etc.
                # Rollup/summary files have 'outcome_distribution' — skip those.
                if isinstance(data, dict) and "ticker" in data and "outcome" in data:
                    recs.append(data)
            except (json.JSONDecodeError, OSError):
                continue
        n = graph.apply_resolutions(recs, as_of)
        logger.info("CRT resolutions: %d applied", n)

    # 5. Manual overrides
    overrides_path = PROD_DATA / "crt_manual_overrides.json"
    if overrides_path.exists():
        try:
            overrides = json.loads(overrides_path.read_text())
            override_list = overrides if isinstance(overrides, list) else overrides.get("overrides", [])
            n = graph.apply_resolutions(override_list, as_of)
            logger.info("Manual overrides: %d applied", n)
        except (json.JSONDecodeError, OSError):
            pass

    logger.info("Catalyst graph: %d total nodes", graph.node_count)
    return graph


def load_market_features(as_of: date) -> Dict[str, Dict[str, Any]]:
    """Load market features from most recent snapshot."""
    features: Dict[str, Dict[str, Any]] = {}

    # Find most recent snapshot
    snapshots_dir = DATA_DIR / "snapshots"
    if not snapshots_dir.exists():
        return features

    snap_dates = []
    for d in snapshots_dir.iterdir():
        if d.is_dir() and len(d.name) == 10:
            try:
                sd = date.fromisoformat(d.name)
                if sd <= as_of:
                    snap_dates.append(sd)
            except (ValueError, TypeError):
                continue

    if not snap_dates:
        return features

    latest = max(snap_dates)
    rankings_path = snapshots_dir / str(latest) / "rankings.csv"
    if not rankings_path.exists():
        return features

    # Parse CSV
    lines = rankings_path.read_text().splitlines()
    if not lines:
        return features

    headers = lines[0].split(",")
    for line in lines[1:]:
        vals = line.split(",")
        if len(vals) != len(headers):
            continue
        row = dict(zip(headers, vals))
        ticker = row.get("ticker", "")
        if not ticker:
            continue

        feat: Dict[str, Any] = {}
        for key in (
            "coinvest_score_z",
            "inst_delta_z",
            "insider_net_buy_value_90d",
            "alpha_60d",
            "de_rsi_14d",
            "short_interest_pct",
            "opt_event_premium",
            "priced_move_pct",
            "market_cap_mm",
            "vol_60d",
            "endpoint_strength_score",
            "design_quality_score",
            "execution_momentum",
            "selector_score",
        ):
            v = row.get(key)
            if v and v not in ("", "NA", "None", "nan"):
                try:
                    feat[key] = float(v)
                except (ValueError, TypeError):
                    pass
        features[ticker] = feat

    logger.info("Market features: %d tickers from %s", len(features), latest)
    return features


def run_single_date(
    as_of: date,
    output_dir: Path,
) -> Dict[str, Any]:
    """Run the full pipeline for a single date."""
    # Load data
    graph = load_catalyst_graph(as_of)
    market_features = load_market_features(as_of)

    # Build context features (subset of market features for outcome model)
    context_features: Dict[str, Dict[str, Any]] = {}
    for ticker, feats in market_features.items():
        ctx = {}
        for key in (
            "endpoint_strength_score",
            "design_quality_score",
            "execution_momentum",
            "market_cap_mm",
            "vol_60d",
        ):
            if key in feats:
                ctx[key] = feats[key]
        context_features[ticker] = ctx

    # Run calculator
    calc = EventEVCalculator(
        as_of_date=as_of,
        max_days=180,
        min_days=0,
    )
    results = calc.run_from_graph(
        graph,
        market_features=market_features,
        context_features=context_features,
        current_weights=None,  # no production weights in research mode
        sizing_mode="ew_filter",
    )

    # Save results
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = str(as_of)

    # Full results
    calc.results_to_json(results, output_dir / f"{prefix}_event_ev_results.json")

    # Summary table
    summary = calc.summary_table(results)
    (output_dir / f"{prefix}_summary_table.json").write_text(json.dumps(summary, indent=2, default=str))

    # Statistics
    stats = compute_run_stats(results, as_of)
    (output_dir / f"{prefix}_run_stats.json").write_text(json.dumps(stats, indent=2, default=str))

    logger.info(
        "Run complete: %d events, %d actionable, top EV=%.2f%%",
        len(results),
        stats["n_actionable"],
        stats.get("top_ev", 0),
    )

    return stats


def compute_run_stats(results: List[EventEV], as_of: date) -> Dict[str, Any]:
    """Compute summary statistics for a single run."""
    actionable = [ev for ev in results if ev.actionable]

    stats: Dict[str, Any] = {
        "as_of_date": str(as_of),
        "n_total": len(results),
        "n_actionable": len(actionable),
    }

    if not results:
        return stats

    evs = [ev.payoff.scenario_ev for ev in results]
    ds_adj = [ev.payoff.downside_adjusted_ev for ev in results]
    p_hits = [ev.outcome.p_hit for ev in results]
    timing_ot = [ev.timing.prob_on_time for ev in results]
    mispricings = [ev.expectation.mispricing_score for ev in results]

    stats.update(
        {
            "top_ev": round(max(evs), 4) if evs else 0,
            "mean_ev": round(sum(evs) / len(evs), 4),
            "median_ev": round(sorted(evs)[len(evs) // 2], 4),
            "top_ds_adj_ev": round(max(ds_adj), 4) if ds_adj else 0,
            "mean_p_hit": round(sum(p_hits) / len(p_hits), 4),
            "mean_timing_on_time": round(sum(timing_ot) / len(timing_ot), 4),
            "mean_mispricing": round(sum(mispricings) / len(mispricings), 4),
            "n_positive_ev": sum(1 for e in evs if e > 0),
            "n_negative_ev": sum(1 for e in evs if e < 0),
            "family_breakdown": {},
            "phase_breakdown": {},
        }
    )

    # Family breakdown
    for ev in results:
        fam = ev.node.event_family
        stats["family_breakdown"].setdefault(fam, 0)
        stats["family_breakdown"][fam] += 1

    # Phase breakdown
    for ev in results:
        phase = ev.node.phase
        stats["phase_breakdown"].setdefault(phase, 0)
        stats["phase_breakdown"][phase] += 1

    # Top 10 by EV
    top_10 = sorted(results, key=lambda e: e.payoff.downside_adjusted_ev, reverse=True)[:10]
    stats["top_10"] = [
        {
            "ticker": ev.node.ticker,
            "event_type": ev.node.event_type,
            "days": ev.node.days_to_event(as_of),
            "scenario_ev": round(ev.scenario_ev, 2),
            "ds_adj_ev": round(ev.payoff.downside_adjusted_ev, 2),
            "p_hit": round(ev.outcome.p_hit, 3),
            "mispricing": round(ev.mispricing_score, 3),
        }
        for ev in top_10
    ]

    return stats


def evaluate_timing(
    graph: CatalystGraph,
    model: TimingHazardModel,
    as_of: date,
) -> Dict[str, Any]:
    """Evaluate timing model on resolved events."""
    resolved = [n for n in graph.get_all_nodes() if n.is_resolved() and n.expected_date]

    correct = 0
    total = 0
    errors = []
    for node in resolved:
        if not node.resolved_date or not node.expected_date:
            continue
        try:
            expected = date.fromisoformat(node.expected_date)
            actual = date.fromisoformat(node.resolved_date)
        except (ValueError, TypeError):
            continue

        # Use date before expected for PIT-safe evaluation
        eval_date = expected - timedelta(days=30)
        if not node.is_visible(eval_date):
            continue

        estimate = model.estimate(node, eval_date)
        delay = (actual - expected).days
        on_time = abs(delay) <= 30

        predicted_on_time = estimate.prob_on_time >= 0.5
        if predicted_on_time == on_time:
            correct += 1
        total += 1
        errors.append(
            {
                "ticker": node.ticker,
                "event_type": node.event_type,
                "expected": str(expected),
                "actual": str(actual),
                "delay_days": delay,
                "on_time": on_time,
                "p_on_time": estimate.prob_on_time,
                "predicted_on_time": predicted_on_time,
            }
        )

    result = {
        "n_evaluated": total,
        "accuracy": round(correct / total, 4) if total > 0 else None,
        "n_correct": correct,
        "errors": errors[:20],  # first 20 for inspection
    }

    if total > 0:
        actual_on_time_rate = sum(1 for e in errors if e["on_time"]) / total
        result["actual_on_time_rate"] = round(actual_on_time_rate, 4)
        result["mean_p_on_time"] = round(sum(e["p_on_time"] for e in errors) / total, 4)

    return result


def evaluate_outcome(
    graph: CatalystGraph,
    model: OutcomeModel,
    as_of: date,
) -> Dict[str, Any]:
    """Evaluate outcome model calibration on resolved events."""
    from event_ev.data_contracts import OutcomeProbabilities

    resolved = [n for n in graph.get_all_nodes() if n.is_resolved() and n.resolution in ("HIT", "MISS", "MIXED")]

    predictions: List[OutcomeProbabilities] = []
    actuals: List[str] = []

    for node in resolved:
        # Use date before expected for PIT-safe evaluation
        if not node.expected_date:
            continue
        try:
            eval_date = date.fromisoformat(node.expected_date) - timedelta(days=30)
        except (ValueError, TypeError):
            continue
        if not node.is_visible(eval_date):
            continue

        pred = model.estimate(node, eval_date)
        predictions.append(pred)
        actuals.append(node.resolution)

    # Calibration evaluation
    cal = model.evaluate_calibration(predictions, actuals)

    # Per-family breakdown
    family_breakdown = {}
    for pred, actual, node in zip(predictions, actuals, resolved):
        fam = node.event_family
        family_breakdown.setdefault(fam, {"predictions": [], "actuals": []})
        family_breakdown[fam]["predictions"].append(pred)
        family_breakdown[fam]["actuals"].append(actual)

    family_cal = {}
    for fam, data in family_breakdown.items():
        family_cal[fam] = model.evaluate_calibration(data["predictions"], data["actuals"])

    return {
        "overall": cal,
        "by_family": family_cal,
        "n_resolved": len(resolved),
        "outcome_distribution": {
            "HIT": sum(1 for a in actuals if a == "HIT"),
            "MISS": sum(1 for a in actuals if a == "MISS"),
            "MIXED": sum(1 for a in actuals if a == "MIXED"),
        },
    }


def run_scenario_examples(
    graph: CatalystGraph,
    calc: EventEVCalculator,
    tickers: List[str],
    market_features: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Run detailed scenario examples for specific tickers."""
    examples = []
    for ticker in tickers:
        nodes = graph.get_active_nodes(ticker, calc.as_of_date)
        if not nodes:
            examples.append({"ticker": ticker, "status": "no_active_catalysts"})
            continue

        for node in nodes:
            feats = market_features.get(ticker, {})
            evs = calc.run(
                catalyst_nodes=[node],
                market_features={ticker: feats},
                context_features={ticker: feats},
            )
            if evs:
                ev = evs[0]
                examples.append(
                    {
                        "ticker": ticker,
                        "event_type": node.event_type,
                        "expected_date": node.expected_date,
                        "full_ev": ev.to_dict(),
                    }
                )
            else:
                examples.append(
                    {
                        "ticker": ticker,
                        "event_type": node.event_type,
                        "status": "filtered_out",
                    }
                )

    return examples


def main() -> None:
    parser = argparse.ArgumentParser(description="Event EV Engine Research Harness")
    parser.add_argument("--as-of", type=str, default=str(date.today()), help="Evaluation date")
    parser.add_argument("--backtest", action="store_true", help="Run backtest over date range")
    parser.add_argument("--start", type=str, help="Backtest start date")
    parser.add_argument("--end", type=str, help="Backtest end date")
    parser.add_argument("--scenario-examples", nargs="+", help="Run detailed examples for tickers")
    parser.add_argument("--output-dir", type=str, default=str(ARTIFACTS_DIR))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    as_of = date.fromisoformat(args.as_of)

    if args.backtest:
        # Monthly backtest
        start = date.fromisoformat(args.start) if args.start else as_of - timedelta(days=365)
        end = date.fromisoformat(args.end) if args.end else as_of

        all_stats = []
        current = start
        while current <= end:
            logger.info("=== Backtest date: %s ===", current)
            try:
                stats = run_single_date(current, output_dir / "backtest")
                all_stats.append(stats)
            except Exception:
                logger.exception("Failed for %s", current)

            # Advance by ~1 month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

        # Save backtest summary
        bt_path = output_dir / "backtest_summary.json"
        bt_path.write_text(json.dumps(all_stats, indent=2, default=str))
        logger.info("Backtest complete: %d periods, saved to %s", len(all_stats), bt_path)

    elif args.scenario_examples:
        # Scenario examples
        graph = load_catalyst_graph(as_of)
        market_features = load_market_features(as_of)
        calc = EventEVCalculator(as_of_date=as_of)

        examples = run_scenario_examples(graph, calc, args.scenario_examples, market_features)
        out_path = output_dir / f"{as_of}_scenario_examples.json"
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(examples, indent=2, default=str))
        logger.info("Scenario examples saved to %s", out_path)

        # Print summary
        for ex in examples:
            if "full_ev" in ex:
                ev = ex["full_ev"]
                print(f"\n{ex['ticker']} | {ex['event_type']} | {ex.get('expected_date', '?')}")
                print(
                    f"  P(HIT)={ev['outcome']['p_hit']:.3f}  "
                    f"P(MISS)={ev['outcome']['p_miss']:.3f}  "
                    f"P(MIXED)={ev['outcome']['p_mixed']:.3f}"
                )
                print(
                    f"  Implied P(HIT)={ev['expectation']['implied_p_hit']:.3f}  "
                    f"Mispricing={ev['expectation']['mispricing_score']:+.3f}"
                )
                print(
                    f"  Upside={ev['payoff']['upside_hit']:+.1f}%  " f"Downside={ev['payoff']['downside_miss']:+.1f}%"
                )
                print(
                    f"  Scenario EV={ev['payoff']['scenario_ev']:+.2f}%  "
                    f"DS-adj EV={ev['payoff']['downside_adjusted_ev']:+.2f}%"
                )
                print(f"  Timing on-time={ev['timing']['prob_on_time']:.3f}  " f"Slip={ev['timing']['prob_slip']:.3f}")
            else:
                print(f"\n{ex['ticker']}: {ex.get('status', 'unknown')}")

    else:
        # Single date run
        stats = run_single_date(as_of, output_dir)

        # Also run evaluations
        graph = load_catalyst_graph(as_of)
        timing_model = TimingHazardModel()
        outcome_model = OutcomeModel()

        timing_eval = evaluate_timing(graph, timing_model, as_of)
        (output_dir / f"{as_of}_timing_eval.json").write_text(json.dumps(timing_eval, indent=2, default=str))

        outcome_eval = evaluate_outcome(graph, outcome_model, as_of)
        (output_dir / f"{as_of}_outcome_eval.json").write_text(json.dumps(outcome_eval, indent=2, default=str))

        # Print top names
        print(f"\n{'='*70}")
        print(f"Event EV Engine — {as_of}")
        print(f"{'='*70}")
        print(f"Total events: {stats['n_total']}")
        print(f"Actionable:   {stats['n_actionable']}")
        print(f"Positive EV:  {stats.get('n_positive_ev', 0)}")
        print(f"Mean EV:      {stats.get('mean_ev', 0):+.2f}%")
        print()

        if stats.get("top_10"):
            print(
                f"{'Rank':>4} {'Ticker':<8} {'Type':<20} {'Days':>5} "
                f"{'P(HIT)':>7} {'Misprice':>9} {'Scen EV':>8} {'DS-Adj':>8}"
            )
            print("-" * 75)
            for i, row in enumerate(stats["top_10"], 1):
                print(
                    f"{i:4d} {row['ticker']:<8} {row['event_type']:<20} "
                    f"{row.get('days', '?'):>5} {row['p_hit']:>7.3f} "
                    f"{row['mispricing']:>+9.3f} {row['scenario_ev']:>+8.2f} "
                    f"{row['ds_adj_ev']:>+8.2f}"
                )

        # Timing eval summary
        if timing_eval.get("accuracy") is not None:
            print(f"\nTiming model: accuracy={timing_eval['accuracy']:.3f} " f"(n={timing_eval['n_evaluated']})")

        # Outcome eval summary
        overall = outcome_eval.get("overall", {})
        if overall.get("brier_score") is not None:
            print(
                f"Outcome model: Brier={overall['brier_score']:.4f} "
                f"ECE={overall.get('ece', '?')} "
                f"(n={overall.get('n', '?')})"
            )


if __name__ == "__main__":
    main()

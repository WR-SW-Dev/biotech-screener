#!/usr/bin/env python3
"""Passive replay: committee_prior vs empirical posterior on FDA_ADCOM subset.

For each AdCom calendar cache, scores every ticker two ways:
  A) committee_prior only (no posterior table — current production behavior)
  B) empirical posterior (using adcom_outcomes.json posterior table)

Reports per-ticker deltas and summary statistics.

Usage:
    python3 scripts/research/replay_adcom_empirical.py [--out-dir DIR]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.adcom_empirical import build_posterior_table, load_outcomes
from common.adcom_vote_features import compute_adcom_vote_features

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

OUTCOMES_PATH = PROJECT_ROOT / "production_data" / "adcom_outcomes.json"
ADCOM_CACHE_DIR = PROJECT_ROOT / "cache" / "fda"
DEFAULT_OUT_DIR = PROJECT_ROOT / "output" / "research" / "adcom_empirical_replay"


def discover_caches() -> List[Path]:
    """Find all adcom_calendar_*.json cache files, sorted by date."""
    return sorted(ADCOM_CACHE_DIR.glob("adcom_calendar_*.json"))


def extract_as_of_date(cache_path: Path) -> str:
    """Extract YYYY-MM-DD from adcom_calendar_YYYY-MM-DD.json."""
    stem = cache_path.stem  # adcom_calendar_2026-03-09
    return stem.replace("adcom_calendar_", "")


def replay_one_cache(
    cache_path: Path,
    outcomes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Score all tickers in one cache file under both regimes.

    Returns list of per-ticker result dicts.
    """
    as_of_date = extract_as_of_date(cache_path)
    events = json.loads(cache_path.read_text(encoding="utf-8"))

    # Build empirical posterior table (PIT-safe)
    posterior_table = build_posterior_table(outcomes, as_of_date)

    # Group events by ticker
    by_ticker: Dict[str, List[Dict[str, Any]]] = {}
    for ev in events:
        tk = (ev.get("ticker") or "").upper()
        if tk:
            by_ticker.setdefault(tk, []).append(ev)

    results = []
    for ticker, ticker_events in sorted(by_ticker.items()):
        # A) committee_prior only (no posterior_table)
        prior_features = compute_adcom_vote_features(ticker, ticker_events, as_of_date, posterior_table=None)

        # B) empirical posterior
        emp_features = compute_adcom_vote_features(ticker, ticker_events, as_of_date, posterior_table=posterior_table)

        prior_score = prior_features.get("adcom_vote_score", "")
        emp_score = emp_features.get("adcom_vote_score", "")

        # Determine committee for this ticker's nearest event
        committee = ""
        for ev in ticker_events:
            committee = ev.get("committee", "")
            break

        delta = None
        if isinstance(prior_score, (int, float)) and isinstance(emp_score, (int, float)):
            delta = round(emp_score - prior_score, 4)

        results.append(
            {
                "as_of_date": as_of_date,
                "ticker": ticker,
                "committee": committee,
                "prior_score": prior_score,
                "prior_signal": prior_features.get("adcom_vote_signal", ""),
                "prior_basis": prior_features.get("adcom_vote_basis", ""),
                "prior_n": prior_features.get("adcom_vote_n", ""),
                "emp_score": emp_score,
                "emp_signal": emp_features.get("adcom_vote_signal", ""),
                "emp_basis": emp_features.get("adcom_vote_basis", ""),
                "emp_n": emp_features.get("adcom_vote_n", ""),
                "delta": delta,
                "days_until": prior_features.get("adcom_vote_recency_days", ""),
            }
        )

    return results


def format_report(all_results: List[Dict[str, Any]], posterior_table: Dict) -> str:
    """Format a human-readable report."""
    lines = []
    lines.append("=" * 78)
    lines.append("ADCOM EMPIRICAL REPLAY: committee_prior vs empirical posterior")
    lines.append("=" * 78)
    lines.append("")

    # Posterior table summary
    lines.append("Posterior table entries:")
    if posterior_table:
        for key, entry in sorted(posterior_table.items()):
            lines.append(f"  {key}: score={entry['score']:.4f}  n={entry['n']}  basis={entry['basis']}")
    else:
        lines.append("  (empty — no committee crosses MIN_OBSERVATIONS)")
    lines.append("")

    # Group by as_of_date
    by_date: Dict[str, List[Dict]] = {}
    for r in all_results:
        by_date.setdefault(r["as_of_date"], []).append(r)

    changed_count = 0

    for aod in sorted(by_date):
        rows = by_date[aod]
        lines.append(f"--- {aod} ({len(rows)} tickers) ---")
        for r in rows:
            delta_str = f"{r['delta']:+.4f}" if r["delta"] is not None else "N/A"
            signal_change = ""
            if r["prior_signal"] and r["emp_signal"] and r["prior_signal"] != r["emp_signal"]:
                signal_change = f"  SIGNAL: {r['prior_signal']} → {r['emp_signal']}"

            if r["delta"] is not None and r["delta"] != 0:
                changed_count += 1
                marker = " ***"
            else:
                marker = ""

            # Handle empty scores (ticker outside relevance window)
            ps = r["prior_score"]
            es = r["emp_score"]
            ps_str = f"{ps:.4f}" if isinstance(ps, (int, float)) else str(ps)
            es_str = f"{es:.4f}" if isinstance(es, (int, float)) else str(es)

            lines.append(
                f"  {r['ticker']:6s}  "
                f"prior={ps_str} ({r['prior_basis']})  "
                f"emp={es_str} ({r['emp_basis']}, n={r['emp_n']})  "
                f"delta={delta_str}  "
                f"days={r['days_until']}"
                f"{signal_change}{marker}"
            )
        lines.append("")

    # Summary
    scored = [r for r in all_results if r["delta"] is not None]
    changed = [r for r in scored if r["delta"] != 0]
    unchanged = [r for r in scored if r["delta"] == 0]

    lines.append("=" * 78)
    lines.append("SUMMARY")
    lines.append("=" * 78)
    lines.append(f"Total ticker-date observations: {len(all_results)}")
    lines.append(f"  Scored (both regimes): {len(scored)}")
    lines.append(f"  Changed (delta != 0):  {len(changed)}")
    lines.append(f"  Unchanged:             {len(unchanged)}")

    if changed:
        deltas = [r["delta"] for r in changed]
        lines.append(f"  Mean delta:            {sum(deltas)/len(deltas):+.4f}")
        lines.append(f"  Min delta:             {min(deltas):+.4f}")
        lines.append(f"  Max delta:             {max(deltas):+.4f}")

        # Signal changes
        signal_changes = [r for r in changed if r["prior_signal"] != r["emp_signal"]]
        lines.append(f"  Signal changes:        {len(signal_changes)}")
        for r in signal_changes:
            lines.append(
                f"    {r['ticker']} ({r['as_of_date']}): "
                f"{r['prior_signal']} → {r['emp_signal']} "
                f"(delta={r['delta']:+.4f})"
            )

    # Basis breakdown
    lines.append("")
    lines.append("Basis breakdown (empirical arm):")
    basis_counts: Dict[str, int] = {}
    for r in all_results:
        b = r.get("emp_basis", "")
        basis_counts[b] = basis_counts.get(b, 0) + 1
    for b, c in sorted(basis_counts.items()):
        lines.append(f"  {b}: {c}")

    # Committee breakdown
    lines.append("")
    lines.append("Per-committee deltas:")
    by_committee: Dict[str, List[float]] = {}
    for r in scored:
        c = r["committee"]
        by_committee.setdefault(c, []).append(r["delta"])
    for c in sorted(by_committee):
        ds = by_committee[c]
        mean_d = sum(ds) / len(ds)
        lines.append(f"  {c[:50]:50s}  n={len(ds)}  mean_delta={mean_d:+.4f}")

    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Replay AdCom empirical vs prior scoring")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    # Load outcomes
    outcomes = load_outcomes(OUTCOMES_PATH)
    print(f"Loaded {len(outcomes)} provenance-validated AdCom outcome records")

    # Discover caches
    caches = discover_caches()
    if not caches:
        print("ERROR: No adcom_calendar_*.json files found in cache/fda/")
        sys.exit(1)
    print(f"Found {len(caches)} AdCom calendar caches")

    # Build posterior table at latest date for summary
    latest_date = extract_as_of_date(caches[-1])
    posterior_table = build_posterior_table(outcomes, latest_date)
    print(f"Posterior table at {latest_date}: {len(posterior_table)} entries")
    for key, entry in sorted(posterior_table.items()):
        print(f"  {key}: score={entry['score']:.4f}  n={entry['n']}")

    # Replay each cache
    all_results: List[Dict[str, Any]] = []
    for cache_path in caches:
        aod = extract_as_of_date(cache_path)
        results = replay_one_cache(cache_path, outcomes)
        all_results.extend(results)
        n_changed = sum(1 for r in results if r["delta"] and r["delta"] != 0)
        print(f"  {aod}: {len(results)} tickers, {n_changed} changed")

    # Generate report
    report = format_report(all_results, posterior_table)
    print()
    print(report)

    # Write outputs
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.out_dir / "replay_report.txt"
    report_path.write_text(report, encoding="utf-8")

    json_path = args.out_dir / "replay_results.json"
    json_path.write_text(json.dumps(all_results, indent=2), encoding="utf-8")

    print(f"\nWritten: {report_path}")
    print(f"Written: {json_path}")


if __name__ == "__main__":
    main()

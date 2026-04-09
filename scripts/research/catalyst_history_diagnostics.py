#!/usr/bin/env python3
"""Catalyst history coverage diagnostics (Spec 034, Phase C).

Analyzes the event ledger for coverage quality, source mix over time,
date-revision rates, and negative-event coverage.

Output:
    artifacts/catalyst_history/{date}_diagnostics.json
    artifacts/catalyst_history/{date}_diagnostics.md

Usage:
    python scripts/research/catalyst_history_diagnostics.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("catalyst_diagnostics")


def load_events(events_path: Path) -> List[Dict]:
    events = []
    if not events_path.exists():
        return events
    with open(events_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events


def build_diagnostics(events: List[Dict], as_of_date: str) -> Dict:
    """Build comprehensive coverage diagnostics."""

    # --- Overall stats ---
    n_events = len(events)
    tickers = set(e["ticker"] for e in events)
    sources = Counter(e.get("source_family", "OTHER") for e in events)
    event_types = Counter(e.get("event_type", "") for e in events)
    confidences = Counter(str(e.get("confidence", "")).upper() for e in events)

    # --- Temporal coverage ---
    # Events per year
    year_counts: Dict[str, int] = Counter()
    for e in events:
        ed = e.get("event_date", "")
        if len(ed) >= 4:
            year_counts[ed[:4]] += 1

    # --- Source mix by year ---
    source_by_year: Dict[str, Dict[str, int]] = defaultdict(Counter)
    for e in events:
        ed = e.get("event_date", "")
        if len(ed) >= 4:
            source_by_year[ed[:4]][e.get("source_family", "OTHER")] += 1

    # --- Negative regulatory events ---
    negative_types = {"FDA_CRL", "FDA_RTF", "FDA_WARNING_LETTER", "CLINICAL_HOLD", "SAFETY_SIGNAL"}
    neg_events = [e for e in events if e.get("event_type", "") in negative_types]
    neg_tickers = Counter(e["ticker"] for e in neg_events)

    # --- Date revision detection ---
    # Group by (ticker, event_type, source_family) and look for events with
    # same ticker+type but different dates (potential revisions)
    event_groups: Dict[str, List[str]] = defaultdict(list)
    for e in events:
        key = f"{e['ticker']}|{e.get('event_type', '')}|{e.get('source_family', '')}"
        event_groups[key].append(e.get("event_date", ""))

    n_potential_revisions = 0
    revision_examples = []
    for key, dates in event_groups.items():
        unique_dates = sorted(set(dates))
        if len(unique_dates) > 1:
            n_potential_revisions += 1
            if len(revision_examples) < 5:
                revision_examples.append({"key": key, "dates": unique_dates[:5]})

    # --- Coverage gaps ---
    # Tickers in universe but with few or no events
    universe_path = PROJECT_ROOT / "production_data" / "universe.json"
    universe_tickers = set()
    if universe_path.exists():
        uni = json.load(open(universe_path))
        if isinstance(uni, list):
            universe_tickers = {t.get("ticker", t) if isinstance(t, dict) else t for t in uni}

    uncovered = universe_tickers - tickers
    low_coverage = {t for t in tickers if sum(1 for e in events if e["ticker"] == t) < 3}

    # --- Multi-source confirmation ---
    # Tickers with events from 2+ source families
    ticker_sources: Dict[str, set] = defaultdict(set)
    for e in events:
        ticker_sources[e["ticker"]].add(e.get("source_family", "OTHER"))
    multi_source = {t for t, srcs in ticker_sources.items() if len(srcs) >= 2}
    single_source = tickers - multi_source

    return {
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": {
            "n_events": n_events,
            "n_tickers": len(tickers),
            "n_universe_tickers": len(universe_tickers),
            "coverage_pct": round(len(tickers) / max(len(universe_tickers), 1) * 100, 1),
            "events_per_ticker_median": (
                sorted(Counter(e["ticker"] for e in events).values())[len(tickers) // 2] if tickers else 0
            ),
        },
        "source_mix": dict(sources.most_common()),
        "source_pct": {k: round(v / max(n_events, 1) * 100, 1) for k, v in sources.most_common()},
        "event_types_top10": dict(event_types.most_common(10)),
        "confidence_dist": dict(confidences.most_common()),
        "temporal": {
            "events_by_year": dict(sorted(year_counts.items())),
            "source_by_year": {y: dict(s) for y, s in sorted(source_by_year.items())},
        },
        "negative_events": {
            "n_total": len(neg_events),
            "n_tickers": len(neg_tickers),
            "top_tickers": dict(neg_tickers.most_common(10)),
            "types": dict(Counter(e["event_type"] for e in neg_events).most_common()),
        },
        "date_revisions": {
            "n_potential_revisions": n_potential_revisions,
            "examples": revision_examples,
        },
        "coverage_quality": {
            "n_uncovered_universe": len(uncovered),
            "uncovered_sample": sorted(uncovered)[:20],
            "n_low_coverage": len(low_coverage),
            "n_multi_source": len(multi_source),
            "n_single_source": len(single_source),
            "multi_source_pct": round(len(multi_source) / max(len(tickers), 1) * 100, 1),
        },
    }


def format_diagnostics_md(d: Dict) -> str:
    lines = []
    o = d["overall"]
    lines.append(f"# Catalyst History Diagnostics — {d['as_of_date']}")
    lines.append("")
    lines.append(
        f"**{o['n_events']} events** | **{o['n_tickers']} tickers** | "
        f"**{o['coverage_pct']}%** universe coverage | "
        f"median {o['events_per_ticker_median']} events/ticker"
    )
    lines.append("")

    lines.append("## Source Mix")
    lines.append("")
    lines.append("| Source | Events | % |")
    lines.append("|--------|--------|---|")
    for src, pct in d.get("source_pct", {}).items():
        cnt = d["source_mix"].get(src, 0)
        lines.append(f"| {src} | {cnt} | {pct}% |")
    lines.append("")

    lines.append("## Events by Year")
    lines.append("")
    lines.append("| Year | Events |")
    lines.append("|------|--------|")
    for year, cnt in d.get("temporal", {}).get("events_by_year", {}).items():
        lines.append(f"| {year} | {cnt} |")
    lines.append("")

    neg = d.get("negative_events", {})
    lines.append("## Negative Regulatory Events")
    lines.append("")
    lines.append(f"**{neg['n_total']} events** across **{neg['n_tickers']} tickers**")
    lines.append("")
    if neg.get("top_tickers"):
        lines.append("| Ticker | Count |")
        lines.append("|--------|-------|")
        for t, c in neg["top_tickers"].items():
            lines.append(f"| {t} | {c} |")
        lines.append("")

    rev = d.get("date_revisions", {})
    lines.append("## Date Revisions")
    lines.append("")
    lines.append(f"**{rev['n_potential_revisions']} event groups** with multiple dates (potential revisions)")
    lines.append("")

    cq = d.get("coverage_quality", {})
    lines.append("## Coverage Quality")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Uncovered universe tickers | {cq['n_uncovered_universe']} |")
    lines.append(f"| Low coverage (<3 events) | {cq['n_low_coverage']} |")
    lines.append(f"| Multi-source confirmation | {cq['n_multi_source']} ({cq['multi_source_pct']}%) |")
    lines.append(f"| Single-source only | {cq['n_single_source']} |")
    lines.append("")

    lines.append(f"*Generated: {d.get('generated_at', '')}*")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Catalyst history diagnostics (Spec 034, Phase C)")
    parser.add_argument(
        "--events", type=Path, default=PROJECT_ROOT / "data" / "catalyst_history" / "catalyst_history_events.jsonl"
    )
    parser.add_argument("--as-of-date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = parser.parse_args()

    events = load_events(args.events)
    logger.info("Loaded %d events", len(events))

    diag = build_diagnostics(events, args.as_of_date)

    out_dir = PROJECT_ROOT / "artifacts" / "catalyst_history"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"{args.as_of_date}_diagnostics.json"
    md_path = out_dir / f"{args.as_of_date}_diagnostics.md"

    with open(json_path, "w") as f:
        json.dump(diag, f, indent=2, default=str)
    logger.info("Wrote %s", json_path)

    md_path.write_text(format_diagnostics_md(diag))
    logger.info("Wrote %s", md_path)

    # Summary
    o = diag["overall"]
    logger.info("Coverage: %d/%d tickers (%.1f%%)", o["n_tickers"], o["n_universe_tickers"], o["coverage_pct"])
    logger.info("Negative events: %d", diag["negative_events"]["n_total"])
    logger.info("Date revisions: %d groups", diag["date_revisions"]["n_potential_revisions"])


if __name__ == "__main__":
    main()

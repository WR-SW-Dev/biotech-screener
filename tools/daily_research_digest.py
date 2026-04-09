#!/usr/bin/env python3
"""Daily biotech research digest — one-screen summary for stock selection.

Reads the latest promoted snapshot and produces a concise research-ready
digest: top names, new entrants/exits, big movers, catalyst timing,
and health warnings.

Read-only — does not change rankings, scoring, or execution.

Usage:
    python tools/daily_research_digest.py
    python tools/daily_research_digest.py --as-of-date 2026-03-18
    python tools/daily_research_digest.py --top-n 20
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("daily_research_digest")

SCHEMA_VERSION = "research_digest.v1"


def load_snapshot(snap_dir: Path) -> List[Dict[str, Any]]:
    """Load rankings.csv from a snapshot directory."""
    path = snap_dir / "rankings.csv"
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_prior_snapshot(snapshots_root: Path, current_date: str) -> List[Dict[str, Any]]:
    """Find and load the most recent snapshot before current_date."""
    candidates = sorted(
        [
            d.name
            for d in snapshots_root.iterdir()
            if d.is_dir() and d.name < current_date and (d / "rankings.csv").exists()
        ],
        reverse=True,
    )
    if not candidates:
        return []
    return load_snapshot(snapshots_root / candidates[0]), candidates[0]


def build_digest(
    current_rows: List[Dict[str, Any]],
    prior_rows: List[Dict[str, Any]],
    prior_date: str,
    as_of_date: str,
    top_n: int = 20,
    mover_threshold: int = 5,
) -> Dict[str, Any]:
    """Build the research digest from current and prior snapshots."""

    def _eligible(rows):
        return [
            r for r in rows if r.get("eligible", "").lower() in ("true", "1", "yes") and r.get("actionable_rank", "")
        ]

    current = _eligible(current_rows)
    current.sort(key=lambda r: int(r["actionable_rank"]))
    prior = _eligible(prior_rows)
    prior_by_ticker = {r["ticker"]: r for r in prior}
    # Top names
    top_names = []
    for r in current[:top_n]:
        rank = int(r["actionable_rank"])
        ticker = r["ticker"]
        prior_r = prior_by_ticker.get(ticker)
        prior_rank = int(prior_r["actionable_rank"]) if prior_r else None
        rank_delta = prior_rank - rank if prior_rank else None

        top_names.append(
            {
                "rank": rank,
                "ticker": ticker,
                "company": r.get("company_name", ""),
                "tier": r.get("tier_any", ""),
                "bucket": r.get("catalyst_bucket", ""),
                "catalyst_days": r.get("catalyst_days", ""),
                "catalyst_family": r.get("catalyst_family", ""),
                "archetype": r.get("archetype", ""),
                "score_rank_pct": r.get("score_rank_pct", ""),
                "binary_quality": r.get("binary_quality_score", ""),
                "prior_rank": prior_rank,
                "rank_delta": rank_delta,
                "top_drivers": r.get("top_3_drivers", ""),
                "risk_flags": r.get("risk_flags", ""),
                "cheap_vol": r.get("vol_classification", ""),
            }
        )

    # New entrants (in current top_n but not in prior top_n)
    prior_top_tickers = set(r["ticker"] for r in prior[:top_n]) if prior else set()
    current_top_tickers = set(r["ticker"] for r in current[:top_n])
    new_entrants = [t for t in top_names if t["ticker"] not in prior_top_tickers]
    exits = [tk for tk in prior_top_tickers if tk not in current_top_tickers]

    # Big movers (rank changed by >= mover_threshold)
    movers = []
    for r in current[:60]:
        ticker = r["ticker"]
        rank = int(r["actionable_rank"])
        prior_r = prior_by_ticker.get(ticker)
        if not prior_r:
            continue
        prior_rank = int(prior_r["actionable_rank"])
        delta = prior_rank - rank
        if abs(delta) >= mover_threshold:
            movers.append(
                {
                    "ticker": ticker,
                    "rank": rank,
                    "prior_rank": prior_rank,
                    "delta": delta,
                    "direction": "UP" if delta > 0 else "DOWN",
                    "tier": r.get("tier_any", ""),
                    "bucket": r.get("catalyst_bucket", ""),
                }
            )
    movers.sort(key=lambda m: -abs(m["delta"]))

    # Catalyst timing summary
    catalyst_summary = {"binary_now": 0, "build_window": 0, "less_binary": 0, "core": 0}
    for r in current[:top_n]:
        bucket = r.get("catalyst_bucket", "other")
        if bucket in catalyst_summary:
            catalyst_summary[bucket] += 1

    # Health warnings from snapshot
    health_warnings = []
    health_path = Path(REPO_ROOT / "data" / "snapshots" / as_of_date / "data_collection_health.json")
    if health_path.exists():
        hd = json.loads(health_path.read_text())
        if hd.get("status") in ("WARN", "FAIL"):
            health_warnings = hd.get("flags", [])

    return {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "prior_date": prior_date,
        "n_eligible": len(current),
        "top_n": top_n,
        "top_names": top_names,
        "new_entrants": [t["ticker"] for t in new_entrants],
        "exits": exits,
        "movers": movers[:10],
        "catalyst_summary": catalyst_summary,
        "health_warnings": health_warnings,
    }


def render_markdown(digest: Dict[str, Any]) -> str:
    """Render the digest as a concise markdown one-pager."""
    d = digest
    lines = [
        f"# Biotech Research Digest — {d['as_of_date']}",
        "",
        f"*{d['n_eligible']} eligible names | vs {d['prior_date']}*",
        "",
    ]

    # Health warnings
    if d["health_warnings"]:
        lines.append("**Health warnings:**")
        for w in d["health_warnings"]:
            lines.append(f"- {w}")
        lines.append("")

    # Top names table
    lines.append(f"## Top {d['top_n']} Research Names\n")
    lines.append("| Rank | Ticker | Tier | Bucket | Cat Days | Family | Quality | " "Vol Class | Delta | Drivers |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for t in d["top_names"]:
        delta_str = ""
        if t["rank_delta"] is not None:
            delta_str = f"{t['rank_delta']:+d}" if t["rank_delta"] != 0 else "="
        if t["ticker"] in d["new_entrants"]:
            delta_str = "NEW"
        bqs = t.get("binary_quality", "")
        if bqs:
            try:
                bqs = f"{float(bqs):.2f}"
            except ValueError:
                pass
        drivers = t.get("top_drivers", "")[:30]
        lines.append(
            f"| {t['rank']} | **{t['ticker']}** | {t['tier']} | {t['bucket']} "
            f"| {t['catalyst_days']} | {t['catalyst_family']} "
            f"| {bqs} | {t.get('cheap_vol', '')} "
            f"| {delta_str} | {drivers} |"
        )
    lines.append("")

    # New entrants and exits
    if d["new_entrants"] or d["exits"]:
        lines.append("## Changes vs Prior\n")
        if d["new_entrants"]:
            lines.append(f"**New entrants** (top {d['top_n']}): {', '.join(d['new_entrants'])}")
        if d["exits"]:
            lines.append(f"**Exits** (top {d['top_n']}): {', '.join(d['exits'])}")
        lines.append("")

    # Big movers
    if d["movers"]:
        lines.append("## Biggest Movers\n")
        lines.append("| Ticker | Rank | Prior | Delta | Direction | Bucket |")
        lines.append("|---|---|---|---|---|---|")
        for m in d["movers"]:
            lines.append(
                f"| {m['ticker']} | {m['rank']} | {m['prior_rank']} "
                f"| {m['delta']:+d} | {m['direction']} | {m['bucket']} |"
            )
        lines.append("")

    # Catalyst timing
    cs = d["catalyst_summary"]
    lines.append("## Catalyst Timing (top names)\n")
    lines.append(f"- **Binary now** (0-30d): {cs.get('binary_now', 0)}")
    lines.append(f"- **Build window** (31-90d): {cs.get('build_window', 0)}")
    lines.append(f"- **Less binary** (91-180d): {cs.get('less_binary', 0)}")
    lines.append(f"- **Core** (180d+): {cs.get('core', 0)}")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily biotech research digest")
    parser.add_argument(
        "--as-of-date",
        type=str,
        default=None,
        help="Snapshot date (default: latest)",
    )
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--mover-threshold", type=int, default=5)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "output" / "research_digest",
    )
    args = parser.parse_args()

    snapshots_root = REPO_ROOT / "data" / "snapshots"

    # Find latest snapshot if no date given
    if args.as_of_date:
        as_of = args.as_of_date
    else:
        candidates = sorted(
            [
                d.name
                for d in snapshots_root.iterdir()
                if d.is_dir() and not d.name.startswith("_") and (d / "rankings.csv").exists()
            ],
            reverse=True,
        )
        if not candidates:
            logger.error("No snapshots found")
            return 1
        as_of = candidates[0]

    snap_dir = snapshots_root / as_of
    if not (snap_dir / "rankings.csv").exists():
        logger.error("No rankings.csv in %s", snap_dir)
        return 1

    current = load_snapshot(snap_dir)
    prior_result = load_prior_snapshot(snapshots_root, as_of)
    if prior_result:
        prior, prior_date = prior_result
    else:
        prior, prior_date = [], ""

    digest = build_digest(current, prior, prior_date, as_of, args.top_n, args.mover_threshold)

    # Write outputs
    args.output_dir.mkdir(parents=True, exist_ok=True)

    md_content = render_markdown(digest)
    md_path = args.output_dir / f"digest_{as_of}.md"
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".md",
        dir=str(args.output_dir),
        delete=False,
    ) as tmp:
        tmp.write(md_content)
        tmp_name = tmp.name
    os.replace(tmp_name, str(md_path))

    json_path = args.output_dir / f"digest_{as_of}.json"
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        dir=str(args.output_dir),
        delete=False,
    ) as tmp:
        json.dump(digest, tmp, indent=2, default=str)
        tmp_name = tmp.name
    os.replace(tmp_name, str(json_path))

    # Print to console
    print(md_content)
    logger.info("Wrote %s", md_path)
    logger.info("Wrote %s", json_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())

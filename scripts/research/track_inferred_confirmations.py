#!/usr/bin/env python3
"""Track confirmation rate and date accuracy of inferred regulatory entries.

For each inferred regulatory entry, check whether a confirmed PDUFA has
since appeared. Report per-source accuracy metrics.

Usage:
    python scripts/research/track_inferred_confirmations.py
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def load_confirmed(data_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Load confirmed PDUFA entries → {ticker: {date, drug, ...}}."""
    path = data_dir / "pdufa_dates.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    entries = data if isinstance(data, list) else data.get("events", [])
    result = {}
    for e in entries:
        tk = e.get("ticker", "").upper()
        if tk:
            result[tk] = {
                "pdufa_date": e.get("pdufa_date", ""),
                "drug_name": e.get("drug_name", ""),
                "source": e.get("source", ""),
            }
    return result


def load_inferred(data_dir: Path) -> List[Dict[str, Any]]:
    """Load inferred regulatory entries."""
    path = data_dir / "inferred_regulatory_dates.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return data.get("entries", [])


def track_confirmations(
    inferred: List[Dict[str, Any]],
    confirmed: Dict[str, Dict[str, Any]],
    as_of: date,
) -> List[Dict[str, Any]]:
    """Cross-reference inferred entries against confirmed PDUFA calendar."""
    results = []

    for entry in inferred:
        ticker = entry.get("ticker", "").upper()
        inferred_date = entry.get("pdufa_date", "")
        source = entry.get("source", "")

        status = "pending"
        confirmed_date = ""
        delta_days = None

        if ticker in confirmed:
            conf = confirmed[ticker]
            confirmed_date = conf.get("pdufa_date", "")

            if confirmed_date and inferred_date:
                try:
                    d_inf = date.fromisoformat(inferred_date)
                    d_conf = date.fromisoformat(confirmed_date)
                    delta_days = (d_conf - d_inf).days
                    status = "confirmed"
                except (ValueError, TypeError):
                    status = "confirmed_no_date_match"
            elif confirmed_date:
                status = "confirmed_no_inferred_date"
            else:
                status = "confirmed_no_confirmed_date"
        else:
            # Check if the inferred date has passed without confirmation
            if inferred_date:
                try:
                    d_inf = date.fromisoformat(inferred_date)
                    if d_inf < as_of:
                        status = "expired_unconfirmed"
                except (ValueError, TypeError):
                    pass

        results.append(
            {
                "ticker": ticker,
                "source": source,
                "inferred_date": inferred_date,
                "confirmed_date": confirmed_date,
                "delta_days": delta_days,
                "status": status,
                "event_type": entry.get("event_type", ""),
                "confidence": entry.get("confidence_numeric", ""),
            }
        )

    return results


def main() -> int:
    data_dir = PROJECT_ROOT / "production_data"
    output_dir = PROJECT_ROOT / "output" / "inferred_confirmation_tracking"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Loading confirmed PDUFA entries ...")
    confirmed = load_confirmed(data_dir)
    logger.info("Confirmed: %d entries", len(confirmed))

    logger.info("Loading inferred entries ...")
    inferred = load_inferred(data_dir)
    logger.info("Inferred: %d entries", len(inferred))

    if not inferred:
        logger.warning("No inferred entries to track")
        return 0

    as_of = date.today()
    results = track_confirmations(inferred, confirmed, as_of)

    # Per-source accuracy
    from collections import defaultdict

    by_source: Dict[str, List] = defaultdict(list)
    for r in results:
        by_source[r["source"]].append(r)

    source_stats = {}
    for src, entries in by_source.items():
        n_total = len(entries)
        n_confirmed = sum(1 for e in entries if e["status"] == "confirmed")
        n_expired = sum(1 for e in entries if e["status"] == "expired_unconfirmed")
        n_pending = sum(1 for e in entries if e["status"] == "pending")
        deltas = [e["delta_days"] for e in entries if e["delta_days"] is not None]

        source_stats[src] = {
            "n_total": n_total,
            "n_confirmed": n_confirmed,
            "n_expired": n_expired,
            "n_pending": n_pending,
            "confirmation_rate": round(n_confirmed / n_total, 2) if n_total else 0,
            "mean_delta_days": round(sum(deltas) / len(deltas), 1) if deltas else None,
            "median_delta_days": sorted(deltas)[len(deltas) // 2] if deltas else None,
        }

    # Write outputs
    report = {
        "as_of": as_of.isoformat(),
        "n_inferred": len(inferred),
        "n_confirmed_tickers": len(confirmed),
        "source_stats": source_stats,
        "entries": results,
    }
    (output_dir / "confirmation_tracking.json").write_text(json.dumps(report, indent=2, default=str) + "\n")

    # Markdown
    md = [
        "# Inferred Regulatory Confirmation Tracking",
        "",
        f"**As-of**: {as_of.isoformat()}",
        f"**Inferred entries**: {len(inferred)}",
        f"**Confirmed PDUFA tickers**: {len(confirmed)}",
        "",
        "## Per-Source Accuracy",
        "",
        "| Source | Total | Confirmed | Expired | Pending | Confirm Rate | Mean Delta |",
        "|--------|-------|-----------|---------|---------|-------------|-----------|",
    ]
    for src, stats in sorted(source_stats.items()):
        md.append(
            f"| {src} | {stats['n_total']} | {stats['n_confirmed']} | {stats['n_expired']} "
            f"| {stats['n_pending']} | {stats['confirmation_rate']:.0%} "
            f"| {stats['mean_delta_days'] if stats['mean_delta_days'] is not None else '—'} |"
        )

    md += [
        "",
        "## Entry Details",
        "",
        "| Ticker | Source | Inferred | Confirmed | Delta | Status |",
        "|--------|--------|----------|-----------|-------|--------|",
    ]
    for r in sorted(results, key=lambda x: x["ticker"]):
        delta = str(r["delta_days"]) if r["delta_days"] is not None else "—"
        md.append(
            f"| {r['ticker']} | {r['source']} | {r['inferred_date']} | {r['confirmed_date']} | {delta} | {r['status']} |"
        )

    md.append("")
    (output_dir / "confirmation_tracking.md").write_text("\n".join(md))

    logger.info("Tracking → %s", output_dir)
    for src, stats in source_stats.items():
        logger.info(
            "  %s: %d total, %d confirmed, rate=%.0f%%",
            src,
            stats["n_total"],
            stats["n_confirmed"],
            stats["confirmation_rate"] * 100,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())

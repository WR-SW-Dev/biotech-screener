#!/usr/bin/env python3
"""Unified production health monitor — overlap, dispersion, catalyst quality, ranker drift.

Tracks day-over-day changes in the live production book to surface
operational drift that individual monitors miss. Read-only — does NOT
modify rankings, scoring, or execution.

Monitors:
  1. Position overlap (Jaccard + rank correlation vs prior day)
  2. Weight dispersion (HHI — flags drift from equal-weight)
  3. Catalyst quality (book-avg event_type_score, hard-catalyst %, timing confidence)
  4. Ranker drift (pairwise vs clinical_50 overlap from shadow comparison)

Output:
    artifacts/production_monitor/{date}_monitor.json
    artifacts/production_monitor/{date}_monitor.md

Usage:
    python tools/build_production_monitor.py --as-of-date 2026-04-04
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("production_monitor")

SCHEMA_VERSION = "production_monitor.v1"

# Thresholds
OVERLAP_WARN = 0.80  # Jaccard overlap below this triggers warn
OVERLAP_ALERT = 0.60
HHI_WARN = 500  # HHI above this for 30-position EW book (EW30 ≈ 333)
RANKER_DIVERGENCE_WARN = 5  # >5 names differ between pairwise and clinical_50

# Event type score mapping (Spec 056)
EVENT_TYPE_SCORE_MAP = {
    "FDA_PDUFA_DATE": 3,
    "DATA_READOUT": 2,
    "CT_PRIMARY_COMPLETION": 1,
    "CT_STUDY_COMPLETION": 1,
    "CT_RESULTS_POSTED": 0,
    "CT_TRIAL_SUSPENDED": 0,
    "IR_EVENT": 0,
}


def _sf(val: Any) -> float:
    if val is None or val == "":
        return math.nan
    try:
        return float(val)
    except (ValueError, TypeError):
        return math.nan


def _load_json(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _load_positions(date: str, artifacts_dir: Path) -> List[Dict]:
    path = artifacts_dir / "live_shadow" / "positions" / f"{date}.json"
    data = _load_json(path)
    if not data:
        return []
    return data.get("positions", [])


def _load_rankings(date: str, snapshots_dir: Path) -> Dict[str, Dict]:
    rpath = snapshots_dir / date / "rankings.csv"
    if not rpath.exists():
        return {}
    with open(rpath, encoding="utf-8") as f:
        return {r["ticker"]: r for r in csv.DictReader(f)}


def _find_prior_date(date: str, artifacts_dir: Path) -> Optional[str]:
    """Find the most recent position file before the given date."""
    pos_dir = artifacts_dir / "live_shadow" / "positions"
    if not pos_dir.exists():
        return None
    import re

    date_pat = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
    dates = sorted(f.stem for f in pos_dir.iterdir() if date_pat.match(f.name) and f.stem < date)
    return dates[-1] if dates else None


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def compute_overlap(today_tickers: set, prior_tickers: set) -> Dict[str, Any]:
    """Jaccard overlap between two position sets."""
    if not today_tickers or not prior_tickers:
        return {"jaccard": None, "added": [], "removed": [], "n_common": 0}
    intersection = today_tickers & prior_tickers
    union = today_tickers | prior_tickers
    jaccard = len(intersection) / len(union) if union else 0
    return {
        "jaccard": round(jaccard, 4),
        "added": sorted(today_tickers - prior_tickers),
        "removed": sorted(prior_tickers - today_tickers),
        "n_common": len(intersection),
    }


def compute_rank_correlation(today_ranks: Dict[str, int], prior_ranks: Dict[str, int]) -> Optional[float]:
    """Spearman rank correlation on common tickers."""
    common = set(today_ranks) & set(prior_ranks)
    if len(common) < 5:
        return None
    tickers = sorted(common)
    x = [today_ranks[t] for t in tickers]
    y = [prior_ranks[t] for t in tickers]
    n = len(x)
    # Spearman via rank difference
    d_sq = sum((xi - yi) ** 2 for xi, yi in zip(x, y))
    rho = 1 - 6 * d_sq / (n * (n * n - 1))
    return round(rho, 4)


def compute_hhi(weights: List[float]) -> float:
    """Herfindahl-Hirschman Index of position weights (in basis points).

    For EW with 30 names: HHI ≈ 333. Higher = more concentrated.
    """
    if not weights:
        return 0
    total = sum(weights)
    if total <= 0:
        return 0
    shares = [w / total * 100 for w in weights]
    return round(sum(s * s for s in shares), 1)


def compute_catalyst_quality(rankings: Dict[str, Dict], tickers: set) -> Dict[str, Any]:
    """Compute catalyst quality metrics for the book."""
    scores = []
    hard_count = 0
    n_with_catalyst = 0
    for t in tickers:
        r = rankings.get(t, {})
        # Event type score
        evt = r.get("catalyst_event_type", "")
        ets = EVENT_TYPE_SCORE_MAP.get(evt, 0) if evt else None
        if ets is not None:
            scores.append(ets)

        # Hard catalyst
        hard = _sf(r.get("is_hard_catalyst"))
        if hard == 1.0:
            hard_count += 1

        # Catalyst presence
        cat_days = _sf(r.get("catalyst_days"))
        if not math.isnan(cat_days) and cat_days > 0:
            n_with_catalyst += 1

    n = len(tickers) or 1
    return {
        "mean_event_type_score": round(sum(scores) / len(scores), 2) if scores else None,
        "hard_catalyst_pct": round(hard_count / n * 100, 1),
        "has_catalyst_pct": round(n_with_catalyst / n * 100, 1),
        "n_scored": len(scores),
    }


def load_ranker_shadow(
    date: str, artifacts_dir: Path, snapshots_dir: Path = REPO_ROOT / "data" / "snapshots"
) -> Optional[Dict]:
    """Load ranker shadow comparison for this date.

    Checks both the snapshot directory (where run_screen.py writes it)
    and the artifacts directory (legacy path).
    """
    # Primary: snapshot directory (where run_screen.py actually writes it)
    path = snapshots_dir / date / "ranker_shadow_comparison.json"
    if path.exists():
        return _load_json(path)
    # Fallback: artifacts directory (legacy paths)
    path = artifacts_dir / "ranker_shadow_comparison.json"
    if path.exists():
        return _load_json(path)
    path = artifacts_dir / f"ranker_shadow_comparison_{date}.json"
    return _load_json(path)


def compute_ranker_drift(shadow: Optional[Dict]) -> Dict[str, Any]:
    """Extract ranker divergence metrics from shadow comparison."""
    if not shadow:
        return {"overlap": None, "n_divergent": None, "status": "no_data"}

    overlap = shadow.get("overlap_count")
    n_pairwise = shadow.get("n_pairwise", 30)
    n_clinical = shadow.get("n_clinical", 30)
    if overlap is not None:
        n_divergent = max(n_pairwise, n_clinical) - overlap
    else:
        n_divergent = None

    return {
        "overlap": overlap,
        "n_divergent": n_divergent,
        "pairwise_top": shadow.get("pairwise_only", [])[:5],
        "clinical_only": shadow.get("clinical_only", [])[:5],
        "status": "ok",
    }


# ---------------------------------------------------------------------------
# Alert classification
# ---------------------------------------------------------------------------


def classify_alerts(
    overlap: Dict[str, Any],
    hhi: float,
    ranker_drift: Dict[str, Any],
) -> List[Dict[str, str]]:
    """Generate production health alerts."""
    alerts = []

    # Overlap alerts
    jaccard = overlap.get("jaccard")
    if jaccard is not None:
        if jaccard < OVERLAP_ALERT:
            alerts.append(
                {
                    "level": "ALERT",
                    "code": "POSITION_OVERLAP_LOW",
                    "detail": f"Jaccard={jaccard:.2f} (added: {overlap['added']}, removed: {overlap['removed']})",
                }
            )
        elif jaccard < OVERLAP_WARN:
            alerts.append(
                {
                    "level": "WARN",
                    "code": "POSITION_OVERLAP_LOW",
                    "detail": f"Jaccard={jaccard:.2f}",
                }
            )

    # HHI alerts
    if hhi > HHI_WARN:
        alerts.append(
            {
                "level": "WARN",
                "code": "WEIGHT_CONCENTRATION",
                "detail": f"HHI={hhi:.0f} (EW30 baseline=333)",
            }
        )

    # Ranker drift
    n_div = ranker_drift.get("n_divergent")
    if n_div is not None and n_div > RANKER_DIVERGENCE_WARN:
        alerts.append(
            {
                "level": "WARN",
                "code": "RANKER_DIVERGENCE",
                "detail": f"{n_div} names differ between pairwise and clinical_50",
            }
        )

    return alerts


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_production_monitor(
    as_of_date: str,
    *,
    artifacts_dir: Path = REPO_ROOT / "artifacts",
    snapshots_dir: Path = REPO_ROOT / "data" / "snapshots",
) -> Dict[str, Any]:
    """Build unified production monitor artifact."""
    # Load today's positions
    today_positions = _load_positions(as_of_date, artifacts_dir)
    if not today_positions:
        return {"error": f"no positions for {as_of_date}"}

    today_tickers = {p.get("ticker", "") for p in today_positions}
    today_weights = [p.get("weight_pct", 0) for p in today_positions]
    today_ranks = {}
    rankings = _load_rankings(as_of_date, snapshots_dir)
    for t in today_tickers:
        r = rankings.get(t, {})
        ar = r.get("actionable_rank", "")
        if ar:
            try:
                today_ranks[t] = int(ar)
            except ValueError:
                pass

    # Load prior day
    prior_date = _find_prior_date(as_of_date, artifacts_dir)
    prior_tickers = set()
    prior_ranks: Dict[str, int] = {}
    if prior_date:
        prior_positions = _load_positions(prior_date, artifacts_dir)
        prior_tickers = {p.get("ticker", "") for p in prior_positions}
        prior_rankings = _load_rankings(prior_date, snapshots_dir)
        for t in prior_tickers:
            r = prior_rankings.get(t, {})
            ar = r.get("actionable_rank", "")
            if ar:
                try:
                    prior_ranks[t] = int(ar)
                except ValueError:
                    pass

    # Compute metrics
    overlap = compute_overlap(today_tickers, prior_tickers)
    rank_corr = compute_rank_correlation(today_ranks, prior_ranks)
    hhi = compute_hhi(today_weights)
    catalyst_quality = compute_catalyst_quality(rankings, today_tickers)
    ranker_shadow = load_ranker_shadow(as_of_date, artifacts_dir, snapshots_dir)
    ranker_drift = compute_ranker_drift(ranker_shadow)

    # Alerts
    alerts = classify_alerts(overlap, hhi, ranker_drift)

    n_alerts = sum(1 for a in alerts if a["level"] == "ALERT")
    n_warns = sum(1 for a in alerts if a["level"] == "WARN")
    if n_alerts > 0:
        attention = "HIGH"
    elif n_warns > 0:
        attention = "MEDIUM"
    else:
        attention = "LOW"

    result = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "prior_date": prior_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "attention": attention,
        "n_positions": len(today_positions),
        "overlap": overlap,
        "rank_correlation": rank_corr,
        "hhi": hhi,
        "catalyst_quality": catalyst_quality,
        "ranker_drift": ranker_drift,
        "alerts": alerts,
    }

    # Write artifacts
    out_dir = artifacts_dir / "production_monitor"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"{as_of_date}_monitor.json"
    md_path = out_dir / f"{as_of_date}_monitor.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Wrote %s", json_path)

    md_text = format_monitor_md(result)
    md_path.write_text(md_text, encoding="utf-8")
    logger.info("Wrote %s", md_path)

    result["_json_path"] = str(json_path)
    result["_md_path"] = str(md_path)
    return result


# ---------------------------------------------------------------------------
# Markdown formatter
# ---------------------------------------------------------------------------


def format_monitor_md(d: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"# Production Monitor — {d['as_of_date']}")
    lines.append("")
    lines.append(f"**Attention: {d['attention']}** | Prior: {d.get('prior_date', '?')}")
    lines.append("")

    # Overlap
    ov = d.get("overlap", {})
    lines.append("## Position Overlap")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Jaccard overlap | {ov.get('jaccard', '?')} |")
    lines.append(f"| Common names | {ov.get('n_common', '?')} |")
    lines.append(f"| Rank correlation | {d.get('rank_correlation', '?')} |")
    if ov.get("added"):
        lines.append(f"| Added | {', '.join(ov['added'])} |")
    if ov.get("removed"):
        lines.append(f"| Removed | {', '.join(ov['removed'])} |")
    lines.append("")

    # Dispersion
    lines.append("## Weight Dispersion")
    lines.append("")
    lines.append(f"- HHI: {d.get('hhi', '?')} (EW30 baseline = 333)")
    lines.append(f"- Positions: {d.get('n_positions', '?')}")
    lines.append("")

    # Catalyst quality
    cq = d.get("catalyst_quality", {})
    lines.append("## Catalyst Quality")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Mean event_type_score | {cq.get('mean_event_type_score', '?')} |")
    lines.append(f"| Hard catalyst % | {cq.get('hard_catalyst_pct', '?')}% |")
    lines.append(f"| Has catalyst % | {cq.get('has_catalyst_pct', '?')}% |")
    lines.append("")

    # Ranker drift
    rd = d.get("ranker_drift", {})
    if rd.get("status") != "no_data":
        lines.append("## Ranker Drift")
        lines.append("")
        lines.append(f"- Overlap: {rd.get('overlap', '?')} names")
        lines.append(f"- Divergent: {rd.get('n_divergent', '?')} names")
        if rd.get("pairwise_top"):
            lines.append(f"- Pairwise-only: {', '.join(rd['pairwise_top'])}")
        if rd.get("clinical_only"):
            lines.append(f"- Clinical-only: {', '.join(rd['clinical_only'])}")
        lines.append("")

    # Alerts
    alerts = d.get("alerts", [])
    if alerts:
        lines.append("## Alerts")
        lines.append("")
        for a in alerts:
            lines.append(f"- **{a['level']}** [{a['code']}]: {a['detail']}")
        lines.append("")

    lines.append(f"*Generated: {d.get('generated_at', '')}*")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Unified production health monitor")
    parser.add_argument("--as-of-date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--artifacts-dir", type=Path, default=REPO_ROOT / "artifacts")
    parser.add_argument("--snapshots-dir", type=Path, default=REPO_ROOT / "data" / "snapshots")
    args = parser.parse_args()

    result = build_production_monitor(
        args.as_of_date,
        artifacts_dir=args.artifacts_dir,
        snapshots_dir=args.snapshots_dir,
    )

    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)

    logger.info(
        "Production monitor: %s attention, %d alerts, HHI=%.0f, overlap=%s",
        result["attention"],
        len(result["alerts"]),
        result["hhi"],
        result["overlap"].get("jaccard", "?"),
    )


if __name__ == "__main__":
    main()

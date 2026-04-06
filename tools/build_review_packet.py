#!/usr/bin/env python3
"""Daily review packet — unified timing + event quality operating layer.

Reads all timing and event quality artifacts for a snapshot date and produces
a single review packet containing:
  - Timing calibration by family/horizon
  - Top timing warnings with reasons
  - Event-type distribution in live book
  - Herald precision / confusion summary
  - Source reliability table
  - Review priority queue

Usage:
    python tools/build_review_packet.py
    python tools/build_review_packet.py --snapshot-date 2026-04-05
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
OUTPUT_DIR = ARTIFACTS_DIR / "review"

SCHEMA = "review_packet.v1"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Artifact loaders (all return None on missing/error)
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as e:
        logger.warning("Failed to load %s: %s", path, e)
        return None


def _find_latest_dated(directory: Path, prefix: str, ext: str = ".json") -> Path | None:
    """Find the most recent dated file matching prefix_YYYY-MM-DD.ext."""
    if not directory.exists():
        return None
    matches = sorted(directory.glob(f"{prefix}*{ext}"), reverse=True)
    return matches[0] if matches else None


def load_timing_hazard(snap_date: str) -> dict | None:
    path = ARTIFACTS_DIR / "timing_hazard" / f"timing_hazard_{snap_date}.json"
    return _load_json(path)


def load_calibration_dashboard() -> dict | None:
    path = ARTIFACTS_DIR / "timing_hazard" / "calibration_dashboard.json"
    return _load_json(path)


def load_calibration_by_slice() -> dict | None:
    path = ARTIFACTS_DIR / "timing_hazard" / "calibration_by_slice.json"
    return _load_json(path)


def load_event_quality_shadow(snap_date: str) -> dict | None:
    path = ARTIFACTS_DIR / "event_quality_shadow" / f"event_quality_shadow_{snap_date}.json"
    return _load_json(path)


def load_review_priority(snap_date: str) -> dict | None:
    path = ARTIFACTS_DIR / "review" / f"review_priority_{snap_date}.json"
    return _load_json(path)


def load_herald_precision_dashboard() -> dict | None:
    path = _find_latest_dated(ARTIFACTS_DIR / "herald_precision", "dashboard")
    return _load_json(path) if path else None


def load_confusion_dashboard() -> dict | None:
    path = ARTIFACTS_DIR / "event_quality" / "confusion_dashboard.json"
    return _load_json(path)


def load_source_reliability() -> dict | None:
    """Load latest source reliability table."""
    rel_dir = ARTIFACTS_DIR / "calendar_source_reliability"
    if not rel_dir.exists():
        return None
    dates = sorted(
        (d.name for d in rel_dir.iterdir() if d.is_dir()),
        reverse=True,
    )
    if not dates:
        return None
    path = rel_dir / dates[0] / "source_reliability.json"
    return _load_json(path)


# ---------------------------------------------------------------------------
# Packet assembly
# ---------------------------------------------------------------------------


def _summarize_timing_warnings(timing: dict) -> list[dict]:
    """Extract top timing warnings with reasons."""
    warnings = []
    for cat in timing.get("catalysts", []):
        if not cat.get("execution_warning_flag"):
            continue
        warnings.append(
            {
                "ticker": cat["ticker"],
                "rank": cat["rank"],
                "catalyst_days": cat["catalyst_days"],
                "catalyst_family": cat.get("catalyst_family", ""),
                "on_time_prob": cat["on_time_prob"],
                "confidence": cat["timing_confidence_bucket"],
                "warnings": [(w["label"] if isinstance(w, dict) else str(w)) for w in cat.get("warning_reasons", [])],
                "top_reason": (
                    cat["warning_reasons"][0]["reason"]
                    if cat.get("warning_reasons") and isinstance(cat["warning_reasons"][0], dict)
                    else str(cat["warning_reasons"][0]) if cat.get("warning_reasons") else ""
                ),
            }
        )
    return warnings


def _summarize_calibration(cal: dict | None) -> dict:
    """Summarize calibration dashboard into packet-friendly format."""
    if not cal:
        return {"available": False}

    return {
        "available": True,
        "n_resolved": cal.get("n_resolved", 0),
        "overall_brier": cal.get("overall", {}).get("brier"),
        "overall_overconfidence": cal.get("overall", {}).get("overconfidence"),
        "by_horizon": {
            h: {
                "n": v.get("n", 0),
                "brier": v.get("brier"),
                "actual_rate": v.get("actual_rate"),
            }
            for h, v in cal.get("horizons", {}).items()
        },
        "by_source_top5": sorted(
            [{"source": s, "n": v.get("n", 0), "brier": v.get("brier")} for s, v in cal.get("sources", {}).items()],
            key=lambda x: x["n"],
            reverse=True,
        )[:5],
    }


def _summarize_event_type_dist(eq_shadow: dict | None) -> dict:
    """Summarize event type distribution from shadow sizer."""
    if not eq_shadow:
        return {"available": False}
    return {
        "available": True,
        "n_positions": eq_shadow.get("n_positions", 0),
        "event_type_dist": eq_shadow.get("event_type_dist", {}),
        "mean_event_type_score": _mean_ets(eq_shadow),
    }


def _mean_ets(eq_shadow: dict) -> float | None:
    positions = eq_shadow.get("positions", [])
    scores = [p["event_type_score"] for p in positions if p.get("event_type_score") is not None]
    return round(sum(scores) / len(scores), 2) if scores else None


def _summarize_herald_precision(hp: dict | None) -> dict:
    """Summarize Herald precision dashboard."""
    if not hp:
        return {"available": False}
    rolling = hp.get("rolling_metrics", {})
    return {
        "available": True,
        "false_informational_rate": rolling.get("rolling_informational", {}).get("false_informational_rate"),
        "severity_reaction_rate": rolling.get("rolling_severity", {}).get("reaction_rate"),
        "crt_agreement_rate": rolling.get("rolling_crt", {}).get("category_agreement_rate"),
        "drift_flags": hp.get("drift_flags", []),
    }


def _summarize_confusion(confusion: dict | None) -> dict:
    """Summarize confusion dashboard."""
    if not confusion:
        return {"available": False}
    return {
        "available": True,
        "n_labeled": confusion.get("n_labeled", 0),
        "accuracy": confusion.get("overall", {}).get("accuracy"),
        "top_confusion_pairs": confusion.get("top_confusion_pairs", [])[:3],
        "drift_flags": confusion.get("drift_flags", []),
    }


def _summarize_source_reliability(rel: dict | None) -> list[dict]:
    """Summarize source reliability table."""
    if not rel:
        return []
    buckets = rel.get("buckets", [])
    summary = []
    for b in buckets:
        summary.append(
            {
                "source": b.get("source", ""),
                "family": b.get("family", ""),
                "action": b.get("action", "UNKNOWN"),
                "reliability_score": b.get("reliability_score"),
                "sample_count": b.get("sample_count", 0),
                "large_slip_rate": b.get("large_slip_rate", 0),
            }
        )
    # Sort: SUPPRESS first, then DEMOTE, then by reliability_score ascending
    action_order = {"SUPPRESS": 0, "DEMOTE": 1, "UNKNOWN": 2, "ALLOW": 3}
    summary.sort(key=lambda x: (action_order.get(x["action"], 9), x.get("reliability_score") or 0))
    return summary


def build_review_packet(snapshot_date: str | None = None) -> dict:
    """Assemble the unified review packet from all available artifacts."""
    # Find snapshot date
    if not snapshot_date:
        available = sorted(
            d.name
            for d in SNAPSHOTS_DIR.iterdir()
            if d.is_dir() and (d / "rankings.csv").exists() and "__pre_" not in d.name and not d.name.startswith("_")
        )
        if not available:
            return {"error": "no snapshots found"}
        snapshot_date = available[-1]

    # Load artifacts
    timing = load_timing_hazard(snapshot_date)
    cal_dashboard = load_calibration_dashboard()
    eq_shadow = load_event_quality_shadow(snapshot_date)
    review_priority = load_review_priority(snapshot_date)
    herald_precision = load_herald_precision_dashboard()
    confusion = load_confusion_dashboard()
    source_rel = load_source_reliability()

    # Assemble packet sections
    packet = {
        "schema": SCHEMA,
        "snapshot_date": snapshot_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifacts_loaded": {
            "timing_hazard": timing is not None,
            "calibration_dashboard": cal_dashboard is not None,
            "event_quality_shadow": eq_shadow is not None,
            "review_priority": review_priority is not None,
            "herald_precision": herald_precision is not None,
            "confusion_dashboard": confusion is not None,
            "source_reliability": source_rel is not None,
        },
    }

    # 1. Timing section
    if timing:
        packet["timing"] = {
            "n_catalysts": timing.get("n_catalysts", 0),
            "n_warnings": timing.get("n_warnings", 0),
            "rolling_base_rate": timing.get("rolling_base_rate"),
            "base_rate_trend": timing.get("base_rate_trend"),
            "confidence_dist": timing.get("confidence_dist", {}),
            "mean_on_time_prob": timing.get("mean_on_time_prob"),
            "warnings": _summarize_timing_warnings(timing),
        }
    else:
        packet["timing"] = {"available": False}

    # 2. Calibration section
    packet["calibration"] = _summarize_calibration(cal_dashboard)

    # 3. Event type distribution
    packet["event_type_distribution"] = _summarize_event_type_dist(eq_shadow)

    # 4. Herald precision
    packet["herald_precision"] = _summarize_herald_precision(herald_precision)

    # 5. Confusion dashboard
    packet["confusion"] = _summarize_confusion(confusion)

    # 6. Source reliability
    packet["source_reliability"] = _summarize_source_reliability(source_rel)

    # 7. Review priority queue
    if review_priority:
        packet["review_queue"] = {
            "n_flagged": review_priority.get("n_reviewed", 0),
            "n_candidates": review_priority.get("n_candidates", 0),
            "top_priorities": review_priority.get("priorities", [])[:10],
        }
    else:
        packet["review_queue"] = {"available": False}

    # Overall health summary
    n_sections = sum(
        1
        for k in ("timing", "calibration", "event_type_distribution", "herald_precision", "confusion")
        if packet.get(k, {}).get("available", True) is not False
    )
    packet["health"] = {
        "sections_available": n_sections,
        "sections_total": 5,
        "has_timing_warnings": bool(packet.get("timing", {}).get("warnings")),
        "has_drift_flags": bool(packet.get("confusion", {}).get("drift_flags"))
        or bool(packet.get("herald_precision", {}).get("drift_flags")),
    }

    return packet


def render_review_packet_md(packet: dict) -> str:
    """Render the review packet as a compact operator-readable markdown document."""
    snap = packet.get("snapshot_date", "?")
    lines = [
        f"# Review Packet — {snap}",
        "",
        f"*Generated: {packet.get('generated_at', '?')}*  ",
        "*Status: DIAGNOSTIC / NON-BINDING*",
        "",
    ]

    # Health summary
    timing = packet.get("timing", {})
    cal = packet.get("calibration", {})

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(
        f"| Artifacts loaded | {sum(packet.get('artifacts_loaded', {}).values())}/{len(packet.get('artifacts_loaded', {}))} |"
    )
    lines.append(f"| Timing warnings | {timing.get('n_warnings', 0)} |")
    lines.append(f"| Rolling base rate | {timing.get('rolling_base_rate', '—')} |")
    trend = timing.get("base_rate_trend")
    lines.append(f"| Base rate trend | {f'{trend:+.3f}' if trend is not None else '—'} |")
    lines.append(f"| Calibration | {cal.get('n_resolved', 0)} resolved, Brier={cal.get('overall_brier', '—')} |")

    eq = packet.get("event_type_distribution", {})
    if eq.get("available"):
        lines.append(f"| Mean event_type_score | {eq.get('mean_event_type_score', '—')} |")

    confusion = packet.get("confusion", {})
    if confusion.get("available"):
        lines.append(
            f"| Herald accuracy | {confusion.get('accuracy', '—')} ({confusion.get('n_labeled', 0)} labeled) |"
        )

    lines.append("")

    # Top timing warnings
    warnings = timing.get("warnings", [])
    if warnings:
        lines.append("## Top Timing Warnings")
        lines.append("")
        lines.append("| Ticker | Rank | Days | Family | Prob | Warnings |")
        lines.append("|--------|------|------|--------|------|----------|")
        for w in warnings[:10]:
            wlabels = ", ".join(w.get("warnings", []))
            lines.append(
                f"| {w['ticker']} | {w['rank']} | {w['catalyst_days']} "
                f"| {w.get('catalyst_family', '—')} | {w['on_time_prob']:.2f} "
                f"| {wlabels} |"
            )
        lines.append("")

    # Calibration health
    if cal.get("available"):
        lines.append("## Calibration Health")
        lines.append("")
        by_horizon = cal.get("by_horizon", {})
        if by_horizon:
            lines.append("| Horizon | N | Brier | Actual Rate |")
            lines.append("|---------|---|-------|-------------|")
            for h, v in sorted(by_horizon.items()):
                lines.append(f"| {h} | {v.get('n', 0)} | {v.get('brier', '—')} | {v.get('actual_rate', '—')} |")
            lines.append("")

    # Event quality
    if eq.get("available"):
        lines.append("## Event Quality")
        lines.append("")
        dist = eq.get("event_type_dist", {})
        if dist:
            lines.append(f"Event type distribution: {dist}")
        lines.append("")

    # Herald precision
    hp = packet.get("herald_precision", {})
    if hp.get("available"):
        lines.append("## Herald Precision")
        lines.append("")
        lines.append(f"- False informational rate: {hp.get('false_informational_rate', '—')}")
        lines.append(f"- Severity reaction rate: {hp.get('severity_reaction_rate', '—')}")
        lines.append(f"- CRT agreement rate: {hp.get('crt_agreement_rate', '—')}")
        drift = hp.get("drift_flags", [])
        if drift:
            lines.append(f"- **DRIFT FLAGS**: {len(drift)}")
        lines.append("")

    # Review queue
    rq = packet.get("review_queue", {})
    if rq.get("top_priorities"):
        lines.append("## Operator Priority Queue")
        lines.append("")
        for p in rq["top_priorities"][:10]:
            ticker = p.get("ticker", "?")
            reasons = ", ".join(p.get("reasons", []))
            lines.append(f"- **{ticker}**: {reasons}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Build unified review packet")
    parser.add_argument("--snapshot-date", default=None, help="Snapshot date (default: latest)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    packet = build_review_packet(args.snapshot_date)

    if "error" in packet:
        print(f"ERROR: {packet['error']}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    snap = packet["snapshot_date"]

    # Write JSON
    out_json = OUTPUT_DIR / f"{snap}_review_packet.json"
    out_json.write_text(json.dumps(packet, indent=2, default=str))

    # Write Markdown
    out_md = OUTPUT_DIR / f"{snap}_review_packet.md"
    out_md.write_text(render_review_packet_md(packet))

    # Print summary
    print(f"REVIEW PACKET -- {snap}")
    print(f"  Artifacts loaded: {sum(packet['artifacts_loaded'].values())}/{len(packet['artifacts_loaded'])}")

    if packet.get("timing", {}).get("n_warnings"):
        print(f"  Timing warnings: {packet['timing']['n_warnings']}")
        for w in packet["timing"].get("warnings", [])[:5]:
            print(f"    {w['ticker']:6s} rank={w['rank']:2d} [{', '.join(w['warnings'])}]")

    if packet.get("timing", {}).get("base_rate_trend") is not None:
        trend = packet["timing"]["base_rate_trend"]
        print(f"  Base rate trend: {'+' if trend >= 0 else ''}{trend:.3f}")

    cal = packet.get("calibration", {})
    if cal.get("available"):
        print(f"  Calibration: {cal['n_resolved']} resolved, Brier={cal['overall_brier']}")

    eq = packet.get("event_type_distribution", {})
    if eq.get("available"):
        print(f"  Event type dist: {eq['event_type_dist']} (mean={eq['mean_event_type_score']})")

    rq = packet.get("review_queue", {})
    if rq.get("n_flagged"):
        print(f"  Review queue: {rq['n_flagged']}/{rq['n_candidates']} flagged")

    print(f"  Saved: {out_json}")
    print(f"  Saved: {out_md}")


if __name__ == "__main__":
    main()

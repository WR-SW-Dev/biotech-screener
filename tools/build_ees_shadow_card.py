#!/usr/bin/env python3
"""EES v3 daily shadow card — tracks operational shadow gate progress.

Reads the EES v3 forward monitor artifact and today's production snapshot
to build a daily status card showing:
  1. Days since DIAGNOSTIC_WIRING_APPROVED (2026-06-25)
  2. 20d shadow gate progress (observations started, when gate clears)
  3. raw_veto_core (ees_v3_score) IC trend from completed observations
  4. Today's EES veto fires against current snapshot

Classification: EES_SHADOW_OBSERVATION_ONLY — no model change, no production
promotion, no ranking change.

Usage:
    python tools/build_ees_shadow_card.py
    python tools/build_ees_shadow_card.py --as-of-date 2026-06-27
    python tools/build_ees_shadow_card.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from datetime import date as dt_date
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("build_ees_shadow_card")

ARTIFACT_DIR = REPO_ROOT / "artifacts" / "ees_shadow_monitor"
SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"
MONITOR_PATH = REPO_ROOT / "artifacts" / "ees_v3_monitor_native_20260625.json"

DIAGNOSTIC_WIRING_APPROVED = dt_date(2026, 6, 25)
GATE_20D_REQUIRED = 20
TRADING_DAYS_PER_20D = 20
CALENDAR_DAYS_PER_20D = 28  # ~4 weeks

GOVERNANCE = {
    "model_change": False,
    "ranker_change": False,
    "selector_change": False,
    "sizing_change": False,
    "production_promotion": False,
    "classification": "EES_SHADOW_OBSERVATION_ONLY",
}


def _business_days_since(start: dt_date, end: dt_date) -> int:
    """Count weekdays between start (inclusive) and end (inclusive)."""
    count = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count


def _gate_clear_date(start: dt_date, trading_days_needed: int) -> dt_date:
    """Estimate calendar date when N more trading-day windows will complete."""
    calendar_buffer = int(trading_days_needed * 1.4) + 10
    return start + timedelta(days=calendar_buffer)


def _load_monitor() -> dict:
    if not MONITOR_PATH.exists():
        return {}
    with open(MONITOR_PATH) as f:
        return json.load(f)


def _load_today_snapshot(as_of_date: str) -> list[dict]:
    """Load current snapshot rankings — for shadow veto signal check."""
    snap_path = SNAPSHOTS_DIR / as_of_date / "rankings.csv"
    if not snap_path.exists():
        snaps = sorted(d for d in SNAPSHOTS_DIR.iterdir() if d.is_dir() and (d / "rankings.csv").exists())
        if not snaps:
            return []
        snap_path = snaps[-1] / "rankings.csv"
        logger.info("No %s snapshot; using %s", as_of_date, snap_path.parent.name)

    import csv

    with open(snap_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _shadow_veto_fires(rows: list[dict]) -> list[dict]:
    """Identify tickers where raw_veto_core (ees_v3_score) would veto selection.

    Veto fires when ees_v3_score < -0.5 AND ticker is in top-30.
    Shadow mode: report only, never acted on.
    """
    fires = []
    for row in rows:
        try:
            rank = int(row.get("actionable_rank") or 999)
            score = float(row.get("ees_v3_score") or "nan")
        except (ValueError, TypeError):
            continue
        if rank <= 30 and score < -0.5:
            fires.append(
                {
                    "ticker": row.get("ticker", "?"),
                    "actionable_rank": rank,
                    "ees_v3_score": round(score, 4),
                    "shadow_veto": True,
                }
            )
    return sorted(fires, key=lambda x: x["ees_v3_score"])


def build_ees_shadow_card(as_of_date: str) -> dict:
    today = dt_date.fromisoformat(as_of_date)

    # Gate progress
    days_since_approval = (today - DIAGNOSTIC_WIRING_APPROVED).days
    trading_days_since = _business_days_since(DIAGNOSTIC_WIRING_APPROVED, today)
    # 20d windows that have STARTED: each trading day since approval starts one
    # A window COMPLETES after TRADING_DAYS_PER_20D more trading days
    windows_started = max(0, trading_days_since - 1)
    windows_completed = max(0, trading_days_since - TRADING_DAYS_PER_20D)
    gate_met = windows_completed >= GATE_20D_REQUIRED
    gate_clear_est = _gate_clear_date(DIAGNOSTIC_WIRING_APPROVED, GATE_20D_REQUIRED + TRADING_DAYS_PER_20D)

    # IC stats from historical completed observations
    monitor = _load_monitor()
    date_detail = monitor.get("date_detail", [])
    scored = [d for d in date_detail if d.get("status") == "scored"]
    ic_values = [d["ees_v3_score_ic"] for d in scored if "ees_v3_score_ic" in d]
    ws4 = monitor.get("ws4_progress", {}).get("ees_v3_score", {})

    ic_mean = round(statistics.mean(ic_values), 4) if ic_values else None
    ic_latest = round(ic_values[-1], 4) if ic_values else None
    ic_last3 = round(statistics.mean(ic_values[-3:]), 4) if len(ic_values) >= 3 else None
    n_positive = sum(1 for v in ic_values if v > 0)
    hit_rate = round(n_positive / len(ic_values), 3) if ic_values else None

    # Today's shadow veto check
    rows = _load_today_snapshot(as_of_date)
    veto_fires = _shadow_veto_fires(rows)

    return {
        "schema": "ees_shadow_card.v1",
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gate_progress": {
            "diagnostic_wiring_approved": str(DIAGNOSTIC_WIRING_APPROVED),
            "days_since_approval": days_since_approval,
            "trading_days_since_approval": trading_days_since,
            "gate_20d_required": GATE_20D_REQUIRED,
            "windows_started": windows_started,
            "windows_completed": windows_completed,
            "gate_20d_met": gate_met,
            "estimated_gate_clear_date": str(gate_clear_est),
        },
        "ic_stats": {
            "n_completed_observations": len(ic_values),
            "mean_ic": ic_mean,
            "ic_latest_date": scored[-1]["date"] if scored else None,
            "ic_latest": ic_latest,
            "ic_last3_mean": ic_last3,
            "hit_rate": hit_rate,
            "ws4_t_adj": ws4.get("t_adj"),
            "ws4_cleared": ws4.get("cleared", False),
            "monitor_generated": monitor.get("generated"),
        },
        "shadow_veto": {
            "n_fires": len(veto_fires),
            "fires": veto_fires,
            "note": "Shadow mode — veto not applied, observation only",
        },
        "governance": GOVERNANCE,
    }


def _build_markdown(card: dict) -> str:
    g = card["gate_progress"]
    ic = card["ic_stats"]
    sv = card["shadow_veto"]

    gate_bar = f"{g['windows_completed']}/{g['gate_20d_required']}"
    gate_status = "GATE MET" if g["gate_20d_met"] else f"UNMET (est. clear {g['estimated_gate_clear_date']})"

    lines = [
        f"# EES v3 Shadow Card — {card['as_of_date']}",
        "",
        f"Generated: {card['generated_at']}",
        f"Classification: {card['governance']['classification']}",
        "",
        "## Gate Progress",
        "",
        "| Item | Value |",
        "|------|-------|",
        f"| Approved | {g['diagnostic_wiring_approved']} |",
        f"| Days since approval | {g['days_since_approval']} |",
        f"| Trading days | {g['trading_days_since_approval']} |",
        f"| 20d windows started | {g['windows_started']} |",
        f"| 20d windows completed | {g['windows_completed']} |",
        f"| Gate (need {g['gate_20d_required']}) | **{gate_bar} — {gate_status}** |",
        "",
        "## IC Stats (raw_veto_core = ees_v3_score)",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Completed observations | {ic['n_completed_observations']} |",
        f"| Mean IC | {ic['mean_ic'] if ic['mean_ic'] is not None else '—'} |",
        f"| Latest IC ({ic['ic_latest_date'] or '?'}) | {ic['ic_latest'] if ic['ic_latest'] is not None else '—'} |",
        f"| Last-3 mean IC | {ic['ic_last3_mean'] if ic['ic_last3_mean'] is not None else '—'} |",
        f"| Hit rate (IC > 0) | {ic['hit_rate'] if ic['hit_rate'] is not None else '—'} |",
        f"| WS4 t_adj | {ic['ws4_t_adj'] if ic['ws4_t_adj'] is not None else '—'} |",
        f"| WS4 cleared | {'YES' if ic['ws4_cleared'] else 'NO'} |",
        "",
        "## Shadow Veto Fires Today",
        "",
    ]

    if sv["fires"]:
        lines += [
            "| Ticker | Rank | EES Score | Shadow Veto |",
            "|--------|------|-----------|-------------|",
        ]
        for fire in sv["fires"]:
            lines.append(f"| {fire['ticker']} | {fire['actionable_rank']} | {fire['ees_v3_score']} | WOULD VETO |")
    else:
        lines.append("No shadow veto fires today (no top-30 names with ees_v3_score < -0.5).")

    lines += [
        "",
        f"*{sv['note']}*",
        "",
        "## Governance",
        "",
        "- model_change: False",
        "- ranker_change: False",
        "- selector_change: False",
        "- sizing_change: False",
        "- production_promotion: False",
    ]

    return "\n".join(lines) + "\n"


def run_ees_shadow_card(as_of_date: str) -> dict:
    """Programmatic entry point for pipeline wiring. Never raises."""
    try:
        card = build_ees_shadow_card(as_of_date)
        md = _build_markdown(card)

        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        json_path = ARTIFACT_DIR / f"{as_of_date}_ees_shadow_card.json"
        md_path = ARTIFACT_DIR / f"{as_of_date}_ees_shadow_card.md"

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(card, f, indent=2, default=str)
            f.write("\n")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md)

        g = card["gate_progress"]
        return {
            "gate_20d_met": g["gate_20d_met"],
            "windows_completed": g["windows_completed"],
            "gate_20d_required": g["gate_20d_required"],
            "n_veto_fires": card["shadow_veto"]["n_fires"],
            "json_path": str(json_path),
            "md_path": str(md_path),
        }
    except Exception as exc:
        logger.warning("build_ees_shadow_card failed: %s", exc)
        return {"error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build EES v3 daily shadow card")
    parser.add_argument("--as-of-date", default=str(dt_date.today()), help="YYYY-MM-DD (default: today)")
    parser.add_argument("--dry-run", action="store_true", help="Print but do not write")
    args = parser.parse_args()

    card = build_ees_shadow_card(args.as_of_date)
    md = _build_markdown(card)

    if args.dry_run:
        print(md)
        return 0

    result = run_ees_shadow_card(args.as_of_date)
    if "error" in result:
        logger.error("Failed: %s", result["error"])
        return 1

    logger.info("Wrote %s", result["json_path"])
    logger.info("Wrote %s", result["md_path"])
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())

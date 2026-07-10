#!/usr/bin/env python3
"""forward_validation_liveness_monitor.py — small liveness control for SM-20260629-001.

Read-only monitor. Surfaces the ways the forward-validation feed can silently
stop producing genuine live evidence, so a broken evaluator is never mistaken for
weak investment evidence. NOT a dashboard: it emits a short list of alerts, writes
a status JSON, and exits non-zero when any alert fires (for a cron wrapper).

Alerts:
  1. stale_live_capture       — snapshots produced but no eligible live capture
                                for the last two completed snapshot days
  2. candidate_hash_mismatch  — latest capture's model != frozen candidate
  3. xbi_freshness            — XBI missing/stale in price_history.csv
  4. rankings_mismatch        — latest capture's Top-30 != its snapshot rankings
  5. duplicate_capture        — >1 capture row for a date
  6. hardfail_skipped_capture — a completed snapshot hard-failed and has no capture

The check_* functions are pure (data in, alerts out) so they are unit-testable;
main() does the IO.

Usage:
    python3 tools/forward_validation_liveness_monitor.py
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date as ddate
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = REPO_ROOT / "artifacts" / "forward_validation"
CAPTURES_LEDGER = ARTIFACTS / "captures.jsonl"
CANDIDATE_FILE = ARTIFACTS / "CANDIDATE.json"
SNAPSHOTS_ROOT = REPO_ROOT / "data" / "snapshots"
PRICE_HISTORY = REPO_ROOT / "production_data" / "price_history.csv"
STATUS_PATH = ARTIFACTS / "LIVENESS_STATUS.json"

sys.path.insert(0, str(REPO_ROOT))
from tools.run_forward_validation import capture_is_live_and_clean  # noqa: E402

# How many completed snapshot days without a live capture / without XBI before alerting.
STALE_DAYS = 2


def _alert(kind: str, severity: str, detail: str) -> dict:
    return {"alert": kind, "severity": severity, "detail": detail}


# --- pure checks -----------------------------------------------------------
def check_stale_live_capture(completed_dates: list[str], live_clean_dates: set[str]) -> list[dict]:
    """Production produced snapshots but no eligible live capture for the last
    STALE_DAYS completed snapshot days."""
    recent = completed_dates[-STALE_DAYS:]
    if len(recent) < STALE_DAYS:
        return []  # not enough completed history to judge
    if any(d in live_clean_dates for d in recent):
        return []
    return [
        _alert(
            "stale_live_capture",
            "CRITICAL",
            f"snapshots exist for {recent} but none has an eligible live forward-validation capture",
        )
    ]


def check_candidate_hash_mismatch(latest_capture: dict | None, candidate: dict | None) -> list[dict]:
    if not latest_capture or not candidate:
        return []
    cand_hash = candidate.get("model_hash")
    cap_hash = latest_capture.get("model_hash")
    if cand_hash and cap_hash and cand_hash != cap_hash:
        return [
            _alert(
                "candidate_hash_mismatch",
                "HIGH",
                f"latest capture {latest_capture.get('date')} model={cap_hash} != candidate {cand_hash}",
            )
        ]
    return []


def check_xbi_freshness(xbi_last_date: str | None, completed_dates: list[str]) -> list[dict]:
    if xbi_last_date is None:
        return [_alert("xbi_freshness", "HIGH", "XBI not found in price_history.csv")]
    behind = [d for d in completed_dates if d > xbi_last_date]
    if len(behind) >= STALE_DAYS:
        return [
            _alert(
                "xbi_freshness",
                "HIGH",
                f"XBI last={xbi_last_date} is {len(behind)} completed snapshot days behind (>= {STALE_DAYS})",
            )
        ]
    return []


def check_rankings_mismatch(latest_capture: dict | None, snapshot_top30: list[str] | None) -> list[dict]:
    if not latest_capture or snapshot_top30 is None:
        return []
    cap_top = {t.get("ticker") if isinstance(t, dict) else t for t in latest_capture.get("top30", [])}
    snap_top = set(snapshot_top30)
    if cap_top and snap_top and cap_top != snap_top:
        missing = sorted(snap_top - cap_top)[:5]
        extra = sorted(cap_top - snap_top)[:5]
        return [
            _alert(
                "rankings_mismatch",
                "HIGH",
                f"capture {latest_capture.get('date')} Top-30 != snapshot rankings "
                f"(in snapshot not capture: {missing}; in capture not snapshot: {extra})",
            )
        ]
    return []


def check_duplicate_captures(captures: list[dict]) -> list[dict]:
    seen: dict[str, int] = {}
    for c in captures:
        d = c.get("date")
        if d:
            seen[d] = seen.get(d, 0) + 1
    dups = sorted(d for d, n in seen.items() if n > 1)
    if dups:
        return [_alert("duplicate_capture", "HIGH", f"duplicate capture rows for dates: {dups}")]
    return []


def check_hardfail_skipped_capture(
    completed_dates: list[str], snapshot_status: dict[str, str], captured_dates: set[str]
) -> list[dict]:
    alerts = []
    for d in completed_dates[-5:]:
        if snapshot_status.get(d) == "FAIL" and d not in captured_dates:
            alerts.append(
                _alert(
                    "hardfail_skipped_capture",
                    "MEDIUM",
                    f"production hard-failed on {d} (overall_status=FAIL) so the capture was skipped",
                )
            )
    return alerts


def evaluate(
    completed_dates: list[str],
    captures: list[dict],
    candidate: dict | None,
    xbi_last_date: str | None,
    snapshot_top30: list[str] | None,
    snapshot_status: dict[str, str],
) -> list[dict]:
    live_clean_dates = {c.get("date") for c in captures if capture_is_live_and_clean(c)}
    captured_dates = {c.get("date") for c in captures}
    latest_capture = max(captures, key=lambda c: c.get("date", "")) if captures else None
    alerts: list[dict] = []
    alerts += check_stale_live_capture(completed_dates, live_clean_dates)
    alerts += check_candidate_hash_mismatch(latest_capture, candidate)
    alerts += check_xbi_freshness(xbi_last_date, completed_dates)
    alerts += check_rankings_mismatch(latest_capture, snapshot_top30)
    alerts += check_duplicate_captures(captures)
    alerts += check_hardfail_skipped_capture(completed_dates, snapshot_status, captured_dates)
    return alerts


# --- IO --------------------------------------------------------------------
def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def _completed_snapshot_dates(today: ddate) -> list[str]:
    if not SNAPSHOTS_ROOT.exists():
        return []
    dates = []
    for p in SNAPSHOTS_ROOT.iterdir():
        name = p.name
        if len(name) == 10 and name[4] == "-" and (p / "rankings.csv").exists():
            if name < today.isoformat():  # exclude today (possibly incomplete)
                dates.append(name)
    return sorted(dates)


def _snapshot_status(dates: list[str]) -> dict[str, str]:
    status = {}
    for d in dates[-5:]:
        mf = SNAPSHOTS_ROOT / d / "run_manifest.json"
        if mf.exists():
            try:
                status[d] = json.loads(mf.read_text()).get("overall_status", "")
            except json.JSONDecodeError:
                pass
    return status


def _snapshot_top30(date: str | None) -> list[str] | None:
    if not date:
        return None
    rk = SNAPSHOTS_ROOT / date / "rankings.csv"
    if not rk.exists():
        return None
    ranked = []
    with open(rk, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                rank = int(float(r.get("actionable_rank", 9999) or 9999))
            except (ValueError, TypeError):
                continue
            ranked.append((rank, r["ticker"]))
    ranked.sort()
    return [t for _, t in ranked[:30]]


def _xbi_last_date() -> str | None:
    if not PRICE_HISTORY.exists():
        return None
    last = None
    with open(PRICE_HISTORY, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("ticker") == "XBI":
                d = (row.get("date") or "")[:10]
                if d and (last is None or d > last):
                    last = d
    return last


def main() -> int:
    today = ddate.today()
    completed = _completed_snapshot_dates(today)
    captures = _load_jsonl(CAPTURES_LEDGER)
    candidate = json.loads(CANDIDATE_FILE.read_text()) if CANDIDATE_FILE.exists() else None
    latest_capture = max(captures, key=lambda c: c.get("date", ""), default=None) if captures else None
    latest_cap_date = latest_capture.get("date") if latest_capture else None

    alerts = evaluate(
        completed_dates=completed,
        captures=captures,
        candidate=candidate,
        xbi_last_date=_xbi_last_date(),
        snapshot_top30=_snapshot_top30(latest_cap_date),
        snapshot_status=_snapshot_status(completed),
    )

    status = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "mandate_id": "SM-20260629-001",
        "n_completed_snapshot_days": len(completed),
        "latest_capture_date": latest_cap_date,
        "n_alerts": len(alerts),
        "alerts": alerts,
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2) + "\n")

    if alerts:
        print(f"LIVENESS: {len(alerts)} alert(s) for SM-20260629-001")
        for a in alerts:
            print(f"  [{a['severity']}] {a['alert']}: {a['detail']}")
    else:
        print("LIVENESS: OK — no alerts")
    print(f"Status: {STATUS_PATH}", file=sys.stderr)
    return 1 if alerts else 0


if __name__ == "__main__":
    raise SystemExit(main())

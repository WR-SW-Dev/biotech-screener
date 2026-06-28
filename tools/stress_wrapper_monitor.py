#!/usr/bin/env python3
"""
stress_wrapper_monitor.py — DEM conditional stress-wrapper shadow monitor.

VALIDATION_INFRASTRUCTURE / STRESS_WRAPPER_SHADOW / NO_MODEL_CHANGE /
NO_RANKER_CHANGE / NO_SELECTOR_CHANGE / NO_SIZING_CHANGE / NO_TRADING_CHANGE.

Model lesson (operator, 2026-06-28): the edge is quality/survivability
selection (convex upside), and the avoidable failure mode is repeat-offender /
event-premium exposure — NOT a broken ranker. This monitor (shadow only) builds:

  1. A repeat-offender table  — names that keep dragging while still in Top-30.
  2. A conditional_risk_wrapper_active flag — only "on" in the kind of
     environment where failures historically showed up.

It does NOT change the production basket, ranker, or selector, and does NOT
trade. Whether substituting deteriorating Top-30 names with rank31_60 bench
names actually helps must be validated forward before any promotion.

Usage:
    python3 tools/stress_wrapper_monitor.py
    python3 tools/stress_wrapper_monitor.py --min-neg-windows 2 --since 2026-06-01
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date as ddate
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FV = REPO_ROOT / "artifacts" / "forward_validation"
CAPTURES = FV / "captures.jsonl"
FILLS = FV / "fills.jsonl"
SNAPSHOTS = REPO_ROOT / "data" / "snapshots"
OUT_DIR = REPO_ROOT / "artifacts" / "validation" / "stress_wrapper"
OUT_MD = OUT_DIR / "STRESS_WRAPPER_CARD.md"
OUT_JSON = OUT_DIR / "stress_wrapper_card.json"

# conditional_risk_wrapper_active triggers (shadow thresholds, pre-registered)
ROLLING_XS_TRIGGER = -0.05  # rolling 4-window Top-30 excess <= -5pp
REPEAT_OFFENDER_TRIGGER = 2  # >= 2 current repeat offenders
EES_FALSE_TRIGGER = 5  # >= 5 Top-30 names failing the EES v3 gate
DEFAULT_MIN_NEG_WINDOWS = 2  # a "repeat offender" drags in >= this many windows


def week_key(d: str) -> str:
    y, w, _ = ddate.fromisoformat(d).isocalendar()
    return f"{y}-W{w:02d}"


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def weekly_windows(captures: list[dict], fills: dict[str, dict], since: str | None) -> list[dict]:
    """Earliest capture per ISO week with a completed 5d fill (with per-name data)."""
    by_week: dict[str, dict] = {}
    for cap in sorted(captures, key=lambda c: c["date"]):
        d = cap["date"]
        if since and d < since:
            continue
        f = fills.get(d, {})
        if f.get("xs_5d") is None:
            continue
        wk = week_key(d)
        if wk not in by_week:
            by_week[wk] = {"week": wk, "date": d, "capture": cap, "fill": f}
    return list(by_week.values())


def build_repeat_offender_table(windows: list[dict], min_neg: int) -> list[dict]:
    """Per-ticker drag history across weekly windows. Pure (testable)."""
    agg: dict[str, dict] = {}
    latest_top30: set[str] = set()
    latest_rank: dict[str, int] = {}
    for w in windows:
        top30 = {t.get("ticker"): t.get("rank") for t in w["capture"].get("top30", [])}
        latest_top30 = set(top30)  # last window wins (windows are time-ordered)
        latest_rank = top30
        per_name = w["fill"].get("per_name", {}) or {}
        for tkr in top30:
            a = agg.setdefault(tkr, {"ticker": tkr, "weeks_in_top30": 0, "neg_windows": 0, "cum_xs": 0.0})
            a["weeks_in_top30"] += 1
            xs = (per_name.get(tkr, {}).get("5d", {}) or {}).get("xs")
            if xs is not None:
                a["cum_xs"] += xs
                if xs < 0:
                    a["neg_windows"] += 1
    rows = []
    for tkr, a in agg.items():
        a["cum_xs"] = round(a["cum_xs"], 6)
        a["current_rank"] = latest_rank.get(tkr)
        a["currently_top30"] = tkr in latest_top30
        a["is_repeat_offender"] = a["currently_top30"] and a["neg_windows"] >= min_neg
        rows.append(a)
    rows.sort(key=lambda r: (not r["is_repeat_offender"], r["cum_xs"]))  # offenders first, worst cum_xs first
    return rows


def evaluate_wrapper_active(rolling_4w_xs, repeat_offender_count, ees_false_count) -> dict:
    """Pure: which stress triggers fire, and is the wrapper active. Shadow only."""
    triggers = {
        "rolling_4w_xs_le_-5pp": (rolling_4w_xs is not None and rolling_4w_xs <= ROLLING_XS_TRIGGER),
        "repeat_offenders_ge_2": (repeat_offender_count >= REPEAT_OFFENDER_TRIGGER),
        "ees_false_top30_ge_5": (ees_false_count is not None and ees_false_count >= EES_FALSE_TRIGGER),
    }
    return {
        "active": any(triggers.values()),
        "triggers": triggers,
        "rolling_4w_xs": rolling_4w_xs,
        "repeat_offender_count": repeat_offender_count,
        "ees_false_top30_count": ees_false_count,
    }


def latest_snapshot_ees(top30_tickers: list[str], snap_date: str):
    """Return (ees_false_count, {ticker: ees_gate}) from the snapshot, or (None, {}) if unavailable."""
    path = SNAPSHOTS / snap_date / "rankings.csv"
    if not path.exists():
        return None, {}
    gate = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t = (r.get("ticker") or "").strip().upper()
            if t in top30_tickers:
                gate[t] = (r.get("ees_v3_gate") or "").strip()
    if not gate:
        return None, {}
    false_count = sum(1 for v in gate.values() if v.lower() in ("false", "0", "veto", "fail"))
    return false_count, gate


def build_card(captures, fills, since, min_neg) -> dict:
    windows = weekly_windows(captures, fills, since)
    table = build_repeat_offender_table(windows, min_neg)
    repeat_offenders = [r for r in table if r["is_repeat_offender"]]

    # rolling 4-window Top-30 excess
    last4 = windows[-4:]
    xs_vals = [w["fill"].get("xs_5d") for w in last4 if w["fill"].get("xs_5d") is not None]
    rolling_4w_xs = round(sum(xs_vals), 6) if xs_vals else None

    # EES-false count from the latest window's snapshot
    ees_false, ees_gate = (None, {})
    repl_candidates = []
    if windows:
        latest = windows[-1]
        top30 = [t.get("ticker") for t in latest["capture"].get("top30", [])]
        ees_false, ees_gate = latest_snapshot_ees(top30, latest["date"])
        # 31-60 replacement bench from latest capture
        band = (latest["capture"].get("cohorts") or {}).get("rank31_60") or [
            e.get("ticker") for e in (latest["capture"].get("rank31_60") or []) if isinstance(e, dict)
        ]
        repl_candidates = [t for t in band if t not in set(top30)][:10]

    wrapper = evaluate_wrapper_active(rolling_4w_xs, len(repeat_offenders), ees_false)

    # attach EES status + a replacement suggestion to each offender
    for r in repeat_offenders:
        r["ees_gate"] = ees_gate.get(r["ticker"])
        r["replacement_candidate"] = repl_candidates[0] if repl_candidates else None

    return {
        "schema": "stress_wrapper_card.v1",
        "generated": datetime.now(timezone.utc).isoformat(),
        "classification": "VALIDATION_INFRASTRUCTURE / STRESS_WRAPPER_SHADOW / NO_MODEL_CHANGE / NO_SELECTOR_CHANGE",
        "windows_analyzed": len(windows),
        "min_neg_windows": min_neg,
        "conditional_risk_wrapper": wrapper,
        "repeat_offenders": repeat_offenders,
        "repeat_offender_count": len(repeat_offenders),
        "replacement_bench_31_60": repl_candidates,
        "full_drag_table": table,
        "pending": {
            "shadow_substitution_net_delta": "PENDING — needs >=1 wrapper-active window to simulate 31-60 replacement net return",
            "ees_guarded_basket_return": "PENDING — accrues as per-name forward windows mature",
            "build_window_less_binary_exposure": "PENDING — catalyst-bucket exposure wiring not yet added",
        },
        "governance": {
            "model_change": False,
            "ranker_change": False,
            "selector_change": False,
            "sizing_change": False,
            "trading_change": False,
            "cron_change": False,
        },
        "note": "Shadow only. Substitution is NOT applied to the production basket and is NOT traded. "
        "Promotion requires forward proof that guards improve failure windows without killing convexity.",
    }


def render_md(c: dict) -> str:
    w = c["conditional_risk_wrapper"]

    def pct(v):
        return f"{v:+.2%}" if isinstance(v, (int, float)) else "—"

    L = [
        "# DEM Stress-Wrapper Shadow Card",
        "",
        f"**Generated:** {c['generated'][:16]}Z  ",
        f"**Windows analyzed:** {c['windows_analyzed']}  ",
        f"**Classification:** `{c['classification']}`",
        "",
        f"## conditional_risk_wrapper_active = `{w['active']}`",
        "",
        "| Trigger | Value | Fired |",
        "|---|---:|:--:|",
        f"| rolling 4w Top-30 excess ≤ −5pp | {pct(w['rolling_4w_xs'])} | {'🔴' if w['triggers']['rolling_4w_xs_le_-5pp'] else '—'} |",
        f"| repeat offenders ≥ 2 | {w['repeat_offender_count']} | {'🔴' if w['triggers']['repeat_offenders_ge_2'] else '—'} |",
        f"| EES-false Top-30 ≥ 5 | {w['ees_false_top30_count'] if w['ees_false_top30_count'] is not None else '—'} | {'🔴' if w['triggers']['ees_false_top30_ge_5'] else '—'} |",
        "",
        f"## Repeat offenders ({c['repeat_offender_count']})",
        "",
        "| Ticker | Rank | Weeks in T30 | Neg windows | Cum XS | EES | Replace← |",
        "|---|---:|---:|---:|---:|:--:|---|",
    ]
    for r in c["repeat_offenders"]:
        L.append(
            f"| {r['ticker']} | {r.get('current_rank', '—')} | {r['weeks_in_top30']} | "
            f"{r['neg_windows']} | {pct(r['cum_xs'])} | {r.get('ees_gate') or '—'} | {r.get('replacement_candidate') or '—'} |"
        )
    if not c["repeat_offenders"]:
        L.append("| _none yet_ | | | | | | |")
    L += [
        "",
        f"**31–60 replacement bench:** {', '.join(c['replacement_bench_31_60']) or '—'}",
        "",
        "## Pending (forward-data gated)",
        "",
    ]
    for k, v in c["pending"].items():
        L.append(f"- **{k}**: {v}")
    L += ["", f"_{c['note']}_"]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="DEM stress-wrapper shadow monitor")
    ap.add_argument("--since", help="Only windows from YYYY-MM-DD onward")
    ap.add_argument("--min-neg-windows", type=int, default=DEFAULT_MIN_NEG_WINDOWS)
    args = ap.parse_args()

    captures = load_jsonl(CAPTURES)
    fills = {f["capture_date"]: f for f in load_jsonl(FILLS)}
    card = build_card(captures, fills, args.since, args.min_neg_windows)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(card, indent=2) + "\n")
    md = render_md(card)
    OUT_MD.write_text(md)
    print(md)
    print(f"Wrote {OUT_MD}\nWrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

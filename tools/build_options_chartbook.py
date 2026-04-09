#!/usr/bin/env python3
"""Daily options chartbook — watchlist-scoped HTML surface report.

Assembles structured options data from the daily packet into an 8-page
HTML chartbook with inline SVG charts.  Watchlist-scoped: only charts
names that pass options eligibility gates.

Inputs (required):
    data/snapshots/{date}/rankings.csv
    data/snapshots/{date}/options_diagnostics_summary.json

Inputs (optional, graceful degradation):
    artifacts/options_watch/{date}_watch.json
    data/snapshots/{date}/coverage_quality.json
    data/snapshots/{date}/review_queue.csv
    artifacts/live_shadow/trade_plan/{date}/trade_plan.csv
    artifacts/live_shadow/positions/{date}.json
    data/snapshots/{date}/surface_delta.json

Output:
    artifacts/options_chartbook/{date}_chartbook.html
    artifacts/options_chartbook/{date}_chartbook.json

Read-only — does not affect rankings, scoring, or execution.

Usage:
    python tools/build_options_chartbook.py
    python tools/build_options_chartbook.py --as-of-date 2026-03-26
    python tools/build_options_chartbook.py --open  # open in browser after build
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
import webbrowser
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("options_chartbook")

SCHEMA_VERSION = "options_chartbook.v1"
SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots"
OUT_DIR = REPO_ROOT / "artifacts" / "options_chartbook"

# Max names per chart to keep visuals readable
CHART_MAX_BARS = 20
WATCHLIST_MAX = 50


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _sf(val: Any, default: float = float("nan")) -> float:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _si(val: Any, default: int = 0) -> int:
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _load_csv(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _find_latest_snapshot(snap_dir: Path) -> Optional[str]:
    candidates = sorted(
        d.name for d in snap_dir.iterdir() if d.is_dir() and not d.name.startswith("_") and d.name != "state"
    )
    return candidates[-1] if candidates else None


# ---------------------------------------------------------------------------
# Watchlist assembly
# ---------------------------------------------------------------------------


def build_watchlist(
    rankings: List[Dict[str, Any]],
    options_watch: Optional[Dict[str, Any]],
    trade_plan_tickers: Set[str],
    shadow_tickers: Set[str],
    review_queue_tickers: Set[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build the chartbook watchlist from rankings + optional options_watch.

    Returns (eligible_rows, suppressed_rows).
    Eligible rows are enriched with context flags.
    """
    # If options_watch exists, use its rows as the primary driver
    if options_watch and options_watch.get("rows"):
        watch_tickers = {r["ticker"] for r in options_watch["rows"]}
    else:
        watch_tickers = None  # fall back to rankings-based selection

    eligible: List[Dict[str, Any]] = []
    suppressed: List[Dict[str, Any]] = []

    for row in rankings:
        ticker = (row.get("ticker") or "").strip().upper()
        if not ticker:
            continue

        has_data = row.get("opt_has_data") == "1"
        use_for_judgment = row.get("opt_use_for_judgment") == "YES"
        liquidity_ok = row.get("opt_liquidity_ok") == "1"

        # Determine if this name is in watchlist scope
        if watch_tickers is not None:
            in_scope = ticker in watch_tickers
        else:
            # Fallback: hard-catalyst queue + trade plan + shadow + near-term A-tier
            is_hard = row.get("is_hard_catalyst") == "1"
            cat_days = _sf(row.get("catalyst_days"))
            tier = (row.get("tier_dev") or row.get("tier_any") or "").strip()
            rank = _si(row.get("actionable_rank"), 999)
            in_trade = ticker in trade_plan_tickers
            in_shadow = ticker in shadow_tickers
            in_queue = ticker in review_queue_tickers

            in_scope = (
                is_hard
                or in_trade
                or in_shadow
                or in_queue
                or (tier == "A" and not math.isnan(cat_days) and cat_days <= 30)
                or rank <= 30
            )

        if not in_scope:
            continue

        if not has_data:
            suppressed.append(
                {
                    "ticker": ticker,
                    "reason": "no_options_data",
                    "opt_has_data": 0,
                    "opt_liquidity_ok": 0,
                    "opt_use_for_judgment": "NO",
                }
            )
            continue

        if not use_for_judgment:
            reason_parts = []
            if not liquidity_ok:
                reason_parts.append("illiquid")
            regime = row.get("opt_iv_regime", "")
            if regime == "EXTREME":
                reason_parts.append("EXTREME_IV")
            suppressed.append(
                {
                    "ticker": ticker,
                    "reason": ", ".join(reason_parts) if reason_parts else "judgment_gate_fail",
                    "opt_has_data": 1,
                    "opt_liquidity_ok": 1 if liquidity_ok else 0,
                    "opt_use_for_judgment": "NO",
                    "opt_iv_regime": regime,
                }
            )
            continue

        # Build enriched row
        enriched = {
            "ticker": ticker,
            "tier": (row.get("tier_dev") or row.get("tier_any") or "").strip(),
            "actionable_rank": _si(row.get("actionable_rank"), 999),
            "catalyst_days": _sf(row.get("catalyst_days")),
            "catalyst_bucket": (row.get("catalyst_bucket") or "").strip(),
            "catalyst_family": (row.get("catalyst_family") or "").strip(),
            "is_hard_catalyst": row.get("is_hard_catalyst") == "1",
            "opt_atm_iv": _sf(row.get("opt_atm_iv")),
            "opt_front_iv": _sf(row.get("opt_front_iv")),
            "opt_back_iv": _sf(row.get("opt_back_iv")),
            "opt_term_slope": _sf(row.get("opt_term_slope")),
            "opt_put_call_skew": _sf(row.get("opt_put_call_skew")),
            "opt_rr_25d": _sf(row.get("opt_rr_25d")),
            "opt_iv_regime": (row.get("opt_iv_regime") or "").strip(),
            "opt_event_premium": (row.get("opt_event_premium") or "").strip(),
            "implied_event_move": _sf(row.get("implied_event_move")),
            "actual_implied_move_pctile": _sf(row.get("actual_implied_move_pctile")),
            "atm_iv_change_5d": _sf(row.get("atm_iv_change_5d")),
            "in_trade_plan": ticker in trade_plan_tickers,
            "in_shadow": ticker in shadow_tickers,
            "in_review_queue": ticker in review_queue_tickers,
        }

        # Merge options_watch flags if available
        if options_watch:
            for wr in options_watch.get("rows", []):
                if wr.get("ticker") == ticker:
                    enriched["flags"] = wr.get("flags", [])
                    enriched["priority_score"] = wr.get("priority_score", 0)
                    enriched["why"] = wr.get("why", "")
                    break
            else:
                enriched["flags"] = []
                enriched["priority_score"] = 0
                enriched["why"] = ""
        else:
            enriched["flags"] = _derive_flags(enriched)
            enriched["priority_score"] = len(enriched["flags"])
            enriched["why"] = ""

        eligible.append(enriched)

    # Sort: priority desc, then hard catalyst, then rank asc
    eligible.sort(
        key=lambda r: (
            -r.get("priority_score", 0),
            -int(r.get("is_hard_catalyst", False)),
            r.get("actionable_rank", 999),
        )
    )

    return eligible[:WATCHLIST_MAX], suppressed


def _derive_flags(row: Dict[str, Any]) -> List[str]:
    """Derive basic flags when options_watch is not available.

    Uses fields available in rankings.csv (not surface signals enrichment).
    Row values may be floats (from enriched rows) or strings (raw CSV).
    """
    flags = []
    if row.get("opt_event_premium") == "YES":
        flags.append("EVENT_PREMIUM")
    slope = _sf(row.get("opt_term_slope"))
    if not math.isnan(slope) and slope < -0.20:
        flags.append("DEEP_BACKWARDATION")
    rr = _sf(row.get("opt_rr_25d"))
    if not math.isnan(rr) and abs(rr) >= 0.15:
        flags.append("EXTREME_SKEW")
    skew = _sf(row.get("opt_put_call_skew"))
    if not math.isnan(skew) and abs(skew) >= 0.20:
        flags.append("HIGH_SKEW")
    # Surface signal fields (only populated if enrichment ran)
    pctile = _sf(row.get("actual_implied_move_pctile"))
    if not math.isnan(pctile) and pctile >= 0.80:
        flags.append("SURFACE_MOVE_HIGH")
    iv_chg = _sf(row.get("atm_iv_change_5d"))
    if not math.isnan(iv_chg) and iv_chg >= 0.10:
        flags.append("IV_RAMP_HIGH")
    return flags


# ---------------------------------------------------------------------------
# SVG chart generators
# ---------------------------------------------------------------------------

_COLORS = {
    "alert": "#dc3545",
    "watch": "#fd7e14",
    "normal": "#0d6efd",
    "positive": "#198754",
    "negative": "#dc3545",
    "hard": "#6f42c1",
    "soft": "#adb5bd",
    "muted": "#6c757d",
    "bg": "#f8f9fa",
    "grid": "#dee2e6",
}


def _svg_hbar(
    data: List[Tuple[str, float]],
    title: str,
    *,
    width: int = 700,
    bar_height: int = 22,
    label_width: int = 80,
    color_fn=None,
    fmt: str = ".2f",
    zero_line: bool = True,
) -> str:
    """Render a horizontal bar chart as inline SVG."""
    if not data:
        return f'<p class="muted">No data for {escape(title)}</p>'

    n = len(data)
    margin_top = 30
    margin_bottom = 10
    chart_height = margin_top + n * (bar_height + 4) + margin_bottom
    chart_left = label_width + 10
    chart_width = width - chart_left - 20

    vals = [v for _, v in data]
    v_min = min(0, min(vals)) if vals else 0
    v_max = max(0, max(vals)) if vals else 1
    v_range = v_max - v_min or 1

    def x_pos(v: float) -> float:
        return chart_left + (v - v_min) / v_range * chart_width

    zero_x = x_pos(0)

    lines = [f'<svg width="{width}" height="{chart_height}" xmlns="http://www.w3.org/2000/svg">']
    lines.append(
        f'<text x="{width // 2}" y="18" text-anchor="middle" font-size="13" '
        f'font-weight="600" fill="#212529">{escape(title)}</text>'
    )

    # Grid line at zero
    if zero_line and v_min < 0:
        lines.append(
            f'<line x1="{zero_x:.1f}" y1="{margin_top}" '
            f'x2="{zero_x:.1f}" y2="{chart_height - margin_bottom}" '
            f'stroke="{_COLORS["grid"]}" stroke-width="1" stroke-dasharray="4,2"/>'
        )

    for i, (label, val) in enumerate(data):
        y = margin_top + i * (bar_height + 4)
        color = color_fn(label, val) if color_fn else (_COLORS["positive"] if val >= 0 else _COLORS["negative"])
        bx = min(x_pos(val), zero_x)
        bw = abs(x_pos(val) - zero_x)

        lines.append(
            f'<text x="{chart_left - 4}" y="{y + bar_height // 2 + 4}" '
            f'text-anchor="end" font-size="11" fill="#495057">{escape(label)}</text>'
        )
        lines.append(
            f'<rect x="{bx:.1f}" y="{y}" width="{max(bw, 1):.1f}" '
            f'height="{bar_height}" rx="2" fill="{color}" opacity="0.85"/>'
        )

        # Value label
        val_str = f"{val:{fmt}}"
        val_x = x_pos(val) + (4 if val >= 0 else -4)
        anchor = "start" if val >= 0 else "end"
        lines.append(
            f'<text x="{val_x:.1f}" y="{y + bar_height // 2 + 4}" '
            f'text-anchor="{anchor}" font-size="10" fill="#495057">{val_str}</text>'
        )

    lines.append("</svg>")
    return "\n".join(lines)


def _svg_scatter(
    data: List[Tuple[str, float, float, float, bool]],
    title: str,
    x_label: str,
    y_label: str,
    *,
    width: int = 700,
    height: int = 400,
) -> str:
    """Render a scatter plot as inline SVG.

    data: [(label, x, y, size, is_hard)]
    """
    if not data:
        return f'<p class="muted">No data for {escape(title)}</p>'

    margin = {"top": 35, "right": 20, "bottom": 40, "left": 55}
    cw = width - margin["left"] - margin["right"]
    ch = height - margin["top"] - margin["bottom"]

    xs = [x for _, x, _, _, _ in data if not math.isnan(x)]
    ys = [y for _, _, y, _, _ in data if not math.isnan(y)]
    if not xs or not ys:
        return f'<p class="muted">Insufficient data for {escape(title)}</p>'

    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_range = x_max - x_min or 1
    y_range = y_max - y_min or 1

    # Pad by 5%
    x_min -= x_range * 0.05
    x_max += x_range * 0.05
    y_min -= y_range * 0.05
    y_max += y_range * 0.05
    x_range = x_max - x_min
    y_range = y_max - y_min

    def px(v: float) -> float:
        return margin["left"] + (v - x_min) / x_range * cw

    def py(v: float) -> float:
        return margin["top"] + (1 - (v - y_min) / y_range) * ch

    lines = [f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">']
    lines.append(
        f'<text x="{width // 2}" y="18" text-anchor="middle" font-size="13" '
        f'font-weight="600" fill="#212529">{escape(title)}</text>'
    )

    # Axes
    lines.append(
        f'<line x1="{margin["left"]}" y1="{margin["top"]}" '
        f'x2="{margin["left"]}" y2="{height - margin["bottom"]}" stroke="{_COLORS["grid"]}"/>'
    )
    lines.append(
        f'<line x1="{margin["left"]}" y1="{height - margin["bottom"]}" '
        f'x2="{width - margin["right"]}" y2="{height - margin["bottom"]}" stroke="{_COLORS["grid"]}"/>'
    )

    # Axis labels
    lines.append(
        f'<text x="{width // 2}" y="{height - 5}" text-anchor="middle" '
        f'font-size="11" fill="{_COLORS["muted"]}">{escape(x_label)}</text>'
    )
    lines.append(
        f'<text x="12" y="{height // 2}" text-anchor="middle" '
        f'font-size="11" fill="{_COLORS["muted"]}" '
        f'transform="rotate(-90, 12, {height // 2})">{escape(y_label)}</text>'
    )

    # Points
    for label, x, y, size, is_hard in data:
        if math.isnan(x) or math.isnan(y):
            continue
        r = max(4, min(12, 4 + size * 2))
        color = _COLORS["hard"] if is_hard else _COLORS["normal"]
        cx, cy = px(x), py(y)
        lines.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" '
            f'fill="{color}" opacity="0.7" stroke="white" stroke-width="1"/>'
        )
        lines.append(
            f'<text x="{cx:.1f}" y="{cy - r - 2:.1f}" text-anchor="middle" '
            f'font-size="9" fill="#495057">{escape(label)}</text>'
        )

    lines.append("</svg>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML page builders
# ---------------------------------------------------------------------------


def _page_scoreboard(
    as_of_date: str,
    eligible: List[Dict],
    suppressed: List[Dict],
    diag_summary: Optional[Dict],
    coverage: Optional[Dict],
    surface_delta: Optional[Dict],
    ruleset_id: str,
) -> str:
    """Page 1: Cover / scoreboard."""
    n_flagged = sum(1 for r in eligible if r.get("flags"))
    n_hard = sum(1 for r in eligible if r.get("is_hard_catalyst"))
    n_trade = sum(1 for r in eligible if r.get("in_trade_plan"))
    n_shadow = sum(1 for r in eligible if r.get("in_shadow"))

    cov = coverage or {}
    comp_cov = cov.get("component_coverage", {})
    opt_fresh = cov.get("options_data_freshness", {})
    ds = diag_summary or {}
    ds_cov = ds.get("coverage", {})

    sd_alert = surface_delta.get("n_alert", 0) if surface_delta else 0
    sd_watch = surface_delta.get("n_watch", 0) if surface_delta else 0

    # Coverage banner
    cred_ok = ds_cov.get("has_credentials", False)
    fresh_ok = opt_fresh.get("all_fresh", False)
    coverage_pct = comp_cov.get("options_pct", ds_cov.get("coverage_pct", 0))
    banner_cls = ""
    banner_msg = ""
    if not cred_ok:
        banner_cls = "banner-fail"
        banner_msg = "WARNING: Tastytrade credentials missing — options data is stale or absent"
    elif not fresh_ok:
        banner_cls = "banner-warn"
        banner_msg = "WARNING: Options data freshness check failed — surfaces may be stale"
    elif coverage_pct < 50:
        banner_cls = "banner-warn"
        banner_msg = f"WARNING: Options coverage at {coverage_pct:.0f}% — below 50% threshold"

    html = []
    if banner_msg:
        html.append(f'<div class="banner {banner_cls}">{escape(banner_msg)}</div>')

    html.append('<div class="kpi-grid">')
    kpis = [
        ("Watchlist", str(len(eligible))),
        ("Flagged", str(n_flagged)),
        ("Suppressed", str(len(suppressed))),
        ("Hard Catalyst", str(n_hard)),
        ("In Trade Plan", str(n_trade)),
        ("In Shadow", str(n_shadow)),
    ]
    for label, val in kpis:
        html.append(f'<div class="kpi"><div class="kpi-val">{val}</div>' f'<div class="kpi-label">{label}</div></div>')
    html.append("</div>")

    # Status strip
    html.append('<table class="tbl"><tr>')
    html.append(f"<th>Coverage</th><td>{coverage_pct:.1f}%</td>")
    html.append(f'<th>Credentials</th><td>{"OK" if cred_ok else "MISSING"}</td>')
    html.append(f'<th>Freshness</th><td>{"OK" if fresh_ok else "STALE"}</td>')
    html.append(f"<th>Ruleset</th><td><code>{escape(ruleset_id)}</code></td>")
    if surface_delta:
        html.append(f"<th>Surface Delta</th><td>{sd_alert} alert / {sd_watch} watch</td>")
    html.append("</tr></table>")

    # Regime distribution
    regimes = ds.get("flag_distributions", {}).get("iv_regime", {})
    if regimes:
        html.append("<h3>IV Regime Distribution</h3>")
        html.append('<table class="tbl"><tr>')
        for regime, count in sorted(regimes.items()):
            html.append(f"<th>{regime}</th><td>{count}</td>")
        html.append("</tr></table>")

    return "\n".join(html)


def _page_flagged(eligible: List[Dict]) -> str:
    """Page 2: Flagged names table."""
    flagged = [r for r in eligible if r.get("flags")]
    if not flagged:
        return '<p class="muted">No flagged names in current watchlist.</p>'

    cols = [
        ("Ticker", "ticker"),
        ("Tier", "tier"),
        ("Rank", "actionable_rank"),
        ("Cat Days", "catalyst_days"),
        ("Hard", "is_hard_catalyst"),
        ("ATM IV", "opt_atm_iv"),
        ("Regime", "opt_iv_regime"),
        ("Flags", "flags"),
        ("Priority", "priority_score"),
        ("Trade", "in_trade_plan"),
        ("Shadow", "in_shadow"),
        ("Queue", "in_review_queue"),
    ]

    rows = []
    for r in flagged:
        row_html = []
        for label, key in cols:
            val = r.get(key)
            if key == "flags":
                val = ", ".join(val) if val else ""
                cell = f'<span class="flag-tag">{escape(val)}</span>'
            elif key == "is_hard_catalyst":
                cell = "HARD" if val else ""
            elif key in ("in_trade_plan", "in_shadow", "in_review_queue"):
                cell = "Y" if val else ""
            elif isinstance(val, float) and not math.isnan(val):
                cell = (
                    f"{val:.2f}"
                    if key.startswith("opt_")
                    else (f"{val:.0f}" if key in ("catalyst_days", "actionable_rank") else f"{val}")
                )
            else:
                cell = escape(str(val)) if val else ""
            row_html.append(f"<td>{cell}</td>")
        rows.append("<tr>" + "".join(row_html) + "</tr>")

    header = "<tr>" + "".join(f"<th>{c[0]}</th>" for c in cols) + "</tr>"
    return f'<table class="tbl">{header}{"".join(rows)}</table>'


def _page_backwardation(eligible: List[Dict]) -> str:
    """Page 3: Top backwardation."""
    rows = [
        (r["ticker"], r["opt_term_slope"]) for r in eligible if not math.isnan(r.get("opt_term_slope", float("nan")))
    ]
    rows.sort(key=lambda x: x[1])
    top = rows[:CHART_MAX_BARS]

    def color_fn(label, val):
        return _COLORS["negative"] if val < -0.10 else _COLORS["muted"]

    chart = _svg_hbar(top, "Term Structure Slope (most backwardated)", color_fn=color_fn, fmt=".3f")

    # Table of event premium names
    ep_names = [r for r in eligible if r.get("opt_event_premium") == "YES"]
    table = ""
    if ep_names:
        ep_names.sort(key=lambda r: r.get("opt_term_slope", 0))
        table = '<h3>Event Premium Names</h3><table class="tbl">'
        table += "<tr><th>Ticker</th><th>Term Slope</th><th>ATM IV</th><th>Cat Days</th></tr>"
        for r in ep_names[:15]:
            table += (
                f'<tr><td>{r["ticker"]}</td>'
                f'<td>{r["opt_term_slope"]:.3f}</td>'
                f'<td>{r["opt_atm_iv"]:.2f}</td>'
                f'<td>{r.get("catalyst_days", ""):.0f}</td></tr>'
            )
        table += "</table>"

    return chart + "\n" + table


def _page_iv_movers(eligible: List[Dict]) -> str:
    """Page 4: Top IV movers / IV level distribution.

    Uses atm_iv_change_5d if available (from surface signals enrichment),
    otherwise falls back to ATM IV level chart sorted by magnitude.
    """
    # Try 5d change first
    change_rows = [
        (r["ticker"], r["atm_iv_change_5d"])
        for r in eligible
        if not math.isnan(r.get("atm_iv_change_5d", float("nan")))
    ]

    if change_rows:
        pos = sorted([r for r in change_rows if r[1] > 0], key=lambda x: -x[1])[: CHART_MAX_BARS // 2]
        neg = sorted([r for r in change_rows if r[1] < 0], key=lambda x: x[1])[: CHART_MAX_BARS // 2]
        combined = pos + neg
        chart = _svg_hbar(combined, "ATM IV Change (5d)", fmt=".4f")

        table = '<table class="tbl">'
        table += "<tr><th>Ticker</th><th>IV Change 5d</th><th>ATM IV</th><th>Regime</th><th>Priority</th></tr>"
        for ticker, chg in combined:
            r = next((x for x in eligible if x["ticker"] == ticker), {})
            iv = r.get("opt_atm_iv", float("nan"))
            table += (
                f"<tr><td>{ticker}</td><td>{chg:+.4f}</td>"
                f'<td>{iv:.2f}</td><td>{r.get("opt_iv_regime", "")}</td>'
                f'<td>{r.get("priority_score", 0)}</td></tr>'
            )
        table += "</table>"
        return chart + "\n" + table

    # Fallback: ATM IV levels (always available for eligible names)
    iv_rows = [(r["ticker"], r["opt_atm_iv"]) for r in eligible if not math.isnan(r.get("opt_atm_iv", float("nan")))]
    if not iv_rows:
        return '<p class="muted">No ATM IV data available.</p>'

    iv_rows.sort(key=lambda x: -x[1])
    top = iv_rows[:CHART_MAX_BARS]

    def regime_color(label, val):
        if val >= 2.00:
            return _COLORS["alert"]
        if val >= 0.60:
            return _COLORS["watch"]
        return _COLORS["normal"]

    chart = _svg_hbar(top, "ATM IV Level (highest first)", color_fn=regime_color, fmt=".2f")

    table = '<table class="tbl">'
    table += "<tr><th>Ticker</th><th>ATM IV</th><th>Regime</th><th>Event Premium</th><th>Cat Days</th></tr>"
    for ticker, iv in top:
        r = next((x for x in eligible if x["ticker"] == ticker), {})
        cd = r.get("catalyst_days", float("nan"))
        cd_str = f"{cd:.0f}" if not math.isnan(cd) else ""
        table += (
            f"<tr><td>{ticker}</td><td>{iv:.2f}</td>"
            f'<td>{r.get("opt_iv_regime", "")}</td>'
            f'<td>{r.get("opt_event_premium", "")}</td>'
            f"<td>{cd_str}</td></tr>"
        )
    table += "</table>"
    return chart + "\n" + table


def _page_scatter(eligible: List[Dict]) -> str:
    """Page 5: Implied event move vs catalyst timing scatter."""
    data = []
    for r in eligible:
        x = r.get("catalyst_days", float("nan"))
        # Prefer actual_implied_move_pctile, fall back to implied_event_move
        y = r.get("actual_implied_move_pctile", float("nan"))
        if math.isnan(y):
            y = r.get("implied_event_move", float("nan"))
        if math.isnan(x) or math.isnan(y):
            continue
        size = r.get("priority_score", 0)
        data.append((r["ticker"], x, y, size, r.get("is_hard_catalyst", False)))

    chart = _svg_scatter(
        data,
        "Implied Event Move vs Catalyst Days",
        "Catalyst Days",
        "Implied Event Move",
    )

    legend = (
        '<div class="legend">'
        f'<span style="color:{_COLORS["hard"]}">&#9679; Hard catalyst</span> &nbsp; '
        f'<span style="color:{_COLORS["normal"]}">&#9679; Soft catalyst</span> &nbsp; '
        "Size = priority score</div>"
    )

    return chart + "\n" + legend


def _page_skew(eligible: List[Dict]) -> str:
    """Page 6: Skew / RR panel."""
    # RR chart — flagged names + top 5 non-flagged by abs RR
    flagged_tickers = {r["ticker"] for r in eligible if r.get("flags")}
    rr_rows = [(r["ticker"], r["opt_rr_25d"]) for r in eligible if not math.isnan(r.get("opt_rr_25d", float("nan")))]
    # Flagged first, then top non-flagged
    flagged_rr = [(t, v) for t, v in rr_rows if t in flagged_tickers]
    nonflagged_rr = sorted(
        [(t, v) for t, v in rr_rows if t not in flagged_tickers],
        key=lambda x: -abs(x[1]),
    )[:5]
    rr_chart_data = sorted(flagged_rr + nonflagged_rr, key=lambda x: x[1])

    def rr_color(label, val):
        if label in flagged_tickers:
            return _COLORS["alert"] if abs(val) >= 0.15 else _COLORS["watch"]
        return _COLORS["muted"]

    rr_chart = _svg_hbar(rr_chart_data[:CHART_MAX_BARS], "25-Delta Risk Reversal", color_fn=rr_color, fmt=".4f")

    # Skew chart
    skew_rows = [
        (r["ticker"], r["opt_put_call_skew"])
        for r in eligible
        if not math.isnan(r.get("opt_put_call_skew", float("nan")))
    ]
    flagged_skew = [(t, v) for t, v in skew_rows if t in flagged_tickers]
    nonflagged_skew = sorted(
        [(t, v) for t, v in skew_rows if t not in flagged_tickers],
        key=lambda x: -abs(x[1]),
    )[:5]
    skew_chart_data = sorted(flagged_skew + nonflagged_skew, key=lambda x: x[1])

    skew_chart = _svg_hbar(skew_chart_data[:CHART_MAX_BARS], "Put/Call Skew (ATM)", color_fn=rr_color, fmt=".4f")

    return rr_chart + "\n<br/>\n" + skew_chart


def _page_queue_context(
    eligible: List[Dict],
    review_queue: List[Dict],
    trade_plan: List[Dict],
    shadow_positions: Optional[Dict],
) -> str:
    """Page 7: Queue / trade context."""
    sections = []

    # Review queue overlap
    rq_tickers = {(r.get("ticker") or "").upper() for r in review_queue}
    rq_overlap = [r for r in eligible if r["ticker"] in rq_tickers]
    if rq_overlap:
        rq_detail = {(r.get("ticker") or "").upper(): r for r in review_queue}
        sections.append("<h3>In Review Queue</h3>")
        sections.append(
            '<table class="tbl"><tr><th>Ticker</th><th>Action</th>' "<th>Reason</th><th>ATM IV</th><th>Flags</th></tr>"
        )
        for r in rq_overlap:
            rqr = rq_detail.get(r["ticker"], {})
            sections.append(
                f'<tr><td>{r["ticker"]}</td>'
                f'<td>{escape(rqr.get("action", ""))}</td>'
                f'<td>{escape(rqr.get("action_reason", ""))}</td>'
                f'<td>{r["opt_atm_iv"]:.2f}</td>'
                f'<td>{", ".join(r.get("flags", []))}</td></tr>'
            )
        sections.append("</table>")

    # Trade plan overlap
    tp_tickers = {(r.get("ticker") or "").upper() for r in trade_plan}
    tp_overlap = [r for r in eligible if r["ticker"] in tp_tickers]
    if tp_overlap:
        tp_detail = {(r.get("ticker") or "").upper(): r for r in trade_plan}
        sections.append("<h3>In Trade Plan</h3>")
        sections.append(
            '<table class="tbl"><tr><th>Ticker</th><th>Action</th>'
            "<th>Delta $</th><th>ATM IV</th><th>Regime</th></tr>"
        )
        for r in tp_overlap:
            tpr = tp_detail.get(r["ticker"], {})
            sections.append(
                f'<tr><td>{r["ticker"]}</td>'
                f'<td>{escape(tpr.get("action", ""))}</td>'
                f'<td>{tpr.get("delta_usd", "")}</td>'
                f'<td>{r["opt_atm_iv"]:.2f}</td>'
                f'<td>{r.get("opt_iv_regime", "")}</td></tr>'
            )
        sections.append("</table>")

    # Shadow positions overlap
    shadow_overlap = [r for r in eligible if r.get("in_shadow")]
    if shadow_overlap:
        sections.append("<h3>In Shadow Portfolio</h3>")
        sections.append(
            '<table class="tbl"><tr><th>Ticker</th><th>ATM IV</th>'
            "<th>Term Slope</th><th>Event Premium</th><th>Flags</th></tr>"
        )
        for r in shadow_overlap:
            sections.append(
                f'<tr><td>{r["ticker"]}</td>'
                f'<td>{r["opt_atm_iv"]:.2f}</td>'
                f'<td>{r["opt_term_slope"]:.3f}</td>'
                f'<td>{r.get("opt_event_premium", "")}</td>'
                f'<td>{", ".join(r.get("flags", []))}</td></tr>'
            )
        sections.append("</table>")

    if not sections:
        return '<p class="muted">No watchlist names overlap with queue, trade plan, or shadow.</p>'

    return "\n".join(sections)


def _page_suppressed(suppressed: List[Dict]) -> str:
    """Page 8: Suppressed / excluded."""
    if not suppressed:
        return '<p class="muted">No suppressed names.</p>'

    html = ['<table class="tbl">']
    html.append(
        "<tr><th>Ticker</th><th>Reason</th><th>Has Data</th>" "<th>Liquidity</th><th>Judgment</th><th>Regime</th></tr>"
    )
    for r in suppressed:
        html.append(
            f'<tr><td>{r["ticker"]}</td>'
            f'<td>{escape(r.get("reason", ""))}</td>'
            f'<td>{r.get("opt_has_data", "")}</td>'
            f'<td>{r.get("opt_liquidity_ok", "")}</td>'
            f'<td>{r.get("opt_use_for_judgment", "")}</td>'
            f'<td>{r.get("opt_iv_regime", "")}</td></tr>'
        )
    html.append("</table>")
    return "\n".join(html)


def _page_live_delta(surface_delta: Optional[Dict]) -> str:
    """Page 9 (optional): Live opening surface delta."""
    if not surface_delta:
        return '<p class="muted">No surface delta data available (run surface_delta_monitor.py first).</p>'

    deltas = surface_delta.get("deltas", [])
    if not deltas:
        return '<p class="muted">No significant surface shifts detected.</p>'

    alerts = [d for d in deltas if d.get("severity") == "alert"]
    watches = [d for d in deltas if d.get("severity") == "watch"]

    html = [
        f'<p>Prior: {surface_delta.get("prior_date", "?")} | '
        f'Compared: {surface_delta.get("n_compared", 0)} | '
        f"<strong>{len(alerts)} alert</strong> / {len(watches)} watch</p>"
    ]

    if alerts:
        html.append("<h3>Alerts</h3>")
        html.append(_delta_table(alerts))

    if watches:
        html.append("<h3>Watch</h3>")
        html.append(_delta_table(watches[:15]))

    return "\n".join(html)


def _delta_table(rows: List[Dict]) -> str:
    """Render surface delta rows as a table."""
    html = ['<table class="tbl">']
    html.append(
        "<tr><th>Ticker</th><th>Cat Days</th><th>IV Change</th>"
        "<th>RR Change</th><th>Skew Change</th><th>Flags</th></tr>"
    )
    for d in rows:
        iv_chg = d.get("atm_iv_change", "")
        if isinstance(iv_chg, (int, float)):
            iv_chg = f"{iv_chg:+.4f}"
        rr_chg = d.get("rr_25d_change", "")
        if isinstance(rr_chg, (int, float)):
            rr_chg = f"{rr_chg:+.4f}"
        skew_chg = d.get("skew_change", "")
        if isinstance(skew_chg, (int, float)):
            skew_chg = f"{skew_chg:+.4f}"
        flags = d.get("flags", [])
        if isinstance(flags, list):
            flags = ", ".join(flags)
        html.append(
            f'<tr><td>{d.get("ticker", "")}</td>'
            f'<td>{d.get("catalyst_days", "")}</td>'
            f"<td>{iv_chg}</td>"
            f"<td>{rr_chg}</td>"
            f"<td>{skew_chg}</td>"
            f'<td><span class="flag-tag">{escape(str(flags))}</span></td></tr>'
        )
    html.append("</table>")
    return "\n".join(html)


# ---------------------------------------------------------------------------
# Full HTML assembly
# ---------------------------------------------------------------------------

_CSS = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 13px; color: #212529; background: #fff;
    max-width: 800px; margin: 0 auto; padding: 20px;
  }
  h1 { font-size: 20px; margin-bottom: 4px; }
  h2 { font-size: 16px; margin: 24px 0 8px; padding: 6px 0; border-bottom: 2px solid #0d6efd; }
  h3 { font-size: 14px; margin: 16px 0 6px; color: #495057; }
  .subtitle { color: #6c757d; font-size: 12px; margin-bottom: 16px; }
  .muted { color: #6c757d; font-style: italic; }
  .banner { padding: 8px 12px; border-radius: 4px; margin-bottom: 12px; font-weight: 600; }
  .banner-fail { background: #f8d7da; color: #842029; }
  .banner-warn { background: #fff3cd; color: #664d03; }
  .kpi-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; margin: 12px 0; }
  .kpi { text-align: center; padding: 10px 4px; background: #f8f9fa; border-radius: 6px; }
  .kpi-val { font-size: 22px; font-weight: 700; color: #0d6efd; }
  .kpi-label { font-size: 11px; color: #6c757d; margin-top: 2px; }
  .tbl { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 12px; }
  .tbl th, .tbl td { padding: 4px 8px; border: 1px solid #dee2e6; text-align: left; }
  .tbl th { background: #f8f9fa; font-weight: 600; white-space: nowrap; }
  .tbl tr:nth-child(even) { background: #f8f9fa; }
  .flag-tag { font-size: 10px; color: #dc3545; }
  .page-break { page-break-after: always; }
  .legend { font-size: 11px; color: #6c757d; margin: 8px 0; }
  svg { display: block; margin: 8px 0; }
  @media print { .page-break { page-break-after: always; } }
</style>
"""


def render_html(
    as_of_date: str,
    pages: List[Tuple[str, str]],
) -> str:
    """Render full HTML chartbook from page list of (title, content_html)."""
    html = [
        "<!DOCTYPE html>",
        f"<html><head><meta charset='utf-8'><title>Options Chartbook — {as_of_date}</title>",
        _CSS,
        "</head><body>",
        "<h1>Options Chartbook</h1>",
        f'<div class="subtitle">{as_of_date} &mdash; generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</div>',
    ]

    for i, (title, content) in enumerate(pages):
        html.append(f"<h2>{i + 1}. {escape(title)}</h2>")
        html.append(content)
        if i < len(pages) - 1:
            html.append('<div class="page-break"></div>')

    html.append("</body></html>")
    return "\n".join(html)


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def build_chartbook(
    as_of_date: str,
    *,
    snapshots_dir: Path = SNAPSHOT_DIR,
) -> Dict[str, Any]:
    """Build the options chartbook.

    Returns result dict with schema, paths, and metadata.
    """
    snap_dir = snapshots_dir / as_of_date
    if not snap_dir.exists():
        return {"error": f"No snapshot for {as_of_date}"}

    # Load inputs
    rankings = _load_csv(snap_dir / "rankings.csv")
    if not rankings:
        return {"error": f"No rankings.csv in {snap_dir}"}

    options_watch = _load_json(REPO_ROOT / "artifacts" / "options_watch" / f"{as_of_date}_watch.json")
    diag_summary = _load_json(snap_dir / "options_diagnostics_summary.json")
    coverage = _load_json(snap_dir / "coverage_quality.json")
    review_queue = _load_csv(snap_dir / "review_queue.csv")
    trade_plan = _load_csv(REPO_ROOT / "artifacts" / "live_shadow" / "trade_plan" / as_of_date / "trade_plan.csv")
    shadow_json = _load_json(REPO_ROOT / "artifacts" / "live_shadow" / "positions" / f"{as_of_date}.json")
    surface_delta = _load_json(snap_dir / "surface_delta.json")

    # Extract ticker sets from context artifacts
    trade_plan_tickers = {(r.get("ticker") or "").upper() for r in trade_plan} - {""}
    shadow_tickers = set()
    if shadow_json:
        for p in shadow_json.get("positions", []):
            t = (p.get("ticker") or "").upper()
            if t:
                shadow_tickers.add(t)
    review_queue_tickers = {(r.get("ticker") or "").upper() for r in review_queue} - {""}

    # Get ruleset ID
    metadata = _load_json(snap_dir / "metadata.json")
    ruleset_id = "?"
    if metadata:
        ruleset_id = metadata.get("ruleset_id", metadata.get("decision_engine_version", "?"))
    p2h = _load_json(snap_dir / "phase2_health.json")
    if p2h:
        ruleset_id = p2h.get("metrics", {}).get("ruleset_id", ruleset_id)

    # Build watchlist
    eligible, suppressed = build_watchlist(
        rankings,
        options_watch,
        trade_plan_tickers,
        shadow_tickers,
        review_queue_tickers,
    )

    logger.info(
        "Watchlist: %d eligible, %d suppressed, %d flagged",
        len(eligible),
        len(suppressed),
        sum(1 for r in eligible if r.get("flags")),
    )

    # Build pages
    pages = [
        (
            "Cover / Scoreboard",
            _page_scoreboard(
                as_of_date,
                eligible,
                suppressed,
                diag_summary,
                coverage,
                surface_delta,
                ruleset_id,
            ),
        ),
        ("Flagged Names", _page_flagged(eligible)),
        ("Top Backwardation", _page_backwardation(eligible)),
        ("Top IV Movers (5d)", _page_iv_movers(eligible)),
        ("Surface Move vs Catalyst Timing", _page_scatter(eligible)),
        ("Skew / Risk Reversal", _page_skew(eligible)),
        (
            "Queue / Trade Context",
            _page_queue_context(
                eligible,
                review_queue,
                trade_plan,
                shadow_json,
            ),
        ),
        ("Suppressed / Excluded", _page_suppressed(suppressed)),
    ]

    # Optional live delta page
    if surface_delta:
        pages.append(("Live Surface Delta", _page_live_delta(surface_delta)))

    html = render_html(as_of_date, pages)

    # Write outputs
    out_dir = OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    html_path = out_dir / f"{as_of_date}_chartbook.html"
    html_path.write_text(html, encoding="utf-8")
    logger.info("Wrote %s", html_path)

    # JSON metadata
    json_result = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active_ruleset_id": ruleset_id,
        "source_artifacts": {
            "rankings": str(snap_dir / "rankings.csv"),
            "options_watch": str(REPO_ROOT / "artifacts" / "options_watch" / f"{as_of_date}_watch.json"),
            "options_diagnostics_summary": str(snap_dir / "options_diagnostics_summary.json"),
            "coverage_quality": str(snap_dir / "coverage_quality.json"),
            "review_queue": str(snap_dir / "review_queue.csv"),
            "trade_plan": str(REPO_ROOT / "artifacts" / "live_shadow" / "trade_plan" / as_of_date / "trade_plan.csv"),
            "shadow_positions": str(REPO_ROOT / "artifacts" / "live_shadow" / "positions" / f"{as_of_date}.json"),
            "surface_delta": str(snap_dir / "surface_delta.json"),
        },
        "scoreboard": {
            "watchlist_size": len(eligible),
            "n_flagged": sum(1 for r in eligible if r.get("flags")),
            "n_suppressed": len(suppressed),
            "options_watch_available": options_watch is not None,
            "surface_delta_available": surface_delta is not None,
        },
        "flagged_tickers": [r["ticker"] for r in eligible if r.get("flags")],
        "suppressed_tickers": [r["ticker"] for r in suppressed],
    }

    json_path = out_dir / f"{as_of_date}_chartbook.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_result, f, indent=2, default=str)
    logger.info("Wrote %s", json_path)

    return {
        **json_result,
        "_html_path": str(html_path),
        "_json_path": str(json_path),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Build daily options chartbook (HTML)")
    parser.add_argument(
        "--as-of-date",
        default=None,
        help="Snapshot date (YYYY-MM-DD). Default: latest snapshot.",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the chartbook in a browser after building.",
    )
    args = parser.parse_args()

    as_of = args.as_of_date or _find_latest_snapshot(SNAPSHOT_DIR)
    if not as_of:
        print("No snapshots found.", file=sys.stderr)
        sys.exit(1)

    result = build_chartbook(as_of)
    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    print(f"Chartbook: {result['_html_path']}")
    print(f"Metadata:  {result['_json_path']}")
    print(
        f"Watchlist: {result['scoreboard']['watchlist_size']} eligible, "
        f"{result['scoreboard']['n_flagged']} flagged, "
        f"{result['scoreboard']['n_suppressed']} suppressed"
    )

    if args.open:
        webbrowser.open(f"file://{result['_html_path']}")


if __name__ == "__main__":
    main()

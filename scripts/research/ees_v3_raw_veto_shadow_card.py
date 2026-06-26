"""
EES v3 Raw Veto Shadow Card

Daily production-shadow artifact for raw_veto_core monitoring.
Records which ranker-selected names would be vetoed by raw_veto_core
and tracks their forward outcomes.

NOT a production gate. NOT a portfolio action. NOT a selector change.
This is a scoreboard — read-only diagnostic output alongside the
production run. No production path reads this artifact.

Required labels:
    FREEZE_ACTIVE
    DIAGNOSTIC_ONLY
    RAW_VETO_CORE_LEAD_CANDIDATE
    NO_PRODUCTION_DECISIONING
    NO_PORTFOLIO_ACTION

GOVERNANCE: DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE | NO_CRON
"""

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

GOVERNANCE = "DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE | NO_CRON"
LABELS = [
    "FREEZE_ACTIVE",
    "DIAGNOSTIC_ONLY",
    "RAW_VETO_CORE_LEAD_CANDIDATE",
    "NO_PRODUCTION_DECISIONING",
    "NO_PORTFOLIO_ACTION",
]

SNAP_DIR = Path("data/snapshots")
PRICE_HISTORY = Path("production_data/price_history.csv")
LEDGER_PATH = Path("artifacts/shadow/ees_v3_raw_veto_shadow_ledger.jsonl")
CARD_DIR = Path("artifacts/shadow")
STATUS_DIR = Path("artifacts/readiness")

QUINTILE_PCT = 20
HORIZONS = [5, 10, 20]
GATE_HORIZON = 20
GATE_OBS_NEEDED = 20

# Historical PIT baseline (raw_veto_core, 63d, from promotion simulator)
HISTORICAL_VETO_FREQ_MEAN = 7.0
HISTORICAL_VETO_FREQ_MIN_WARN = 3
HISTORICAL_VETO_FREQ_MAX_WARN = 15
HISTORICAL_PIT_EXCESS_PCT = 3.53  # raw_veto_core 63d mean excess vs XBI


# ─── helpers ─────────────────────────────────────────────────────────────────


def _safe_float(v, default=None):
    if v is None or v == "" or v in ("None", "nan", "NaN"):
        return default
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return default


def _has_priced_move(row):
    val = row.get("priced_move_pct", "")
    if not val or val in ("None", "nan", "NaN", "0", "0.0", ""):
        return False
    try:
        f = float(val)
        return not math.isnan(f) and f != 0.0
    except (ValueError, TypeError):
        return False


def _top_q_threshold(values, pct):
    vals = sorted([v for v in values if v is not None], reverse=True)
    n = max(1, int(len(vals) * pct / 100))
    return vals[n - 1] if vals else 0.0


def _bottom_q_threshold(values, pct):
    vals = sorted([v for v in values if v is not None])
    n = max(1, int(len(vals) * pct / 100))
    return vals[n - 1] if vals else 0.0


def _mean(vals):
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else None


# ─── failure mode classification (PIT-safe) ───────────────────────────────────


def classify_failure_modes(row, anchor_price):
    """Classify failure modes using only information available at snapshot date."""
    misprice = _safe_float(row.get("conditional_misprice_score"))
    priced = _has_priced_move(row)
    dilution = _safe_float(row.get("dilution_haircut"), default=0.0)
    financing_raw = row.get("financing_truth_gate", "")
    try:
        financing = (
            float(financing_raw)
            if financing_raw not in ("True", "False", "", None)
            else (1.0 if financing_raw == "True" else 0.0)
        )
    except (ValueError, TypeError):
        financing = 1.0
    catalyst_days = _safe_float(row.get("catalyst_days"))

    modes = set()

    if priced and misprice is not None and misprice < -0.1:
        modes.add("market_already_priced")

    if not priced and misprice is not None and abs(misprice) < 0.05:
        modes.add("no_options_coverage")

    if financing < 0.5:
        modes.add("dilution_overhang")
    elif dilution is not None and dilution > 0.25:
        modes.add("dilution_overhang")

    if catalyst_days is not None and catalyst_days > 180:
        modes.add("catalyst_too_far")

    if anchor_price is None:
        modes.add("stale_proxy")

    if not modes:
        modes.add("other")

    return sorted(modes)


# ─── price loading ────────────────────────────────────────────────────────────


def load_prices():
    prices = defaultdict(dict)
    with open(PRICE_HISTORY) as f:
        reader = csv.DictReader(f)
        for row in reader:
            close = _safe_float(row.get("close"))
            if close is not None:
                prices[row["ticker"]][row["date"]] = close
    return prices


def _sorted_dates(prices):
    return sorted(prices.get("XBI", {}).keys())


def _anchor(ticker, date, prices, sdates):
    tp = prices.get(ticker, {})
    if date in tp:
        return tp[date]
    candidates = [d for d in sdates if d <= date and d in tp]
    return tp[candidates[-1]] if candidates else None


def _nth_trading_date(from_date, n, sdates):
    for i, d in enumerate(sdates):
        if d >= from_date:
            target = i + n
            return sdates[target] if target < len(sdates) else None
    return None


def _fwd_return(ticker, snap_date, n, prices, sdates):
    tp = prices.get(ticker, {})
    anchor = _anchor(ticker, snap_date, prices, sdates)
    if not anchor:
        return None
    fwd_date = _nth_trading_date(snap_date, n, sdates)
    if not fwd_date:
        return None
    fwd = tp.get(fwd_date)
    if fwd is None:
        return None
    return (fwd - anchor) / anchor


def _portfolio_excess(tickers, snap_date, n, prices, sdates):
    """Equal-weight mean excess return of tickers vs XBI at horizon n."""
    xbi_ret = _fwd_return("XBI", snap_date, n, prices, sdates)
    if xbi_ret is None:
        return None
    rets = []
    for t in tickers:
        r = _fwd_return(t, snap_date, n, prices, sdates)
        if r is not None:
            rets.append(r - xbi_ret)
    return _mean(rets)


# ─── snapshot loading ─────────────────────────────────────────────────────────


def find_snap_date(as_of_date):
    """Find the most recent snapshot date <= as_of_date."""
    if not SNAP_DIR.exists():
        return None
    dates = sorted(d.name for d in SNAP_DIR.iterdir() if (SNAP_DIR / d.name / "rankings.csv").exists())
    candidates = [d for d in dates if d <= as_of_date]
    return candidates[-1] if candidates else None


def load_snapshot(snap_date):
    path = SNAP_DIR / snap_date / "rankings.csv"
    if not path.exists():
        return None
    with open(path) as f:
        return list(csv.DictReader(f))


# ─── veto logic ───────────────────────────────────────────────────────────────


def apply_raw_veto_core(rows, prices, sdates, snap_date):
    """
    Apply raw_veto_core: ranker top-Q minus EES v3 bottom-Q.
    Returns (selected, vetoed, meta).
    """
    fs_vals = [_safe_float(r.get("final_score")) for r in rows]
    v3_vals = [_safe_float(r.get("ees_v3_score")) for r in rows]

    fs_top_q = _top_q_threshold(fs_vals, QUINTILE_PCT)
    v3_bottom_q = _bottom_q_threshold(v3_vals, QUINTILE_PCT)

    selected = []
    vetoed = []

    for row in rows:
        ticker = row.get("ticker", "")
        fs = _safe_float(row.get("final_score"))
        v3 = _safe_float(row.get("ees_v3_score"))
        if fs is None or v3 is None:
            continue
        if fs < fs_top_q:
            continue

        anchor = _anchor(ticker, snap_date, prices, sdates)
        entry = {
            "ticker": ticker,
            "final_score": fs,
            "ees_v3_score": v3,
            "anchor_price": anchor,
            "priced_move_pct": _safe_float(row.get("priced_move_pct")),
            "conditional_misprice_score": _safe_float(row.get("conditional_misprice_score")),
            "conditional_expected_move": _safe_float(row.get("conditional_expected_move")),
            "catalyst_days": _safe_float(row.get("catalyst_days")),
            "catalyst_family": row.get("catalyst_family", ""),
        }

        if v3 <= v3_bottom_q:
            entry["failure_modes"] = classify_failure_modes(row, anchor)
            vetoed.append(entry)
        else:
            selected.append(entry)

    meta = {
        "fs_top_q_threshold": fs_top_q,
        "v3_bottom_q_threshold": v3_bottom_q,
        "n_eligible": len(rows),
        "n_ranker_top_q": len(selected) + len(vetoed),
    }
    return selected, vetoed, meta


# ─── ledger operations ────────────────────────────────────────────────────────


def load_ledger():
    if not LEDGER_PATH.exists():
        return []
    rows = []
    with open(LEDGER_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def settle_row(row, prices, sdates):
    """
    Try to settle forward returns for any unsettled horizons.
    Returns (updated_row, changed).
    Settled rows are immutable — this only fills in null slots.
    """
    changed = False
    snap_date = row["snap_date"]
    selected = row.get("selected_tickers", [])
    vetoed = row.get("vetoed_tickers", [])

    for h in HORIZONS:
        key_settled = f"fwd_{h}d_settled"
        if row.get(key_settled):
            continue

        # Check if the forward date is available
        fwd_date = _nth_trading_date(snap_date, h, sdates)
        if fwd_date is None:
            continue

        # Check if XBI has price for fwd_date
        if prices.get("XBI", {}).get(fwd_date) is None:
            continue

        sel_exc = _portfolio_excess(selected, snap_date, h, prices, sdates)
        veto_exc = _portfolio_excess(vetoed, snap_date, h, prices, sdates)
        alpha = (sel_exc - veto_exc) if (sel_exc is not None and veto_exc is not None) else None

        row[f"fwd_{h}d_selected_excess"] = round(sel_exc * 100, 3) if sel_exc is not None else None
        row[f"fwd_{h}d_vetoed_excess"] = round(veto_exc * 100, 3) if veto_exc is not None else None
        row[f"fwd_{h}d_veto_alpha"] = round(alpha * 100, 3) if alpha is not None else None
        row[key_settled] = True
        changed = True

    return row, changed


def build_new_row(snap_date, selected, vetoed, meta):
    """Build a new ledger row for snap_date."""
    mode_counts = defaultdict(int)
    for v in vetoed:
        for m in v.get("failure_modes", []):
            mode_counts[m] += 1

    priced_vetoed = sum(1 for v in vetoed if v.get("priced_move_pct") is not None)

    return {
        "snap_date": snap_date,
        "lead_policy": "raw_veto_core",
        "governance": GOVERNANCE,
        "labels": LABELS,
        "n_eligible": meta["n_eligible"],
        "n_ranker_top_q": meta["n_ranker_top_q"],
        "n_selected": len(selected),
        "n_vetoed": len(vetoed),
        "selected_tickers": [e["ticker"] for e in selected],
        "vetoed_tickers": [e["ticker"] for e in vetoed],
        "vetoed_detail": [
            {
                "ticker": e["ticker"],
                "final_score": e["final_score"],
                "ees_v3_score": e["ees_v3_score"],
                "failure_modes": e["failure_modes"],
                "anchor_price": e["anchor_price"],
                "priced_move_pct": e["priced_move_pct"],
                "catalyst_days": e["catalyst_days"],
                "catalyst_family": e["catalyst_family"],
            }
            for e in vetoed
        ],
        "failure_mode_counts": dict(mode_counts),
        "priced_move_pct_covered_vetoed": priced_vetoed,
        "fs_top_q_threshold": meta["fs_top_q_threshold"],
        "v3_bottom_q_threshold": meta["v3_bottom_q_threshold"],
        # Settlement slots — filled in as time passes
        "fwd_5d_selected_excess": None,
        "fwd_5d_vetoed_excess": None,
        "fwd_5d_veto_alpha": None,
        "fwd_5d_settled": False,
        "fwd_10d_selected_excess": None,
        "fwd_10d_vetoed_excess": None,
        "fwd_10d_veto_alpha": None,
        "fwd_10d_settled": False,
        "fwd_20d_selected_excess": None,
        "fwd_20d_vetoed_excess": None,
        "fwd_20d_veto_alpha": None,
        "fwd_20d_settled": False,
        "ledger_version": "v1",
        "run_ts": datetime.now().isoformat(),
    }


def save_ledger(rows):
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_PATH, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


# ─── cumulative stats ─────────────────────────────────────────────────────────


def compute_cumulative(ledger):
    stats = {}
    for h in HORIZONS:
        # Only count rows where a veto actually occurred (n_vetoed > 0)
        # Zero-veto rows (pre-EES-v3 snapshots) don't produce meaningful alpha
        settled = [r for r in ledger if r.get(f"fwd_{h}d_settled") and r.get("n_vetoed", 0) > 0]
        alphas = [r[f"fwd_{h}d_veto_alpha"] for r in settled if r.get(f"fwd_{h}d_veto_alpha") is not None]
        sel_exc = [r[f"fwd_{h}d_selected_excess"] for r in settled if r.get(f"fwd_{h}d_selected_excess") is not None]
        veto_exc = [r[f"fwd_{h}d_vetoed_excess"] for r in settled if r.get(f"fwd_{h}d_vetoed_excess") is not None]
        stats[h] = {
            "n_settled": len(settled),
            "mean_veto_alpha_pct": round(_mean(alphas), 3) if alphas else None,
            "mean_selected_excess_pct": round(_mean(sel_exc), 3) if sel_exc else None,
            "mean_vetoed_excess_pct": round(_mean(veto_exc), 3) if veto_exc else None,
            "positive_alpha_rate": round(sum(1 for a in alphas if a > 0) / len(alphas), 3) if alphas else None,
        }
    gate_obs = stats.get(GATE_HORIZON, {}).get("n_settled", 0)
    stats["gate"] = {
        "horizon_days": GATE_HORIZON,
        "obs_needed": GATE_OBS_NEEDED,
        "obs_complete": gate_obs,
        "gate_met": gate_obs >= GATE_OBS_NEEDED,
        "obs_remaining": max(0, GATE_OBS_NEEDED - gate_obs),
    }
    return stats


# ─── warning flags ────────────────────────────────────────────────────────────


def compute_warnings(n_vetoed, cumulative, ledger):
    warnings = []

    if n_vetoed < HISTORICAL_VETO_FREQ_MIN_WARN:
        warnings.append(
            f"VETO_FREQ_LOW: {n_vetoed} vetoed names (historical mean {HISTORICAL_VETO_FREQ_MEAN:.1f}, "
            f"warn threshold {HISTORICAL_VETO_FREQ_MIN_WARN})"
        )
    if n_vetoed > HISTORICAL_VETO_FREQ_MAX_WARN:
        warnings.append(
            f"VETO_FREQ_HIGH: {n_vetoed} vetoed names (historical mean {HISTORICAL_VETO_FREQ_MEAN:.1f}, "
            f"warn threshold {HISTORICAL_VETO_FREQ_MAX_WARN})"
        )

    gate = cumulative.get("gate", {})
    if not gate.get("gate_met"):
        warnings.append(
            f"GATE_UNMET: {gate.get('obs_complete', 0)}/{GATE_OBS_NEEDED} "
            f"{GATE_HORIZON}d observations complete — "
            f"{gate.get('obs_remaining', GATE_OBS_NEEDED)} more needed before freeze-lift review"
        )

    # Check if recent alpha is degrading
    recent = [r for r in ledger[-10:] if r.get("fwd_10d_settled")]
    if len(recent) >= 5:
        recent_alphas = [r["fwd_10d_veto_alpha"] for r in recent if r.get("fwd_10d_veto_alpha") is not None]
        if recent_alphas and _mean(recent_alphas) is not None and _mean(recent_alphas) < -2.0:
            warnings.append(
                f"RECENT_ALPHA_NEGATIVE: 10d veto alpha mean = {_mean(recent_alphas):.1f}% over last {len(recent_alphas)} periods"
            )

    return warnings


# ─── card and markdown output ─────────────────────────────────────────────────


def write_card(as_of_date, snap_date, selected, vetoed, meta, cumulative, warnings, card_path):
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card = {
        "as_of_date": as_of_date,
        "snap_date": snap_date,
        "governance": GOVERNANCE,
        "labels": LABELS,
        "today": {
            "n_eligible": meta["n_eligible"],
            "n_ranker_top_q": meta["n_ranker_top_q"],
            "n_selected": len(selected),
            "n_vetoed": len(vetoed),
            "vetoed_tickers": [e["ticker"] for e in vetoed],
            "surviving_tickers": [e["ticker"] for e in selected],
            "failure_mode_counts": {
                "no_options_coverage": sum(1 for v in vetoed if "no_options_coverage" in v.get("failure_modes", [])),
                "dilution_overhang": sum(1 for v in vetoed if "dilution_overhang" in v.get("failure_modes", [])),
                "market_already_priced": sum(
                    1 for v in vetoed if "market_already_priced" in v.get("failure_modes", [])
                ),
                "catalyst_too_far": sum(1 for v in vetoed if "catalyst_too_far" in v.get("failure_modes", [])),
                "stale_proxy": sum(1 for v in vetoed if "stale_proxy" in v.get("failure_modes", [])),
                "other": sum(1 for v in vetoed if "other" in v.get("failure_modes", [])),
            },
            "priced_move_pct_covered_vetoed": sum(1 for v in vetoed if v.get("priced_move_pct") is not None),
            "vetoed_detail": [
                {
                    "ticker": e["ticker"],
                    "final_score": e["final_score"],
                    "ees_v3_score": e["ees_v3_score"],
                    "failure_modes": e["failure_modes"],
                    "priced_move_pct": e["priced_move_pct"],
                    "catalyst_days": e["catalyst_days"],
                }
                for e in vetoed
            ],
        },
        "cumulative_shadow": cumulative,
        "historical_pit_baseline": {
            "policy": "raw_veto_core",
            "horizon_days": 63,
            "mean_excess_pct": HISTORICAL_PIT_EXCESS_PCT,
            "ic": 0.0639,
            "t_nw": 2.36,
            "n_snaps": 76,
            "source": "ees_v3_promotion_simulator_2026_06_25",
        },
        "warnings": warnings,
        "generated_at": datetime.now().isoformat(),
    }
    with open(card_path, "w") as f:
        json.dump(card, f, indent=2)


def write_markdown(as_of_date, snap_date, selected, vetoed, meta, cumulative, warnings, md_path):
    md_path.parent.mkdir(parents=True, exist_ok=True)

    def fmt_pct(v, decimals=1):
        if v is None:
            return "n/a"
        return f"{v:+.{decimals}f}%"

    def fmt_rate(v):
        return f"{v:.1%}" if v is not None else "n/a"

    def fmt_n(v, default="n/a"):
        return str(v) if v is not None else default

    gate = cumulative.get("gate", {})
    gate_obs = gate.get("obs_complete", 0)
    gate_met = gate.get("gate_met", False)
    gate_status = "MET" if gate_met else f"UNMET ({gate_obs}/{GATE_OBS_NEEDED})"

    lines = [
        f"# EES v3 Raw Veto Shadow Status — {as_of_date}",
        "",
        "**Governance:** FREEZE_ACTIVE | DIAGNOSTIC_ONLY | NO_PRODUCTION_DECISIONING | NO_PORTFOLIO_ACTION",
        "**Lead policy:** raw_veto_core",
        f"**Snapshot date:** {snap_date}",
        f"**Shadow gate ({GATE_HORIZON}d observations):** {gate_status}",
        "",
        "---",
        "",
        "## Today's Veto Card",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Eligible names | {meta['n_eligible']} |",
        f"| Ranker top-Q | {meta['n_ranker_top_q']} |",
        f"| **Vetoed by EES v3** | **{len(vetoed)}** |",
        f"| Surviving selection | {len(selected)} |",
        "",
        "**Vetoed tickers:** " + (", ".join(e["ticker"] for e in vetoed) if vetoed else "none"),
        "",
        "**Failure mode breakdown:**",
        "",
    ]

    mode_counts = defaultdict(int)
    for v in vetoed:
        for m in v.get("failure_modes", []):
            mode_counts[m] += 1

    for mode in [
        "no_options_coverage",
        "dilution_overhang",
        "market_already_priced",
        "catalyst_too_far",
        "stale_proxy",
        "other",
    ]:
        n = mode_counts.get(mode, 0)
        lines.append(f"- `{mode}`: {n}")

    # Vetoed detail table
    if vetoed:
        lines += [
            "",
            "| Ticker | Final Score | EES v3 | Failure Modes | Catalyst Days |",
            "|--------|------------|--------|---------------|---------------|",
        ]
        for e in vetoed:
            modes_str = ", ".join(e.get("failure_modes", []))
            cat_days = e.get("catalyst_days")
            cat_str = f"{int(cat_days)}d" if cat_days is not None else "n/a"
            lines.append(
                f"| {e['ticker']} | {e['final_score']:.3f} | {e['ees_v3_score']:.3f} | {modes_str} | {cat_str} |"
            )

    lines += [
        "",
        "---",
        "",
        "## Cumulative Shadow Performance",
        "",
        "Positive veto alpha = selected names outperforming vetoed names (veto correct).",
        "",
        "| Horizon | N Settled | Mean Veto Alpha | Selected Excess | Vetoed Excess | Alpha+ Rate |",
        "|---------|-----------|-----------------|-----------------|---------------|-------------|",
    ]

    for h in HORIZONS:
        cs = cumulative.get(h, {})
        n = cs.get("n_settled", 0)
        alpha = cs.get("mean_veto_alpha_pct")
        sel = cs.get("mean_selected_excess_pct")
        veto = cs.get("mean_vetoed_excess_pct")
        pos_rate = cs.get("positive_alpha_rate")
        lines.append(f"| {h}d | {n} | {fmt_pct(alpha)} | {fmt_pct(sel)} | {fmt_pct(veto)} | {fmt_rate(pos_rate)} |")

    # Gate status
    lines += [
        "",
        "---",
        "",
        "## Shadow Gate Progress",
        "",
        f"Gate: {GATE_OBS_NEEDED} completed {GATE_HORIZON}d observations required before freeze-lift review.",
        "",
        "| Gate | Required | Complete | Remaining | Status |",
        "|------|----------|----------|-----------|--------|",
        f"| {GATE_HORIZON}d obs | {GATE_OBS_NEEDED} | {gate_obs} | {gate.get('obs_remaining', GATE_OBS_NEEDED)} | "
        + ("**MET** ✓" if gate_met else "UNMET")
        + " |",
        "",
    ]

    # Historical baseline
    lines += [
        "## Historical PIT Baseline (raw_veto_core)",
        "",
        "From `ees_v3_promotion_simulator_2026_06_25.py` across 76 PIT snapshots 2020-2026.",
        "",
        "| Metric | PIT Value |",
        "|--------|-----------|",
        "| IC | 0.0639 |",
        "| NW t-stat | 2.36 |",
        "| Mean excess 63d | +3.53% |",
        "| Mean excess LATE | +7.1% |",
        f"| Veto freq (avg/snap) | {HISTORICAL_VETO_FREQ_MEAN} |",
        "",
    ]

    # Warnings
    if warnings:
        lines += ["## Warnings", ""]
        for w in warnings:
            lines.append(f"- **{w}**")
        lines.append("")

    lines += [
        "---",
        "",
        "## Governance",
        "",
        "```",
        "FREEZE_ACTIVE",
        "DIAGNOSTIC_ONLY",
        "RAW_VETO_CORE_LEAD_CANDIDATE",
        "NO_PRODUCTION_DECISIONING",
        "NO_PORTFOLIO_ACTION",
        "PRODUCTION_PROMOTION = NOT_AUTHORIZED (pending 20d gate + operator approval)",
        "```",
        "",
    ]

    with open(md_path, "w") as f:
        f.write("\n".join(lines) + "\n")


# ─── main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="EES v3 raw veto shadow card")
    parser.add_argument(
        "--as-of-date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Date to run card for (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not write ledger")
    args = parser.parse_args()

    as_of_date = args.as_of_date
    print(f"GOVERNANCE: {GOVERNANCE}", file=sys.stderr)
    print(f"Running shadow card for {as_of_date}", file=sys.stderr)

    # Find snapshot
    snap_date = find_snap_date(as_of_date)
    if not snap_date:
        print(f"No snapshot found on or before {as_of_date}", file=sys.stderr)
        sys.exit(1)
    print(f"Using snapshot: {snap_date}", file=sys.stderr)

    rows = load_snapshot(snap_date)
    if not rows:
        print(f"Empty snapshot at {snap_date}", file=sys.stderr)
        sys.exit(1)

    # Load prices
    print("Loading prices...", file=sys.stderr)
    prices = load_prices()
    sdates = _sorted_dates(prices)

    # Apply veto
    selected, vetoed, meta = apply_raw_veto_core(rows, prices, sdates, snap_date)
    print(
        f"Veto result: {len(vetoed)} vetoed, {len(selected)} selected from {meta['n_ranker_top_q']} ranker-top-Q",
        file=sys.stderr,
    )

    # Load ledger and settle
    ledger = load_ledger()
    settled_count = 0
    for row in ledger:
        row, changed = settle_row(row, prices, sdates)
        if changed:
            settled_count += 1
    if settled_count:
        print(f"Settled {settled_count} ledger rows", file=sys.stderr)

    # Append today's row if not already present
    existing_dates = {r["snap_date"] for r in ledger}
    if snap_date not in existing_dates:
        new_row = build_new_row(snap_date, selected, vetoed, meta)
        # Try to settle immediately (in case forward dates already exist)
        new_row, _ = settle_row(new_row, prices, sdates)
        ledger.append(new_row)
        print(f"Appended new ledger row for {snap_date}", file=sys.stderr)
    else:
        print(f"Ledger row for {snap_date} already exists (settlement updated)", file=sys.stderr)

    if not args.dry_run:
        save_ledger(ledger)
        print(f"Saved ledger ({len(ledger)} rows)", file=sys.stderr)

    # Compute cumulative stats
    cumulative = compute_cumulative(ledger)
    warnings = compute_warnings(len(vetoed), cumulative, ledger)

    # Write outputs
    date_slug = as_of_date.replace("-", "_")
    card_path = CARD_DIR / f"ees_v3_raw_veto_shadow_card_{date_slug}.json"
    md_path = STATUS_DIR / f"EES_V3_RAW_VETO_SHADOW_STATUS_{date_slug}.md"

    write_card(as_of_date, snap_date, selected, vetoed, meta, cumulative, warnings, card_path)
    write_markdown(as_of_date, snap_date, selected, vetoed, meta, cumulative, warnings, md_path)

    print(f"Wrote card:     {card_path}", file=sys.stderr)
    print(f"Wrote markdown: {md_path}", file=sys.stderr)

    # Console summary
    gate = cumulative.get("gate", {})
    print(f"\n=== EES v3 Veto Shadow Card — {as_of_date} ===")
    print(f"Snapshot: {snap_date}")
    print(f"Vetoed: {len(vetoed)} — {[e['ticker'] for e in vetoed]}")
    print(f"Selected: {len(selected)}")
    print(
        f"Shadow gate ({GATE_HORIZON}d): {gate.get('obs_complete', 0)}/{GATE_OBS_NEEDED} — {'MET' if gate.get('gate_met') else 'UNMET'}"
    )
    if cumulative.get(20, {}).get("n_settled"):
        cs = cumulative[20]
        print(f"Cumulative 20d veto alpha: {cs.get('mean_veto_alpha_pct', 'n/a')}%")
    for w in warnings:
        print(f"WARNING: {w}")


if __name__ == "__main__":
    main()

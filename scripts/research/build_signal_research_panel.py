#!/usr/bin/env python3
"""Build the unified signal research panel for Spec 049.

Joins PIT-safe snapshots × forward returns × regime labels into a single
research panel with one row per (ticker, snapshot_date).  Every gate,
selector, ranker and modifier signal column from rankings.csv is preserved,
plus computed forward returns at multiple horizons and regime labels.

Outputs:
  output/signals/research_panel.parquet   – full panel
  output/signals/research_panel_meta.json – coverage summary + manifest

Usage:
    python3 scripts/research/build_signal_research_panel.py
    python3 scripts/research/build_signal_research_panel.py --start 2022-01-01
    python3 scripts/research/build_signal_research_panel.py --no-parquet  # CSV only
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots_pit_v2"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
IPO_DATES_PATH = PROJECT_ROOT / "production_data" / "ipo_dates.json"
OUTPUT_DIR = PROJECT_ROOT / "output" / "signals"

SCHEMA_VERSION = "signal_research_panel.v1"
HORIZONS = [5, 20, 63]
TOP_NS = [20, 30]

# ── Signal column taxonomy ────────────────────────────────────────────
# Maps each signal column to its research role.
# Columns not listed here are still kept in the panel but tagged "other".

GATE_COLUMNS = [
    "eligible",
    "ineligible_reasons",
    "severity",
    "fundamental_red_flag",
    "fundamental_red_flag_reasons",
    "de_drawdown",
    "de_drawdown_xbi",
    "de_drawdown_rel_xbi",
    "dd_rel_margin_rescued",
    "missing_components",
    "missingness_penalty",
    "cost_bucket",
    "size_band",
]

SELECTOR_COLUMNS = [
    # Clinical optionality / program quality
    "clinical_score_v2_z",
    "clinical_score_v2",
    "clinical_score",
    "clinical_optionality_pct_dev",
    "clinical_rank_pct_dev",
    "clinical_alpha_z",
    "clinical_score_z",
    "clinical_score_z_tier",
    "lead_program_phase",
    "program_count",
    "program_diversification",
    "endpoint_strength_score",
    "design_quality_score",
    "readout_density_90",
    "readout_curve_score",
    "late_stage_readouts_180",
    "execution_momentum",
    "clinical_quality_composite",
    "clinical_quality",
    "binary_quality_score",
    "single_asset_risk",
    "clinical_days_precision",
    "clinical_date_confidence",
    "clinical_design_quality",
    "clinical_program_depth",
    # Catalyst architecture
    "catalyst_days",
    "catalyst_bucket",
    "catalyst_mode",
    "catalyst_strength",
    "catalyst_decay_w",
    "cat_priority",
    "catalyst_event_type",
    "catalyst_family",
    "catalyst_source",
    "is_hard_catalyst",
    "catalyst_in_window",
    "catalyst_tilt_mult",
    "catalyst_tilt_applied",
    "catalyst_type_tier",
    "catalyst_type_mult",
    "regulatory_days",
    "regulatory_event_type",
    "regulatory_confidence",
    "has_regulatory_upcoming_180d",
    # Financial survivability
    "financial_score",
    "severity",
    "runway_bucket",
    # Institutional freshness
    "inst_delta_z",
    "inst_delta_net",
    "inst_delta_new",
    "inst_delta_exit",
    "inst_delta_nonzero_pct",
    "has_inst_delta",
    "coinvest_conviction",
    "coinvest_tier1_conviction",
    "coinvest_filing_age_days",
    "coinvest_recency_state",
    "coinvest_score_z",
    "coinvest_tag",
    "coinvest_max_position_pct",
    "has_coinvest_signal",
]

RANKER_COLUMNS = [
    # Options / event-premium
    "opt_atm_iv",
    "opt_front_iv",
    "opt_back_iv",
    "opt_term_slope",
    "opt_put_call_skew",
    "opt_rr_25d",
    "opt_iv_regime",
    "opt_event_premium",
    "opt_liquidity_state",
    "opt_liquidity_ok",
    "opt_use_for_judgment",
    "actual_implied_move_pctile",
    "implied_event_move",
    "options_quality_composite",
    "cheap_vol_score",
    "vol_classification",
    "iv_crush_breakeven_pct",
    "crush_adjusted_implied_move",
    "pos_divergence",
    "market_model_disagreement",
    "surface_signal_quality",
    "ovf_composite",
    "ovf_agreement_count",
    "ovf_severity_score",
    "ovf11_score",
    "ovf11_confidence",
    "ovf11_quality",
    "pre_event_put_call_ratio",
    "atm_iv_change_5d",
    "surface_move_extreme",
    "iv_ramp_flag",
    "rr_25d_trend_7d",
    "rr_trend_flag",
    # AACT / timeline delta
    "aact_execution_score",
    # Microstructure
    # (total_volume_z not yet in snapshots — added when available)
]

MODIFIER_COLUMNS = [
    "competitive_intensity_z",
    "crowding_level",
    "therapeutic_area",
    "archetype",
    "stage_bucket",
    "market_cap_bucket",
    "sizing_multiplier_clinical",
]

COMPOSITE_COLUMNS = [
    "composite_score",
    "composite_rank",
    "score_z",
    "score_rank_pct",
    "composite_score_attn",
    "score_rank_pct_attn",
    "score_z_attn",
    "momentum_score",
    "catalyst_score",
    "smart_money_score",
    "valuation_score",
    "de_sort_total_adj",
    "de_sort_contrib_clinical",
    "de_sort_contrib_coinvest",
    "de_sort_contrib_institutional",
    "de_sort_contrib_calendar_alpha",
    "de_sort_contrib_alpha_cohort_tb",
    "de_sort_contrib_catalyst_bonus",
    "de_sort_contrib_binary_quality",
    "de_sort_contrib_binary_institutional",
    "de_sort_contrib_clinical_quality_91_180",
    "de_sort_contrib_options_quality_91_180",
    "de_sort_contrib_binary_quality_now",
    "de_sort_contrib_binary_institutional_now",
    "de_sort_contrib_clinical_build_window",
    "de_sort_contrib_pcr_penalty_bw",
    "de_sort_contrib_oncology_crowding",
    "de_sort_contrib_options_verdict",
]

ALL_SIGNAL_COLUMNS = list(
    dict.fromkeys(GATE_COLUMNS + SELECTOR_COLUMNS + RANKER_COLUMNS + MODIFIER_COLUMNS + COMPOSITE_COLUMNS)
)


def _build_role_map() -> Dict[str, str]:
    """Map column name → research role."""
    role = {}
    for c in GATE_COLUMNS:
        role[c] = "gate"
    for c in SELECTOR_COLUMNS:
        role.setdefault(c, "selector")
    for c in RANKER_COLUMNS:
        role.setdefault(c, "ranker")
    for c in MODIFIER_COLUMNS:
        role.setdefault(c, "modifier")
    for c in COMPOSITE_COLUMNS:
        role.setdefault(c, "composite")
    return role


# ── Helpers ───────────────────────────────────────────────────────────


def _sf(v, default=float("nan")):
    """Safe float parse."""
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def _sb(v) -> Optional[bool]:
    """Safe bool parse."""
    if v in ("1", "True", "true", True, 1):
        return True
    if v in ("0", "False", "false", False, 0):
        return False
    return None


# ── Data loading ──────────────────────────────────────────────────────


def load_prices() -> Dict[str, Dict[str, float]]:
    """Load price_history.csv → {ticker: {date_str: close}}."""
    series: Dict[str, Dict[str, float]] = {}
    with open(PRICE_CSV) as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "")
            d = row.get("date", "")
            c = row.get("close", "")
            if t and d and c:
                try:
                    series.setdefault(t, {})[d] = float(c)
                except ValueError:
                    pass
    return series


def _load_ipo_dates() -> Dict[str, str]:
    """Load ipo_dates.json → {ticker: first_price_date}."""
    if not IPO_DATES_PATH.exists():
        return {}
    with open(IPO_DATES_PATH) as f:
        raw = json.load(f)
    tickers = raw.get("tickers", {})
    return {t: v.get("first_price_date", "") for t, v in tickers.items()}


def get_snapshot_dates(start: str) -> List[str]:
    """Get sorted PIT v2 snapshot dates with rankings.csv."""
    dates = []
    for d in SNAPSHOTS_DIR.iterdir():
        if not d.is_dir() or d.name.startswith("_"):
            continue
        if d.name < start:
            continue
        if (d / "rankings.csv").exists():
            dates.append(d.name)
    return sorted(dates)


def dedupe_monthly(dates: List[str]) -> List[str]:
    """Keep one snapshot per calendar month (last available)."""
    by_month: Dict[str, str] = {}
    for d in dates:
        by_month[d[:7]] = d
    return sorted(by_month.values())


def load_rankings(snap_date: str, ipo_dates: Dict[str, str]) -> List[Dict[str, str]]:
    """Load rankings.csv with IPO-date survivorship filter and deduplication."""
    path = SNAPSHOTS_DIR / snap_date / "rankings.csv"
    with open(path) as f:
        rows = list(csv.DictReader(f))
    if ipo_dates:
        rows = [r for r in rows if ipo_dates.get(r.get("ticker", ""), "0000") <= snap_date]
    # Guard against duplicate tickers in a single snapshot
    seen = set()
    deduped = []
    for r in rows:
        t = r.get("ticker", "")
        if t and t not in seen:
            seen.add(t)
            deduped.append(r)
        elif t in seen:
            print(f"  WARNING: duplicate ticker {t} in {snap_date}, keeping first")
    return deduped


def forward_return(
    prices: Dict[str, float],
    sorted_dates: List[str],
    snap_date: str,
    horizon: int,
    execution_lag: int = 1,
) -> Optional[float]:
    """Forward return from snap_date over horizon trading days.

    With ``execution_lag=1`` (default), the return window starts at the
    **next trading day** after snap_date — matching realistic execution
    where signals are computed at close and trades execute next day.

    With ``execution_lag=0``, starts at snap_date close (legacy behavior).

    Uses pre-sorted date list to avoid re-sorting per call.
    """
    # Binary search for start date
    lo, hi = 0, len(sorted_dates)
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_dates[mid] < snap_date:
            lo = mid + 1
        else:
            hi = mid
    if lo >= len(sorted_dates):
        return None
    # Apply execution lag: skip N trading days from snap_date
    idx = lo + execution_lag
    target_idx = idx + horizon
    if target_idx >= len(sorted_dates) or idx >= len(sorted_dates):
        return None
    p0 = prices.get(sorted_dates[idx])
    p1 = prices.get(sorted_dates[target_idx])
    if p0 and p1 and p0 > 0:
        return (p1 - p0) / p0
    return None


# ── Panel building ────────────────────────────────────────────────────


def build_panel(
    start: str = "2020-06-01",
    monthly: bool = True,
) -> List[Dict[str, Any]]:
    """Build the full research panel."""
    print("Loading prices...")
    prices = load_prices()
    xbi_prices = prices.get("XBI", {})
    xbi_sorted = sorted(xbi_prices.keys())
    print(f"  {len(prices)} tickers, XBI dates: {len(xbi_prices)}")

    # Pre-sort per-ticker date lists (avoids repeated sort in forward_return)
    ticker_sorted: Dict[str, List[str]] = {}
    for t, p in prices.items():
        ticker_sorted[t] = sorted(p.keys())

    print("Loading IPO dates...")
    ipo_dates = _load_ipo_dates()
    print(f"  {len(ipo_dates)} tickers with IPO dates")

    all_dates = get_snapshot_dates(start)
    if monthly:
        eval_dates = dedupe_monthly(all_dates)
    else:
        eval_dates = all_dates
    print(f"Snapshots: {len(eval_dates)} ({eval_dates[0]} to {eval_dates[-1]})")

    panel_rows: List[Dict[str, Any]] = []
    col_presence: Dict[str, int] = defaultdict(int)

    for snap_i, snap_date in enumerate(eval_dates):
        if snap_i % 10 == 0:
            print(f"  Processing {snap_date} ({snap_i + 1}/{len(eval_dates)})...")

        rankings = load_rankings(snap_date, ipo_dates)
        if not rankings:
            continue

        # Determine available columns from this snapshot
        available_cols = set(rankings[0].keys()) if rankings else set()

        # XBI forward returns for regime labels
        xbi_rets: Dict[int, Optional[float]] = {}
        for h in HORIZONS:
            xbi_rets[h] = forward_return(xbi_prices, xbi_sorted, snap_date, h)

        # Eligible universe forward returns (for excess vs eligible EW)
        eligible_tickers = []
        for r in rankings:
            rank_val = _sf(r.get("actionable_rank"))
            is_elig = _sb(r.get("eligible"))
            if is_elig:
                eligible_tickers.append(r.get("ticker", ""))

        # Compute eligible EW returns per horizon
        eligible_ew: Dict[int, Optional[float]] = {}
        for h in HORIZONS:
            rets = []
            for t in eligible_tickers:
                if t in prices and t in ticker_sorted:
                    ret = forward_return(prices[t], ticker_sorted[t], snap_date, h)
                    if ret is not None:
                        rets.append(ret)
            eligible_ew[h] = (sum(rets) / len(rets)) if rets else None

        # Build one row per ticker
        for r in rankings:
            ticker = r.get("ticker", "")
            if not ticker:
                continue

            rank_val = _sf(r.get("actionable_rank"))
            is_eligible = _sb(r.get("eligible"))

            row: Dict[str, Any] = {
                "snapshot_date": snap_date,
                "ticker": ticker,
                "company_name": r.get("company_name", ""),
                "actionable_rank": rank_val,
                "eligible": is_eligible,
            }

            # ── Top-K membership labels ──
            for n in TOP_NS:
                row[f"in_top_{n}"] = not math.isnan(rank_val) and rank_val <= n and is_eligible

            # ── Forward returns ──
            t_prices = prices.get(ticker, {})
            t_sorted = ticker_sorted.get(ticker, [])
            for h in HORIZONS:
                ret = forward_return(t_prices, t_sorted, snap_date, h) if t_sorted else None
                row[f"fwd_ret_{h}d"] = ret

                # Excess vs XBI
                xbi_r = xbi_rets.get(h)
                if ret is not None and xbi_r is not None:
                    row[f"fwd_excess_xbi_{h}d"] = ret - xbi_r
                else:
                    row[f"fwd_excess_xbi_{h}d"] = None

                # Excess vs eligible EW
                elig_r = eligible_ew.get(h)
                if ret is not None and elig_r is not None:
                    row[f"fwd_excess_elig_{h}d"] = ret - elig_r
                else:
                    row[f"fwd_excess_elig_{h}d"] = None

            # ── Regime labels ──
            xbi_20 = xbi_rets.get(20)
            xbi_63 = xbi_rets.get(63)
            if xbi_63 is not None:
                if xbi_63 < -0.02:
                    row["regime_63d"] = "bear"
                elif xbi_63 > 0.02:
                    row["regime_63d"] = "bull"
                else:
                    row["regime_63d"] = "neutral"
            else:
                row["regime_63d"] = None

            if xbi_20 is not None:
                if xbi_20 < -0.02:
                    row["regime_20d"] = "bear"
                elif xbi_20 > 0.02:
                    row["regime_20d"] = "bull"
                else:
                    row["regime_20d"] = "neutral"
            else:
                row["regime_20d"] = None

            # ── XBI returns (for reference) ──
            for h in HORIZONS:
                row[f"xbi_ret_{h}d"] = xbi_rets.get(h)
            row["eligible_ew_ret_20d"] = eligible_ew.get(20)
            row["eligible_ew_ret_63d"] = eligible_ew.get(63)

            # ── All signal columns from rankings.csv ──
            for col in ALL_SIGNAL_COLUMNS:
                if col in available_cols:
                    raw = r.get(col, "")
                    # Try numeric first; keep string if not numeric
                    fv = _sf(raw, default=None)
                    if fv is not None:
                        row[col] = fv
                    else:
                        row[col] = raw if raw != "" else None
                    col_presence[col] += 1
                else:
                    row[col] = None

            # Also grab any columns from rankings.csv not in the taxonomy
            # (so the panel is exhaustive)
            for col in available_cols:
                if col not in row and col not in ("ticker", "company_name", "actionable_rank", "eligible"):
                    raw = r.get(col, "")
                    fv = _sf(raw, default=None)
                    if fv is not None:
                        row[col] = fv
                    else:
                        row[col] = raw if raw != "" else None

            panel_rows.append(row)

    print(f"Panel: {len(panel_rows)} rows across {len(eval_dates)} snapshots")
    return panel_rows


def forward_fill_quarterly_signals(
    panel_rows: List[Dict[str, Any]],
    signals: List[str] = ("inst_delta_z",),
    max_stale_months: int = 3,
) -> int:
    """Forward-fill quarterly signals (e.g. inst_delta_z from 13F filings).

    For each ticker, carry forward the most recent non-zero value into
    subsequent snapshots where the signal is zero/missing. PIT-safe:
    only uses values from earlier snapshot dates.

    Args:
        panel_rows: panel rows sorted by (snapshot_date, ticker)
        signals: column names to forward-fill
        max_stale_months: maximum months to carry forward (default 3 = one quarter)

    Returns:
        Number of values filled.
    """
    from datetime import date

    # Group by ticker, sorted by date
    by_ticker: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in panel_rows:
        by_ticker[row.get("ticker", "")].append(row)

    n_filled = 0
    for ticker, rows in by_ticker.items():
        rows.sort(key=lambda r: r.get("snapshot_date", ""))
        for sig in signals:
            last_nonzero_val = None
            last_nonzero_date = None
            for row in rows:
                snap_date = row.get("snapshot_date", "")
                val = row.get(sig)
                # Check if this row has a real (non-zero) value
                try:
                    fv = float(val) if val is not None else 0.0
                except (ValueError, TypeError):
                    fv = 0.0
                if abs(fv) > 1e-9:
                    last_nonzero_val = fv
                    last_nonzero_date = snap_date
                elif last_nonzero_val is not None and last_nonzero_date:
                    # Fill if within staleness window
                    try:
                        d_now = date.fromisoformat(snap_date)
                        d_last = date.fromisoformat(last_nonzero_date)
                        months_stale = (d_now.year - d_last.year) * 12 + (d_now.month - d_last.month)
                        if months_stale <= max_stale_months:
                            row[sig] = last_nonzero_val
                            n_filled += 1
                    except (ValueError, TypeError):
                        pass

    return n_filled


def compute_coverage(panel_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute per-column coverage statistics."""
    if not panel_rows:
        return {}

    role_map = _build_role_map()
    n_total = len(panel_rows)
    coverage: Dict[str, Dict[str, Any]] = {}

    # Collect all numeric-ish signal columns
    test_cols = set(ALL_SIGNAL_COLUMNS)
    for row in panel_rows[:1]:
        for k in row:
            if k.startswith("fwd_") or k.startswith("regime_") or k.startswith("xbi_"):
                continue
            if k in ("snapshot_date", "ticker", "company_name"):
                continue
            test_cols.add(k)

    for col in sorted(test_cols):
        n_present = 0
        n_numeric = 0
        n_nonzero = 0
        for row in panel_rows:
            v = row.get(col)
            if v is not None and v != "":
                n_present += 1
                try:
                    fv = float(v)
                    if not math.isnan(fv):
                        n_numeric += 1
                        if fv != 0.0:
                            n_nonzero += 1
                except (ValueError, TypeError):
                    pass  # categorical — still "present"

        coverage[col] = {
            "role": role_map.get(col, "other"),
            "n_present": n_present,
            "n_numeric": n_numeric,
            "n_nonzero": n_nonzero,
            "coverage_pct": round(n_present / n_total * 100, 1) if n_total else 0,
            "numeric_pct": round(n_numeric / n_total * 100, 1) if n_total else 0,
            "nonzero_pct": round(n_nonzero / n_total * 100, 1) if n_total else 0,
        }

    return coverage


def write_outputs(
    panel_rows: List[Dict[str, Any]],
    coverage: Dict[str, Any],
    use_parquet: bool = True,
) -> None:
    """Write panel + metadata."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Coverage metadata
    n_snapshots = len(set(r["snapshot_date"] for r in panel_rows))
    n_tickers = len(set(r["ticker"] for r in panel_rows))
    date_range = sorted(set(r["snapshot_date"] for r in panel_rows))

    meta = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_rows": len(panel_rows),
        "n_snapshots": n_snapshots,
        "n_tickers": n_tickers,
        "date_range": [date_range[0], date_range[-1]] if date_range else [],
        "horizons": HORIZONS,
        "top_ns": TOP_NS,
        "snapshot_dir": str(SNAPSHOTS_DIR),
        "role_summary": {},
        "column_coverage": coverage,
    }

    # Role summary
    role_counts: Dict[str, int] = defaultdict(int)
    for col, info in coverage.items():
        role_counts[info["role"]] += 1
    meta["role_summary"] = dict(role_counts)

    meta_path = OUTPUT_DIR / "research_panel_meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2, default=str)
    print(f"Metadata: {meta_path}")

    # Panel output
    if use_parquet:
        try:
            import pandas as pd

            df = pd.DataFrame(panel_rows)
            parquet_path = OUTPUT_DIR / "research_panel.parquet"
            df.to_parquet(parquet_path, index=False)
            print(f"Parquet: {parquet_path} ({len(df)} rows × {len(df.columns)} cols)")
        except ImportError:
            print("WARNING: pandas not available, falling back to CSV")
            use_parquet = False

    # Always write CSV as well (easier to inspect)
    csv_path = OUTPUT_DIR / "research_panel.csv"
    if panel_rows:
        # Use consistent column ordering
        all_cols = list(panel_rows[0].keys())
        # Ensure any extra columns from later snapshots are included
        all_col_set = set(all_cols)
        for row in panel_rows:
            for k in row:
                if k not in all_col_set:
                    all_cols.append(k)
                    all_col_set.add(k)

        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
            writer.writeheader()
            for row in panel_rows:
                writer.writerow(row)
        print(f"CSV: {csv_path}")

    # Coverage report (quick human-readable)
    report_path = OUTPUT_DIR / "research_panel_coverage.md"
    lines = [
        "# Signal Research Panel — Coverage Report\n",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n",
        f"Rows: {len(panel_rows):,} | Snapshots: {n_snapshots} | Tickers: {n_tickers}\n",
        f"Date range: {date_range[0]} to {date_range[-1]}\n" if date_range else "",
        "",
        "## Coverage by role\n",
        "| Role | Column | Coverage % | Numeric % | Nonzero % |",
        "|------|--------|-----------|-----------|-----------|",
    ]
    role_order = ["gate", "selector", "ranker", "modifier", "composite", "other"]
    for role in role_order:
        role_cols = [(col, info) for col, info in sorted(coverage.items()) if info["role"] == role]
        if not role_cols:
            continue
        for col, info in role_cols:
            lines.append(
                f"| {role} | `{col}` | {info['coverage_pct']}% " f"| {info['numeric_pct']}% | {info['nonzero_pct']}% |"
            )
    lines.append("")

    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Coverage report: {report_path}")


def main():
    parser = argparse.ArgumentParser(description="Build signal research panel (Spec 049)")
    parser.add_argument("--start", default="2020-06-01", help="Start date")
    parser.add_argument("--no-parquet", action="store_true", help="Skip parquet output")
    parser.add_argument("--all-dates", action="store_true", help="Use all snapshots, not monthly")
    args = parser.parse_args()

    panel_rows = build_panel(
        start=args.start,
        monthly=not args.all_dates,
    )

    if not panel_rows:
        print("ERROR: No panel rows generated")
        sys.exit(1)

    # Forward-fill quarterly signals (inst_delta_z from 13F filings)
    print("\nForward-filling quarterly signals...")
    n_filled = forward_fill_quarterly_signals(panel_rows, signals=["inst_delta_z"])
    print(f"  inst_delta_z: {n_filled} values forward-filled (max 3 months)")

    print("\nComputing coverage...")
    coverage = compute_coverage(panel_rows)

    print("\nWriting outputs...")
    write_outputs(panel_rows, coverage, use_parquet=not args.no_parquet)

    # Quick summary
    n_snapshots = len(set(r["snapshot_date"] for r in panel_rows))
    n_tickers = len(set(r["ticker"] for r in panel_rows))
    n_eligible = sum(1 for r in panel_rows if r.get("eligible"))
    n_top20 = sum(1 for r in panel_rows if r.get("in_top_20"))
    n_top30 = sum(1 for r in panel_rows if r.get("in_top_30"))

    # Forward return coverage
    fwd_20_n = sum(1 for r in panel_rows if r.get("fwd_ret_20d") is not None)
    fwd_63_n = sum(1 for r in panel_rows if r.get("fwd_ret_63d") is not None)

    print(f"\n{'='*60}")
    print("PANEL SUMMARY")
    print(f"{'='*60}")
    print(f"  Rows:          {len(panel_rows):>8,}")
    print(f"  Snapshots:     {n_snapshots:>8}")
    print(f"  Tickers:       {n_tickers:>8}")
    print(f"  Eligible:      {n_eligible:>8,}")
    print(f"  In top-20:     {n_top20:>8,}")
    print(f"  In top-30:     {n_top30:>8,}")
    print(f"  Fwd ret 20d:   {fwd_20_n:>8,} ({fwd_20_n/len(panel_rows)*100:.1f}%)")
    print(f"  Fwd ret 63d:   {fwd_63_n:>8,} ({fwd_63_n/len(panel_rows)*100:.1f}%)")

    # Key signal coverage
    key_signals = [
        "clinical_score_v2_z",
        "catalyst_days",
        "inst_delta_z",
        "opt_atm_iv",
        "actual_implied_move_pctile",
        "aact_execution_score",
    ]
    print("\n  Key signal coverage:")
    for sig in key_signals:
        info = coverage.get(sig)
        if info:
            print(f"    {sig:40s} {info['coverage_pct']:>6.1f}%  (nonzero: {info['nonzero_pct']:.1f}%)")
        else:
            print(f"    {sig:40s}   N/A")

    print("\nDone.")


if __name__ == "__main__":
    main()

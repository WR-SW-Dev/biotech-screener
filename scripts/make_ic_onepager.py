#!/usr/bin/env python3
"""IC One-Pager Generator — assembles a single Markdown summary from snapshot artifacts.

Reads phase2_health.json, decision_portfolio.csv, rankings.csv,
phase2_run_delta_details.json, and catalyst_source_mix.json from a snapshot
directory and produces ``ic_onepager.md`` alongside them.

Usage:
    python scripts/make_ic_onepager.py --snapshot-dir data/snapshots/2026-02-16
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> Optional[dict]:
    """Return parsed JSON or None if file missing / malformed."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _load_csv_rows(path: Path) -> Optional[List[dict]]:
    """Return list-of-dicts from CSV or None if missing."""
    try:
        with open(path, "r") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return None


def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val, default: int = 0) -> int:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def _fmt_pct(val, decimals: int = 1) -> str:
    return f"{_safe_float(val):.{decimals}f}%"


_NOT_AVAILABLE = "*Not available (file missing)*"


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _health_section(health_data: Optional[dict]) -> str:
    """## Health Gate"""
    if health_data is None:
        return f"## Health Gate\n{_NOT_AVAILABLE}\n"

    status = health_data.get("status", "UNKNOWN")
    metrics = health_data.get("metrics", {})

    a_count = metrics.get("a_count", "?")
    cat_cov = _fmt_pct(metrics.get("catalyst_coverage_pct", 0))
    turnover = _fmt_pct(metrics.get("name_turnover_pct", 0))
    weight_l1 = _fmt_pct(metrics.get("weight_l1_delta", 0))

    lines = [
        f"## Health Gate: {status}",
        f"A-tier: {a_count} | Catalyst coverage: {cat_cov}" f" | Turnover: {turnover} | Weight L1: {weight_l1}",
    ]

    reasons = health_data.get("reasons", [])
    if reasons:
        lines.append(f"Reasons: {', '.join(reasons)}")

    return "\n".join(lines) + "\n"


def _portfolio_section(
    portfolio_rows: Optional[List[dict]],
    rankings_rows: Optional[List[dict]],
) -> str:
    """## Portfolio table with explainability column."""
    if portfolio_rows is None:
        return f"## Portfolio\n{_NOT_AVAILABLE}\n"

    # Build lookup: ticker -> top_3_drivers first entry
    driver_map: Dict[str, str] = {}
    if rankings_rows:
        for row in rankings_rows:
            t3 = row.get("top_3_drivers", "")
            if t3:
                # e.g. "clinical_score:+22.0;financial_score:+17.4;..."
                first = t3.split(";")[0] if t3 else ""
                driver_map[row.get("ticker", "")] = first

    # Check if any non-dev names are in portfolio
    has_commercial = any(r.get("archetype", "") != "drug_developer" for r in portfolio_rows)

    n = len(portfolio_rows)
    if has_commercial:
        lines = [
            f"## Portfolio ({n} positions)",
            "| # | Ticker | Arch | Tier | Wt% | Cat Days | Strength | Mom | Risk | Top Driver |",
            "|---|--------|------|------|-----|----------|----------|-----|------|------------|",
        ]
    else:
        lines = [
            f"## Portfolio ({n} positions)",
            "| # | Ticker | Tier | Wt% | Cat Days | Strength | Mom | Risk | Top Driver |",
            "|---|--------|------|-----|----------|----------|-----|------|------------|",
        ]

    for row in portfolio_rows:
        rank = row.get("actionable_rank", "")
        ticker = row.get("ticker", "")
        tier = row.get("tier_any", "") or row.get("tier_dev", "")
        wt = _fmt_pct(row.get("target_weight_pct", 0))
        cat_days = row.get("catalyst_days", "")
        strength = row.get("catalyst_strength", row.get("catalyst_mode", ""))
        mom = row.get("mom_state", "")
        risk = row.get("risk_flags", "")
        driver = driver_map.get(ticker, "")
        if has_commercial:
            is_dev = row.get("archetype", "") == "drug_developer"
            arch_label = "D" if is_dev else "C"
            lines.append(
                f"| {rank} | {ticker} | {arch_label} | {tier} | {wt} | {cat_days} "
                f"| {strength} | {mom} | {risk} | {driver} |"
            )
        else:
            lines.append(
                f"| {rank} | {ticker} | {tier} | {wt} | {cat_days} " f"| {strength} | {mom} | {risk} | {driver} |"
            )

    return "\n".join(lines) + "\n"


def _delta_section(delta_data: Optional[dict]) -> str:
    """## Delta vs Prior."""
    if delta_data is None:
        return f"## Delta vs Prior\n{_NOT_AVAILABLE}\n"

    prior = delta_data.get("prior") or {}
    prior_date = prior.get("date", "?")
    pt = delta_data.get("portfolio_turnover", {})
    turnover = _fmt_pct(pt.get("name_turnover_pct", 0))
    weight_l1 = _fmt_pct(pt.get("weight_l1_delta", 0))
    entrants = pt.get("entrants", [])
    exits = pt.get("exits", [])

    lines = [
        f"## Delta vs Prior ({prior_date})",
        f"Turnover: {turnover} | Weight L1: {weight_l1}",
    ]

    ent_str = ", ".join(entrants) if entrants else "none"
    exit_str = ", ".join(exits) if exits else "none"
    lines.append(f"Entrants: {ent_str}  ")
    lines.append(f"Exits: {exit_str}")

    return "\n".join(lines) + "\n"


def _catalyst_section(
    delta_data: Optional[dict],
    source_mix: Optional[dict],
) -> str:
    """## Catalyst Coverage."""
    lines = ["## Catalyst Coverage"]

    has_content = False

    # Coverage from delta
    if delta_data:
        cat_cov = delta_data.get("catalyst_coverage", {}).get("current", {})
        n_dev = cat_cov.get("n_dev", 0)
        n_specific = cat_cov.get("n_specific", 0)
        pct = _fmt_pct(cat_cov.get("pct", 0))
        lines.append(f"Dev specific_days: {n_specific}/{n_dev} ({pct})")

        # Nearest catalysts
        top_cats = delta_data.get("top_catalysts", {}).get("current", [])
        if top_cats:
            nearest = top_cats[:5]
            parts = [f"{c['ticker']} ({c['catalyst_days']}d, {c.get('tier_dev', '?')})" for c in nearest]
            lines.append(f"Nearest 5: {', '.join(parts)}")
        has_content = True

    # Source mix
    if source_mix:
        by_src = source_mix.get("by_source", {})
        total = source_mix.get("total_events", 0)
        src_parts = [f"{k}={v}" for k, v in sorted(by_src.items())]
        lines.append(f"Sources ({total} total): {', '.join(src_parts)}")
        has_content = True

    if not has_content:
        lines.append(_NOT_AVAILABLE)

    return "\n".join(lines) + "\n"


def _tier_section(
    rankings_rows: Optional[List[dict]],
    portfolio_rows: Optional[List[dict]],
) -> str:
    """## Tier Distribution table (universe + portfolio)."""
    if rankings_rows is None:
        return f"## Tier Distribution\n{_NOT_AVAILABLE}\n"

    # Check if tier_any column exists (commercial tier feature)
    has_tier_any = any(row.get("tier_any", "") for row in rankings_rows)

    # Count tiers in universe using tier_any (falls back to tier_dev)
    tier_order = ["A", "B", "C", "D"]
    uni_dev: Dict[str, int] = {t: 0 for t in tier_order}
    uni_comm: Dict[str, int] = {t: 0 for t in tier_order}
    for row in rankings_rows:
        td = row.get("tier_dev", "")
        if td in uni_dev:
            uni_dev[td] += 1
        tc = row.get("tier_commercial", "")
        if tc in uni_comm:
            uni_comm[tc] += 1

    port_counts: Dict[str, int] = {t: 0 for t in tier_order}
    if portfolio_rows:
        for row in portfolio_rows:
            ta = row.get("tier_any", "") or row.get("tier_dev", "")
            if ta in port_counts:
                port_counts[ta] += 1

    if has_tier_any and any(uni_comm[t] > 0 for t in tier_order):
        lines = [
            "## Tier Distribution",
            "| Tier | Dev | Comm | Portfolio |",
            "|------|-----|------|-----------|",
        ]
        for t in tier_order:
            lines.append(f"| {t} | {uni_dev[t]} | {uni_comm[t]} | {port_counts[t]} |")
    else:
        lines = [
            "## Tier Distribution",
            "| Tier | Universe | Portfolio |",
            "|------|----------|-----------|",
        ]
        for t in tier_order:
            lines.append(f"| {t} | {uni_dev[t]} | {port_counts[t]} |")

    return "\n".join(lines) + "\n"


def _exceptions_section(
    rankings_rows: Optional[List[dict]],
    portfolio_rows: Optional[List[dict]],
    health_data: Optional[dict],
) -> str:
    """## Exceptions — ineligible tickers, risk flags, health warnings."""
    lines = ["## Exceptions"]

    # Ineligible count + reasons
    if rankings_rows:
        ineligible = [
            r for r in rankings_rows if str(r.get("eligible", "1")).strip().lower() not in ("1", "1.0", "true", "yes")
        ]
        if ineligible:
            reason_counts: Dict[str, int] = {}
            for r in ineligible:
                reason = r.get("ineligible_reasons", "unknown") or "unknown"
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            top_reasons = sorted(reason_counts.items(), key=lambda x: -x[1])[:3]
            reason_str = ", ".join(f"{k} ({v})" for k, v in top_reasons)
            lines.append(f"Ineligible: {len(ineligible)} ({reason_str})")
        else:
            lines.append("Ineligible: 0")
    else:
        lines.append(f"Ineligible: {_NOT_AVAILABLE}")

    # Risk flags in portfolio
    if portfolio_rows:
        risk_count = 0
        risk_details: List[str] = []
        for r in portfolio_rows:
            rf = r.get("risk_flags", "")
            if rf and rf.strip():
                risk_count += 1
                risk_details.append(f"{r.get('ticker', '?')}: {rf}")
        if risk_count:
            lines.append(f"Risk flags in portfolio: {risk_count}" f" ({'; '.join(risk_details)})")
        else:
            lines.append("Risk flags in portfolio: 0")
    else:
        lines.append("Risk flags in portfolio: N/A")

    # Missing data in portfolio (join from rankings)
    if rankings_rows and portfolio_rows:
        port_tickers = {r.get("ticker") for r in portfolio_rows}
        port_rankings = [r for r in rankings_rows if r.get("ticker") in port_tickers]
        mc_count = sum(1 for r in port_rankings if r.get("missing_components", "").strip())
        if mc_count:
            comp_counts: Dict[str, int] = {}
            for r in port_rankings:
                mc = r.get("missing_components", "")
                for c in mc.split("|"):
                    if c.strip():
                        comp_counts[c.strip()] = comp_counts.get(c.strip(), 0) + 1
            parts = [f"{k}: {v}" for k, v in sorted(comp_counts.items())]
            lines.append(f"Missing data in portfolio: {mc_count}/{len(port_rankings)} ({', '.join(parts)})")
        else:
            lines.append("Missing data in portfolio: 0")

    # Dev coverage from health metrics
    if health_data:
        hmetrics = health_data.get("metrics", {})
        cov_parts = []
        for comp in ("catalyst", "sponsor", "drawdown"):
            key = f"coverage_{comp}_pct"
            if key in hmetrics:
                cov_parts.append(f"{comp}: {hmetrics[key]}%")
        if cov_parts:
            lines.append(f"Dev coverage: {', '.join(cov_parts)}")

    # Health warnings
    if health_data:
        reasons = health_data.get("reasons", [])
        if reasons:
            lines.append(f"Health warnings: {', '.join(reasons)}")
        else:
            lines.append("Health warnings: none")
    else:
        lines.append("Health warnings: N/A")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Regime decomposition — first-class bear/bull reporting
# ---------------------------------------------------------------------------


def _regime_section(snap_dir: Path) -> str:
    """## Regime Performance — bear/bull/neutral decomposition.

    Reads shadow performance CSV and computes cumulative excess by regime.
    This is the "truth-in-advertising" section: if the strategy is primarily
    a bear-regime alpha source, that must be visible at a glance.
    """
    perf_csv = PROJECT_ROOT / "artifacts" / "live_shadow" / "performance.csv"
    if not perf_csv.exists():
        return "## Regime Performance\n*Shadow performance data not available.*\n"

    rows = _load_csv_rows(perf_csv)
    if not rows:
        return "## Regime Performance\n*No performance rows.*\n"

    # Classify each row by XBI regime (trailing 63d XBI return)
    # Accumulate per-regime
    regime_data: Dict[str, List[float]] = {"bear": [], "neutral": [], "bull": []}
    cum_excess = 0.0
    cum_bear = 0.0
    cum_bull = 0.0
    cum_neutral = 0.0

    for row in rows:
        xbi_pct = _safe_float(row.get("xbi_return_pct"), 0)
        excess = _safe_float(row.get("excess_vs_xbi_pct"), 0)

        # Simple regime: based on XBI daily return
        if xbi_pct < -1.0:
            regime = "bear"
            cum_bear += excess
        elif xbi_pct > 1.0:
            regime = "bull"
            cum_bull += excess
        else:
            regime = "neutral"
            cum_neutral += excess
        cum_excess += excess
        regime_data[regime].append(excess)

    n_bear = len(regime_data["bear"])
    n_bull = len(regime_data["bull"])
    n_neutral = len(regime_data["neutral"])
    n_total = n_bear + n_bull + n_neutral

    def _mean(vals: List[float]) -> str:
        if not vals:
            return "—"
        return f"{sum(vals) / len(vals):+.2f}%"

    lines = [
        "## Regime Performance",
        "",
        "| Regime | Days | Mean Excess | Cum Excess | Share |",
        "|--------|------|-------------|------------|-------|",
        f"| **All** | {n_total} | {_mean(regime_data['bear'] + regime_data['bull'] + regime_data['neutral'])} | {cum_excess:+.1f}% | 100% |",
        f"| Bear (XBI<-1%) | {n_bear} | {_mean(regime_data['bear'])} | {cum_bear:+.1f}% | {n_bear / max(n_total, 1) * 100:.0f}% |",
        f"| Neutral | {n_neutral} | {_mean(regime_data['neutral'])} | {cum_neutral:+.1f}% | {n_neutral / max(n_total, 1) * 100:.0f}% |",
        f"| Bull (XBI>+1%) | {n_bull} | {_mean(regime_data['bull'])} | {cum_bull:+.1f}% | {n_bull / max(n_total, 1) * 100:.0f}% |",
        "",
    ]

    # Flag if bear-dominated
    if n_bear > 0 and cum_bear > 0 and cum_bull < 0:
        lines.append(
            "> **Bear-regime alpha source**: cumulative excess is positive in bear "
            "markets and negative in bull markets. The strategy harvests biotech "
            "stress, not broad stock selection."
        )
    elif n_bear > 0 and cum_bear > 0 and cum_bull > 0:
        lines.append("> Alpha positive across regimes.")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Factor exposure monitoring
# ---------------------------------------------------------------------------


def _factor_exposure_section(
    rankings_rows: Optional[List[dict]],
    portfolio_rows: Optional[List[dict]],
) -> str:
    """## Factor Exposures — size, beta, momentum, liquidity.

    Compares portfolio vs universe median to surface unintended factor bets.
    Monitoring only — no neutralization.
    """
    if not rankings_rows or not portfolio_rows:
        return "## Factor Exposures\n*Data not available.*\n"

    port_tickers = {r.get("ticker", "") for r in portfolio_rows}

    def _extract(rows: List[dict], field: str) -> List[float]:
        vals = []
        for r in rows:
            v = _safe_float(r.get(field), None)
            if v is not None:
                vals.append(v)
        return vals

    def _median(vals: List[float]) -> Optional[float]:
        if not vals:
            return None
        s = sorted(vals)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    def _mean_vals(vals: List[float]) -> Optional[float]:
        return sum(vals) / len(vals) if vals else None

    # Compute for portfolio vs universe

    # Use numeric fields from rankings
    port_rows = [r for r in rankings_rows if r.get("ticker", "") in port_tickers]
    univ_rows = [r for r in rankings_rows if str(r.get("eligible", "")).strip().lower() in ("1", "1.0", "true", "yes")]

    lines = [
        "## Factor Exposures (portfolio vs universe)",
        "",
        "| Factor | Portfolio Mean | Universe Mean | Tilt |",
        "|--------|---------------|---------------|------|",
    ]

    for label, field, _ in [
        ("Beta XBI 60d", "de_beta_xbi_60d", None),
        ("Volatility 60d", "de_vol_60d", None),
        ("Drawdown", "de_drawdown", None),
        ("RSI 14d", "de_rsi_14d", None),
    ]:
        port_vals = _extract(port_rows, field)
        univ_vals = _extract(univ_rows, field)
        p_mean = _mean_vals(port_vals)
        u_mean = _mean_vals(univ_vals)
        if p_mean is not None and u_mean is not None and u_mean != 0:
            tilt = (p_mean - u_mean) / abs(u_mean)
            tilt_str = f"{tilt:+.1%}"
        else:
            tilt_str = "—"
        p_str = f"{p_mean:.3f}" if p_mean is not None else "—"
        u_str = f"{u_mean:.3f}" if u_mean is not None else "—"
        lines.append(f"| {label} | {p_str} | {u_str} | {tilt_str} |")

    # Momentum state distribution
    port_moms = [r.get("mom_state", "") for r in port_rows]
    univ_moms = [r.get("mom_state", "") for r in univ_rows]
    lines.append("")
    lines.append("**Momentum distribution** (portfolio / universe):")
    for state in ["tailwind", "neutral", "headwind"]:
        p_pct = port_moms.count(state) / max(len(port_moms), 1) * 100
        u_pct = univ_moms.count(state) / max(len(univ_moms), 1) * 100
        lines.append(f"  - {state}: {p_pct:.0f}% / {u_pct:.0f}%")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Factor drift alerts
# ---------------------------------------------------------------------------


def _factor_drift_section(snap_dir: Path) -> str:
    """## Factor Drift — alerts from the two-baseline drift monitor."""
    date_str = snap_dir.name
    drift_path = PROJECT_ROOT / "artifacts" / "factor_drift" / f"{date_str}_factor_drift.json"
    drift_data = _load_json(drift_path)

    if drift_data is None:
        return "## Factor Drift\n*No drift artifact for this date.*\n"

    alerts = drift_data.get("alerts", [])
    attention = drift_data.get("attention", "GREEN")

    lines = [f"## Factor Drift: {attention}"]

    if not alerts:
        lines.append("All metrics within thresholds.")
    else:
        for a in alerts:
            lines.append(f"- **{a['level']}** [{a['code']}]: {a['detail']}")

    # Key metrics summary
    jaccard = drift_data.get("jaccard_prev")
    hhi = drift_data.get("hhi")
    univ_size = drift_data.get("universe_size")
    lines.append("")
    parts = []
    if jaccard is not None:
        parts.append(f"Jaccard={jaccard:.2f}")
    if hhi is not None:
        parts.append(f"HHI={hhi:.0f}")
    if univ_size is not None:
        parts.append(f"Eligible={univ_size}")
    if parts:
        lines.append(f"Metrics: {' | '.join(parts)}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main assembler
# ---------------------------------------------------------------------------


def generate_ic_onepager(snap_dir: Path) -> str:
    """Return IC one-pager markdown from a snapshot directory.

    Never raises — partial output is better than no output.
    """
    date_str = snap_dir.name

    health_data = _load_json(snap_dir / "phase2_health.json")
    delta_data = _load_json(snap_dir / "phase2_run_delta_details.json")
    source_mix = _load_json(snap_dir / "catalyst_source_mix.json")
    portfolio_rows = _load_csv_rows(snap_dir / "decision_portfolio.csv")
    rankings_rows = _load_csv_rows(snap_dir / "rankings.csv")

    sections = [
        f"# IC Run Summary — {date_str}",
        "",
        _health_section(health_data),
        _regime_section(snap_dir),
        _factor_drift_section(snap_dir),
        _factor_exposure_section(rankings_rows, portfolio_rows),
        _portfolio_section(portfolio_rows, rankings_rows),
        _delta_section(delta_data),
        _catalyst_section(delta_data, source_mix),
        _tier_section(rankings_rows, portfolio_rows),
        _exceptions_section(rankings_rows, portfolio_rows, health_data),
    ]

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate IC one-pager from a snapshot directory.")
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        required=True,
        help="Path to snapshot directory (e.g. data/snapshots/2026-02-16)",
    )
    args = parser.parse_args()

    snap_dir = args.snapshot_dir.resolve()
    if not snap_dir.is_dir():
        print(f"ERROR: {snap_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    md = generate_ic_onepager(snap_dir)
    out_path = snap_dir / "ic_onepager.md"
    out_path.write_text(md, encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()

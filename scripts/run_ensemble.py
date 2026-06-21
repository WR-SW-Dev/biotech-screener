#!/usr/bin/env python
"""Reusable multi-agent ensemble runner — combines fundamental, clinical, and
optimized score signals into a unified investment report.

Replaces the ad-hoc 3-subagent approach with a single deterministic script that
can be run on demand or via cron. Produces a markdown report at
output/ensemble_report_YYYY-MM-DD.md.

Usage:
    python scripts/run_ensemble.py
    python scripts/run_ensemble.py --snapshot 2024-04-01
    python scripts/run_ensemble.py --top 15
    python scripts/run_ensemble.py --output output/my_report.md
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(os.environ.get(
    "BIOTECH_PROJECT_DIR",
    Path(__file__).resolve().parent.parent,
))
DATA_DIR = PROJECT_DIR / "data"
OUTPUT_DIR = PROJECT_DIR / "output"
PRICES_FILE = DATA_DIR / "daily_prices.csv"
TRIAL_MAP_FILE = DATA_DIR / "trial_mapping.csv"
AACT_DIR = DATA_DIR / "aact_snapshots"

# Therapeutic area mapping (domain knowledge — AACT CSVs lack condition field)
THERAPEUTIC_AREA: dict[str, str] = {
    "MRNA": "Infectious Disease", "BNTX": "Infectious Disease",
    "VRTX": "Rare Disease", "REGN": "Immunology",
    "BIIB": "Neurology", "ALNY": "Rare Disease",
    "BMRN": "Rare Disease", "INCY": "Oncology",
    "EXEL": "Oncology", "AMGN": "Oncology",
    "SGEN": "Oncology", "ACAD": "Neurology",
    "ARWR": "Rare Disease", "BEAM": "Rare Disease",
    "BLUE": "Rare Disease", "EDIT": "Rare Disease",
    "HALO": "Oncology",          # Halozyme — enzyme replacement, oncology adjunct
    "FOLD": "Rare Disease",      # Amicus Therapeutics — lysosomal storage disorders
    "RARE": "Rare Disease",      # Ultragenyx — rare and ultra-rare diseases
    "IMVT": "Immunology",        # Immunovant — autoimmune FcRn inhibitors
}

PHASE_RANK: dict[str, int] = {
    "Phase 1": 1, "Phase 1/Phase 2": 2, "Phase 2": 3,
    "Phase 2/Phase 3": 4, "Phase 3": 5, "Phase 4": 6,
}
ACTIVE_STATUSES = {"Recruiting", "Active, not recruiting", "Not yet recruiting"}


# ═══════════════════════════════════════════════════════════════════
# Data loading
# ═══════════════════════════════════════════════════════════════════

def find_latest_snapshot() -> Path | None:
    """Find the latest snapshot JSON in output/."""
    candidates = sorted(OUTPUT_DIR.glob("snapshot_*.json"))
    # Prefer optimized snapshots, fall back to base
    optimized = [p for p in candidates if "optimized" in p.name]
    if optimized:
        return optimized[-1]
    if candidates:
        return candidates[-1]
    return None


def load_snapshot(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_prices() -> dict[str, list[tuple[str, float]]]:
    """Load daily prices: ticker -> [(date_str, price), ...] sorted by date."""
    prices: dict[str, list[tuple[str, float]]] = defaultdict(list)
    with open(PRICES_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticker = row.get("ticker", "").strip().upper()
            if ticker:
                prices[ticker].append((row["date"], float(row["adj_close"])))
    for t in prices:
        prices[t].sort(key=lambda x: x[0])
    return dict(prices)


def load_trial_mapping() -> dict[str, list[str]]:
    """ticker -> [nct_id, ...]"""
    mapping: dict[str, list[str]] = defaultdict(list)
    with open(TRIAL_MAP_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticker = row.get("ticker", "").upper().strip()
            nct = row.get("nct_id", "").strip()
            if ticker and nct:
                mapping[ticker].append(nct)
    return dict(mapping)


def load_aact_data() -> tuple[dict[str, dict], dict[str, list[str]]]:
    """Load latest AACT snapshot: (studies, sponsors)."""
    if not AACT_DIR.is_dir():
        return {}, {}
    subdirs = sorted(p for p in AACT_DIR.iterdir() if p.is_dir())
    if not subdirs:
        return {}, {}
    snap = subdirs[-1]

    studies: dict[str, dict] = {}
    studies_file = snap / "studies.csv"
    if studies_file.exists():
        with open(studies_file, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                nct = (row.get("nct_id") or "").strip()
                if nct:
                    studies[nct] = row

    sponsors: dict[str, list[str]] = defaultdict(list)
    sponsors_file = snap / "sponsors.csv"
    if sponsors_file.exists():
        with open(sponsors_file, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                nct = (row.get("nct_id") or "").strip()
                name = (row.get("name") or "").strip()
                if nct and name:
                    sponsors[nct].append(name)

    return studies, dict(sponsors)


# ═══════════════════════════════════════════════════════════════════
# Fundamental analysis (price-based)
# ═══════════════════════════════════════════════════════════════════

def compute_price_metrics(
    prices: list[tuple[str, float]],
    as_of: str,
) -> dict[str, float | None]:
    """Compute 6M momentum, annualized volatility, max drawdown as of a date."""
    pit = [(d, p) for d, p in prices if d <= as_of]
    if len(pit) < 20:
        return {"momentum_6m": None, "volatility": None, "max_drawdown": None, "n_days": len(pit)}

    px = [p for _, p in pit]
    n = len(px)

    # 6-month momentum (~126 trading days)
    lookback = min(126, n - 1)
    momentum = (px[-1] / px[-1 - lookback] - 1) * 100 if px[-1 - lookback] > 0 else 0.0

    # Annualized volatility (daily returns over full history)
    rets = []
    for i in range(1, n):
        if px[i - 1] > 0:
            rets.append(math.log(px[i] / px[i - 1]))
    vol = (math.sqrt(sum(r * r for r in rets) / max(len(rets), 1)) * math.sqrt(252)) * 100 if rets else 0.0

    # Max drawdown
    peak = px[0]
    max_dd = 0.0
    for p in px:
        if p > peak:
            peak = p
        dd = (peak - p) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    return {
        "momentum_6m": round(momentum, 2),
        "volatility": round(vol, 2),
        "max_drawdown": round(max_dd, 2),
        "n_days": n,
    }


def health_rating(vol: float | None, max_dd: float | None, momentum: float | None) -> str:
    """Rate financial health from price-based risk signals."""
    v = vol or 0
    d = max_dd or 0
    m = momentum if momentum is not None else 0
    if v > 55 or d > 60 or m < -30:
        return "Weak"
    if v < 35 and d < 40 and m >= 0:
        return "Strong"
    return "Moderate"


# ═══════════════════════════════════════════════════════════════════
# Clinical analysis (AACT-based)
# ═══════════════════════════════════════════════════════════════════

def parse_pcd(pcd_str: str) -> date | None:
    if not pcd_str:
        return None
    try:
        return date.fromisoformat(pcd_str[:10])
    except (ValueError, IndexError):
        return None


def grade_pipeline(
    lead_phase: str,
    active: int,
    catalysts: list[str],
    sponsor_div: int,
    lead_completed: bool,
) -> str:
    """A-F grading heuristic for pipeline quality."""
    score = 0
    pr = PHASE_RANK.get(lead_phase, 0)
    if pr >= 5:
        score += 3
    elif pr >= 3:
        score += 2
    elif pr >= 1:
        score += 1
    score += min(active, 2)
    score += min(len(catalysts), 2)
    if sponsor_div >= 2:
        score += 1
    if active == 0 and lead_completed:
        score -= 1
    if score >= 6:
        return "A"
    if score >= 5:
        return "B"
    if score >= 4:
        return "C"
    if score >= 3:
        return "D"
    return "F"


def analyze_clinical(
    ticker: str,
    ncts: list[str],
    studies: dict[str, dict],
    sponsors: dict[str, list[str]],
    snapshot_date: date,
) -> dict[str, Any]:
    """Analyze clinical pipeline for a single ticker."""
    phases: list[str] = []
    active_n = 0
    catalysts: list[str] = []
    all_sponsors: set[str] = set()
    lead_completed = False

    for nct in ncts:
        s = studies.get(nct)
        if not s:
            continue
        phases.append(s.get("phase", ""))
        if s.get("overall_status", "") in ACTIVE_STATUSES:
            active_n += 1
        pcd = parse_pcd(s.get("primary_completion_date", ""))
        if pcd and s.get("primary_completion_date_type") == "Anticipated" and pcd > snapshot_date:
            catalysts.append(f"{nct} ({pcd.isoformat()})")
        if s.get("overall_status", "") in ("Completed", "Terminated"):
            lead_completed = True
        for sp in sponsors.get(nct, []):
            all_sponsors.add(sp)

    lead_phase = max(phases, key=lambda p: PHASE_RANK.get(p, 0)) if phases else "N/A"
    grade = grade_pipeline(lead_phase, active_n, catalysts, len(all_sponsors), lead_completed)

    return {
        "lead_phase": lead_phase,
        "active_trials": active_n,
        "total_trials": len(ncts),
        "catalysts": catalysts,
        "sponsor_diversity": len(all_sponsors),
        "therapeutic_area": THERAPEUTIC_AREA.get(ticker, "Unknown"),
        "grade": grade,
    }


# ═══════════════════════════════════════════════════════════════════
# Ensemble merging
# ═══════════════════════════════════════════════════════════════════

def consensus_rating(health: str, grade: str, has_optimized: bool, composite_score: float | None) -> str:
    """Determine BUY/HOLD/AVOID consensus from multiple signals."""
    signals = []

    # Fundamental signal
    if health == "Strong":
        signals.append("buy")
    elif health == "Weak":
        signals.append("avoid")

    # Clinical signal
    if grade in ("A", "B"):
        signals.append("buy")
    elif grade in ("D", "F"):
        signals.append("avoid")
    else:
        signals.append("hold")

    # Score signal (if optimized snapshot available)
    if has_optimized and composite_score is not None:
        if composite_score >= 60:
            signals.append("buy")
        elif composite_score < 40:
            signals.append("avoid")
        else:
            signals.append("hold")

    if not signals:
        return "HOLD"

    buy_count = signals.count("buy")
    avoid_count = signals.count("avoid")

    if buy_count >= 2 and avoid_count == 0:
        return "BUY"
    if avoid_count >= 2 and buy_count == 0:
        return "AVOID"
    return "HOLD"


def run_ensemble(
    snapshot_path: Path,
    top_n: int = 10,
    output_path: Path | None = None,
) -> Path:
    """Run the full ensemble analysis and write a markdown report."""
    as_of_date = snapshot_path.stem.replace("snapshot_", "").replace("optimized_", "")
    try:
        snap_date = date.fromisoformat(as_of_date)
    except ValueError:
        snap_date = date.today()

    print(f"Loading snapshot: {snapshot_path.name} (as-of: {as_of_date})")
    snap = load_snapshot(snapshot_path)

    # Get ranked securities
    ranked = snap.get("ranked_securities") or snap.get("module_5_composite", {}).get("ranked_securities", [])
    if not ranked:
        raise ValueError(f"No ranked_securities found in {snapshot_path}")

    # Sort by composite score descending
    def get_score(r: dict) -> float:
        s = r.get("composite_score")
        if s is None:
            s = r.get("rank_score", 0)
        try:
            return float(s)
        except (TypeError, ValueError):
            return 0.0

    ranked_sorted = sorted(ranked, key=lambda r: (-get_score(r), r.get("composite_rank", 9999)))
    top = ranked_sorted[:top_n]
    tickers = [c.get("ticker", "") for c in top]

    print(f"Top {len(tickers)} tickers: {', '.join(tickers)}")

    # Load supporting data
    print("Loading price data...")
    prices = load_prices()
    print("Loading trial mapping...")
    trial_map = load_trial_mapping()
    print("Loading AACT data...")
    studies, sponsors = load_aact_data()

    is_optimized = "optimized" in snapshot_path.name

    # Analyze each ticker
    results: list[dict[str, Any]] = []
    for company in top:
        ticker = company.get("ticker", "")
        composite_score = get_score(company)

        # Fundamental
        price_data = prices.get(ticker, [])
        price_metrics = compute_price_metrics(price_data, as_of_date) if price_data else {
            "momentum_6m": None, "volatility": None, "max_drawdown": None, "n_days": 0
        }
        health = health_rating(
            price_metrics["volatility"],
            price_metrics["max_drawdown"],
            price_metrics["momentum_6m"],
        )

        # Clinical
        ncts = trial_map.get(ticker, [])
        if ncts and studies:
            clinical = analyze_clinical(ticker, ncts, studies, sponsors, snap_date)
        else:
            clinical = {
                "lead_phase": "N/A",
                "active_trials": 0,
                "total_trials": len(ncts),
                "catalysts": [],
                "sponsor_diversity": 0,
                "therapeutic_area": THERAPEUTIC_AREA.get(ticker, "Unknown"),
                "grade": "N/A",
            }

        # Consensus
        consensus = consensus_rating(health, clinical["grade"], is_optimized, composite_score)

        results.append({
            "ticker": ticker,
            "composite_score": composite_score,
            "composite_rank": company.get("composite_rank"),
            "momentum_6m": price_metrics["momentum_6m"],
            "volatility": price_metrics["volatility"],
            "max_drawdown": price_metrics["max_drawdown"],
            "financial_health": health,
            "lead_phase": clinical["lead_phase"],
            "active_trials": clinical["active_trials"],
            "total_trials": clinical["total_trials"],
            "catalysts": clinical["catalysts"],
            "sponsor_diversity": clinical["sponsor_diversity"],
            "therapeutic_area": clinical["therapeutic_area"],
            "pipeline_grade": clinical["grade"],
            "consensus": consensus,
        })

    # Generate report
    report = generate_report(results, as_of_date, snapshot_path.name, is_optimized)

    # Write output
    if output_path is None:
        output_path = OUTPUT_DIR / f"ensemble_report_{as_of_date}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nReport written to: {output_path}")
    return output_path


def generate_report(
    results: list[dict[str, Any]],
    as_of: str,
    snapshot_name: str,
    is_optimized: bool,
) -> str:
    """Generate the markdown ensemble report."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# 🧬 Wake Robin Biotech Ensemble Report",
        f"**Generated:** {now}",
        f"**Snapshot:** `{snapshot_name}` (as-of: {as_of})",
        f"**Method:** Deterministic ensemble (fundamental + clinical{' + optimized scores' if is_optimized else ''})",
        f"",
        f"---",
        f"",
        f"## Unified Investment Matrix",
        f"",
        f"| Ticker | Score | 6M Mom% | Vol% | MaxDD% | Health | Phase | Active | Grade | TA | Consensus |",
        f"|--------|-------|---------|------|--------|--------|-------|--------|-------|----|-----------|",
    ]

    for r in results:
        mom = f"{r['momentum_6m']:+.1f}" if r["momentum_6m"] is not None else "N/A"
        vol = f"{r['volatility']:.1f}" if r["volatility"] is not None else "N/A"
        mdd = f"{r['max_drawdown']:.1f}" if r["max_drawdown"] is not None else "N/A"
        consensus_emoji = {"BUY": "🟢", "HOLD": "🟡", "AVOID": "🔴"}.get(r["consensus"], "⚪")
        lines.append(
            f"| **{r['ticker']}** | {r['composite_score']:.1f} | {mom} | {vol} | {mdd} | "
            f"{r['financial_health']} | {r['lead_phase']} | {r['active_trials']} | "
            f"{r['pipeline_grade']} | {r['therapeutic_area']} | {consensus_emoji} **{r['consensus']}** |"
        )

    # Consensus picks
    buy = [r for r in results if r["consensus"] == "BUY"]
    hold = [r for r in results if r["consensus"] == "HOLD"]
    avoid = [r for r in results if r["consensus"] == "AVOID"]

    lines.extend([
        f"",
        f"---",
        f"",
        f"## Consensus Picks",
        f"",
        f"| Rating | Tickers |",
        f"|--------|---------|",
        f"| 🟢 **BUY** | {', '.join(r['ticker'] for r in buy) or 'None'} |",
        f"| 🟡 **HOLD** | {', '.join(r['ticker'] for r in hold) or 'None'} |",
        f"| 🔴 **AVOID** | {', '.join(r['ticker'] for r in avoid) or 'None'} |",
        f"",
    ])

    # Top picks detail
    if buy:
        lines.extend([f"### 🟢 Top BUY Signals", f""])
        for r in buy[:3]:
            lines.append(f"**{r['ticker']}** — Health: {r['financial_health']}, Pipeline: {r['pipeline_grade']}, "
                        f"Phase: {r['lead_phase']}, {r['active_trials']} active trial(s)")
            if r["catalysts"]:
                lines.append(f"  Catalysts: {'; '.join(r['catalysts'])}")
            lines.append("")

    # Catalysts
    all_catalysts = [(r["ticker"], c) for r in results for c in r["catalysts"]]
    if all_catalysts:
        lines.extend([
            f"---",
            f"",
            f"## Upcoming Catalysts",
            f"",
            f"| Ticker | Catalyst |",
            f"|--------|----------|",
        ])
        for ticker, cat in all_catalysts:
            lines.append(f"| {ticker} | {cat} |")
        lines.append("")

    # Therapeutic area breakdown
    ta_counts: dict[str, int] = defaultdict(int)
    for r in results:
        ta_counts[r["therapeutic_area"]] += 1
    if ta_counts:
        lines.extend([
            f"---",
            f"",
            f"## Therapeutic Area Distribution",
            f"",
            f"| Area | Companies |",
            f"|------|-----------|",
        ])
        for ta, cnt in sorted(ta_counts.items(), key=lambda x: -x[1]):
            lines.append(f"| {ta} | {cnt} |")
        lines.append("")

    lines.extend([
        f"---",
        f"",
        f"## Methodology",
        f"",
        f"| Dimension | Source | Key Metrics |",
        f"|-----------|--------|-------------|",
        f"| **Fundamental** | `data/daily_prices.csv` | 6M momentum, annualized volatility, max drawdown |",
        f"| **Clinical** | `data/aact_snapshots/` + `data/trial_mapping.csv` | Phase, active trials, catalysts, sponsor diversity, A-F grade |",
    ])
    if is_optimized:
        lines.append(f"| **Optimized Scores** | Grid-search weighted composite | IC-optimized feature weights (clinical + financial) |")
    lines.extend([
        f"",
        f"**Consensus Logic:** BUY = 2+ buy signals, 0 avoid. AVOID = 2+ avoid signals, 0 buy. HOLD = everything else.",
        f"",
    ])

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Run biotech ensemble analysis")
    parser.add_argument("--snapshot", default=None, help="Snapshot date (YYYY-MM-DD). Defaults to latest.")
    parser.add_argument("--top", type=int, default=10, help="Number of top companies to analyze")
    parser.add_argument("--output", default=None, help="Output file path")
    args = parser.parse_args()

    # Find snapshot
    if args.snapshot:
        # Try optimized first, then base
        path = OUTPUT_DIR / f"snapshot_optimized_{args.snapshot}.json"
        if not path.exists():
            path = OUTPUT_DIR / f"snapshot_{args.snapshot}.json"
        if not path.exists():
            print(f"Error: No snapshot found for {args.snapshot}")
            sys.exit(1)
    else:
        path = find_latest_snapshot()
        if not path:
            print("Error: No snapshots found in output/")
            sys.exit(1)

    output_path = Path(args.output) if args.output else None
    result_path = run_ensemble(path, top_n=args.top, output_path=output_path)

    # Print summary
    print("\n" + "=" * 60)
    print("ENSEMBLE COMPLETE")
    print("=" * 60)
    print(f"Report: {result_path}")


if __name__ == "__main__":
    main()

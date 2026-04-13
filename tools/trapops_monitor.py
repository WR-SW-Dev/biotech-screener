#!/usr/bin/env python3
"""TrapOps — daily monitoring agent for Trap T20 → B6 → sizing system.

Monitors, audits, and reports. Does NOT modify production state.

Modules:
  A. selection_diff — yesterday vs today, removed/added, overlap
  B. execution_stress — participation, scaled/skipped, tail concentration
  C. trap_attribution — removed vs kept forward returns
  D. health_alerts — threshold-based state: GREEN / YELLOW / RED

Usage:
    python3 tools/trapops_monitor.py
    python3 tools/trapops_monitor.py --snapshot-date 2026-04-12
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ═════════════════════════════════════════════════════════════════════════
# Data loading
# ═════════════════════════════════════════════════════════════════════════


def _load_snapshot(snap_dir: Path) -> List[Dict[str, str]]:
    csv_path = snap_dir / "rankings.csv"
    if not csv_path.exists():
        return []
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _sf(v) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "None", "nan"):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _find_prior_snapshot(snap_root: Path, current_date: str) -> Optional[Path]:
    """Find the most recent snapshot before current_date."""
    candidates = sorted(
        d.name
        for d in snap_root.iterdir()
        if d.is_dir() and len(d.name) == 10 and d.name < current_date and (d / "rankings.csv").exists()
    )
    if candidates:
        return snap_root / candidates[-1]
    return None


def _find_lookback_snapshots(snap_root: Path, current_date: str, n: int = 20) -> List[Path]:
    """Find the most recent N snapshots before current_date."""
    candidates = sorted(
        d.name
        for d in snap_root.iterdir()
        if d.is_dir() and len(d.name) == 10 and d.name < current_date and (d / "rankings.csv").exists()
    )
    return [snap_root / d for d in candidates[-n:]]


# ═════════════════════════════════════════════════════════════════════════
# Module A: Selection Diff
# ═════════════════════════════════════════════════════════════════════════


def selection_diff(current_rows: List[Dict], prior_rows: Optional[List[Dict]]) -> Dict[str, Any]:
    """Compare today's top-30 vs yesterday's."""

    def _top30(rows):
        eligible = [
            r for r in rows if r.get("ees_eligible") is True or str(r.get("ees_eligible", "")).strip().lower() == "true"
        ]
        b6 = []
        for r in eligible:
            sel = _sf(r.get("selector_score"))
            if sel is not None:
                b6.append((r.get("ticker", ""), sel))
        b6.sort(key=lambda x: x[1], reverse=True)
        return [t for t, _ in b6[:30]]

    current_top = _top30(current_rows)
    current_set = set(current_top)

    if not prior_rows:
        return {
            "current_top30": current_top,
            "prior_top30": [],
            "overlap": 0,
            "added": list(current_set),
            "removed": [],
            "trap_removed_today": _trap_removed(current_rows),
        }

    prior_top = _top30(prior_rows)
    prior_set = set(prior_top)

    return {
        "current_top30": current_top,
        "prior_top30": prior_top,
        "overlap": len(current_set & prior_set),
        "added": sorted(current_set - prior_set),
        "removed": sorted(prior_set - current_set),
        "trap_removed_today": _trap_removed(current_rows),
    }


def _trap_removed(rows: List[Dict]) -> List[str]:
    """Names in top-30 by B6 that are removed by trap gate."""
    all_b6 = []
    for r in rows:
        sel = _sf(r.get("selector_score"))
        if sel is not None:
            all_b6.append((r.get("ticker", ""), sel))
    all_b6.sort(key=lambda x: x[1], reverse=True)

    top30_all = set(t for t, _ in all_b6[:30])
    eligible = set(
        r.get("ticker", "")
        for r in rows
        if r.get("ees_eligible") is True or str(r.get("ees_eligible", "")).strip().lower() == "true"
    )
    return sorted(top30_all - eligible)


# ═════════════════════════════════════════════════════════════════════════
# Module B: Execution Stress
# ═════════════════════════════════════════════════════════════════════════


def execution_stress(snap_dir: Path) -> Dict[str, Any]:
    """Read pre-computed execution stress reports."""
    result = {}
    for scenario in ["base", "stress"]:
        path = snap_dir / f"execution_stress_{scenario}.json"
        if path.exists():
            with open(path) as f:
                result[scenario] = json.load(f)
    return result


# ═════════════════════════════════════════════════════════════════════════
# Module C: Trap Attribution
# ═════════════════════════════════════════════════════════════════════════


def trap_attribution(snap_dir: Path) -> Dict[str, Any]:
    """Read pre-computed gate performance."""
    path = snap_dir / "ees_gate_performance.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


# ═════════════════════════════════════════════════════════════════════════
# Module D: Health Alerts
# ═════════════════════════════════════════════════════════════════════════


def health_alerts(
    current_rows: List[Dict],
    lookback_dirs: List[Path],
    stress_data: Dict[str, Any],
    attribution_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute health state: GREEN / YELLOW / RED."""
    alerts = []
    state = "GREEN"

    # 1. Trap coverage
    n_total = len(current_rows)
    n_eligible = sum(
        1
        for r in current_rows
        if r.get("ees_eligible") is True or str(r.get("ees_eligible", "")).strip().lower() == "true"
    )
    trap_pass_rate = n_eligible / n_total * 100 if n_total > 0 else 0

    # Compare to rolling average
    rolling_rates = []
    for d in lookback_dirs:
        rows = _load_snapshot(d)
        if rows:
            n = len(rows)
            e = sum(
                1
                for r in rows
                if r.get("ees_eligible") is True or str(r.get("ees_eligible", "")).strip().lower() == "true"
            )
            rolling_rates.append(e / n * 100 if n > 0 else 0)

    if rolling_rates:
        avg_rate = statistics.mean(rolling_rates)
        if abs(trap_pass_rate - avg_rate) > 15:
            alerts.append(f"Trap pass rate shifted: {trap_pass_rate:.0f}% vs {avg_rate:.0f}% rolling avg")
            state = "YELLOW"

    # 2. Rolling IC from gate diagnostics
    ic_vals = []
    for d in lookback_dirs:
        diag_path = d / "ees_gate_diagnostics.json"
        if diag_path.exists():
            with open(diag_path) as f:
                diag = json.load(f)
            corr = diag.get("quality_trap_correlation")
            if corr is not None:
                ic_vals.append(corr)

    if len(ic_vals) >= 5:
        recent_corr = statistics.mean(ic_vals[-5:])
        if recent_corr > 0.40:
            alerts.append(f"Quality-trap correlation rising: {recent_corr:.3f} > 0.40")
            state = "YELLOW"

    # 3. Execution stress
    base_stress = stress_data.get("base", {})
    tc = base_stress.get("tail_concentration", {})
    if tc.get("n_above_20pct_adv", 0) > 0:
        alerts.append(f"Names above 20% ADV: {tc['n_above_20pct_adv']}")
        state = "RED"
    elif tc.get("n_above_5pct_adv", 0) > 3:
        alerts.append(f"Multiple names above 5% ADV: {tc['n_above_5pct_adv']}")
        state = "YELLOW"

    top3_weight = tc.get("top3_participation_weight_pct", 0)
    if top3_weight > 15:
        alerts.append(f"Top 3 stress names hold {top3_weight:.1f}% of capital")
        state = max(state, "YELLOW")

    # 4. Attribution: removed vs kept
    if attribution_data:
        e_ret = attribution_data.get("eligible", {}).get("mean_ret")
        t_ret = attribution_data.get("trap_fail", {}).get("mean_ret")
        if e_ret is not None and t_ret is not None and t_ret > e_ret:
            alerts.append(f"Trap-removed outperforming eligible: {t_ret:.2f}% vs {e_ret:.2f}%")
            state = "RED"

    # 5. No-volume data names in portfolio
    stress_top = base_stress.get("top_10_stress", [])
    no_vol = [t for t in stress_top if t.get("dollar_volume") is None]
    if no_vol:
        alerts.append(f"No-volume names in stress report: {[t['ticker'] for t in no_vol]}")
        state = max(state, "YELLOW")

    return {
        "state": state,
        "alerts": alerts,
        "trap_pass_rate": round(trap_pass_rate, 1),
        "n_eligible": n_eligible,
        "n_total": n_total,
    }


# ═════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════


def run_trapops(snap_date: str, snap_root: Path) -> Dict[str, Any]:
    """Run all TrapOps modules."""
    snap_dir = snap_root / snap_date
    current_rows = _load_snapshot(snap_dir)
    if not current_rows:
        return {"error": f"No rankings.csv in {snap_dir}"}

    prior_dir = _find_prior_snapshot(snap_root, snap_date)
    prior_rows = _load_snapshot(prior_dir) if prior_dir else None
    lookback_dirs = _find_lookback_snapshots(snap_root, snap_date, n=20)

    # Module A
    sel_diff = selection_diff(current_rows, prior_rows)

    # Module B
    stress = execution_stress(snap_dir)

    # Module C
    attrib = trap_attribution(snap_dir)

    # Module D
    health = health_alerts(current_rows, lookback_dirs, stress, attrib)

    return {
        "snapshot_date": snap_date,
        "selection_diff": sel_diff,
        "execution_stress": stress,
        "trap_attribution": attrib,
        "health": health,
    }


def print_report(result: Dict[str, Any]) -> None:
    snap_date = result.get("snapshot_date", "?")
    health = result.get("health", {})
    sel = result.get("selection_diff", {})
    stress = result.get("execution_stress", {})
    attrib = result.get("trap_attribution", {})

    state = health.get("state", "?")
    state_icon = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(state, "⚪")

    print(f"\n{'=' * 60}")
    print(f"  TrapOps Daily Report — {snap_date}")
    print(f"  Status: {state_icon} {state}")
    print(f"{'=' * 60}")

    # Health
    print(
        f"\n  Universe: {health.get('n_eligible', 0)}/{health.get('n_total', 0)} eligible ({health.get('trap_pass_rate', 0):.0f}%)"
    )
    if health.get("alerts"):
        print("  Alerts:")
        for a in health["alerts"]:
            print(f"    - {a}")
    else:
        print("  Alerts: none")

    # Selection diff
    print(f"\n  Top-30 overlap: {sel.get('overlap', '?')}/30")
    if sel.get("added"):
        print(f"  Added: {', '.join(sel['added'][:10])}")
    if sel.get("removed"):
        print(f"  Removed: {', '.join(sel['removed'][:10])}")
    if sel.get("trap_removed_today"):
        print(f"  Trap vetoes: {', '.join(sel['trap_removed_today'][:10])}")

    # Execution stress
    base = stress.get("base", {})
    tc = base.get("tail_concentration", {})
    if tc:
        print(
            f"\n  Execution ($5M): >5%ADV={tc.get('n_above_5pct_adv', 0)}, >20%ADV={tc.get('n_above_20pct_adv', 0)}, top3_weight={tc.get('top3_participation_weight_pct', 0):.1f}%"
        )

    top_stress = base.get("top_10_stress", [])[:3]
    if top_stress:
        print("  Worst trades: ", end="")
        parts = [f"{t['ticker']}({t['participation']:.1%})" for t in top_stress if t.get("participation")]
        print(", ".join(parts))

    # Attribution
    if attrib:
        e = attrib.get("eligible", {})
        t = attrib.get("trap_fail", {})
        e_ret = e.get("mean_ret")
        t_ret = t.get("mean_ret")
        if e_ret is not None and t_ret is not None:
            print(f"\n  Attribution: eligible={e_ret:+.2f}%, trap_fail={t_ret:+.2f}% (gap={e_ret - t_ret:+.2f}%)")
        else:
            print("\n  Attribution: insufficient data")

    print()


def main():
    parser = argparse.ArgumentParser(description="TrapOps daily monitoring agent")
    parser.add_argument("--snapshot-date", default=None)
    parser.add_argument("--snapshot-root", type=Path, default=PROJECT_ROOT / "data" / "snapshots")
    args = parser.parse_args()

    snap_date = args.snapshot_date
    if not snap_date:
        # Find most recent snapshot
        candidates = sorted(
            d.name
            for d in args.snapshot_root.iterdir()
            if d.is_dir() and len(d.name) == 10 and (d / "rankings.csv").exists()
        )
        if candidates:
            snap_date = candidates[-1]
        else:
            print("No snapshots found")
            return

    result = run_trapops(snap_date, args.snapshot_root)

    # Save JSON
    out_path = args.snapshot_root / snap_date / "trapops_daily_summary.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print_report(result)
    print(f"  Written: {out_path}")


if __name__ == "__main__":
    main()

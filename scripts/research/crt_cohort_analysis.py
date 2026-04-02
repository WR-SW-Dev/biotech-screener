"""CRT cohort analysis — realized returns by catalyst type, liquidity, and options surface.

Reads the CRT × options join (v2) and produces cohort return diagnostics
for the resolved catalyst events. This is the analytical output that makes
the realized-return backfill useful.

Usage:
    python scripts/research/crt_cohort_analysis.py
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

JOIN_PATH = REPO_ROOT / "output" / "catalyst_ev" / "crt_options_join.json"
OUTPUT_PATH = REPO_ROOT / "output" / "catalyst_ev" / "crt_cohort_analysis.json"


def _cohort_stats(records: list[dict], return_field: str = "realized_1d_return") -> dict:
    """Compute return stats for a cohort."""
    rets = [r[return_field] for r in records if r.get(return_field) is not None]
    if not rets:
        return {"n": 0}
    abs_rets = [abs(r) for r in rets]
    return {
        "n": len(rets),
        "mean": round(statistics.mean(rets), 4),
        "median": round(statistics.median(rets), 4),
        "mean_abs": round(statistics.mean(abs_rets), 4),
        "pct_positive": round(sum(1 for r in rets if r > 0) / len(rets), 3),
        "std": round(statistics.stdev(rets), 4) if len(rets) > 1 else 0,
        "min": round(min(rets), 4),
        "max": round(max(rets), 4),
    }


def run_analysis() -> dict:
    if not JOIN_PATH.exists():
        return {"error": f"Join file not found: {JOIN_PATH}"}

    join_data = json.loads(JOIN_PATH.read_text())
    records = join_data.get("records", [])

    # Only records with realized 1d returns
    with_1d = [r for r in records if r.get("realized_1d_return") is not None]
    with_5d = [r for r in records if r.get("realized_5d_return") is not None]

    # --- Cohort 1: By catalyst type ---
    by_type: dict[str, list] = {}
    for r in with_1d:
        ct = r.get("catalyst_type", "UNKNOWN")
        by_type.setdefault(ct, []).append(r)

    type_stats = {ct: _cohort_stats(recs) for ct, recs in sorted(by_type.items())}

    # --- Cohort 2: Hard vs soft ---
    hard = [r for r in with_1d if r.get("is_hard_catalyst")]
    soft = [r for r in with_1d if not r.get("is_hard_catalyst")]

    # --- Cohort 3: By outcome ---
    by_outcome: dict[str, list] = {}
    for r in with_1d:
        outcome = r.get("outcome", "UNKNOWN")
        by_outcome.setdefault(outcome, []).append(r)

    outcome_stats = {o: _cohort_stats(recs) for o, recs in sorted(by_outcome.items())}

    # --- Cohort 4: Options surface at prediction ---
    with_options = [r for r in with_1d if r.get("opt_has_data") == "1"]
    event_loaded = [r for r in with_options if r.get("opt_event_premium") == "YES"]
    flat_surface = [r for r in with_options if r.get("opt_event_premium") != "YES"]

    # --- Cohort 5: Implied vs realized ---
    with_ivr = [r for r in with_1d if r.get("implied_vs_realized_1d") is not None]
    overpriced = [r for r in with_ivr if r.get("market_overpriced_1d") is True]
    underpriced = [r for r in with_ivr if r.get("market_overpriced_1d") is False]

    # --- Cohort 6: By IV regime ---
    by_regime: dict[str, list] = {}
    for r in with_options:
        regime = r.get("opt_iv_regime", "UNKNOWN") or "UNKNOWN"
        by_regime.setdefault(regime, []).append(r)

    regime_stats = {reg: _cohort_stats(recs) for reg, recs in sorted(by_regime.items())}

    # --- Cohort 7: Regulatory vs clinical (hard only) ---
    hard_reg = [r for r in hard if r.get("is_regulatory")]
    hard_clin = [r for r in hard if not r.get("is_regulatory")]

    # --- Summary: implied-vs-realized distribution ---
    ivr_values = [r["implied_vs_realized_1d"] for r in with_ivr]

    result = {
        "schema": "crt_cohort_analysis.v1",
        "n_total": len(records),
        "n_with_1d_return": len(with_1d),
        "n_with_5d_return": len(with_5d),
        "n_with_options": len(with_options),
        "cohorts": {
            "by_catalyst_type": type_stats,
            "hard_vs_soft": {
                "hard_catalyst": _cohort_stats(hard),
                "soft_catalyst": _cohort_stats(soft),
            },
            "by_outcome": outcome_stats,
            "event_loaded_vs_flat": {
                "event_loaded": _cohort_stats(event_loaded),
                "flat_surface": _cohort_stats(flat_surface),
            },
            "implied_vs_realized": {
                "with_ratio": {
                    "n": len(with_ivr),
                    "mean_ratio": round(statistics.mean(ivr_values), 3) if ivr_values else None,
                    "median_ratio": round(statistics.median(ivr_values), 3) if ivr_values else None,
                },
                "market_overpriced": _cohort_stats(overpriced),
                "market_underpriced": _cohort_stats(underpriced),
            },
            "by_iv_regime": regime_stats,
            "hard_regulatory_vs_clinical": {
                "hard_regulatory": _cohort_stats(hard_reg),
                "hard_clinical": _cohort_stats(hard_clin),
            },
        },
        "five_day_returns": {
            "all": _cohort_stats(with_5d, "realized_5d_return"),
            "hard": _cohort_stats([r for r in with_5d if r.get("is_hard_catalyst")], "realized_5d_return"),
        },
    }
    return result


def print_report(result: dict):
    if "error" in result:
        print(result["error"])
        return

    print(f"\n{'='*70}")
    print("CRT COHORT ANALYSIS — Realized Returns")
    print(f"{'='*70}")
    print(f"Total resolutions: {result['n_total']}")
    print(f"With 1d return: {result['n_with_1d_return']}")
    print(f"With 5d return: {result['n_with_5d_return']}")
    print(f"With options at prediction: {result['n_with_options']}")

    for section_name, section in result["cohorts"].items():
        print(f"\n--- {section_name} ---")
        for cohort_name, stats in section.items():
            if isinstance(stats, dict) and "n" in stats:
                n = stats["n"]
                mean = stats.get("mean")
                mean_abs = stats.get("mean_abs")
                pct = stats.get("pct_positive")
                mean_str = f"{mean:>+.4f}" if mean is not None else "—"
                abs_str = f"{mean_abs:.4f}" if mean_abs is not None else ""
                pct_str = f"{pct:.0%}" if pct is not None else "—"
                extra = f" |abs|={abs_str}" if abs_str else ""
                print(f"  {cohort_name:<30} n={n:<4} mean={mean_str}  %+={pct_str}{extra}")
            elif isinstance(stats, dict):
                for k, v in stats.items():
                    if v is not None:
                        print(f"  {k}: {v}")

    print("\n--- 5-day returns ---")
    for k, stats in result.get("five_day_returns", {}).items():
        if stats.get("n", 0) > 0:
            print(f"  {k:<30} n={stats['n']:<4} mean={stats['mean']:>+.4f}  %+={stats['pct_positive']:.0%}")


def main():
    result = run_analysis()
    Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"Wrote {OUTPUT_PATH}")
    print_report(result)


if __name__ == "__main__":
    main()

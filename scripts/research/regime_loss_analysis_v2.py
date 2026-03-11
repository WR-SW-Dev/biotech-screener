#!/usr/bin/env python3
"""
Regime loss analysis v2 — deeper dives:
1. Excess vs XBI weekly return (not drawdown level)
2. Single-name concentration in worst weeks
3. Conditional vol: does the model's worst excess cluster during XBI vol spikes?
4. Sequential loss clustering: are bad weeks followed by more bad weeks?
"""

import csv
import math
from pathlib import Path

PANEL_CSV = Path(__file__).resolve().parents[2] / "data" / "regime_loss_panel.csv"


def load_panel():
    with open(PANEL_CSV) as f:
        return list(csv.DictReader(f))


def to_float(v, default=float("nan")):
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def main():
    panel = load_panel()
    for r in panel:
        r["_excess"] = to_float(r["excess_pct"])
        r["_port"] = to_float(r["port_ret_pct"])
        r["_xbi"] = to_float(r["xbi_ret_pct"])
        r["_xbi_dd"] = to_float(r["xbi_dd_pct"])
        r["_worst_ret"] = to_float(r["worst_ret_pct"])
        r["_gap_wt"] = to_float(r["gap_risk_wt_pct"])

    print("=" * 70)
    print("DEEPER REGIME ANALYSIS")
    print("=" * 70)

    # 1. Excess vs XBI weekly return buckets (not drawdown level)
    print("\n--- EXCESS RETURN BY XBI WEEKLY RETURN BUCKET ---")
    for label, lo, hi in [
        ("XBI < -5%", -999, -5),
        ("XBI -5% to -2%", -5, -2),
        ("XBI -2% to 0%", -2, 0),
        ("XBI 0% to +2%", 0, 2),
        ("XBI +2% to +5%", 2, 5),
        ("XBI > +5%", 5, 999),
    ]:
        subset = [r for r in panel if lo <= r["_xbi"] < hi]
        if not subset:
            continue
        ex = [r["_excess"] for r in subset]
        neg_ex = [e for e in ex if e < 0]
        print(
            f"  {label:22s}  n={len(subset):3d}  "
            f"mean_excess={sum(ex)/len(ex):+.3f}%  "
            f"neg_weeks={len(neg_ex)} ({100*len(neg_ex)/len(subset):.0f}%)  "
            f"worst_excess={min(ex):+.2f}%"
        )

    # 2. Single-name concentration in worst weeks
    print("\n--- SINGLE-NAME BLOW-UP IN WORST EXCESS WEEKS ---")
    print("  Are the worst weeks driven by a single name's outsized loss?")
    worst_20 = sorted(panel, key=lambda r: r["_excess"])[:20]
    blowup_count = 0
    for r in worst_20:
        worst_ret = r["_worst_ret"]
        port_ret = r["_port"]
        n_held = to_float(r["n_held"], 25)
        if n_held > 0 and not math.isnan(worst_ret):
            # Contribution of worst name to portfolio (equal weight)
            worst_contrib = worst_ret / n_held
            # What fraction of portfolio loss is explained by worst name?
            if port_ret < 0:
                frac = worst_contrib / port_ret
                if frac > 0.25:
                    blowup_count += 1
                    print(
                        f"  {r['as_of']}: excess={r['_excess']:+.2f}%  "
                        f"worst={r['worst_ticker']} ({worst_ret:+.1f}%)  "
                        f"contrib={worst_contrib:+.2f}%  "
                        f"explains {frac:.0%} of port loss"
                    )
    print(f"\n  Single-name explains >25% of loss: {blowup_count}/20 worst weeks ({blowup_count/20:.0%})")

    # 3. Sequential clustering: are bad weeks followed by bad weeks?
    print("\n--- SEQUENTIAL LOSS CLUSTERING ---")
    print("  After a week with excess < -3%, what happens next week?")
    bad_weeks = [(i, r) for i, r in enumerate(panel) if r["_excess"] < -3.0]
    next_excess = []
    for i, r in bad_weeks:
        if i + 1 < len(panel):
            next_excess.append(panel[i + 1]["_excess"])
    if next_excess:
        print(f"  n={len(bad_weeks)} bad weeks")
        print(f"  Mean next-week excess: {sum(next_excess)/len(next_excess):+.3f}%")
        neg_follow = sum(1 for e in next_excess if e < 0)
        print(f"  Next week negative: {neg_follow}/{len(next_excess)} ({100*neg_follow/len(next_excess):.0f}%)")

    # After 2 consecutive bad weeks
    print("\n  After TWO consecutive weeks with excess < -2%:")
    double_bad = []
    for i in range(len(panel) - 2):
        if panel[i]["_excess"] < -2.0 and panel[i + 1]["_excess"] < -2.0:
            double_bad.append(panel[i + 2]["_excess"])
    if double_bad:
        print(f"  n={len(double_bad)} double-bad sequences")
        print(f"  Mean 3rd-week excess: {sum(double_bad)/len(double_bad):+.3f}%")
        neg = sum(1 for e in double_bad if e < 0)
        print(f"  3rd week negative: {neg}/{len(double_bad)} ({100*neg/len(double_bad):.0f}%)")

    # 4. XBI drawdown CHANGE (getting worse) vs excess
    print("\n--- XBI DRAWDOWN CHANGE (DEEPENING) VS EXCESS ---")
    for i in range(1, len(panel)):
        panel[i]["_dd_change"] = panel[i]["_xbi_dd"] - panel[i - 1]["_xbi_dd"]
    deepening = [r for r in panel[1:] if "_dd_change" in r and r["_dd_change"] < -5]
    stable = [r for r in panel[1:] if "_dd_change" in r and -2 <= r["_dd_change"] <= 2]
    recovering = [r for r in panel[1:] if "_dd_change" in r and r["_dd_change"] > 5]
    for label, subset in [
        ("Deepening (dd change < -5pp)", deepening),
        ("Stable (dd change -2 to +2pp)", stable),
        ("Recovering (dd change > +5pp)", recovering),
    ]:
        if not subset:
            continue
        ex = [r["_excess"] for r in subset]
        print(f"  {label:40s}  n={len(subset):3d}  mean_excess={sum(ex)/len(ex):+.3f}%")

    # 5. Model beta to XBI: does excess worsen when XBI is down big?
    print("\n--- MODEL BETA ANALYSIS ---")
    print("  Regress port_ret on xbi_ret to get portfolio beta:")
    xbi_vals = [r["_xbi"] for r in panel if not math.isnan(r["_xbi"])]
    port_vals = [r["_port"] for r in panel if not math.isnan(r["_port"])]
    n = min(len(xbi_vals), len(port_vals))
    xbi_vals = xbi_vals[:n]
    port_vals = port_vals[:n]
    mean_x = sum(xbi_vals) / n
    mean_y = sum(port_vals) / n
    cov_xy = sum((xbi_vals[i] - mean_x) * (port_vals[i] - mean_y) for i in range(n)) / n
    var_x = sum((x - mean_x) ** 2 for x in xbi_vals) / n
    if var_x > 0:
        beta = cov_xy / var_x
        alpha_w = mean_y - beta * mean_x
        print(f"  Beta to XBI: {beta:.3f}")
        print(f"  Weekly alpha: {alpha_w:+.3f}%")
        print(f"  Annualized alpha: {alpha_w * 52:+.1f}%")

    # 6. Conditional excess in worst XBI weeks
    print("\n--- EXCESS WHEN XBI HAS WORST WEEKS ---")
    xbi_bottom_decile = sorted(panel, key=lambda r: r["_xbi"])[:36]
    ex_bottom = [r["_excess"] for r in xbi_bottom_decile]
    print(f"  Worst XBI decile ({len(xbi_bottom_decile)} weeks):")
    print(f"    Mean XBI ret: {sum(r['_xbi'] for r in xbi_bottom_decile)/len(xbi_bottom_decile):+.2f}%")
    print(f"    Mean excess:  {sum(ex_bottom)/len(ex_bottom):+.3f}%")
    print(f"    % negative excess: {sum(1 for e in ex_bottom if e < 0)/len(ex_bottom):.0%}")

    xbi_top_decile = sorted(panel, key=lambda r: r["_xbi"], reverse=True)[:36]
    ex_top = [r["_excess"] for r in xbi_top_decile]
    print(f"  Best XBI decile ({len(xbi_top_decile)} weeks):")
    print(f"    Mean XBI ret: {sum(r['_xbi'] for r in xbi_top_decile)/len(xbi_top_decile):+.2f}%")
    print(f"    Mean excess:  {sum(ex_top)/len(ex_top):+.3f}%")

    print("\nDone.")


if __name__ == "__main__":
    main()

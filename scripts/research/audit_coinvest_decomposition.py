#!/usr/bin/env python3
"""Coinvest signal forensic audit — Spec 049 PIT check #1.

Decomposes coinvest_score_z into components to test whether Spec 049's
"coinvest is dominant" finding is driven by:
  (a) real institutional co-investment information, or
  (b) a market-cap / size-band confound (bigger biotechs attract more sponsors)

Creates audit variants in the research panel:
  1. coinvest_binary         – 1 if any tier-1 sponsor, else 0
  2. coinvest_z_sponsored    – z-scored ONLY among tickers with count > 0 (NaN for zeros)
  3. coinvest_z_size_resid   – size-residualized: subtract size-band mean, then z-score

Then runs signal cards on all variants vs the original coinvest_score_z.

Usage:
    python3 scripts/research/audit_coinvest_decomposition.py
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "research"))

PANEL_CSV = PROJECT_ROOT / "output" / "signals" / "research_panel.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "signals"
AUDIT_DIR = OUTPUT_DIR / "coinvest_audit"


def _sf(v, default=float("nan")):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def load_panel() -> List[Dict[str, str]]:
    with open(PANEL_CSV) as f:
        return list(csv.DictReader(f))


def group_by_snapshot(panel):
    groups = defaultdict(list)
    for row in panel:
        groups[row["snapshot_date"]].append(row)
    return dict(sorted(groups.items()))


def zscore_population(vals: List[float]) -> List[float]:
    """Population z-score (ddof=0)."""
    if not vals:
        return []
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    std = var**0.5
    if std < 1e-9:
        return [0.0] * len(vals)
    return [round((v - mean) / std, 4) for v in vals]


def add_audit_columns(panel: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Add decomposed coinvest variants per snapshot."""
    snapshots = group_by_snapshot(panel)
    out_rows = []

    for snap_date, rows in snapshots.items():
        # Parse raw tier1 counts and size bands
        parsed = []
        for r in rows:
            t1 = _sf(r.get("sponsor_tier1_count"), default=None)
            sb = r.get("size_band", r.get("market_cap_bucket", "?"))
            cz_orig = _sf(r.get("coinvest_score_z"), default=None)
            parsed.append(
                {
                    "row": r,
                    "t1": t1 if t1 is not None else 0.0,
                    "t1_valid": t1 is not None,
                    "has_any": (t1 is not None and t1 > 0),
                    "size_band": sb,
                    "cz_orig": cz_orig,
                }
            )

        # --- Variant 1: Binary ---
        # (no z-scoring needed, it's just 0/1)

        # --- Variant 2: Z-score among sponsored only ---
        sponsored_indices = [i for i, p in enumerate(parsed) if p["has_any"]]
        sponsored_vals = [parsed[i]["t1"] for i in sponsored_indices]
        if sponsored_vals:
            z_sponsored = zscore_population(sponsored_vals)
            z_map = {sponsored_indices[i]: z_sponsored[i] for i in range(len(sponsored_indices))}
        else:
            z_map = {}

        # --- Variant 3: Size-residualized z-score ---
        # Step 1: compute size-band means
        by_band = defaultdict(list)
        for p in parsed:
            by_band[p["size_band"]].append(p["t1"])
        band_mean = {band: sum(vals) / len(vals) for band, vals in by_band.items()}
        # Step 2: subtract band mean
        residuals = [p["t1"] - band_mean.get(p["size_band"], 0) for p in parsed]
        # Step 3: z-score the residuals
        z_resid = zscore_population(residuals)

        # Assign to rows
        for i, p in enumerate(parsed):
            row = dict(p["row"])  # copy
            row["coinvest_binary"] = 1.0 if p["has_any"] else 0.0
            row["coinvest_z_sponsored"] = z_map.get(i, "")  # empty for non-sponsored
            row["coinvest_z_size_resid"] = z_resid[i] if z_resid else 0.0
            row["coinvest_size_band_mean"] = round(band_mean.get(p["size_band"], 0), 3)
            out_rows.append(row)

    return out_rows


def write_audit_panel(rows: List[Dict[str, Any]]):
    """Write the augmented panel."""
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = AUDIT_DIR / "research_panel_audit.csv"
    if rows:
        all_cols = list(rows[0].keys())
        all_col_set = set(all_cols)
        for row in rows:
            for k in row:
                if k not in all_col_set:
                    all_cols.append(k)
                    all_col_set.add(k)
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
    print(f"Audit panel: {csv_path} ({len(rows)} rows)")
    return csv_path


def run_signal_cards_on_variants(panel_csv: Path):
    """Run signal card evaluation on the four coinvest variants."""
    from run_signal_cards import group_by_snapshot, pass_a_gate, pass_b_selector, pass_c_ranker, pass_d_regime

    with open(panel_csv) as f:
        panel = list(csv.DictReader(f))

    snapshots = group_by_snapshot(panel)
    horizons = [20, 63]
    top_ns = [20, 30]

    signals = [
        "coinvest_score_z",  # original (full-universe z-score, zeros included)
        "coinvest_binary",  # binary: any tier-1 sponsor vs none
        "coinvest_z_sponsored",  # z-scored among sponsored only (NaN for non-sponsored)
        "coinvest_z_size_resid",  # size-residualized z-score
        "inst_delta_z",  # comparison: institutional delta
        "clinical_score_v2_z",  # comparison: clinical (known problematic)
    ]

    results = {}
    for sig in signals:
        print(f"\n{'='*60}")
        print(f"Signal: {sig}")
        print(f"{'='*60}")

        # Check coverage
        n_total = 0
        n_present = 0
        n_nonzero = 0
        for row in panel:
            v = row.get(sig, "")
            n_total += 1
            if v != "" and v is not None:
                try:
                    fv = float(v)
                    if not math.isnan(fv):
                        n_present += 1
                        if fv != 0.0:
                            n_nonzero += 1
                except (ValueError, TypeError):
                    pass
        print(
            f"  Coverage: {n_present}/{n_total} ({n_present/n_total*100:.1f}%), nonzero: {n_nonzero} ({n_nonzero/n_total*100:.1f}%)"
        )

        card = {
            "signal": sig,
            "coverage_pct": round(n_present / n_total * 100, 1),
            "nonzero_pct": round(n_nonzero / n_total * 100, 1),
        }

        try:
            a = pass_a_gate(snapshots, sig, horizons)
            card["pass_a"] = a
            for h in horizons:
                h_res = a["horizons"].get(str(h), {})
                spread = h_res.get("spread_pp")
                print(f"  Pass A ({h}d): spread={spread}pp")
        except Exception as e:
            print(f"  Pass A error: {e}")

        try:
            b = pass_b_selector(snapshots, sig, horizons, top_ns)
            card["pass_b"] = b
            for tn in top_ns:
                for h in horizons:
                    h_res = b["top_ns"].get(str(tn), {}).get("horizons", {}).get(str(h), {})
                    imp = h_res.get("improvement_pp")
                    ic = h_res.get("universe_ic_mean")
                    t_stat = h_res.get("improvement_tstat")
                    print(f"  Pass B (top-{tn}, {h}d): Δ={imp}pp, IC={ic}, t={t_stat}")
        except Exception as e:
            print(f"  Pass B error: {e}")

        try:
            c = pass_c_ranker(snapshots, sig, horizons, top_ns)
            card["pass_c"] = c
            for tn in top_ns:
                for h in horizons:
                    h_res = c["top_ns"].get(str(tn), {}).get("horizons", {}).get(str(h), {})
                    ic = h_res.get("ic_mean")
                    rw_net = h_res.get("rw_minus_ew_net_pp")
                    cov = h_res.get("signal_coverage_mean")
                    print(f"  Pass C (top-{tn}, {h}d): IC={ic}, RW-EW net={rw_net}pp, cov={cov}")
        except Exception as e:
            print(f"  Pass C error: {e}")

        try:
            d = pass_d_regime(snapshots, sig, horizons, top_n=30)
            card["pass_d"] = d
            for regime in ["bear", "bull", "neutral"]:
                r_res = d["regimes"].get(regime, {})
                ic = r_res.get("ic_mean")
                n_p = r_res.get("n_periods")
                print(f"  Pass D ({regime}): IC={ic}, n={n_p}")
        except Exception as e:
            print(f"  Pass D error: {e}")

        results[sig] = card

    return results


def write_audit_report(results: Dict[str, Any]):
    """Write the comparative audit report."""
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = AUDIT_DIR / "coinvest_decomposition_results.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults JSON: {json_path}")

    # Markdown summary
    md_lines = [
        "# Coinvest Signal Decomposition Audit",
        f"\nGenerated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Purpose",
        "Test whether `coinvest_score_z` dominance in Spec 049 is driven by:",
        "- (a) real co-investment information, or",
        "- (b) a market-cap/size-band confound",
        "",
        "## Signal Variants",
        "| Variant | Description |",
        "|---------|-------------|",
        "| `coinvest_score_z` | Original: z-score of tier1_count, full universe |",
        "| `coinvest_binary` | Binary: any tier-1 sponsor (1) vs none (0) |",
        "| `coinvest_z_sponsored` | Z-scored ONLY among tickers with count>0 |",
        "| `coinvest_z_size_resid` | Size-residualized: subtract band mean, then z-score |",
        "| `inst_delta_z` | Comparison: institutional net delta |",
        "| `clinical_score_v2_z` | Comparison: clinical (known problematic) |",
        "",
        "## Results — Selector (Pass B, Top-30, 63d)",
        "",
        "| Signal | Δ vs baseline (pp) | Universe IC | t-stat | Coverage |",
        "|--------|-------------------|-------------|--------|----------|",
    ]

    for sig, card in results.items():
        b_res = card.get("pass_b", {}).get("top_ns", {}).get("30", {}).get("horizons", {}).get("63", {})
        imp = b_res.get("improvement_pp", "N/A")
        ic = b_res.get("universe_ic_mean", "N/A")
        t = b_res.get("improvement_tstat", "N/A")
        cov = card.get("coverage_pct", "N/A")
        md_lines.append(f"| `{sig}` | {imp} | {ic} | {t} | {cov}% |")

    md_lines.extend(
        [
            "",
            "## Results — Ranker (Pass C, Top-30, 63d)",
            "",
            "| Signal | Within-top-30 IC | RW-EW net (pp/mo) | Coverage |",
            "|--------|-----------------|-------------------|----------|",
        ]
    )

    for sig, card in results.items():
        c_res = card.get("pass_c", {}).get("top_ns", {}).get("30", {}).get("horizons", {}).get("63", {})
        ic = c_res.get("ic_mean", "N/A")
        rw = c_res.get("rw_minus_ew_net_pp", "N/A")
        cov = c_res.get("signal_coverage_mean", "N/A")
        md_lines.append(f"| `{sig}` | {ic} | {rw} | {cov} |")

    md_lines.extend(
        [
            "",
            "## Interpretation Guide",
            "",
            "- If `coinvest_binary` matches or beats `coinvest_score_z`: power is in the binary split, not count granularity",
            "- If `coinvest_z_size_resid` is much weaker: the signal is a market-cap proxy",
            "- If `coinvest_z_sponsored` is strong: real information in count variation among sponsored names",
            "- If size-residualized version still works: genuine co-investment signal beyond size",
            "",
        ]
    )

    md_path = AUDIT_DIR / "coinvest_decomposition_report.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines))
    print(f"Report: {md_path}")


def main():
    print("=" * 60)
    print("COINVEST SIGNAL FORENSIC AUDIT — Spec 049 PIT Check")
    print("=" * 60)

    print("\n1. Loading research panel...")
    panel = load_panel()
    print(f"   {len(panel)} rows")

    print("\n2. Adding decomposition columns...")
    augmented = add_audit_columns(panel)

    # Quick sanity check
    snap_sample = [r for r in augmented if r["snapshot_date"] == augmented[-1]["snapshot_date"]]
    n_bin_1 = sum(1 for r in snap_sample if float(r.get("coinvest_binary", 0)) == 1)
    n_sponsored = sum(1 for r in snap_sample if r.get("coinvest_z_sponsored", "") != "")
    print(
        f"   Latest snapshot: {len(snap_sample)} tickers, {n_bin_1} with any sponsor, {n_sponsored} with sponsored z-score"
    )

    # Size-band mean check
    bands = {}
    for r in snap_sample:
        sb = r.get("size_band", "?")
        bands.setdefault(sb, []).append(float(r.get("coinvest_size_band_mean", 0)))
    for sb in sorted(bands):
        print(f"   Size band {sb}: mean tier1_count = {bands[sb][0]:.2f}")

    print("\n3. Writing audit panel...")
    panel_csv = write_audit_panel(augmented)

    print("\n4. Running signal cards on all variants...")
    results = run_signal_cards_on_variants(panel_csv)

    print("\n5. Writing audit report...")
    write_audit_report(results)

    # Summary verdicts
    print("\n" + "=" * 60)
    print("AUDIT SUMMARY")
    print("=" * 60)

    orig = results.get("coinvest_score_z", {})
    binary = results.get("coinvest_binary", {})
    resid = results.get("coinvest_z_size_resid", {})

    def _get_selector_imp(card):
        return (
            card.get("pass_b", {})
            .get("top_ns", {})
            .get("30", {})
            .get("horizons", {})
            .get("63", {})
            .get("improvement_pp")
        )

    def _get_ranker_ic(card):
        return card.get("pass_c", {}).get("top_ns", {}).get("30", {}).get("horizons", {}).get("63", {}).get("ic_mean")

    print("\nSelector improvement (Top-30, 63d) — pp vs baseline:")
    for name, card in results.items():
        imp = _get_selector_imp(card)
        print(f"  {name:30s}  {imp}")

    print("\nRanker IC (within Top-30, 63d):")
    for name, card in results.items():
        ic = _get_ranker_ic(card)
        print(f"  {name:30s}  {ic}")

    # Verdicts
    orig_imp = _get_selector_imp(orig)
    resid_imp = _get_selector_imp(resid)
    binary_imp = _get_selector_imp(binary)

    print("\n--- VERDICTS ---")
    if orig_imp is not None and resid_imp is not None:
        try:
            o, r = float(orig_imp), float(resid_imp)
            pct_retained = (r / o * 100) if o != 0 else 0
            print(f"Size-residualized retains {pct_retained:.0f}% of original selector improvement")
            if pct_retained < 30:
                print("  → COINVEST IS PRIMARILY A SIZE PROXY — Spec 049 claims suspect")
            elif pct_retained < 70:
                print("  → MIXED: partial size confound, partial real signal")
            else:
                print("  → GENUINE: signal survives size adjustment")
        except (ValueError, TypeError):
            print(f"  Could not compute retention (orig={orig_imp}, resid={resid_imp})")

    if orig_imp is not None and binary_imp is not None:
        try:
            o, b = float(orig_imp), float(binary_imp)
            if abs(o) > 0.01 and abs(b) > abs(o) * 0.7:
                print("Binary explains most of the improvement — count granularity adds little")
            elif abs(o) > abs(b) * 1.5:
                print("Count granularity adds substantial value beyond binary")
        except (ValueError, TypeError):
            pass

    print("\nDone.")


if __name__ == "__main__":
    main()

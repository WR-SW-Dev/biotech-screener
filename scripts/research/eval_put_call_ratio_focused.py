#!/usr/bin/env python3
"""Focused put_call_ratio study: bucket/family splits + temporal stability.

Tests whether pre-catalyst put_call_ratio is a stable negative-alpha signal
independent of clinical quality, and identifies which sleeves it works in.

Usage:
    python scripts/research/eval_put_call_ratio_focused.py \
        --panel data/research/precatalyst_options_panel.csv \
        --price-csv production_data/price_history.csv \
        --output-dir output/put_call_ratio_study
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "research"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("pcr_study")

# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------


def _rank(xs: List[float]) -> List[float]:
    """Fractional ranks (1-based)."""
    n = len(xs)
    indexed = sorted(range(n), key=lambda i: xs[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and xs[indexed[j]] == xs[indexed[j + 1]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg_rank
        i = j + 1
    return ranks


def spearman_ic(x: List[float], y: List[float]) -> Optional[float]:
    """Spearman rank correlation."""
    if len(x) < 10:
        return None
    rx = _rank(x)
    ry = _rank(y)
    n = len(rx)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    sx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    sy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    if sx == 0 or sy == 0:
        return None
    return cov / (sx * sy)


def residualize(x: List[float], z: List[float]) -> List[float]:
    """OLS residuals of x regressed on z."""
    n = len(x)
    mz = sum(z) / n
    mx = sum(x) / n
    ssz = sum((z[i] - mz) ** 2 for i in range(n))
    if ssz == 0:
        return [xi - mx for xi in x]
    beta = sum((x[i] - mx) * (z[i] - mz) for i in range(n)) / ssz
    alpha = mx - beta * mz
    return [x[i] - (alpha + beta * z[i]) for i in range(n)]


# ---------------------------------------------------------------------------
# Price loader
# ---------------------------------------------------------------------------


def load_prices(path: Path) -> Dict[str, Dict[str, float]]:
    """Load price_history.csv → {ticker: {date_str: close}}."""
    prices: Dict[str, Dict[str, float]] = defaultdict(dict)
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker", row.get("Ticker", ""))
            dt = row.get("date", row.get("Date", ""))
            close = row.get("close", row.get("Close", ""))
            if ticker and dt and close:
                try:
                    prices[ticker][dt] = float(close)
                except ValueError:
                    pass
    return dict(prices)


def forward_return(prices: Dict[str, Dict[str, float]], ticker: str, snap_date: str, horizon: int) -> Optional[float]:
    """Compute forward return from snap_date over horizon business days."""
    dt = date.fromisoformat(snap_date)
    p0 = prices.get(ticker, {}).get(snap_date)
    if p0 is None or p0 <= 0:
        # Try nearby dates
        for offset in range(1, 4):
            alt = (dt - timedelta(days=offset)).isoformat()
            p0 = prices.get(ticker, {}).get(alt)
            if p0 is not None and p0 > 0:
                break
        else:
            return None

    # Walk forward horizon business days
    target = dt
    bdays = 0
    while bdays < horizon:
        target += timedelta(days=1)
        if target.weekday() < 5:
            bdays += 1

    # Try target date ± 2 days
    for offset in range(0, 3):
        for sign in [0, 1, -1]:
            check = (target + timedelta(days=sign * offset)).isoformat()
            p1 = prices.get(ticker, {}).get(check)
            if p1 is not None and p1 > 0:
                return (p1 - p0) / p0
    return None


# ---------------------------------------------------------------------------
# Main study
# ---------------------------------------------------------------------------


def run_study(
    panel_path: Path,
    price_path: Path,
    horizons: List[int],
    output_dir: Path,
) -> dict:
    """Run focused put_call_ratio study."""
    # Load panel
    rows = []
    with open(panel_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pcr = row.get("pre_event_put_call_ratio", "")
            if not pcr or pcr in ("", "nan", "None"):
                continue
            try:
                row["_pcr"] = float(pcr)
            except ValueError:
                continue
            try:
                row["_composite"] = float(row.get("composite_score", "0") or "0")
            except ValueError:
                row["_composite"] = 0.0
            rows.append(row)

    logger.info("Panel: %d rows with valid put_call_ratio", len(rows))

    # Load prices
    logger.info("Loading prices...")
    prices = load_prices(price_path)

    # Attach forward returns
    for h in horizons:
        key = f"_fwd_{h}d"
        n_ok = 0
        for row in rows:
            ret = forward_return(prices, row["ticker"], row["snapshot_date"], h)
            row[key] = ret
            if ret is not None:
                n_ok += 1
        logger.info("  %dd: %d/%d with returns", h, n_ok, len(rows))

    results: Dict[str, Any] = {
        "schema": "put_call_ratio_study.v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_total": len(rows),
        "horizons": horizons,
    }

    # --- 1. Pooled IC ---
    pooled = {}
    for h in horizons:
        key = f"_fwd_{h}d"
        valid = [(r["_pcr"], r[key]) for r in rows if r[key] is not None]
        if len(valid) < 20:
            pooled[f"{h}d"] = {"status": "insufficient", "n": len(valid)}
            continue
        xs, ys = zip(*valid)
        raw = spearman_ic(list(xs), list(ys))
        # Incremental
        comps = [r["_composite"] for r in rows if r[key] is not None]
        resid = residualize(list(xs), comps)
        incr = spearman_ic(resid, list(ys))
        pooled[f"{h}d"] = {
            "raw_ic": round(raw, 6) if raw else None,
            "incremental_ic": round(incr, 6) if incr else None,
            "n": len(valid),
        }
    results["pooled_ic"] = pooled

    # --- 2. By bucket ---
    bucket_results = {}
    buckets = sorted(set(r.get("catalyst_bucket", "") for r in rows))
    for bucket in buckets:
        if not bucket:
            continue
        subset = [r for r in rows if r.get("catalyst_bucket") == bucket]
        bucket_results[bucket] = {"n": len(subset)}
        for h in horizons:
            key = f"_fwd_{h}d"
            valid = [(r["_pcr"], r[key]) for r in subset if r[key] is not None]
            if len(valid) < 15:
                bucket_results[bucket][f"{h}d"] = {
                    "status": "insufficient",
                    "n": len(valid),
                }
                continue
            xs, ys = zip(*valid)
            raw = spearman_ic(list(xs), list(ys))
            comps = [r["_composite"] for r in subset if r[key] is not None]
            resid = residualize(list(xs), comps)
            incr = spearman_ic(resid, list(ys))
            bucket_results[bucket][f"{h}d"] = {
                "raw_ic": round(raw, 6) if raw else None,
                "incremental_ic": round(incr, 6) if incr else None,
                "n": len(valid),
            }
    results["by_bucket"] = bucket_results

    # --- 3. By family ---
    family_results = {}
    families = sorted(set(r.get("catalyst_family", "") for r in rows))
    for fam in families:
        if not fam:
            continue
        subset = [r for r in rows if r.get("catalyst_family") == fam]
        family_results[fam] = {"n": len(subset)}
        for h in horizons:
            key = f"_fwd_{h}d"
            valid = [(r["_pcr"], r[key]) for r in subset if r[key] is not None]
            if len(valid) < 15:
                family_results[fam][f"{h}d"] = {
                    "status": "insufficient",
                    "n": len(valid),
                }
                continue
            xs, ys = zip(*valid)
            raw = spearman_ic(list(xs), list(ys))
            comps = [r["_composite"] for r in subset if r[key] is not None]
            resid = residualize(list(xs), comps)
            incr = spearman_ic(resid, list(ys))
            family_results[fam][f"{h}d"] = {
                "raw_ic": round(raw, 6) if raw else None,
                "incremental_ic": round(incr, 6) if incr else None,
                "n": len(valid),
            }
    results["by_family"] = family_results

    # --- 4. Bucket × Family ---
    cross_results = {}
    for bucket in buckets:
        if not bucket:
            continue
        for fam in families:
            if not fam:
                continue
            subset = [r for r in rows if r.get("catalyst_bucket") == bucket and r.get("catalyst_family") == fam]
            if len(subset) < 10:
                continue
            label = f"{bucket}|{fam}"
            cross_results[label] = {"n": len(subset)}
            for h in horizons:
                key = f"_fwd_{h}d"
                valid = [(r["_pcr"], r[key]) for r in subset if r[key] is not None]
                if len(valid) < 10:
                    cross_results[label][f"{h}d"] = {
                        "status": "insufficient",
                        "n": len(valid),
                    }
                    continue
                xs, ys = zip(*valid)
                raw = spearman_ic(list(xs), list(ys))
                cross_results[label][f"{h}d"] = {
                    "raw_ic": round(raw, 6) if raw else None,
                    "n": len(valid),
                }
    results["by_bucket_family"] = cross_results

    # --- 5. Temporal stability (per-snapshot IC sign consistency) ---
    snap_dates = sorted(set(r["snapshot_date"] for r in rows))
    temporal = {}
    for h in horizons:
        key = f"_fwd_{h}d"
        per_snap = []
        for sd in snap_dates:
            subset = [r for r in rows if r["snapshot_date"] == sd and r[key] is not None]
            if len(subset) < 10:
                continue
            xs = [r["_pcr"] for r in subset]
            ys = [r[key] for r in subset]
            ic = spearman_ic(xs, ys)
            if ic is not None:
                per_snap.append({"date": sd, "ic": round(ic, 6), "n": len(subset)})

        n_neg = sum(1 for s in per_snap if s["ic"] < 0)
        n_pos = sum(1 for s in per_snap if s["ic"] >= 0)
        temporal[f"{h}d"] = {
            "snapshots": per_snap,
            "n_negative": n_neg,
            "n_positive": n_pos,
            "sign_consistency": (round(n_neg / len(per_snap), 3) if per_snap else None),
        }
    results["temporal_stability"] = temporal

    # --- 6. Decision summary ---
    p5 = pooled.get("5d", {})
    p20 = pooled.get("20d", {})
    raw_5 = p5.get("raw_ic")
    raw_20 = p20.get("raw_ic")
    incr_5 = p5.get("incremental_ic")
    incr_20 = p20.get("incremental_ic")

    reasons = []
    classification = "abandon"

    # Check if negative alpha candidate
    neg_alpha_5 = raw_5 is not None and raw_5 < -0.05 and incr_5 is not None and abs(incr_5) >= 0.05
    neg_alpha_20 = raw_20 is not None and raw_20 < -0.05 and incr_20 is not None and abs(incr_20) >= 0.05

    if neg_alpha_5 or neg_alpha_20:
        classification = "negative_alpha_candidate"
        if neg_alpha_5:
            reasons.append(f"5d: raw IC={raw_5:.4f}, incremental IC={incr_5:.4f} — survives quality control")
        if neg_alpha_20:
            reasons.append(f"20d: raw IC={raw_20:.4f}, incremental IC={incr_20:.4f} — survives quality control")

        # Check temporal stability
        t5 = temporal.get("5d", {})
        t20 = temporal.get("20d", {})
        sc5 = t5.get("sign_consistency")
        sc20 = t20.get("sign_consistency")
        if sc5 is not None and sc5 >= 0.6:
            reasons.append(f"5d sign consistency: {sc5:.0%} negative")
        if sc20 is not None and sc20 >= 0.6:
            reasons.append(f"20d sign consistency: {sc20:.0%} negative")

        # Check bucket concentration
        strong_buckets = []
        for bk, bv in bucket_results.items():
            for hk in ["5d", "20d"]:
                v = bv.get(hk, {})
                if isinstance(v, dict) and v.get("raw_ic") is not None:
                    if v["raw_ic"] < -0.05:
                        strong_buckets.append(f"{bk}@{hk}")
        if strong_buckets:
            reasons.append(f"Strong in: {', '.join(strong_buckets)}")
    else:
        if raw_5 is not None and abs(raw_5) < 0.05:
            reasons.append(f"5d raw IC={raw_5:.4f} — below threshold")
        if raw_20 is not None and abs(raw_20) < 0.05:
            reasons.append(f"20d raw IC={raw_20:.4f} — below threshold")

    results["decision"] = {
        "classification": classification,
        "reasons": reasons,
    }

    # Write outputs
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "put_call_ratio_study.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    logger.info("JSON → %s", json_path)

    # Write markdown summary
    md_path = output_dir / "put_call_ratio_study.md"
    md = _build_markdown(results)
    md_path.write_text(md)
    logger.info("MD → %s", md_path)

    return results


def _build_markdown(r: dict) -> str:
    lines = [
        "# Put/Call Ratio Focused Study",
        "",
        f"**Generated**: {r['generated_at']}",
        f"**N**: {r['n_total']} events",
        f"**Decision**: **{r['decision']['classification'].upper()}**",
        "",
    ]

    for reason in r["decision"]["reasons"]:
        lines.append(f"- {reason}")
    lines.append("")

    # Pooled IC
    lines.append("## Pooled IC")
    lines.append("")
    lines.append("| Horizon | Raw IC | Incr IC | N |")
    lines.append("|---------|--------|---------|---|")
    for hk, hv in r["pooled_ic"].items():
        if hv.get("status") == "insufficient":
            lines.append(f"| {hk} | insufficient | — | {hv['n']} |")
        else:
            raw = f"{hv['raw_ic']:.4f}" if hv.get("raw_ic") is not None else "—"
            incr = f"{hv['incremental_ic']:.4f}" if hv.get("incremental_ic") is not None else "—"
            lines.append(f"| {hk} | {raw} | {incr} | {hv['n']} |")
    lines.append("")

    # By bucket
    lines.append("## By Bucket")
    lines.append("")
    lines.append("| Bucket | Horizon | Raw IC | Incr IC | N |")
    lines.append("|--------|---------|--------|---------|---|")
    for bk, bv in r["by_bucket"].items():
        for hk in [f"{h}d" for h in r["horizons"]]:
            v = bv.get(hk, {})
            if isinstance(v, dict) and v.get("status") == "insufficient":
                lines.append(f"| {bk} | {hk} | insufficient | — | {v['n']} |")
            elif isinstance(v, dict):
                raw = f"{v['raw_ic']:.4f}" if v.get("raw_ic") is not None else "—"
                incr = f"{v['incremental_ic']:.4f}" if v.get("incremental_ic") is not None else "—"
                lines.append(f"| {bk} | {hk} | {raw} | {incr} | {v['n']} |")
    lines.append("")

    # By family
    lines.append("## By Family")
    lines.append("")
    lines.append("| Family | Horizon | Raw IC | Incr IC | N |")
    lines.append("|--------|---------|--------|---------|---|")
    for fk, fv in r["by_family"].items():
        for hk in [f"{h}d" for h in r["horizons"]]:
            v = fv.get(hk, {})
            if isinstance(v, dict) and v.get("status") == "insufficient":
                lines.append(f"| {fk} | {hk} | insufficient | — | {v['n']} |")
            elif isinstance(v, dict):
                raw = f"{v['raw_ic']:.4f}" if v.get("raw_ic") is not None else "—"
                incr = f"{v['incremental_ic']:.4f}" if v.get("incremental_ic") is not None else "—"
                lines.append(f"| {fk} | {hk} | {raw} | {incr} | {v['n']} |")
    lines.append("")

    # Bucket × Family
    if r.get("by_bucket_family"):
        lines.append("## Bucket x Family")
        lines.append("")
        lines.append("| Sleeve | Horizon | Raw IC | N |")
        lines.append("|--------|---------|--------|---|")
        for label, lv in r["by_bucket_family"].items():
            for hk in [f"{h}d" for h in r["horizons"]]:
                v = lv.get(hk, {})
                if isinstance(v, dict) and v.get("status") == "insufficient":
                    lines.append(f"| {label} | {hk} | insufficient | {v['n']} |")
                elif isinstance(v, dict):
                    raw = f"{v['raw_ic']:.4f}" if v.get("raw_ic") is not None else "—"
                    lines.append(f"| {label} | {hk} | {raw} | {v['n']} |")
        lines.append("")

    # Temporal stability
    lines.append("## Temporal Stability (per-snapshot IC)")
    lines.append("")
    for hk, hv in r["temporal_stability"].items():
        sc = hv.get("sign_consistency")
        sc_str = f"{sc:.0%}" if sc is not None else "—"
        lines.append(f"### {hk}: {hv['n_negative']} negative / {hv['n_positive']} positive " f"({sc_str} negative)")
        lines.append("")
        if hv.get("snapshots"):
            lines.append("| Date | IC | N |")
            lines.append("|------|-----|---|")
            for s in hv["snapshots"]:
                lines.append(f"| {s['date']} | {s['ic']:.4f} | {s['n']} |")
            lines.append("")

    lines.append("---\n*Schema: put_call_ratio_study.v1*")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Focused put_call_ratio study with bucket/family splits",
    )
    parser.add_argument(
        "--panel",
        type=Path,
        default=_PROJECT_ROOT / "data" / "research" / "precatalyst_options_panel.csv",
    )
    parser.add_argument(
        "--price-csv",
        type=Path,
        default=_PROJECT_ROOT / "production_data" / "price_history.csv",
    )
    parser.add_argument("--horizons", type=str, default="5,20,63")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_PROJECT_ROOT / "output" / "put_call_ratio_study",
    )
    args = parser.parse_args()

    horizons = [int(h) for h in args.horizons.split(",")]
    results = run_study(args.panel, args.price_csv, horizons, args.output_dir)

    print(f"\nDecision: {results['decision']['classification'].upper()}")
    for reason in results["decision"]["reasons"]:
        print(f"  {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

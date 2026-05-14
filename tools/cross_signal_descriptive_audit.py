#!/usr/bin/env python3
"""Cross-signal bucket DESCRIPTIVE audit on the 21 clean-schema snapshots.

NOT a historical alpha test. Read-only descriptive aggregation across the
2026-04-03 → 2026-04-28 schema-era window where all six independent signals
are available. No ruleset normalization, no PIT regen, no validation claim.

For each snapshot in that window:
  - assign DEM × cross-signal bucket per ticker (same definitions as the
    forward logger: top/bottom selector_score quintile × agreement_score
    >=0.50 / <=0.10)
  - compute forward 5d and 10d simple total returns where price data is
    available
  - aggregate per bucket: count, mean return, median return, hit rate,
    excess vs XBI

Caveats locked in the output:
- Only 21 snapshots over ~26 days; observations are heavily overlapping.
- Effective independent N is much smaller than face N.
- Historical alpha claims are not credible per standing policy.
- This is descriptive only.

Outputs:
  artifacts/audit/cross_signal_forward_shadow/descriptive_audit_2026-04-28.{md,json}
"""

from __future__ import annotations

import csv
import json
import statistics
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SNAP_DIR = REPO / "data" / "snapshots"
PRICE_FILE = REPO / "production_data" / "price_history.csv"
OUT_DIR = REPO / "artifacts" / "audit" / "cross_signal_forward_shadow"
INDEPENDENT_SIGNALS = [
    "clinical_score_v2_z",
    "financial_score",
    "selector_clinical_block",
    "selector_catalyst_block",
    "selector_survivability_block",
    "selector_market_block",
]
CROSS_HIGH = 0.50
CROSS_LOW = 0.10
DEM_QUINTILE = 0.20
HORIZONS_TRADING_DAYS = [5, 10]


def f(s):
    try:
        return float(s) if s not in ("", None, "nan") else None
    except (ValueError, TypeError):
        return None


def add_trading_days(start_iso: str, n: int) -> str:
    d = date.fromisoformat(start_iso)
    added = 0
    while added < n:
        d = d + timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d.isoformat()


def load_prices_for_dates(needed_dates):
    """Return {(ticker, date): close}."""
    out = {}
    needed = set(needed_dates)
    with open(PRICE_FILE) as fh:
        for r in csv.DictReader(fh):
            d = r["date"][:10]
            if d in needed:
                p = f(r["close"])
                if p is not None:
                    out[(r["ticker"], d)] = p
    return out


def find_clean_snapshots():
    dates = []
    for p in sorted(SNAP_DIR.iterdir()):
        if not (p.is_dir() and p.name[:4].isdigit() and len(p.name) == 10 and "backup" not in p.name):
            continue
        rk = p / "rankings.csv"
        if not rk.exists():
            continue
        with open(rk) as fh:
            cols = next(csv.reader(fh))
        if all(c in cols for c in INDEPENDENT_SIGNALS + ["selector_score", "actionable_rank"]):
            dates.append(p.name)
    return dates


def load_snapshot(date_iso: str):
    rk = SNAP_DIR / date_iso / "rankings.csv"
    with open(rk) as fh:
        rows = [dict(r) for r in csv.DictReader(fh)]
    universe = []
    for r in rows:
        rec = {"ticker": r["ticker"], "selector_score": f(r.get("selector_score"))}
        for col in INDEPENDENT_SIGNALS:
            rec[col] = f(r.get(col))
        universe.append(rec)
    return universe


def percentile_arrays(universe):
    arrs = {}
    for col in INDEPENDENT_SIGNALS:
        vals = [u[col] for u in universe if u.get(col) is not None]
        if len(vals) >= 50:
            arrs[col] = sorted(vals)
    return arrs


def percentile_of(arrs, col, x):
    a = arrs.get(col)
    if a is None or x is None:
        return None
    below = sum(1 for v in a if v < x)
    return below / len(a)


def bucket(selector_pct, agreement_score):
    if selector_pct is None or agreement_score is None:
        return "UNDEF"
    if selector_pct >= 1 - DEM_QUINTILE:
        dem = "H"
    elif selector_pct <= DEM_QUINTILE:
        dem = "L"
    else:
        dem = "M"
    if agreement_score >= CROSS_HIGH:
        cs = "H"
    elif agreement_score <= CROSS_LOW:
        cs = "L"
    else:
        cs = "M"
    if dem == "M" or cs == "M":
        return "MIDDLE"
    return f"{dem}{cs}"


def main():
    snapshots = find_clean_snapshots()
    print(f"Clean-schema snapshots found: {len(snapshots)} ({snapshots[0]} → {snapshots[-1]})")

    # Collect all observations (ticker, snapshot_date, bucket, return_5d, return_10d, xbi_5d, xbi_10d)
    obs = []
    needed_dates = set()
    for d in snapshots:
        needed_dates.add(d)
        for h in HORIZONS_TRADING_DAYS:
            needed_dates.add(add_trading_days(d, h))
    prices = load_prices_for_dates(needed_dates)

    today = max(snapshots)
    skipped_horizon = {h: 0 for h in HORIZONS_TRADING_DAYS}

    for snap_date in snapshots:
        universe = load_snapshot(snap_date)
        rankable = [u for u in universe if u["selector_score"] is not None]
        n = len(rankable)
        if n < 50:
            continue
        sorted_scores = sorted([u["selector_score"] for u in rankable])
        score_to_pct = {s: (i + 1) / n for i, s in enumerate(sorted_scores)}

        arrs = percentile_arrays(rankable)

        for u in rankable:
            t = u["ticker"]
            sp = score_to_pct.get(u["selector_score"])
            # agreement
            n_top = 0
            n_avail = 0
            for col in arrs:
                v = u.get(col)
                if v is None:
                    continue
                n_avail += 1
                pct = percentile_of(arrs, col, v)
                if pct is not None and pct >= 0.80:
                    n_top += 1
            ag = n_top / n_avail if n_avail > 0 else None
            b = bucket(sp, ag)
            p0 = prices.get((t, snap_date))
            row = {
                "ticker": t,
                "snap_date": snap_date,
                "selector_pct": sp,
                "agreement_score": ag,
                "bucket": b,
                "T0_close": p0,
            }
            for h in HORIZONS_TRADING_DAYS:
                tgt = add_trading_days(snap_date, h)
                ph = prices.get((t, tgt))
                xh = prices.get(("XBI", tgt))
                p_xbi0 = prices.get(("XBI", snap_date))
                if p0 is not None and ph is not None:
                    row[f"ret_{h}d"] = ph / p0 - 1.0
                else:
                    row[f"ret_{h}d"] = None
                    skipped_horizon[h] += 1
                if p_xbi0 is not None and xh is not None:
                    row[f"xbi_ret_{h}d"] = xh / p_xbi0 - 1.0
                else:
                    row[f"xbi_ret_{h}d"] = None
            obs.append(row)

    # Aggregate per bucket per horizon
    def agg(rows, ret_key, xbi_key):
        rs = [r[ret_key] for r in rows if r.get(ret_key) is not None]
        xs = [r[xbi_key] for r in rows if r.get(xbi_key) is not None]
        if not rs:
            return {"n": 0}
        rs_sorted = sorted(rs)
        return {
            "n_obs": len(rs),
            "n_unique_tickers": len({r["ticker"] for r in rows if r.get(ret_key) is not None}),
            "n_snapshots": len({r["snap_date"] for r in rows if r.get(ret_key) is not None}),
            "mean_return": round(statistics.mean(rs), 6),
            "median_return": round(statistics.median(rs), 6),
            "p10": round(rs_sorted[int(0.1 * len(rs))], 6) if len(rs) > 10 else None,
            "p90": round(rs_sorted[int(0.9 * len(rs))], 6) if len(rs) > 10 else None,
            "hit_rate": round(sum(1 for r in rs if r > 0) / len(rs), 4),
            "mean_xbi": round(statistics.mean(xs), 6) if xs else None,
            "mean_excess_vs_xbi": (round(statistics.mean(rs) - statistics.mean(xs), 6) if xs else None),
            "max_return_ticker": max(
                ((r["ticker"], r[ret_key]) for r in rows if r.get(ret_key) is not None),
                key=lambda x: x[1],
                default=(None, None),
            ),
            "min_return_ticker": min(
                ((r["ticker"], r[ret_key]) for r in rows if r.get(ret_key) is not None),
                key=lambda x: x[1],
                default=(None, None),
            ),
        }

    buckets = ["HH", "HL", "LH", "LL"]
    by_bucket = {}
    for b in buckets:
        rows_in = [r for r in obs if r["bucket"] == b]
        by_bucket[b] = {
            "5d": agg(rows_in, "ret_5d", "xbi_ret_5d"),
            "10d": agg(rows_in, "ret_10d", "xbi_ret_10d"),
        }

    # MIDDLE for context
    rows_mid = [r for r in obs if r["bucket"] == "MIDDLE"]
    by_bucket["MIDDLE"] = {
        "5d": agg(rows_mid, "ret_5d", "xbi_ret_5d"),
        "10d": agg(rows_mid, "ret_10d", "xbi_ret_10d"),
    }

    out = {
        "as_of": today,
        "schema_window": {"first": snapshots[0], "last": snapshots[-1], "n_snapshots": len(snapshots)},
        "definitions": {
            "DEM_high": f"top {DEM_QUINTILE:.0%} by selector_score",
            "DEM_low": f"bottom {DEM_QUINTILE:.0%} by selector_score",
            "cross_signal_high": f"agreement_score >= {CROSS_HIGH}",
            "cross_signal_low": f"agreement_score <= {CROSS_LOW}",
            "horizons_trading_days": HORIZONS_TRADING_DAYS,
            "independent_signals_excluded": "coinvest_score_z, inst_delta_z, institutional block (B6 components)",
        },
        "bucket_aggregates": by_bucket,
        "labeling": "SCHEMA-ERA DESCRIPTIVE BEHAVIOR — NOT historical alpha evidence.",
        "caveats": [
            "Only 21 snapshots over ~26 days. Observations are heavily overlapping (same tickers reappear in adjacent snapshots).",
            "Effective independent N is far smaller than face n_obs; do not interpret as a population mean.",
            "Standing policy: 'Forward monitoring is the only valid evidence for alpha validation' (memory: historical_backtest_invalidated_2026_04_17).",
            "20d/60d horizons not computable in this window.",
            "Snapshots include the post-2026-04-25 cohort-rebuild contamination period (04-25 to 04-28). inst_delta_z is excluded from agreement_score so cohort effect on the bucket assignment is small, but DEM_high tickers in those snapshots may still be cohort-influenced.",
            "Conclusion language: descriptive only. No alpha conclusion drawn.",
        ],
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_json = OUT_DIR / "descriptive_audit_2026-04-28.json"
    with open(out_json, "w") as fh:
        json.dump(out, fh, indent=2, default=str)

    # Markdown
    lines = [
        "# Cross-signal × DEM bucket audit — schema-era descriptive (2026-04-03 → 2026-04-28)\n",
        "**Labeling**: SCHEMA-ERA DESCRIPTIVE BEHAVIOR — **not historical alpha evidence**.\n",
        f"**Snapshots used**: {len(snapshots)} (first {snapshots[0]}, last {snapshots[-1]}).",
        f"**Horizons**: {HORIZONS_TRADING_DAYS} trading days. **20d/60d not computable in this window.**\n",
        "## Bucket definitions",
        f"- **DEM-high** = top {DEM_QUINTILE:.0%} by `selector_score`",
        f"- **DEM-low** = bottom {DEM_QUINTILE:.0%} by `selector_score`",
        f"- **cross-signal-high** = `agreement_score >= {CROSS_HIGH}`",
        f"- **cross-signal-low** = `agreement_score <= {CROSS_LOW}`",
        "- Independent signals exclude B6 components (`coinvest_score_z`, `inst_delta_z`) and institutional block.\n",
        "## Bucket aggregates\n",
    ]
    for h in HORIZONS_TRADING_DAYS:
        lines.append(f"### {h}d forward returns\n")
        lines.append("| Bucket | n_obs | unique tickers | snapshots | mean | median | hit | mean − XBI |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for b in buckets + ["MIDDLE"]:
            a = by_bucket[b][f"{h}d"]
            if a.get("n_obs", 0) == 0:
                lines.append(f"| {b} | 0 |  |  |  |  |  |  |")
                continue
            lines.append(
                f"| {b} | {a['n_obs']} | {a['n_unique_tickers']} | {a['n_snapshots']} | "
                f"{a['mean_return']:+.4f} | {a['median_return']:+.4f} | {a['hit_rate']:.2f} | "
                f"{a.get('mean_excess_vs_xbi') or 0:+.4f} |"
            )
        lines.append("")
    lines.append("## Caveats\n")
    for c in out["caveats"]:
        lines.append(f"- {c}")
    lines.append("\n## Conclusion\n")
    lines.append(
        "**No historical alpha conclusion drawn.** Forward shadows (`inst_delta_forward_shadow`, `cross_signal_forward_shadow`) are the only valid validators. Re-evaluate at h20d (2026-05-26) and h60d (2026-07-21)."
    )

    out_md = OUT_DIR / "descriptive_audit_2026-04-28.md"
    with open(out_md, "w") as fh:
        fh.write("\n".join(lines))

    # Console summary
    print(f"\nwrote {out_md}")
    print(f"wrote {out_json}\n")
    for h in HORIZONS_TRADING_DAYS:
        print(f"=== {h}d returns by bucket ===")
        print(f"  {'bucket':<8} {'n_obs':>6} {'mean':>8} {'median':>8} {'hit':>6} {'excess_xbi':>10}")
        for b in buckets + ["MIDDLE"]:
            a = by_bucket[b][f"{h}d"]
            if a.get("n_obs", 0) == 0:
                print(f"  {b:<8} {0:>6}")
                continue
            print(
                f"  {b:<8} {a['n_obs']:>6} {a['mean_return']:>+8.4f} {a['median_return']:>+8.4f} "
                f"{a['hit_rate']:>6.2f} {a.get('mean_excess_vs_xbi') or 0:>+10.4f}"
            )
        print()
    print("No historical alpha conclusion drawn.")


if __name__ == "__main__":
    main()

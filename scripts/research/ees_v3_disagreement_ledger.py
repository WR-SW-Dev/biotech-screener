"""
EES v3 disagreement ledger — diagnostic-only snapshot analysis.

Classifies names into 4 buckets based on ranker vs EES v3 alignment:
  HH: ranker_high / ees_v3_high  — both agree (high)
  HL: ranker_high / ees_v3_low   — ranker likes, EES v3 doesn't
  LH: ranker_low  / ees_v3_high  — EES v3 likes, ranker doesn't
  LL: ranker_low  / ees_v3_low   — both reject

Threshold: median split on each score (all names classified, no mid zone).
Optionally joins scientific_cartography features (disease_crowding, stage_crowding).
Optionally runs historical bucket IC over PIT snapshots.

Usage:
    python3 scripts/research/ees_v3_disagreement_ledger.py --as-of-date 2026-06-25
    python3 scripts/research/ees_v3_disagreement_ledger.py --as-of-date 2026-06-25 --pit-analysis

GOVERNANCE: DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

GOVERNANCE = "DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE"
MIN_PAIRS = 5
PIT_HORIZONS = [21, 63]

BUCKET_LABELS = ["HH", "HL", "LH", "LL"]
BUCKET_DESCRIPTIONS = {
    "HH": "ranker_high / ees_v3_high — both agree (high)",
    "HL": "ranker_high / ees_v3_low — ranker likes, EES v3 disagrees",
    "LH": "ranker_low / ees_v3_high — EES v3 likes, ranker ignores",
    "LL": "ranker_low / ees_v3_low — both reject",
}


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _snapshots_dir() -> Path:
    return _repo_root() / "data" / "snapshots"


def _pit_snapshots_dir() -> Path:
    return _repo_root() / "data" / "snapshots_pit_v2"


def _price_csv() -> Path:
    return _repo_root() / "production_data" / "price_history.csv"


def _cartography_dir() -> Path:
    return _repo_root() / "artifacts" / "scientific_cartography"


def _shadow_dir() -> Path:
    return _repo_root() / "artifacts" / "shadow"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sf(v: object) -> Optional[float]:
    if v is None or v == "" or v == "None" or v == "nan":
        return None
    try:
        f = float(v)  # type: ignore[arg-type]
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def _sb(v: object) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes")


def _has_priced_move(row: dict) -> bool:
    val = row.get("priced_move_pct", "")
    if not val or val in ("None", "nan", "0", "0.0", ""):
        return False
    try:
        f = float(val)
        return not math.isnan(f) and f != 0.0
    except (ValueError, TypeError):
        return False


def _median(values: list[float]) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def _mean(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _bucket(
    final_score: Optional[float], ees_v3_score: Optional[float], fs_median: float, v3_median: float
) -> Optional[str]:
    if final_score is None or ees_v3_score is None:
        return None
    fs_high = final_score > fs_median
    v3_high = ees_v3_score > v3_median
    if fs_high and v3_high:
        return "HH"
    if fs_high and not v3_high:
        return "HL"
    if not fs_high and v3_high:
        return "LH"
    return "LL"


# ---------------------------------------------------------------------------
# Rankings loader
# ---------------------------------------------------------------------------


def load_rankings(snap_date: str, snap_root: Optional[Path] = None) -> list[dict]:
    root = snap_root or _snapshots_dir()
    path = root / snap_date / "rankings.csv"
    if not path.exists():
        return []
    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Cartography join
# ---------------------------------------------------------------------------


def load_cartography_features() -> dict[str, dict]:
    """Load latest landscape_features.jsonl and return {ticker: {field: value}}."""
    cdir = _cartography_dir()
    if not cdir.exists():
        return {}
    # Find latest run directory with landscape_features.jsonl
    candidates = sorted(
        [d for d in cdir.iterdir() if d.is_dir() and (d / "landscape_features.jsonl").exists()],
        key=lambda d: d.name,
        reverse=True,
    )
    if not candidates:
        return {}
    lf_path = candidates[0] / "landscape_features.jsonl"
    log.info("Loading cartography from: %s", lf_path)

    by_ticker: dict[str, list[dict]] = defaultdict(list)
    with open(lf_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ticker = rec.get("ticker", "")
            if ticker:
                by_ticker[ticker].append(rec)

    result = {}
    for ticker, recs in by_ticker.items():
        # Aggregate across programs: take max crowding, mean white_space, sum counts
        disease_counts = [_sf(r.get("disease_program_count")) for r in recs]
        stage_crowding = [_sf(r.get("stage_crowding_score")) for r in recs]
        disease_counts_valid = [v for v in disease_counts if v is not None]
        stage_crowding_valid = [v for v in stage_crowding if v is not None]
        result[ticker] = {
            "disease_program_count_max": max(disease_counts_valid) if disease_counts_valid else None,
            "stage_crowding_score_max": max(stage_crowding_valid) if stage_crowding_valid else None,
            "n_programs": len(recs),
        }
    log.info("Loaded cartography for %d tickers", len(result))
    return result


# ---------------------------------------------------------------------------
# Current-snapshot bucket analysis
# ---------------------------------------------------------------------------


def analyze_snapshot(rows: list[dict], cartography: dict) -> dict:
    """Classify all names into buckets and compute per-bucket diagnostics."""
    fs_vals = [_sf(r.get("final_score")) for r in rows]
    v3_vals = [_sf(r.get("ees_v3_score")) for r in rows]

    fs_valid = [v for v in fs_vals if v is not None]
    v3_valid = [v for v in v3_vals if v is not None]

    if not fs_valid or not v3_valid:
        return {"error": "insufficient score data"}

    fs_median = _median(fs_valid)
    v3_median = _median(v3_valid)

    log.info("Median final_score=%.4f | median ees_v3_score=%.4f", fs_median, v3_median)

    # Classify
    classified = []
    for r in rows:
        fs = _sf(r.get("final_score"))
        v3 = _sf(r.get("ees_v3_score"))
        bkt = _bucket(fs, v3, fs_median, v3_median)
        cart = cartography.get(r.get("ticker", ""), {})
        classified.append(
            {
                "ticker": r.get("ticker", ""),
                "bucket": bkt,
                "final_score": fs,
                "ees_v3_score": v3,
                "ranker_active": _sb(r.get("ranker_active", False)),
                "market_cap_bucket": r.get("market_cap_bucket", ""),
                "market_cap_mm": _sf(r.get("market_cap_mm")),
                "lead_program_phase": _sf(r.get("lead_program_phase")),
                "catalyst_days": _sf(r.get("catalyst_days")),
                "catalyst_family": r.get("catalyst_family", ""),
                "catalyst_event_type": r.get("catalyst_event_type", ""),
                "priced_move_available": _has_priced_move(r),
                "priced_move_pct": _sf(r.get("priced_move_pct")),
                "implied_event_move": _sf(r.get("implied_event_move")),
                "disease_program_count_max": cart.get("disease_program_count_max"),
                "stage_crowding_score_max": cart.get("stage_crowding_score_max"),
                "n_programs": cart.get("n_programs"),
            }
        )

    # Per-bucket summaries
    bucket_stats = {}
    for bkt in BUCKET_LABELS:
        bkt_rows = [c for c in classified if c["bucket"] == bkt]
        tickers = [c["ticker"] for c in bkt_rows]
        n = len(bkt_rows)

        cat_days = [c["catalyst_days"] for c in bkt_rows if c["catalyst_days"] is not None]
        mkt_cap = [c["market_cap_mm"] for c in bkt_rows if c["market_cap_mm"] is not None]
        n_priced = sum(1 for c in bkt_rows if c["priced_move_available"])
        n_active = sum(1 for c in bkt_rows if c["ranker_active"])

        # Market cap distribution
        mcap_buckets: dict[str, int] = defaultdict(int)
        for c in bkt_rows:
            mcap_buckets[c["market_cap_bucket"] or "unknown"] += 1

        # Catalyst family distribution
        cat_families: dict[str, int] = defaultdict(int)
        for c in bkt_rows:
            cat_families[c["catalyst_family"] or "none"] += 1

        # Cartography stats
        crowding = [c["disease_program_count_max"] for c in bkt_rows if c["disease_program_count_max"] is not None]
        stage_cr = [c["stage_crowding_score_max"] for c in bkt_rows if c["stage_crowding_score_max"] is not None]

        bucket_stats[bkt] = {
            "description": BUCKET_DESCRIPTIONS[bkt],
            "count": n,
            "tickers": tickers,
            "n_ranker_active": n_active,
            "n_priced_move_available": n_priced,
            "pct_priced_move_available": round(n_priced / n * 100, 1) if n else None,
            "catalyst_days_mean": round(_mean(cat_days), 1) if cat_days else None,
            "catalyst_days_median": round(_median(cat_days), 1) if cat_days else None,
            "market_cap_mm_mean": round(_mean(mkt_cap), 1) if mkt_cap else None,
            "market_cap_bucket_dist": dict(sorted(mcap_buckets.items())),
            "catalyst_family_dist": dict(sorted(cat_families.items(), key=lambda kv: -kv[1])),
            "disease_program_count_mean": round(_mean(crowding), 2) if crowding else None,
            "stage_crowding_score_mean": round(_mean(stage_cr), 3) if stage_cr else None,
            "n_with_cartography": len(crowding),
            # Score stats within bucket
            "final_score_mean": (
                round(_mean([c["final_score"] for c in bkt_rows if c["final_score"] is not None]), 4)
                if bkt_rows
                else None
            ),
            "ees_v3_score_mean": (
                round(_mean([c["ees_v3_score"] for c in bkt_rows if c["ees_v3_score"] is not None]), 4)
                if bkt_rows
                else None
            ),
        }

    return {
        "n_total": len(classified),
        "n_classified": sum(1 for c in classified if c["bucket"] is not None),
        "fs_median_threshold": round(fs_median, 4),
        "v3_median_threshold": round(v3_median, 4),
        "buckets": bucket_stats,
        "all_names": classified,
    }


# ---------------------------------------------------------------------------
# PIT historical bucket IC analysis
# ---------------------------------------------------------------------------


def load_price_history() -> tuple[dict[str, dict[str, float]], list[str]]:
    path = _price_csv()
    if not path.exists():
        log.warning("Price history not found: %s", path)
        return {}, []
    prices: dict[str, dict[str, float]] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "")
            d = row.get("date", "")
            c_str = row.get("close", "")
            if not t or not d or not c_str:
                continue
            try:
                prices.setdefault(t, {})[d] = float(c_str)
            except (ValueError, TypeError):
                continue
    all_dates = sorted(set(d for td in prices.values() for d in td))
    return prices, all_dates


def _forward_return(ticker: str, snap_date: str, horizon: int, prices: dict, sorted_dates: list) -> Optional[float]:
    tp = prices.get(ticker, {})
    anchor_d = (
        snap_date if snap_date in tp else next((d for d in reversed(sorted_dates) if d <= snap_date and d in tp), None)
    )
    if anchor_d is None:
        return None
    anchor_c = tp[anchor_d]
    try:
        idx = sorted_dates.index(anchor_d)
    except ValueError:
        return None
    fwd_idx = idx + horizon
    if fwd_idx >= len(sorted_dates):
        return None
    fwd_c = tp.get(sorted_dates[fwd_idx])
    if fwd_c is None or anchor_c == 0:
        return None
    return (fwd_c - anchor_c) / anchor_c


def run_pit_analysis(prices: dict, sorted_dates: list) -> dict:
    """Run bucket IC over all PIT snapshots."""
    pit_root = _pit_snapshots_dir()
    if not pit_root.exists():
        return {"error": "PIT snapshots not found"}

    snap_dates = sorted(d.name for d in pit_root.iterdir() if d.is_dir() and (d / "rankings.csv").exists())
    log.info("PIT analysis: %d snapshots", len(snap_dates))

    # Collect per-snap classified rows
    all_observations: list[dict] = []
    for snap_date in snap_dates:
        rows = load_rankings(snap_date, pit_root)
        if not rows:
            continue

        fs_vals = [_sf(r.get("final_score")) for r in rows]
        v3_vals = [_sf(r.get("ees_v3_score")) for r in rows]
        fs_valid = [v for v in fs_vals if v is not None]
        v3_valid = [v for v in v3_vals if v is not None]
        if len(fs_valid) < 5 or len(v3_valid) < 5:
            continue

        fs_med = _median(fs_valid)
        v3_med = _median(v3_valid)

        for r in rows:
            fs = _sf(r.get("final_score"))
            v3 = _sf(r.get("ees_v3_score"))
            bkt = _bucket(fs, v3, fs_med, v3_med)
            if bkt is None:
                continue
            ticker = r.get("ticker", "")
            for hz in PIT_HORIZONS:
                actual = _forward_return(ticker, snap_date, hz, prices, sorted_dates)
                xbi = _forward_return("XBI", snap_date, hz, prices, sorted_dates)
                excess = (actual - xbi) if actual is not None and xbi is not None else None
                all_observations.append(
                    {
                        "snap_date": snap_date,
                        "ticker": ticker,
                        "bucket": bkt,
                        "final_score": fs,
                        "ees_v3_score": v3,
                        "horizon": hz,
                        "excess_return": excess,
                    }
                )

    if not all_observations:
        return {"error": "no observations computed"}

    # Aggregate: per bucket, per horizon — mean excess return and count
    result_by_bucket: dict[str, dict] = {}
    for bkt in BUCKET_LABELS:
        result_by_bucket[bkt] = {}
        for hz in PIT_HORIZONS:
            obs = [
                o
                for o in all_observations
                if o["bucket"] == bkt and o["horizon"] == hz and o["excess_return"] is not None
            ]
            excess_vals = [o["excess_return"] for o in obs]
            result_by_bucket[bkt][f"hz_{hz}d"] = {
                "n_obs": len(obs),
                "mean_excess_return": round(_mean(excess_vals), 4) if excess_vals else None,
                "hit_rate": round(sum(1 for v in excess_vals if v > 0) / len(excess_vals), 3) if excess_vals else None,
            }

    # Also compute: per bucket, how well does ees_v3_score predict excess returns within bucket?
    for bkt in BUCKET_LABELS:
        for hz in PIT_HORIZONS:
            obs = [
                o
                for o in all_observations
                if o["bucket"] == bkt and o["horizon"] == hz and o["excess_return"] is not None
            ]
            if len(obs) >= MIN_PAIRS:
                by_date: dict[str, list] = defaultdict(list)
                for o in obs:
                    by_date[o["snap_date"]].append((o["ees_v3_score"], o["excess_return"]))
                ics = []
                for pairs in by_date.values():
                    if len(pairs) < MIN_PAIRS:
                        continue
                    xs, ys = zip(*pairs)
                    ic = _spearman_ic(list(xs), list(ys))
                    if ic is not None:
                        ics.append(ic)
                result_by_bucket[bkt][f"hz_{hz}d"]["within_bucket_ic"] = {
                    "mean_ic": round(sum(ics) / len(ics), 4) if ics else None,
                    "n_dates": len(ics),
                }

    return {
        "n_snapshots": len(snap_dates),
        "n_total_observations": len(all_observations),
        "bucket_performance": result_by_bucket,
    }


def _rank(xs: list[float]) -> list[float]:
    sorted_vals = sorted(enumerate(xs), key=lambda t: t[1])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(sorted_vals):
        j = i
        while j < len(sorted_vals) - 1 and sorted_vals[j + 1][1] == sorted_vals[i][1]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[sorted_vals[k][0]] = avg_rank
        i = j + 1
    return ranks


def _spearman_ic(xs: list[float], ys: list[float]) -> Optional[float]:
    n = len(xs)
    if n < MIN_PAIRS:
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    vx = sum((r - mx) ** 2 for r in rx)
    vy = sum((r - my) ** 2 for r in ry)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="EES v3 disagreement ledger — DIAGNOSTIC_ONLY")
    p.add_argument("--as-of-date", required=True, dest="as_of_date", help="Snapshot date: YYYY-MM-DD")
    p.add_argument(
        "--pit-analysis",
        action="store_true",
        dest="pit_analysis",
        help="Run historical bucket IC over all PIT snapshots (slow)",
    )
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    as_of_date = args.as_of_date
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    log.info("=== EES v3 Disagreement Ledger ===")
    log.info("as_of_date=%s | pit_analysis=%s | dry_run=%s", as_of_date, args.pit_analysis, args.dry_run)
    log.info("GOVERNANCE: %s", GOVERNANCE)

    # 1. Load rankings
    rows = load_rankings(as_of_date)
    if not rows:
        log.error("No rankings found for %s", as_of_date)
        return 1
    log.info("Loaded %d names", len(rows))

    # 2. Load cartography
    cartography = load_cartography_features()

    # 3. Analyze current snapshot
    snapshot_analysis = analyze_snapshot(rows, cartography)

    # Log bucket summary
    for bkt in BUCKET_LABELS:
        bs = snapshot_analysis["buckets"].get(bkt, {})
        log.info(
            "Bucket %s (%s): n=%d | ranker_active=%d | priced_move=%d",
            bkt,
            BUCKET_DESCRIPTIONS[bkt],
            bs.get("count", 0),
            bs.get("n_ranker_active", 0),
            bs.get("n_priced_move_available", 0),
        )

    # 4. PIT analysis (optional)
    pit_analysis_result: Optional[dict] = None
    if args.pit_analysis:
        log.info("Running PIT bucket analysis over all snapshots...")
        prices, sorted_dates = load_price_history()
        if prices:
            pit_analysis_result = run_pit_analysis(prices, sorted_dates)
            log.info("PIT analysis complete: %d total observations", pit_analysis_result.get("n_total_observations", 0))
        else:
            log.warning("Skipping PIT analysis — no price data")

    # 5. Assemble output
    output = {
        "as_of": as_of_date,
        "run_ts": run_ts,
        "governance": GOVERNANCE,
        "threshold_method": "median_split",
        "snapshot_analysis": snapshot_analysis,
        "pit_analysis": pit_analysis_result,
        "interpretation_note": (
            "HH/LL = agreement. HL = ranker high but EES v3 disagrees — investigate "
            "whether EES v3 should veto or simply flag. LH = EES v3 likes but ranker "
            "ignores — investigate whether EES v3 finds missed upside."
        ),
    }

    if args.dry_run:
        log.info("DRY RUN — output not written")
        print(json.dumps(output, indent=2)[:2000])
        return 0

    out_path = _shadow_dir() / f"ees_v3_disagreement_{as_of_date}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
        f.write("\n")
    log.info("Output written: %s", out_path)

    log.info("=== Done === DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())

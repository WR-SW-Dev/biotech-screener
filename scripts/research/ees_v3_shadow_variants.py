"""
EES v3 shadow variant monitor — diagnostic-only, append-only ledger.

Tracks 5 diagnostic variants of EES v3 to decompose which components carry alpha:
  ees_v3_core              — stored ees_v3_score (0.70*z(misprice) + 0.30*z(expected))
  ees_v3_expected_move_only — z(expected_move) only, full universe
  ees_v3_misprice_only      — z(misprice) within priced_move_pct-covered names; None elsewhere
  ees_v3_no_misprice        — same as expected_move_only in rank space; stored for empirical confirmation
  ees_v3_native_high_coverage — full 0.70/0.30 composite, z-scored within high-coverage subset only

True misprice_available derived from priced_move_pct non-null (not from ees_v3_misprice_available
flag, which is incorrectly set to 1 for all names when conditional_misprice_score returns 0.0).

Usage:
    python3 scripts/research/ees_v3_shadow_variants.py --as-of-date YYYY-MM-DD
    python3 scripts/research/ees_v3_shadow_variants.py --as-of-date YYYY-MM-DD --dry-run

GOVERNANCE: DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE | NO_CRON
No ranker/selector/sizing/final_score/gate/snapshot/portfolio changes.
No model promotion. No freeze lift. No live data fetch.
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

# ---------------------------------------------------------------------------
# Governance constants
# ---------------------------------------------------------------------------

GOVERNANCE = "DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE | NO_CRON"
LEDGER_VERSION = "1.0"
MONITOR_VERSION = "1.0"
HORIZONS = [5, 10, 20]
OBS_GATE_5D = 20
OBS_GATE_10D = 10
OBS_GATE_20D = 20
MIN_PAIRS_PER_DATE = 5
TOP_N_OVERLAP = 20  # top-N names for overlap computation

VARIANTS = [
    "ees_v3_core",
    "ees_v3_expected_move_only",
    "ees_v3_misprice_only",
    "ees_v3_no_misprice",
    "ees_v3_native_high_coverage",
]

EPS = 1e-6


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _snapshots_dir() -> Path:
    return _repo_root() / "data" / "snapshots"


def _shadow_dir() -> Path:
    return _repo_root() / "artifacts" / "shadow"


def _price_csv() -> Path:
    return _repo_root() / "production_data" / "price_history.csv"


def ledger_path() -> Path:
    return _shadow_dir() / "ees_v3_shadow_variants_ledger.jsonl"


def summary_path(as_of_date: str) -> Path:
    return _shadow_dir() / f"ees_v3_shadow_variants_summary_{as_of_date}.json"


# ---------------------------------------------------------------------------
# Numeric helpers
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


def _is_settled(v: object) -> bool:
    if v is True or v == 1:
        return True
    if isinstance(v, str) and v.strip().lower() == "true":
        return True
    return False


def _has_priced_move(row: dict) -> bool:
    """True when priced_move_pct is a real non-zero value."""
    val = row.get("priced_move_pct", "")
    if not val or val in ("None", "nan", "0", "0.0", ""):
        return False
    try:
        f = float(val)
        return not math.isnan(f) and f != 0.0
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Cross-sectional z-score helpers
# ---------------------------------------------------------------------------


def _z_full(values: list[Optional[float]]) -> list[float]:
    """Z-score full vector; None/NaN → 0.0 (neutral)."""
    valid = [v for v in values if v is not None]
    if len(valid) < 3:
        return [0.0] * len(values)
    m = sum(valid) / len(valid)
    var = sum((v - m) ** 2 for v in valid) / len(valid)
    s = math.sqrt(var)
    if s < EPS:
        return [0.0] * len(values)
    return [(v - m) / s if v is not None else 0.0 for v in values]


def _z_subset_or_none(values: list[Optional[float]]) -> list[Optional[float]]:
    """Z-score only non-None values; None positions remain None."""
    indexed_valid = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(indexed_valid) < 3:
        return [None if v is None else 0.0 for v in values]
    vals = [v for _, v in indexed_valid]
    m = sum(vals) / len(vals)
    var = sum((v - m) ** 2 for v in vals) / len(vals)
    s = math.sqrt(var)
    if s < EPS:
        return [None if v is None else 0.0 for v in values]
    result: list[Optional[float]] = [None] * len(values)
    for i, v in indexed_valid:
        result[i] = (v - m) / s
    return result


# ---------------------------------------------------------------------------
# Variant computation
# ---------------------------------------------------------------------------


def compute_variant_scores(rows: list[dict]) -> dict[str, dict]:
    """
    Compute 5 diagnostic variant scores from raw rankings columns.
    Returns: {ticker: {variant_name: Optional[float], "misprice_available": bool}}
    """
    tickers = [r.get("ticker", "") for r in rows]
    misprice_raw = [_sf(r.get("conditional_misprice_score")) for r in rows]
    expected_raw = [_sf(r.get("conditional_expected_move")) for r in rows]
    core_scores = [_sf(r.get("ees_v3_score")) for r in rows]
    misprice_avail = [_has_priced_move(r) for r in rows]

    # v1: stored composite (no recomputation needed)
    v1 = core_scores

    # v2: expected_move only, full universe, NaN→0.0
    v2 = _z_full(expected_raw)

    # v3: misprice only, within high-coverage subset; None for uncovered
    misprice_for_subset = [m if misprice_avail[i] else None for i, m in enumerate(misprice_raw)]
    v3 = _z_subset_or_none(misprice_for_subset)

    # v4: no_misprice — rank-equivalent to v2 (stored separately to confirm empirically)
    v4 = list(v2)

    # v5: full 0.70/0.30 composite, z-scored within high-coverage subset; None for uncovered
    hi_idx = [i for i, a in enumerate(misprice_avail) if a]
    if len(hi_idx) >= 3:
        hi_m = [misprice_raw[i] for i in hi_idx]
        hi_e = [expected_raw[i] for i in hi_idx]
        hi_mz = _z_full(hi_m)
        hi_ez = _z_full(hi_e)
        hi_composite = {i: 0.70 * hi_mz[k] + 0.30 * hi_ez[k] for k, i in enumerate(hi_idx)}
        v5: list[Optional[float]] = [hi_composite.get(i) for i in range(len(rows))]
    else:
        v5 = [None] * len(rows)

    n_avail = sum(misprice_avail)
    n_total = len(rows)
    log.info(
        "Variant scores: n=%d | misprice_available=%d (%.0f%%) | v3 non-null=%d | v5 non-null=%d",
        n_total,
        n_avail,
        n_avail / n_total * 100 if n_total else 0,
        sum(1 for v in v3 if v is not None),
        sum(1 for v in v5 if v is not None),
    )

    return {
        ticker: {
            "ees_v3_core": v1[i],
            "ees_v3_expected_move_only": v2[i],
            "ees_v3_misprice_only": v3[i],
            "ees_v3_no_misprice": v4[i],
            "ees_v3_native_high_coverage": v5[i],
            "misprice_available": misprice_avail[i],
        }
        for i, ticker in enumerate(tickers)
    }


# ---------------------------------------------------------------------------
# Rankings loader
# ---------------------------------------------------------------------------


def load_rankings(snap_date: str) -> list[dict]:
    path = _snapshots_dir() / snap_date / "rankings.csv"
    if not path.exists():
        log.warning("rankings.csv not found: %s", path)
        return []
    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    log.info("Loaded rankings: %s — %d rows", snap_date, len(rows))
    return rows


# ---------------------------------------------------------------------------
# Price loading
# ---------------------------------------------------------------------------


def load_prices() -> tuple[dict[str, dict[str, float]], list[str]]:
    """Load full production price history. Returns ({ticker: {date: close}}, sorted_dates)."""
    path = _price_csv()
    if not path.exists():
        log.error("Price history not found: %s", path)
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
                c = float(c_str)
            except (ValueError, TypeError):
                continue
            if t not in prices:
                prices[t] = {}
            prices[t][d] = c
    all_dates: set[str] = set()
    for td in prices.values():
        all_dates.update(td.keys())
    sorted_dates = sorted(all_dates)
    log.info("Loaded price history: %d tickers, %d trading dates", len(prices), len(sorted_dates))
    return prices, sorted_dates


def resolve_anchor(
    ticker: str,
    snap_date: str,
    prices: dict[str, dict[str, float]],
    sorted_dates: list[str],
) -> tuple[Optional[float], Optional[str]]:
    tp = prices.get(ticker, {})
    if snap_date in tp:
        return tp[snap_date], snap_date
    candidates = [d for d in sorted_dates if d <= snap_date and d in tp]
    if candidates:
        best = candidates[-1]
        return tp[best], best
    return None, None


def compute_return(
    ticker: str,
    anchor_date: Optional[str],
    horizon: int,
    prices: dict[str, dict[str, float]],
    anchor_close: Optional[float],
    sorted_dates: list[str],
) -> Optional[float]:
    if anchor_date is None or anchor_close is None or anchor_close == 0:
        return None
    try:
        idx = sorted_dates.index(anchor_date)
    except ValueError:
        return None
    fwd_idx = idx + horizon
    if fwd_idx >= len(sorted_dates):
        return None
    fwd_date = sorted_dates[fwd_idx]
    fwd_close = prices.get(ticker, {}).get(fwd_date)
    if fwd_close is None:
        return None
    return (fwd_close - anchor_close) / anchor_close


# ---------------------------------------------------------------------------
# Ledger I/O
# ---------------------------------------------------------------------------


def load_ledger(path: Path) -> tuple[list[dict], set[tuple[str, str]], set[tuple[str, str]]]:
    rows: list[dict] = []
    if path.exists():
        with open(path) as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    log.warning("Ledger parse error at line %d: %s", lineno, exc)
    existing_keys = {(r["snap_date"], r["ticker"]) for r in rows}
    settled_keys = {(r["snap_date"], r["ticker"]) for r in rows if _is_settled(r.get("forward_complete_20d"))}
    log.info(
        "Loaded ledger: %d rows (%d unique keys, %d settled)",
        len(rows),
        len(existing_keys),
        len(settled_keys),
    )
    return rows, existing_keys, settled_keys


def write_ledger(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
    log.info("Ledger written: %d rows → %s", len(rows), path)


# ---------------------------------------------------------------------------
# Row construction
# ---------------------------------------------------------------------------


def make_new_row(
    snap_date: str,
    ranking_row: dict,
    variant_scores: dict,
    prices: dict[str, dict[str, float]],
    sorted_dates: list[str],
    run_ts: str,
) -> dict:
    ticker = ranking_row["ticker"]
    vscores = variant_scores.get(ticker, {})

    anchor_close, anchor_date = resolve_anchor(ticker, snap_date, prices, sorted_dates)
    xbi_close, xbi_date = resolve_anchor("XBI", snap_date, prices, sorted_dates)

    row: dict = {
        "snap_date": snap_date,
        "ticker": ticker,
        # Variant scores
        "ees_v3_core": vscores.get("ees_v3_core"),
        "ees_v3_expected_move_only": vscores.get("ees_v3_expected_move_only"),
        "ees_v3_misprice_only": vscores.get("ees_v3_misprice_only"),
        "ees_v3_no_misprice": vscores.get("ees_v3_no_misprice"),
        "ees_v3_native_high_coverage": vscores.get("ees_v3_native_high_coverage"),
        # Diagnostics
        "misprice_available": vscores.get("misprice_available", False),
        "final_score": _sf(ranking_row.get("final_score")),
        "ranker_active": _sb(ranking_row.get("ranker_active", False)),
        "market_cap_bucket": ranking_row.get("market_cap_bucket", ""),
        "lead_program_phase": _sf(ranking_row.get("lead_program_phase")),
        "catalyst_family": ranking_row.get("catalyst_family", ""),
        "catalyst_days": _sf(ranking_row.get("catalyst_days")),
        # Anchors
        "anchor_date": anchor_date,
        "anchor_close": anchor_close,
        "xbi_anchor_date": xbi_date,
        "xbi_anchor_close": xbi_close,
        # Forward returns (filled by backfill)
        "actual_return_5d": None,
        "xbi_return_5d": None,
        "excess_return_5d": None,
        "forward_complete_5d": False,
        "actual_return_10d": None,
        "xbi_return_10d": None,
        "excess_return_10d": None,
        "forward_complete_10d": False,
        "actual_return_20d": None,
        "xbi_return_20d": None,
        "excess_return_20d": None,
        "forward_complete_20d": False,
        "ledger_version": LEDGER_VERSION,
        "run_ts": run_ts,
    }
    return row


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------


def backfill_open_rows(
    rows: list[dict],
    prices: dict[str, dict[str, float]],
    sorted_dates: list[str],
) -> tuple[list[dict], int, int, int]:
    result = []
    new_5d = new_10d = new_20d = 0

    for raw_row in rows:
        if _is_settled(raw_row.get("forward_complete_20d")):
            result.append(raw_row)
            continue

        row = dict(raw_row)
        ticker = row["ticker"]
        anchor_close = row.get("anchor_close")
        anchor_date = row.get("anchor_date")
        xbi_anchor_close = row.get("xbi_anchor_close")
        xbi_anchor_date = row.get("xbi_anchor_date")

        for hz in HORIZONS:
            cmp_col = f"forward_complete_{hz}d"
            if _is_settled(row.get(cmp_col)):
                continue
            ticker_ret = compute_return(ticker, anchor_date, hz, prices, anchor_close, sorted_dates)
            if ticker_ret is None:
                continue
            row[f"actual_return_{hz}d"] = ticker_ret
            xbi_ret = compute_return("XBI", xbi_anchor_date, hz, prices, xbi_anchor_close, sorted_dates)
            if xbi_ret is not None:
                row[f"xbi_return_{hz}d"] = xbi_ret
                row[f"excess_return_{hz}d"] = ticker_ret - xbi_ret
            else:
                row[f"xbi_return_{hz}d"] = None
                row[f"excess_return_{hz}d"] = None
            row[cmp_col] = True
            if hz == 5:
                new_5d += 1
            elif hz == 10:
                new_10d += 1
            elif hz == 20:
                new_20d += 1

        result.append(row)

    return result, new_5d, new_10d, new_20d


# ---------------------------------------------------------------------------
# IC and summary metrics
# ---------------------------------------------------------------------------


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
    if n < MIN_PAIRS_PER_DATE:
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


def _t_stat(vals: list[float]) -> Optional[float]:
    n = len(vals)
    if n < 3:
        return None
    m = sum(vals) / n
    var = sum((x - m) ** 2 for x in vals) / (n - 1)
    if var == 0:
        return None
    return m / math.sqrt(var / n)


def _rho1(series: list[float]) -> Optional[float]:
    n = len(series)
    if n < 4:
        return None
    m = sum(series) / n
    demeaned = [s - m for s in series]
    var = sum(d**2 for d in demeaned) / n
    if var < EPS:
        return None
    cov1 = sum(demeaned[i] * demeaned[i - 1] for i in range(1, n)) / (n - 1)
    return cov1 / var


def _per_variant_ic(settled_rows: list[dict], variant: str, hz: int) -> Optional[dict]:
    ret_col = f"excess_return_{hz}d"
    by_date: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in settled_rows:
        score = r.get(variant)
        ret = r.get(ret_col)
        if score is None or ret is None:
            continue
        by_date[r["snap_date"]].append((score, ret))

    ics: list[float] = []
    for pairs in by_date.values():
        if len(pairs) < MIN_PAIRS_PER_DATE:
            continue
        xs, ys = zip(*pairs)
        ic = _spearman_ic(list(xs), list(ys))
        if ic is not None:
            ics.append(ic)

    if not ics:
        return None

    n = len(ics)
    m = sum(ics) / n
    rho1 = _rho1(ics)
    n_eff = n * (1 - rho1) / (1 + rho1) if rho1 is not None and abs(rho1) < 1.0 else None
    return {
        "mean_ic": round(m, 4),
        "t_stat": round(_t_stat(ics), 3) if _t_stat(ics) is not None else None,
        "hit_rate": round(sum(1 for ic in ics if ic > 0) / n, 3),
        "n_obs": n,
        "n_eff": round(n_eff, 1) if n_eff is not None else None,
        "rho1": round(rho1, 3) if rho1 is not None else None,
    }


def _quintile_spread(settled_rows: list[dict], variant: str, hz: int) -> Optional[float]:
    ret_col = f"excess_return_{hz}d"
    pairs = [
        (r[variant], r[ret_col]) for r in settled_rows if r.get(variant) is not None and r.get(ret_col) is not None
    ]
    if len(pairs) < 10:
        return None
    pairs.sort(key=lambda p: p[0])
    q = max(1, len(pairs) // 5)
    bottom_mean = sum(p[1] for p in pairs[:q]) / q
    top_mean = sum(p[1] for p in pairs[-q:]) / q
    return round(top_mean - bottom_mean, 4)


def _top_n(rows: list[dict], variant: str, n: int = TOP_N_OVERLAP) -> list[str]:
    """Return tickers from latest snap_date with top-N scores for variant."""
    if not rows:
        return []
    latest_date = max(r["snap_date"] for r in rows)
    latest = [
        (r.get(variant), r["ticker"]) for r in rows if r["snap_date"] == latest_date and r.get(variant) is not None
    ]
    latest.sort(key=lambda p: p[0], reverse=True)
    return [t for _, t in latest[:n]]


def _jaccard(a: list[str], b: list[str]) -> Optional[float]:
    if not a or not b:
        return None
    sa, sb = set(a), set(b)
    inter = len(sa & sb)
    union = len(sa | sb)
    return round(inter / union, 3) if union > 0 else None


def compute_summary(all_rows: list[dict], as_of_date: str) -> dict:
    settled_by_hz = {hz: [r for r in all_rows if _is_settled(r.get(f"forward_complete_{hz}d"))] for hz in HORIZONS}

    gate_status = {
        5: len(settled_by_hz[5]) >= OBS_GATE_5D,
        10: len(settled_by_hz[10]) >= OBS_GATE_10D,
        20: len(settled_by_hz[20]) >= OBS_GATE_20D,
    }

    # Overlap: top-N for each variant vs core and final_score
    core_top = _top_n(all_rows, "ees_v3_core")
    fs_top = _top_n(all_rows, "final_score")

    variant_summaries = {}
    for vname in VARIANTS:
        v_top = _top_n(all_rows, vname)
        vs: dict = {
            "n_rows_with_score": sum(1 for r in all_rows if r.get(vname) is not None),
            "overlap_vs_core_top20": _jaccard(v_top, core_top),
            "overlap_vs_finalscore_top20": _jaccard(v_top, fs_top),
        }
        for hz in HORIZONS:
            gate_met = gate_status[hz]
            settled = settled_by_hz[hz]
            vs[f"n_completed_{hz}d"] = len(settled)
            vs[f"gate_{hz}d"] = "MET" if gate_met else "NOT_MET"
            if gate_met:
                ic = _per_variant_ic(settled, vname, hz)
                vs[f"ic_{hz}d"] = ic
                vs[f"quintile_spread_{hz}d"] = _quintile_spread(settled, vname, hz)
            else:
                vs[f"ic_{hz}d"] = None
                vs[f"quintile_spread_{hz}d"] = None
        variant_summaries[vname] = vs

    return {
        "as_of": as_of_date,
        "governance": GOVERNANCE,
        "monitor_version": MONITOR_VERSION,
        "total_rows": len(all_rows),
        "completed_5d": len(settled_by_hz[5]),
        "completed_10d": len(settled_by_hz[10]),
        "completed_20d": len(settled_by_hz[20]),
        "gate_5d": "MET" if gate_status[5] else "NOT_MET",
        "gate_10d": "MET" if gate_status[10] else "NOT_MET",
        "gate_20d": "MET" if gate_status[20] else "NOT_MET",
        "interpretation_status": (
            "GATE_MET" if all(gate_status.values()) else "OBSERVATION_WINDOW_INCOMPLETE_NO_INTERPRETATION"
        ),
        "variants": variant_summaries,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="EES v3 shadow variant monitor — DIAGNOSTIC_ONLY")
    p.add_argument("--as-of-date", required=True, dest="as_of_date", help="Snapshot date: YYYY-MM-DD")
    p.add_argument("--dry-run", action="store_true", help="Compute but do not write outputs")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    as_of_date = args.as_of_date
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    log.info("=== EES v3 Shadow Variant Monitor ===")
    log.info("as_of_date=%s | run_ts=%s | dry_run=%s", as_of_date, run_ts, args.dry_run)
    log.info("GOVERNANCE: %s", GOVERNANCE)

    # 1. Load rankings
    all_rankings = load_rankings(as_of_date)
    if not all_rankings:
        log.error("No rankings found for %s", as_of_date)
        return 1

    # 2. Compute variant scores
    variant_scores = compute_variant_scores(all_rankings)

    # 3. Load prices
    prices, sorted_dates = load_prices()
    if not prices:
        log.warning("No price data — forward returns will be null")

    # 4. Load existing ledger
    lpath = ledger_path()
    existing_rows, existing_keys, settled_keys = load_ledger(lpath)

    # 5. Construct new rows for keys not already in ledger
    new_rows = []
    skipped = 0
    for ranking_row in all_rankings:
        key = (as_of_date, ranking_row["ticker"])
        if key in existing_keys:
            skipped += 1
            continue
        new_rows.append(make_new_row(as_of_date, ranking_row, variant_scores, prices, sorted_dates, run_ts))

    log.info("New rows: %d | Skipped (duplicate): %d | Settled: %d", len(new_rows), skipped, len(settled_keys))

    # 6. Backfill open rows in existing ledger
    updated_existing, new_5d, new_10d, new_20d = backfill_open_rows(existing_rows, prices, sorted_dates)
    log.info("Backfill: %d new 5d, %d new 10d, %d new 20d completions", new_5d, new_10d, new_20d)

    # 7. Combine
    all_rows = updated_existing + new_rows

    # 8. Settled-row integrity check
    for old, new in zip(existing_rows, updated_existing):
        if _is_settled(old.get("forward_complete_20d")):
            assert old == new, f"INTEGRITY VIOLATION: settled row modified for ({old['snap_date']}, {old['ticker']})"

    # 9. Summary
    summary = compute_summary(all_rows, as_of_date)
    log.info(
        "Summary: total=%d | completed 5d=%d 10d=%d 20d=%d",
        summary["total_rows"],
        summary["completed_5d"],
        summary["completed_10d"],
        summary["completed_20d"],
    )
    for vname in VARIANTS:
        vs = summary["variants"][vname]
        ic5 = vs.get("ic_5d")
        if ic5:
            log.info(
                "  %s 5d IC: mean=%.4f t=%.2f n=%d hr=%.3f n_eff=%s",
                vname,
                ic5["mean_ic"],
                ic5["t_stat"] or 0,
                ic5["n_obs"],
                ic5["hit_rate"],
                ic5.get("n_eff"),
            )
        log.info(
            "  %s overlap_vs_core=%s overlap_vs_fs=%s",
            vname,
            vs.get("overlap_vs_core_top20"),
            vs.get("overlap_vs_finalscore_top20"),
        )

    if args.dry_run:
        log.info("DRY RUN — no files written")
        return 0

    # 10. Write outputs
    write_ledger(all_rows, lpath)

    spath = summary_path(as_of_date)
    spath.parent.mkdir(parents=True, exist_ok=True)
    with open(spath, "w") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")
    log.info("Summary written: %s", spath)

    log.info("=== Done === DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())

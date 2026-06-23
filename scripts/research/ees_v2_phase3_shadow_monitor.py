"""
EES v2 Phase 3 shadow monitor — diagnostic-only, append-only ledger.

Usage:
    python3 ees_v2_phase3_shadow_monitor.py --as-of-date YYYY-MM-DD

Spec: artifacts/audit/EES_V2_PHASE3_SHADOW_MONITOR_SPEC_2026_06_23.md
Validation: e80c3ff2 (EES forward validation PASS)

Governance:
    DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE | NO_CRON
    No ranker/selector/sizing/final_score/gate/snapshot/portfolio changes.
    No model promotion. No freeze lift. No live fetch. No yfinance/API/IEX.
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
HORIZONS = [5, 20]
OBS_GATE_5D = 20  # min completed 5d observations before interpretation
OBS_GATE_20D = 20  # min completed 20d observations before interpretation
MIN_PAIRS_PER_DATE = 5  # min valid pairs for per-date Spearman IC

# Explicit block: no scheduling, no production files
_FORBIDDEN_IMPORTS = ["yfinance", "alpaca", "iexfinance", "tiingo", "requests"]


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _snapshots_dir() -> Path:
    return _repo_root() / "data" / "snapshots"


def _archives_dir() -> Path:
    return _repo_root() / "data" / "pit_archives"


def _shadow_dir() -> Path:
    return _repo_root() / "artifacts" / "shadow"


def ledger_path() -> Path:
    return _shadow_dir() / "ees_v2_phase3_shadow_ledger.jsonl"


def summary_path(as_of_date: str) -> Path:
    return _shadow_dir() / f"ees_v2_phase3_shadow_summary_{as_of_date}.json"


# ---------------------------------------------------------------------------
# Phase 3 normalization (open question 3 from spec)
# ---------------------------------------------------------------------------


def is_phase3(value: object) -> bool:
    """
    Return True if value indicates Phase 3.

    Accepts:
      - float/int >= 3.0
      - strings containing 'phase 3', 'phase3', or 'p3' (case-insensitive)
      - numeric strings that parse to float >= 3.0
    """
    if value is None or value == "":
        return False
    try:
        return float(value) >= 3.0
    except (ValueError, TypeError):
        pass
    s = str(value).lower().strip()
    return "phase 3" in s or "phase3" in s or s == "p3"


# ---------------------------------------------------------------------------
# Rankings loader
# ---------------------------------------------------------------------------


def load_rankings(snap_date: str) -> list[dict]:
    """Load rankings.csv for snap_date. Returns all rows."""
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


def filter_phase3_ees(rows: list[dict]) -> list[dict]:
    """Return rows that are Phase 3 with a valid ees_v2_score."""
    out = []
    for r in rows:
        if not is_phase3(r.get("lead_program_phase")):
            continue
        v = r.get("ees_v2_score", "")
        try:
            f = float(v)
            if math.isnan(f):
                continue
        except (ValueError, TypeError):
            continue
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# Price cache (reuses pattern from pit_gap_forward_returns.py)
# ---------------------------------------------------------------------------


def resolve_archive(snap_date: str) -> tuple[Optional[str], bool]:
    """
    Return (arch_date, is_fallback) for the best available archive on or
    before snap_date. Returns (None, False) if no archive is found.
    """
    arch_root = _archives_dir()
    direct = arch_root / snap_date
    if direct.exists() and (direct / "price_history.csv").exists():
        return snap_date, False
    available = sorted(
        d.name for d in arch_root.iterdir() if d.is_dir() and d.name <= snap_date and (d / "price_history.csv").exists()
    )
    if not available:
        log.warning("No archive found on or before %s", snap_date)
        return None, False
    return available[-1], True


def load_prices(arch_date: str) -> tuple[dict[str, dict[str, float]], list[str]]:
    """Return ({ticker: {date: close}}, sorted_trading_dates)."""
    path = _archives_dir() / arch_date / "price_history.csv"
    if not path.exists():
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
    return prices, sorted(all_dates)


def resolve_anchor(
    ticker: str,
    snap_date: str,
    prices: dict[str, dict[str, float]],
    sorted_dates: list[str],
) -> tuple[Optional[float], Optional[str]]:
    """Find anchor close at or before snap_date."""
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
    """Compute N-day return from anchor_date. Returns None if data unavailable."""
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
    """
    Load JSONL ledger.

    Returns:
        rows: all ledger rows in order
        existing_keys: set of (snap_date, ticker) already in ledger
        settled_keys: set of (snap_date, ticker) where forward_complete_20d is True
    """
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
        "Loaded ledger: %d rows (%d existing keys, %d settled)",
        len(rows),
        len(existing_keys),
        len(settled_keys),
    )
    return rows, existing_keys, settled_keys


def write_ledger(rows: list[dict], path: Path) -> None:
    """
    Write ledger. Settled rows are guaranteed identical to what was loaded.

    We rewrite the entire file (not file-append) so that open rows can be
    backfilled. The invariant is enforced in code: settled rows flow through
    unchanged; only open rows are modified.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
    log.info("Ledger written: %d rows → %s", len(rows), path)


# ---------------------------------------------------------------------------
# Row construction
# ---------------------------------------------------------------------------


def _safe_float(v: object) -> Optional[float]:
    try:
        f = float(v)  # type: ignore[arg-type]
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def _safe_bool(v: object) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes")


def _is_settled(v: object) -> bool:
    """
    Return True if a forward_complete_Nd field indicates a settled (immutable) row.

    Accepts JSON boolean True, numeric 1, and common truthy string forms so that
    manually edited ledger rows are protected identically to script-generated ones.
    Rejects everything else, including None and missing fields.
    """
    if v is True or v == 1:
        return True
    if isinstance(v, str) and v.strip().lower() in ("true",):
        return True
    return False


def make_new_row(
    snap_date: str,
    ranking_row: dict,
    prices: dict[str, dict[str, float]],
    sorted_dates: list[str],
    run_ts: str,
) -> dict:
    """Construct a new ledger row from a rankings row + price cache."""
    ticker = ranking_row["ticker"]

    # Anchor: ticker
    anchor_close, anchor_date = resolve_anchor(ticker, snap_date, prices, sorted_dates)

    # Anchor: XBI benchmark
    xbi_anchor_close, xbi_anchor_date = resolve_anchor("XBI", snap_date, prices, sorted_dates)

    row: dict = {
        "snap_date": snap_date,
        "ticker": ticker,
        "ees_v2_score": _safe_float(ranking_row.get("ees_v2_score")),
        "lead_program_phase": _safe_float(ranking_row.get("lead_program_phase")),
        "is_hard_catalyst": _safe_bool(ranking_row.get("is_hard_catalyst", False)),
        "catalyst_event_type": ranking_row.get("catalyst_event_type", ""),
        "catalyst_family": ranking_row.get("catalyst_family", ""),
        "anchor_date": anchor_date,
        "anchor_close": anchor_close,
        "xbi_anchor_date": xbi_anchor_date,
        "xbi_anchor_close": xbi_anchor_close,
        "actual_return_5d": None,
        "xbi_return_5d": None,
        "excess_return_5d": None,
        "forward_complete_5d": False,
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
) -> tuple[list[dict], int, int]:
    """
    Fill forward returns for open (not settled) rows.

    Settled rows (forward_complete_20d = True) are passed through unchanged.
    Returns (updated_rows, n_newly_settled_5d, n_newly_settled_20d).
    """
    result = []
    newly_5d = 0
    newly_20d = 0

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
                continue  # already filled

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
                newly_5d += 1
            elif hz == 20:
                newly_20d += 1

        result.append(row)

    return result, newly_5d, newly_20d


# ---------------------------------------------------------------------------
# Summary metrics
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
    mean = sum(vals) / n
    var = sum((x - mean) ** 2 for x in vals) / (n - 1)
    if var == 0:
        return None
    return mean / math.sqrt(var / n)


def _per_date_ic(settled_rows: list[dict], hz: int) -> dict:
    ret_col = f"excess_return_{hz}d"
    by_date: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in settled_rows:
        s = r.get("ees_v2_score")
        ret = r.get(ret_col)
        if s is None or ret is None:
            continue
        by_date[r["snap_date"]].append((s, ret))

    ics = []
    for pairs in by_date.values():
        if len(pairs) < MIN_PAIRS_PER_DATE:
            continue
        xs, ys = zip(*pairs)
        ic = _spearman_ic(list(xs), list(ys))
        if ic is not None:
            ics.append(ic)

    if not ics:
        return {"mean_ic": None, "median_ic": None, "t_stat": None, "hit_rate": None, "n_dates": 0}

    n = len(ics)
    sorted_ics = sorted(ics)
    mean = sum(ics) / n
    median = sorted_ics[n // 2] if n % 2 else (sorted_ics[n // 2 - 1] + sorted_ics[n // 2]) / 2
    return {
        "mean_ic": round(mean, 4),
        "median_ic": round(median, 4),
        "t_stat": round(_t_stat(ics), 2) if _t_stat(ics) is not None else None,
        "hit_rate": round(sum(1 for ic in ics if ic > 0) / n, 3),
        "n_dates": n,
    }


def _quintile_spread(settled_rows: list[dict], hz: int) -> Optional[float]:
    ret_col = f"excess_return_{hz}d"
    pairs = [
        (r["ees_v2_score"], r[ret_col])
        for r in settled_rows
        if r.get("ees_v2_score") is not None and r.get(ret_col) is not None
    ]
    if len(pairs) < 10:
        return None
    pairs.sort(key=lambda p: p[0])
    q = max(1, len(pairs) // 5)
    bottom_mean = sum(p[1] for p in pairs[:q]) / q
    top_mean = sum(p[1] for p in pairs[-q:]) / q
    return round(top_mean - bottom_mean, 4)


def compute_summary(all_rows: list[dict], as_of_date: str) -> dict:
    """Compute summary stats. Enforces gate: no interpretation before thresholds met."""
    settled_5d = [r for r in all_rows if _is_settled(r.get("forward_complete_5d"))]
    settled_20d = [r for r in all_rows if _is_settled(r.get("forward_complete_20d"))]

    gate_5d_met = len(settled_5d) >= OBS_GATE_5D
    gate_20d_met = len(settled_20d) >= OBS_GATE_20D

    summary: dict = {
        "as_of": as_of_date,
        "governance": GOVERNANCE,
        "monitor_version": MONITOR_VERSION,
        "phase3_rows_total": len(all_rows),
        "phase3_rows_with_ees_v2": sum(1 for r in all_rows if r.get("ees_v2_score") is not None),
        "completed_5d": len(settled_5d),
        "completed_20d": len(settled_20d),
        "observation_gate_5d": "MET" if gate_5d_met else "NOT_MET",
        "observation_gate_20d": "MET" if gate_20d_met else "NOT_MET",
    }

    if not gate_5d_met or not gate_20d_met:
        summary["interpretation_status"] = "OBSERVATION_WINDOW_INCOMPLETE_NO_INTERPRETATION"
        for key in [
            "ic_5d_mean",
            "ic_5d_median",
            "ic_5d_t_stat",
            "ic_5d_n_dates",
            "ic_20d_mean",
            "ic_20d_median",
            "ic_20d_t_stat",
            "ic_20d_n_dates",
            "hit_rate_5d",
            "hit_rate_20d",
            "quintile_spread_5d",
            "quintile_spread_20d",
        ]:
            summary[key] = None
        return summary

    summary["interpretation_status"] = "OBSERVATION_WINDOW_COMPLETE_INTERPRET_WITH_CARE"

    ic5 = _per_date_ic(settled_5d, 5)
    summary.update(
        {
            "ic_5d_mean": ic5["mean_ic"],
            "ic_5d_median": ic5["median_ic"],
            "ic_5d_t_stat": ic5["t_stat"],
            "ic_5d_n_dates": ic5["n_dates"],
            "hit_rate_5d": ic5["hit_rate"],
            "quintile_spread_5d": _quintile_spread(settled_5d, 5),
        }
    )

    ic20 = _per_date_ic(settled_20d, 20)
    summary.update(
        {
            "ic_20d_mean": ic20["mean_ic"],
            "ic_20d_median": ic20["median_ic"],
            "ic_20d_t_stat": ic20["t_stat"],
            "ic_20d_n_dates": ic20["n_dates"],
            "hit_rate_20d": ic20["hit_rate"],
            "quintile_spread_20d": _quintile_spread(settled_20d, 20),
        }
    )

    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="EES v2 Phase 3 shadow monitor — DIAGNOSTIC_ONLY, NO_CRON")
    p.add_argument(
        "--as-of-date",
        required=True,
        help="Snapshot date to process: YYYY-MM-DD",
        dest="as_of_date",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and log but do not write ledger or summary",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    as_of_date = args.as_of_date
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    log.info("=== EES v2 Phase 3 Shadow Monitor ===")
    log.info("as_of_date=%s | run_ts=%s | dry_run=%s", as_of_date, run_ts, args.dry_run)
    log.info("GOVERNANCE: %s", GOVERNANCE)

    # 1. Load rankings for as_of_date
    all_rankings = load_rankings(as_of_date)
    if not all_rankings:
        log.error("No rankings found for %s — aborting", as_of_date)
        return 1

    phase3_rows = filter_phase3_ees(all_rankings)
    log.info(
        "Phase 3 with valid ees_v2_score: %d / %d total rankings",
        len(phase3_rows),
        len(all_rankings),
    )

    # 2. Resolve archive and load prices
    arch_date, is_fallback = resolve_archive(as_of_date)
    if arch_date is None:
        log.warning("No price archive found on or before %s — returns will be null", as_of_date)
        prices: dict[str, dict[str, float]] = {}
        sorted_dates: list[str] = []
    else:
        if is_fallback:
            log.info("Archive fallback: %s (no archive at %s)", arch_date, as_of_date)
        prices, sorted_dates = load_prices(arch_date)
        log.info(
            "Loaded archive %s: %d tickers, %d trading dates",
            arch_date,
            len(prices),
            len(sorted_dates),
        )

    # 3. Load existing ledger
    lpath = ledger_path()
    existing_rows, existing_keys, settled_keys = load_ledger(lpath)

    # 4. Construct new rows for (as_of_date, ticker) pairs not already in ledger
    new_rows = []
    skipped_dup = 0
    for rrow in phase3_rows:
        key = (as_of_date, rrow["ticker"])
        if key in existing_keys:
            skipped_dup += 1
            continue
        new_rows.append(make_new_row(as_of_date, rrow, prices, sorted_dates, run_ts))

    log.info(
        "New rows: %d | Skipped (duplicate): %d | Settled (immutable): %d",
        len(new_rows),
        skipped_dup,
        len(settled_keys),
    )

    # 5. Backfill open rows in existing ledger (never touch settled rows)
    updated_existing, new_5d, new_20d = backfill_open_rows(existing_rows, prices, sorted_dates)
    log.info("Backfill: %d newly completed 5d, %d newly completed 20d", new_5d, new_20d)

    # 6. Combine: existing (with backfill) + new rows
    all_rows = updated_existing + new_rows

    # 7. Verify settled-row integrity (safety check — should always pass)
    for old, new in zip(existing_rows, updated_existing):
        if _is_settled(old.get("forward_complete_20d")):
            assert old == new, (
                f"INTEGRITY VIOLATION: settled row modified for " f"({old['snap_date']}, {old['ticker']})"
            )

    # 8. Compute summary
    summary = compute_summary(all_rows, as_of_date)
    log.info("Summary:")
    log.info("  phase3_rows_total=%d", summary["phase3_rows_total"])
    log.info("  completed_5d=%d (gate=%s)", summary["completed_5d"], summary["observation_gate_5d"])
    log.info("  completed_20d=%d (gate=%s)", summary["completed_20d"], summary["observation_gate_20d"])
    log.info("  interpretation_status=%s", summary["interpretation_status"])
    if summary.get("ic_5d_mean") is not None:
        log.info(
            "  IC 5d: mean=%.4f t=%.2f n=%d hit_rate=%.3f",
            summary["ic_5d_mean"],
            summary["ic_5d_t_stat"] or 0,
            summary["ic_5d_n_dates"],
            summary["hit_rate_5d"] or 0,
        )
    if summary.get("ic_20d_mean") is not None:
        log.info(
            "  IC 20d: mean=%.4f t=%.2f n=%d hit_rate=%.3f",
            summary["ic_20d_mean"],
            summary["ic_20d_t_stat"] or 0,
            summary["ic_20d_n_dates"],
            summary["hit_rate_20d"] or 0,
        )

    # 9. Write outputs
    if args.dry_run:
        log.info("DRY RUN — no files written")
        return 0

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

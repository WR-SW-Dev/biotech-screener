#!/usr/bin/env python3
"""Build a historical pre-catalyst options panel for signal research.

Joins archived snapshot catalyst data with Massive options history to test
whether pre-event option activity predicts better ordering within
binary/regulatory names.

Phase 1: Extract catalyst events from archived snapshots
Phase 2: For each catalyst ticker+date, fetch Massive day-agg options data
Phase 3: Derive pre-catalyst features
Phase 4: Output panel CSV for downstream IC analysis

Usage:
    python scripts/research/build_precatalyst_options_panel.py \
        --archive-dir data/archives \
        --out data/research/precatalyst_options_panel.csv \
        --families REGULATORY,CLINICAL \
        --buckets binary_now,build_window,less_binary \
        --lookback-days 10
"""
from __future__ import annotations

import argparse
import csv
import io
import logging
import sys
import tarfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("precatalyst_panel")

# ---------------------------------------------------------------------------
# Catalyst classification (mirrors decision_engine.py + event_ledger.py)
# ---------------------------------------------------------------------------

CATALYST_FAMILY_MAP = {
    "PDUFA": "REGULATORY",
    "FDA_PDUFA_DATE": "REGULATORY",
    "FDA_ADCOM": "REGULATORY",
    "FDA_APPROVAL": "REGULATORY",
    "FDA_SUBMISSION": "REGULATORY",
    "FDA_DESIGNATION": "REGULATORY",
    "FDA_CRL": "REGULATORY",
    "FDA_RTF": "REGULATORY",
    "FDA_DECISION": "REGULATORY",
    "EMA_AGENDA": "REGULATORY",
    "EMA_OUTCOME": "REGULATORY",
    "EMA_COMMITTEE_AGENDA": "REGULATORY",
    "EMA_COMMITTEE_OUTCOME": "REGULATORY",
    "CLINICAL_PCD": "CLINICAL",
    "CLINICAL_CD": "CLINICAL",
    "CT_PRIMARY_COMPLETION": "CLINICAL",
    "CT_STUDY_COMPLETION": "CLINICAL",
    "CT_RESULTS_POSTED": "CLINICAL",
    "CT_DATE_CONFIRMED_ACTUAL": "CLINICAL",
    "DATA_READOUT": "CLINICAL",
    "DATA_PRESENTATION": "CLINICAL",
    "DATA_PUBLICATION": "CLINICAL",
    "CLINICAL_HOLD": "SAFETY",
    "SAFETY_SIGNAL": "SAFETY",
    "FDA_WARNING_LETTER": "SAFETY",
    "CT_TRIAL_TERMINATED": "SAFETY",
    "CT_TRIAL_WITHDRAWN": "SAFETY",
    "CT_TIMELINE_PULLIN": "CLINICAL",
    "CT_STATUS_UPGRADE": "CLINICAL",
}

BUCKET_BINARY_NOW_MAX = 30
BUCKET_BUILD_WINDOW_MAX = 90
BUCKET_LESS_BINARY_MAX = 180

_BUCKET_CORE_MODES = frozenset({"no_upcoming", "missing"})


def classify_family(event_type: str) -> str:
    return CATALYST_FAMILY_MAP.get(event_type, "")


def assign_bucket(catalyst_days: Optional[float], catalyst_mode: str) -> str:
    if catalyst_mode in _BUCKET_CORE_MODES:
        return "core"
    if catalyst_days is None:
        return "core"
    if catalyst_days <= BUCKET_BINARY_NOW_MAX:
        return "binary_now"
    if catalyst_days <= BUCKET_BUILD_WINDOW_MAX:
        return "build_window"
    if catalyst_days <= BUCKET_LESS_BINARY_MAX:
        return "less_binary"
    return "core"


def _safe_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Phase 1: Extract catalyst events from archives
# ---------------------------------------------------------------------------


def extract_catalyst_events(
    archive_dir: Path,
    families: set,
    buckets: set,
    min_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Scan archives and extract catalyst event rows.

    Returns list of dicts: {ticker, snapshot_date, catalyst_event_type,
    catalyst_family, catalyst_bucket, catalyst_days, catalyst_mode,
    catalyst_source, composite_score, optionality_pct}
    """
    events = []
    archives = sorted(archive_dir.glob("*.tar.gz"))
    logger.info("Scanning %d archives...", len(archives))

    for arch in archives:
        snap_date_str = arch.stem.replace(".tar", "")
        try:
            snap_date = date.fromisoformat(snap_date_str)
        except ValueError:
            continue
        if min_date and snap_date < min_date:
            continue

        try:
            with tarfile.open(arch, "r:gz") as tf:
                members = [m for m in tf.getmembers() if m.name.endswith("rankings.csv")]
                if not members:
                    continue
                f = tf.extractfile(members[0])
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
                for row in reader:
                    event_type = row.get("catalyst_event_type", "")
                    family = classify_family(event_type)
                    if family not in families:
                        continue

                    days = _safe_float(row.get("catalyst_days"))
                    mode = row.get("catalyst_mode", "")
                    bucket = assign_bucket(days, mode)
                    if bucket not in buckets:
                        continue

                    events.append(
                        {
                            "ticker": row.get("ticker", ""),
                            "snapshot_date": snap_date_str,
                            "catalyst_event_type": event_type,
                            "catalyst_family": family,
                            "catalyst_bucket": bucket,
                            "catalyst_days": days,
                            "catalyst_mode": mode,
                            "catalyst_source": row.get("catalyst_source", ""),
                            "composite_score": _safe_float(row.get("composite_score")),
                            "optionality_pct": _safe_float(row.get("optionality_pct")),
                        }
                    )
        except Exception as exc:
            logger.warning("Error reading %s: %s", arch.name, exc)
            continue

    logger.info("Extracted %d catalyst events from archives", len(events))
    return events


# ---------------------------------------------------------------------------
# Phase 2: Fetch Massive options data for pre-catalyst windows
# ---------------------------------------------------------------------------


def _build_underlying_date_pairs(
    events: List[Dict[str, Any]],
    lookback_days: int,
) -> Dict[str, set]:
    """Build map of underlying_ticker → set of dates we need options data for."""
    ticker_dates: Dict[str, set] = defaultdict(set)
    for ev in events:
        ticker = ev["ticker"]
        snap = date.fromisoformat(ev["snapshot_date"])
        # We need options data for [snap - lookback, snap]
        for offset in range(lookback_days + 1):
            d = snap - timedelta(days=offset)
            if d.weekday() < 5:  # trading days only
                ticker_dates[ticker].add(d)
    return ticker_dates


def fetch_options_for_dates(
    dates_needed: set,
    force: bool = False,
    cached_only: bool = False,
) -> Dict[date, List[Dict[str, Any]]]:
    """Download and ingest day aggs for all needed dates.

    Returns {date: [normalized records]}.
    If cached_only=True, skip dates that aren't already in the local cache.
    """
    from common.options_history_massive import ingest_day_aggs

    result = {}
    sorted_dates = sorted(dates_needed)
    logger.info(
        "Fetching day aggs for %d unique dates (%s to %s)", len(sorted_dates), sorted_dates[0], sorted_dates[-1]
    )

    cache_root = REPO_ROOT / "data" / "caches" / "massive_options"
    skipped = 0
    for dt in sorted_dates:
        if cached_only:
            cache_path = (
                cache_root / "day_aggs" / str(dt.year) / f"{dt.month:02d}" / f"{dt.strftime('%Y-%m-%d')}.csv.gz"
            )
            if not cache_path.exists():
                skipped += 1
                continue
        records = ingest_day_aggs(dt, force=force)
        if records:
            result[dt] = records
            logger.info("  %s: %d records", dt, len(records))
        else:
            logger.debug("  %s: no data", dt)

    if skipped:
        logger.info("Skipped %d dates not in local cache (--cached-only)", skipped)

    return result


def _build_ticker_volume_index(
    day_aggs: Dict[date, List[Dict[str, Any]]],
) -> Dict[str, Dict[date, Dict[str, float]]]:
    """Build index: underlying_ticker → date → {total_volume, total_transactions,
    contract_count, put_volume, call_volume}.

    Aggregates across all option contracts for each underlying on each date.
    """
    index: Dict[str, Dict[date, Dict[str, float]]] = defaultdict(
        lambda: defaultdict(
            lambda: {
                "total_volume": 0,
                "total_transactions": 0,
                "contract_count": 0,
                "put_volume": 0,
                "call_volume": 0,
            }
        )
    )

    for dt, records in day_aggs.items():
        for rec in records:
            underlying = rec["underlying_ticker"]
            if not underlying:
                continue
            entry = index[underlying][dt]
            vol = rec["volume"] or 0
            txn = rec["transactions"] or 0
            entry["total_volume"] += vol
            entry["total_transactions"] += txn
            entry["contract_count"] += 1

            # Determine put/call from option ticker
            # Format: O:MRNA260320P00025000 — P or C before strike digits
            opt_ticker = rec["option_ticker"]
            stripped = opt_ticker[2:] if opt_ticker.startswith("O:") else opt_ticker
            for ch in reversed(stripped):
                if ch == "P":
                    entry["put_volume"] += vol
                    break
                elif ch == "C":
                    entry["call_volume"] += vol
                    break
                elif ch.isdigit():
                    continue
                else:
                    break

    return index


# ---------------------------------------------------------------------------
# Phase 3: Derive pre-catalyst features
# ---------------------------------------------------------------------------

FEATURE_COLUMNS = [
    "pre_event_volume_mean",
    "pre_event_volume_surge",
    "pre_event_transactions_mean",
    "pre_event_contract_count_mean",
    "pre_event_put_call_ratio",
    "pre_event_volume_trend",
    "chain_breadth",
]


def compute_precatalyst_features(
    ticker: str,
    snap_date: date,
    lookback_days: int,
    vol_index: Dict[str, Dict[date, Dict[str, float]]],
) -> Dict[str, Any]:
    """Compute pre-catalyst options features for one ticker+snapshot.

    Features:
      - pre_event_volume_mean: avg daily option volume over lookback
      - pre_event_volume_surge: ratio of last-day volume to lookback mean
      - pre_event_transactions_mean: avg daily transaction count
      - pre_event_contract_count_mean: avg daily active contracts (chain breadth)
      - pre_event_put_call_ratio: put_volume / (put_volume + call_volume)
      - pre_event_volume_trend: slope of daily volume (positive = increasing)
      - chain_breadth: max contract_count in window
    """
    features: Dict[str, Any] = {col: "" for col in FEATURE_COLUMNS}

    ticker_data = vol_index.get(ticker, {})
    if not ticker_data:
        return features

    # Collect window data
    window_data = []
    for offset in range(lookback_days + 1):
        d = snap_date - timedelta(days=offset)
        if d in ticker_data:
            window_data.append((offset, ticker_data[d]))

    if len(window_data) < 2:
        return features

    volumes = [wd[1]["total_volume"] for wd in window_data]
    transactions = [wd[1]["total_transactions"] for wd in window_data]
    contracts = [wd[1]["contract_count"] for wd in window_data]
    put_vols = [wd[1]["put_volume"] for wd in window_data]
    call_vols = [wd[1]["call_volume"] for wd in window_data]

    mean_vol = sum(volumes) / len(volumes) if volumes else 0
    mean_txn = sum(transactions) / len(transactions) if transactions else 0
    mean_contracts = sum(contracts) / len(contracts) if contracts else 0

    # Volume surge: last day vs mean of rest
    if len(volumes) > 1 and mean_vol > 0:
        last_day_vol = volumes[0]  # offset 0 = snap_date
        rest_mean = sum(volumes[1:]) / len(volumes[1:]) if len(volumes) > 1 else mean_vol
        surge = last_day_vol / rest_mean if rest_mean > 0 else 0
    else:
        surge = 0

    # Put/call ratio
    total_puts = sum(put_vols)
    total_calls = sum(call_vols)
    pc_ratio = total_puts / (total_puts + total_calls) if (total_puts + total_calls) > 0 else 0.5

    # Volume trend (simple: compare first half to second half)
    if len(volumes) >= 4:
        mid = len(volumes) // 2
        first_half = sum(volumes[mid:]) / len(volumes[mid:])
        second_half = sum(volumes[:mid]) / len(volumes[:mid])
        trend = (second_half - first_half) / first_half if first_half > 0 else 0
    else:
        trend = 0

    features["pre_event_volume_mean"] = round(mean_vol, 2)
    features["pre_event_volume_surge"] = round(surge, 4)
    features["pre_event_transactions_mean"] = round(mean_txn, 2)
    features["pre_event_contract_count_mean"] = round(mean_contracts, 2)
    features["pre_event_put_call_ratio"] = round(pc_ratio, 4)
    features["pre_event_volume_trend"] = round(trend, 4)
    features["chain_breadth"] = max(contracts) if contracts else 0

    return features


# ---------------------------------------------------------------------------
# Phase 4: Assemble panel
# ---------------------------------------------------------------------------

OUTPUT_COLUMNS = [
    "ticker",
    "snapshot_date",
    "catalyst_event_type",
    "catalyst_family",
    "catalyst_bucket",
    "catalyst_days",
    "catalyst_mode",
    "catalyst_source",
    "composite_score",
    "optionality_pct",
    *FEATURE_COLUMNS,
]


def build_panel(
    events: List[Dict[str, Any]],
    vol_index: Dict[str, Dict[date, Dict[str, float]]],
    lookback_days: int,
) -> List[Dict[str, Any]]:
    """Join events with pre-catalyst features."""
    panel = []
    for ev in events:
        snap = date.fromisoformat(ev["snapshot_date"])
        features = compute_precatalyst_features(ev["ticker"], snap, lookback_days, vol_index)
        row = {**ev, **features}
        panel.append(row)

    # Report coverage
    with_data = sum(1 for p in panel if p["pre_event_volume_mean"] != "")
    logger.info(
        "Panel: %d events, %d with options data (%.1f%%)",
        len(panel),
        with_data,
        100 * with_data / len(panel) if panel else 0,
    )
    return panel


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Build pre-catalyst options research panel")
    parser.add_argument("--archive-dir", type=Path, default=REPO_ROOT / "data" / "archives")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "research" / "precatalyst_options_panel.csv")
    parser.add_argument("--families", default="REGULATORY,CLINICAL", help="Catalyst families to include")
    parser.add_argument("--buckets", default="binary_now,build_window,less_binary", help="Catalyst buckets to include")
    parser.add_argument("--lookback-days", type=int, default=10, help="Days of options data before snapshot")
    parser.add_argument("--min-date", default=None, help="Earliest archive date (YYYY-MM-DD)")
    parser.add_argument("--force", action="store_true", help="Re-download cached files")
    parser.add_argument(
        "--cached-only", action="store_true", help="Use only locally cached day aggs, skip S3 downloads"
    )
    parser.add_argument("--dry-run", action="store_true", help="Extract events only, skip options fetch")
    args = parser.parse_args()

    families = set(args.families.split(","))
    buckets = set(args.buckets.split(","))
    min_date = date.fromisoformat(args.min_date) if args.min_date else None

    # Phase 1: extract
    events = extract_catalyst_events(args.archive_dir, families, buckets, min_date)
    if not events:
        logger.warning("No events found — check archive dir and filters")
        return 1

    # Deduplicate: same ticker+snapshot_date → keep first
    seen = set()
    deduped = []
    for ev in events:
        key = (ev["ticker"], ev["snapshot_date"])
        if key not in seen:
            seen.add(key)
            deduped.append(ev)
    events = deduped
    logger.info("After dedup: %d unique ticker-date pairs", len(events))

    # Report distribution
    from collections import Counter

    dist = Counter((ev["catalyst_family"], ev["catalyst_bucket"]) for ev in events)
    for (fam, bkt), cnt in sorted(dist.items()):
        logger.info("  %s / %s: %d events", fam, bkt, cnt)

    if args.dry_run:
        logger.info("Dry run — skipping options fetch. Writing events only.")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(events)
        logger.info("Wrote %d events to %s", len(events), args.out)
        return 0

    # Phase 2: determine dates needed and fetch
    ticker_dates = _build_underlying_date_pairs(events, args.lookback_days)
    all_dates = set()
    for dates in ticker_dates.values():
        all_dates.update(dates)

    logger.info("Need options data for %d unique dates across %d tickers", len(all_dates), len(ticker_dates))
    day_aggs = fetch_options_for_dates(all_dates, force=args.force, cached_only=args.cached_only)

    # Build volume index
    vol_index = _build_ticker_volume_index(day_aggs)
    logger.info("Volume index: %d tickers with data", len(vol_index))

    # Phase 3+4: compute features and assemble panel
    panel = build_panel(events, vol_index, args.lookback_days)

    # Write output
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(panel)
    logger.info("Panel written to %s (%d rows)", args.out, len(panel))
    return 0


if __name__ == "__main__":
    sys.exit(main())

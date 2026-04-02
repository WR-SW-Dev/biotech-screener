#!/usr/bin/env python3
"""
PIT (Point-in-Time) Validation Audit
=====================================
Detects look-ahead bias in retroactively generated snapshots.

Three audit checks:
  1. Universe survivorship — flags tickers that IPO'd after or delisted before snapshot date
  2. Price data consistency — flags missing prices and extreme returns between snapshots
  3. Catalyst look-ahead — flags catalyst entries with resolved outcomes post-snapshot

Usage:
  python scripts/research/pit_validation_audit.py
  python scripts/research/pit_validation_audit.py --start-date 2024-01-01 --end-date 2025-12-31
  python scripts/research/pit_validation_audit.py --audit survivorship price
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
PROD_DATA_DIR = PROJECT_ROOT / "production_data"
PRICE_HISTORY = PROD_DATA_DIR / "price_history.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "pit_audit"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def get_snapshot_dates(start=None, end=None):
    """Return sorted list of snapshot date strings within range."""
    dates = []
    if not SNAPSHOTS_DIR.exists():
        return dates
    for d in sorted(os.listdir(SNAPSHOTS_DIR)):
        try:
            dt = parse_date(d)
        except ValueError:
            continue
        if start and dt < start:
            continue
        if end and dt > end:
            continue
        dates.append(d)
    return dates


def load_rankings_tickers(snapshot_date_str):
    """Load tickers from a snapshot's rankings.csv."""
    path = SNAPSHOTS_DIR / snapshot_date_str / "rankings.csv"
    if not path.exists():
        return []
    tickers = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            t = row.get("ticker", "").strip()
            if t:
                tickers.append(t)
    return tickers


def load_rankings_rows(snapshot_date_str):
    """Load full rows from a snapshot's rankings.csv."""
    path = SNAPSHOTS_DIR / snapshot_date_str / "rankings.csv"
    if not path.exists():
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def build_price_date_range():
    """Build {ticker: (earliest_date, latest_date)} from price_history.csv.

    earliest_date = proxy for IPO/listing.
    latest_date = if well before today, proxy for delisting.
    """
    ticker_range = {}
    if not PRICE_HISTORY.exists():
        print(f"WARNING: {PRICE_HISTORY} not found, survivorship check will be limited")
        return ticker_range

    print("  Loading price_history.csv (this may take a moment)...")
    with open(PRICE_HISTORY) as f:
        reader = csv.DictReader(f)
        for row in reader:
            t = row.get("ticker", "").strip()
            d = row.get("date", "").strip()
            if not t or not d:
                continue
            try:
                dt = parse_date(d)
            except ValueError:
                continue
            if t not in ticker_range:
                ticker_range[t] = [dt, dt]
            else:
                if dt < ticker_range[t][0]:
                    ticker_range[t][0] = dt
                if dt > ticker_range[t][1]:
                    ticker_range[t][1] = dt

    return {t: (r[0], r[1]) for t, r in ticker_range.items()}


def build_price_lookup():
    """Build {(ticker, date_str): close_price} from price_history.csv."""
    prices = {}
    if not PRICE_HISTORY.exists():
        return prices

    print("  Loading price_history.csv for price lookup...")
    with open(PRICE_HISTORY) as f:
        reader = csv.DictReader(f)
        for row in reader:
            t = row.get("ticker", "").strip()
            d = row.get("date", "").strip()
            c = row.get("close", "").strip()
            if not t or not d or not c:
                continue
            try:
                prices[(t, d)] = float(c)
            except ValueError:
                continue
    return prices


# ---------------------------------------------------------------------------
# Audit 1: Universe Survivorship
# ---------------------------------------------------------------------------


def audit_survivorship(snapshot_dates, price_ranges):
    """Check for tickers that IPO'd after or delisted before snapshot date."""
    print("\n=== AUDIT 1: Universe Survivorship Check ===")

    # Delist threshold: latest price date > 60 trading days before today
    today = date.today()
    DELIST_BUFFER_DAYS = 90  # calendar days — if last price is >90 days old, consider delisted

    results = {
        "per_snapshot": [],
        "worst_offenders_ipo": defaultdict(int),
        "worst_offenders_delist": defaultdict(int),
        "total_ipo_violations": 0,
        "total_delist_violations": 0,
        "snapshots_checked": 0,
    }

    for snap_date_str in snapshot_dates:
        snap_dt = parse_date(snap_date_str)
        tickers = load_rankings_tickers(snap_date_str)

        ipo_violations = []
        delist_violations = []

        for t in tickers:
            if t not in price_ranges:
                continue  # no price data — can't check
            earliest, latest = price_ranges[t]

            # IPO after snapshot: ticker didn't exist yet
            if earliest > snap_dt:
                ipo_violations.append(
                    {
                        "ticker": t,
                        "earliest_price_date": str(earliest),
                        "snapshot_date": snap_date_str,
                        "days_ahead": (earliest - snap_dt).days,
                    }
                )
                results["worst_offenders_ipo"][t] += 1

            # Delisted before snapshot: last price well before snapshot
            # Only flag if latest price is before the snapshot AND before today minus buffer
            if latest < snap_dt and (today - latest).days > DELIST_BUFFER_DAYS:
                delist_violations.append(
                    {
                        "ticker": t,
                        "latest_price_date": str(latest),
                        "snapshot_date": snap_date_str,
                        "days_stale": (snap_dt - latest).days,
                    }
                )
                results["worst_offenders_delist"][t] += 1

        results["per_snapshot"].append(
            {
                "date": snap_date_str,
                "tickers_in_rankings": len(tickers),
                "ipo_violations": len(ipo_violations),
                "delist_violations": len(delist_violations),
                "ipo_details": ipo_violations[:10],  # cap details for readability
                "delist_details": delist_violations[:10],
            }
        )
        results["total_ipo_violations"] += len(ipo_violations)
        results["total_delist_violations"] += len(delist_violations)
        results["snapshots_checked"] += 1

    # Sort worst offenders
    results["worst_offenders_ipo"] = sorted(results["worst_offenders_ipo"].items(), key=lambda x: -x[1])[:20]
    results["worst_offenders_delist"] = sorted(results["worst_offenders_delist"].items(), key=lambda x: -x[1])[:20]

    # Print summary
    n = results["snapshots_checked"]
    print(f"  Snapshots checked: {n}")
    print(f"  Total IPO look-ahead violations: {results['total_ipo_violations']}")
    print(f"  Total delist zombie violations:   {results['total_delist_violations']}")

    if results["worst_offenders_ipo"]:
        print("\n  Top IPO look-ahead offenders (ticker, # snapshots contaminated):")
        for t, count in results["worst_offenders_ipo"][:10]:
            pr = price_ranges.get(t, ("?", "?"))
            print(f"    {t:8s}  {count:4d} snapshots   (first price: {pr[0]})")

    if results["worst_offenders_delist"]:
        print("\n  Top delist zombie offenders (ticker, # snapshots contaminated):")
        for t, count in results["worst_offenders_delist"][:10]:
            pr = price_ranges.get(t, ("?", "?"))
            print(f"    {t:8s}  {count:4d} snapshots   (last price: {pr[1]})")

    # Flag snapshots with high violation rate
    bad_snaps = [s for s in results["per_snapshot"] if (s["ipo_violations"] + s["delist_violations"]) > 0]
    if bad_snaps:
        pct = len(bad_snaps) / n * 100 if n else 0
        print(f"\n  {len(bad_snaps)}/{n} snapshots ({pct:.1f}%) have at least one violation")

    return results


# ---------------------------------------------------------------------------
# Audit 2: Price Data Consistency
# ---------------------------------------------------------------------------


def audit_price_consistency(snapshot_dates, price_lookup):
    """Check price availability and extreme returns between consecutive snapshots."""
    print("\n=== AUDIT 2: Price Data Consistency Check ===")

    results = {
        "per_pair": [],
        "total_missing_prices": 0,
        "total_extreme_returns": 0,
        "extreme_returns_detail": [],
        "pairs_checked": 0,
    }

    RETURN_HIGH = 1.0  # >+100%
    RETURN_LOW = -0.80  # <-80%

    for i in range(len(snapshot_dates) - 1):
        date_a = snapshot_dates[i]
        date_b = snapshot_dates[i + 1]

        tickers_a = set(load_rankings_tickers(date_a))
        # Only check tickers in the earlier snapshot (held positions)
        # Restrict to top-ranked for performance: check all
        missing_at_a = 0
        missing_at_b = 0
        extreme = []

        for t in tickers_a:
            price_a = price_lookup.get((t, date_a))
            price_b = price_lookup.get((t, date_b))

            if price_a is None:
                missing_at_a += 1
            if price_b is None:
                missing_at_b += 1

            if price_a and price_b and price_a > 0:
                ret = (price_b - price_a) / price_a
                if ret > RETURN_HIGH or ret < RETURN_LOW:
                    extreme.append(
                        {
                            "ticker": t,
                            "date_a": date_a,
                            "date_b": date_b,
                            "price_a": round(price_a, 2),
                            "price_b": round(price_b, 2),
                            "return_pct": round(ret * 100, 1),
                        }
                    )

        results["per_pair"].append(
            {
                "date_a": date_a,
                "date_b": date_b,
                "tickers_checked": len(tickers_a),
                "missing_price_at_a": missing_at_a,
                "missing_price_at_b": missing_at_b,
                "extreme_returns": len(extreme),
                "extreme_details": extreme[:5],
            }
        )
        results["total_missing_prices"] += missing_at_a + missing_at_b
        results["total_extreme_returns"] += len(extreme)
        results["extreme_returns_detail"].extend(extreme)
        results["pairs_checked"] += 1

    # Print summary
    n = results["pairs_checked"]
    print(f"  Consecutive pairs checked: {n}")
    print(f"  Total missing price entries: {results['total_missing_prices']}")
    print(f"  Total extreme return flags:  {results['total_extreme_returns']}")

    # Summarize extreme returns
    if results["extreme_returns_detail"]:
        print(f"\n  Extreme returns (>{RETURN_HIGH*100:.0f}% or <{RETURN_LOW*100:.0f}%):")
        by_ticker = defaultdict(list)
        for e in results["extreme_returns_detail"]:
            by_ticker[e["ticker"]].append(e["return_pct"])
        top = sorted(by_ticker.items(), key=lambda x: -len(x[1]))[:15]
        for t, rets in top:
            print(f"    {t:8s}  {len(rets)} extreme periods  (range: {min(rets):+.0f}% to {max(rets):+.0f}%)")

    # Missing price coverage
    pairs_with_missing = sum(1 for p in results["per_pair"] if p["missing_price_at_a"] + p["missing_price_at_b"] > 0)
    if pairs_with_missing:
        print(f"\n  {pairs_with_missing}/{n} pairs have missing price data")
        # Show worst
        worst = sorted(results["per_pair"], key=lambda p: -(p["missing_price_at_a"] + p["missing_price_at_b"]))[:5]
        for p in worst:
            miss = p["missing_price_at_a"] + p["missing_price_at_b"]
            print(f"    {p['date_a']} -> {p['date_b']}: {miss} missing ({p['tickers_checked']} tickers)")

    # Cap detail list for JSON output
    results["extreme_returns_detail"] = results["extreme_returns_detail"][:200]

    return results


# ---------------------------------------------------------------------------
# Audit 3: Catalyst Look-Ahead
# ---------------------------------------------------------------------------

# Status strings that imply a resolved outcome (post-hoc knowledge)
RESOLVED_STATUSES = {
    "approved",
    "rejected",
    "refused",
    "withdrawn",
    "complete",
    "completed",
    "crl",
    "crl_issued",
    "terminated",
    "suspended",
    "hit",
    "miss",
    "positive",
    "negative",
    "failed",
    "succeeded",
}


def audit_catalyst_lookahead(snapshot_dates):
    """Check catalyst events for resolved-outcome look-ahead bias."""
    print("\n=== AUDIT 3: Catalyst Look-Ahead Check ===")

    results = {
        "per_snapshot": [],
        "total_lookahead_flags": 0,
        "snapshots_checked": 0,
        "snapshots_missing_catalyst_file": 0,
        "flag_detail": [],
    }

    for snap_date_str in snapshot_dates:
        snap_dt = parse_date(snap_date_str)
        cat_file = PROD_DATA_DIR / f"catalyst_events_{snap_date_str}.json"

        if not cat_file.exists():
            results["snapshots_missing_catalyst_file"] += 1
            continue

        with open(cat_file) as f:
            data = json.load(f)

        summaries = data.get("summaries", [])
        if isinstance(summaries, dict):
            # Handle old format where summaries was {ticker: {...}}
            summaries = list(summaries.values())

        flags = []

        for entry in summaries:
            if not isinstance(entry, dict):
                continue
            ticker = entry.get("ticker", "?")
            events = entry.get("events", [])
            if not events:
                continue

            for ev in events:
                if not isinstance(ev, dict):
                    continue

                # Check 1: event has a resolved status for a future event_date
                event_date_str = ev.get("event_date") or ev.get("date") or ev.get("catalyst_date")
                status = (ev.get("status") or ev.get("outcome") or ev.get("resolution") or "").lower().strip()

                if event_date_str and status:
                    try:
                        event_dt = parse_date(event_date_str)
                    except (ValueError, TypeError):
                        event_dt = None

                    if event_dt and event_dt > snap_dt and status in RESOLVED_STATUSES:
                        flags.append(
                            {
                                "ticker": ticker,
                                "snapshot_date": snap_date_str,
                                "event_date": event_date_str,
                                "status": status,
                                "event_type": ev.get("event_type", ev.get("type", "?")),
                                "reason": "resolved_status_for_future_event",
                            }
                        )

                # Check 2: catalyst references result/outcome text that implies knowledge
                # of what happened (e.g., "APPROVED on 2025-06-15" in a 2025-01-01 snapshot)
                description = (
                    ev.get("description") or ev.get("detail") or ev.get("notes") or ev.get("title") or ""
                ).lower()
                for keyword in ["approved", "rejected", "crl issued", "failed", "terminated", "completed successfully"]:
                    if keyword in description:
                        # Only flag if event is future relative to snapshot
                        if event_dt and event_dt > snap_dt:
                            flags.append(
                                {
                                    "ticker": ticker,
                                    "snapshot_date": snap_date_str,
                                    "event_date": event_date_str,
                                    "keyword_found": keyword,
                                    "event_type": ev.get("event_type", ev.get("type", "?")),
                                    "reason": "outcome_keyword_in_future_event_description",
                                }
                            )
                            break  # one flag per event is enough

            # Check 3: rankings.csv catalyst fields — look for resolved catalyst_mode
            # on a future catalyst_days (this is a cross-check)

        results["per_snapshot"].append(
            {
                "date": snap_date_str,
                "events_checked": sum(len(e.get("events", [])) for e in summaries if isinstance(e, dict)),
                "lookahead_flags": len(flags),
                "flag_details": flags[:10],
            }
        )
        results["total_lookahead_flags"] += len(flags)
        results["flag_detail"].extend(flags)
        results["snapshots_checked"] += 1

    # Also check rankings.csv catalyst columns for look-ahead
    rankings_flags = _audit_rankings_catalyst_lookahead(snapshot_dates)
    results["rankings_catalyst_flags"] = rankings_flags["total_flags"]
    results["flag_detail"].extend(rankings_flags.get("flags", []))
    results["total_lookahead_flags"] += rankings_flags["total_flags"]

    # Print summary
    n = results["snapshots_checked"]
    missing = results["snapshots_missing_catalyst_file"]
    print(f"  Snapshots checked: {n} (missing catalyst files: {missing})")
    print(
        f"  Total look-ahead flags (catalyst events): {results['total_lookahead_flags'] - rankings_flags['total_flags']}"
    )
    print(f"  Total look-ahead flags (rankings catalyst cols): {rankings_flags['total_flags']}")
    print(f"  Combined: {results['total_lookahead_flags']}")

    if results["flag_detail"]:
        by_reason = defaultdict(int)
        for f in results["flag_detail"]:
            by_reason[f.get("reason", "unknown")] += 1
        print("\n  Flags by reason:")
        for reason, count in sorted(by_reason.items(), key=lambda x: -x[1]):
            print(f"    {reason}: {count}")

    # Cap for JSON
    results["flag_detail"] = results["flag_detail"][:200]

    return results


def _audit_rankings_catalyst_lookahead(snapshot_dates):
    """Cross-check: in rankings.csv, flag tickers with catalyst_source that implies
    knowledge from after the snapshot date (e.g., CTGOV data posted after snapshot)."""
    flags = []
    # Heuristic: if catalyst_days is negative (event already passed) but the event
    # is described with a resolved keyword, that's fine — it's historical.
    # But if the snapshot uses catalyst data that couldn't have been known at snapshot time,
    # that's look-ahead. We check metadata.json for collected_at timestamps.

    sample_count = min(len(snapshot_dates), 50)  # check a sample for speed
    step = max(1, len(snapshot_dates) // sample_count)

    for snap_date_str in snapshot_dates[::step]:
        meta_path = SNAPSHOTS_DIR / snap_date_str / "metadata.json"
        if not meta_path.exists():
            continue

        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        # Check if saved_at is much later than as_of_date (retroactive generation)
        saved_at_str = meta.get("saved_at", "")
        as_of_str = meta.get("as_of_date", snap_date_str)
        if saved_at_str:
            try:
                # saved_at is ISO format with Z
                saved_dt = datetime.fromisoformat(saved_at_str.replace("Z", "+00:00")).date()
                as_of_dt = parse_date(as_of_str)
                gap_days = (saved_dt - as_of_dt).days
                if gap_days > 7:  # generated more than a week after the as-of date
                    flags.append(
                        {
                            "snapshot_date": snap_date_str,
                            "saved_at": saved_at_str,
                            "gap_days": gap_days,
                            "reason": "retroactive_generation",
                            "ticker": "N/A",
                        }
                    )
            except (ValueError, TypeError):
                pass

    return {"total_flags": len(flags), "flags": flags}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="PIT Validation Audit for biotech screener snapshots")
    parser.add_argument("--start-date", type=str, default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--audit",
        nargs="+",
        default=["all"],
        choices=["all", "survivorship", "price", "catalyst"],
        help="Which audits to run (default: all)",
    )
    args = parser.parse_args()

    start = parse_date(args.start_date) if args.start_date else None
    end = parse_date(args.end_date) if args.end_date else None

    run_all = "all" in args.audit
    run_survivorship = run_all or "survivorship" in args.audit
    run_price = run_all or "price" in args.audit
    run_catalyst = run_all or "catalyst" in args.audit

    snapshot_dates = get_snapshot_dates(start, end)
    if not snapshot_dates:
        print("ERROR: No snapshot dates found in range.")
        sys.exit(1)

    print("PIT Validation Audit")
    print(f"  Snapshot range: {snapshot_dates[0]} to {snapshot_dates[-1]}")
    print(f"  Total snapshots: {len(snapshot_dates)}")
    print(f"  Audits: {', '.join(a for a in ['survivorship', 'price', 'catalyst'] if (run_all or a in args.audit))}")

    combined = {}

    # Load shared data
    price_ranges = None
    price_lookup = None

    if run_survivorship:
        if price_ranges is None:
            price_ranges = build_price_date_range()
        combined["survivorship"] = audit_survivorship(snapshot_dates, price_ranges)

    if run_price:
        if price_lookup is None:
            price_lookup = build_price_lookup()
        combined["price_consistency"] = audit_price_consistency(snapshot_dates, price_lookup)

    if run_catalyst:
        combined["catalyst_lookahead"] = audit_catalyst_lookahead(snapshot_dates)

    # --- Overall summary ---
    print("\n" + "=" * 60)
    print("OVERALL PIT AUDIT SUMMARY")
    print("=" * 60)

    severity = "CLEAN"
    issues = []

    if "survivorship" in combined:
        s = combined["survivorship"]
        total_v = s["total_ipo_violations"] + s["total_delist_violations"]
        if total_v > 0:
            issues.append(
                f"  Survivorship: {s['total_ipo_violations']} IPO look-ahead + "
                f"{s['total_delist_violations']} zombie delist = {total_v} total"
            )
            severity = "WARNING" if total_v < 50 else "CONTAMINATED"

    if "price_consistency" in combined:
        p = combined["price_consistency"]
        if p["total_extreme_returns"] > 0:
            issues.append(
                f"  Price: {p['total_extreme_returns']} extreme return flags, "
                f"{p['total_missing_prices']} missing prices"
            )
            if p["total_extreme_returns"] > 20:
                severity = "WARNING" if severity == "CLEAN" else severity
        if p["total_missing_prices"] > 100:
            severity = "WARNING" if severity == "CLEAN" else severity

    if "catalyst_lookahead" in combined:
        c = combined["catalyst_lookahead"]
        if c["total_lookahead_flags"] > 0:
            issues.append(f"  Catalyst: {c['total_lookahead_flags']} look-ahead flags")
            if c["total_lookahead_flags"] > 10:
                severity = "CONTAMINATED"

    print(f"\n  Verdict: {severity}")
    if issues:
        for iss in issues:
            print(iss)
    else:
        print("  No violations detected.")

    # Save results
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "audit_results.json"

    # Convert defaultdicts and date objects for JSON serialization
    def serialize(obj):
        if isinstance(obj, (date, datetime)):
            return str(obj)
        if isinstance(obj, defaultdict):
            return dict(obj)
        raise TypeError(f"Not JSON serializable: {type(obj)}")

    with open(out_path, "w") as f:
        json.dump(combined, f, indent=2, default=serialize)

    print(f"\n  Detailed results saved to: {out_path}")


if __name__ == "__main__":
    main()

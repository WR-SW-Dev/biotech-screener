"""
EES v3 Veto Backfill

One-shot backfill of veto shadow card ledger across all historical snapshots
in data/snapshots/. Loads prices once, processes all dates in a single pass.

GOVERNANCE: DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE | NO_CRON
"""

import sys
from pathlib import Path

# Import shadow card functions directly
sys.path.insert(0, str(Path(__file__).parent))
from ees_v3_raw_veto_shadow_card import (  # noqa: E402
    SNAP_DIR,
    _sorted_dates,
    apply_raw_veto_core,
    build_new_row,
    load_ledger,
    load_prices,
    load_snapshot,
    save_ledger,
    settle_row,
)

GOVERNANCE = "DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE | NO_CRON"


def main():
    print(f"GOVERNANCE: {GOVERNANCE}", file=sys.stderr)

    # All snapshot dates available
    if not SNAP_DIR.exists():
        print("SNAP_DIR not found", file=sys.stderr)
        sys.exit(1)

    all_dates = sorted(
        d.name
        for d in SNAP_DIR.iterdir()
        if not d.name.startswith("_") and (SNAP_DIR / d.name / "rankings.csv").exists()
    )
    print(f"Found {len(all_dates)} snapshots: {all_dates[0]} -> {all_dates[-1]}", file=sys.stderr)

    # Load prices once
    print("Loading prices...", file=sys.stderr)
    prices = load_prices()
    sdates = _sorted_dates(prices)

    # Load existing ledger
    ledger = load_ledger()
    existing = {r["snap_date"] for r in ledger}
    print(f"Existing ledger rows: {len(ledger)}", file=sys.stderr)

    # Process each snapshot
    added = 0
    for i, snap_date in enumerate(all_dates):
        if snap_date in existing:
            continue

        rows = load_snapshot(snap_date)
        if not rows:
            continue

        selected, vetoed, meta = apply_raw_veto_core(rows, prices, sdates, snap_date)
        new_row = build_new_row(snap_date, selected, vetoed, meta)
        new_row, _ = settle_row(new_row, prices, sdates)
        ledger.append(new_row)
        added += 1

        if added % 20 == 0:
            print(f"  {i+1}/{len(all_dates)} processed, {added} added so far", file=sys.stderr)

    # Settle all rows (including previously existing ones)
    settled_count = 0
    for row in ledger:
        row, changed = settle_row(row, prices, sdates)
        if changed:
            settled_count += 1

    # Sort by snap_date before saving
    ledger.sort(key=lambda r: r["snap_date"])

    save_ledger(ledger)

    # Summary
    settled_5 = sum(1 for r in ledger if r.get("fwd_5d_settled"))
    settled_10 = sum(1 for r in ledger if r.get("fwd_10d_settled"))
    settled_20 = sum(1 for r in ledger if r.get("fwd_20d_settled"))
    n_veto_mean = sum(r.get("n_vetoed", 0) for r in ledger) / len(ledger) if ledger else 0

    print("\n=== Backfill Complete ===", file=sys.stderr)
    print(f"Total ledger rows: {len(ledger)}", file=sys.stderr)
    print(f"New rows added: {added}", file=sys.stderr)
    print(f"Rows settled: {settled_count} (during this run)", file=sys.stderr)
    print(f"Settled at 5d: {settled_5}", file=sys.stderr)
    print(f"Settled at 10d: {settled_10}", file=sys.stderr)
    print(f"Settled at 20d: {settled_20}", file=sys.stderr)
    print(f"Mean veto count/snap: {n_veto_mean:.1f}", file=sys.stderr)
    print(f"Shadow gate (20d): {settled_20}/20 — {'MET' if settled_20 >= 20 else 'UNMET'}", file=sys.stderr)

    print(f"\n{len(ledger)}", end="")


if __name__ == "__main__":
    main()

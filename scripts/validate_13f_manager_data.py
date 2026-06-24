#!/usr/bin/env python3
"""
13F Manager Data Validator

Validates current and historical 13F manager data across:
  1. Registry integrity (CIK gaps, AUM staleness, conditional vs elite split)
  2. Filing status completeness (registry vs EDGAR status)
  3. Snapshot coverage (quarters present, manager counts, warning analysis)
  4. CUSIP resolution coverage (universe tickers with no CUSIP mapping)
  5. Manager consistency across quarters (entries/exits, position drift)
  6. Q1 2026 gap detection (all managers filed, snapshot missing)

Usage:
    python scripts/validate_13f_manager_data.py
"""

import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PROD = BASE / "production_data"
DATA = BASE / "data"

REGISTRY_PATH = BASE / "manager_registry.json"
FILING_STATUS = PROD / "13f_filing_status.json"
UNIVERSE_PATH = PROD / "universe.json"
CUSIP_MAP_PATH = PROD / "cusip_static_map.json"
PROD_HIST = PROD / "holdings_history"
REFRESH_DIR = DATA / "13f_refresh_2025q4"
TODAY = date(2026, 6, 23)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_json(path: Path):
    with open(path) as f:
        return json.load(f)


def _snap_summary(snap: dict) -> dict:
    return {
        "quarter_end": snap.get("_schema", {}).get("quarter_end"),
        "managers": list(snap.get("managers", {}).keys()),
        "n_managers": len(snap.get("managers", {})),
        "n_tickers": len(snap.get("tickers", {})),
        "n_warnings": len(snap.get("warnings", [])),
        "warnings": snap.get("warnings", []),
    }


def load_all_snapshots() -> dict:
    """Return {quarter_end: summary} for every snapshot found on disk."""
    snaps = {}
    for d in [REFRESH_DIR, DATA / "13f_2026q1", PROD_HIST]:
        if not d.exists():
            continue
        for f in sorted(d.glob("holdings_*.json")):
            try:
                data = load_json(f)
                s = _snap_summary(data)
                q = s["quarter_end"]
                # Prefer production_data version if duplicate
                if q not in snaps or "production_data" in str(f):
                    s["source"] = str(f.relative_to(BASE))
                    snaps[q] = s
            except Exception as e:
                print(f"  [WARN] Could not load {f}: {e}")
    return snaps


HEADER = "=" * 70


def section(title: str):
    print(f"\n{HEADER}")
    print(f"  {title}")
    print(HEADER)


def ok(msg):
    print(f"  [OK]   {msg}")


def warn(msg):
    print(f"  [WARN] {msg}")


def err(msg):
    print(f"  [ERR]  {msg}")


def info(msg):
    print(f"         {msg}")


# ---------------------------------------------------------------------------
# 1. Registry integrity
# ---------------------------------------------------------------------------


def validate_registry(registry: dict) -> dict:
    section("1. REGISTRY INTEGRITY")

    elite = registry.get("elite_core", [])
    conditional = registry.get("conditional", [])
    meta = registry.get("metadata", {})

    print(f"  elite_core: {len(elite)}  |  conditional: {len(conditional)}")
    if meta:
        info(f"metadata keys: {list(meta.keys())}")

    # Duplicate CIKs
    all_entries = elite + conditional
    cik_counts = defaultdict(list)
    for m in all_entries:
        cik_counts[m["cik"]].append(m["name"])
    dupes = {cik: names for cik, names in cik_counts.items() if len(names) > 1}
    if dupes:
        for cik, names in dupes.items():
            err(f"Duplicate CIK {cik}: {names}")
    else:
        ok("No duplicate CIKs")

    # Missing required fields
    missing_fields = []
    for m in all_entries:
        for field in ("cik", "name", "aum_b", "style"):
            if not m.get(field):
                missing_fields.append((m.get("name", "?"), field))
    if missing_fields:
        for name, field in missing_fields:
            warn(f"{name} missing field '{field}'")
    else:
        ok("All registry entries have required fields")

    # AUM staleness (rough check — AUM listed as $B, flag zeros)
    stale_aum = [m for m in all_entries if m.get("aum_b", 0) <= 0]
    if stale_aum:
        for m in stale_aum:
            warn(f"{m['name']} has aum_b={m.get('aum_b')}")
    else:
        ok("All managers have positive AUM")

    # Style distribution
    styles = defaultdict(int)
    for m in all_entries:
        styles[m.get("style", "unknown")] += 1
    info(f"Styles: {dict(styles)}")

    return {m["cik"]: m["name"] for m in all_entries}


# ---------------------------------------------------------------------------
# 2. Filing status completeness
# ---------------------------------------------------------------------------


def validate_filing_status(registry_ciks: dict, filing_status: dict):
    section("2. FILING STATUS vs REGISTRY")

    last_check = filing_status.get("last_check", "unknown")
    filed = filing_status.get("filed", {})
    not_filed = filing_status.get("not_filed", {})

    # Filing status freshness
    try:
        check_dt = datetime.fromisoformat(last_check)
        age_days = (datetime.now() - check_dt).days
        if age_days > 14:
            warn(f"Filing status is {age_days}d old (last_check: {last_check})")
        else:
            ok(f"Filing status fresh: {last_check} ({age_days}d ago)")
    except Exception:
        warn(f"Cannot parse last_check: {last_check}")

    print(f"\n  Filed: {len(filed)}  |  Not filed: {len(not_filed)}")

    if not_filed:
        for cik, info_d in not_filed.items():
            err(f"NOT FILED: {info_d.get('name', '?')} ({cik})")

    # Registry gap: in registry but not in filing status
    status_ciks = set(filed.keys()) | set(not_filed.keys())
    in_reg_not_status = set(registry_ciks.keys()) - status_ciks
    if in_reg_not_status:
        print()
        warn(f"{len(in_reg_not_status)} registry manager(s) NOT in filing status:")
        for cik in sorted(in_reg_not_status):
            warn(f"  {registry_ciks[cik]} ({cik})")
    else:
        ok("All registry managers present in filing status")

    # Surplus: in filing status but not in registry
    in_status_not_reg = status_ciks - set(registry_ciks.keys())
    if in_status_not_reg:
        print()
        info(f"{len(in_status_not_reg)} tracked manager(s) in filing status but NOT in registry:")
        for cik in sorted(in_status_not_reg):
            name = filed.get(cik, not_filed.get(cik, {})).get("name", "?")
            info(f"  {name} ({cik})")

    # Q1 2026 snapshot gap
    print()
    info("Q1 2026 (period 2026-03-31): all 53 managers filed by May 18.")
    info("Checking if Q1 2026 snapshot exists...")
    q1_candidates = [
        PROD_HIST / "holdings_2026-03-31.json",
        REFRESH_DIR.parent / "13f_refresh_2026q1" / "holdings_2026-03-31.json",
        DATA / "13f_2026q1" / "holdings_2026-03-31.json",
    ]
    found_q1 = next((p for p in q1_candidates if p.exists()), None)
    if found_q1:
        ok(f"Q1 2026 snapshot exists: {found_q1.relative_to(BASE)}")
    else:
        err("Q1 2026 snapshot MISSING — 53 managers filed, extraction not run")


# ---------------------------------------------------------------------------
# 3. Snapshot coverage
# ---------------------------------------------------------------------------


def validate_snapshot_coverage(snapshots: dict, registry_ciks: dict):
    section("3. SNAPSHOT COVERAGE (ALL QUARTERS)")

    if not snapshots:
        err("No snapshots found")
        return

    quarters = sorted(snapshots.keys())
    print(f"\n  {'Quarter':<14} {'Managers':>9} {'Tickers':>8} {'Warnings':>9}  Source")
    print(f"  {'-'*14} {'-'*9} {'-'*8} {'-'*9}  ------")
    for q in quarters:
        s = snapshots[q]
        marker = " ← BROKEN" if s["n_managers"] < 10 else ""
        print(f"  {q:<14} {s['n_managers']:>9} {s['n_tickers']:>8} {s['n_warnings']:>9}  {s['source']}{marker}")

    # Flag quarters with abnormally low manager counts
    counts = [s["n_managers"] for s in snapshots.values()]
    median_count = sorted(counts)[len(counts) // 2]
    print()
    for q, s in snapshots.items():
        if s["n_managers"] < median_count * 0.5:
            err(
                f"{q}: only {s['n_managers']} managers (median={median_count}) — extraction ran before filings were due"
            )
            for w in s["warnings"][:5]:
                info(f"  sample warning: {w}")
            if len(s["warnings"]) > 5:
                info(f"  ... and {len(s['warnings']) - 5} more")

    # Check registry managers present in most recent clean snapshot
    clean = [(q, s) for q, s in snapshots.items() if s["n_managers"] >= median_count * 0.5]
    if clean:
        latest_q, latest_s = sorted(clean)[-1]
        snap_ciks = set(latest_s["managers"])
        reg_ciks = set(registry_ciks.keys())

        missing_from_snap = reg_ciks - snap_ciks
        if missing_from_snap:
            warn(f"Registry managers absent from latest clean snapshot ({latest_q}):")
            for cik in sorted(missing_from_snap):
                warn(f"  {registry_ciks.get(cik, '?')} ({cik})")
        else:
            ok(f"All registry managers present in latest snapshot ({latest_q})")

        extra_in_snap = snap_ciks - reg_ciks
        if extra_in_snap:
            info(f"{len(extra_in_snap)} non-registry CIKs in {latest_q} snapshot:")
            for cik in sorted(extra_in_snap):
                info(f"  {cik}")


# ---------------------------------------------------------------------------
# 4. CUSIP resolution coverage
# ---------------------------------------------------------------------------


def validate_cusip_coverage(universe: list, cusip_map: dict):
    section("4. CUSIP RESOLUTION COVERAGE")

    universe_tickers = {
        s.get("ticker", "").strip().upper()
        for s in universe
        if s.get("ticker") and s.get("ticker") != "_XBI_BENCHMARK_"
    }

    # Build reverse map: ticker -> [CUSIPs]
    ticker_to_cusip = defaultdict(list)
    for cusip, ticker in cusip_map.items():
        if isinstance(ticker, str):
            ticker_to_cusip[ticker.upper()].append(cusip)
        elif isinstance(ticker, dict):
            t = ticker.get("ticker", "")
            if t:
                ticker_to_cusip[t.upper()].append(cusip)

    covered = universe_tickers & set(ticker_to_cusip.keys())
    uncovered = universe_tickers - set(ticker_to_cusip.keys())

    print(f"  Universe tickers: {len(universe_tickers)}")
    print(f"  CUSIP map entries: {len(cusip_map)}")
    print(f"  Tickers with CUSIP mapping: {len(covered)}")

    if uncovered:
        warn(f"{len(uncovered)} tickers have NO CUSIP mapping (13F resolution will fail):")
        for t in sorted(uncovered):
            warn(f"  {t}")
    else:
        ok("All universe tickers have CUSIP mappings")

    # Multi-CUSIP tickers (e.g., share classes, warrants)
    multi = {t: cs for t, cs in ticker_to_cusip.items() if t in universe_tickers and len(cs) > 1}
    if multi:
        info(f"{len(multi)} tickers with multiple CUSIPs:")
        for t, cs in sorted(multi.items()):
            info(f"  {t}: {cs}")


# ---------------------------------------------------------------------------
# 5. Manager consistency across quarters
# ---------------------------------------------------------------------------


def validate_manager_consistency(snapshots: dict, registry_ciks: dict):
    section("5. MANAGER CONSISTENCY ACROSS QUARTERS")

    # Only consider clean snapshots
    counts = [s["n_managers"] for s in snapshots.values()]
    if not counts:
        return
    median_count = sorted(counts)[len(counts) // 2]
    clean = {q: s for q, s in snapshots.items() if s["n_managers"] >= median_count * 0.5}
    quarters = sorted(clean.keys())

    if len(quarters) < 2:
        info("Fewer than 2 clean snapshots — skipping consistency check")
        return

    # Track which CIKs appear per quarter
    presence = {}  # {cik: [quarters]}
    all_ciks = set()
    for q in quarters:
        ciks = set(clean[q]["managers"])
        all_ciks |= ciks
        for cik in ciks:
            presence.setdefault(cik, []).append(q)

    # Managers present in ALL quarters
    always_present = {cik for cik, qs in presence.items() if len(qs) == len(quarters)}
    sometimes_present = {cik for cik, qs in presence.items() if 0 < len(qs) < len(quarters)}

    print(f"  Quarters analyzed: {', '.join(quarters)}")
    print(f"  Managers always present: {len(always_present)}")
    print(f"  Managers sometimes present: {len(sometimes_present)}")
    print()

    # Show entry/exit table for inconsistent managers
    if sometimes_present:
        print(f"  {'CIK':<15} {'Name':<38} {'Present In'}")
        print(f"  {'-'*15} {'-'*38} {'-'*30}")
        for cik in sorted(sometimes_present):
            name = registry_ciks.get(cik, "(unregistered)")
            qs = presence[cik]
            absent = [q for q in quarters if q not in qs]
            marker = ""
            if absent[-1] == quarters[-1]:
                marker = " ← DROPPED OUT"
            elif absent[0] == quarters[0]:
                marker = " ← LATE ENTRY"
            print(f"  {cik:<15} {name[:38]:<38} {', '.join(q[2:7] for q in qs)}{marker}")

    # Ticker coverage drift
    print()
    ticker_counts = [(q, clean[q]["n_tickers"]) for q in quarters]
    drifts = []
    for i in range(1, len(ticker_counts)):
        q_prev, n_prev = ticker_counts[i - 1]
        q_curr, n_curr = ticker_counts[i]
        delta = n_curr - n_prev
        if abs(delta) > 20:
            drifts.append((q_prev, q_curr, delta))

    if drifts:
        warn("Large ticker-count swings between quarters:")
        for q_prev, q_curr, delta in drifts:
            warn(f"  {q_prev} -> {q_curr}: {delta:+d} tickers")
    else:
        ok("Ticker count stable across quarters")


# ---------------------------------------------------------------------------
# 6. Production snapshot integrity
# ---------------------------------------------------------------------------


def validate_production_snapshots():
    section("6. PRODUCTION SNAPSHOT INTEGRITY (SHA256)")

    manifest_path = PROD_HIST / "manifest.json"
    if not manifest_path.exists():
        warn("No manifest.json in production_data/holdings_history")
        return

    manifest = load_json(manifest_path)
    quarters_info = manifest.get("quarters", [])
    run_id = manifest.get("run_id", "?")
    print(f"  run_id: {run_id}")
    print(f"  quarters in manifest: {len(quarters_info)}")

    import hashlib

    for q_info in quarters_info:
        fname = q_info.get("filename")
        expected_hash = q_info.get("sha256", "")
        fpath = PROD_HIST / fname
        if not fpath.exists():
            err(f"{fname}: FILE MISSING")
            continue
        actual_hash = hashlib.sha256(fpath.read_bytes()).hexdigest()
        if actual_hash == expected_hash:
            ok(f"{fname}: SHA256 OK")
        else:
            err(f"{fname}: SHA256 MISMATCH")
            info(f"  expected: {expected_hash}")
            info(f"  actual:   {actual_hash}")

    # Check for warnings in production snapshots
    for q_info in quarters_info:
        if q_info.get("warnings_count", 0) > 0:
            fname = q_info["filename"]
            fpath = PROD_HIST / fname
            if fpath.exists():
                snap = load_json(fpath)
                warn(f"{fname} has {q_info['warnings_count']} warning(s):")
                for w in snap.get("warnings", [])[:5]:
                    info(f"  {w}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def print_summary(issues: dict):
    section("SUMMARY")
    total_err = issues.get("errors", 0)
    total_warn = issues.get("warnings", 0)
    print(f"\n  Errors:   {total_err}")
    print(f"  Warnings: {total_warn}")

    if total_err == 0 and total_warn == 0:
        print("\n  All checks passed.")
    elif total_err > 0:
        print("\n  Action required: review [ERR] items above.")
    else:
        print("\n  Review [WARN] items — may require attention.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print(f"\n{'='*70}")
    print("  13F MANAGER DATA VALIDATION")
    print(f"  Run date: {TODAY}")
    print(f"{'='*70}")

    registry = load_json(REGISTRY_PATH)
    filing_status = load_json(FILING_STATUS)
    universe = load_json(UNIVERSE_PATH)
    cusip_map = load_json(CUSIP_MAP_PATH)
    snapshots = load_all_snapshots()

    registry_ciks = validate_registry(registry)
    validate_filing_status(registry_ciks, filing_status)
    validate_snapshot_coverage(snapshots, registry_ciks)
    validate_cusip_coverage(universe, cusip_map)
    validate_manager_consistency(snapshots, registry_ciks)
    validate_production_snapshots()

    print()


if __name__ == "__main__":
    main()

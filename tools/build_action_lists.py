#!/usr/bin/env python3
"""Build Action Lists — per-bucket CSV files from a snapshot's rankings.csv.

Reads a promoted snapshot and produces four CSV files split by catalyst
horizon bucket, plus a README.md summary.

Output:
    action_lists/binary_0_30.csv
    action_lists/binary_31_90.csv
    action_lists/binary_91_180.csv
    action_lists/less_binary.csv
    action_lists/README.md

Classification rules (deterministic):
    binary  iff catalyst_mode == "specific_days" AND 1 <= catalyst_days <= 180
    less_binary  otherwise (blended_window, no_upcoming, missing, or far-out)

Within each bucket: sorted by actionable_rank ASC, then ticker ASC.

Usage:
    python3 tools/build_action_lists.py --snapshot-dir data/snapshots/2026-03-08
    python3 tools/build_action_lists.py --as-of-date 2026-03-08
    python3 tools/build_action_lists.py --as-of-date 2026-03-08 --out-dir output/action_lists
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SNAPSHOTS_ROOT = PROJECT_ROOT / "data" / "snapshots"

# Columns carried into action list CSVs (subset of rankings.csv)
ACTION_LIST_COLUMNS = [
    "ticker",
    "actionable_rank",
    "eligible",
    "tier_any",
    "target_weight_pct",
    "catalyst_days",
    "catalyst_mode",
    "catalyst_bucket",
    "catalyst_strength",
    "archetype",
    "alpha_cohort_key",
    "mom_state",
    "industry_group",
    "size_band",
]

# Account-aware sizing: per-name dollar caps by size band.
# Keys are size_band values; values are max weight pct per name.
DEFAULT_BAND_CAPS: Dict[str, float] = {
    "XS": 2.0,
    "S": 3.0,
    "M": 5.0,
    "L": 5.0,
}

# Columns appended when --account-usd is set
SIZING_COLUMNS = ["weight_pct_raw", "weight_pct_capped", "target_dollars"]

# Risk-rail columns (always present)
RAIL_COLUMNS = ["gap_risk", "price_coverage"]

# Gap-risk thresholds for binary_0_30 names
GAP_RISK_IMMINENT_DAYS = 7  # catalyst within 7 trading days → HIGH gap risk

# Bucket definitions
BUCKET_NAMES = ["binary_0_30", "binary_31_90", "binary_91_180", "less_binary"]

BUCKET_DISPLAY = {
    "binary_0_30": "Binary 0-30d (event imminent)",
    "binary_31_90": "Binary 31-90d (setup window)",
    "binary_91_180": "Binary 91-180d (pipeline on deck)",
    "less_binary": "Less Binary (carry / no dated event)",
}

BAND_CAP_FALLBACK = 5.0  # cap for unknown size_band values

# Microcap inversion sleeve: bottom-K of less-binary bucket, XS band only.
# Opt-in only (--include-microcap-sleeve).  Deliberately exposed to
# illiquidity/microcap risk — do not use for size-constrained accounts.
MICROCAP_SLEEVE_NAME = "microcap_inversion"
MICROCAP_SLEEVE_SIZE_BANDS = {"XS"}  # size_band values included
MICROCAP_SLEEVE_DEFAULT_K = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val: Any) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _sort_key(row: Dict[str, str]) -> Tuple[float, str]:
    """Sort by actionable_rank ASC then ticker ASC (deterministic)."""
    rank = _safe_float(row.get("actionable_rank", ""), 9999.0)
    ticker = row.get("ticker", "")
    return (rank, ticker)


def _find_latest_snapshot_date() -> Optional[str]:
    if not SNAPSHOTS_ROOT.is_dir():
        return None
    candidates = []
    for d in SNAPSHOTS_ROOT.iterdir():
        name = d.name
        if len(name) == 10 and name[4] == "-" and name[7] == "-":
            try:
                datetime.strptime(name, "%Y-%m-%d")
                candidates.append(name)
            except ValueError:
                pass
    return max(candidates) if candidates else None


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_action_bucket(row: Dict[str, str]) -> str:
    """Classify a rankings row into an action list bucket.

    Returns one of: "binary_0_30", "binary_31_90", "binary_91_180", "less_binary".

    Rules:
        binary iff catalyst_mode == "specific_days" AND 1 <= catalyst_days <= 180
        Sub-bucket by catalyst_days: 0-30, 31-90, 91-180
        Everything else → less_binary
    """
    mode = (row.get("catalyst_mode") or "").strip()
    days = _safe_int(row.get("catalyst_days"))

    if mode != "specific_days" or days is None or days < 1 or days > 180:
        return "less_binary"

    if days <= 30:
        return "binary_0_30"
    if days <= 90:
        return "binary_31_90"
    return "binary_91_180"


# ---------------------------------------------------------------------------
# Build action lists
# ---------------------------------------------------------------------------


def build_action_lists(
    snapshot_dir: Path,
    *,
    eligible_only: bool = True,
) -> Dict[str, List[Dict[str, str]]]:
    """Read rankings.csv and split into action list buckets.

    Args:
        snapshot_dir: Path to snapshot directory.
        eligible_only: If True, only include eligible names.

    Returns:
        Dict mapping bucket name → list of row dicts, sorted deterministically.
    """
    csv_path = snapshot_dir / "rankings.csv"
    if not csv_path.is_file():
        raise FileNotFoundError(f"rankings.csv not found: {csv_path}")

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    # Filter
    if eligible_only:
        all_rows = [r for r in all_rows if r.get("eligible") == "1"]

    # Classify and sort
    buckets: Dict[str, List[Dict[str, str]]] = {b: [] for b in BUCKET_NAMES}
    for row in all_rows:
        bucket = classify_action_bucket(row)
        # Keep only the action list columns (plus any missing as "")
        slim = {col: row.get(col, "") for col in ACTION_LIST_COLUMNS}
        # Carry source field for risk rail tagging (not emitted to CSV)
        slim["de_beta_xbi_60d_source"] = row.get("de_beta_xbi_60d_source", "")
        buckets[bucket].append(slim)

    # Sort each bucket deterministically
    for bucket_rows in buckets.values():
        bucket_rows.sort(key=_sort_key)

    return buckets


# ---------------------------------------------------------------------------
# Microcap inversion sleeve
# ---------------------------------------------------------------------------


def build_microcap_sleeve(
    snapshot_dir: Path,
    *,
    k: int = MICROCAP_SLEEVE_DEFAULT_K,
    size_bands: Optional[set] = None,
    eligible_only: bool = True,
) -> List[Dict[str, str]]:
    """Build the microcap inversion sleeve from the less-binary bucket.

    Takes the bottom-K names by actionable_rank from the less-binary bucket,
    filtered to XS-band (microcap) names.  This is a *contrarian* selection:
    the model's worst-ranked less-binary names outperform in OOS, but only
    among microcaps.

    Args:
        snapshot_dir: Path to snapshot directory.
        k: Number of names to include (bottom-K by rank).
        size_bands: Set of size_band values to include (default: {"XS"}).
        eligible_only: If True, only include eligible names.

    Returns:
        List of row dicts, sorted by actionable_rank DESC then ticker ASC
        (worst-ranked first, since this is a contrarian sleeve).
    """
    if size_bands is None:
        size_bands = MICROCAP_SLEEVE_SIZE_BANDS

    csv_path = snapshot_dir / "rankings.csv"
    if not csv_path.is_file():
        return []

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    if eligible_only:
        all_rows = [r for r in all_rows if r.get("eligible") == "1"]

    # Filter to less-binary bucket + specified size bands
    sleeve_rows = []
    for row in all_rows:
        bucket = classify_action_bucket(row)
        band = (row.get("size_band") or "").strip()
        if bucket == "less_binary" and band in size_bands:
            slim = {col: row.get(col, "") for col in ACTION_LIST_COLUMNS}
            sleeve_rows.append(slim)

    # Sort by actionable_rank ASC (best to worst), then take bottom-K
    sleeve_rows.sort(key=_sort_key)
    bottom_k = sleeve_rows[-k:] if len(sleeve_rows) > k else sleeve_rows

    # Re-sort bottom-K: worst rank first (contrarian ordering)
    bottom_k.sort(key=lambda r: (-_safe_float(r.get("actionable_rank", ""), 0.0), r.get("ticker", "")))

    return bottom_k


# ---------------------------------------------------------------------------
# Risk rails
# ---------------------------------------------------------------------------


def apply_risk_rails(
    buckets: Dict[str, List[Dict[str, str]]],
) -> None:
    """Tag each row with gap_risk and price_coverage flags (in-place).

    gap_risk:
        "HIGH"  — binary_0_30 name with catalyst_days <= 7 (imminent event)
        "MODERATE" — binary_0_30 name with catalyst_days > 7
        ""      — all other buckets

    price_coverage:
        "OK"      — de_beta_xbi_60d_source is non-empty (price history present)
        "MISSING" — de_beta_xbi_60d_source is empty (no beta/alpha/drawdown)
    """
    for bucket_name, rows in buckets.items():
        for row in rows:
            # Gap risk (only relevant for binary_0_30)
            if bucket_name == "binary_0_30":
                days = _safe_int(row.get("catalyst_days"))
                if days is not None and days <= GAP_RISK_IMMINENT_DAYS:
                    row["gap_risk"] = "HIGH"
                else:
                    row["gap_risk"] = "MODERATE"
            else:
                row["gap_risk"] = ""

            # Price coverage
            src = (row.get("de_beta_xbi_60d_source") or "").strip()
            row["price_coverage"] = "OK" if src else "MISSING"


# ---------------------------------------------------------------------------
# Account-aware sizing
# ---------------------------------------------------------------------------


def apply_account_sizing(
    buckets: Dict[str, List[Dict[str, str]]],
    account_usd: float,
    band_caps: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Add per-name dollar sizing columns to every row in *buckets* (in-place).

    For each row, appends:
        weight_pct_raw   — the DEM target_weight_pct (unchanged)
        weight_pct_capped — min(raw, band cap)
        target_dollars   — account_usd * capped / 100

    Args:
        buckets: Dict of bucket_name → list of row dicts (mutated in-place).
        account_usd: Total account value in dollars.
        band_caps: Per-name max weight by size_band.  Defaults to DEFAULT_BAND_CAPS.

    Returns:
        Summary dict with keys: total_allocated, residual_cash,
        per_bucket totals, per_band totals.
    """
    if band_caps is None:
        band_caps = DEFAULT_BAND_CAPS

    per_bucket: Dict[str, float] = {}
    per_band: Dict[str, float] = {}
    total_allocated = 0.0

    for bucket_name, rows in buckets.items():
        bucket_total = 0.0
        for row in rows:
            raw = _safe_float(row.get("target_weight_pct", ""))
            band = (row.get("size_band") or "").strip()
            cap = band_caps.get(band, BAND_CAP_FALLBACK)
            capped = min(raw, cap)
            dollars = account_usd * capped / 100.0

            row["weight_pct_raw"] = f"{raw:.4f}"
            row["weight_pct_capped"] = f"{capped:.4f}"
            row["target_dollars"] = f"{dollars:.2f}"

            bucket_total += dollars
            per_band[band] = per_band.get(band, 0.0) + dollars

        per_bucket[bucket_name] = bucket_total
        total_allocated += bucket_total

    return {
        "account_usd": account_usd,
        "total_allocated": total_allocated,
        "residual_cash": account_usd - total_allocated,
        "per_bucket": per_bucket,
        "per_band": per_band,
        "band_caps": band_caps,
    }


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def write_action_lists(
    buckets: Dict[str, List[Dict[str, str]]],
    out_dir: Path,
    *,
    as_of_date: str = "",
    microcap_sleeve: Optional[List[Dict[str, str]]] = None,
    sizing_summary: Optional[Dict[str, Any]] = None,
) -> Path:
    """Write per-bucket CSVs and README.md to out_dir.

    Args:
        buckets: Dict of bucket_name → list of row dicts.
        out_dir: Output directory path.
        as_of_date: Snapshot date string for README header.
        microcap_sleeve: Optional sleeve rows.
        sizing_summary: If set (from apply_account_sizing), include sizing
            columns in CSVs and account summary in README.

    Returns the out_dir path.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    has_sizing = sizing_summary is not None
    # Check if risk rails have been applied (gap_risk key present in rows)
    sample_rows = next((rows for rows in buckets.values() if rows), [])
    has_rails = sample_rows and "gap_risk" in sample_rows[0]
    cols = ACTION_LIST_COLUMNS + (RAIL_COLUMNS if has_rails else []) + (SIZING_COLUMNS if has_sizing else [])

    for bucket_name in BUCKET_NAMES:
        rows = buckets.get(bucket_name, [])
        csv_path = out_dir / f"{bucket_name}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    # Microcap inversion sleeve (opt-in)
    if microcap_sleeve is not None:
        # Sleeve already has size_band in ACTION_LIST_COLUMNS now
        sleeve_cols = cols
        csv_path = out_dir / f"{MICROCAP_SLEEVE_NAME}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=sleeve_cols, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(microcap_sleeve)

    # README summary
    readme = _build_readme(
        buckets,
        as_of_date,
        microcap_sleeve=microcap_sleeve,
        sizing_summary=sizing_summary,
    )
    (out_dir / "README.md").write_text(readme, encoding="utf-8")

    return out_dir


def _build_readme(
    buckets: Dict[str, List[Dict[str, str]]],
    as_of_date: str,
    *,
    microcap_sleeve: Optional[List[Dict[str, str]]] = None,
    sizing_summary: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate a summary README.md for the action lists."""
    lines: List[str] = []
    lines.append(f"# Action Lists — {as_of_date}")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    total = sum(len(rows) for rows in buckets.values())
    lines.append(f"**Total names**: {total}")
    lines.append("")

    # Summary table
    lines.append("| Bucket | Count | Total Weight | Median Weight | Top Tickers |")
    lines.append("|--------|-------|-------------|---------------|-------------|")

    for bucket_name in BUCKET_NAMES:
        rows = buckets.get(bucket_name, [])
        count = len(rows)
        weights = [_safe_float(r.get("target_weight_pct", "")) for r in rows]
        total_wt = sum(weights)
        median_wt = statistics.median(weights) if weights else 0.0
        top_tickers = ", ".join(r.get("ticker", "") for r in rows[:5])
        display = BUCKET_DISPLAY.get(bucket_name, bucket_name)
        lines.append(f"| {display} | {count} | {total_wt:.1f}% | {median_wt:.2f}% | {top_tickers} |")

    lines.append("")

    # Binary vs less-binary aggregate
    binary_count = sum(len(buckets.get(b, [])) for b in ["binary_0_30", "binary_31_90", "binary_91_180"])
    binary_weight = sum(
        _safe_float(r.get("target_weight_pct", ""))
        for b in ["binary_0_30", "binary_31_90", "binary_91_180"]
        for r in buckets.get(b, [])
    )
    lb_count = len(buckets.get("less_binary", []))
    lb_weight = sum(_safe_float(r.get("target_weight_pct", "")) for r in buckets.get("less_binary", []))

    lines.append("## Book Summary")
    lines.append("")
    lines.append(f"- **Binary book**: {binary_count} names, {binary_weight:.1f}% weight")
    lines.append(f"- **Less-binary book**: {lb_count} names, {lb_weight:.1f}% weight")
    lines.append("")

    # Account sizing section (if --account-usd was provided)
    if sizing_summary:
        acct = sizing_summary["account_usd"]
        alloc = sizing_summary["total_allocated"]
        residual = sizing_summary["residual_cash"]
        lines.append("## Account Sizing")
        lines.append("")
        lines.append(f"- **Account**: ${acct:,.0f}")
        lines.append(f"- **Total allocated**: ${alloc:,.2f}")
        lines.append(f"- **Residual cash**: ${residual:,.2f} ({residual / acct * 100:.1f}%)")
        lines.append("")
        lines.append("### Band Caps (per-name max)")
        lines.append("")
        lines.append("| Band | Cap |")
        lines.append("|------|-----|")
        for band, cap in sorted(sizing_summary["band_caps"].items()):
            lines.append(f"| {band} | {cap:.1f}% |")
        lines.append("")
        lines.append("### Per-Bucket Allocation")
        lines.append("")
        lines.append("| Bucket | Allocated |")
        lines.append("|--------|-----------|")
        for bucket_name in BUCKET_NAMES:
            bucket_alloc = sizing_summary["per_bucket"].get(bucket_name, 0.0)
            display = BUCKET_DISPLAY.get(bucket_name, bucket_name)
            lines.append(f"| {display} | ${bucket_alloc:,.2f} |")
        lines.append("")
        lines.append("### Per-Band Allocation")
        lines.append("")
        lines.append("| Band | Allocated |")
        lines.append("|------|-----------|")
        for band in sorted(sizing_summary["per_band"].keys()):
            band_alloc = sizing_summary["per_band"][band]
            lines.append(f"| {band} | ${band_alloc:,.2f} |")
        lines.append("")

    # Risk rails summary (if applied)
    all_rows_flat = [r for rows in buckets.values() for r in rows]
    if all_rows_flat and "gap_risk" in all_rows_flat[0]:
        high_gap = [r for r in buckets.get("binary_0_30", []) if r.get("gap_risk") == "HIGH"]
        missing_price = [r for r in all_rows_flat if r.get("price_coverage") == "MISSING"]
        lines.append("## Risk Rails")
        lines.append("")
        if high_gap:
            tickers = ", ".join(r.get("ticker", "") for r in high_gap)
            lines.append(
                f"- **Gap risk HIGH** ({len(high_gap)} names, " f"catalyst <= {GAP_RISK_IMMINENT_DAYS}d): {tickers}"
            )
        else:
            lines.append("- **Gap risk HIGH**: none")
        if missing_price:
            tickers = ", ".join(r.get("ticker", "") for r in missing_price)
            lines.append(f"- **Price coverage MISSING** ({len(missing_price)} names): {tickers}")
        else:
            lines.append("- **Price coverage**: all names OK")
        lines.append("")

    # Microcap inversion sleeve (if present)
    if microcap_sleeve:
        lines.append("## Microcap Inversion Sleeve (opt-in)")
        lines.append("")
        lines.append(
            "**WARNING**: This sleeve is intentionally microcap/illiquidity-exposed. "
            "Use only when account size permits and you accept concentration risk "
            "in XS-band names with no dated catalyst."
        )
        lines.append("")
        lines.append(f"- **Names**: {len(microcap_sleeve)}")
        lines.append("- **Selection**: Bottom-K by actionable_rank (contrarian)")
        lines.append("- **Universe**: less-binary bucket, XS band only")
        sleeve_weights = [_safe_float(r.get("target_weight_pct", "")) for r in microcap_sleeve]
        if sleeve_weights:
            lines.append(f"- **Median weight (from DEM)**: {statistics.median(sleeve_weights):.2f}%")
        lines.append("")
        lines.append("| Rank | Ticker | Tier | Catalyst Mode | Weight |")
        lines.append("|------|--------|------|---------------|--------|")
        for r in microcap_sleeve[:20]:
            lines.append(
                f"| {r.get('actionable_rank', '')} "
                f"| {r.get('ticker', '')} "
                f"| {r.get('tier_any', '')} "
                f"| {r.get('catalyst_mode', '')} "
                f"| {_safe_float(r.get('target_weight_pct', '')):.2f}% |"
            )
        lines.append("")

    # Classification rules
    lines.append("## Classification Rules")
    lines.append("")
    lines.append("- **Binary**: `catalyst_mode == specific_days` AND `1 <= catalyst_days <= 180`")
    lines.append("  - **0-30d**: event imminent (highest vol)")
    lines.append("  - **31-90d**: setup window (position building)")
    lines.append("  - **91-180d**: pipeline on deck")
    lines.append("- **Less-binary**: everything else (blended_window, no_upcoming, missing, far-out >540d)")
    lines.append("- Sort: `actionable_rank` ASC, then `ticker` ASC (deterministic)")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Build per-bucket action list CSVs from a snapshot's rankings.csv.",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=None,
        help="Path to snapshot directory (e.g. data/snapshots/2026-03-08)",
    )
    parser.add_argument(
        "--as-of-date",
        default=None,
        help="Snapshot date (YYYY-MM-DD); discovers snapshot in data/snapshots/",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default: action_lists/ inside snapshot dir)",
    )
    parser.add_argument(
        "--include-ineligible",
        action="store_true",
        default=False,
        help="Include ineligible names (default: eligible only)",
    )
    parser.add_argument(
        "--include-microcap-sleeve",
        action="store_true",
        default=False,
        help=(
            "Include microcap inversion sleeve: bottom-K of less-binary bucket, "
            "XS band only. Intentionally illiquidity-exposed (research/opt-in)."
        ),
    )
    parser.add_argument(
        "--microcap-sleeve-k",
        type=int,
        default=MICROCAP_SLEEVE_DEFAULT_K,
        help=f"Number of names in microcap sleeve (default: {MICROCAP_SLEEVE_DEFAULT_K}).",
    )
    parser.add_argument(
        "--account-usd",
        type=float,
        default=None,
        help="Account value in USD.  Enables per-name dollar sizing with band caps.",
    )
    parser.add_argument(
        "--band-caps",
        default=None,
        help=(
            "Per-name max weight by size band, comma-separated KEY=VAL pairs. "
            "Example: XS=2,S=3,M=5,L=5  (default: XS=2, S=3, M=5, L=5)"
        ),
    )
    args = parser.parse_args()

    if args.snapshot_dir:
        snap_dir = args.snapshot_dir
    elif args.as_of_date:
        snap_dir = SNAPSHOTS_ROOT / args.as_of_date
    else:
        latest = _find_latest_snapshot_date()
        if latest is None:
            print("ERROR: No snapshots found and no --snapshot-dir / --as-of-date given.", file=sys.stderr)
            sys.exit(1)
        snap_dir = SNAPSHOTS_ROOT / latest

    if not snap_dir.is_dir():
        print(f"ERROR: Snapshot directory not found: {snap_dir}", file=sys.stderr)
        sys.exit(1)

    out_dir = args.out_dir or (snap_dir / "action_lists")

    buckets = build_action_lists(snap_dir, eligible_only=not args.include_ineligible)

    # Risk rails (always applied)
    apply_risk_rails(buckets)

    sleeve = None
    if args.include_microcap_sleeve:
        sleeve = build_microcap_sleeve(
            snap_dir,
            k=args.microcap_sleeve_k,
            eligible_only=not args.include_ineligible,
        )

    # Account-aware sizing (opt-in)
    sizing_summary = None
    if args.account_usd is not None:
        band_caps = None
        if args.band_caps:
            band_caps = {}
            for pair in args.band_caps.split(","):
                k, v = pair.strip().split("=")
                band_caps[k.strip()] = float(v.strip())
        sizing_summary = apply_account_sizing(buckets, args.account_usd, band_caps)

    write_action_lists(
        buckets,
        out_dir,
        as_of_date=snap_dir.name,
        microcap_sleeve=sleeve,
        sizing_summary=sizing_summary,
    )

    total = sum(len(rows) for rows in buckets.values())
    print(f"Action lists → {out_dir}")
    for b in BUCKET_NAMES:
        print(f"  {b}: {len(buckets[b])} names")
    print(f"  total: {total}")
    if sleeve is not None:
        print(f"  {MICROCAP_SLEEVE_NAME}: {len(sleeve)} names (opt-in sleeve)")
    if sizing_summary:
        print(f"  account: ${sizing_summary['account_usd']:,.0f}")
        print(f"  allocated: ${sizing_summary['total_allocated']:,.2f}")
        print(f"  residual cash: ${sizing_summary['residual_cash']:,.2f}")

    # Risk rail summary
    high_gap = [r for r in buckets.get("binary_0_30", []) if r.get("gap_risk") == "HIGH"]
    all_rows = [r for rows in buckets.values() for r in rows]
    missing_price = [r for r in all_rows if r.get("price_coverage") == "MISSING"]
    if high_gap:
        print(f"  gap_risk HIGH: {', '.join(r['ticker'] for r in high_gap)}")
    if missing_price:
        print(f"  price_coverage MISSING: {', '.join(r['ticker'] for r in missing_price)}")


if __name__ == "__main__":
    main()

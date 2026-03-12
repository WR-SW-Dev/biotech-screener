#!/usr/bin/env python3
"""Crowding penalty orthogonality analysis.

Tests whether pre-catalyst options activity (crowding signal) adds independent
negative information after controlling for the active clinical-quality tilt.

Key questions:
  1. Is the negative IC stable over time (per-snapshot)?
  2. Is it stronger in binary_now vs less_binary?
  3. Is it concentrated in CLINICAL only, or also DATA_READOUT vs others?
  4. Is it still present after conditioning on clinical_quality_composite?

Uses the existing Massive day-agg cache + archived snapshot data.

Usage:
    python scripts/research/crowding_orthogonality_analysis.py
    python scripts/research/crowding_orthogonality_analysis.py --horizons 5,20,63
"""
from __future__ import annotations

import argparse
import csv
import io
import logging
import sys
import tarfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from common.event_quality_features import compute_clinical_91_180_quality
from scripts.research.build_precatalyst_options_panel import FEATURE_COLUMNS
from scripts.research.build_precatalyst_options_panel import _safe_float as panel_safe_float
from scripts.research.build_precatalyst_options_panel import assign_bucket, classify_family

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("crowding_ortho")

# ---------------------------------------------------------------------------
# Price history loader
# ---------------------------------------------------------------------------

_PRICE_CACHE: Dict[Tuple[str, str], float] = {}


def _load_price_history(path: Path) -> None:
    """Load price_history.csv into {(ticker, date_str): close} dict."""
    if _PRICE_CACHE:
        return
    logger.info("Loading price history from %s ...", path)
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tk = row.get("ticker", "")
            dt = row.get("date", "")
            cl = row.get("close", "")
            if tk and dt and cl:
                try:
                    _PRICE_CACHE[(tk, dt)] = float(cl)
                except ValueError:
                    pass
    logger.info("Loaded %d price records", len(_PRICE_CACHE))


def _forward_return(ticker: str, snap_date: date, horizon: int) -> Optional[float]:
    """Compute forward return over `horizon` trading days.

    Uses the closest available price within ±2 days of the target.
    """
    p0 = _find_price(ticker, snap_date)
    if p0 is None:
        return None

    # Approximate trading-day target: horizon * 7/5 calendar days
    target = snap_date + timedelta(days=int(horizon * 7 / 5))
    p1 = _find_price(ticker, target)
    if p1 is None:
        return None
    if p0 <= 0:
        return None
    return (p1 - p0) / p0


def _find_price(ticker: str, target: date) -> Optional[float]:
    """Find price for ticker near target date (±3 calendar days)."""
    for offset in range(4):
        for sign in (0, 1, -1):
            d = target + timedelta(days=offset * sign)
            key = (ticker, d.isoformat())
            if key in _PRICE_CACHE:
                return _PRICE_CACHE[key]
    return None


# ---------------------------------------------------------------------------
# Archive extraction (enriched version — includes quality inputs)
# ---------------------------------------------------------------------------

# Columns to extract from archives for clinical quality recomputation
_ARCHIVE_COLS = [
    "ticker",
    "catalyst_event_type",
    "catalyst_days",
    "catalyst_mode",
    "catalyst_source",
    "composite_score",
    "optionality_pct",
    "design_quality_score",
    "lead_program_phase",
    "endpoint_strength_score",
    "program_count",
    "single_asset_risk",
    "catalyst_corroborated",
    "clinical_score_v2",
    "clinical_score_v2_z",
]


def extract_enriched_events(
    archive_dir: Path,
    families: set,
    buckets: set,
    min_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Extract catalyst events with clinical quality inputs from archives."""
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
                    # Older archives lack catalyst_event_type — skip them
                    if not event_type:
                        continue

                    family = classify_family(event_type)
                    if family not in families:
                        continue

                    days = panel_safe_float(row.get("catalyst_days"))
                    mode = row.get("catalyst_mode", "")
                    bucket = assign_bucket(days, mode)
                    if bucket not in buckets:
                        continue

                    ev = {
                        "snapshot_date": snap_date_str,
                        "catalyst_family": family,
                        "catalyst_bucket": bucket,
                    }
                    for col in _ARCHIVE_COLS:
                        ev[col] = row.get(col, "")

                    events.append(ev)
        except Exception as exc:
            logger.warning("Error reading %s: %s", arch.name, exc)
            continue

    logger.info("Extracted %d enriched catalyst events", len(events))
    return events


# ---------------------------------------------------------------------------
# Compute clinical quality composite from archive inputs
# ---------------------------------------------------------------------------


def enrich_clinical_quality(events: List[Dict[str, Any]]) -> None:
    """Add clinical_quality_composite to each event (in-place)."""
    computed = 0
    for ev in events:
        if ev["catalyst_family"] != "CLINICAL":
            ev["clinical_quality_composite"] = ""
            continue
        quality = compute_clinical_91_180_quality(ev)
        ev["clinical_quality_composite"] = quality.get("clinical_quality_composite", "")
        if ev["clinical_quality_composite"] != "":
            computed += 1
    logger.info("Computed clinical_quality_composite for %d/%d CLINICAL events", computed, len(events))


# ---------------------------------------------------------------------------
# Join with options panel
# ---------------------------------------------------------------------------


def join_options_features(
    events: List[Dict[str, Any]],
    panel_path: Path,
) -> List[Dict[str, Any]]:
    """Join enriched events with pre-computed options features from panel CSV."""
    # Load panel into lookup: (ticker, snapshot_date) → features
    panel_index: Dict[Tuple[str, str], Dict[str, Any]] = {}
    with open(panel_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row["ticker"], row["snapshot_date"])
            panel_index[key] = {col: row.get(col, "") for col in FEATURE_COLUMNS}

    joined = 0
    for ev in events:
        key = (ev["ticker"], ev["snapshot_date"])
        if key in panel_index:
            ev.update(panel_index[key])
            joined += 1
        else:
            for col in FEATURE_COLUMNS:
                ev[col] = ""

    logger.info("Joined %d/%d events with options features", joined, len(events))
    return events


# ---------------------------------------------------------------------------
# Forward returns
# ---------------------------------------------------------------------------


def attach_forward_returns(
    events: List[Dict[str, Any]],
    horizons: List[int],
    price_path: Path,
) -> None:
    """Attach forward returns for each horizon (in-place)."""
    _load_price_history(price_path)
    for ev in events:
        snap = date.fromisoformat(ev["snapshot_date"])
        for h in horizons:
            ret = _forward_return(ev["ticker"], snap, h)
            ev[f"fwd_ret_{h}d"] = ret


# ---------------------------------------------------------------------------
# IC analysis
# ---------------------------------------------------------------------------


def spearman_ic(x: List[float], y: List[float]) -> Tuple[float, int]:
    """Spearman rank correlation. Returns (rho, n)."""
    if len(x) < 5:
        return (float("nan"), len(x))
    from scipy.stats import spearmanr

    rho, _ = spearmanr(x, y)
    return (rho, len(x))


def partial_rank_correlation(x: List[float], y: List[float], z: List[float]) -> Tuple[float, int]:
    """Partial Spearman correlation of x and y, controlling for z.

    Residualizes x and y on z via OLS on ranks, then correlates residuals.
    """
    n = len(x)
    if n < 10:
        return (float("nan"), n)

    from scipy.stats import rankdata, spearmanr

    rx = rankdata(x)
    ry = rankdata(y)
    rz = rankdata(z)

    # Residualize x ranks on z ranks
    rz_mean = np.mean(rz)
    rz_var = np.sum((rz - rz_mean) ** 2)
    if rz_var == 0:
        # z is constant — partial = marginal
        return spearman_ic(x, y)

    beta_xz = np.sum((rx - np.mean(rx)) * (rz - rz_mean)) / rz_var
    beta_yz = np.sum((ry - np.mean(ry)) * (rz - rz_mean)) / rz_var

    resid_x = rx - beta_xz * rz
    resid_y = ry - beta_yz * rz

    rho, _ = spearmanr(resid_x, resid_y)
    return (rho, n)


def run_ic_analysis(
    events: List[Dict[str, Any]],
    horizons: List[int],
    features: List[str],
) -> Dict[str, Any]:
    """Run full IC analysis with splits.

    Returns structured results dict.
    """
    results: Dict[str, Any] = {
        "overall": {},
        "by_bucket": {},
        "by_event_type": {},
        "by_family": {},
        "by_snapshot": {},
        "partial_ic": {},  # after controlling for clinical_quality_composite
    }

    # Filter to rows with options data and forward returns
    for horizon in horizons:
        h_key = f"fwd_ret_{horizon}d"

        # --- Overall IC ---
        for feat in features:
            pairs = [(float(ev[feat]), ev[h_key]) for ev in events if ev.get(feat, "") != "" and ev[h_key] is not None]
            if pairs:
                x, y = zip(*pairs)
                rho, n = spearman_ic(list(x), list(y))
                results["overall"][(feat, horizon)] = (rho, n)

        # --- By bucket ---
        bucket_groups = defaultdict(list)
        for ev in events:
            bucket_groups[ev["catalyst_bucket"]].append(ev)

        for bkt, bkt_events in sorted(bucket_groups.items()):
            for feat in features:
                pairs = [
                    (float(ev[feat]), ev[h_key])
                    for ev in bkt_events
                    if ev.get(feat, "") != "" and ev[h_key] is not None
                ]
                if pairs:
                    x, y = zip(*pairs)
                    rho, n = spearman_ic(list(x), list(y))
                    results["by_bucket"][(bkt, feat, horizon)] = (rho, n)

        # --- By event_type ---
        etype_groups = defaultdict(list)
        for ev in events:
            etype_groups[ev["catalyst_event_type"]].append(ev)

        for etype, et_events in sorted(etype_groups.items()):
            for feat in features:
                pairs = [
                    (float(ev[feat]), ev[h_key]) for ev in et_events if ev.get(feat, "") != "" and ev[h_key] is not None
                ]
                if len(pairs) >= 10:  # min sample for event type splits
                    x, y = zip(*pairs)
                    rho, n = spearman_ic(list(x), list(y))
                    results["by_event_type"][(etype, feat, horizon)] = (rho, n)

        # --- By family ---
        fam_groups = defaultdict(list)
        for ev in events:
            fam_groups[ev["catalyst_family"]].append(ev)

        for fam, fam_events in sorted(fam_groups.items()):
            for feat in features:
                pairs = [
                    (float(ev[feat]), ev[h_key])
                    for ev in fam_events
                    if ev.get(feat, "") != "" and ev[h_key] is not None
                ]
                if pairs:
                    x, y = zip(*pairs)
                    rho, n = spearman_ic(list(x), list(y))
                    results["by_family"][(fam, feat, horizon)] = (rho, n)

        # --- By snapshot date (temporal stability) ---
        snap_groups = defaultdict(list)
        for ev in events:
            snap_groups[ev["snapshot_date"]].append(ev)

        for snap, snap_events in sorted(snap_groups.items()):
            for feat in features:
                pairs = [
                    (float(ev[feat]), ev[h_key])
                    for ev in snap_events
                    if ev.get(feat, "") != "" and ev[h_key] is not None
                ]
                if len(pairs) >= 10:
                    x, y = zip(*pairs)
                    rho, n = spearman_ic(list(x), list(y))
                    results["by_snapshot"][(snap, feat, horizon)] = (rho, n)

        # --- Partial IC (controlling for clinical_quality_composite) ---
        for feat in features:
            triples = [
                (float(ev[feat]), ev[h_key], float(ev["clinical_quality_composite"]))
                for ev in events
                if ev.get(feat, "") != "" and ev[h_key] is not None and ev.get("clinical_quality_composite", "") != ""
            ]
            if len(triples) >= 10:
                x, y, z = zip(*triples)
                rho, n = partial_rank_correlation(list(x), list(y), list(z))
                results["partial_ic"][(feat, horizon)] = (rho, n)

    return results


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def format_report(
    results: Dict[str, Any],
    horizons: List[int],
    features: List[str],
    event_dist: Counter,
) -> str:
    """Format IC analysis results into readable report."""
    lines = []
    lines.append("=" * 80)
    lines.append("CROWDING PENALTY ORTHOGONALITY ANALYSIS")
    lines.append("=" * 80)
    lines.append("")

    # Distribution
    lines.append("Event distribution:")
    for (fam, bkt), cnt in sorted(event_dist.items()):
        lines.append(f"  {fam:12s} / {bkt:14s}: {cnt:4d}")
    lines.append("")

    # Overall IC
    lines.append("-" * 80)
    lines.append("1. OVERALL IC (Spearman rho vs forward returns)")
    lines.append("-" * 80)
    header = f"{'Feature':<35s}"
    for h in horizons:
        header += f"  {h:>3d}d rho (n)"
    lines.append(header)

    for feat in features:
        row_str = f"  {feat:<33s}"
        for h in horizons:
            key = (feat, h)
            if key in results["overall"]:
                rho, n = results["overall"][key]
                row_str += f"  {rho:>+6.3f} ({n:>3d})"
            else:
                row_str += f"  {'n/a':>12s}"
        lines.append(row_str)
    lines.append("")

    # By bucket
    lines.append("-" * 80)
    lines.append("2. IC BY CATALYST BUCKET")
    lines.append("-" * 80)
    buckets_seen = sorted(set(k[0] for k in results["by_bucket"]))
    for bkt in buckets_seen:
        lines.append(f"\n  [{bkt}]")
        for feat in features:
            row_str = f"    {feat:<31s}"
            for h in horizons:
                key = (bkt, feat, h)
                if key in results["by_bucket"]:
                    rho, n = results["by_bucket"][key]
                    row_str += f"  {rho:>+6.3f} ({n:>3d})"
                else:
                    row_str += f"  {'n/a':>12s}"
            lines.append(row_str)
    lines.append("")

    # By event type (only show types with n >= 10)
    lines.append("-" * 80)
    lines.append("3. IC BY CATALYST EVENT TYPE (n >= 10)")
    lines.append("-" * 80)
    etypes_seen = sorted(set(k[0] for k in results["by_event_type"]))
    for etype in etypes_seen:
        lines.append(f"\n  [{etype}]")
        for feat in ["pre_event_volume_mean", "chain_breadth", "pre_event_transactions_mean"]:
            if feat not in features:
                continue
            row_str = f"    {feat:<31s}"
            for h in horizons:
                key = (etype, feat, h)
                if key in results["by_event_type"]:
                    rho, n = results["by_event_type"][key]
                    row_str += f"  {rho:>+6.3f} ({n:>3d})"
                else:
                    row_str += f"  {'n/a':>12s}"
            lines.append(row_str)
    lines.append("")

    # By family
    lines.append("-" * 80)
    lines.append("4. IC BY CATALYST FAMILY")
    lines.append("-" * 80)
    for fam in sorted(set(k[0] for k in results["by_family"])):
        lines.append(f"\n  [{fam}]")
        for feat in features:
            row_str = f"    {feat:<31s}"
            for h in horizons:
                key = (fam, feat, h)
                if key in results["by_family"]:
                    rho, n = results["by_family"][key]
                    row_str += f"  {rho:>+6.3f} ({n:>3d})"
                else:
                    row_str += f"  {'n/a':>12s}"
            lines.append(row_str)
    lines.append("")

    # Temporal stability
    lines.append("-" * 80)
    lines.append("5. TEMPORAL STABILITY (per-snapshot IC for volume_mean)")
    lines.append("-" * 80)
    feat_check = "pre_event_volume_mean"
    header = f"  {'Snapshot':<14s}"
    for h in horizons:
        header += f"  {h:>3d}d rho (n)"
    lines.append(header)

    snaps = sorted(set(k[0] for k in results["by_snapshot"] if k[1] == feat_check))
    for snap in snaps:
        row_str = f"  {snap:<14s}"
        for h in horizons:
            key = (snap, feat_check, h)
            if key in results["by_snapshot"]:
                rho, n = results["by_snapshot"][key]
                row_str += f"  {rho:>+6.3f} ({n:>3d})"
            else:
                row_str += f"  {'n/a':>12s}"
        lines.append(row_str)

    # Temporal sign consistency
    for h in horizons:
        snap_rhos = []
        for snap in snaps:
            key = (snap, feat_check, h)
            if key in results["by_snapshot"]:
                rho, n = results["by_snapshot"][key]
                if not np.isnan(rho):
                    snap_rhos.append(rho)
        if snap_rhos:
            neg_frac = sum(1 for r in snap_rhos if r < 0) / len(snap_rhos)
            mean_rho = np.mean(snap_rhos)
            lines.append(
                f"\n  {h}d: {len(snap_rhos)} snapshots, mean rho = {mean_rho:+.3f}, "
                f"negative in {neg_frac:.0%} of snapshots"
            )
    lines.append("")

    # Partial IC
    lines.append("-" * 80)
    lines.append("6. PARTIAL IC (controlling for clinical_quality_composite)")
    lines.append("   Tests orthogonality: does crowding add info beyond clinical quality?")
    lines.append("-" * 80)
    header = f"  {'Feature':<33s}"
    for h in horizons:
        header += f"  {h:>3d}d partial (n)  marginal"
    lines.append(header)

    for feat in features:
        row_str = f"  {feat:<33s}"
        for h in horizons:
            p_key = (feat, h)
            o_key = (feat, h)
            partial_str = "n/a"
            marginal_str = ""
            if p_key in results["partial_ic"]:
                rho_p, n_p = results["partial_ic"][p_key]
                partial_str = f"{rho_p:>+6.3f} ({n_p:>3d})"
            if o_key in results["overall"]:
                rho_o, _ = results["overall"][o_key]
                marginal_str = f"  {rho_o:>+6.3f}"
            row_str += f"  {partial_str}{marginal_str}"
        lines.append(row_str)
    lines.append("")

    lines.append("=" * 80)
    lines.append("INTERPRETATION GUIDE:")
    lines.append("  - Negative marginal IC: crowding signal confirms prior finding")
    lines.append("  - Negative partial IC ≈ marginal: signal is ORTHOGONAL to clinical quality")
    lines.append("  - Partial IC → 0 when marginal is negative: crowding is a PROXY for quality")
    lines.append("  - Stable sign across snapshots: signal is robust, not data-mined")
    lines.append("=" * 80)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Crowding penalty orthogonality analysis")
    parser.add_argument("--archive-dir", type=Path, default=REPO_ROOT / "data" / "archives")
    parser.add_argument(
        "--panel", type=Path, default=REPO_ROOT / "data" / "research" / "precatalyst_options_panel_clinical.csv"
    )
    parser.add_argument("--price-history", type=Path, default=REPO_ROOT / "production_data" / "price_history.csv")
    parser.add_argument("--horizons", default="5,20", help="Forward-return horizons (trading days)")
    parser.add_argument("--families", default="CLINICAL", help="Catalyst families")
    parser.add_argument("--buckets", default="binary_now,build_window,less_binary", help="Catalyst buckets")
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "data" / "research" / "crowding_orthogonality_report.txt"
    )
    parser.add_argument(
        "--out-csv", type=Path, default=REPO_ROOT / "data" / "research" / "crowding_orthogonality_panel.csv"
    )
    args = parser.parse_args()

    horizons = [int(h) for h in args.horizons.split(",")]
    families = set(args.families.split(","))
    buckets = set(args.buckets.split(","))

    # Step 1: Extract enriched events
    events = extract_enriched_events(args.archive_dir, families, buckets)

    # Deduplicate
    seen = set()
    deduped = []
    for ev in events:
        key = (ev["ticker"], ev["snapshot_date"])
        if key not in seen:
            seen.add(key)
            deduped.append(ev)
    events = deduped
    logger.info("After dedup: %d unique ticker-date pairs", len(events))

    # Step 2: Compute clinical_quality_composite
    enrich_clinical_quality(events)

    # Step 3: Join with options features
    events = join_options_features(events, args.panel)

    # Step 4: Attach forward returns
    attach_forward_returns(events, horizons, args.price_history)

    # Report coverage
    with_opts = sum(1 for ev in events if ev.get("pre_event_volume_mean", "") != "")
    with_rets = {h: sum(1 for ev in events if ev.get(f"fwd_ret_{h}d") is not None) for h in horizons}
    with_quality = sum(1 for ev in events if ev.get("clinical_quality_composite", "") != "")
    logger.info("Coverage: %d events, %d with options, %d with clinical quality", len(events), with_opts, with_quality)
    for h, n in with_rets.items():
        logger.info("  %dd forward returns: %d", h, n)

    # Distribution
    event_dist = Counter((ev["catalyst_family"], ev["catalyst_bucket"]) for ev in events)

    # Step 5: Run IC analysis
    features_to_test = [
        "pre_event_volume_mean",
        "chain_breadth",
        "pre_event_transactions_mean",
        "pre_event_contract_count_mean",
        "pre_event_put_call_ratio",
        "pre_event_volume_surge",
        "pre_event_volume_trend",
    ]
    results = run_ic_analysis(events, horizons, features_to_test)

    # Format and write report
    report = format_report(results, horizons, features_to_test, event_dist)
    print(report)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        f.write(report)
    logger.info("Report written to %s", args.out)

    # Write enriched panel CSV
    out_cols = [
        "ticker",
        "snapshot_date",
        "catalyst_event_type",
        "catalyst_family",
        "catalyst_bucket",
        "catalyst_days",
        "catalyst_mode",
        "catalyst_source",
        "composite_score",
        "clinical_quality_composite",
        *FEATURE_COLUMNS,
        *[f"fwd_ret_{h}d" for h in horizons],
    ]
    with open(args.out_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=out_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(events)
    logger.info("Enriched panel written to %s (%d rows)", args.out_csv, len(events))

    return 0


if __name__ == "__main__":
    sys.exit(main())

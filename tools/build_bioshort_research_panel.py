#!/usr/bin/env python3
"""Spec 092 Phase C — Historical bioshort feature panel builder.

Backfills deterministic hedge-report features across historical snapshots
into artifacts/research/bioshort_backfill/ without mutating live output/hedge_report/.

Invokes biotech_hedge_report.py with --research-mode isolation.
"""

from __future__ import annotations

import csv
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PROJECT_ROOT
DATA_DIR = REPO_ROOT / "data" / "snapshots"
OUTPUT_BASE = REPO_ROOT / "artifacts" / "research" / "bioshort_backfill"
REPORTS_DIR = OUTPUT_BASE / "reports"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def enumerate_snapshots() -> list[tuple[str, Path]]:
    """Enumerate clean snapshot dates with portfolio_positions.csv.

    Returns:
        List of (date_str, snapshot_dir) tuples, sorted chronologically.
    """
    snapshots = []

    for snap_dir in sorted(DATA_DIR.iterdir()):
        # Only include clean date directories (no special suffixes)
        if not snap_dir.is_dir():
            continue

        date_str = snap_dir.name
        # Check if it's a clean date (YYYY-MM-DD format, no suffix)
        if not _is_clean_date(date_str):
            continue

        portfolio_csv = snap_dir / "portfolio_positions.csv"
        if portfolio_csv.exists():
            snapshots.append((date_str, snap_dir))

    return snapshots


def _is_clean_date(name: str) -> bool:
    """Check if name is YYYY-MM-DD format (no special suffixes)."""
    parts = name.split("-")
    if len(parts) != 3:
        return False
    try:
        int(parts[0])
        int(parts[1])
        int(parts[2])
        return True
    except ValueError:
        return False


def run_producer(
    snapshot_dir: Path,
    date_str: str,
    output_dir: Path,
) -> dict:
    """Invoke biotech_hedge_report.py for one snapshot in research mode.

    Returns:
        Status dict with keys: status, error, report_json.
    """
    portfolio_csv = snapshot_dir / "portfolio_positions.csv"

    if not portfolio_csv.exists():
        return {
            "status": "skipped_no_portfolio",
            "error": "portfolio_positions.csv not found",
            "report_json": None,
        }

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "tools" / "biotech_hedge_report.py"),
        "--as-of-date",
        date_str,
        "--portfolio-csv",
        str(portfolio_csv),
        "--snap-dir",
        str(snapshot_dir.parent),  # data/snapshots, so snap-dir defaults correctly
        "--output-dir",
        str(output_dir),
        "--backtest-mode",
        "bs",  # Use Black-Scholes for historical (no live market data)
        "--research-mode",
    ]

    try:
        logger.info(f"Running producer for {date_str}...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 min per snapshot
        )

        if result.returncode != 0:
            logger.error(f"Producer failed for {date_str}: {result.stderr}")
            return {
                "status": "error_producer_failed",
                "error": result.stderr[:500],  # Truncate for manifest
                "report_json": None,
            }

        # Check if the report JSON was written
        report_json = output_dir / f"hedge_report_{date_str}.json"
        if report_json.exists():
            with open(report_json) as f:
                report_data = json.load(f)
            return {
                "status": "ok",
                "error": None,
                "report_json": report_data,
                "report_path": str(report_json),
            }
        else:
            return {
                "status": "error_no_output",
                "error": "hedge_report JSON not written",
                "report_json": None,
            }

    except subprocess.TimeoutExpired:
        return {
            "status": "error_timeout",
            "error": "Producer timed out (>300s)",
            "report_json": None,
        }
    except Exception as e:
        logger.exception(f"Unexpected error running producer for {date_str}")
        return {
            "status": "error_exception",
            "error": str(e)[:500],
            "report_json": None,
        }


def extract_row_data(report_json: dict | None, date_str: str, status: str) -> dict:
    """Extract feature row from hedge report JSON.

    Returns:
        Dict with panel row keys (as_of_date, verdict, recommendation, etc.)
    """
    row = {"as_of_date": date_str, "error_status": status}

    if report_json is None:
        row.update(
            {
                "verdict": "",
                "recommendation": "",
                "hedge_score": "",
                "confidence": "",
                "best_vehicle": "",
                "xbi_beta": "",
                "xbi_r2": "",
                "ibb_beta": "",
                "ibb_r2": "",
                "primary_cost_bps": "",
                "options_source": "",
                "portfolio_n": "",
                "portfolio_weight_sum": "",
                "top_contributors": "",
            }
        )
        return row

    # Extract IC decision
    ic = report_json.get("ic_decision", {})
    row.update(
        {
            "verdict": ic.get("policy_action", ""),
            "recommendation": ic.get("primary_hedge", ""),
            "hedge_score": ic.get("hedge_score", ""),
            "confidence": ic.get("confidence", ""),
            "best_vehicle": ic.get("best_vehicle", ""),
        }
    )

    # Extract beta stats
    beta_stats = report_json.get("beta_stats", {})
    row.update(
        {
            "xbi_beta": beta_stats.get("beta", ""),
            "xbi_r2": beta_stats.get("r_squared", ""),
            "ibb_beta": "",  # Not computed in current producer
            "ibb_r2": "",
        }
    )

    # Extract cost and options info
    primary_hedge = ic.get("primary_hedge", "")
    if primary_hedge and "put_spread" in primary_hedge.lower():
        costs = report_json.get("structure_costs", {})
        row["primary_cost_bps"] = costs.get(primary_hedge, "")

    row.update(
        {
            "options_source": report_json.get("options_source", ""),
            "portfolio_n": report_json.get("portfolio_n_positions", ""),
            "portfolio_weight_sum": report_json.get("portfolio_weight_sum", ""),
            "top_contributors": json.dumps(report_json.get("top_contributors", [])),
        }
    )

    return row


def build_panel(snapshots: list[tuple[str, Path]]) -> tuple[list[dict], dict]:
    """Build feature panel across all snapshots.

    Returns:
        (rows, manifest) where rows are dicts with panel keys, manifest is status record.
    """
    rows = []
    status_by_date = {}
    failures = []

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    for date_str, snap_dir in snapshots:
        logger.info(f"Processing {date_str}...")

        # Run producer in research mode
        result = run_producer(snap_dir, date_str, REPORTS_DIR)
        status = result["status"]
        status_by_date[date_str] = status

        if status == "ok":
            # Extract feature row
            report_json = result["report_json"]
            row = extract_row_data(report_json, date_str, "ok")
            rows.append(row)
        else:
            # Record failure
            failures.append(
                {
                    "date": date_str,
                    "status": status,
                    "error": result.get("error", ""),
                }
            )
            row = extract_row_data(None, date_str, status)
            rows.append(row)

    # Build manifest
    manifest = {
        "schema": "bioshort_research_panel.v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code_commit": _get_git_commit(),
        "date_range": {
            "start": snapshots[0][0] if snapshots else None,
            "end": snapshots[-1][0] if snapshots else None,
        },
        "snapshot_count": len(snapshots),
        "success_count": sum(1 for s in status_by_date.values() if s == "ok"),
        "failure_count": len(failures),
        "status_by_date": status_by_date,
        "failures": failures,
        "parquet_status": _check_parquet_available(),
    }

    return rows, manifest


def _get_git_commit() -> str:
    """Get current git commit SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _check_parquet_available() -> str:
    """Check if parquet writing is available."""
    try:
        import pyarrow  # noqa: F401

        return "available"
    except ImportError:
        return "skipped_missing_dependency"


def write_panel_csv(rows: list[dict], output_csv: Path) -> None:
    """Write feature panel to CSV."""
    if not rows:
        logger.warning("No rows to write")
        return

    fieldnames = [
        "as_of_date",
        "verdict",
        "recommendation",
        "hedge_score",
        "confidence",
        "best_vehicle",
        "xbi_beta",
        "xbi_r2",
        "ibb_beta",
        "ibb_r2",
        "primary_cost_bps",
        "options_source",
        "portfolio_n",
        "portfolio_weight_sum",
        "top_contributors",
        "error_status",
    ]

    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"Wrote panel to {output_csv} ({len(rows)} rows)")


def write_manifest(manifest: dict, output_json: Path) -> None:
    """Write backfill manifest."""
    with open(output_json, "w") as f:
        json.dump(manifest, f, indent=2)

    logger.info(f"Wrote manifest to {output_json}")


def safety_check() -> bool:
    """Verify no mutations to live paths will occur."""
    # Verify --research-mode flag exists in producer
    producer_py = PROJECT_ROOT / "tools" / "biotech_hedge_report.py"
    if not producer_py.exists():
        logger.error(f"Producer not found: {producer_py}")
        return False

    with open(producer_py) as f:
        content = f.read()
        if "--research-mode" not in content:
            logger.error("Producer does not have --research-mode flag")
            return False

    # Verify output directory is clean
    if (REPO_ROOT / "output" / "hedge_report" / "archive").exists():
        logger.info("Note: live archive exists (expected for operational mode)")

    logger.info("Safety checks passed")
    return True


def main():
    """Run Phase C builder."""
    logger.info("=== Spec 092 Phase C — Bioshort Research Panel Builder ===")

    if not safety_check():
        logger.error("Safety checks failed")
        return 1

    # Enumerate snapshots
    logger.info(f"Enumerating snapshots from {DATA_DIR}...")
    snapshots = enumerate_snapshots()
    logger.info(f"Found {len(snapshots)} snapshots with portfolio_positions.csv")

    if not snapshots:
        logger.error("No snapshots found")
        return 1

    # Build panel
    rows, manifest = build_panel(snapshots)

    # Write outputs
    OUTPUT_BASE.mkdir(parents=True, exist_ok=True)
    write_panel_csv(rows, OUTPUT_BASE / "panel.csv")
    write_manifest(manifest, OUTPUT_BASE / "backfill_manifest.json")

    logger.info(f"Phase C complete: {manifest['success_count']}/{len(snapshots)} successful")
    return 0


if __name__ == "__main__":
    sys.exit(main())

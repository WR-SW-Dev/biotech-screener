#!/usr/bin/env python3
"""
Phase 2 Forward Paper Test Manual Runner

Paper-only simulation tracking 5 portfolio policies forward from the latest
approved production snapshot (canonical: data/snapshots/YYYY-MM-DD/rankings.csv).
Manual/on-demand execution only.

Boundaries:
- Read-only price data
- No live trading
- No production integration
- No cron scheduling
- Paper-only artifacts

Usage:
  python scripts/run_phase2_forward_paper_test.py \\
    --snapshot-date <YYYYMMDD> \\
    --test-length 1 \\
    --output-dir artifacts/portfolio_policy_forward_test/ \\
    --paper-only
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)


def get_latest_snapshot():
    """Find the latest approved production snapshot from canonical source."""
    snap_dir = Path("data/snapshots")
    if not snap_dir.exists():
        logger.error(f"Canonical snapshots directory not found: {snap_dir}")
        return None

    # Find date-based snapshot directories (YYYY-MM-DD format)
    snap_dates = sorted([d for d in snap_dir.iterdir() if d.is_dir() and len(d.name) == 10])
    if not snap_dates:
        logger.error("No snapshots found in data/snapshots/ (expected YYYY-MM-DD directories)")
        return None

    latest_dir = snap_dates[-1]
    rankings_file = latest_dir / "rankings.csv"

    if not rankings_file.exists():
        logger.error(f"Rankings not found in latest snapshot: {latest_dir}")
        return None

    logger.info(f"Latest snapshot: {latest_dir.name} (canonical source)")
    return latest_dir


def load_snapshot(snapshot_dir):
    """Load a snapshot and extract holdings from canonical rankings.csv."""
    try:
        import csv

        snapshot_dir = Path(snapshot_dir)
        date_str = snapshot_dir.name

        rankings_file = snapshot_dir / "rankings.csv"
        if not rankings_file.exists():
            logger.error(f"Rankings not found: {rankings_file}")
            return None

        # Read top-30 from rankings.csv (sorted by final_score)
        holdings = []
        with open(rankings_file) as f:
            reader = csv.DictReader(f)
            for row in reader:
                holdings.append(
                    {
                        "ticker": row.get("ticker", ""),
                        "company_name": row.get("company_name", ""),
                        "actionable_rank": row.get("actionable_rank", ""),
                        "final_score": row.get("final_score", ""),
                        "composite_score": row.get("composite_score", ""),
                    }
                )
                if len(holdings) >= 30:
                    break

        logger.info(f"Loaded snapshot from {date_str}: {len(holdings)} holdings")

        return {"date": date_str, "holdings": holdings, "data": {"date": date_str, "source": "data/snapshots/"}}
    except Exception as e:
        logger.error(f"Failed to load snapshot {snapshot_dir}: {e}")
        return None


def simulate_policies(snapshot_date, holdings, test_length_days=1):
    """
    Simulate 5 policies forward from snapshot date.

    Returns daily artifact structure (paper-only).
    """
    policies = {
        "current_advisory": {
            "description": "Current portfolio (advisory behavior)",
            "rebalance_days": [],
            "turnover": 0.0,
        },
        "weekly_trade_packet_proxy": {
            "description": "Hypothetical weekly rebalance",
            "rebalance_days": 7,
            "turnover": 0.963,
        },
        "quarterly_rebalance_proxy": {
            "description": "Hypothetical quarterly rebalance",
            "rebalance_days": 63,
            "turnover": 0.857,
        },
        "static_inception_hold": {
            "description": "Buy and hold from inception",
            "rebalance_days": None,
            "turnover": 0.0,
        },
        "delisting_liquidity_only": {
            "description": "Rebalance only on delisting/liquidity events",
            "rebalance_days": [],
            "turnover": 0.0,
        },
    }

    # Paper-only stub: return structure without live execution
    # Use all 30 canonical decision-portfolio holdings (governance-approved)
    artifacts = {
        "snapshot_date": snapshot_date,
        "test_date": datetime.now().isoformat(),
        "test_length_days": test_length_days,
        "paper_only": True,
        "policies": policies,
        "holdings_snapshot": holdings,  # All 30 holdings from canonical decision portfolio
        "message": "Paper-only. No live trading. No production changes.",
    }

    return artifacts


def write_artifacts(output_dir, snapshot_date, artifacts):
    """Write paper-only artifacts to disk."""
    output_path = Path(output_dir) / snapshot_date
    output_path.mkdir(parents=True, exist_ok=True)

    # Holdings snapshot
    holdings_file = output_path / "holdings.json"
    with open(holdings_file, "w") as f:
        json.dump(
            {
                "snapshot_date": snapshot_date,
                "paper_only": True,
                "holdings_count": len(artifacts.get("holdings_snapshot", [])),
                "holdings": artifacts.get("holdings_snapshot", []),
            },
            f,
            indent=2,
        )
    logger.info(f"✓ {holdings_file}")

    # Performance stub
    performance_file = output_path / "performance.json"
    with open(performance_file, "w") as f:
        json.dump(
            {
                "snapshot_date": snapshot_date,
                "paper_only": True,
                "message": "Performance tracking not yet implemented (placeholder)",
            },
            f,
            indent=2,
        )
    logger.info(f"✓ {performance_file}")

    # Staleness stub
    staleness_file = output_path / "staleness.json"
    with open(staleness_file, "w") as f:
        json.dump(
            {
                "snapshot_date": snapshot_date,
                "paper_only": True,
                "message": "Data quality metrics not yet implemented (placeholder)",
            },
            f,
            indent=2,
        )
    logger.info(f"✓ {staleness_file}")

    # Turnover stub
    turnover_file = output_path / "turnover.json"
    with open(turnover_file, "w") as f:
        json.dump(
            {
                "snapshot_date": snapshot_date,
                "paper_only": True,
                "policies": artifacts.get("policies", {}),
            },
            f,
            indent=2,
        )
    logger.info(f"✓ {turnover_file}")

    # Attribution stub
    attribution_file = output_path / "attribution.json"
    with open(attribution_file, "w") as f:
        json.dump(
            {
                "snapshot_date": snapshot_date,
                "paper_only": True,
                "message": "Attribution analysis not yet implemented (placeholder)",
            },
            f,
            indent=2,
        )
    logger.info(f"✓ {attribution_file}")

    return output_path


def main():
    parser = argparse.ArgumentParser(description="Phase 2 forward paper test manual runner (paper-only, no cron)")
    parser.add_argument("--snapshot-date", default=None, help="Snapshot date (YYYYMMDD). If not provided, uses latest.")
    parser.add_argument("--test-length", type=int, default=1, help="Test length in days (default: 1 for dry-run)")
    parser.add_argument(
        "--output-dir", default="artifacts/portfolio_policy_forward_test/", help="Output directory for artifacts"
    )
    parser.add_argument("--paper-only", action="store_true", help="Confirm paper-only execution (required)")

    args = parser.parse_args()

    if not args.paper_only:
        logger.error("CRITICAL: --paper-only flag required. No live trading authorized.")
        sys.exit(1)

    logger.info("=== Phase 2 Forward Paper Test Manual Runner ===")
    logger.info("Paper-only. No live trading. No production integration.")

    # Load snapshot from canonical source
    if args.snapshot_date:
        snapshot_dir = Path(f"data/snapshots/{args.snapshot_date}")
    else:
        snapshot_dir = get_latest_snapshot()

    if not snapshot_dir or not snapshot_dir.exists():
        logger.error(f"Snapshot not found: {snapshot_dir} (expected canonical: data/snapshots/YYYY-MM-DD/)")
        sys.exit(1)

    snapshot = load_snapshot(snapshot_dir)
    if not snapshot:
        sys.exit(1)

    # Simulate policies
    logger.info(f"Simulating {args.test_length} day(s) forward...")
    artifacts = simulate_policies(snapshot["date"], snapshot["holdings"], test_length_days=args.test_length)

    # Write artifacts
    logger.info(f"Writing artifacts to {args.output_dir}...")
    output_path = write_artifacts(args.output_dir, snapshot["date"], artifacts)

    logger.info("")
    logger.info("=== Dry-Run Complete ===")
    logger.info(f"Snapshot date: {snapshot['date']}")
    logger.info(f"Output: {output_path}")
    logger.info(f"Artifacts: {list(output_path.glob('*.json'))}")
    logger.info("")
    logger.info("✓ Paper-only. No production changes.")
    logger.info("✓ No cron scheduled.")
    logger.info("✓ Manual execution only.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Weekly Execution Runner — one-command, safe-by-default execution pipeline.

Orchestrates:
  1. Verify snapshot exists (via run_daily_production.py if missing)
  2. Build shadow positions (live_shadow_portfolio.py)
  3. Run pre_trade_check
  4. If can_trade=false → EXECUTION_PACKET with status=BLOCKED, exit 2
  5. If can_trade=true → build trade plan + broker orders → status=READY, exit 0

Outputs:
    artifacts/live_shadow/execution/{YYYY-MM-DD}/EXECUTION_PACKET.json
    artifacts/live_shadow/execution/{YYYY-MM-DD}/EXECUTION_PACKET.md
    artifacts/live_shadow/execution/{YYYY-MM-DD}/trade_plan.csv      (if READY)
    artifacts/live_shadow/execution/{YYYY-MM-DD}/broker_orders.csv   (if READY)
    artifacts/live_shadow/execution/{YYYY-MM-DD}/pre_trade.json
    artifacts/live_shadow/execution/{YYYY-MM-DD}/pre_trade.md

Usage:
    python3 tools/run_weekly_execution.py --as-of-date 2026-03-10
    python3 tools/run_weekly_execution.py --as-of-date 2026-03-10 --dry-run
    python3 tools/run_weekly_execution.py --as-of-date 2026-03-10 --skip-snapshot
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_trade_deltas import POSITIONS_DIR
from tools.live_shadow_portfolio import (
    PERFORMANCE_CSV,
    SHADOW_ROOT,
    SNAPSHOTS_ROOT,
    append_performance,
    build_positions,
    compute_performance,
    load_metadata,
    load_policy,
    load_rankings,
    save_positions,
)

EXECUTION_ROOT = SHADOW_ROOT / "execution"
DAILY_PRODUCTION_SCRIPT = PROJECT_ROOT / "tools" / "run_daily_production.py"

SCHEMA_VERSION = "execution_packet.v1"

# ---------------------------------------------------------------------------
# Production-path guards (same pattern as pre_trade_check.py)
# ---------------------------------------------------------------------------

_PRODUCTION_PATHS = {
    "positions_dir": POSITIONS_DIR,
    "execution_root": EXECUTION_ROOT,
    "snap_root": SNAPSHOTS_ROOT,
}


def _in_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ


def _assert_not_production_default(name: str, value: Path, production_default: Path) -> None:
    if _in_pytest() and value == production_default:
        raise AssertionError(f"Tests must pass `{name}` explicitly — got production default {production_default}")


# ---------------------------------------------------------------------------
# Step 1: Ensure snapshot exists
# ---------------------------------------------------------------------------


def ensure_snapshot(
    as_of_date: str,
    *,
    snap_root: Path = SNAPSHOTS_ROOT,
    data_dir: Optional[Path] = None,
    skip_snapshot: bool = False,
    timeout_seconds: int = 900,
) -> Dict[str, Any]:
    """Verify snapshot exists; optionally run daily production to create it.

    Returns dict with snapshot_dir, created (bool), and any error.
    """
    snap_dir = snap_root / as_of_date
    rankings_path = snap_dir / "rankings.csv"

    if rankings_path.is_file():
        return {"snapshot_dir": str(snap_dir), "created": False, "status": "EXISTS"}

    if skip_snapshot:
        return {
            "snapshot_dir": str(snap_dir),
            "created": False,
            "status": "MISSING",
            "error": f"Snapshot missing for {as_of_date} and --skip-snapshot is set",
        }

    # Run daily production to create the snapshot
    cmd = [
        sys.executable,
        str(DAILY_PRODUCTION_SCRIPT),
        "--as-of-date",
        as_of_date,
        "--data-dir",
        str(data_dir or (PROJECT_ROOT / "production_data")),
        "--snapshot-dir",
        str(snap_root),
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired:
        return {
            "snapshot_dir": str(snap_dir),
            "created": False,
            "status": "TIMEOUT",
            "error": f"run_daily_production timed out after {timeout_seconds}s",
        }

    if proc.returncode not in (0, 2):
        return {
            "snapshot_dir": str(snap_dir),
            "created": False,
            "status": "FAIL",
            "error": f"run_daily_production exit {proc.returncode}: {proc.stderr[-500:] if proc.stderr else ''}",
            "exit_code": proc.returncode,
        }

    # Verify snapshot was actually created
    if not rankings_path.is_file():
        return {
            "snapshot_dir": str(snap_dir),
            "created": False,
            "status": "FAIL",
            "error": "run_daily_production succeeded but rankings.csv not found",
        }

    return {
        "snapshot_dir": str(snap_dir),
        "created": True,
        "status": "OK",
        "exit_code": proc.returncode,
    }


# ---------------------------------------------------------------------------
# Step 2: Build shadow positions
# ---------------------------------------------------------------------------


def build_shadow_positions(
    as_of_date: str,
    snap_dir: Path,
    *,
    positions_dir: Path = POSITIONS_DIR,
    policy_path: Optional[Path] = None,
    perf_csv: Path = PERFORMANCE_CSV,
    price_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build shadow positions from snapshot, save to positions_dir.

    Returns dict with positions path, metadata, and performance info.
    """
    _assert_not_production_default("positions_dir", positions_dir, POSITIONS_DIR)

    policy = load_policy(policy_path)
    rankings = load_rankings(snap_dir)
    metadata = load_metadata(snap_dir)

    positions_data = build_positions(rankings, policy)
    pos_path = save_positions(as_of_date, positions_data, metadata, out_dir=positions_dir)

    # Compute performance vs prior week (best-effort)
    perf_result = None
    from tools.build_trade_deltas import find_prior_positions, load_positions_json

    prior_path = find_prior_positions(as_of_date, positions_dir)
    if prior_path:
        prior_date, prior_positions = load_positions_json(prior_path)
        try:
            _price_path = price_path or (PROJECT_ROOT / "production_data" / "price_history.csv")
            perf_result = compute_performance(
                prior_positions,
                positions_data["positions"],
                prior_date,
                as_of_date,
                price_path=_price_path,
            )
            ruleset_id = metadata.get("ruleset_id", "")
            append_performance(as_of_date, perf_result, ruleset_id=ruleset_id, perf_csv=perf_csv)
        except Exception as e:
            perf_result = {"error": str(e)}

    return {
        "positions_path": str(pos_path),
        "n_positions": len(positions_data.get("positions", [])),
        "metadata": metadata,
        "performance": perf_result,
    }


# ---------------------------------------------------------------------------
# Step 3-5: Pre-trade check + trade plan
# ---------------------------------------------------------------------------


def run_execution_pipeline(
    as_of_date: str,
    snap_dir: Path,
    *,
    positions_dir: Path = POSITIONS_DIR,
    execution_root: Path = EXECUTION_ROOT,
    policy_path: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
    perf_csv: Path = PERFORMANCE_CSV,
    price_source: Optional[Path] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Run the full execution pipeline: pre-trade check → trade plan → broker orders.

    Returns the execution packet dict.
    """
    _assert_not_production_default("positions_dir", positions_dir, POSITIONS_DIR)
    _assert_not_production_default("execution_root", execution_root, EXECUTION_ROOT)

    out_dir = execution_root / as_of_date
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Run pre-trade check
    from tools.pre_trade_check import run_pre_trade_check, write_pre_trade_json, write_pre_trade_md

    _manifest_path = manifest_path or (PROJECT_ROOT / "production_data" / "decision_rulesets" / "manifest.json")

    ptc = run_pre_trade_check(
        as_of_date,
        positions_dir=positions_dir,
        snap_dir=snap_dir,
        manifest_path=_manifest_path,
        perf_csv=perf_csv,
        policy_path=policy_path,
    )

    write_pre_trade_json(ptc, out_dir / "pre_trade.json")
    write_pre_trade_md(ptc, out_dir / "pre_trade.md")

    packet = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "generated_at": ts,
        "pre_trade": {
            "overall": ptc.overall,
            "can_trade": ptc.can_trade,
            "checks": ptc.checks,
        },
    }

    if not ptc.can_trade:
        packet["status"] = "BLOCKED"
        packet["reason"] = f"Pre-trade check {ptc.overall}"
        packet["exit_code"] = 2
        _write_packet(packet, out_dir)
        return packet

    if dry_run:
        packet["status"] = "DRY_RUN"
        packet["reason"] = "Trade plan not generated (dry run)"
        packet["exit_code"] = 0
        _write_packet(packet, out_dir)
        return packet

    # Build trade plan with broker orders
    from tools.build_trade_plan import build_trade_plan

    plan_result = build_trade_plan(
        as_of_date,
        positions_dir=positions_dir,
        perf_csv=perf_csv,
        out_dir=out_dir,
        skip_pre_trade_check=True,  # Already ran it above
        broker_orders=True,
        price_source=price_source,
        manifest_path=_manifest_path,
        snap_dir=snap_dir,
    )

    if "error" in plan_result:
        packet["status"] = "BLOCKED"
        packet["reason"] = f"Trade plan error: {plan_result['error']}"
        packet["exit_code"] = 2
        _write_packet(packet, out_dir)
        return packet

    packet["status"] = "READY"
    packet["exit_code"] = 0
    packet["trade_plan"] = {
        "n_trades": plan_result.get("n_trades", 0),
        "n_buys": plan_result.get("n_buys", 0),
        "n_sells": plan_result.get("n_sells", 0),
        "total_buy_usd": plan_result.get("total_buy_usd", 0),
        "total_sell_usd": plan_result.get("total_sell_usd", 0),
        "risk_permission": plan_result.get("risk_permission", "ADD_OK"),
        "csv_path": plan_result.get("csv_path", ""),
        "md_path": plan_result.get("md_path", ""),
        "broker_orders_path": plan_result.get("broker_orders_path", ""),
    }

    _write_packet(packet, out_dir)
    return packet


# ---------------------------------------------------------------------------
# Packet output
# ---------------------------------------------------------------------------


def _write_packet(packet: Dict[str, Any], out_dir: Path) -> None:
    """Write EXECUTION_PACKET.json and .md to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = out_dir / "EXECUTION_PACKET.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(packet, f, indent=2, default=str)

    # Markdown
    md_path = out_dir / "EXECUTION_PACKET.md"
    lines = _render_packet_md(packet)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _render_packet_md(packet: Dict[str, Any]) -> List[str]:
    """Render execution packet as markdown."""
    lines = []
    status = packet.get("status", "UNKNOWN")
    as_of = packet.get("as_of_date", "?")
    ts = packet.get("generated_at", "?")

    lines.append(f"# Execution Packet — {as_of}")
    lines.append("")
    lines.append(f"**Status**: {status}")
    lines.append(f"**Generated**: {ts}")
    lines.append("")

    if status == "BLOCKED":
        lines.append(f"> **BLOCKED** — {packet.get('reason', 'pre-trade check failed')}")
        lines.append("")

    # Pre-trade checks
    ptc = packet.get("pre_trade", {})
    lines.append(f"## Pre-Trade Gate: {ptc.get('overall', '?')}")
    lines.append("")
    for c in ptc.get("checks", []):
        icon = {"PASS": "PASS", "WARN": "WARN", "FAIL": "FAIL"}.get(c["status"], "???")
        lines.append(f"- [{icon}] **{c['name']}**: {c['detail']}")
    lines.append("")

    # Trade plan (if READY)
    tp = packet.get("trade_plan")
    if tp:
        lines.append("## Trade Plan")
        lines.append("")
        lines.append(f"- **Trades**: {tp['n_trades']} ({tp['n_buys']} buys, {tp['n_sells']} sells)")
        lines.append(f"- **Buy total**: ${tp['total_buy_usd']:,.0f}")
        lines.append(f"- **Sell total**: ${tp['total_sell_usd']:,.0f}")
        lines.append(f"- **Risk permission**: {tp.get('risk_permission', 'ADD_OK')}")
        lines.append("")
        if tp.get("csv_path"):
            lines.append(f"Trade plan CSV: `{tp['csv_path']}`")
        if tp.get("broker_orders_path"):
            lines.append(f"Broker orders: `{tp['broker_orders_path']}`")
        lines.append("")

    if status == "DRY_RUN":
        lines.append("> Dry run — no trade plan generated.")
        lines.append("")

    return lines


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


def run_weekly_execution(
    as_of_date: str,
    *,
    snap_root: Path = SNAPSHOTS_ROOT,
    positions_dir: Path = POSITIONS_DIR,
    execution_root: Path = EXECUTION_ROOT,
    policy_path: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
    perf_csv: Path = PERFORMANCE_CSV,
    price_source: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    skip_snapshot: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Full weekly execution: snapshot → positions → pre-trade → trade plan.

    Returns execution packet dict with status in {READY, BLOCKED, DRY_RUN}.
    Exit codes: 0 (READY/DRY_RUN), 2 (BLOCKED).
    """
    _assert_not_production_default("positions_dir", positions_dir, POSITIONS_DIR)
    _assert_not_production_default("execution_root", execution_root, EXECUTION_ROOT)
    _assert_not_production_default("snap_root", snap_root, SNAPSHOTS_ROOT)

    # Step 1: Ensure snapshot
    snap_result = ensure_snapshot(
        as_of_date,
        snap_root=snap_root,
        data_dir=data_dir,
        skip_snapshot=skip_snapshot,
    )

    if snap_result.get("error"):
        out_dir = execution_root / as_of_date
        packet = {
            "schema": SCHEMA_VERSION,
            "as_of_date": as_of_date,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "BLOCKED",
            "reason": f"Snapshot: {snap_result['error']}",
            "exit_code": 2,
            "pre_trade": {"overall": "FAIL", "can_trade": False, "checks": []},
        }
        _write_packet(packet, out_dir)
        return packet

    snap_dir = Path(snap_result["snapshot_dir"])

    # Step 2: Build shadow positions
    pos_result = build_shadow_positions(
        as_of_date,
        snap_dir,
        positions_dir=positions_dir,
        policy_path=policy_path,
        perf_csv=perf_csv,
        price_path=price_source,
    )

    # Steps 3-5: Pre-trade check → trade plan → broker orders
    packet = run_execution_pipeline(
        as_of_date,
        snap_dir,
        positions_dir=positions_dir,
        execution_root=execution_root,
        policy_path=policy_path,
        manifest_path=manifest_path,
        perf_csv=perf_csv,
        price_source=price_source,
        dry_run=dry_run,
    )

    # Attach position info to packet
    packet["positions"] = {
        "n_positions": pos_result.get("n_positions", 0),
        "positions_path": pos_result.get("positions_path", ""),
    }
    packet["snapshot"] = snap_result

    # IC Packet (best-effort — skip on failure)
    try:
        # Load current positions for IC packet
        from tools.build_trade_deltas import load_positions_json
        from tools.ic_packet import build_ic_packet, write_ic_packet

        pos_file = positions_dir / f"{as_of_date}.json"
        positions = []
        if pos_file.is_file():
            _, positions = load_positions_json(pos_file)

        policy = load_policy(policy_path)
        metadata = load_metadata(snap_dir)
        perf = pos_result.get("performance")

        out_dir = execution_root / as_of_date
        ic = build_ic_packet(
            as_of_date,
            packet,
            positions,
            policy,
            metadata,
            perf,
            out_dir,
            policy_path=policy_path,
        )
        write_ic_packet(out_dir, ic)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("IC packet failed: %s", exc)

    return packet


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly execution runner — one-command trade pipeline")
    parser.add_argument("--as-of-date", type=str, required=True, help="Snapshot date (YYYY-MM-DD)")
    parser.add_argument("--policy", type=str, help="Portfolio policy JSON path")
    parser.add_argument("--skip-snapshot", action="store_true", help="Don't run daily production if snapshot missing")
    parser.add_argument("--dry-run", action="store_true", help="Run pre-trade checks but don't generate trade plan")
    parser.add_argument("--price-source", type=str, help="Price CSV path")
    parser.add_argument("--data-dir", type=str, help="Data directory for run_daily_production")
    args = parser.parse_args()

    policy_path = Path(args.policy) if args.policy else None
    price_source = Path(args.price_source) if args.price_source else None
    data_dir = Path(args.data_dir) if args.data_dir else None

    result = run_weekly_execution(
        args.as_of_date,
        policy_path=policy_path,
        skip_snapshot=args.skip_snapshot,
        dry_run=args.dry_run,
        price_source=price_source,
        data_dir=data_dir,
    )

    status = result.get("status", "UNKNOWN")
    print(f"Execution status: {status}")

    if status == "BLOCKED":
        print(f"Reason: {result.get('reason', '?')}")
        ptc = result.get("pre_trade", {})
        for c in ptc.get("checks", []):
            print(f"  [{c['status']}] {c['name']}: {c['detail']}")
        sys.exit(2)

    if status == "READY":
        tp = result.get("trade_plan", {})
        print(f"Trades: {tp.get('n_trades', 0)} ({tp.get('n_buys', 0)} buys, {tp.get('n_sells', 0)} sells)")
        print(f"Risk permission: {tp.get('risk_permission', '?')}")
        if tp.get("broker_orders_path"):
            print(f"Broker orders: {tp['broker_orders_path']}")

    out_dir = EXECUTION_ROOT / args.as_of_date
    print(f"Packet: {out_dir / 'EXECUTION_PACKET.json'}")


if __name__ == "__main__":
    main()

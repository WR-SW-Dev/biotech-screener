"""Tests for tools/run_weekly_execution.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.run_weekly_execution import (
    SCHEMA_VERSION,
    _write_packet,
    ensure_snapshot,
    run_execution_pipeline,
    run_weekly_execution,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PERF_COLUMNS = [
    "schema_version",
    "date",
    "prior_date",
    "total_pnl",
    "pnl_pct",
    "xbi_return_pct",
    "excess_vs_xbi_pct",
    "n_held",
    "turnover",
    "gap_risk_high_count",
    "n_missing_price",
    "sleeve_binary_0_30_pnl",
    "sleeve_binary_31_90_pnl",
    "sleeve_binary_91_180_pnl",
    "sleeve_less_binary_pnl",
    "ruleset_id",
]


def _write_metadata(snap_dir, **overrides):
    snap_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "ruleset_id": "test1234",
        "as_of_date": "2026-03-10",
        "engine_version": "v1.3.0",
        "git_sha": "abc123",  # pragma: allowlist secret
    }
    meta.update(overrides)
    with open(snap_dir / "metadata.json", "w") as f:
        json.dump(meta, f)


def _write_rankings(snap_dir, n=10):
    """Write a minimal rankings.csv with n eligible rows."""
    snap_dir.mkdir(parents=True, exist_ok=True)
    header = [
        "ticker",
        "actionable_rank",
        "composite_rank",
        "eligible",
        "archetype",
        "catalyst_family",
        "catalyst_mode",
        "catalyst_days",
        "has_regulatory_upcoming_180d",
        "target_weight_pct",
        "tier_any",
        "gap_risk",
        "regulatory_days",
    ]
    rows = []
    for i in range(n):
        rows.append(
            {
                "ticker": f"T{i:03d}",
                "actionable_rank": str(i + 1),
                "composite_rank": str(i + 1),
                "eligible": "1",
                "archetype": "CLINICAL",
                "catalyst_family": "CLINICAL",
                "catalyst_mode": "specific_days",
                "catalyst_days": "120",
                "has_regulatory_upcoming_180d": "0",
                "target_weight_pct": "2.0",
                "tier_any": "A",
                "gap_risk": "",
                "regulatory_days": "",
            }
        )
    with open(snap_dir / "rankings.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


def _write_positions(pos_dir, date, positions):
    pos_dir.mkdir(parents=True, exist_ok=True)
    with open(pos_dir / f"{date}.json", "w") as f:
        json.dump(
            {"schema": "live_shadow_positions.v1", "as_of_date": date, "positions": positions},
            f,
        )


def _make_positions():
    """Create positions spread across buckets matching default policy proportions.

    Policy: $500k account, 55/25/10/10 bucket targets.
    """
    account = 500_000
    bucket_specs = [
        ("binary_91_180", 0.55, 20),
        ("binary_31_90", 0.25, 10),
        ("binary_0_30", 0.10, 5),
        ("less_binary", 0.10, 5),
    ]
    positions = []
    idx = 0
    for bucket, pct, count in bucket_specs:
        per_name = account * pct / count
        for j in range(count):
            positions.append(
                {
                    "ticker": f"T{idx:03d}",
                    "bucket": bucket,
                    "target_dollars": round(per_name, 2),
                    "gap_risk": "",
                    "price_coverage": "OK",
                    "actionable_rank": idx + 1,
                }
            )
            idx += 1
    return positions


def _write_manifest(manifest_path, active_id="test1234"):
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "rulesets": [
            {"id": active_id, "status": "active", "version": "v1.11.0"},
        ]
    }
    with open(manifest_path, "w") as f:
        json.dump(data, f)


def _write_perf_csv(path, rows=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if rows is None:
        rows = []
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PERF_COLUMNS)
        w.writeheader()
        w.writerows(rows)


def _write_price_csv(path, tickers=None, date="2026-03-10"):
    """Write a minimal price_history.csv."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if tickers is None:
        tickers = [f"T{i:03d}" for i in range(40)]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "date", "open", "high", "low", "close", "volume"])
        w.writeheader()
        for t in tickers:
            w.writerow(
                {"ticker": t, "date": date, "open": "10", "high": "11", "low": "9", "close": "10", "volume": "1000"}
            )


def _setup_full_env(tmp_path, as_of="2026-03-10", prior_as_of="2026-03-03"):
    """Set up a complete test environment with snapshot, positions, manifest, etc."""
    snap_root = tmp_path / "snapshots"
    snap_dir = snap_root / as_of
    positions_dir = tmp_path / "positions"
    execution_root = tmp_path / "execution"
    manifest_path = tmp_path / "manifest.json"
    perf_csv = tmp_path / "performance.csv"
    price_csv = tmp_path / "price_history.csv"

    _write_rankings(snap_dir, n=10)
    _write_metadata(snap_dir, as_of_date=as_of)
    (snap_dir / "run_manifest.json").write_text("{}")

    _write_manifest(manifest_path)
    _write_perf_csv(perf_csv)
    _write_price_csv(price_csv)

    # Write prior positions so we have a baseline for deltas
    if prior_as_of:
        _write_positions(positions_dir, prior_as_of, _make_positions())

    return {
        "snap_root": snap_root,
        "snap_dir": snap_dir,
        "positions_dir": positions_dir,
        "execution_root": execution_root,
        "manifest_path": manifest_path,
        "perf_csv": perf_csv,
        "price_csv": price_csv,
        "as_of": as_of,
    }


# ---------------------------------------------------------------------------
# ensure_snapshot tests
# ---------------------------------------------------------------------------


class TestEnsureSnapshot:
    def test_snapshot_already_exists(self, tmp_path):
        snap_root = tmp_path / "snapshots"
        snap_dir = snap_root / "2026-03-10"
        _write_rankings(snap_dir)
        result = ensure_snapshot("2026-03-10", snap_root=snap_root, skip_snapshot=True)
        assert result["status"] == "EXISTS"
        assert result["created"] is False

    def test_snapshot_missing_skip(self, tmp_path):
        snap_root = tmp_path / "snapshots"
        result = ensure_snapshot("2026-03-10", snap_root=snap_root, skip_snapshot=True)
        assert result["status"] == "MISSING"
        assert "error" in result


# ---------------------------------------------------------------------------
# run_execution_pipeline: READY path
# ---------------------------------------------------------------------------


class TestReadyPath:
    def test_ready_with_valid_env(self, tmp_path):
        """Pre-trade passes + trade plan generated → READY."""
        env = _setup_full_env(tmp_path)

        # Write well-formed positions directly (bypasses build_positions)
        positions = _make_positions()
        _write_positions(env["positions_dir"], env["as_of"], positions)

        packet = run_execution_pipeline(
            env["as_of"],
            env["snap_dir"],
            positions_dir=env["positions_dir"],
            execution_root=env["execution_root"],
            manifest_path=env["manifest_path"],
            perf_csv=env["perf_csv"],
            price_source=env["price_csv"],
        )

        assert packet["status"] == "READY"
        assert packet["exit_code"] == 0
        assert "trade_plan" in packet
        assert packet["trade_plan"]["n_trades"] >= 0
        assert packet["pre_trade"]["can_trade"] is True

        # Verify packet files written
        out_dir = env["execution_root"] / env["as_of"]
        assert (out_dir / "EXECUTION_PACKET.json").is_file()
        assert (out_dir / "EXECUTION_PACKET.md").is_file()
        assert (out_dir / "pre_trade.json").is_file()
        assert (out_dir / "pre_trade.md").is_file()

    def test_ready_includes_broker_orders(self, tmp_path):
        """READY packet includes broker_orders_path when trades exist."""
        env = _setup_full_env(tmp_path, prior_as_of=None)

        # Write current positions (many names) and empty prior → all buys
        positions = _make_positions()
        _write_positions(env["positions_dir"], env["as_of"], positions)
        _write_positions(env["positions_dir"], "2026-03-03", [])

        packet = run_execution_pipeline(
            env["as_of"],
            env["snap_dir"],
            positions_dir=env["positions_dir"],
            execution_root=env["execution_root"],
            manifest_path=env["manifest_path"],
            perf_csv=env["perf_csv"],
            price_source=env["price_csv"],
        )

        assert packet["status"] == "READY"
        tp = packet["trade_plan"]
        if tp["n_trades"] > 0:
            assert tp.get("broker_orders_path")


# ---------------------------------------------------------------------------
# run_execution_pipeline: BLOCKED path
# ---------------------------------------------------------------------------


class TestBlockedPath:
    def test_blocked_on_ruleset_mismatch(self, tmp_path):
        """Ruleset mismatch in pre-trade → BLOCKED."""
        env = _setup_full_env(tmp_path)

        # Write manifest with different active ID
        _write_manifest(env["manifest_path"], active_id="different")

        positions = _make_positions()
        _write_positions(env["positions_dir"], env["as_of"], positions)

        packet = run_execution_pipeline(
            env["as_of"],
            env["snap_dir"],
            positions_dir=env["positions_dir"],
            execution_root=env["execution_root"],
            manifest_path=env["manifest_path"],
            perf_csv=env["perf_csv"],
        )

        assert packet["status"] == "BLOCKED"
        assert packet["exit_code"] == 2
        assert packet["pre_trade"]["can_trade"] is False

        # Verify packet files still written
        out_dir = env["execution_root"] / env["as_of"]
        assert (out_dir / "EXECUTION_PACKET.json").is_file()

    def test_blocked_no_positions_file(self, tmp_path):
        """No positions file → BLOCKED."""
        env = _setup_full_env(tmp_path)

        # Don't build positions — just run pipeline directly
        packet = run_execution_pipeline(
            env["as_of"],
            env["snap_dir"],
            positions_dir=env["positions_dir"],
            execution_root=env["execution_root"],
            manifest_path=env["manifest_path"],
            perf_csv=env["perf_csv"],
        )

        # Pre-trade check should fail because no positions file
        assert packet["status"] == "BLOCKED"
        assert packet["exit_code"] == 2


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_skips_trade_plan(self, tmp_path):
        env = _setup_full_env(tmp_path)

        positions = _make_positions()
        _write_positions(env["positions_dir"], env["as_of"], positions)

        packet = run_execution_pipeline(
            env["as_of"],
            env["snap_dir"],
            positions_dir=env["positions_dir"],
            execution_root=env["execution_root"],
            manifest_path=env["manifest_path"],
            perf_csv=env["perf_csv"],
            dry_run=True,
        )

        assert packet["status"] == "DRY_RUN"
        assert packet["exit_code"] == 0
        assert "trade_plan" not in packet


# ---------------------------------------------------------------------------
# No production leakage
# ---------------------------------------------------------------------------


class TestNoProductionLeakage:
    def test_positions_dir_guard(self):
        """Using production default positions_dir in tests raises."""
        with pytest.raises(AssertionError, match="Tests must pass"):
            run_execution_pipeline(
                "2026-03-10",
                Path("/tmp/fake_snap"),
            )

    def test_execution_root_guard(self, tmp_path):
        """Using production default execution_root in tests raises."""
        with pytest.raises(AssertionError, match="Tests must pass"):
            run_execution_pipeline(
                "2026-03-10",
                Path("/tmp/fake_snap"),
                positions_dir=tmp_path / "positions",
            )

    def test_snap_root_guard(self):
        """Using production default snap_root in run_weekly_execution raises."""
        with pytest.raises(AssertionError, match="Tests must pass"):
            run_weekly_execution(
                "2026-03-10",
                positions_dir=Path("/tmp/pos"),
                execution_root=Path("/tmp/exec"),
            )


# ---------------------------------------------------------------------------
# Packet output
# ---------------------------------------------------------------------------


class TestPacketOutput:
    def test_write_packet_creates_json_and_md(self, tmp_path):
        packet = {
            "schema": SCHEMA_VERSION,
            "as_of_date": "2026-03-10",
            "status": "READY",
            "exit_code": 0,
            "pre_trade": {"overall": "PASS", "can_trade": True, "checks": []},
            "trade_plan": {
                "n_trades": 5,
                "n_buys": 3,
                "n_sells": 2,
                "total_buy_usd": 15000,
                "total_sell_usd": 10000,
                "risk_permission": "ADD_OK",
                "csv_path": "/tmp/trade_plan.csv",
                "md_path": "/tmp/trade_plan.md",
                "broker_orders_path": "/tmp/broker_orders.csv",
            },
        }
        _write_packet(packet, tmp_path)
        assert (tmp_path / "EXECUTION_PACKET.json").is_file()
        assert (tmp_path / "EXECUTION_PACKET.md").is_file()

        loaded = json.loads((tmp_path / "EXECUTION_PACKET.json").read_text())
        assert loaded["status"] == "READY"

        md = (tmp_path / "EXECUTION_PACKET.md").read_text()
        assert "READY" in md
        assert "5" in md  # n_trades

    def test_blocked_packet_md_has_blocked_banner(self, tmp_path):
        packet = {
            "schema": SCHEMA_VERSION,
            "as_of_date": "2026-03-10",
            "status": "BLOCKED",
            "reason": "Pre-trade check FAIL",
            "exit_code": 2,
            "pre_trade": {
                "overall": "FAIL",
                "can_trade": False,
                "checks": [{"name": "ruleset_active", "status": "FAIL", "detail": "mismatch"}],
            },
        }
        _write_packet(packet, tmp_path)
        md = (tmp_path / "EXECUTION_PACKET.md").read_text()
        assert "BLOCKED" in md
        assert "FAIL" in md


# ---------------------------------------------------------------------------
# Full run_weekly_execution integration
# ---------------------------------------------------------------------------


class TestFullExecution:
    def test_end_to_end_ready(self, tmp_path):
        """Full pipeline with existing snapshot → READY."""
        env = _setup_full_env(tmp_path)

        # Mock build_shadow_positions to write well-formed positions
        positions = _make_positions()

        def _mock_build(as_of_date, snap_dir, *, positions_dir, **kwargs):
            _write_positions(positions_dir, as_of_date, positions)
            return {
                "positions_path": str(positions_dir / f"{as_of_date}.json"),
                "n_positions": len(positions),
                "metadata": {"ruleset_id": "test1234"},
                "performance": None,
            }

        with patch("tools.run_weekly_execution.build_shadow_positions", side_effect=_mock_build):
            packet = run_weekly_execution(
                env["as_of"],
                snap_root=env["snap_root"],
                positions_dir=env["positions_dir"],
                execution_root=env["execution_root"],
                manifest_path=env["manifest_path"],
                perf_csv=env["perf_csv"],
                price_source=env["price_csv"],
                skip_snapshot=True,
            )

        assert packet["status"] == "READY"
        assert "snapshot" in packet
        assert packet["snapshot"]["status"] == "EXISTS"
        assert "positions" in packet
        assert packet["positions"]["n_positions"] > 0

    def test_end_to_end_blocked_missing_snapshot(self, tmp_path):
        """Missing snapshot + skip_snapshot → BLOCKED."""
        packet = run_weekly_execution(
            "2026-03-10",
            snap_root=tmp_path / "empty_snaps",
            positions_dir=tmp_path / "positions",
            execution_root=tmp_path / "execution",
            skip_snapshot=True,
        )

        assert packet["status"] == "BLOCKED"
        assert "Snapshot" in packet.get("reason", "")

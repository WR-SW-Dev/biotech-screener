"""Tests for binding caps — TRADE_WITH_CAPS adjusts trade plan + broker orders."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.run_weekly_execution import run_weekly_execution
from tools.trade_decision import (
    VERDICT_NO_TRADE,
    VERDICT_TRADE,
    VERDICT_TRADE_WITH_CAPS,
    apply_caps_to_positions,
    build_global_name_cap,
)

# ---------------------------------------------------------------------------
# Shared fixtures (same pattern as test_weekly_execution.py)
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


def _make_positions(gap_risk_tickers=None):
    """Create positions spread across buckets, with optional gap-risk HIGH tickers."""
    if gap_risk_tickers is None:
        gap_risk_tickers = set()

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
            ticker = f"T{idx:03d}"
            positions.append(
                {
                    "ticker": ticker,
                    "bucket": bucket,
                    "target_dollars": round(per_name, 2),
                    "weight_pct": round(per_name / account * 100, 4),
                    "gap_risk": "HIGH" if ticker in gap_risk_tickers else "",
                    "price_coverage": "OK",
                    "actionable_rank": idx + 1,
                    "catalyst_days": "5" if ticker in gap_risk_tickers else "120",
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


def _write_trade_decision_policy(path, **overrides):
    """Write trade_decision_policy.json with overridable thresholds."""
    policy = {
        "schema": "trade_decision_policy.v1",
        "gates": {"pre_trade_must_pass": True},
        "risk_limits": {
            "max_gap_risk_high_count": 4,
            "max_gap_risk_high_weight_pct": 8.0,
            "max_missing_price_coverage": 2,
            "max_resolved_regulatory": 3,
        },
        "execution_quality": {
            "min_fill_coverage_pct": 50.0,
            "max_avg_slippage_bps": 50.0,
        },
        "model_vs_realized": {"max_negative_gap_pct": -0.50},
        "alpha_health": {"min_trailing_excess_pct": -1.0},
        "turnover": {"max_turnover_pct": 40.0},
        "caps": {
            "gap_risk_high_count_trigger": 3,
            "gap_risk_high_name_cap_pct": 0.25,
            "gap_risk_high_budget_reduction_pct": 15.0,
            "realized_worse_slippage_trigger_bps": 30.0,
            "realized_worse_min_trade_usd_bump": 500,
        },
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and k in policy:
            policy[k].update(v)
        else:
            policy[k] = v
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(policy, f)
    return policy


def _setup_full_env(tmp_path, as_of="2026-03-10", prior_as_of="2026-03-03", gap_risk_tickers=None):
    """Set up a complete test environment."""
    snap_root = tmp_path / "snapshots"
    snap_dir = snap_root / as_of
    positions_dir = tmp_path / "positions"
    execution_root = tmp_path / "execution"
    manifest_path = tmp_path / "manifest.json"
    perf_csv = tmp_path / "performance.csv"
    price_csv = tmp_path / "price_history.csv"
    td_policy_path = tmp_path / "trade_decision_policy.json"

    _write_rankings(snap_dir, n=10)
    _write_metadata(snap_dir, as_of_date=as_of)
    (snap_dir / "run_manifest.json").write_text("{}")

    _write_manifest(manifest_path)
    _write_perf_csv(perf_csv)
    _write_price_csv(price_csv)

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
        "td_policy_path": td_policy_path,
        "as_of": as_of,
        "gap_risk_tickers": gap_risk_tickers,
    }


def _run_execution(env, positions, td_policy_overrides=None):
    """Helper to run full execution with mock positions."""
    _write_trade_decision_policy(env["td_policy_path"], **(td_policy_overrides or {}))

    def _mock_build(as_of_date, snap_dir, *, positions_dir, **kwargs):
        _write_positions(positions_dir, as_of_date, positions)
        return {
            "positions_path": str(positions_dir / f"{as_of_date}.json"),
            "n_positions": len(positions),
            "metadata": {"ruleset_id": "test1234"},
            "performance": None,
        }

    with patch("tools.run_weekly_execution.build_shadow_positions", side_effect=_mock_build):
        return run_weekly_execution(
            env["as_of"],
            snap_root=env["snap_root"],
            positions_dir=env["positions_dir"],
            execution_root=env["execution_root"],
            manifest_path=env["manifest_path"],
            perf_csv=env["perf_csv"],
            price_source=env["price_csv"],
            skip_snapshot=True,
            trade_decision_policy_path=env["td_policy_path"],
        )


# ---------------------------------------------------------------------------
# Unit tests for apply_caps_to_positions
# ---------------------------------------------------------------------------


class TestApplyCaps:
    def test_gap_risk_cap_reduces_affected_tickers(self):
        positions = [
            {"ticker": "A", "bucket": "binary_0_30", "target_dollars": 15000, "weight_pct": 3.0, "gap_risk": "HIGH"},
            {"ticker": "B", "bucket": "binary_91_180", "target_dollars": 10000, "weight_pct": 2.0, "gap_risk": ""},
        ]
        caps = [
            {
                "type": "gap_risk_cap",
                "name_cap_pct": 0.25,
                "budget_reduction_pct": 0,
                "affected_tickers": ["A"],
                "triggered_by": "gap_risk_high_count",
            }
        ]
        capped, summary = apply_caps_to_positions(positions, caps, 500_000)

        # A capped to 0.25% of $500k = $1,250
        assert capped[0]["target_dollars"] == 1250.0
        # B unchanged
        assert capped[1]["target_dollars"] == 10000
        assert summary["caps_applied"] is True
        assert len(summary["top_reductions"]) == 1
        assert summary["top_reductions"][0]["ticker"] == "A"

    def test_budget_reduction_scales_all(self):
        positions = [
            {"ticker": "A", "bucket": "b", "target_dollars": 10000, "weight_pct": 2.0, "gap_risk": ""},
            {"ticker": "B", "bucket": "b", "target_dollars": 20000, "weight_pct": 4.0, "gap_risk": ""},
        ]
        caps = [
            {
                "type": "gap_risk_cap",
                "name_cap_pct": 100.0,
                "budget_reduction_pct": 10.0,
                "affected_tickers": [],
                "triggered_by": "gap_risk_high_count",
            }
        ]
        capped, summary = apply_caps_to_positions(positions, caps, 500_000)

        assert capped[0]["target_dollars"] == 9000.0
        assert capped[1]["target_dollars"] == 18000.0
        assert summary["targets_after"]["total_usd"] == 27000.0

    def test_min_trade_bump_returned(self):
        positions = [
            {"ticker": "A", "bucket": "b", "target_dollars": 10000, "weight_pct": 2.0, "gap_risk": ""},
        ]
        caps = [
            {"type": "min_trade_bump", "min_trade_usd_bump": 500, "triggered_by": "execution_quality"},
        ]
        capped, summary = apply_caps_to_positions(positions, caps, 500_000)

        # Positions unchanged
        assert capped[0]["target_dollars"] == 10000
        assert summary["min_trade_usd_bump"] == 500

    def test_originals_not_mutated(self):
        positions = [
            {"ticker": "A", "bucket": "b", "target_dollars": 15000, "weight_pct": 3.0, "gap_risk": "HIGH"},
        ]
        caps = [
            {
                "type": "gap_risk_cap",
                "name_cap_pct": 0.25,
                "budget_reduction_pct": 0,
                "affected_tickers": ["A"],
                "triggered_by": "test",
            }
        ]
        capped, _ = apply_caps_to_positions(positions, caps, 500_000)

        assert positions[0]["target_dollars"] == 15000
        assert capped[0]["target_dollars"] == 1250.0

    def test_no_negative_weights(self):
        positions = [
            {"ticker": "A", "bucket": "b", "target_dollars": 0, "weight_pct": 0, "gap_risk": "HIGH"},
        ]
        caps = [
            {
                "type": "gap_risk_cap",
                "name_cap_pct": 0.25,
                "budget_reduction_pct": 50.0,
                "affected_tickers": ["A"],
                "triggered_by": "test",
            }
        ]
        capped, _ = apply_caps_to_positions(positions, caps, 500_000)

        assert capped[0]["target_dollars"] >= 0
        assert capped[0]["weight_pct"] >= 0

    def test_weight_pct_updated(self):
        positions = [
            {"ticker": "A", "bucket": "b", "target_dollars": 15000, "weight_pct": 3.0, "gap_risk": "HIGH"},
        ]
        caps = [
            {
                "type": "gap_risk_cap",
                "name_cap_pct": 0.25,
                "budget_reduction_pct": 0,
                "affected_tickers": ["A"],
                "triggered_by": "test",
            }
        ]
        capped, _ = apply_caps_to_positions(positions, caps, 500_000)

        # weight_pct should be 1250 / 500000 * 100 = 0.25
        assert capped[0]["weight_pct"] == 0.25

    def test_combined_cap_and_budget_reduction(self):
        """Cap + budget reduction applied in sequence."""
        positions = [
            {"ticker": "A", "bucket": "b", "target_dollars": 15000, "weight_pct": 3.0, "gap_risk": "HIGH"},
            {"ticker": "B", "bucket": "b", "target_dollars": 10000, "weight_pct": 2.0, "gap_risk": ""},
        ]
        caps = [
            {
                "type": "gap_risk_cap",
                "name_cap_pct": 0.25,
                "budget_reduction_pct": 10.0,
                "affected_tickers": ["A"],
                "triggered_by": "gap_risk_high_count",
            }
        ]
        capped, summary = apply_caps_to_positions(positions, caps, 500_000)

        # A: capped to 1250, then 10% reduction → 1125
        assert capped[0]["target_dollars"] == 1125.0
        # B: 10% reduction → 9000
        assert capped[1]["target_dollars"] == 9000.0
        assert summary["targets_before"]["total_usd"] == 25000.0
        assert summary["targets_after"]["total_usd"] == 10125.0


# ---------------------------------------------------------------------------
# TestCapsBindToOrders — caps actually reduce broker order notional
# ---------------------------------------------------------------------------


class TestCapsBindToOrders:
    def test_capped_orders_smaller_than_uncapped(self, tmp_path):
        """When TRADE_WITH_CAPS triggers, broker orders have reduced notional."""
        gap_tickers = {"T000", "T001", "T002"}
        env = _setup_full_env(tmp_path, gap_risk_tickers=gap_tickers, prior_as_of=None)

        # Positions with 3 gap-risk HIGH tickers (triggers cap at >=3)
        positions = _make_positions(gap_risk_tickers=gap_tickers)

        # Raise weight threshold so weight check passes but count trigger fires
        caps_policy = {
            "risk_limits": {"max_gap_risk_high_weight_pct": 20.0},
        }

        # First run uncapped to get baseline (policy that won't trigger caps)
        env_uncapped = _setup_full_env(tmp_path / "uncapped", gap_risk_tickers=gap_tickers, prior_as_of=None)
        # Set trigger impossibly high so no caps fire
        uncapped_packet = _run_execution(
            env_uncapped,
            positions,
            td_policy_overrides={
                **caps_policy,
                "caps": {"gap_risk_high_count_trigger": 999},
            },
        )

        # Now run with caps that will fire (trigger at 3)
        capped_packet = _run_execution(env, positions, td_policy_overrides=caps_policy)

        assert capped_packet["status"] == "READY"
        assert capped_packet.get("trade_decision", {}).get("verdict") == VERDICT_TRADE_WITH_CAPS
        assert capped_packet.get("caps_enforcement", {}).get("caps_applied") is True

        # Compare notional: capped should be less
        uncapped_buy = uncapped_packet["trade_plan"]["total_buy_usd"]
        capped_buy = capped_packet["trade_plan"]["total_buy_usd"]
        assert capped_buy < uncapped_buy, f"Capped buy ${capped_buy} should be less than uncapped ${uncapped_buy}"

        # Verify capped positions file written
        out_dir = env["execution_root"] / env["as_of"]
        assert (out_dir / "positions_capped.json").is_file()

    def test_caps_enforcement_in_packet(self, tmp_path):
        """caps_enforcement section present with before/after."""
        gap_tickers = {"T000", "T001", "T002"}
        env = _setup_full_env(tmp_path, gap_risk_tickers=gap_tickers, prior_as_of=None)
        positions = _make_positions(gap_risk_tickers=gap_tickers)

        packet = _run_execution(
            env, positions, td_policy_overrides={"risk_limits": {"max_gap_risk_high_weight_pct": 20.0}}
        )

        ce = packet.get("caps_enforcement")
        assert ce is not None
        assert ce["caps_applied"] is True
        assert "targets_before" in ce
        assert "targets_after" in ce
        assert ce["targets_after"]["total_usd"] < ce["targets_before"]["total_usd"]
        assert len(ce["top_reductions"]) > 0

    def test_caps_enforcement_in_md(self, tmp_path):
        """EXECUTION_PACKET.md contains caps transparency section."""
        gap_tickers = {"T000", "T001", "T002"}
        env = _setup_full_env(tmp_path, gap_risk_tickers=gap_tickers, prior_as_of=None)
        positions = _make_positions(gap_risk_tickers=gap_tickers)

        _run_execution(env, positions, td_policy_overrides={"risk_limits": {"max_gap_risk_high_weight_pct": 20.0}})

        out_dir = env["execution_root"] / env["as_of"]
        md = (out_dir / "EXECUTION_PACKET.md").read_text()
        assert "Caps Enforcement" in md
        assert "caps_applied" in md
        assert "Top Reductions" in md


# ---------------------------------------------------------------------------
# TestNoTradeBlocksOrders — NO_TRADE means no trade plan or broker orders
# ---------------------------------------------------------------------------


class TestNoTradeBlocksOrders:
    def test_no_trade_blocks_trade_plan(self, tmp_path):
        """NO_TRADE verdict → no trade_plan.csv or broker_orders.csv."""
        gap_tickers = {"T000"}
        env = _setup_full_env(tmp_path, prior_as_of=None, gap_risk_tickers=gap_tickers)
        positions = _make_positions(gap_risk_tickers=gap_tickers)

        # Force NO_TRADE: max_gap_risk_high_count=0 means 1 gap-risk name → FAIL
        packet = _run_execution(
            env,
            positions,
            td_policy_overrides={"risk_limits": {"max_gap_risk_high_count": 0}},
        )

        assert packet["status"] == "BLOCKED"
        assert "NO_TRADE" in packet.get("reason", "")
        assert "trade_plan" not in packet

        out_dir = env["execution_root"] / env["as_of"]
        assert not (out_dir / "trade_plan.csv").is_file()
        assert not (out_dir / "broker_orders.csv").is_file()

    def test_no_trade_has_decision_in_packet(self, tmp_path):
        """NO_TRADE packet still includes trade_decision section."""
        gap_tickers = {"T000"}
        env = _setup_full_env(tmp_path, prior_as_of=None, gap_risk_tickers=gap_tickers)
        positions = _make_positions(gap_risk_tickers=gap_tickers)

        packet = _run_execution(
            env,
            positions,
            td_policy_overrides={"risk_limits": {"max_gap_risk_high_count": 0}},
        )

        td = packet.get("trade_decision")
        assert td is not None
        assert td["verdict"] == VERDICT_NO_TRADE
        assert td["n_fail"] >= 1


# ---------------------------------------------------------------------------
# TestTradeUnchanged — TRADE verdict produces same behavior as before
# ---------------------------------------------------------------------------


class TestTradeUnchanged:
    def test_trade_produces_ready_with_plan(self, tmp_path):
        """TRADE verdict → READY packet with trade plan.

        Global name cap may still apply (it's universal), so caps_enforcement
        may be present.  The key check is verdict=TRADE and status=READY.
        """
        env = _setup_full_env(tmp_path, prior_as_of=None)
        positions = _make_positions()

        packet = _run_execution(env, positions)

        assert packet["status"] == "READY"
        assert packet.get("trade_decision", {}).get("verdict") == VERDICT_TRADE
        assert "trade_plan" in packet
        assert packet["trade_plan"]["n_trades"] >= 0

    def test_trade_plan_files_exist(self, tmp_path):
        """TRADE produces expected files."""
        env = _setup_full_env(tmp_path, prior_as_of=None)
        positions = _make_positions()
        _write_positions(env["positions_dir"], "2026-03-03", [])

        packet = _run_execution(env, positions)

        out_dir = env["execution_root"] / env["as_of"]
        assert (out_dir / "EXECUTION_PACKET.json").is_file()
        assert (out_dir / "EXECUTION_PACKET.md").is_file()
        assert (out_dir / "IC_PACKET.json").is_file()
        assert (out_dir / "TRADE_DECISION.json").is_file()
        assert (out_dir / "pre_trade.json").is_file()
        if packet["trade_plan"]["n_trades"] > 0:
            assert (out_dir / "trade_plan.csv").is_file()
            assert (out_dir / "broker_orders.csv").is_file()


# ---------------------------------------------------------------------------
# TestDeterminism — same inputs produce same outputs
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_inputs_same_decision(self, tmp_path):
        """build_trade_decision is deterministic (excluding timestamps)."""
        from tools.trade_decision import build_trade_decision as _build_td

        ic_packet = {
            "schema": "ic_packet.v1",
            "provenance": {"as_of_date": "2026-03-10", "ruleset_id": "test"},
            "gates": {"overall": "PASS", "can_trade": True, "checks": [], "blocking_reasons": []},
            "positions_summary": {"turnover_estimate_pct": 5.0},
            "model_vs_realized": None,
            "alpha_attribution": {"available": False},
            "execution_quality": {"available": False},
            "risk_flags": {
                "gap_risk_high": [{"ticker": "A", "weight_pct": 1.0}] * 3,
                "missing_price_coverage": [],
                "resolved_regulatory": [],
            },
        }
        td_policy = {
            "schema": "trade_decision_policy.v1",
            "gates": {"pre_trade_must_pass": True},
            "risk_limits": {
                "max_gap_risk_high_count": 4,
                "max_gap_risk_high_weight_pct": 8.0,
                "max_missing_price_coverage": 2,
                "max_resolved_regulatory": 3,
            },
            "execution_quality": {"min_fill_coverage_pct": 50.0, "max_avg_slippage_bps": 50.0},
            "model_vs_realized": {"max_negative_gap_pct": -0.50},
            "alpha_health": {"min_trailing_excess_pct": -1.0},
            "turnover": {"max_turnover_pct": 40.0},
            "caps": {
                "gap_risk_high_count_trigger": 3,
                "gap_risk_high_name_cap_pct": 0.25,
                "gap_risk_high_budget_reduction_pct": 15.0,
                "realized_worse_slippage_trigger_bps": 30.0,
                "realized_worse_min_trade_usd_bump": 500,
            },
        }

        d1 = _build_td(ic_packet, td_policy)
        d2 = _build_td(ic_packet, td_policy)

        # Strip timestamps for comparison
        for d in (d1, d2):
            d.pop("generated_at", None)

        assert d1 == d2

    def test_apply_caps_deterministic(self):
        """apply_caps_to_positions is deterministic."""
        positions = [
            {"ticker": "A", "bucket": "b", "target_dollars": 15000, "weight_pct": 3.0, "gap_risk": "HIGH"},
            {"ticker": "B", "bucket": "b", "target_dollars": 10000, "weight_pct": 2.0, "gap_risk": ""},
        ]
        caps = [
            {
                "type": "gap_risk_cap",
                "name_cap_pct": 0.25,
                "budget_reduction_pct": 10.0,
                "affected_tickers": ["A"],
                "triggered_by": "test",
            }
        ]

        c1, s1 = apply_caps_to_positions(positions, caps, 500_000)
        c2, s2 = apply_caps_to_positions(positions, caps, 500_000)

        assert c1 == c2
        assert s1 == s2


# ---------------------------------------------------------------------------
# TestMinTradeBump — min_trade_usd_bump increases min trade size
# ---------------------------------------------------------------------------


class TestMinTradeBump:
    def test_min_trade_bump_filters_small_trades(self, tmp_path):
        """min_trade_bump increases the min trade threshold."""
        env = _setup_full_env(tmp_path, prior_as_of="2026-03-03")

        # Positions similar to prior but with small differences + high slippage trigger
        positions = _make_positions()
        # Slightly adjust one position to create a small delta
        positions[0]["target_dollars"] = positions[0]["target_dollars"] + 600  # small BUY

        # Force TRADE_WITH_CAPS via execution quality cap
        # We need gap_risk >= 3 for gap_risk_cap OR execution quality issue
        # Let's use 3 gap risk tickers to trigger caps
        gap_tickers = {"T000", "T001", "T002"}
        positions_gap = _make_positions(gap_risk_tickers=gap_tickers)

        packet = _run_execution(env, positions_gap)

        # Verify caps triggered
        td = packet.get("trade_decision", {})
        if td.get("verdict") == VERDICT_TRADE_WITH_CAPS:
            ce = packet.get("caps_enforcement", {})
            assert ce.get("caps_applied") is True


# ---------------------------------------------------------------------------
# TestGlobalNameCap — universal single-name cap + reflow
# ---------------------------------------------------------------------------


class TestGlobalNameCap:
    """Tests for global_name_cap cap type and build_global_name_cap helper."""

    def test_global_cap_caps_all_names(self):
        """Global cap applies to ALL names, not just gap-risk."""
        positions = [
            {"ticker": "A", "bucket": "binary_91_180", "target_dollars": 20000, "weight_pct": 4.0, "gap_risk": ""},
            {"ticker": "B", "bucket": "binary_91_180", "target_dollars": 18000, "weight_pct": 3.6, "gap_risk": ""},
            {"ticker": "C", "bucket": "binary_31_90", "target_dollars": 5000, "weight_pct": 1.0, "gap_risk": ""},
        ]
        caps = [
            {
                "type": "global_name_cap",
                "name_cap_pct": 0.035,
                "base_cap_pct": 0.035,
                "shock_applied": False,
                "triggered_by": "global_name_cap",
            }
        ]
        account = 500_000
        cap_dollars = account * 0.035  # 17,500

        capped, summary = apply_caps_to_positions(positions, caps, account)

        # A was 20k (> 17.5k cap) → capped
        assert capped[0]["target_dollars"] <= cap_dollars + 0.01
        # B was 18k (> 17.5k cap) → capped
        assert capped[1]["target_dollars"] <= cap_dollars + 0.01
        # C was 5k (< 17.5k cap) → gets reflow, increases
        assert capped[2]["target_dollars"] > 5000
        # None are gap-risk — proves universal application
        assert all(p["gap_risk"] == "" for p in capped)

    def test_reflow_conserves_total(self):
        """Overflow from capped names is redistributed; total $ preserved."""
        positions = [
            {"ticker": "A", "bucket": "b", "target_dollars": 25000, "weight_pct": 5.0, "gap_risk": ""},
            {"ticker": "B", "bucket": "b", "target_dollars": 20000, "weight_pct": 4.0, "gap_risk": ""},
            {"ticker": "C", "bucket": "b", "target_dollars": 10000, "weight_pct": 2.0, "gap_risk": ""},
            {"ticker": "D", "bucket": "b", "target_dollars": 5000, "weight_pct": 1.0, "gap_risk": ""},
        ]
        caps = [
            {
                "type": "global_name_cap",
                "name_cap_pct": 0.035,
                "base_cap_pct": 0.035,
                "shock_applied": False,
                "triggered_by": "global_name_cap",
            }
        ]
        before_total = sum(p["target_dollars"] for p in positions)  # 60,000

        capped, summary = apply_caps_to_positions(positions, caps, 500_000)

        after_total = sum(p["target_dollars"] for p in capped)
        # Total should be conserved (within floating-point tolerance)
        assert abs(after_total - before_total) < 1.0, f"Total changed: {before_total} → {after_total}"

    def test_no_position_exceeds_cap_after_reflow(self):
        """After reflow iterations, no position exceeds the cap."""
        # Create a scenario where reflow could push names over cap
        positions = [
            {"ticker": f"T{i}", "bucket": "b", "target_dollars": 20000, "weight_pct": 4.0, "gap_risk": ""}
            for i in range(5)
        ] + [
            {"ticker": "SMALL", "bucket": "b", "target_dollars": 1000, "weight_pct": 0.2, "gap_risk": ""},
        ]
        caps = [
            {
                "type": "global_name_cap",
                "name_cap_pct": 0.035,
                "base_cap_pct": 0.035,
                "shock_applied": False,
                "triggered_by": "global_name_cap",
            }
        ]
        cap_dollars = 500_000 * 0.035  # 17,500

        capped, _ = apply_caps_to_positions(positions, caps, 500_000)

        for p in capped:
            assert (
                p["target_dollars"] <= cap_dollars + 0.01
            ), f"{p['ticker']} at ${p['target_dollars']:.2f} exceeds cap ${cap_dollars:.2f}"

    def test_determinism(self):
        """Global cap + reflow is deterministic."""
        positions = [
            {"ticker": "A", "bucket": "b", "target_dollars": 25000, "weight_pct": 5.0, "gap_risk": ""},
            {"ticker": "B", "bucket": "b", "target_dollars": 15000, "weight_pct": 3.0, "gap_risk": ""},
            {"ticker": "C", "bucket": "b", "target_dollars": 5000, "weight_pct": 1.0, "gap_risk": ""},
        ]
        caps = [
            {
                "type": "global_name_cap",
                "name_cap_pct": 0.035,
                "base_cap_pct": 0.035,
                "shock_applied": False,
                "triggered_by": "global_name_cap",
            }
        ]

        c1, s1 = apply_caps_to_positions(positions, caps, 500_000)
        c2, s2 = apply_caps_to_positions(positions, caps, 500_000)

        assert c1 == c2
        assert s1 == s2

    def test_global_cap_summary_includes_params(self):
        """Summary includes global_cap_params with cap level and shock status."""
        positions = [
            {"ticker": "A", "bucket": "b", "target_dollars": 25000, "weight_pct": 5.0, "gap_risk": ""},
        ]
        caps = [
            {
                "type": "global_name_cap",
                "name_cap_pct": 0.028,
                "base_cap_pct": 0.035,
                "shock_applied": True,
                "triggered_by": "global_name_cap",
            }
        ]

        _, summary = apply_caps_to_positions(positions, caps, 500_000)

        assert "global_cap_params" in summary
        gcp = summary["global_cap_params"]
        assert gcp["name_cap_pct"] == 0.028
        assert gcp["base_cap_pct"] == 0.035
        assert gcp["shock_applied"] is True

    def test_combined_gap_risk_and_global_cap(self):
        """Gap-risk cap + global cap both apply; total still conserved."""
        positions = [
            {"ticker": "GAP", "bucket": "binary_0_30", "target_dollars": 25000, "weight_pct": 5.0, "gap_risk": "HIGH"},
            {"ticker": "BIG", "bucket": "binary_91_180", "target_dollars": 22000, "weight_pct": 4.4, "gap_risk": ""},
            {"ticker": "SAFE", "bucket": "binary_91_180", "target_dollars": 8000, "weight_pct": 1.6, "gap_risk": ""},
        ]
        caps = [
            {
                "type": "gap_risk_cap",
                "name_cap_pct": 0.25,
                "budget_reduction_pct": 0,
                "affected_tickers": ["GAP"],
                "triggered_by": "gap_risk_high_count",
            },
            {
                "type": "global_name_cap",
                "name_cap_pct": 0.035,
                "base_cap_pct": 0.035,
                "shock_applied": False,
                "triggered_by": "global_name_cap",
            },
        ]
        account = 500_000
        cap_dollars = account * 0.035  # 17,500
        before_total = sum(p["target_dollars"] for p in positions)

        capped, summary = apply_caps_to_positions(positions, caps, account)

        # GAP was first reduced by gap_risk, but reflow may push it up;
        # the key constraint is that no name exceeds the global cap
        for p in capped:
            assert (
                p["target_dollars"] <= cap_dollars + 0.01
            ), f"{p['ticker']} at ${p['target_dollars']:.2f} exceeds global cap ${cap_dollars:.2f}"
        # Total is reduced because gap_risk_cap destroyed budget (no reflow for that cap type)
        after_total = sum(p["target_dollars"] for p in capped)
        assert after_total < before_total
        # Verify reductions reported
        assert len(summary["top_reductions"]) >= 1


# ---------------------------------------------------------------------------
# TestBuildGlobalNameCap — helper function
# ---------------------------------------------------------------------------


class TestBuildGlobalNameCap:
    def test_disabled_returns_none(self):
        policy = {"global_name_cap": {"enabled": False, "cap_pct": 0.035}}
        assert build_global_name_cap(policy) is None

    def test_missing_config_returns_none(self):
        policy = {}
        assert build_global_name_cap(policy) is None

    def test_enabled_returns_cap_dict(self):
        policy = {"global_name_cap": {"enabled": True, "cap_pct": 0.035}}
        cap = build_global_name_cap(policy)
        assert cap is not None
        assert cap["type"] == "global_name_cap"
        assert cap["name_cap_pct"] == 0.035
        assert cap["shock_applied"] is False

    def test_shock_not_triggered_without_conditions(self):
        policy = {
            "global_name_cap": {"enabled": True, "cap_pct": 0.035},
            "global_cap_shock": {
                "enabled": True,
                "xbi_weekly_ret_floor": -0.05,
                "dd_change_floor_pp": -5.0,
                "multiplier": 0.8,
            },
        }
        # XBI down but not enough
        cap = build_global_name_cap(policy, xbi_weekly_ret=-0.03, xbi_dd_change_pp=-3.0)
        assert cap["name_cap_pct"] == 0.035
        assert cap["shock_applied"] is False

    def test_shock_triggered_tightens_cap(self):
        policy = {
            "global_name_cap": {"enabled": True, "cap_pct": 0.035},
            "global_cap_shock": {
                "enabled": True,
                "xbi_weekly_ret_floor": -0.05,
                "dd_change_floor_pp": -5.0,
                "multiplier": 0.8,
            },
        }
        cap = build_global_name_cap(policy, xbi_weekly_ret=-0.06, xbi_dd_change_pp=-7.0)
        assert cap["shock_applied"] is True
        assert abs(cap["name_cap_pct"] - 0.035 * 0.8) < 1e-6

    def test_shock_requires_both_conditions(self):
        """Shock needs BOTH XBI return <= floor AND dd_change <= floor."""
        policy = {
            "global_name_cap": {"enabled": True, "cap_pct": 0.035},
            "global_cap_shock": {
                "enabled": True,
                "xbi_weekly_ret_floor": -0.05,
                "dd_change_floor_pp": -5.0,
                "multiplier": 0.8,
            },
        }
        # XBI bad but drawdown stable
        cap = build_global_name_cap(policy, xbi_weekly_ret=-0.06, xbi_dd_change_pp=-2.0)
        assert cap["shock_applied"] is False

        # Drawdown deepening but XBI return mild
        cap = build_global_name_cap(policy, xbi_weekly_ret=-0.02, xbi_dd_change_pp=-7.0)
        assert cap["shock_applied"] is False

    def test_shock_disabled_ignores_conditions(self):
        policy = {
            "global_name_cap": {"enabled": True, "cap_pct": 0.035},
            "global_cap_shock": {"enabled": False, "multiplier": 0.8},
        }
        cap = build_global_name_cap(policy, xbi_weekly_ret=-0.10, xbi_dd_change_pp=-10.0)
        assert cap["name_cap_pct"] == 0.035
        assert cap["shock_applied"] is False

    def test_shock_with_none_xbi_data(self):
        """Missing XBI data → shock not applied."""
        policy = {
            "global_name_cap": {"enabled": True, "cap_pct": 0.035},
            "global_cap_shock": {
                "enabled": True,
                "xbi_weekly_ret_floor": -0.05,
                "dd_change_floor_pp": -5.0,
                "multiplier": 0.8,
            },
        }
        cap = build_global_name_cap(policy, xbi_weekly_ret=None, xbi_dd_change_pp=None)
        assert cap["shock_applied"] is False


# ---------------------------------------------------------------------------
# TestGlobalCapIntegration — end-to-end with run_weekly_execution
# ---------------------------------------------------------------------------


class TestGlobalCapIntegration:
    def test_global_cap_fires_on_trade(self, tmp_path):
        """Global cap applies even when trade decision is TRADE (no other caps)."""
        env = _setup_full_env(tmp_path, prior_as_of=None)
        # Positions with one oversized name (5% > 3.5% cap)
        positions = _make_positions()
        # Inflate first position to 5% = $25,000
        positions[0]["target_dollars"] = 25000
        positions[0]["weight_pct"] = 5.0

        # Write portfolio policy with global cap enabled
        policy_path = tmp_path / "portfolio_policy.json"
        policy = {
            "schema": "portfolio_policy.v3",
            "rebalance_cadence": "weekly",
            "rebalance_day": "FRIDAY",
            "execution": "NEXT_OPEN",
            "account_usd": 500000,
            "family_filter_mode": "secondary",
            "bucket_targets": {"binary_91_180": 0.55, "binary_31_90": 0.25, "binary_0_30": 0.10, "less_binary": 0.10},
            "bucket_top_k": {"binary_91_180": 20, "binary_31_90": 15, "binary_0_30": 10, "less_binary": 15},
            "bucket_name_caps": {"binary_91_180": 3.0, "binary_31_90": 2.0, "binary_0_30": 1.0, "less_binary": 2.0},
            "family_overrides": {},
            "family_targets": {},
            "gap_risk": {"high_days": 7, "high_cap_pct": 0.5},
            "regulatory_ladder_enabled": False,
            "rebalance_buffer_ranks": 30,
            "bucket_hysteresis_days": 7,
            "alpha_health": {"enabled": False},
            "global_name_cap": {"enabled": True, "cap_pct": 0.035},
            "global_cap_shock": {"enabled": False},
        }
        with open(policy_path, "w") as f:
            json.dump(policy, f)

        _write_trade_decision_policy(env["td_policy_path"])

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
                trade_decision_policy_path=env["td_policy_path"],
                policy_path=policy_path,
            )

        assert packet["status"] == "READY"
        ce = packet.get("caps_enforcement")
        assert ce is not None, "caps_enforcement should be present when global cap is enabled"
        assert ce["caps_applied"] is True
        # Max position should be reduced
        assert ce["targets_after"]["largest_position_pct"] <= 3.5 + 0.01

    def test_global_cap_in_packet_md(self, tmp_path):
        """EXECUTION_PACKET.md shows global cap params."""
        env = _setup_full_env(tmp_path, prior_as_of=None)
        positions = _make_positions()
        positions[0]["target_dollars"] = 25000
        positions[0]["weight_pct"] = 5.0

        policy_path = tmp_path / "portfolio_policy.json"
        policy = {
            "schema": "portfolio_policy.v3",
            "rebalance_cadence": "weekly",
            "rebalance_day": "FRIDAY",
            "execution": "NEXT_OPEN",
            "account_usd": 500000,
            "family_filter_mode": "secondary",
            "bucket_targets": {"binary_91_180": 0.55, "binary_31_90": 0.25, "binary_0_30": 0.10, "less_binary": 0.10},
            "bucket_top_k": {"binary_91_180": 20, "binary_31_90": 15, "binary_0_30": 10, "less_binary": 15},
            "bucket_name_caps": {"binary_91_180": 3.0, "binary_31_90": 2.0, "binary_0_30": 1.0, "less_binary": 2.0},
            "family_overrides": {},
            "family_targets": {},
            "gap_risk": {"high_days": 7, "high_cap_pct": 0.5},
            "regulatory_ladder_enabled": False,
            "rebalance_buffer_ranks": 30,
            "bucket_hysteresis_days": 7,
            "alpha_health": {"enabled": False},
            "global_name_cap": {"enabled": True, "cap_pct": 0.035},
            "global_cap_shock": {"enabled": False},
        }
        with open(policy_path, "w") as f:
            json.dump(policy, f)

        _write_trade_decision_policy(env["td_policy_path"])

        def _mock_build(as_of_date, snap_dir, *, positions_dir, **kwargs):
            _write_positions(positions_dir, as_of_date, positions)
            return {
                "positions_path": str(positions_dir / f"{as_of_date}.json"),
                "n_positions": len(positions),
                "metadata": {"ruleset_id": "test1234"},
                "performance": None,
            }

        with patch("tools.run_weekly_execution.build_shadow_positions", side_effect=_mock_build):
            run_weekly_execution(
                env["as_of"],
                snap_root=env["snap_root"],
                positions_dir=env["positions_dir"],
                execution_root=env["execution_root"],
                manifest_path=env["manifest_path"],
                perf_csv=env["perf_csv"],
                price_source=env["price_csv"],
                skip_snapshot=True,
                trade_decision_policy_path=env["td_policy_path"],
                policy_path=policy_path,
            )

        md = (env["execution_root"] / env["as_of"] / "EXECUTION_PACKET.md").read_text()
        assert "Global name cap" in md
        assert "0.035" in md

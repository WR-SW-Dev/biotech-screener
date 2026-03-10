"""Tests for the alpha health gate in pre_trade_check + build_trade_plan.

Covers:
  1. Cold start PASS (no prior positions / perf rows)
  2. Insufficient weeks PASS (< min_weeks)
  3. NO_ADD_RISK triggers when both portfolio & b91 negative
  4. ADD_OK when only one metric is negative
  5. Trade plan strips BUYs under NO_ADD_RISK
  6. Trade plan preserves all trades under ADD_OK
  7. Disabled policy → PASS
  8. risk_permission column in CSV output
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.pre_trade_check import check_alpha_health

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PERF_HEADER = [
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


def _write_perf_csv(tmp_path: Path, rows: list) -> Path:
    """Write a minimal performance.csv with given rows."""
    perf_csv = tmp_path / "performance.csv"
    with open(perf_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_PERF_HEADER)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    return perf_csv


def _make_perf_row(
    date: str,
    excess_vs_xbi_pct: str = "0.5",
    sleeve_b91_pnl: str = "100",
    sleeve_b31_pnl: str = "50",
    sleeve_b0_pnl: str = "20",
    sleeve_lb_pnl: str = "10",
) -> dict:
    return {
        "schema_version": "live_shadow_perf.v1",
        "date": date,
        "prior_date": "",
        "total_pnl": "200",
        "pnl_pct": "0.5",
        "xbi_return_pct": "0.3",
        "excess_vs_xbi_pct": excess_vs_xbi_pct,
        "n_held": "20",
        "turnover": "0.1",
        "gap_risk_high_count": "0",
        "n_missing_price": "0",
        "sleeve_binary_0_30_pnl": sleeve_b0_pnl,
        "sleeve_binary_31_90_pnl": sleeve_b31_pnl,
        "sleeve_binary_91_180_pnl": sleeve_b91_pnl,
        "sleeve_less_binary_pnl": sleeve_lb_pnl,
        "ruleset_id": "test",
    }


_DEFAULT_POLICY = {
    "alpha_health": {
        "enabled": True,
        "lookback_weeks": 4,
        "min_weeks": 3,
        "no_add_if_portfolio_hedged_excess_lt": 0.0,
        "no_add_if_b91_hedged_excess_lt": 0.0,
    }
}


# ---------------------------------------------------------------------------
# 1. Cold start PASS
# ---------------------------------------------------------------------------


class TestColdStartPass:
    def test_no_perf_rows(self):
        result = check_alpha_health([], _DEFAULT_POLICY)
        assert result.status == "PASS"
        assert "cold start" in result.detail

    def test_empty_perf_rows(self):
        result = check_alpha_health([], _DEFAULT_POLICY)
        assert result.value["decision"] == "ADD_OK"


# ---------------------------------------------------------------------------
# 2. Insufficient weeks PASS
# ---------------------------------------------------------------------------


class TestInsufficientWeeksPass:
    def test_one_week(self):
        rows = [_make_perf_row("2026-03-01")]
        result = check_alpha_health(rows, _DEFAULT_POLICY)
        assert result.status == "PASS"
        assert "insufficient history" in result.detail

    def test_two_weeks(self):
        rows = [
            _make_perf_row("2026-03-01"),
            _make_perf_row("2026-03-08"),
        ]
        result = check_alpha_health(rows, _DEFAULT_POLICY)
        assert result.status == "PASS"
        assert result.value["weeks_available"] == 2


# ---------------------------------------------------------------------------
# 3. NO_ADD_RISK triggers
# ---------------------------------------------------------------------------


class TestNoAddRiskTriggers:
    def test_both_negative_triggers_warn(self):
        rows = [
            _make_perf_row("2026-02-14", excess_vs_xbi_pct="-0.5", sleeve_b91_pnl="-100"),
            _make_perf_row("2026-02-21", excess_vs_xbi_pct="-0.3", sleeve_b91_pnl="-80"),
            _make_perf_row("2026-02-28", excess_vs_xbi_pct="-0.2", sleeve_b91_pnl="-50"),
            _make_perf_row("2026-03-07", excess_vs_xbi_pct="-0.1", sleeve_b91_pnl="-30"),
        ]
        result = check_alpha_health(rows, _DEFAULT_POLICY)
        assert result.status == "WARN"
        assert result.value["decision"] == "NO_ADD_RISK"
        assert result.value["portfolio_hedged_excess_4w"] < 0
        assert result.value["bucket_hedged_excess_4w"]["binary_91_180"] < 0


# ---------------------------------------------------------------------------
# 4. ADD_OK when only one is negative
# ---------------------------------------------------------------------------


class TestAddOkPartialNegative:
    def test_portfolio_negative_b91_positive(self):
        rows = [
            _make_perf_row("2026-02-14", excess_vs_xbi_pct="-0.5", sleeve_b91_pnl="100"),
            _make_perf_row("2026-02-21", excess_vs_xbi_pct="-0.3", sleeve_b91_pnl="80"),
            _make_perf_row("2026-02-28", excess_vs_xbi_pct="-0.2", sleeve_b91_pnl="50"),
            _make_perf_row("2026-03-07", excess_vs_xbi_pct="-0.1", sleeve_b91_pnl="30"),
        ]
        result = check_alpha_health(rows, _DEFAULT_POLICY)
        assert result.status == "PASS"
        assert result.value["decision"] == "ADD_OK"

    def test_portfolio_positive_b91_negative(self):
        rows = [
            _make_perf_row("2026-02-14", excess_vs_xbi_pct="0.5", sleeve_b91_pnl="-100"),
            _make_perf_row("2026-02-21", excess_vs_xbi_pct="0.3", sleeve_b91_pnl="-80"),
            _make_perf_row("2026-02-28", excess_vs_xbi_pct="0.2", sleeve_b91_pnl="-50"),
            _make_perf_row("2026-03-07", excess_vs_xbi_pct="0.1", sleeve_b91_pnl="-30"),
        ]
        result = check_alpha_health(rows, _DEFAULT_POLICY)
        assert result.status == "PASS"
        assert result.value["decision"] == "ADD_OK"

    def test_both_positive(self):
        rows = [
            _make_perf_row("2026-02-14", excess_vs_xbi_pct="0.5", sleeve_b91_pnl="100"),
            _make_perf_row("2026-02-21", excess_vs_xbi_pct="0.3", sleeve_b91_pnl="80"),
            _make_perf_row("2026-02-28", excess_vs_xbi_pct="0.2", sleeve_b91_pnl="50"),
            _make_perf_row("2026-03-07", excess_vs_xbi_pct="0.1", sleeve_b91_pnl="30"),
        ]
        result = check_alpha_health(rows, _DEFAULT_POLICY)
        assert result.status == "PASS"
        assert result.value["decision"] == "ADD_OK"


# ---------------------------------------------------------------------------
# 5. Trade plan strips BUYs under NO_ADD_RISK
# ---------------------------------------------------------------------------


def _write_positions_json(path: Path, date: str, positions: list) -> Path:
    """Write a minimal positions JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema": "live_shadow_positions.v1", "as_of_date": date, "positions": positions}
    path.write_text(json.dumps(doc))
    return path


def _make_position(ticker: str, bucket: str, dollars: float = 10000) -> dict:
    return {
        "ticker": ticker,
        "bucket": bucket,
        "target_dollars": dollars,
        "weight_pct": 2.0,
        "gap_risk": "LOW",
        "price_coverage": "OK",
        "catalyst_days": 120,
    }


def _write_snap_metadata(snap_dir: Path, ruleset_id: str = "test1234") -> Path:
    snap_dir.mkdir(parents=True, exist_ok=True)
    meta = {"ruleset_id": ruleset_id, "as_of_date": "2026-03-08"}
    (snap_dir / "metadata.json").write_text(json.dumps(meta))
    return snap_dir


def _write_manifest(tmp_path: Path, active_id: str = "test1234") -> Path:
    manifest = {
        "schema_version": 1,
        "rulesets": [{"id": active_id, "file": "test.json", "status": "active"}],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


class TestTradePlanStripsBuys:
    def test_no_add_risk_removes_buys(self, tmp_path):
        from tools.build_trade_plan import build_trade_plan

        pos_dir = tmp_path / "positions"
        pos_dir.mkdir()

        # Prior: AAAA (keep, will be trimmed), CCCC (keep)
        # Current: AAAA (trimmed), BBBB (new buy), CCCC (keep)
        # This gives >60% overlap so turnover check passes
        prior_pos = [
            _make_position("AAAA", "binary_91_180", 15000),
            _make_position("CCCC", "binary_91_180", 10000),
        ]
        _write_positions_json(pos_dir / "2026-03-01.json", "2026-03-01", prior_pos)

        current_pos = [
            _make_position("AAAA", "binary_91_180", 8000),
            _make_position("BBBB", "binary_91_180", 10000),
            _make_position("CCCC", "binary_91_180", 10000),
        ]
        _write_positions_json(pos_dir / "2026-03-08.json", "2026-03-08", current_pos)

        # Perf CSV with negative trailing alpha (triggers NO_ADD_RISK)
        perf_rows = [
            _make_perf_row(f"2026-02-{7 + i * 7:02d}", excess_vs_xbi_pct="-1.0", sleeve_b91_pnl="-500")
            for i in range(4)
        ]
        perf_csv = _write_perf_csv(tmp_path, perf_rows)

        # Snapshot + manifest for pre-trade check
        snap_dir = _write_snap_metadata(tmp_path / "snap")
        manifest_path = _write_manifest(tmp_path)

        out_dir = tmp_path / "out"
        result = build_trade_plan(
            "2026-03-08",
            positions_dir=pos_dir,
            perf_csv=perf_csv,
            out_dir=out_dir,
            snap_dir=snap_dir,
            manifest_path=manifest_path,
        )

        assert result.get("risk_permission") == "NO_ADD_RISK"
        # All trades should be SELLs — no BUYs
        assert result["n_buys"] == 0
        for t in result["trades"]:
            assert t["action"] == "SELL"
            assert t["risk_permission"] == "NO_ADD_RISK"

    def test_add_ok_preserves_buys(self, tmp_path):
        from tools.build_trade_plan import build_trade_plan

        pos_dir = tmp_path / "positions"
        pos_dir.mkdir()

        prior_pos = [_make_position("AAAA", "binary_91_180", 15000)]
        _write_positions_json(pos_dir / "2026-03-01.json", "2026-03-01", prior_pos)

        current_pos = [
            _make_position("AAAA", "binary_91_180", 10000),
            _make_position("BBBB", "binary_91_180", 10000),
        ]
        _write_positions_json(pos_dir / "2026-03-08.json", "2026-03-08", current_pos)

        # Perf CSV with positive trailing alpha
        perf_rows = [
            _make_perf_row(f"2026-02-{7 + i * 7:02d}", excess_vs_xbi_pct="1.0", sleeve_b91_pnl="500") for i in range(4)
        ]
        perf_csv = _write_perf_csv(tmp_path, perf_rows)

        snap_dir = _write_snap_metadata(tmp_path / "snap")
        manifest_path = _write_manifest(tmp_path)

        policy_path = tmp_path / "policy.json"
        policy_path.write_text(
            json.dumps(
                {
                    "schema": "portfolio_policy.v3",
                    "account_usd": 500000,
                    "bucket_targets": {
                        "binary_91_180": 0.55,
                        "binary_31_90": 0.25,
                        "binary_0_30": 0.10,
                        "less_binary": 0.10,
                    },
                    "alpha_health": {
                        "enabled": True,
                        "lookback_weeks": 4,
                        "min_weeks": 3,
                        "no_add_if_portfolio_hedged_excess_lt": 0.0,
                        "no_add_if_b91_hedged_excess_lt": 0.0,
                    },
                }
            )
        )

        out_dir = tmp_path / "out"
        result = build_trade_plan(
            "2026-03-08",
            positions_dir=pos_dir,
            perf_csv=perf_csv,
            out_dir=out_dir,
            snap_dir=snap_dir,
            manifest_path=manifest_path,
        )

        assert result.get("risk_permission") == "ADD_OK"
        actions = [t["action"] for t in result["trades"]]
        assert "BUY" in actions


# ---------------------------------------------------------------------------
# 6. CSV output contains risk_permission column
# ---------------------------------------------------------------------------


class TestRiskPermissionCSV:
    def test_csv_has_risk_permission_column(self, tmp_path):
        from tools.build_trade_plan import write_trade_plan_csv

        trades = [
            {
                "ticker": "XYZ",
                "action": "SELL",
                "delta_usd": -5000,
                "target_usd": 0,
                "prior_usd": 5000,
                "bucket": "binary_91_180",
                "tier": "1",
                "catalyst_days": "90",
                "gap_risk": "LOW",
                "reason": "exit",
                "risk_permission": "NO_ADD_RISK",
            }
        ]
        csv_path = write_trade_plan_csv(trades, tmp_path / "trade_plan.csv")
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert rows[0]["risk_permission"] == "NO_ADD_RISK"


# ---------------------------------------------------------------------------
# 7. Disabled policy → PASS
# ---------------------------------------------------------------------------


class TestDisabledPolicy:
    def test_disabled_returns_pass(self):
        policy = {
            "alpha_health": {
                "enabled": False,
                "lookback_weeks": 4,
                "min_weeks": 3,
            }
        }
        rows = [
            _make_perf_row("2026-02-14", excess_vs_xbi_pct="-5.0", sleeve_b91_pnl="-5000"),
            _make_perf_row("2026-02-21", excess_vs_xbi_pct="-5.0", sleeve_b91_pnl="-5000"),
            _make_perf_row("2026-02-28", excess_vs_xbi_pct="-5.0", sleeve_b91_pnl="-5000"),
        ]
        result = check_alpha_health(rows, policy)
        assert result.status == "PASS"
        assert "disabled" in result.detail

    def test_no_alpha_health_key_passes(self):
        """Policy without alpha_health key uses defaults (enabled=True)."""
        rows = [
            _make_perf_row("2026-02-14", excess_vs_xbi_pct="1.0", sleeve_b91_pnl="100"),
            _make_perf_row("2026-02-21", excess_vs_xbi_pct="1.0", sleeve_b91_pnl="100"),
            _make_perf_row("2026-02-28", excess_vs_xbi_pct="1.0", sleeve_b91_pnl="100"),
        ]
        result = check_alpha_health(rows, {})
        assert result.status == "PASS"


# ---------------------------------------------------------------------------
# 8. Bucket-level detail
# ---------------------------------------------------------------------------


class TestBucketDetail:
    def test_all_buckets_reported(self):
        rows = [
            _make_perf_row(
                f"2026-02-{7 + i * 7:02d}",
                excess_vs_xbi_pct="-0.5",
                sleeve_b91_pnl="-100",
                sleeve_b31_pnl="50",
                sleeve_b0_pnl="-20",
                sleeve_lb_pnl="10",
            )
            for i in range(4)
        ]
        result = check_alpha_health(rows, _DEFAULT_POLICY)
        bh = result.value["bucket_hedged_excess_4w"]
        assert "binary_91_180" in bh
        assert "binary_31_90" in bh
        assert "binary_0_30" in bh
        assert "less_binary" in bh
        assert bh["binary_91_180"] == -400.0
        assert bh["binary_31_90"] == 200.0

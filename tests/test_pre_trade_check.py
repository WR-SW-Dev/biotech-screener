"""Tests for pre_trade_check.py — pre-trade sanity gate.

Validates:
  1. Provenance check (ruleset_id, as_of_date)
  2. Bucket deviation detection
  3. Missing price flagging
  4. Gap-risk concentration
  5. Turnover threshold
  6. Overall PASS/WARN/FAIL + can_trade
  7. JSON + MD output
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _pos(ticker, dollars, bucket="binary_91_180", gap_risk="", price_coverage="OK"):
    return {
        "ticker": ticker,
        "target_dollars": dollars,
        "bucket": bucket,
        "gap_risk": gap_risk,
        "price_coverage": price_coverage,
        "tier": "A",
        "catalyst_days": "",
        "actionable_rank": 1,
        "weight_pct": 5.0,
        "reason": "",
    }


def _write_positions(path, as_of_date, positions):
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"as_of_date": as_of_date, "positions": positions}
    with open(path, "w") as f:
        json.dump(doc, f)


def _write_manifest(tmp_path, active_id="abc"):
    """Write a mock ruleset manifest with the given active ID."""
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "rulesets": [{"id": active_id, "file": "active.json", "status": "active"}],
            }
        )
    )
    return manifest_path


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class TestProvenance:
    def test_pass_with_metadata(self, tmp_path):
        from tools.pre_trade_check import check_provenance

        snap = tmp_path / "snap"
        snap.mkdir()
        (snap / "metadata.json").write_text(json.dumps({"ruleset_id": "abc123", "as_of_date": "2026-03-08"}))
        r = check_provenance(snap)
        assert r.status == "PASS"

    def test_fail_missing_metadata(self, tmp_path):
        from tools.pre_trade_check import check_provenance

        snap = tmp_path / "snap"
        snap.mkdir()
        r = check_provenance(snap)
        assert r.status == "FAIL"

    def test_fail_missing_ruleset_id(self, tmp_path):
        from tools.pre_trade_check import check_provenance

        snap = tmp_path / "snap"
        snap.mkdir()
        (snap / "metadata.json").write_text(json.dumps({"as_of_date": "2026-03-08"}))
        r = check_provenance(snap)
        assert r.status == "FAIL"
        assert "ruleset_id" in r.detail


# ---------------------------------------------------------------------------
# Bucket deviation
# ---------------------------------------------------------------------------


class TestBucketDeviation:
    def test_pass_within_threshold(self):
        from tools.pre_trade_check import check_bucket_deviation

        positions = [_pos(f"T{i}", 25000) for i in range(20)]  # all in binary_91_180
        policy = {
            "account_usd": 500_000,
            "bucket_targets": {
                "binary_91_180": 1.0,
                "binary_0_30": 0.0,
                "binary_31_90": 0.0,
                "less_binary": 0.0,
            },
        }
        r = check_bucket_deviation(positions, policy, max_deviation_pct=5.0)
        assert r.status == "PASS"

    def test_fail_exceeds_threshold(self):
        from tools.pre_trade_check import check_bucket_deviation

        positions = [_pos(f"T{i}", 25000) for i in range(20)]  # 500k all in binary_91_180
        policy = {
            "account_usd": 500_000,
            "bucket_targets": {
                "binary_91_180": 0.50,  # expect 50%, have 100%
                "binary_0_30": 0.25,
                "binary_31_90": 0.25,
            },
        }
        r = check_bucket_deviation(positions, policy, max_deviation_pct=3.0)
        assert r.status == "FAIL"


# ---------------------------------------------------------------------------
# Missing prices
# ---------------------------------------------------------------------------


class TestMissingPrices:
    def test_pass_all_ok(self):
        from tools.pre_trade_check import check_missing_prices

        positions = [_pos("AAPL", 5000), _pos("GOOG", 3000)]
        r = check_missing_prices(positions, max_missing=2)
        assert r.status == "PASS"

    def test_warn_some_missing(self):
        from tools.pre_trade_check import check_missing_prices

        positions = [_pos("AAPL", 5000, price_coverage="MISSING"), _pos("GOOG", 3000)]
        r = check_missing_prices(positions, max_missing=2)
        assert r.status == "WARN"

    def test_fail_too_many_missing(self):
        from tools.pre_trade_check import check_missing_prices

        positions = [
            _pos("AAPL", 5000, price_coverage="MISSING"),
            _pos("GOOG", 3000, price_coverage="MISSING"),
            _pos("MSFT", 2000, price_coverage="MISSING"),
        ]
        r = check_missing_prices(positions, max_missing=2)
        assert r.status == "FAIL"
        assert "3 missing" in r.detail


# ---------------------------------------------------------------------------
# Gap-risk concentration
# ---------------------------------------------------------------------------


class TestGapRiskConcentration:
    def test_pass_below_cap(self):
        from tools.pre_trade_check import check_gap_risk_concentration

        positions = [
            _pos("AAPL", 5000, gap_risk="HIGH"),
            _pos("GOOG", 45000),
        ]
        policy = {"account_usd": 500_000}
        r = check_gap_risk_concentration(positions, policy, max_gap_high_pct=10.0)
        assert r.status == "PASS"

    def test_fail_exceeds_cap(self):
        from tools.pre_trade_check import check_gap_risk_concentration

        positions = [_pos(f"T{i}", 10000, gap_risk="HIGH") for i in range(10)]  # 100k of 500k = 20%
        policy = {"account_usd": 500_000}
        r = check_gap_risk_concentration(positions, policy, max_gap_high_pct=10.0)
        assert r.status == "FAIL"
        assert "20.0%" in r.detail


# ---------------------------------------------------------------------------
# Turnover
# ---------------------------------------------------------------------------


class TestTurnover:
    def test_pass_low_turnover(self):
        from tools.pre_trade_check import check_turnover

        prior = [_pos(f"T{i}", 5000) for i in range(20)]
        current = [_pos(f"T{i}", 5000) for i in range(20)]
        r = check_turnover(current, prior, max_turnover_pct=40.0)
        assert r.status == "PASS"
        assert r.value == 0.0

    def test_fail_high_turnover(self):
        from tools.pre_trade_check import check_turnover

        prior = [_pos(f"T{i}", 5000) for i in range(20)]
        current = [_pos(f"T{i}", 5000) for i in range(10, 30)]  # 50% overlap
        r = check_turnover(current, prior, max_turnover_pct=40.0)
        assert r.status == "FAIL"
        assert r.value == 50.0

    def test_first_snapshot_passes(self):
        from tools.pre_trade_check import check_turnover

        current = [_pos("AAPL", 5000)]
        r = check_turnover(current, [], max_turnover_pct=40.0)
        assert r.status == "PASS"


# ---------------------------------------------------------------------------
# Overall result + can_trade
# ---------------------------------------------------------------------------


class TestOverallResult:
    def test_all_pass(self, tmp_path):
        from tools.pre_trade_check import run_pre_trade_check

        pos_dir = tmp_path / "positions"
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [
                _pos("AAPL", 5000),
                _pos("GOOG", 3000),
            ],
        )
        snap = tmp_path / "snap"
        snap.mkdir()
        (snap / "metadata.json").write_text(json.dumps({"ruleset_id": "abc", "as_of_date": "2026-03-08"}))
        manifest = _write_manifest(tmp_path, active_id="abc")

        result = run_pre_trade_check(
            "2026-03-08",
            positions_dir=pos_dir,
            snap_dir=snap,
            deviation_max_pct=100,  # won't fail
            manifest_path=manifest,
        )
        assert result.overall == "PASS"
        assert result.can_trade is True

    def test_fail_blocks_trade(self, tmp_path):
        from tools.pre_trade_check import run_pre_trade_check

        pos_dir = tmp_path / "positions"
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [
                _pos("AAPL", 5000, price_coverage="MISSING"),
                _pos("GOOG", 3000, price_coverage="MISSING"),
                _pos("MSFT", 2000, price_coverage="MISSING"),
            ],
        )
        snap = tmp_path / "snap"
        snap.mkdir()
        (snap / "metadata.json").write_text(json.dumps({"ruleset_id": "abc", "as_of_date": "2026-03-08"}))

        result = run_pre_trade_check(
            "2026-03-08",
            positions_dir=pos_dir,
            snap_dir=snap,
            max_missing_prices=2,
            deviation_max_pct=100,
        )
        assert result.overall == "FAIL"
        assert result.can_trade is False

    def test_no_positions_fails(self, tmp_path):
        from tools.pre_trade_check import run_pre_trade_check

        result = run_pre_trade_check("2026-03-08", positions_dir=tmp_path / "positions")
        assert result.overall == "FAIL"
        assert result.can_trade is False


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------


class TestOutput:
    def test_json_output(self, tmp_path):
        from tools.pre_trade_check import PreTradeResult, write_pre_trade_json

        result = PreTradeResult(
            as_of_date="2026-03-08",
            overall="PASS",
            can_trade=True,
            checks=[{"name": "test", "status": "PASS", "detail": "ok", "value": None, "threshold": None}],
        )
        path = write_pre_trade_json(result, tmp_path / "pre_trade.json")
        data = json.loads(path.read_text())
        assert data["schema"] == SCHEMA_VERSION
        assert data["can_trade"] is True
        assert len(data["checks"]) == 1

    def test_md_output(self, tmp_path):
        from tools.pre_trade_check import PreTradeResult, write_pre_trade_md

        result = PreTradeResult(
            as_of_date="2026-03-08",
            overall="FAIL",
            can_trade=False,
            checks=[
                {"name": "provenance", "status": "PASS", "detail": "ok", "value": None, "threshold": None},
                {"name": "missing_prices", "status": "FAIL", "detail": "3 missing", "value": 3, "threshold": 2},
            ],
        )
        path = write_pre_trade_md(result, tmp_path / "pre_trade.md")
        text = path.read_text()
        assert "Pre-Trade Checklist" in text
        assert "BLOCKED" in text
        assert "[FAIL]" in text
        assert "[PASS]" in text


# ---------------------------------------------------------------------------
# Pre-trade gate blocks trade plan
# ---------------------------------------------------------------------------


class TestPreTradeBlocksTradePlan:
    def test_fail_blocks_trade_plan(self, tmp_path):
        from tools.build_trade_plan import build_trade_plan

        pos_dir = tmp_path / "positions"
        # 3 missing prices → FAIL (max_missing=2)
        positions = [
            _pos("AAPL", 5000, price_coverage="MISSING"),
            _pos("GOOG", 3000, price_coverage="MISSING"),
            _pos("MSFT", 2000, price_coverage="MISSING"),
        ]
        _write_positions(pos_dir / "2026-03-08.json", "2026-03-08", positions)
        snap = tmp_path / "snap"
        snap.mkdir()
        (snap / "metadata.json").write_text(json.dumps({"ruleset_id": "abc", "as_of_date": "2026-03-08"}))

        result = build_trade_plan(
            "2026-03-08",
            positions_dir=pos_dir,
            perf_csv=tmp_path / "perf.csv",
            min_trade_usd=100,
            out_dir=tmp_path / "out",
        )
        assert result.get("can_trade") is False
        assert "error" in result
        # Pre-trade artifacts should still be written
        assert (tmp_path / "out" / "pre_trade.json").is_file()
        assert (tmp_path / "out" / "pre_trade.md").is_file()
        # Trade plan CSV should NOT exist (blocked before write)
        assert not (tmp_path / "out" / "trade_plan.csv").is_file()

    def test_pass_allows_trade_plan(self, tmp_path):
        from tools.build_trade_plan import build_trade_plan

        pos_dir = tmp_path / "positions"
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [
                _pos("AAPL", 5000),
                _pos("GOOG", 3000),
            ],
        )

        result = build_trade_plan(
            "2026-03-08",
            positions_dir=pos_dir,
            perf_csv=tmp_path / "perf.csv",
            min_trade_usd=100,
            out_dir=tmp_path / "out",
            skip_pre_trade_check=True,
        )
        assert "error" not in result
        assert result["n_buys"] >= 0
        assert (tmp_path / "out" / "trade_plan.csv").is_file()


# Use SCHEMA_VERSION from module
from tools.pre_trade_check import SCHEMA_VERSION  # noqa: E402

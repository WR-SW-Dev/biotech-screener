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


def _pos(ticker, dollars, bucket="binary_91_180", gap_risk="", price_coverage="OK", weight_pct=5.0):
    return {
        "ticker": ticker,
        "target_dollars": dollars,
        "bucket": bucket,
        "gap_risk": gap_risk,
        "price_coverage": price_coverage,
        "tier": "A",
        "catalyst_days": "",
        "actionable_rank": 1,
        "weight_pct": weight_pct,
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
                _pos("AAPL", 5000, weight_pct=50.0),
                _pos("GOOG", 3000, weight_pct=50.0),
            ],
        )
        snap = tmp_path / "snap"
        snap.mkdir()
        (snap / "metadata.json").write_text(
            json.dumps(
                {
                    "ruleset_id": "abc",
                    "as_of_date": "2026-03-08",
                    "source_reliability": {
                        "table_loaded": True,
                        "table_buckets": 5,
                        "action_counts": {"ALLOW": 10},
                    },
                }
            )
        )
        manifest = _write_manifest(tmp_path, active_id="abc")

        # Empty perf CSV so alpha_health check gets cold-start PASS
        perf_csv = tmp_path / "performance.csv"
        perf_csv.write_text("")

        result = run_pre_trade_check(
            "2026-03-08",
            positions_dir=pos_dir,
            snap_dir=snap,
            deviation_max_pct=100,  # won't fail
            manifest_path=manifest,
            perf_csv=perf_csv,
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
        manifest = _write_manifest(tmp_path, active_id="abc")

        result = run_pre_trade_check(
            "2026-03-08",
            positions_dir=pos_dir,
            snap_dir=snap,
            max_missing_prices=2,
            deviation_max_pct=100,
            manifest_path=manifest,
        )
        assert result.overall == "FAIL"
        assert result.can_trade is False

    def test_no_positions_fails(self, tmp_path):
        from tools.pre_trade_check import run_pre_trade_check

        manifest = _write_manifest(tmp_path, active_id="any")
        result = run_pre_trade_check(
            "2026-03-08",
            positions_dir=tmp_path / "positions",
            manifest_path=manifest,
        )
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
        manifest = _write_manifest(tmp_path, active_id="abc")

        result = build_trade_plan(
            "2026-03-08",
            positions_dir=pos_dir,
            perf_csv=tmp_path / "perf.csv",
            min_trade_usd=100,
            out_dir=tmp_path / "out",
            manifest_path=manifest,
            snap_dir=snap,
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

# ---------------------------------------------------------------------------
# Regression: manifest isolation (guards against production manifest leak)
# ---------------------------------------------------------------------------


class TestManifestIsolation:
    """Regression tests for manifest/fixture isolation.

    These guard against the pattern where tests silently read the real
    production manifest instead of a test-local mock, causing failures
    when the active ruleset ID changes.
    """

    def test_mismatched_manifest_fails_ruleset_check(self, tmp_path):
        """run_pre_trade_check with wrong manifest_path must FAIL on ruleset."""
        from tools.pre_trade_check import run_pre_trade_check

        pos_dir = tmp_path / "positions"
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [_pos("AAPL", 5000), _pos("GOOG", 3000)],
        )
        snap = tmp_path / "snap"
        snap.mkdir()
        (snap / "metadata.json").write_text(json.dumps({"ruleset_id": "deadbeef", "as_of_date": "2026-03-08"}))
        # Manifest has a DIFFERENT active ID
        manifest = _write_manifest(tmp_path, active_id="cafebabe")

        result = run_pre_trade_check(
            "2026-03-08",
            positions_dir=pos_dir,
            snap_dir=snap,
            manifest_path=manifest,
            deviation_max_pct=100,
        )
        assert result.overall == "FAIL"
        # Should fail specifically on ruleset, not on some other check
        ruleset_checks = [c for c in result.checks if c["name"] == "ruleset_active"]
        assert len(ruleset_checks) == 1
        assert ruleset_checks[0]["status"] == "FAIL"

    def test_matching_manifest_passes_ruleset_check(self, tmp_path):
        """run_pre_trade_check with matching manifest_path must PASS ruleset."""
        from tools.pre_trade_check import run_pre_trade_check

        pos_dir = tmp_path / "positions"
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [_pos("AAPL", 5000), _pos("GOOG", 3000)],
        )
        snap = tmp_path / "snap"
        snap.mkdir()
        (snap / "metadata.json").write_text(json.dumps({"ruleset_id": "test1234", "as_of_date": "2026-03-08"}))
        manifest = _write_manifest(tmp_path, active_id="test1234")

        result = run_pre_trade_check(
            "2026-03-08",
            positions_dir=pos_dir,
            snap_dir=snap,
            manifest_path=manifest,
            deviation_max_pct=100,
        )
        ruleset_checks = [c for c in result.checks if c["name"] == "ruleset_active"]
        assert len(ruleset_checks) == 1
        assert ruleset_checks[0]["status"] == "PASS"

    def test_governance_uses_dynamic_pinned_id(self, tmp_path):
        """Pinned ID fallback must use the import, not a hardcoded string."""
        from run_screen import PHASE2_PINNED_RULESET_ID
        from tools.run_daily_production import check_ruleset_governance

        manifest = _write_manifest(tmp_path, active_id=PHASE2_PINNED_RULESET_ID)
        # Write a proper manifest format for governance check
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "rulesets": [
                        {
                            "id": PHASE2_PINNED_RULESET_ID,
                            "file": "active.json",
                            "status": "active",
                        }
                    ],
                }
            )
        )
        result = check_ruleset_governance(None, manifest)
        assert result.status == "PASS"

    def test_pytest_guard_catches_production_default(self, tmp_path):
        """The test-mode guard must fire when using production defaults."""
        from tools.pre_trade_check import run_pre_trade_check

        pos_dir = tmp_path / "positions"
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [_pos("AAPL", 5000)],
        )
        # Omit manifest_path — should raise AssertionError from guard
        import pytest as _pytest

        with _pytest.raises(AssertionError, match="manifest_path"):
            run_pre_trade_check(
                "2026-03-08",
                positions_dir=pos_dir,
                snap_dir=tmp_path / "snap",
            )

    def test_pytest_guard_catches_snap_dir_default(self, tmp_path):
        """The test-mode guard must fire when snap_dir falls to production."""
        from tools.pre_trade_check import run_pre_trade_check

        pos_dir = tmp_path / "positions"
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [_pos("AAPL", 5000)],
        )
        manifest = _write_manifest(tmp_path, active_id="abc")
        import pytest as _pytest

        # snap_dir=None should raise because it would fall to SNAPSHOTS_ROOT
        with _pytest.raises(AssertionError, match="snap_dir"):
            run_pre_trade_check(
                "2026-03-08",
                positions_dir=pos_dir,
                manifest_path=manifest,
            )


# ---------------------------------------------------------------------------
# AST-based meta test: enforce explicit isolation kwargs in all call sites
# ---------------------------------------------------------------------------


class TestIsolationEnforcement:
    """AST-scan to ensure all calls to run_pre_trade_check() and
    build_trade_plan() in test files pass isolation kwargs explicitly.

    This catches the "passes by coincidence" pattern at the source level.
    """

    # Functions that require isolation kwargs, and which kwargs to require
    REQUIRED_KWARGS = {
        "run_pre_trade_check": {"manifest_path", "positions_dir"},
        "build_trade_plan": {"positions_dir"},
    }

    # Calls that are allowed to omit kwargs (e.g., the guard tests themselves)
    ALLOWED_MISSING = {
        # The guard tests intentionally omit kwargs to verify the guard fires
        "test_pytest_guard_catches_production_default",
        "test_pytest_guard_catches_snap_dir_default",
    }

    def _scan_test_file(self, filepath: Path):
        """Parse a test file and find calls missing required kwargs."""
        import ast

        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))

        violations = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            # Get the function name from the call
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr

            if func_name not in self.REQUIRED_KWARGS:
                continue

            # Check if this call is inside an allowed test method
            # Walk up to find the enclosing function
            enclosing = self._find_enclosing_function(tree, node.lineno)
            if enclosing in self.ALLOWED_MISSING:
                continue

            # Check which required kwargs are present
            call_kwargs = {kw.arg for kw in node.keywords if kw.arg is not None}
            required = self.REQUIRED_KWARGS[func_name]
            missing = required - call_kwargs

            if missing:
                violations.append(
                    f"{filepath.name}:{node.lineno} — {func_name}() "
                    f"missing {sorted(missing)} (in {enclosing or '<module>'})"
                )

        return violations

    @staticmethod
    def _find_enclosing_function(tree, lineno: int) -> str:
        """Find the name of the function/method enclosing a given line number."""
        import ast

        enclosing = ""
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Check if lineno falls within this function
                end = getattr(node, "end_lineno", node.lineno + 1000)
                if node.lineno <= lineno <= end:
                    enclosing = node.name
        return enclosing

    def test_all_calls_pass_isolation_kwargs(self):
        """Every call to run_pre_trade_check/build_trade_plan in test files
        must include explicit isolation kwargs (manifest_path, positions_dir).

        If this test fails, a new test was added that omits isolation kwargs.
        Fix: pass manifest_path=..., positions_dir=..., snap_dir=... explicitly.
        """
        test_file = Path(__file__)
        violations = self._scan_test_file(test_file)
        assert not violations, "Found test calls missing required isolation kwargs:\n" + "\n".join(
            f"  {v}" for v in violations
        )


# ---------------------------------------------------------------------------
# Positions integrity check
# ---------------------------------------------------------------------------


class TestPositionsIntegrity:

    def test_valid_positions_pass(self):
        from tools.pre_trade_check import check_positions_integrity

        positions = [
            _pos("AAAA", 25000, weight_pct=25.0),
            _pos("BBBB", 25000, weight_pct=25.0),
            _pos("CCCC", 25000, weight_pct=25.0),
            _pos("DDDD", 25000, weight_pct=25.0),
        ]
        result = check_positions_integrity(positions)
        assert result.status == "PASS"

    def test_duplicate_tickers_fail(self):
        from tools.pre_trade_check import check_positions_integrity

        positions = [
            _pos("AAAA", 50000),
            _pos("AAAA", 50000),  # duplicate
        ]
        result = check_positions_integrity(positions)
        assert result.status == "FAIL"
        assert "Duplicate" in result.detail

    def test_missing_field_fail(self):
        from tools.pre_trade_check import check_positions_integrity

        positions = [{"ticker": "X"}]  # missing bucket, target_dollars
        result = check_positions_integrity(positions)
        assert result.status == "FAIL"
        assert "missing fields" in result.detail

    def test_weight_deviation_warn(self):
        from tools.pre_trade_check import check_positions_integrity

        positions = [
            _pos("AAAA", 25000, weight_pct=90.0),
            _pos("BBBB", 25000, weight_pct=5.0),
        ]
        # weight_sum = 95% → deviation > 1pp
        result = check_positions_integrity(positions)
        assert result.status == "WARN"
        assert "Weight sum" in result.detail


# ---------------------------------------------------------------------------
# Positions validation (build_trade_deltas)
# ---------------------------------------------------------------------------


class TestValidatePositions:

    def test_valid_list(self):
        from tools.build_trade_deltas import validate_positions

        positions = [_pos("A", 1000, weight_pct=50.0), _pos("B", 2000, weight_pct=50.0)]
        assert validate_positions(positions) == []

    def test_empty_list(self):
        from tools.build_trade_deltas import validate_positions

        warnings = validate_positions([])
        assert any("Empty" in w for w in warnings)

    def test_missing_required_fields(self):
        from tools.build_trade_deltas import validate_positions

        warnings = validate_positions([{"ticker": "X"}])
        assert any("missing fields" in w for w in warnings)

    def test_non_numeric_target_dollars(self):
        from tools.build_trade_deltas import validate_positions

        positions = [{"ticker": "X", "bucket": "b", "target_dollars": "abc"}]
        warnings = validate_positions(positions)
        assert any("not numeric" in w for w in warnings)

    def test_negative_target_dollars(self):
        from tools.build_trade_deltas import validate_positions

        positions = [{"ticker": "X", "bucket": "b", "target_dollars": -100}]
        warnings = validate_positions(positions)
        assert any("negative" in w for w in warnings)

    def test_duplicate_tickers(self):
        from tools.build_trade_deltas import validate_positions

        positions = [_pos("SAME", 1000), _pos("SAME", 2000)]
        warnings = validate_positions(positions)
        assert any("Duplicate" in w for w in warnings)

    def test_load_validates_by_default(self, tmp_path):
        import json

        from tools.build_trade_deltas import load_positions_json

        bad_pos = [{"ticker": "X"}]  # missing bucket, target_dollars
        path = tmp_path / "test.json"
        path.write_text(json.dumps({"as_of_date": "2026-01-01", "positions": bad_pos}))
        import pytest

        with pytest.raises(ValueError, match="missing fields"):
            load_positions_json(path)

    def test_load_skip_validation(self, tmp_path):
        import json

        from tools.build_trade_deltas import load_positions_json

        bad_pos = [{"ticker": "X"}]
        path = tmp_path / "test.json"
        path.write_text(json.dumps({"as_of_date": "2026-01-01", "positions": bad_pos}))
        # Should not raise when validate=False
        date, positions = load_positions_json(path, validate=False)
        assert date == "2026-01-01"
        assert len(positions) == 1


# ---------------------------------------------------------------------------
# Source reliability gate
# ---------------------------------------------------------------------------


class TestSourceReliabilityGate:

    def _snap_with_reliability(self, tmp_path, rel_meta):
        snap = tmp_path / "snap"
        snap.mkdir()
        metadata = {
            "ruleset_id": "abc",
            "as_of_date": "2026-03-08",
            "source_reliability": rel_meta,
        }
        (snap / "metadata.json").write_text(json.dumps(metadata))
        return snap

    def test_pass_healthy_table(self, tmp_path):
        from tools.pre_trade_check import check_source_reliability

        snap = self._snap_with_reliability(
            tmp_path,
            {
                "table_loaded": True,
                "table_buckets": 10,
                "action_counts": {"ALLOW": 80, "DEMOTE": 15, "SUPPRESS": 5},
            },
        )
        result = check_source_reliability(snap)
        assert result.status == "PASS"

    def test_warn_no_table(self, tmp_path):
        from tools.pre_trade_check import check_source_reliability

        snap = self._snap_with_reliability(
            tmp_path,
            {
                "table_loaded": False,
                "table_buckets": 0,
                "action_counts": {},
            },
        )
        result = check_source_reliability(snap)
        assert result.status == "WARN"

    def test_warn_high_suppress(self, tmp_path):
        from tools.pre_trade_check import check_source_reliability

        snap = self._snap_with_reliability(
            tmp_path,
            {
                "table_loaded": True,
                "table_buckets": 10,
                "action_counts": {"ALLOW": 20, "SUPPRESS": 80},
            },
        )
        result = check_source_reliability(snap)
        assert result.status == "WARN"
        assert "High SUPPRESS" in result.detail

    def test_warn_no_metadata(self, tmp_path):
        from tools.pre_trade_check import check_source_reliability

        snap = tmp_path / "empty_snap"
        snap.mkdir()
        result = check_source_reliability(snap)
        assert result.status == "WARN"

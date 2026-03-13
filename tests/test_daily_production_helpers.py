"""Unit tests for untested helpers in tools/run_daily_production.py.

Covers: _parse_cache_date, _find_prior_snapshot, _compute_drift_metrics,
check_cache_health, append_gate_verdict, DriftThresholds, _write_drift_report_md.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from run_daily_production import (
    DriftThresholds,
    _compute_drift_metrics,
    _find_prior_snapshot,
    _parse_cache_date,
    _write_drift_report_md,
    append_gate_verdict,
    check_cache_health,
    check_options_coverage,
    check_trading_day,
)

# =============================================================================
# Helpers
# =============================================================================


def _write_rankings_csv(path: Path, rows: list[dict], *, columns: list[str] | None = None) -> None:
    """Write a minimal rankings.csv with given rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if columns is None:
        columns = list(rows[0].keys()) if rows else ["ticker", "actionable_rank", "tier_dev", "eligible"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


# =============================================================================
# _parse_cache_date
# =============================================================================


class TestParseCacheDate:
    def test_valid_filename(self):
        p = Path("trial_records_2026-01-15.json")
        assert _parse_cache_date(p) == date(2026, 1, 15)

    def test_invalid_date(self):
        p = Path("trial_records_not-a-date.json")
        assert _parse_cache_date(p) is None

    def test_empty_stem(self):
        p = Path("trial_records_.json")
        assert _parse_cache_date(p) is None

    def test_different_date(self):
        p = Path("trial_records_2020-03-31.json")
        assert _parse_cache_date(p) == date(2020, 3, 31)


# =============================================================================
# _find_prior_snapshot
# =============================================================================


class TestFindPriorSnapshot:
    def test_finds_most_recent_prior(self, tmp_path):
        for d in ["2026-01-10", "2026-01-11", "2026-01-12"]:
            _write_rankings_csv(
                tmp_path / d / "rankings.csv",
                [{"ticker": "ACME", "actionable_rank": "1", "tier_dev": "A", "eligible": "1"}],
            )
        result = _find_prior_snapshot(tmp_path, "2026-01-12")
        assert result is not None
        assert result.name == "2026-01-11"

    def test_skips_missing_rankings(self, tmp_path):
        # 2026-01-10 has rankings, 2026-01-11 does not
        _write_rankings_csv(
            tmp_path / "2026-01-10" / "rankings.csv",
            [{"ticker": "ACME", "actionable_rank": "1", "tier_dev": "A", "eligible": "1"}],
        )
        (tmp_path / "2026-01-11").mkdir()
        _write_rankings_csv(
            tmp_path / "2026-01-12" / "rankings.csv",
            [{"ticker": "ACME", "actionable_rank": "1", "tier_dev": "A", "eligible": "1"}],
        )
        result = _find_prior_snapshot(tmp_path, "2026-01-12")
        assert result is not None
        assert result.name == "2026-01-10"

    def test_skips_rankings_without_tier_dev(self, tmp_path):
        # Write rankings without tier_dev column
        p = tmp_path / "2026-01-10" / "rankings.csv"
        p.parent.mkdir(parents=True)
        with open(p, "w") as f:
            f.write("ticker,composite_rank,eligible\nACME,1,1\n")
        _write_rankings_csv(
            tmp_path / "2026-01-11" / "rankings.csv",
            [{"ticker": "ACME", "actionable_rank": "1", "tier_dev": "A", "eligible": "1"}],
        )
        result = _find_prior_snapshot(tmp_path, "2026-01-11")
        assert result is None  # 2026-01-10 lacks tier_dev

    def test_returns_none_when_no_prior(self, tmp_path):
        _write_rankings_csv(
            tmp_path / "2026-01-10" / "rankings.csv",
            [{"ticker": "ACME", "actionable_rank": "1", "tier_dev": "A", "eligible": "1"}],
        )
        result = _find_prior_snapshot(tmp_path, "2026-01-10")
        assert result is None

    def test_current_date_not_in_list(self, tmp_path):
        _write_rankings_csv(
            tmp_path / "2026-01-08" / "rankings.csv",
            [{"ticker": "ACME", "actionable_rank": "1", "tier_dev": "A", "eligible": "1"}],
        )
        result = _find_prior_snapshot(tmp_path, "2026-01-10")
        assert result is not None
        assert result.name == "2026-01-08"


# =============================================================================
# _compute_drift_metrics
# =============================================================================


class TestComputeDriftMetrics:
    def _make_csv(self, tmp_path, name, rows, columns=None):
        p = tmp_path / name
        _write_rankings_csv(p, rows, columns=columns)
        return p

    def test_identical_rankings(self, tmp_path):
        rows = [{"ticker": f"T{i}", "actionable_rank": str(i), "tier_dev": "A", "eligible": "1"} for i in range(1, 21)]
        cur = self._make_csv(tmp_path, "current.csv", rows)
        pri = self._make_csv(tmp_path, "prior.csv", rows)
        m = _compute_drift_metrics(cur, pri)
        assert m["top20_overlap_pct"] == 100.0
        assert m["top60_overlap_pct"] == 100.0
        assert m["rank_spearman_rho"] == 1.0
        assert m["mean_abs_rank_delta_top60"] == 0.0
        assert m["tier_migration_count"] == 0
        assert m["eligibility_change_count"] == 0

    def test_completely_different_universes(self, tmp_path):
        cur_rows = [
            {"ticker": f"A{i}", "actionable_rank": str(i), "tier_dev": "A", "eligible": "1"} for i in range(1, 21)
        ]
        pri_rows = [
            {"ticker": f"B{i}", "actionable_rank": str(i), "tier_dev": "A", "eligible": "1"} for i in range(1, 21)
        ]
        cur = self._make_csv(tmp_path, "current.csv", cur_rows)
        pri = self._make_csv(tmp_path, "prior.csv", pri_rows)
        m = _compute_drift_metrics(cur, pri)
        assert m["top20_overlap_pct"] == 0.0
        assert m["n_common_tickers"] == 0

    def test_tier_migration_counted(self, tmp_path):
        cur_rows = [{"ticker": "ACME", "actionable_rank": "1", "tier_dev": "B", "eligible": "1"}]
        pri_rows = [{"ticker": "ACME", "actionable_rank": "1", "tier_dev": "A", "eligible": "1"}]
        cur = self._make_csv(tmp_path, "current.csv", cur_rows)
        pri = self._make_csv(tmp_path, "prior.csv", pri_rows)
        m = _compute_drift_metrics(cur, pri)
        assert m["tier_migration_count"] == 1

    def test_eligibility_change_counted(self, tmp_path):
        cur_rows = [{"ticker": "ACME", "actionable_rank": "1", "tier_dev": "A", "eligible": "0"}]
        pri_rows = [{"ticker": "ACME", "actionable_rank": "1", "tier_dev": "A", "eligible": "1"}]
        cur = self._make_csv(tmp_path, "current.csv", cur_rows)
        pri = self._make_csv(tmp_path, "prior.csv", pri_rows)
        m = _compute_drift_metrics(cur, pri)
        assert m["eligibility_change_count"] == 1

    def test_rank_delta_nonzero(self, tmp_path):
        cur_rows = [
            {"ticker": "ACME", "actionable_rank": "1", "tier_dev": "A", "eligible": "1"},
            {"ticker": "BETA", "actionable_rank": "2", "tier_dev": "A", "eligible": "1"},
        ]
        pri_rows = [
            {"ticker": "ACME", "actionable_rank": "5", "tier_dev": "A", "eligible": "1"},
            {"ticker": "BETA", "actionable_rank": "2", "tier_dev": "A", "eligible": "1"},
        ]
        cur = self._make_csv(tmp_path, "current.csv", cur_rows)
        pri = self._make_csv(tmp_path, "prior.csv", pri_rows)
        m = _compute_drift_metrics(cur, pri)
        assert m["mean_abs_rank_delta_top60"] > 0

    def test_top20_entrants_exits(self, tmp_path):
        # 20 tickers in current, swap one
        cur_rows = [
            {"ticker": f"T{i}", "actionable_rank": str(i), "tier_dev": "A", "eligible": "1"} for i in range(1, 21)
        ]
        pri_rows = [
            {"ticker": f"T{i}", "actionable_rank": str(i), "tier_dev": "A", "eligible": "1"} for i in range(2, 22)
        ]
        cur = self._make_csv(tmp_path, "current.csv", cur_rows)
        pri = self._make_csv(tmp_path, "prior.csv", pri_rows)
        m = _compute_drift_metrics(cur, pri)
        assert "T1" in m["top20_entrants"]
        assert "T21" in m["top20_exits"]

    def test_spearman_rho_reversed(self, tmp_path):
        """Perfectly reversed rankings should give rho ~ -1."""
        n = 20
        cur_rows = [
            {"ticker": f"T{i}", "actionable_rank": str(i), "tier_dev": "A", "eligible": "1"} for i in range(1, n + 1)
        ]
        pri_rows = [
            {"ticker": f"T{i}", "actionable_rank": str(n + 1 - i), "tier_dev": "A", "eligible": "1"}
            for i in range(1, n + 1)
        ]
        cur = self._make_csv(tmp_path, "current.csv", cur_rows)
        pri = self._make_csv(tmp_path, "prior.csv", pri_rows)
        m = _compute_drift_metrics(cur, pri)
        assert m["rank_spearman_rho"] is not None
        assert m["rank_spearman_rho"] < -0.9

    def test_uses_composite_rank_fallback(self, tmp_path):
        """When actionable_rank is absent, should use composite_rank."""
        cur_rows = [{"ticker": "ACME", "composite_rank": "1", "tier_dev": "A", "eligible": "1"}]
        pri_rows = [{"ticker": "ACME", "composite_rank": "1", "tier_dev": "A", "eligible": "1"}]
        cur = self._make_csv(
            tmp_path,
            "current.csv",
            cur_rows,
        )
        pri = self._make_csv(tmp_path, "prior.csv", pri_rows)
        m = _compute_drift_metrics(cur, pri)
        assert m["rank_column_current"] == "composite_rank"


# =============================================================================
# check_cache_health
# =============================================================================


class TestCheckCacheHealth:
    def test_missing_file_passes(self, tmp_path):
        result = check_cache_health(tmp_path)
        assert result.status == "PASS"
        assert "not found" in result.detail

    def test_ok_status_passes(self, tmp_path):
        health = {"overall_status": "ok", "sec8k": {"status": "ok"}, "ctgov": {"status": "ok"}}
        (tmp_path / "cache_health.json").write_text(json.dumps(health))
        result = check_cache_health(tmp_path)
        assert result.status == "PASS"
        assert result.value == "ok"

    def test_degraded_status_warns(self, tmp_path):
        health = {
            "overall_status": "degraded",
            "sec8k": {"status": "stale", "reason": "stale by 3 days"},
            "ctgov": {"status": "ok"},
        }
        (tmp_path / "cache_health.json").write_text(json.dumps(health))
        result = check_cache_health(tmp_path)
        assert result.status == "WARN"
        assert "stale by 3 days" in result.detail

    def test_bad_status_warns_by_default(self, tmp_path):
        health = {
            "overall_status": "bad",
            "sec8k": {"status": "bad", "reason": "missing"},
            "ctgov": {"status": "ok"},
        }
        (tmp_path / "cache_health.json").write_text(json.dumps(health))
        result = check_cache_health(tmp_path)
        assert result.status == "WARN"

    def test_bad_status_fails_when_fail_on_bad(self, tmp_path):
        health = {
            "overall_status": "bad",
            "sec8k": {"status": "bad", "reason": "missing"},
            "ctgov": {"status": "ok"},
        }
        (tmp_path / "cache_health.json").write_text(json.dumps(health))
        result = check_cache_health(tmp_path, fail_on_bad=True)
        assert result.status == "FAIL"

    def test_malformed_json_warns(self, tmp_path):
        (tmp_path / "cache_health.json").write_text("not json{{{")
        result = check_cache_health(tmp_path)
        assert result.status == "WARN"
        assert "Could not read" in result.detail


# =============================================================================
# append_gate_verdict
# =============================================================================


class TestAppendGateVerdict:
    def test_appends_jsonl_row(self, tmp_path, monkeypatch):
        ledger_path = tmp_path / "ledger.jsonl"
        monkeypatch.setattr("run_daily_production.GATE_LEDGER_PATH", ledger_path)

        manifest = {
            "effective_as_of_date": "2026-01-15",
            "generated_at": "2026-01-15T12:00:00",
            "overall_status": "PASS",
            "gates": [
                {"name": "xbi_staleness", "status": "PASS"},
                {"name": "turnover", "status": "WARN"},
            ],
            "ruleset": {"ruleset_hash": "abc123"},
            "git": {"sha": "def456"},
        }
        append_gate_verdict(manifest)

        lines = ledger_path.read_text().strip().split("\n")
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["as_of_date"] == "2026-01-15"
        assert row["overall_status"] == "PASS"
        assert row["n_pass"] == 1
        assert row["n_warn"] == 1
        assert row["n_fail"] == 0
        assert row["gates"]["xbi_staleness"] == "PASS"
        assert row["ruleset_hash"] == "abc123"

    def test_appends_multiple_rows(self, tmp_path, monkeypatch):
        ledger_path = tmp_path / "ledger.jsonl"
        monkeypatch.setattr("run_daily_production.GATE_LEDGER_PATH", ledger_path)

        for i in range(3):
            manifest = {
                "as_of_date": f"2026-01-{10+i}",
                "overall_status": "PASS",
                "gates": [],
            }
            append_gate_verdict(manifest)

        lines = ledger_path.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_missing_optional_fields(self, tmp_path, monkeypatch):
        ledger_path = tmp_path / "ledger.jsonl"
        monkeypatch.setattr("run_daily_production.GATE_LEDGER_PATH", ledger_path)

        manifest = {"overall_status": "PASS", "gates": []}
        append_gate_verdict(manifest)

        row = json.loads(ledger_path.read_text().strip())
        assert row["ruleset_hash"] == ""
        assert row["git_sha"] == ""


# =============================================================================
# DriftThresholds
# =============================================================================


class TestDriftThresholds:
    def test_thresholds_id_deterministic(self):
        t1 = DriftThresholds()
        t2 = DriftThresholds()
        assert t1.thresholds_id == t2.thresholds_id
        assert len(t1.thresholds_id) == 8

    def test_thresholds_id_changes_with_values(self):
        t1 = DriftThresholds()
        t2 = DriftThresholds(warn_top20_overlap_pct=50.0)
        assert t1.thresholds_id != t2.thresholds_id

    def test_to_json_roundtrip(self, tmp_path):
        t = DriftThresholds(warn_top20_overlap_pct=65.0, warn_tier_migration_count=5)
        d = t.to_json()
        assert d["warn_top20_overlap_pct"] == 65.0
        assert d["warn_tier_migration_count"] == 5
        assert "thresholds_id" in d

        # Write and read back
        p = tmp_path / "thresholds.json"
        p.write_text(json.dumps(d))
        t2 = DriftThresholds.from_json(p)
        assert t2.warn_top20_overlap_pct == 65.0
        assert t2.warn_tier_migration_count == 5
        assert t2.thresholds_id == t.thresholds_id

    def test_from_json_ignores_unknown_fields(self, tmp_path):
        d = {"warn_top20_overlap_pct": 60.0, "future_field": True, "thresholds_id": "ignored"}
        p = tmp_path / "thresholds.json"
        p.write_text(json.dumps(d))
        t = DriftThresholds.from_json(p)
        assert t.warn_top20_overlap_pct == 60.0


# =============================================================================
# _write_drift_report_md
# =============================================================================


class TestWriteDriftReportMd:
    def test_writes_markdown_file(self, tmp_path):
        report = {
            "current_date": "2026-01-15",
            "prior_date": "2026-01-14",
            "status": "WARN",
            "thresholds_id": "abc12345",
            "metrics": {
                "top20_overlap_pct": 75.0,
                "top60_overlap_pct": 85.0,
                "rank_spearman_rho": 0.95,
                "mean_abs_rank_delta_top60": 5.0,
                "tier_migration_count": 2,
                "eligibility_change_count": 1,
            },
            "thresholds": {
                "warn_top20_overlap_pct": 70.0,
                "warn_top60_overlap_pct": 80.0,
            },
            "warn_reasons": ["warn_top20_overlap_pct below threshold"],
        }
        out = tmp_path / "drift.md"
        _write_drift_report_md(report, out)
        content = out.read_text()
        assert "# Drift Report" in content
        assert "2026-01-15" in content
        assert "WARN" in content
        assert "75.0" in content

    def test_handles_none_metrics(self, tmp_path):
        report = {
            "current_date": "2026-01-15",
            "prior_date": "2026-01-14",
            "status": "PASS",
            "thresholds_id": "abc12345",
            "metrics": {
                "top20_overlap_pct": None,
                "top60_overlap_pct": None,
                "rank_spearman_rho": None,
                "mean_abs_rank_delta_top60": None,
                "tier_migration_count": None,
                "eligibility_change_count": None,
            },
            "thresholds": {},
            "warn_reasons": [],
        }
        out = tmp_path / "drift.md"
        _write_drift_report_md(report, out)
        content = out.read_text()
        assert "N/A" in content


# =============================================================================
# Trading-day guard
# =============================================================================


class TestCheckTradingDay:
    def test_weekday_passes(self):
        # 2026-03-13 is a Friday
        result = check_trading_day("2026-03-13")
        assert result.status == "PASS"

    def test_saturday_fails(self):
        # 2026-03-14 is a Saturday
        result = check_trading_day("2026-03-14")
        assert result.status == "FAIL"
        assert "Saturday" in result.detail

    def test_sunday_fails(self):
        # 2026-03-15 is a Sunday
        result = check_trading_day("2026-03-15")
        assert result.status == "FAIL"
        assert "Sunday" in result.detail

    def test_monday_passes(self):
        # 2026-03-16 is a Monday
        result = check_trading_day("2026-03-16")
        assert result.status == "PASS"


# =============================================================================
# check_options_coverage
# =============================================================================


class TestCheckOptionsCoverage:
    """Tests for the WARN-only options coverage gate."""

    def _make_rows(self, tmp_path, rows):
        staging = tmp_path / "2026-03-13"
        staging.mkdir(parents=True, exist_ok=True)
        _write_rankings_csv(staging / "rankings.csv", rows)
        return staging

    def test_pass_with_tt_data(self, tmp_path):
        rows = [
            {
                "ticker": "ACME",
                "opt_has_data": "1",
                "options_quality_composite": "0.6000",
                "opt_diagnostic_basis": "tt_market_metrics",
                "catalyst_family": "REGULATORY",
                "catalyst_bucket": "less_binary",
            },
            {
                "ticker": "BETA",
                "opt_has_data": "1",
                "options_quality_composite": "0.4000",
                "opt_diagnostic_basis": "tt_market_metrics",
                "catalyst_family": "CLINICAL",
                "catalyst_bucket": "less_binary",
            },
            {
                "ticker": "GAMA",
                "opt_has_data": "0",
                "options_quality_composite": "",
                "opt_diagnostic_basis": "no_liquid_expiry",
                "catalyst_family": "REGULATORY",
                "catalyst_bucket": "binary",
            },
        ]
        staging = self._make_rows(tmp_path, rows)
        result = check_options_coverage(staging)
        assert result.status == "PASS"
        assert result.value["n_has_data"] == 2
        assert result.value["n_oqc_nonzero"] == 2
        assert result.value["n_regulatory_less_binary_oqc"] == 1
        assert result.value["ab_ready"] is True

    def test_warn_no_credentials(self, tmp_path):
        rows = [
            {
                "ticker": "ACME",
                "opt_has_data": "0",
                "options_quality_composite": "",
                "opt_diagnostic_basis": "no_credentials",
                "catalyst_family": "REGULATORY",
                "catalyst_bucket": "less_binary",
            },
        ]
        staging = self._make_rows(tmp_path, rows)
        result = check_options_coverage(staging)
        assert result.status == "WARN"
        assert "credentials" in result.detail.lower()
        assert result.value["has_credentials"] is False

    def test_warn_zero_data(self, tmp_path):
        rows = [
            {
                "ticker": "ACME",
                "opt_has_data": "0",
                "options_quality_composite": "",
                "opt_diagnostic_basis": "",
                "catalyst_family": "CLINICAL",
                "catalyst_bucket": "less_binary",
            },
        ]
        staging = self._make_rows(tmp_path, rows)
        result = check_options_coverage(staging)
        assert result.status == "WARN"
        assert "zero options data" in result.detail

    def test_warn_data_but_zero_oqc(self, tmp_path):
        rows = [
            {
                "ticker": "ACME",
                "opt_has_data": "1",
                "options_quality_composite": "",
                "opt_diagnostic_basis": "tt_market_metrics",
                "catalyst_family": "REGULATORY",
                "catalyst_bucket": "less_binary",
            },
        ]
        staging = self._make_rows(tmp_path, rows)
        result = check_options_coverage(staging)
        assert result.status == "WARN"
        assert "zero OQC" in result.detail

    def test_pass_no_rankings(self, tmp_path):
        staging = tmp_path / "2026-03-13"
        staging.mkdir(parents=True, exist_ok=True)
        result = check_options_coverage(staging)
        assert result.status == "PASS"

    def test_regulatory_less_binary_count(self, tmp_path):
        rows = [
            {
                "ticker": "REG1",
                "opt_has_data": "1",
                "options_quality_composite": "0.5",
                "opt_diagnostic_basis": "tt_market_metrics",
                "catalyst_family": "REGULATORY",
                "catalyst_bucket": "less_binary",
            },
            {
                "ticker": "REG2",
                "opt_has_data": "1",
                "options_quality_composite": "0.3",
                "opt_diagnostic_basis": "tt_market_metrics",
                "catalyst_family": "REGULATORY",
                "catalyst_bucket": "binary",
            },
            {
                "ticker": "CLIN1",
                "opt_has_data": "1",
                "options_quality_composite": "0.7",
                "opt_diagnostic_basis": "tt_market_metrics",
                "catalyst_family": "CLINICAL",
                "catalyst_bucket": "less_binary",
            },
        ]
        staging = self._make_rows(tmp_path, rows)
        result = check_options_coverage(staging)
        assert result.status == "PASS"
        # Only REG1 is REGULATORY + less_binary with nonzero OQC
        assert result.value["n_regulatory_less_binary_oqc"] == 1
        assert result.value["n_oqc_nonzero"] == 3

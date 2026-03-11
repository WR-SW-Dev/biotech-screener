"""Tests for options diagnostics snapshot writer and analysis scaffold."""

import csv
import json
from pathlib import Path

from common.options_diagnostics import OPTIONS_DIAGNOSTIC_COLUMNS
from common.options_snapshot import SNAPSHOT_SIDECAR_COLUMNS, write_options_snapshot


def _make_row(
    ticker="ACME",
    opt_has_data="1",
    opt_atm_iv="0.85",
    opt_term_slope="-0.15",
    opt_event_premium="YES",
    opt_iv_regime="ELEVATED",
    opt_liquidity_ok="1",
    opt_use_for_judgment="YES",
    catalyst_days="30",
    catalyst_bucket="reg_0_14",
):
    """Build a minimal row dict matching ranked output shape."""
    row = {col: "" for col in OPTIONS_DIAGNOSTIC_COLUMNS}
    row.update(
        {
            "ticker": ticker,
            "catalyst_days": catalyst_days,
            "catalyst_bucket": catalyst_bucket,
            "opt_has_data": opt_has_data,
            "opt_atm_iv": opt_atm_iv,
            "opt_term_slope": opt_term_slope,
            "opt_event_premium": opt_event_premium,
            "opt_iv_regime": opt_iv_regime,
            "opt_liquidity_ok": opt_liquidity_ok,
            "opt_use_for_judgment": opt_use_for_judgment,
        }
    )
    return row


# ---------------------------------------------------------------------------
# 1. write_options_snapshot
# ---------------------------------------------------------------------------


class TestWriteOptionsSnapshot:
    def test_writes_csv_json_md(self, tmp_path):
        snap = tmp_path / "2026-03-11"
        snap.mkdir()
        rows = [_make_row(), _make_row(ticker="BETA", opt_has_data="0")]
        result = write_options_snapshot(snap, rows, "2026-03-11")
        assert result is not None
        assert (snap / "options_diagnostics.csv").exists()
        assert (snap / "options_diagnostics_summary.json").exists()
        assert (snap / "options_diagnostics_summary.md").exists()

    def test_csv_only_includes_data_rows(self, tmp_path):
        snap = tmp_path / "2026-03-11"
        snap.mkdir()
        rows = [
            _make_row(ticker="AAA"),
            _make_row(ticker="BBB", opt_has_data="0"),
            _make_row(ticker="CCC"),
        ]
        write_options_snapshot(snap, rows, "2026-03-11")
        with open(snap / "options_diagnostics.csv", newline="") as f:
            reader = list(csv.DictReader(f))
        assert len(reader) == 2
        assert reader[0]["ticker"] == "AAA"
        assert reader[1]["ticker"] == "CCC"

    def test_csv_columns_match_spec(self, tmp_path):
        snap = tmp_path / "2026-03-11"
        snap.mkdir()
        write_options_snapshot(snap, [_make_row()], "2026-03-11")
        with open(snap / "options_diagnostics.csv", newline="") as f:
            reader = csv.DictReader(f)
            assert list(reader.fieldnames) == SNAPSHOT_SIDECAR_COLUMNS

    def test_empty_rows_returns_none(self, tmp_path):
        snap = tmp_path / "2026-03-11"
        snap.mkdir()
        assert write_options_snapshot(snap, [], "2026-03-11") is None

    def test_no_data_rows_writes_empty_csv(self, tmp_path):
        snap = tmp_path / "2026-03-11"
        snap.mkdir()
        rows = [_make_row(opt_has_data="0")]
        result = write_options_snapshot(snap, rows, "2026-03-11")
        assert result is not None
        with open(snap / "options_diagnostics.csv", newline="") as f:
            reader = list(csv.DictReader(f))
        assert len(reader) == 0

    def test_summary_schema_version(self, tmp_path):
        snap = tmp_path / "2026-03-11"
        snap.mkdir()
        write_options_snapshot(snap, [_make_row()], "2026-03-11")
        summary = json.loads((snap / "options_diagnostics_summary.json").read_text())
        assert summary["schema"] == "options_diagnostics_summary.v1"
        assert summary["as_of_date"] == "2026-03-11"

    def test_summary_coverage(self, tmp_path):
        snap = tmp_path / "2026-03-11"
        snap.mkdir()
        rows = [_make_row(), _make_row(ticker="B", opt_has_data="0")]
        write_options_snapshot(snap, rows, "2026-03-11")
        summary = json.loads((snap / "options_diagnostics_summary.json").read_text())
        cov = summary["coverage"]
        assert cov["n_universe"] == 2
        assert cov["n_with_options_data"] == 1
        assert cov["coverage_pct"] == 50.0

    def test_summary_flag_distributions(self, tmp_path):
        snap = tmp_path / "2026-03-11"
        snap.mkdir()
        rows = [
            _make_row(ticker="A", opt_iv_regime="ELEVATED"),
            _make_row(ticker="B", opt_iv_regime="NORMAL"),
            _make_row(ticker="C", opt_iv_regime="ELEVATED"),
        ]
        write_options_snapshot(snap, rows, "2026-03-11")
        summary = json.loads((snap / "options_diagnostics_summary.json").read_text())
        iv_dist = summary["flag_distributions"]["iv_regime"]
        assert iv_dist["ELEVATED"] == 2
        assert iv_dist["NORMAL"] == 1

    def test_summary_top_backwardation(self, tmp_path):
        snap = tmp_path / "2026-03-11"
        snap.mkdir()
        rows = [
            _make_row(ticker="A", opt_event_premium="YES", opt_term_slope="-0.20"),
            _make_row(ticker="B", opt_event_premium="YES", opt_term_slope="-0.05"),
            _make_row(ticker="C", opt_event_premium="NO", opt_term_slope="0.10"),
        ]
        write_options_snapshot(snap, rows, "2026-03-11")
        summary = json.loads((snap / "options_diagnostics_summary.json").read_text())
        back = summary["top_backwardation"]
        assert len(back) == 2  # only YES
        assert back[0]["ticker"] == "A"  # most negative first

    def test_md_contains_header(self, tmp_path):
        snap = tmp_path / "2026-03-11"
        snap.mkdir()
        write_options_snapshot(snap, [_make_row()], "2026-03-11")
        md = (snap / "options_diagnostics_summary.md").read_text()
        assert "Options Diagnostics Summary" in md
        assert "2026-03-11" in md


# ---------------------------------------------------------------------------
# 2. Analysis scaffold — dataset loader
# ---------------------------------------------------------------------------


class TestLoadOptionsSnapshots:
    def test_loads_across_dates(self, tmp_path):
        from scripts.research.options_prospective_analysis import load_options_snapshots

        for dt in ["2026-03-04", "2026-03-11"]:
            d = tmp_path / dt
            d.mkdir()
            with open(d / "options_diagnostics.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["ticker", "opt_atm_iv"])
                w.writeheader()
                w.writerow({"ticker": "ACME", "opt_atm_iv": "0.85"})

        rows = load_options_snapshots(tmp_path)
        assert len(rows) == 2
        dates = [r["snap_date"] for r in rows]
        assert "2026-03-04" in dates
        assert "2026-03-11" in dates

    def test_date_filters(self, tmp_path):
        from scripts.research.options_prospective_analysis import load_options_snapshots

        for dt in ["2026-03-04", "2026-03-11", "2026-03-18"]:
            d = tmp_path / dt
            d.mkdir()
            with open(d / "options_diagnostics.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["ticker"])
                w.writeheader()
                w.writerow({"ticker": "X"})

        rows = load_options_snapshots(tmp_path, min_date="2026-03-10")
        assert len(rows) == 2

        rows = load_options_snapshots(tmp_path, max_date="2026-03-11")
        assert len(rows) == 2

    def test_empty_dir(self, tmp_path):
        from scripts.research.options_prospective_analysis import load_options_snapshots

        rows = load_options_snapshots(tmp_path)
        assert rows == []

    def test_missing_csv_skipped(self, tmp_path):
        from scripts.research.options_prospective_analysis import load_options_snapshots

        (tmp_path / "2026-03-11").mkdir()
        # No CSV in this dir
        rows = load_options_snapshots(tmp_path)
        assert rows == []

    def test_nonexistent_dir(self):
        from scripts.research.options_prospective_analysis import load_options_snapshots

        rows = load_options_snapshots(Path("/nonexistent/path"))
        assert rows == []


# ---------------------------------------------------------------------------
# 3. Analysis scaffold — forward returns
# ---------------------------------------------------------------------------


class TestForwardReturns:
    def test_basic_return(self):
        from scripts.research.options_prospective_analysis import compute_forward_return

        prices = {"2026-03-10": 100.0, "2026-03-11": 102.0, "2026-03-12": 105.0}
        dates = sorted(prices.keys())
        ret = compute_forward_return(prices, dates, "2026-03-10", 2)
        assert ret is not None
        assert abs(ret - 0.05) < 0.0001

    def test_snap_date_weekend_resolves(self):
        from scripts.research.options_prospective_analysis import compute_forward_return

        prices = {"2026-03-09": 100.0, "2026-03-10": 101.0, "2026-03-11": 103.0}
        dates = sorted(prices.keys())
        # snap_date is 2026-03-08 (Sunday), resolves to 2026-03-09
        ret = compute_forward_return(prices, dates, "2026-03-08", 1)
        assert ret is not None
        assert abs(ret - 0.01) < 0.0001

    def test_insufficient_horizon(self):
        from scripts.research.options_prospective_analysis import compute_forward_return

        prices = {"2026-03-10": 100.0}
        dates = sorted(prices.keys())
        ret = compute_forward_return(prices, dates, "2026-03-10", 5)
        assert ret is None


# ---------------------------------------------------------------------------
# 4. Analysis scaffold — event outcome
# ---------------------------------------------------------------------------


class TestEventOutcome:
    def test_basic_event(self):
        from scripts.research.options_prospective_analysis import resolve_event_outcome

        prices = {
            "2026-03-09": 100.0,
            "2026-03-10": 100.0,
            "2026-03-11": 110.0,  # event day
            "2026-03-12": 112.0,
            "2026-03-13": 115.0,
        }
        dates = sorted(prices.keys())
        result = resolve_event_outcome(prices, dates, "2026-03-10", 1)
        # Event date = 2026-03-10 + 1 day = 2026-03-11
        assert result["event_1d_move"] is not None
        assert result["event_1d_move"] > 0  # 110/100 - 1 = 0.10
        assert result["abs_gap"] is not None

    def test_no_catalyst_days(self):
        from scripts.research.options_prospective_analysis import resolve_event_outcome

        result = resolve_event_outcome({}, [], "2026-03-10", None)
        assert result["event_1d_move"] is None


# ---------------------------------------------------------------------------
# 5. Analysis scaffold — report generator
# ---------------------------------------------------------------------------


class TestReportGenerator:
    def test_insufficient_sample(self):
        from scripts.research.options_prospective_analysis import generate_report

        dataset = [{"snap_date": "2026-03-11", "fwd_ret_5d": 0.01}]
        report = generate_report(dataset, [5], min_snapshots=4)
        assert report["status"] == "insufficient_sample"
        assert "Need 4" in report["message"]

    def test_sufficient_sample(self):
        from scripts.research.options_prospective_analysis import generate_report

        dataset = []
        for i, dt in enumerate(["2026-03-04", "2026-03-11", "2026-03-18", "2026-03-25"]):
            dataset.append(
                {
                    "snap_date": dt,
                    "ticker": "ACME",
                    "opt_event_premium": "YES",
                    "opt_iv_regime": "ELEVATED",
                    "opt_use_for_judgment": "YES",
                    "opt_has_data": "1",
                    "fwd_ret_5d": 0.01 * (i + 1),
                    "fwd_ret_21d": 0.02 * (i + 1),
                    "abs_gap": 0.05,
                    "signed_gap": 0.05,
                }
            )
        report = generate_report(dataset, [5, 21], min_snapshots=4)
        assert report["status"] == "ok"
        assert "fwd_ret_5d" in report["summary_stats"]
        assert "opt_event_premium" in report["flag_splits"]

    def test_report_md_renders(self):
        from scripts.research.options_prospective_analysis import format_report_md, generate_report

        dataset = [
            {
                "snap_date": f"2026-03-{4+i*7:02d}",
                "ticker": "X",
                "opt_event_premium": "YES",
                "opt_iv_regime": "NORMAL",
                "opt_use_for_judgment": "YES",
                "opt_has_data": "1",
                "fwd_ret_5d": 0.01,
            }
            for i in range(5)
        ]
        report = generate_report(dataset, [5], min_snapshots=4)
        md = format_report_md(report)
        assert "Prospective Analysis" in md

    def test_insufficient_sample_md(self):
        from scripts.research.options_prospective_analysis import format_report_md, generate_report

        report = generate_report(
            [{"snap_date": "2026-03-11", "fwd_ret_5d": 0.01}],
            [5],
            min_snapshots=4,
        )
        md = format_report_md(report)
        assert "insufficient" in md.lower() or "Need" in md

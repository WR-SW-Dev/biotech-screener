"""Tests for Data Explorer Agent (tools/data_explorer).

Covers: loading, exploring, comparing, reporting, QA.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from tools.data_explorer.catalog import catalog_summary, discover_artifacts
from tools.data_explorer.comparator import compare_snapshots, schema_diff, score_drift, top_n_overlap
from tools.data_explorer.explorer import gate_counts, missingness, qa_checks, score_distributions, summarize, top_n
from tools.data_explorer.loader import load_csv, load_directory, load_file
from tools.data_explorer.reporter import comparison_report, qa_report, snapshot_report

# ============================================================================
# Fixtures
# ============================================================================


def _make_rankings_csv(path: Path, n: int = 50, date: str = "2026-04-13") -> Path:
    """Write a synthetic rankings.csv."""
    snap_dir = path / date
    snap_dir.mkdir(parents=True, exist_ok=True)
    csv_path = snap_dir / "rankings.csv"

    rows = []
    for i in range(n):
        rows.append(
            {
                "ticker": f"T{i:03d}",
                "actionable_rank": str(i + 1),
                "selector_score": str(round(1.0 - i * 0.01, 4)),
                "final_score": str(round(0.7 - i * 0.005, 4)),
                "ranker_v2_score": str(round(0.7 - i * 0.005, 4)),
                "ranker_v2_rank": str(i + 1),
                "coinvest_score_z": str(round(2.0 - i * 0.03, 4)),
                "inst_delta_z": str(round(1.0 - i * 0.015, 4)),
                "financial_score": str(round(10 + i * 0.5, 2)),
                "clinical_score_v2_z": str(round(0.5 + i * 0.01, 4)),
                "trap_overlay_score": str(round(-0.05 - i * 0.001, 4)),
                "quality_overlay_score": str(round(-0.02 + i * 0.001, 4)),
                "ees_v2_score": str(round(-0.1 + i * 0.002, 4)),
                "ees_eligible": "True" if i < 40 else "False",
                "opt_liquidity_state": "liquid" if i < 35 else "illiquid",
                "ineligible_reasons": "" if i < 40 else "low_score",
                "phase": "3",
                "primary_indication": "oncology",
            }
        )

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    return csv_path


def _make_json_sidecar(snap_dir: Path, name: str, data: dict) -> Path:
    path = snap_dir / name
    with open(path, "w") as f:
        json.dump(data, f)
    return path


def _make_jsonl(path: Path, records: list) -> Path:
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path


# ============================================================================
# Loader tests
# ============================================================================


class TestLoader:
    def test_load_csv(self, tmp_path: Path):
        csv_path = _make_rankings_csv(tmp_path, n=20)
        df = load_csv(csv_path)
        assert len(df) == 20
        assert "ticker" in df.columns

    def test_load_file_csv(self, tmp_path: Path):
        csv_path = _make_rankings_csv(tmp_path, n=15)
        df = load_file(csv_path)
        assert df.attrs["source_format"] == "csv"
        assert len(df) == 15

    def test_load_file_json(self, tmp_path: Path):
        data = [{"ticker": "A", "score": 1.0}, {"ticker": "B", "score": 0.5}]
        path = tmp_path / "test.json"
        path.write_text(json.dumps(data))
        df = load_file(path)
        assert len(df) == 2
        assert df.attrs["source_format"] == "json"

    def test_load_file_json_dict(self, tmp_path: Path):
        data = {"as_of_date": "2026-04-13", "records": [{"a": 1}, {"a": 2}]}
        path = tmp_path / "test.json"
        path.write_text(json.dumps(data))
        df = load_file(path)
        assert len(df) == 2
        assert df.attrs.get("as_of_date") == "2026-04-13"

    def test_load_file_jsonl(self, tmp_path: Path):
        path = _make_jsonl(
            tmp_path / "test.jsonl",
            [{"ticker": "A"}, {"ticker": "B"}, {"ticker": "C"}],
        )
        df = load_file(path)
        assert len(df) == 3
        assert df.attrs["source_format"] == "jsonl"

    def test_load_file_missing(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_file(tmp_path / "nonexistent.csv")

    def test_load_file_unknown_format(self, tmp_path: Path):
        path = tmp_path / "test.xyz"
        path.write_text("data")
        with pytest.raises(ValueError, match="Cannot infer"):
            load_file(path)

    def test_load_directory(self, tmp_path: Path):
        csv_path = _make_rankings_csv(tmp_path, n=10)
        snap_dir = csv_path.parent
        _make_json_sidecar(snap_dir, "cache_health.json", {"status": "ok"})

        result = load_directory(snap_dir)
        assert "rankings" in result
        assert "cache_health" in result
        assert len(result["rankings"]) == 10

    def test_snapshot_date_from_parent(self, tmp_path: Path):
        csv_path = _make_rankings_csv(tmp_path, n=5, date="2026-04-13")
        df = load_file(csv_path)
        assert df.attrs.get("snapshot_date") == "2026-04-13"

    def test_load_jsonl_malformed(self, tmp_path: Path):
        path = tmp_path / "bad.jsonl"
        path.write_text('{"ok": true}\nnot json\n{"also_ok": true}\n')
        df = load_file(path)
        assert len(df) == 2


# ============================================================================
# Explorer tests
# ============================================================================


class TestExplorer:
    def test_summarize(self, tmp_path: Path):
        csv_path = _make_rankings_csv(tmp_path, n=30)
        df = load_file(csv_path)
        s = summarize(df)
        assert s["n_rows"] == 30
        assert "selector_score" in s["key_scores_present"]
        assert "selector_score" in s["score_stats"]

    def test_missingness(self, tmp_path: Path):
        csv_path = _make_rankings_csv(tmp_path, n=20)
        df = load_file(csv_path)
        m = missingness(df)
        assert m["n_rows"] == 20
        assert m["n_columns"] > 0

    def test_missingness_empty(self):
        df = pd.DataFrame()
        m = missingness(df)
        assert m["n_rows"] == 0

    def test_score_distributions(self, tmp_path: Path):
        csv_path = _make_rankings_csv(tmp_path, n=50)
        df = load_file(csv_path)
        dist = score_distributions(df)
        assert "selector_score" in dist
        assert dist["selector_score"]["count"] == 50

    def test_gate_counts(self, tmp_path: Path):
        csv_path = _make_rankings_csv(tmp_path, n=50)
        df = load_file(csv_path)
        g = gate_counts(df)
        assert "ees_eligible" in g
        assert g["ees_eligible"]["pass"] == 40
        assert g["ees_eligible"]["fail"] == 10

    def test_top_n(self, tmp_path: Path):
        csv_path = _make_rankings_csv(tmp_path, n=50)
        df = load_file(csv_path)
        t = top_n(df, n=10)
        assert len(t) == 10
        assert t["ticker"].iloc[0] == "T000"

    def test_top_n_missing_col(self, tmp_path: Path):
        csv_path = _make_rankings_csv(tmp_path, n=10)
        df = load_file(csv_path)
        t = top_n(df, rank_col="nonexistent_rank", n=5)
        assert t.empty

    def test_qa_checks_clean(self, tmp_path: Path):
        csv_path = _make_rankings_csv(tmp_path, n=30)
        df = load_file(csv_path)
        qa = qa_checks(df)
        # Should have no errors (no dupes, all key cols present)
        errors = [i for i in qa["issues"] if i["severity"] == "error"]
        assert len(errors) == 0

    def test_qa_checks_duplicates(self, tmp_path: Path):
        csv_path = _make_rankings_csv(tmp_path, n=10)
        df = load_file(csv_path)
        # Add duplicate
        dupe = df.iloc[0:1].copy()
        df = pd.concat([df, dupe], ignore_index=True)
        qa = qa_checks(df)
        dupe_issues = [i for i in qa["issues"] if i["check"] == "duplicate_tickers"]
        assert len(dupe_issues) == 1

    def test_qa_checks_missing_column(self):
        df = pd.DataFrame({"ticker": ["A", "B"]})
        qa = qa_checks(df)
        missing = [i for i in qa["issues"] if i["check"] == "missing_key_column"]
        assert len(missing) >= 1


# ============================================================================
# Comparator tests
# ============================================================================


class TestComparator:
    def test_top_n_overlap_identical(self, tmp_path: Path):
        csv_path = _make_rankings_csv(tmp_path, n=50)
        df = load_file(csv_path)
        result = top_n_overlap(df, df, n=30)
        assert result["overlap_count"] == 30
        assert result["overlap_pct"] == 100.0
        assert result["n_added"] == 0
        assert result["n_removed"] == 0

    def test_top_n_overlap_different(self, tmp_path: Path):
        csv_a = _make_rankings_csv(tmp_path / "a", n=50, date="2026-04-12")
        csv_b = _make_rankings_csv(tmp_path / "b", n=50, date="2026-04-13")
        df_a = load_file(csv_a)
        df_b = load_file(csv_b)
        # Rename a few tickers in B to create differences
        df_b.loc[0, "ticker"] = "NEW1"
        df_b.loc[1, "ticker"] = "NEW2"
        result = top_n_overlap(df_a, df_b, n=30)
        assert result["overlap_count"] == 28
        assert result["n_added"] == 2
        assert result["n_removed"] == 2

    def test_top_n_overlap_missing_columns(self):
        df = pd.DataFrame({"something": [1, 2, 3]})
        result = top_n_overlap(df, df, n=5)
        assert result["overlap_count"] == 0

    def test_score_drift(self, tmp_path: Path):
        csv_a = _make_rankings_csv(tmp_path / "a", n=20, date="2026-04-12")
        csv_b = _make_rankings_csv(tmp_path / "b", n=20, date="2026-04-13")
        df_a = load_file(csv_a)
        df_b = load_file(csv_b)
        # Change a score in B
        df_b.loc[df_b["ticker"] == "T000", "selector_score"] = "0.5000"
        drift = score_drift(df_a, df_b, columns=["selector_score"])
        changed = [d for d in drift if d["ticker"] == "T000"]
        assert len(changed) == 1
        assert changed[0]["deltas"]["selector_score"]["delta"] == pytest.approx(-0.5, abs=0.01)

    def test_schema_diff_identical(self, tmp_path: Path):
        csv_path = _make_rankings_csv(tmp_path, n=5)
        df = load_file(csv_path)
        result = schema_diff(df, df)
        assert result["n_only_a"] == 0
        assert result["n_only_b"] == 0

    def test_schema_diff_different(self):
        df_a = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
        df_b = pd.DataFrame({"a": [1], "b": [2], "d": [4]})
        result = schema_diff(df_a, df_b)
        assert result["only_in_a"] == ["c"]
        assert result["only_in_b"] == ["d"]

    def test_compare_snapshots(self, tmp_path: Path):
        csv_a = _make_rankings_csv(tmp_path / "a", n=50, date="2026-04-12")
        csv_b = _make_rankings_csv(tmp_path / "b", n=50, date="2026-04-13")
        df_a = load_file(csv_a)
        df_b = load_file(csv_b)
        comp = compare_snapshots(df_a, df_b)
        assert comp["date_a"] == "2026-04-12"
        assert comp["date_b"] == "2026-04-13"
        assert "overlap" in comp
        assert "top_drift" in comp
        assert "schema" in comp


# ============================================================================
# Catalog tests
# ============================================================================


class TestCatalog:
    def test_discover_artifacts(self, tmp_path: Path):
        csv_path = _make_rankings_csv(tmp_path, n=5)
        snap_dir = csv_path.parent
        _make_json_sidecar(snap_dir, "cache_health.json", {})
        _make_json_sidecar(snap_dir, "expectation_error_overlay.json", {})

        artifacts = discover_artifacts(snap_dir)
        assert "rankings.csv" in artifacts
        assert "cache_health.json" in artifacts
        assert artifacts["rankings.csv"]["category"] == "rankings"

    def test_catalog_summary(self, tmp_path: Path):
        csv_path = _make_rankings_csv(tmp_path, n=5)
        snap_dir = csv_path.parent
        _make_json_sidecar(snap_dir, "expression_overlay_summary.json", {})

        cat = catalog_summary(snap_dir)
        assert cat["has_rankings"] is True
        assert cat["has_expression"] is True


# ============================================================================
# Reporter tests
# ============================================================================


class TestReporter:
    def test_snapshot_report(self, tmp_path: Path):
        csv_path = _make_rankings_csv(tmp_path, n=30)
        df = load_file(csv_path)
        s = summarize(df)
        m = missingness(df)
        g = gate_counts(df)
        t = top_n(df, n=10)
        qa = qa_checks(df)

        md = snapshot_report(s, m, g, t, qa)
        assert "Snapshot Summary" in md
        assert "ANALYSIS ONLY" in md
        assert "selector_score" in md

    def test_comparison_report(self, tmp_path: Path):
        csv_a = _make_rankings_csv(tmp_path / "a", n=30, date="2026-04-12")
        csv_b = _make_rankings_csv(tmp_path / "b", n=30, date="2026-04-13")
        df_a = load_file(csv_a)
        df_b = load_file(csv_b)
        comp = compare_snapshots(df_a, df_b)

        md = comparison_report(comp)
        assert "Snapshot Comparison" in md
        assert "ANALYSIS ONLY" in md
        assert "Overlap" in md

    def test_qa_report_clean(self, tmp_path: Path):
        csv_path = _make_rankings_csv(tmp_path, n=20)
        df = load_file(csv_path)
        qa = qa_checks(df)
        md = qa_report(qa)
        assert "QA Report" in md
        assert "ANALYSIS ONLY" in md

    def test_report_markdown_valid(self, tmp_path: Path):
        csv_path = _make_rankings_csv(tmp_path, n=30)
        df = load_file(csv_path)
        s = summarize(df)
        m = missingness(df)
        g = gate_counts(df)
        t = top_n(df, n=10)
        qa = qa_checks(df)

        md = snapshot_report(s, m, g, t, qa)
        # Should be valid markdown (starts with heading, contains tables)
        assert md.startswith("# ")
        assert "| " in md

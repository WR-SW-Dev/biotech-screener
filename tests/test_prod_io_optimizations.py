#!/usr/bin/env python3
"""Tests for production I/O optimizations in run_screen.py / run_daily_production.py.

Covers (all behavior-preserving / additive):
  - _read_price_history_rows: parse-once caching keyed by (path, mtime, size)
  - detect_no_material_input_change: logging-only no-op detector

These guard the production-infrastructure changes only; model/ranker/selector
behavior is covered by the golden-baseline regression suite.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

MINI_PRICE_CSV = REPO_ROOT / "tests" / "fixtures" / "mini_data" / "price_history.csv"


# ---------------------------------------------------------------------------
# Price-history row cache
# ---------------------------------------------------------------------------
class TestPriceHistoryRowCache:
    def test_rows_match_raw_dictreader(self):
        """Cached rows are byte-identical to a direct csv.DictReader pass."""
        import run_screen

        with open(MINI_PRICE_CSV, "r", encoding="utf-8") as fh:
            expected = list(csv.DictReader(fh))
        got = run_screen._read_price_history_rows(MINI_PRICE_CSV)
        assert got == expected, "cached rows must equal raw DictReader output"

    def test_parse_once_then_reuse(self):
        """Second call returns the SAME cached object (no re-parse)."""
        import run_screen

        run_screen._PRICE_HISTORY_ROW_CACHE.clear()
        first = run_screen._read_price_history_rows(MINI_PRICE_CSV)
        second = run_screen._read_price_history_rows(MINI_PRICE_CSV)
        assert first is second, "repeat read should return the cached list object"

    def test_cache_invalidates_on_change(self, tmp_path):
        """A changed file (new mtime/size) is re-parsed, not served stale."""
        import run_screen

        run_screen._PRICE_HISTORY_ROW_CACHE.clear()
        p = tmp_path / "price_history.csv"
        p.write_text("date,ticker,close\n2026-01-02,AAA,10.0\n", encoding="utf-8")
        rows1 = run_screen._read_price_history_rows(p)
        assert len(rows1) == 1
        # Rewrite with an extra row; cache key (mtime/size) changes → re-parse.
        p.write_text("date,ticker,close\n2026-01-02,AAA,10.0\n2026-01-03,BBB,20.0\n", encoding="utf-8")
        rows2 = run_screen._read_price_history_rows(p)
        assert len(rows2) == 2, "changed file must be re-parsed"

    def test_cache_bounded_to_current_file(self, tmp_path):
        """Only the current file is retained (memory stays bounded)."""
        import run_screen

        run_screen._PRICE_HISTORY_ROW_CACHE.clear()
        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        a.write_text("date,ticker,close\n2026-01-02,AAA,10.0\n", encoding="utf-8")
        b.write_text("date,ticker,close\n2026-01-02,BBB,20.0\n", encoding="utf-8")
        run_screen._read_price_history_rows(a)
        run_screen._read_price_history_rows(b)
        assert len(run_screen._PRICE_HISTORY_ROW_CACHE) == 1


# ---------------------------------------------------------------------------
# No-op detector (logging-only)
# ---------------------------------------------------------------------------
class TestNoOpDetection:
    def _make_snapshot(self, root: Path, date_str: str, hashes: dict):
        d = root / date_str
        d.mkdir(parents=True, exist_ok=True)
        (d / "run_manifest.json").write_text(json.dumps({"hashes": hashes}), encoding="utf-8")
        return d

    def test_returns_none_without_prior(self, tmp_path):
        from tools.run_daily_production import detect_no_material_input_change

        out = detect_no_material_input_change(
            "2026-06-28",
            data_dir=tmp_path,
            price_csv=tmp_path / "nope.csv",
            ctgov_cache_dir=tmp_path / "ctgov",
            final_snapshots_dir=tmp_path / "snaps",
        )
        assert out is None

    def test_detects_unchanged_inputs(self, tmp_path, monkeypatch):
        import tools.run_daily_production as m

        snaps = tmp_path / "snaps"
        prior_hashes = {
            "model_hash": "M",
            "universe_hash": "U",
            "price_hash": "P",
            "clinical_hash": "C",
        }
        self._make_snapshot(snaps, "2026-06-27", prior_hashes)
        # Force current input hashes to equal the prior ones.
        monkeypatch.setattr(m, "_compute_provenance_hashes", lambda **kw: dict(prior_hashes, rankings_hash=""))
        out = m.detect_no_material_input_change(
            "2026-06-28",
            data_dir=tmp_path,
            price_csv=tmp_path / "p.csv",
            ctgov_cache_dir=None,
            final_snapshots_dir=snaps,
        )
        assert out is not None
        assert out["no_material_input_change"] is True
        assert out["changed_inputs"] == []
        assert out["compared_against"] == "2026-06-27"

    def test_detects_changed_inputs(self, tmp_path, monkeypatch):
        import tools.run_daily_production as m

        snaps = tmp_path / "snaps"
        self._make_snapshot(snaps, "2026-06-27", {"model_hash": "M", "price_hash": "P"})
        monkeypatch.setattr(
            m, "_compute_provenance_hashes", lambda **kw: {"model_hash": "M", "price_hash": "P2", "rankings_hash": ""}
        )
        out = m.detect_no_material_input_change(
            "2026-06-28",
            data_dir=tmp_path,
            price_csv=tmp_path / "p.csv",
            ctgov_cache_dir=None,
            final_snapshots_dir=snaps,
        )
        assert out["no_material_input_change"] is False
        assert "price_hash" in out["changed_inputs"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

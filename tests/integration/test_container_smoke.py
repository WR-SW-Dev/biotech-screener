"""
Container smoke test: verify the screening pipeline runs end-to-end
and produces well-formed artifacts (rankings.csv, metadata.json).

Exercises run_screening_pipeline() + save_validation_snapshot() with
synthetic fixtures and validates output structure, required columns,
and determinism.
"""

import csv
import json
import shutil
from pathlib import Path

import pytest

from run_screen import VERSION, run_screening_pipeline, save_validation_snapshot

pytestmark = [pytest.mark.slow, pytest.mark.timeout(180)]

_PIPELINE_KWARGS = dict(
    as_of_date="2026-01-15",
    pit_mode="strict",
    enable_enhancements=False,
    enable_short_interest=False,
    enable_coinvest=False,
    no_clinical_filter=True,
    ctgov_cache_dir=False,
)

AS_OF = _PIPELINE_KWARGS["as_of_date"]


def _patch_trial_records(data_dir: Path) -> None:
    trial_path = data_dir / "trial_records.json"
    trials = json.loads(trial_path.read_text())
    for rec in trials:
        if "ticker" not in rec and "sponsor_ticker" in rec:
            rec["ticker"] = rec["sponsor_ticker"]
        if "last_update_posted" not in rec:
            rec["last_update_posted"] = "2026-01-10"
    trial_path.write_text(json.dumps(trials, indent=2))


def _read_rankings(snapshot_dir: Path) -> list[dict]:
    rankings_path = snapshot_dir / "rankings.csv"
    assert rankings_path.exists(), f"rankings.csv not found in {snapshot_dir}"
    with open(rankings_path, newline="") as f:
        return list(csv.DictReader(f))


class TestContainerSmoke:
    @pytest.fixture(autouse=True)
    def _run_pipeline(self, sample_data_dir: Path, tmp_path: Path):
        _patch_trial_records(sample_data_dir)
        self.data_dir = sample_data_dir
        self.result = run_screening_pipeline(data_dir=self.data_dir, **_PIPELINE_KWARGS)
        self.snap_root = tmp_path / "snapshots"
        save_validation_snapshot(
            snapshot_dir=self.snap_root,
            as_of_date=AS_OF,
            results=self.result,
            version=VERSION,
            decision_mode="phase2",
        )
        self.snapshot_dir = self.snap_root / AS_OF

    def test_pipeline_completes(self):
        assert isinstance(self.result, dict)

    def test_rankings_csv_created(self):
        assert (self.snapshot_dir / "rankings.csv").exists()

    def test_required_columns_present(self):
        rows = _read_rankings(self.snapshot_dir)
        assert rows
        columns = set(rows[0].keys())
        required = {
            "ticker",
            "eligible",
            "tier_dev",
            "composite_rank",
            "size_band",
            "catalyst_strength",
            "catalyst_mode",
            "mom_state",
            "sponsor_tier1_count",
        }
        missing = required - columns
        assert not missing, f"Missing required columns: {missing}"

    def test_metadata_created(self):
        assert (self.snapshot_dir / "metadata.json").exists()

    def test_metadata_has_data_sources(self):
        meta = json.loads((self.snapshot_dir / "metadata.json").read_text())
        assert "data_sources" in meta, f"metadata.json missing 'data_sources'. Keys: {list(meta.keys())}"

    def test_row_count_reasonable(self):
        rows = _read_rankings(self.snapshot_dir)
        assert len(rows) >= 3, f"Expected >= 3 rows in rankings.csv, got {len(rows)}"

    def test_eligible_tickers_exist(self):
        rows = _read_rankings(self.snapshot_dir)
        eligible = [r for r in rows if r.get("eligible") == "1"]
        assert len(eligible) >= 1, "No eligible tickers found"

    def test_decision_engine_columns_present(self):
        rows = _read_rankings(self.snapshot_dir)
        assert rows
        columns = set(rows[0].keys())
        de_columns = {"tier_any", "risk_flags", "catalyst_decay_w"}
        missing = de_columns - columns
        assert not missing, f"Missing DE columns: {missing}"

    def test_output_deterministic(self, sample_data_dir: Path, tmp_path: Path):
        rows_a = _read_rankings(self.snapshot_dir)
        tickers_a = sorted(r["ticker"] for r in rows_a)

        dir_b = tmp_path / "run_b"
        shutil.copytree(sample_data_dir, dir_b)
        _patch_trial_records(dir_b)
        result_b = run_screening_pipeline(data_dir=dir_b, **_PIPELINE_KWARGS)
        snap_b = tmp_path / "snap_b"
        save_validation_snapshot(
            snapshot_dir=snap_b,
            as_of_date=AS_OF,
            results=result_b,
            version=VERSION,
            decision_mode="phase2",
        )
        rows_b = _read_rankings(snap_b / AS_OF)
        tickers_b = sorted(r["ticker"] for r in rows_b)

        assert tickers_a == tickers_b, "Non-deterministic: ticker sets differ"

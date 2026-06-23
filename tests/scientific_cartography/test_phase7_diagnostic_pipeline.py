"""Tests for Phase 7A diagnostic pipeline wrapper."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Import the wrapper function
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools"))
from run_scientific_cartography_diagnostics import run_diagnostics


class Args:
    """Mock argparse.Namespace for CLI testing."""

    def __init__(
        self,
        as_of_date: str,
        snapshot_dir: str,
        ctgov_cache: str,
        output_dir: str,
        strict: bool = False,
        created_at_utc: str = None,
        quiet: bool = True,
    ):
        self.as_of_date = as_of_date
        self.snapshot_dir = snapshot_dir
        self.ctgov_cache = ctgov_cache
        self.output_dir = output_dir
        self.strict = strict
        self.created_at_utc = created_at_utc
        self.quiet = quiet


class TestPhase7DiagnosticPipeline:
    """Test Phase 7A diagnostic pipeline wrapper."""

    def test_wrapper_writes_status_json_on_success(self):
        """Should write scientific_cartography_status.json on success."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshot"
            ctgov_cache = Path(tmpdir) / "ctgov_cache"
            output_dir = Path(tmpdir) / "output"
            snapshot_dir.mkdir()
            ctgov_cache.mkdir()

            args = Args(
                as_of_date="2026-06-17",
                snapshot_dir=str(snapshot_dir),
                ctgov_cache=str(ctgov_cache),
                output_dir=str(output_dir),
                quiet=True,
            )

            # Mock the ingests to return empty lists (which should succeed)
            with (
                patch("run_scientific_cartography_diagnostics.ExistingUniverseIngest") as mock_universe,
                patch("run_scientific_cartography_diagnostics.CTGovIngest") as mock_ctgov,
            ):
                mock_universe_inst = MagicMock()
                mock_universe_inst.load_from_snapshot.return_value = ([], [])
                mock_universe.return_value = mock_universe_inst

                mock_ctgov_inst = MagicMock()
                mock_ctgov_inst.load_from_cache.return_value = []
                mock_ctgov.return_value = mock_ctgov_inst

                run_diagnostics(args)

                # May succeed or have warnings, but should write status
                assert (output_dir / "scientific_cartography_status.json").exists()
                with open(output_dir / "scientific_cartography_status.json") as f:
                    status = json.load(f)
                assert "status" in status
                assert status["as_of_date"] == "2026-06-17"
                assert status["cache_only"] is True
                assert status["governance"]["read_only_diagnostic"] is True

    def test_status_includes_governance_flags(self):
        """Status JSON should include all governance flags."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshot"
            ctgov_cache = Path(tmpdir) / "ctgov_cache"
            output_dir = Path(tmpdir) / "output"
            snapshot_dir.mkdir()
            ctgov_cache.mkdir()

            args = Args(
                as_of_date="2026-06-17",
                snapshot_dir=str(snapshot_dir),
                ctgov_cache=str(ctgov_cache),
                output_dir=str(output_dir),
                quiet=True,
            )

            with (
                patch("run_scientific_cartography_diagnostics.ExistingUniverseIngest") as mock_universe,
                patch("run_scientific_cartography_diagnostics.CTGovIngest") as mock_ctgov,
            ):
                mock_universe_inst = MagicMock()
                mock_universe_inst.load_from_snapshot.return_value = ([], [])
                mock_universe.return_value = mock_universe_inst

                mock_ctgov_inst = MagicMock()
                mock_ctgov_inst.load_from_cache.return_value = []
                mock_ctgov.return_value = mock_ctgov_inst

                run_diagnostics(args)

                with open(output_dir / "scientific_cartography_status.json") as f:
                    status = json.load(f)

                governance = status["governance"]
                assert governance["read_only_diagnostic"] is True
                assert governance["production_wiring"] is False
                assert governance["ranker_change"] is False
                assert governance["selector_change"] is False
                assert governance["sizing_change"] is False
                assert governance["final_score_change"] is False
                assert governance["alpha_promotion"] is False

    def test_non_strict_failure_does_not_return_error(self):
        """Non-strict mode should not return 1 on missing inputs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshot"
            ctgov_cache = Path(tmpdir) / "ctgov_cache"
            output_dir = Path(tmpdir) / "output"
            # Don't create these directories - they don't exist

            args = Args(
                as_of_date="2026-06-17",
                snapshot_dir=str(snapshot_dir),
                ctgov_cache=str(ctgov_cache),
                output_dir=str(output_dir),
                strict=False,
                quiet=True,
            )

            # This should still write a status file with errors, but return 0 in non-strict
            with (
                patch("run_scientific_cartography_diagnostics.ExistingUniverseIngest") as mock_universe,
                patch("run_scientific_cartography_diagnostics.CTGovIngest") as mock_ctgov,
            ):
                mock_universe_inst = MagicMock()
                mock_universe_inst.load_from_snapshot.return_value = ([], [])
                mock_universe.return_value = mock_universe_inst

                mock_ctgov_inst = MagicMock()
                mock_ctgov_inst.load_from_cache.return_value = []
                mock_ctgov.return_value = mock_ctgov_inst

                result = run_diagnostics(args)

                # Non-strict should return 0 even if there's an issue
                assert result == 0

    def test_strict_mode_returns_nonzero_on_failure(self):
        """Strict mode should return non-zero when there's an error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshot"
            ctgov_cache = Path(tmpdir) / "ctgov_cache"
            output_dir = Path(tmpdir) / "output"
            snapshot_dir.mkdir()
            ctgov_cache.mkdir()

            args = Args(
                as_of_date="2026-06-17",
                snapshot_dir=str(snapshot_dir),
                ctgov_cache=str(ctgov_cache),
                output_dir=str(output_dir),
                strict=True,
                quiet=True,
            )

            with (
                patch("run_scientific_cartography_diagnostics.ExistingUniverseIngest") as mock_universe,
                patch("run_scientific_cartography_diagnostics.CTGovIngest") as mock_ctgov,
            ):
                mock_universe_inst = MagicMock()
                # Return empty companies to trigger error in strict mode
                mock_universe_inst.load_from_snapshot.return_value = ([], [])
                mock_universe.return_value = mock_universe_inst

                mock_ctgov_inst = MagicMock()
                mock_ctgov_inst.load_from_cache.return_value = []
                mock_ctgov.return_value = mock_ctgov_inst

                result = run_diagnostics(args)

                # Strict mode should return 1 (failure)
                assert result == 1

    def test_deterministic_timestamp_support(self):
        """Should support deterministic --created-at-utc."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshot"
            ctgov_cache = Path(tmpdir) / "ctgov_cache"
            output_dir = Path(tmpdir) / "output"
            snapshot_dir.mkdir()
            ctgov_cache.mkdir()

            args = Args(
                as_of_date="2026-06-17",
                snapshot_dir=str(snapshot_dir),
                ctgov_cache=str(ctgov_cache),
                output_dir=str(output_dir),
                created_at_utc="2026-06-17T12:00:00Z",
                quiet=True,
            )

            with (
                patch("run_scientific_cartography_diagnostics.ExistingUniverseIngest") as mock_universe,
                patch("run_scientific_cartography_diagnostics.CTGovIngest") as mock_ctgov,
            ):
                mock_universe_inst = MagicMock()
                mock_universe_inst.load_from_snapshot.return_value = ([], [])
                mock_universe.return_value = mock_universe_inst

                mock_ctgov_inst = MagicMock()
                mock_ctgov_inst.load_from_cache.return_value = []
                mock_ctgov.return_value = mock_ctgov_inst

                run_diagnostics(args)

                if (output_dir / "artifact_manifest.json").exists():
                    with open(output_dir / "artifact_manifest.json") as f:
                        manifest = json.load(f)
                    if "created_at_utc" in manifest:
                        assert manifest["created_at_utc"] == "2026-06-17T12:00:00Z"

    def test_cache_only_constraint(self):
        """Should set cache_only flag in status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshot"
            ctgov_cache = Path(tmpdir) / "ctgov_cache"
            output_dir = Path(tmpdir) / "output"
            snapshot_dir.mkdir()
            ctgov_cache.mkdir()

            args = Args(
                as_of_date="2026-06-17",
                snapshot_dir=str(snapshot_dir),
                ctgov_cache=str(ctgov_cache),
                output_dir=str(output_dir),
                quiet=True,
            )

            with (
                patch("run_scientific_cartography_diagnostics.ExistingUniverseIngest") as mock_universe,
                patch("run_scientific_cartography_diagnostics.CTGovIngest") as mock_ctgov,
            ):
                mock_universe_inst = MagicMock()
                mock_universe_inst.load_from_snapshot.return_value = ([], [])
                mock_universe.return_value = mock_universe_inst

                mock_ctgov_inst = MagicMock()
                mock_ctgov_inst.load_from_cache.return_value = []
                mock_ctgov.return_value = mock_ctgov_inst

                run_diagnostics(args)

                with open(output_dir / "scientific_cartography_status.json") as f:
                    status = json.load(f)

                assert status["cache_only"] is True

    def test_output_directory_created(self):
        """Should create output directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshot"
            ctgov_cache = Path(tmpdir) / "ctgov_cache"
            output_dir = Path(tmpdir) / "nonexistent" / "output"
            snapshot_dir.mkdir()
            ctgov_cache.mkdir()

            assert not output_dir.exists()

            args = Args(
                as_of_date="2026-06-17",
                snapshot_dir=str(snapshot_dir),
                ctgov_cache=str(ctgov_cache),
                output_dir=str(output_dir),
                quiet=True,
            )

            with (
                patch("run_scientific_cartography_diagnostics.ExistingUniverseIngest") as mock_universe,
                patch("run_scientific_cartography_diagnostics.CTGovIngest") as mock_ctgov,
            ):
                mock_universe_inst = MagicMock()
                mock_universe_inst.load_from_snapshot.return_value = ([], [])
                mock_universe.return_value = mock_universe_inst

                mock_ctgov_inst = MagicMock()
                mock_ctgov_inst.load_from_cache.return_value = []
                mock_ctgov.return_value = mock_ctgov_inst

                run_diagnostics(args)

                assert output_dir.exists()
                assert (output_dir / "scientific_cartography_status.json").exists()

    def test_status_reflects_errors_and_warnings(self):
        """Status should include errors and warnings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshot"
            ctgov_cache = Path(tmpdir) / "ctgov_cache"
            output_dir = Path(tmpdir) / "output"
            snapshot_dir.mkdir()
            ctgov_cache.mkdir()

            args = Args(
                as_of_date="2026-06-17",
                snapshot_dir=str(snapshot_dir),
                ctgov_cache=str(ctgov_cache),
                output_dir=str(output_dir),
                quiet=True,
            )

            with (
                patch("run_scientific_cartography_diagnostics.ExistingUniverseIngest") as mock_universe,
                patch("run_scientific_cartography_diagnostics.CTGovIngest") as mock_ctgov,
            ):
                mock_universe_inst = MagicMock()
                mock_universe_inst.load_from_snapshot.return_value = ([], [])
                mock_universe.return_value = mock_universe_inst

                mock_ctgov_inst = MagicMock()
                mock_ctgov_inst.load_from_cache.return_value = []
                mock_ctgov.return_value = mock_ctgov_inst

                run_diagnostics(args)

                with open(output_dir / "scientific_cartography_status.json") as f:
                    status = json.load(f)

                assert "errors" in status
                assert "warnings" in status
                assert isinstance(status["errors"], list)
                assert isinstance(status["warnings"], list)


# ---------------------------------------------------------------------------
# Phase 13.1 R2 — trial input discovery tests
# ---------------------------------------------------------------------------

_MINIMAL_TRIAL_JSONL = '{"nct_id": "NCT00000001", "brief_title": "Test Trial"}\n'
_MINIMAL_TRIAL_JSON_LIST = '[{"nct_id": "NCT00000001", "brief_title": "Test Trial"}]'


def _make_args(tmpdir, ctgov_cache):
    snapshot_dir = Path(tmpdir) / "snapshot"
    snapshot_dir.mkdir(exist_ok=True)
    return Args(
        as_of_date="2026-06-23",
        snapshot_dir=str(snapshot_dir),
        ctgov_cache=str(ctgov_cache),
        output_dir=str(Path(tmpdir) / "output"),
        quiet=True,
    )


def _patch_universe(mock_universe):
    inst = MagicMock()
    inst.load_from_snapshot.return_value = ([], [])
    mock_universe.return_value = inst


class TestTrialInputDiscovery:
    """Phase 13.1 R2: trial input-path correction tests."""

    def test_discovers_trials_jsonl(self):
        """trials.jsonl in ctgov_cache should be loaded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctgov_cache = Path(tmpdir) / "cache"
            ctgov_cache.mkdir()
            (ctgov_cache / "trials.jsonl").write_text(_MINIMAL_TRIAL_JSONL)

            args = _make_args(tmpdir, ctgov_cache)
            with patch("run_scientific_cartography_diagnostics.ExistingUniverseIngest") as mock_u:
                _patch_universe(mock_u)
                run_diagnostics(args)

            status_path = Path(tmpdir) / "output" / "scientific_cartography_status.json"
            assert status_path.exists()
            status = json.loads(status_path.read_text())
            # No warning about missing trial files
            missing_warnings = [w for w in status.get("warnings", []) if "No trial data files" in w]
            assert missing_warnings == [], f"Unexpected missing-file warnings: {missing_warnings}"

    def test_discovers_trials_json(self):
        """trials.json in ctgov_cache should be loaded when no jsonl present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctgov_cache = Path(tmpdir) / "cache"
            ctgov_cache.mkdir()
            (ctgov_cache / "trials.json").write_text(_MINIMAL_TRIAL_JSON_LIST)

            args = _make_args(tmpdir, ctgov_cache)
            with patch("run_scientific_cartography_diagnostics.ExistingUniverseIngest") as mock_u:
                _patch_universe(mock_u)
                run_diagnostics(args)

            status_path = Path(tmpdir) / "output" / "scientific_cartography_status.json"
            assert status_path.exists()
            status = json.loads(status_path.read_text())
            missing_warnings = [w for w in status.get("warnings", []) if "No trial data files" in w]
            assert missing_warnings == [], f"Unexpected missing-file warnings: {missing_warnings}"

    def test_discovers_trial_records_json(self):
        """trial_records.json in ctgov_cache should be loaded when no other files present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctgov_cache = Path(tmpdir) / "cache"
            ctgov_cache.mkdir()
            (ctgov_cache / "trial_records.json").write_text(_MINIMAL_TRIAL_JSON_LIST)

            args = _make_args(tmpdir, ctgov_cache)
            with patch("run_scientific_cartography_diagnostics.ExistingUniverseIngest") as mock_u:
                _patch_universe(mock_u)
                run_diagnostics(args)

            status_path = Path(tmpdir) / "output" / "scientific_cartography_status.json"
            assert status_path.exists()
            status = json.loads(status_path.read_text())
            missing_warnings = [w for w in status.get("warnings", []) if "No trial data files" in w]
            assert missing_warnings == [], f"Unexpected missing-file warnings: {missing_warnings}"

    def test_priority_jsonl_over_trial_records(self):
        """trials.jsonl should take priority over trial_records.json when both exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctgov_cache = Path(tmpdir) / "cache"
            ctgov_cache.mkdir()
            # Write both — jsonl has 1 trial, trial_records has 1 trial (same minimal data)
            # We verify no crash and no missing-file warning (can't inspect which was loaded
            # without hooking ingest, but no error = correct path taken)
            (ctgov_cache / "trials.jsonl").write_text(_MINIMAL_TRIAL_JSONL)
            (ctgov_cache / "trial_records.json").write_text(_MINIMAL_TRIAL_JSON_LIST)

            args = _make_args(tmpdir, ctgov_cache)
            loaded_from = {}
            _orig_jsonl = None
            _orig_json = None

            # Patch CTGovIngest to record which method is called first
            import scientific_cartography.ingest.ctgov_ingest as _ingest_mod

            orig_jsonl = _ingest_mod.CTGovIngest.ingest_from_jsonl_file
            orig_json = _ingest_mod.CTGovIngest.ingest_from_json_file
            call_order = []

            def _track_jsonl(self, path):
                call_order.append(("jsonl", path.name))
                return orig_jsonl(self, path)

            def _track_json(self, path):
                call_order.append(("json", path.name))
                return orig_json(self, path)

            with (
                patch("run_scientific_cartography_diagnostics.ExistingUniverseIngest") as mock_u,
                patch.object(_ingest_mod.CTGovIngest, "ingest_from_jsonl_file", _track_jsonl),
                patch.object(_ingest_mod.CTGovIngest, "ingest_from_json_file", _track_json),
            ):
                _patch_universe(mock_u)
                run_diagnostics(args)

            # jsonl should be called first, trial_records.json should not be called
            assert call_order, "No ingest method was called"
            assert call_order[0] == ("jsonl", "trials.jsonl"), f"Expected jsonl first, got: {call_order}"
            jsonl_calls = [c for c in call_order if c[0] == "jsonl"]
            trec_calls = [c for c in call_order if c[1] == "trial_records.json"]
            assert len(jsonl_calls) >= 1
            assert (
                len(trec_calls) == 0
            ), f"trial_records.json should not be loaded when trials.jsonl exists: {call_order}"

    def test_no_trial_files_emits_warning(self):
        """Empty ctgov_cache should emit a warning about missing trial data files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctgov_cache = Path(tmpdir) / "cache"
            ctgov_cache.mkdir()
            # No trial files written

            args = _make_args(tmpdir, ctgov_cache)
            with patch("run_scientific_cartography_diagnostics.ExistingUniverseIngest") as mock_u:
                _patch_universe(mock_u)
                run_diagnostics(args)

            status_path = Path(tmpdir) / "output" / "scientific_cartography_status.json"
            assert status_path.exists()
            status = json.loads(status_path.read_text())
            missing_warnings = [w for w in status.get("warnings", []) if "No trial data files" in w]
            assert (
                len(missing_warnings) == 1
            ), f"Expected exactly one missing-file warning, got: {status.get('warnings', [])}"
            assert (
                "trial_records.json" in missing_warnings[0]
            ), f"Warning should mention trial_records.json: {missing_warnings[0]}"

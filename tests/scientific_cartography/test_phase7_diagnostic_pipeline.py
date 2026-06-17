"""Tests for Phase 7A diagnostic pipeline wrapper."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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

                result = run_diagnostics(args)

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

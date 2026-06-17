"""Tests for Phase 6 artifact export layer."""

import json
import tempfile
from pathlib import Path

import pytest

from scientific_cartography.export import ArtifactManifestExporter, DiseaseMapExporter, MapIndexExporter
from scientific_cartography.schemas.cluster_schema import CompetitiveClusterRecord
from scientific_cartography.schemas.landscape_feature_schema import LandscapeFeatureRecord
from scientific_cartography.schemas.program_schema import ProgramRecord


class TestMapIndexExporter:
    """Test map index exporter."""

    @pytest.fixture
    def exporter(self):
        return MapIndexExporter(as_of_date="2026-06-16")

    def _make_program(self, program_id, disease_id=None, mechanism_class=None, ticker=None, source_refs=None):
        return ProgramRecord(
            program_id=program_id,
            asset_id=f"A_{program_id}",
            asset_name=f"Drug_{program_id}",
            disease_id=disease_id or "",
            disease_name="Alzheimer's" if disease_id else "",
            mechanism_class=mechanism_class,
            modality="small molecule" if mechanism_class else None,
            target="JAK" if mechanism_class else None,
            ticker=ticker,
            company_name="Company",
            source_refs=source_refs or [],
            as_of_date="2026-06-16",
        )

    def test_builds_map_index(self, exporter):
        """Should build map index from records."""
        programs = [self._make_program("P1", disease_id="DOID_001", mechanism_class="JAK inhibitor", ticker="ABC")]
        clusters = []
        features = []

        index = exporter.build_index(programs, clusters, features)

        assert index["as_of_date"] == "2026-06-16"
        assert index["artifact_type"] == "scientific_cartography_map_index"
        assert index["counts"]["program_records"] == 1
        assert index["counts"]["ticker_count"] == 1
        assert index["counts"]["known_mechanism_programs"] == 1

    def test_aggregates_diseases(self, exporter):
        """Should aggregate by disease."""
        programs = [
            self._make_program("P1", disease_id="DOID_001"),
            self._make_program("P2", disease_id="DOID_001"),
            self._make_program("P3", disease_id="DOID_002"),
        ]

        index = exporter.build_index(programs, [], [])

        assert index["counts"]["disease_count"] == 2
        assert len(index["diseases"]) == 2

    def test_preserves_unknown_disease(self, exporter):
        """Should preserve unknown disease bucket."""
        # Create program with truly unknown disease
        program = ProgramRecord(
            program_id="P1",
            asset_id="A1",
            asset_name="Drug",
            disease_id="",  # Empty disease_id
            disease_name="",  # Empty disease_name
            company_name="Company",
            source_refs=["NCT001"],
            as_of_date="2026-06-16",
        )

        index = exporter.build_index([program], [], [])

        # Should have unknown disease entry
        assert len(index["diseases"]) > 0
        # At least one disease bucket should exist
        assert any(d["program_count"] > 0 for d in index["diseases"])

    def test_includes_governance_flags(self, exporter):
        """Should include governance flags."""
        index = exporter.build_index([], [], [])

        assert index["governance"]["production_wiring"] is False
        assert index["governance"]["ranker_change"] is False
        assert index["governance"]["final_score_change"] is False

    def test_deterministic_disease_ordering(self, exporter):
        """Should order diseases deterministically."""
        programs = [
            self._make_program("P1", disease_id="DOID_002"),
            self._make_program("P2", disease_id="DOID_001"),
        ]

        index1 = exporter.build_index(programs, [], [])
        index2 = exporter.build_index(programs, [], [])

        assert [d["disease_id"] for d in index1["diseases"]] == [d["disease_id"] for d in index2["diseases"]]

    def test_writes_map_index(self, exporter):
        """Should write map index to JSON."""
        programs = [self._make_program("P1", disease_id="DOID_001")]
        index = exporter.build_index(programs, [], [])

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "map_index.json"
            exporter.write_index(index, output_path)

            assert output_path.exists()
            with open(output_path) as f:
                loaded = json.load(f)
            assert loaded["artifact_type"] == "scientific_cartography_map_index"


class TestDiseaseMapExporter:
    """Test disease map exporter."""

    @pytest.fixture
    def exporter(self):
        return DiseaseMapExporter(as_of_date="2026-06-16")

    def _make_program(self, program_id, disease_id=None, mechanism_class=None, asset_name=None):
        return ProgramRecord(
            program_id=program_id,
            asset_id=f"A_{program_id}",
            asset_name=asset_name or f"Drug_{program_id}",
            disease_id=disease_id or "",
            disease_name="Alzheimer's" if disease_id else "",
            mechanism_class=mechanism_class,
            modality="small molecule" if mechanism_class else None,
            target="JAK" if mechanism_class else None,
            company_name="Company",
            source_refs=["NCT001"],
            as_of_date="2026-06-16",
        )

    def test_builds_disease_summary(self, exporter):
        """Should build disease summary."""
        programs = [self._make_program("P1", disease_id="DOID_001", mechanism_class="JAK inhibitor")]
        summary = exporter.build_disease_summary(programs, [], [])

        assert summary["artifact_type"] == "scientific_cartography_disease_summary"
        assert len(summary["diseases"]) == 1
        assert summary["diseases"][0]["program_count"] == 1

    def test_includes_mechanism_classes(self, exporter):
        """Should include mechanism classes."""
        programs = [
            self._make_program("P1", disease_id="DOID_001", mechanism_class="JAK inhibitor"),
            self._make_program("P2", disease_id="DOID_001", mechanism_class="IL-13 mAb"),
        ]
        summary = exporter.build_disease_summary(programs, [], [])

        mechanisms = summary["diseases"][0]["mechanism_classes"]
        assert "JAK inhibitor" in mechanisms
        assert "IL-13 mAb" in mechanisms

    def test_includes_diagnostic_feature_coverage(self, exporter):
        """Should include diagnostic feature coverage."""
        programs = [self._make_program("P1", disease_id="DOID_001")]
        features = [
            LandscapeFeatureRecord(
                feature_id="F1",
                program_id="P1",
                disease_id="DOID_001",
                mechanism_crowding_score=0.5,
                stage_crowding_score=0.2,
                white_space_score=0.5,
                as_of_date="2026-06-16",
            ),
        ]
        summary = exporter.build_disease_summary(programs, [], features)

        coverage = summary["diseases"][0]["diagnostic_feature_coverage"]
        assert coverage["features_with_mechanism_crowding_score"] == 1
        assert coverage["features_with_stage_crowding_score"] == 1
        assert coverage["features_with_white_space_score"] == 1

    def test_writes_disease_summary_json(self, exporter):
        """Should write disease summary to JSON."""
        programs = [self._make_program("P1", disease_id="DOID_001")]
        summary = exporter.build_disease_summary(programs, [], [])

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "summary.json"
            exporter.write_disease_summary(summary, output_path)

            assert output_path.exists()

    def test_writes_disease_summary_markdown(self, exporter):
        """Should write disease summary to Markdown."""
        programs = [self._make_program("P1", disease_id="DOID_001", mechanism_class="JAK inhibitor")]
        summary = exporter.build_disease_summary(programs, [], [])

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "summary.md"
            exporter.write_disease_summary_markdown(summary, output_path)

            assert output_path.exists()
            with open(output_path) as f:
                content = f.read()
            assert "Scientific Cartography Disease Map Summary" in content
            assert "Alzheimer" in content


class TestArtifactManifestExporter:
    """Test artifact manifest exporter."""

    @pytest.fixture
    def exporter(self):
        return ArtifactManifestExporter(as_of_date="2026-06-16", created_at_utc="2026-06-16T00:00:00Z")

    def test_builds_manifest(self, exporter):
        """Should build artifact manifest."""
        inputs = {"program_records": "programs.jsonl", "clusters": "clusters.jsonl"}
        outputs = ["map_index.json", "summary.json"]

        manifest = exporter.build_manifest(inputs, outputs)

        assert manifest["artifact_type"] == "scientific_cartography_export_manifest"
        assert manifest["inputs"] == inputs
        assert sorted(manifest["outputs"]) == sorted(outputs)

    def test_includes_governance_flags(self, exporter):
        """Should include governance flags."""
        manifest = exporter.build_manifest({}, [])

        assert manifest["governance"]["read_only_diagnostic"] is True
        assert manifest["governance"]["production_wiring"] is False
        assert manifest["governance"]["alpha_promotion"] is False

    def test_supports_custom_timestamp(self):
        """Should support custom timestamp for deterministic tests."""
        exporter = ArtifactManifestExporter(as_of_date="2026-06-16", created_at_utc="2026-06-16T12:00:00Z")
        manifest = exporter.build_manifest({}, [])

        assert manifest["created_at_utc"] == "2026-06-16T12:00:00Z"

    def test_writes_manifest(self, exporter):
        """Should write manifest to JSON."""
        manifest = exporter.build_manifest({"program_records": "p.jsonl"}, ["map_index.json"])

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "manifest.json"
            exporter.write_manifest(manifest, output_path)

            assert output_path.exists()
            with open(output_path) as f:
                loaded = json.load(f)
            assert loaded["artifact_type"] == "scientific_cartography_export_manifest"


class TestPhase6Governance:
    """Test Phase 6 governance compliance."""

    def test_no_new_scoring_formulas(self):
        """Phase 6 should not introduce new scoring formulas."""
        # Verify that exporters only use data from earlier phases
        # No new mechanism_crowding, white_space, or stage_crowding computations
        exporter = MapIndexExporter()
        assert not hasattr(exporter, "_compute_mechanism_crowding")
        assert not hasattr(exporter, "_compute_white_space")

    def test_exporters_are_read_only(self):
        """Exporters should not modify input records."""
        program = ProgramRecord(
            program_id="P1",
            asset_id="A1",
            asset_name="Drug",
            disease_id="DOID_001",
            company_name="Company",
            source_refs=["NCT001"],
            as_of_date="2026-06-16",
        )

        exporter = MapIndexExporter()
        original_confidence = program.confidence

        exporter.build_index([program], [], [])

        # Verify program was not modified
        assert program.confidence == original_confidence

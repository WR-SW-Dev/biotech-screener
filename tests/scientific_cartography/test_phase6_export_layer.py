"""Tests for Phase 6 artifact export layer."""

import json
import tempfile
from pathlib import Path

import pytest

from scientific_cartography.export import ArtifactManifestExporter, DiseaseMapExporter, MapIndexExporter
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


class TestMapIndexExporterCounts:
    """Detailed count and aggregation coverage for MapIndexExporter."""

    @pytest.fixture
    def exporter(self):
        return MapIndexExporter(as_of_date="2026-06-16")

    def _prog(
        self, pid, disease_id="D001", disease_name="Disease A", mechanism_class=None, ticker=None, source_refs=None
    ):
        return ProgramRecord(
            program_id=pid,
            asset_id=f"A_{pid}",
            asset_name=f"Drug_{pid}",
            disease_id=disease_id,
            disease_name=disease_name,
            mechanism_class=mechanism_class,
            company_name="Co",
            ticker=ticker,
            source_refs=source_refs or [],
            as_of_date="2026-06-16",
        )

    def _cluster(self, cid, disease_id="D001", disease_name="Disease A", **stage_counts):
        from scientific_cartography.schemas.cluster_schema import CompetitiveClusterRecord

        return CompetitiveClusterRecord(
            cluster_id=cid,
            disease_id=disease_id,
            disease_name=disease_name,
            phase1_count=stage_counts.get("phase1_count", 0),
            phase2_count=stage_counts.get("phase2_count", 0),
            phase3_count=stage_counts.get("phase3_count", 0),
            approved_count=stage_counts.get("approved_count", 0),
            filed_count=stage_counts.get("filed_count", 0),
            preclinical_count=stage_counts.get("preclinical_count", 0),
            discontinued_count=stage_counts.get("discontinued_count", 0),
            unknown_stage_count=stage_counts.get("unknown_stage_count", 0),
            source_refs=stage_counts.get("source_refs", []),
        )

    def _feature(self, fid, disease_id="D001", disease_name="Disease A", source_refs=None):
        return LandscapeFeatureRecord(
            feature_id=fid,
            program_id="P1",
            disease_id=disease_id,
            disease_name=disease_name,
            source_refs=source_refs or [],
            as_of_date="2026-06-16",
        )

    # --- counts{} structure ---

    def test_counts_competitive_clusters(self, exporter):
        clusters = [self._cluster("C1"), self._cluster("C2"), self._cluster("C3")]
        index = exporter.build_index([], clusters, [])
        assert index["counts"]["competitive_clusters"] == 3

    def test_counts_landscape_features(self, exporter):
        features = [self._feature("F1"), self._feature("F2")]
        index = exporter.build_index([], [], features)
        assert index["counts"]["landscape_features"] == 2

    def test_counts_known_vs_unknown_mechanism(self, exporter):
        programs = [
            self._prog("P1", mechanism_class="JAK inhibitor"),
            self._prog("P2", mechanism_class="unknown"),
            self._prog("P3"),  # mechanism_class=None
        ]
        index = exporter.build_index(programs, [], [])
        assert index["counts"]["known_mechanism_programs"] == 1
        assert index["counts"]["unknown_mechanism_programs"] == 2

    def test_counts_disease_count_excludes_unknown_bucket(self, exporter):
        programs = [
            self._prog("P1", disease_id="D001", disease_name="Known Disease"),
            # truly unknown: no disease_id or name
            ProgramRecord(
                program_id="P2",
                asset_id="A2",
                asset_name="Drug2",
                disease_id="",
                disease_name="",
                company_name="Co",
                source_refs=[],
                as_of_date="2026-06-16",
            ),
        ]
        index = exporter.build_index(programs, [], [])
        # disease_count only counts named diseases, not the "unknown" bucket
        assert index["counts"]["disease_count"] == 1
        # But the diseases list still contains the unknown entry
        assert len(index["diseases"]) == 2

    def test_counts_ticker_count_deduplicates(self, exporter):
        programs = [
            self._prog("P1", ticker="PTGX"),
            self._prog("P2", ticker="PTGX"),  # duplicate
            self._prog("P3", ticker="CRBU"),
        ]
        index = exporter.build_index(programs, [], [])
        assert index["counts"]["ticker_count"] == 2

    def test_counts_all_zero_for_empty_input(self, exporter):
        index = exporter.build_index([], [], [])
        counts = index["counts"]
        assert counts["program_records"] == 0
        assert counts["competitive_clusters"] == 0
        assert counts["landscape_features"] == 0
        assert counts["disease_count"] == 0
        assert counts["ticker_count"] == 0
        assert counts["known_mechanism_programs"] == 0
        assert counts["unknown_mechanism_programs"] == 0

    # --- disease-level aggregation ---

    def test_cluster_count_per_disease(self, exporter):
        programs = [self._prog("P1")]
        clusters = [self._cluster("C1"), self._cluster("C2")]
        index = exporter.build_index(programs, clusters, [])
        disease = index["diseases"][0]
        assert disease["cluster_count"] == 2

    def test_feature_count_per_disease(self, exporter):
        programs = [self._prog("P1")]
        features = [self._feature("F1"), self._feature("F2"), self._feature("F3")]
        index = exporter.build_index(programs, [], features)
        disease = index["diseases"][0]
        assert disease["feature_count"] == 3

    def test_stage_distribution_from_clusters(self, exporter):
        clusters = [
            self._cluster("C1", phase3_count=2, phase2_count=1),
            self._cluster("C2", approved_count=1, filed_count=1),
        ]
        programs = [self._prog("P1")]
        index = exporter.build_index(programs, clusters, [])
        sd = index["diseases"][0]["stage_distribution"]
        assert sd["phase3"] == 2
        assert sd["phase2"] == 1
        assert sd["approved"] == 1
        assert sd["filed"] == 1
        assert sd["phase1"] == 0

    def test_stage_distribution_accumulates_across_clusters(self, exporter):
        clusters = [
            self._cluster("C1", phase2_count=3),
            self._cluster("C2", phase2_count=2),
        ]
        programs = [self._prog("P1")]
        index = exporter.build_index(programs, clusters, [])
        assert index["diseases"][0]["stage_distribution"]["phase2"] == 5

    def test_public_tickers_deduplicated_and_sorted(self, exporter):
        programs = [
            self._prog("P1", ticker="ZBTK"),
            self._prog("P2", ticker="ABUS"),
            self._prog("P3", ticker="ZBTK"),  # duplicate
        ]
        index = exporter.build_index(programs, [], [])
        tickers = index["diseases"][0]["public_tickers"]
        assert tickers == sorted(set(tickers))
        assert len(tickers) == 2

    def test_source_refs_count(self, exporter):
        programs = [
            self._prog("P1", source_refs=["NCT001", "NCT002"]),
            self._prog("P2", source_refs=["NCT002", "NCT003"]),  # NCT002 overlap
        ]
        index = exporter.build_index(programs, [], [])
        # 3 unique refs: NCT001, NCT002, NCT003
        assert index["diseases"][0]["source_refs_count"] == 3

    def test_cluster_source_refs_merged(self, exporter):
        programs = [self._prog("P1", source_refs=["NCT001"])]
        clusters = [self._cluster("C1", source_refs=["NCT001", "NCT002"])]
        index = exporter.build_index(programs, clusters, [])
        # NCT001 deduped between program and cluster
        assert index["diseases"][0]["source_refs_count"] == 2

    # --- disease key resolution ---

    def test_disease_id_takes_priority_over_name_for_keying(self, exporter):
        programs = [
            self._prog("P1", disease_id="D001", disease_name="Alzheimer's"),
            self._prog("P2", disease_id="D001", disease_name="Alzheimers"),  # name differs
        ]
        index = exporter.build_index(programs, [], [])
        # Both should land in the same bucket (keyed by disease_id)
        assert len(index["diseases"]) == 1
        assert index["diseases"][0]["program_count"] == 2

    def test_cluster_links_to_same_disease_as_program(self, exporter):
        programs = [self._prog("P1", disease_id="D001")]
        clusters = [self._cluster("C1", disease_id="D001")]
        index = exporter.build_index(programs, clusters, [])
        assert len(index["diseases"]) == 1
        assert index["diseases"][0]["cluster_count"] == 1
        assert index["diseases"][0]["program_count"] == 1

    def test_cluster_only_disease_creates_entry(self, exporter):
        """Disease appears in clusters but not programs — should still appear."""
        clusters = [self._cluster("C1", disease_id="D_CLUSTER_ONLY", disease_name="Rare Disease")]
        index = exporter.build_index([], clusters, [])
        assert any(d["disease_id"] == "D_CLUSTER_ONLY" for d in index["diseases"])

    def test_feature_only_disease_creates_entry(self, exporter):
        features = [self._feature("F1", disease_id="D_FEAT_ONLY", disease_name="Feature Only")]
        index = exporter.build_index([], [], features)
        assert any(d["disease_id"] == "D_FEAT_ONLY" for d in index["diseases"])

    # --- ordering and warnings ---

    def test_unknown_disease_sorts_last(self, exporter):
        programs = [
            self._prog("P1", disease_id="D001", disease_name="Alzheimer's"),
            ProgramRecord(
                program_id="P2",
                asset_id="A2",
                asset_name="Drug2",
                disease_id="",
                disease_name="",
                company_name="Co",
                source_refs=[],
                as_of_date="2026-06-16",
            ),
        ]
        index = exporter.build_index(programs, [], [])
        last = index["diseases"][-1]
        assert last["disease_name"] == "unknown"

    def test_warnings_unknown_disease_present(self, exporter):
        programs = [
            ProgramRecord(
                program_id="P1",
                asset_id="A1",
                asset_name="Drug",
                disease_id="",
                disease_name="",
                company_name="Co",
                source_refs=[],
                as_of_date="2026-06-16",
            ),
        ]
        index = exporter.build_index(programs, [], [])
        assert "unknown_disease_present" in index["warnings"]

    def test_no_warnings_when_all_diseases_known(self, exporter):
        programs = [self._prog("P1", disease_id="D001", disease_name="Cancer")]
        index = exporter.build_index(programs, [], [])
        assert index["warnings"] == []

    def test_multiple_diseases_each_get_correct_program_count(self, exporter):
        programs = [
            self._prog("P1", disease_id="DA", disease_name="Alpha"),
            self._prog("P2", disease_id="DA", disease_name="Alpha"),
            self._prog("P3", disease_id="DB", disease_name="Beta"),
        ]
        index = exporter.build_index(programs, [], [])
        counts = {d["disease_id"]: d["program_count"] for d in index["diseases"]}
        assert counts["DA"] == 2
        assert counts["DB"] == 1


class TestMapIndexExporterReportingIntegration:
    """Verify map_index output fields match what LangGraph reporting reads."""

    def _make_index(self):
        exporter = MapIndexExporter(as_of_date="2026-06-23")
        from scientific_cartography.schemas.cluster_schema import CompetitiveClusterRecord

        programs = [
            ProgramRecord(
                program_id="P1",
                asset_id="A1",
                asset_name="Drug1",
                disease_id="D001",
                disease_name="Lymphoma",
                mechanism_class="CD19 CAR-T",
                ticker="ALLO",
                company_name="Co",
                source_refs=["NCT001"],
                as_of_date="2026-06-23",
            ),
            ProgramRecord(
                program_id="P2",
                asset_id="A2",
                asset_name="Drug2",
                disease_id="D001",
                disease_name="Lymphoma",
                mechanism_class=None,
                ticker="AUTL",
                company_name="Co2",
                source_refs=["NCT002"],
                as_of_date="2026-06-23",
            ),
        ]
        clusters = [
            CompetitiveClusterRecord(
                cluster_id="C1",
                disease_id="D001",
                disease_name="Lymphoma",
                phase2_count=1,
                phase3_count=1,
                source_refs=["NCT001"],
            ),
        ]
        return exporter.build_index(programs, clusters, [])

    def test_map_index_has_nested_counts(self):
        """LangGraph load_artifact_index reads index['counts'] — must be nested."""
        index = self._make_index()
        assert "counts" in index
        assert "disease_count" in index["counts"]
        assert "program_records" in index["counts"]
        assert "competitive_clusters" in index["counts"]
        assert "landscape_features" in index["counts"]

    def test_disease_entries_have_disease_id(self):
        """LangGraph select_review_diseases reads disease['disease_id']."""
        index = self._make_index()
        for disease in index["diseases"]:
            assert "disease_id" in disease
            assert "disease_key" not in disease  # old schema key must not appear

    def test_disease_entries_have_disease_name(self):
        """LangGraph reporting reads disease['disease_name']."""
        index = self._make_index()
        for disease in index["diseases"]:
            assert "disease_name" in disease
            assert "normalized_disease_name" not in disease  # old schema key

    def test_disease_entries_have_public_tickers_list(self):
        """LangGraph reporting displays disease['public_tickers']."""
        index = self._make_index()
        disease = index["diseases"][0]
        assert isinstance(disease["public_tickers"], list)
        assert "ALLO" in disease["public_tickers"]

    def test_stage_distribution_has_all_keys(self):
        """All 8 stage keys present so LG3 can render them without KeyError."""
        index = self._make_index()
        expected_keys = {"approved", "filed", "phase3", "phase2", "phase1", "preclinical", "discontinued", "unknown"}
        for disease in index["diseases"]:
            assert set(disease["stage_distribution"].keys()) == expected_keys

    def test_source_refs_converted_to_count(self):
        """Sets must be converted to ints before JSON serialization."""
        index = self._make_index()
        disease = index["diseases"][0]
        assert isinstance(disease["source_refs_count"], int)
        assert "source_refs" not in disease  # raw set must be removed


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

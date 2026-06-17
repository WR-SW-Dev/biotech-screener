"""Tests for Phase 4 competitive clustering."""

import json
import tempfile
from pathlib import Path

import pytest

from scientific_cartography.build.competitive_cluster_builder import CompetitiveClusterBuilder
from scientific_cartography.schemas.cluster_schema import CompetitiveClusterRecord
from scientific_cartography.schemas.program_schema import ProgramRecord


class TestCompetitiveClusterRecord:
    """Test CompetitiveClusterRecord dataclass."""

    def test_to_dict(self):
        """Should serialize cluster to dict."""
        cluster = CompetitiveClusterRecord(
            cluster_id="abc123",
            disease_name="Alzheimer's Disease",
            mechanism_class="tau inhibitor",
            program_count=5,
            as_of_date="2026-06-16",
        )

        d = cluster.to_dict()

        assert d["cluster_id"] == "abc123"
        assert d["disease_name"] == "Alzheimer's Disease"
        assert d["mechanism_class"] == "tau inhibitor"
        assert d["program_count"] == 5
        assert d["as_of_date"] == "2026-06-16"


class TestCompetitiveClusterBuilder:
    """Test competitive clustering."""

    @pytest.fixture
    def builder(self):
        return CompetitiveClusterBuilder(as_of_date="2026-06-16")

    def _make_program(
        self,
        program_id,
        asset_name,
        disease_id=None,
        disease_name=None,
        mechanism_class=None,
        modality=None,
        target=None,
        clinical_stage=None,
        ticker=None,
        company_id=None,
        company_name=None,
        source_refs=None,
    ):
        """Helper to create ProgramRecord with required fields."""
        return ProgramRecord(
            program_id=program_id,
            asset_id=f"ASSET_{program_id}",
            asset_name=asset_name,
            disease_id=disease_id or "",
            disease_name=disease_name or "",
            mechanism_class=mechanism_class,
            modality=modality,
            target=target,
            clinical_stage=clinical_stage,
            ticker=ticker,
            company_id=company_id,
            company_name=company_name or "Unknown",
            source_refs=source_refs or [],
            as_of_date="2026-06-16",
        )

    def test_cluster_key_generation(self, builder):
        """Should generate deterministic cluster keys."""
        key1 = builder._make_cluster_key(
            disease_id="DOID_0001",
            mechanism_class="JAK inhibitor",
            modality="small molecule",
            target="JAK",
        )

        assert key1 == "DOID_0001|JAK inhibitor|small molecule|JAK"

    def test_cluster_id_deterministic(self, builder):
        """Should generate deterministic cluster IDs."""
        cluster_key = "DOID_0001|JAK inhibitor|small molecule|JAK"

        id1 = builder._make_cluster_id(cluster_key)
        id2 = builder._make_cluster_id(cluster_key)

        assert id1 == id2
        assert len(id1) == 16  # SHA256 truncated to 16 chars

    def test_stage_bucket_approved(self, builder):
        """Should bucket approved stage."""
        program = self._make_program("P1", "Drug A", clinical_stage="Approved")
        assert builder._get_stage_bucket(program) == "approved"

    def test_stage_bucket_phase3(self, builder):
        """Should bucket phase 3 stage."""
        program = self._make_program("P1", "Drug A", clinical_stage="Phase 3")
        assert builder._get_stage_bucket(program) == "phase3"

    def test_stage_bucket_unknown(self, builder):
        """Should bucket unknown stage."""
        program = self._make_program("P1", "Drug A", clinical_stage=None)
        assert builder._get_stage_bucket(program) == "unknown"

    def test_public_program_detection(self, builder):
        """Should detect public programs."""
        public_program = self._make_program("P1", "Drug A", ticker="COGT", company_id="COMP_111")
        private_program = self._make_program("P2", "Drug B", ticker=None, company_id=None)

        assert builder._is_public_program(public_program) is True
        assert builder._is_public_program(private_program) is False

    def test_groups_by_disease_mechanism(self, builder):
        """Should group programs by disease + mechanism."""
        programs = [
            self._make_program(
                "P1",
                "JAK Inhibitor A",
                disease_id="DOID_0001",
                disease_name="Alzheimer's",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
                ticker="COGT",
                company_id="COMP_111",
                source_refs=["NCT001"],
            ),
            self._make_program(
                "P2",
                "JAK Inhibitor B",
                disease_id="DOID_0001",
                disease_name="Alzheimer's",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 1",
                ticker=None,
                company_id=None,
                source_refs=["NCT002"],
            ),
        ]

        clusters, _ = builder.build_from_programs(programs)

        assert len(clusters) == 1
        assert clusters[0].program_count == 2
        assert clusters[0].mechanism_class == "JAK inhibitor"

    def test_different_mechanisms_separate_clusters(self, builder):
        """Should create separate clusters for different mechanisms."""
        programs = [
            self._make_program(
                "P1",
                "JAK Inhibitor",
                disease_id="DOID_0001",
                disease_name="Alzheimer's",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
                source_refs=["NCT001"],
            ),
            self._make_program(
                "P2",
                "IL-13 mAb",
                disease_id="DOID_0001",
                disease_name="Alzheimer's",
                mechanism_class="IL-13 monoclonal antibody",
                modality="monoclonal antibody",
                target="IL13",
                clinical_stage="Phase 2",
                source_refs=["NCT002"],
            ),
        ]

        clusters, _ = builder.build_from_programs(programs)

        assert len(clusters) == 2
        assert clusters[0].mechanism_class == "IL-13 monoclonal antibody"
        assert clusters[1].mechanism_class == "JAK inhibitor"

    def test_unknown_mechanism_preserved(self, builder):
        """Should create cluster for unknown mechanism."""
        programs = [
            self._make_program(
                "P1",
                "Unknown Drug",
                disease_id="DOID_0001",
                disease_name="Alzheimer's",
                mechanism_class=None,
                modality=None,
                target=None,
                clinical_stage="Phase 2",
                source_refs=["NCT001"],
            ),
        ]

        clusters, _ = builder.build_from_programs(programs)

        assert len(clusters) == 1
        assert clusters[0].mechanism_class is None
        assert "unknown mechanism" in clusters[0].warnings

    def test_unknown_disease_preserved(self, builder):
        """Should create cluster for unknown disease."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id=None,
                disease_name=None,
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
                source_refs=["NCT001"],
            ),
        ]

        clusters, _ = builder.build_from_programs(programs)

        assert len(clusters) == 1
        assert clusters[0].disease_id == ""
        assert "unknown disease" in clusters[0].warnings

    def test_public_private_counts(self, builder):
        """Should count public and private programs correctly."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id="DOID_0001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
                ticker="COGT",
                company_id="COMP_111",
                source_refs=["NCT001"],
            ),
            self._make_program(
                "P2",
                "Drug B",
                disease_id="DOID_0001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
                ticker=None,
                company_id=None,
                source_refs=["NCT002"],
            ),
        ]

        clusters, _ = builder.build_from_programs(programs)

        assert clusters[0].public_program_count == 1
        assert clusters[0].private_or_unknown_program_count == 1

    def test_stage_counts(self, builder):
        """Should count programs by clinical stage."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id="DOID_0001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Approved",
                source_refs=["NCT001"],
            ),
            self._make_program(
                "P2",
                "Drug B",
                disease_id="DOID_0001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 3",
                source_refs=["NCT002"],
            ),
            self._make_program(
                "P3",
                "Drug C",
                disease_id="DOID_0001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
                source_refs=["NCT003"],
            ),
        ]

        clusters, _ = builder.build_from_programs(programs)

        assert clusters[0].approved_count == 1
        assert clusters[0].phase3_count == 1
        assert clusters[0].phase2_count == 1

    def test_source_refs_deduplicated(self, builder):
        """Should deduplicate and sort source refs."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id="DOID_0001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
                source_refs=["NCT001", "PubMed_123"],
            ),
            self._make_program(
                "P2",
                "Drug B",
                disease_id="DOID_0001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
                source_refs=["NCT001", "PubMed_456"],
            ),
        ]

        clusters, _ = builder.build_from_programs(programs)

        assert len(clusters[0].source_refs) == 3
        assert clusters[0].source_refs == ["NCT001", "PubMed_123", "PubMed_456"]

    def test_cluster_ids_deterministic(self, builder):
        """Should generate deterministic cluster IDs."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id="DOID_0001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
                source_refs=["NCT001"],
            ),
        ]

        clusters1, _ = builder.build_from_programs(programs)
        clusters2, _ = builder.build_from_programs(programs)

        assert clusters1[0].cluster_id == clusters2[0].cluster_id

    def test_cluster_ordering_deterministic(self, builder):
        """Should order clusters deterministically."""
        programs = [
            self._make_program(
                "P1",
                "Drug B",
                disease_id="DOID_0002",
                mechanism_class="IL-13 mAb",
                modality="monoclonal antibody",
                target="IL13",
                clinical_stage="Phase 2",
                source_refs=["NCT001"],
            ),
            self._make_program(
                "P2",
                "Drug A",
                disease_id="DOID_0001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
                source_refs=["NCT002"],
            ),
        ]

        clusters1, _ = builder.build_from_programs(programs)
        clusters2, _ = builder.build_from_programs(programs)

        assert clusters1[0].cluster_id == clusters2[0].cluster_id
        assert clusters1[1].cluster_id == clusters2[1].cluster_id

    def test_coverage_report_counts(self, builder):
        """Should produce accurate coverage report."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id="DOID_0001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
                ticker="COGT",
                company_id="COMP_111",
                source_refs=["NCT001"],
            ),
            self._make_program(
                "P2",
                "Drug B",
                disease_id="DOID_0001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Approved",
                ticker=None,
                company_id=None,
                source_refs=["NCT002"],
            ),
        ]

        clusters, report = builder.build_from_programs(programs)

        assert report["program_records"] == 2
        assert report["competitive_clusters"] == 1
        assert report["public_programs"] == 1
        assert report["private_or_unknown_programs"] == 1
        assert report["phase2_programs"] == 1
        assert report["approved_programs"] == 1

    def test_coverage_report_unknown_tracking(self, builder):
        """Should track unknown fields in coverage report."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id=None,
                disease_name=None,
                mechanism_class=None,
                modality=None,
                target=None,
                clinical_stage="Phase 2",
                source_refs=["NCT001"],
            ),
        ]

        clusters, report = builder.build_from_programs(programs)

        assert report["clusters_with_unknown_disease"] > 0
        assert report["clusters_with_unknown_mechanism"] > 0
        assert report["clusters_with_unknown_modality"] > 0
        assert report["clusters_with_unknown_target"] > 0

    def test_list_fields_sorted(self, builder):
        """Should maintain sorted deterministic order in list fields."""
        programs = [
            self._make_program(
                "P3",
                "Drug C",
                disease_id="DOID_0001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
                ticker="DNTH",
                company_name="C Inc",
                source_refs=["NCT003"],
            ),
            self._make_program(
                "P1",
                "Drug A",
                disease_id="DOID_0001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
                ticker="COGT",
                company_name="A Inc",
                source_refs=["NCT001"],
            ),
            self._make_program(
                "P2",
                "Drug B",
                disease_id="DOID_0001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
                ticker="ERAS",
                company_name="B Inc",
                source_refs=["NCT002"],
            ),
        ]

        clusters, _ = builder.build_from_programs(programs)

        assert clusters[0].public_tickers == ["COGT", "DNTH", "ERAS"]
        assert clusters[0].sponsor_names == ["A Inc", "B Inc", "C Inc"]
        assert clusters[0].program_ids == ["P1", "P2", "P3"]

    def test_empty_program_list(self, builder):
        """Should handle empty program list."""
        clusters, report = builder.build_from_programs([])

        assert len(clusters) == 0
        assert report["program_records"] == 0
        assert report["competitive_clusters"] == 0

    def test_multiple_clusters(self, builder):
        """Should create multiple clusters correctly."""
        programs = [
            self._make_program(
                "P1",
                "JAK Inhibitor",
                disease_id="DOID_0001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
                source_refs=["NCT001"],
            ),
            self._make_program(
                "P2",
                "CD19 CAR-T",
                disease_id="DOID_0002",
                mechanism_class="CD19 CAR-T",
                modality="cell therapy",
                target="CD19",
                clinical_stage="Phase 2",
                source_refs=["NCT002"],
            ),
            self._make_program(
                "P3",
                "Another JAK Inhibitor",
                disease_id="DOID_0001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 1",
                source_refs=["NCT003"],
            ),
        ]

        clusters, report = builder.build_from_programs(programs)

        assert len(clusters) == 2
        assert report["competitive_clusters"] == 2

    def test_write_clusters_jsonl(self, builder):
        """Should write clusters to JSONL file."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id="DOID_0001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
                source_refs=["NCT001"],
            ),
        ]

        clusters, _ = builder.build_from_programs(programs)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "clusters.jsonl"
            builder.write_clusters_jsonl(clusters, output_path)

            assert output_path.exists()
            with open(output_path) as f:
                lines = f.readlines()
            assert len(lines) == 1
            cluster_dict = json.loads(lines[0])
            assert cluster_dict["cluster_id"]
            assert cluster_dict["program_count"] == 1

    def test_write_coverage_report(self, builder):
        """Should write coverage report to JSON file."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id="DOID_0001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
                source_refs=["NCT001"],
            ),
        ]

        clusters, report = builder.build_from_programs(programs)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "coverage.json"
            builder.write_coverage_report(report, output_path)

            assert output_path.exists()
            with open(output_path) as f:
                loaded_report = json.load(f)
            assert loaded_report["as_of_date"] == "2026-06-16"
            assert loaded_report["program_records"] == 1
            assert loaded_report["competitive_clusters"] == 1

"""Tests for Phase 5 landscape features."""

import json
import tempfile
from pathlib import Path

import pytest

from scientific_cartography.build.landscape_feature_builder import LandscapeFeatureBuilder
from scientific_cartography.schemas.cluster_schema import CompetitiveClusterRecord
from scientific_cartography.schemas.landscape_feature_schema import LandscapeFeatureRecord
from scientific_cartography.schemas.program_schema import ProgramRecord


class TestLandscapeFeatureRecord:
    """Test LandscapeFeatureRecord dataclass."""

    def test_to_dict(self):
        """Should serialize feature to dict."""
        feature = LandscapeFeatureRecord(
            feature_id="feat123",
            program_id="P1",
            cluster_id="C1",
            disease_name="Alzheimer's",
            mechanism_class="JAK inhibitor",
            mechanism_crowding_score=0.42,
            feature_confidence=0.85,
            as_of_date="2026-06-16",
        )

        d = feature.to_dict()

        assert d["feature_id"] == "feat123"
        assert d["program_id"] == "P1"
        assert d["mechanism_crowding_score"] == 0.42
        assert d["feature_confidence"] == 0.85


class TestLandscapeFeatureBuilder:
    """Test landscape feature building."""

    @pytest.fixture
    def builder(self):
        return LandscapeFeatureBuilder(as_of_date="2026-06-16")

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
        source_refs=None,
        confidence=1.0,
    ):
        """Helper to create ProgramRecord."""
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
            company_name="Company",
            source_refs=source_refs or [],
            confidence=confidence,
            as_of_date="2026-06-16",
        )

    def _make_cluster(
        self,
        cluster_id,
        disease_id=None,
        disease_name=None,
        mechanism_class=None,
        modality=None,
        target=None,
        program_count=1,
        approved_count=0,
        filed_count=0,
        phase3_count=0,
        phase2_count=0,
        phase1_count=0,
        preclinical_count=0,
        discontinued_count=0,
        public_program_count=0,
        source_refs=None,
    ):
        """Helper to create CompetitiveClusterRecord."""
        return CompetitiveClusterRecord(
            cluster_id=cluster_id,
            disease_id=disease_id,
            disease_name=disease_name,
            mechanism_class=mechanism_class,
            modality=modality,
            target=target,
            cluster_key="test_key",
            program_count=program_count,
            public_program_count=public_program_count,
            private_or_unknown_program_count=program_count - public_program_count,
            approved_count=approved_count,
            filed_count=filed_count,
            phase3_count=phase3_count,
            phase2_count=phase2_count,
            phase1_count=phase1_count,
            preclinical_count=preclinical_count,
            discontinued_count=discontinued_count,
            source_refs=source_refs or [],
            as_of_date="2026-06-16",
            confidence=0.9,
        )

    def test_builds_one_feature_per_program(self, builder):
        """Should build one feature per program."""
        programs = [
            self._make_program("P1", "Drug A", disease_id="DOID_001", mechanism_class="JAK inhibitor"),
            self._make_program("P2", "Drug B", disease_id="DOID_001", mechanism_class="JAK inhibitor"),
        ]
        clusters = [
            self._make_cluster(
                "C1",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                program_count=2,
            )
        ]

        features, _ = builder.build_from_programs_and_clusters(programs, clusters)

        assert len(features) == 2

    def test_links_features_to_cluster(self, builder):
        """Should link feature to matching cluster."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
            )
        ]
        clusters = [
            self._make_cluster(
                "C1",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                program_count=5,
            )
        ]

        features, _ = builder.build_from_programs_and_clusters(programs, clusters)

        assert features[0].cluster_id == "C1"
        assert features[0].mechanism_program_count == 5

    def test_computes_mechanism_crowding_score(self, builder):
        """Should compute mechanism crowding score using documented formula."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
            )
        ]
        clusters = [
            self._make_cluster(
                "C1",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                program_count=10,
                approved_count=1,
                phase3_count=3,
                phase2_count=4,
                phase1_count=2,
            )
        ]

        features, _ = builder.build_from_programs_and_clusters(programs, clusters)

        # Score = min(1.0, 0.12*1 + 0.10*0 + 0.08*3 + 0.05*4 + 0.03*2 + 0.02*0)
        # = min(1.0, 0.12 + 0.24 + 0.20 + 0.06) = 0.62
        score = features[0].mechanism_crowding_score
        assert score is not None
        assert abs(score - 0.62) < 0.01

    def test_white_space_score_formula(self, builder):
        """Should compute white-space score as 1.0 - mechanism_crowding."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
            )
        ]
        clusters = [
            self._make_cluster(
                "C1",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                program_count=5,
                approved_count=1,
                phase3_count=1,
            )
        ]

        features, _ = builder.build_from_programs_and_clusters(programs, clusters)

        crowding = features[0].mechanism_crowding_score
        white_space = features[0].white_space_score
        assert white_space is not None
        assert abs(white_space - (1.0 - crowding)) < 0.01

    def test_white_space_none_for_unknown_mechanism(self, builder):
        """Should not compute white-space when mechanism is unknown."""
        programs = [
            self._make_program(
                "P1",
                "Unknown Drug",
                disease_id="DOID_001",
                mechanism_class=None,
                modality=None,
                target=None,
                clinical_stage="Phase 2",
            )
        ]
        clusters = [
            self._make_cluster(
                "C1",
                disease_id="DOID_001",
                mechanism_class=None,
                modality=None,
                target=None,
                program_count=1,
            )
        ]

        features, _ = builder.build_from_programs_and_clusters(programs, clusters)

        assert features[0].white_space_score is None
        assert "unknown_mechanism_no_crowding_score" in features[0].warnings

    def test_computes_stage_crowding_score(self, builder):
        """Should compute stage crowding using documented weights."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
            )
        ]
        clusters = [
            self._make_cluster(
                "C1",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                program_count=5,
                phase2_count=5,
            )
        ]

        features, _ = builder.build_from_programs_and_clusters(programs, clusters)

        # Stage crowding = min(1.0, 0.05 * 5) = 0.25
        score = features[0].stage_crowding_score
        assert score is not None
        assert abs(score - 0.25) < 0.01

    def test_stage_crowding_none_for_unknown_stage(self, builder):
        """Should not compute stage crowding when stage is unknown."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage=None,
            )
        ]
        clusters = [
            self._make_cluster(
                "C1",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                program_count=1,
            )
        ]

        features, _ = builder.build_from_programs_and_clusters(programs, clusters)

        assert features[0].stage_crowding_score is None
        assert "unknown_stage_no_stage_score" in features[0].warnings

    def test_missing_cluster_match_warning(self, builder):
        """Should warn when cluster match is missing."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
            )
        ]
        # No matching cluster

        features, _ = builder.build_from_programs_and_clusters(programs, [])

        assert features[0].cluster_id is None
        assert "missing_cluster_match" in features[0].warnings
        assert features[0].feature_status == "partial"

    def test_feature_ids_deterministic(self, builder):
        """Should generate deterministic feature IDs."""
        programs = [self._make_program("P1", "Drug A", disease_id="DOID_001", mechanism_class="JAK inhibitor")]
        clusters = [self._make_cluster("C1", disease_id="DOID_001", mechanism_class="JAK inhibitor")]

        features1, _ = builder.build_from_programs_and_clusters(programs, clusters)
        features2, _ = builder.build_from_programs_and_clusters(programs, clusters)

        assert features1[0].feature_id == features2[0].feature_id

    def test_output_ordering_deterministic(self, builder):
        """Should order features deterministically."""
        programs = [
            self._make_program("P3", "Drug C", disease_id="DOID_001", mechanism_class="JAK inhibitor"),
            self._make_program("P1", "Drug A", disease_id="DOID_001", mechanism_class="JAK inhibitor"),
            self._make_program("P2", "Drug B", disease_id="DOID_001", mechanism_class="JAK inhibitor"),
        ]
        clusters = [self._make_cluster("C1", disease_id="DOID_001", mechanism_class="JAK inhibitor")]

        features1, _ = builder.build_from_programs_and_clusters(programs, clusters)
        features2, _ = builder.build_from_programs_and_clusters(programs, clusters)

        assert [f.feature_id for f in features1] == [f.feature_id for f in features2]

    def test_coverage_report_counts(self, builder):
        """Should produce accurate coverage report."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
            ),
            self._make_program(
                "P2",
                "Drug B",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
            ),
        ]
        clusters = [
            self._make_cluster(
                "C1",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                program_count=2,
                phase2_count=2,
            )
        ]

        features, report = builder.build_from_programs_and_clusters(programs, clusters)

        assert report["program_records"] == 2
        assert report["landscape_feature_records"] == 2
        assert report["competitive_clusters"] == 1
        assert report["features_with_mechanism_crowding_score"] > 0
        assert report["features_with_stage_crowding_score"] > 0
        assert report["features_with_white_space_score"] > 0

    def test_coverage_report_mean_scores(self, builder):
        """Should compute mean scores in coverage report."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
            ),
            self._make_program(
                "P2",
                "Drug B",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                clinical_stage="Phase 2",
            ),
        ]
        clusters = [
            self._make_cluster(
                "C1",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                modality="small molecule",
                target="JAK",
                program_count=2,
                phase2_count=2,
            )
        ]

        _, report = builder.build_from_programs_and_clusters(programs, clusters)

        assert report["mean_mechanism_crowding_score"] is not None
        assert report["mean_stage_crowding_score"] is not None
        assert report["mean_white_space_score"] is not None

    def test_source_refs_aggregated(self, builder):
        """Should aggregate and deduplicate source refs."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                source_refs=["NCT001", "PubMed_123"],
            )
        ]
        clusters = [
            self._make_cluster(
                "C1",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                program_count=1,
                source_refs=["NCT001", "PubMed_456"],
            )
        ]

        features, _ = builder.build_from_programs_and_clusters(programs, clusters)

        assert len(features[0].source_refs) == 3
        assert set(features[0].source_refs) == {"NCT001", "PubMed_123", "PubMed_456"}

    def test_write_features_jsonl(self, builder):
        """Should write features to JSONL file."""
        programs = [self._make_program("P1", "Drug A", disease_id="DOID_001", mechanism_class="JAK inhibitor")]
        clusters = [self._make_cluster("C1", disease_id="DOID_001", mechanism_class="JAK inhibitor")]

        features, _ = builder.build_from_programs_and_clusters(programs, clusters)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "features.jsonl"
            builder.write_features_jsonl(features, output_path)

            assert output_path.exists()
            with open(output_path) as f:
                lines = f.readlines()
            assert len(lines) == 1
            feature_dict = json.loads(lines[0])
            assert feature_dict["feature_id"]
            assert feature_dict["program_id"] == "P1"

    def test_write_coverage_report(self, builder):
        """Should write coverage report to JSON file."""
        programs = [self._make_program("P1", "Drug A", disease_id="DOID_001", mechanism_class="JAK inhibitor")]
        clusters = [self._make_cluster("C1", disease_id="DOID_001", mechanism_class="JAK inhibitor")]

        features, report = builder.build_from_programs_and_clusters(programs, clusters)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "coverage.json"
            builder.write_coverage_report(report, output_path)

            assert output_path.exists()
            with open(output_path) as f:
                loaded_report = json.load(f)
            assert loaded_report["as_of_date"] == "2026-06-16"
            assert loaded_report["landscape_feature_records"] == 1

    def test_feature_confidence_computation(self, builder):
        """Should compute feature confidence from program and cluster."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                confidence=0.8,
                source_refs=["NCT001"],
            )
        ]
        clusters = [
            self._make_cluster(
                "C1",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                program_count=1,
                source_refs=["NCT001"],
            )
        ]

        features, _ = builder.build_from_programs_and_clusters(programs, clusters)

        # Confidence should be min of program (0.8) and cluster (0.9)
        assert features[0].feature_confidence == 0.8

    def test_disease_program_count(self, builder):
        """Should compute disease-level program counts."""
        programs = [
            self._make_program("P1", "Drug A", disease_id="DOID_001", mechanism_class="JAK inhibitor"),
            self._make_program("P2", "Drug B", disease_id="DOID_001", mechanism_class="IL-13 mAb"),
        ]
        clusters = [
            self._make_cluster(
                "C1",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                program_count=1,
            ),
            self._make_cluster(
                "C2",
                disease_id="DOID_001",
                mechanism_class="IL-13 mAb",
                program_count=1,
            ),
        ]

        features, _ = builder.build_from_programs_and_clusters(programs, clusters)

        # Both programs target DOID_001, so disease_program_count should be 2
        assert features[0].disease_program_count == 2
        assert features[1].disease_program_count == 2

    def test_same_stage_program_count(self, builder):
        """Should compute same-stage program count from cluster."""
        programs = [
            self._make_program(
                "P1",
                "Drug A",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                clinical_stage="Phase 2",
            )
        ]
        clusters = [
            self._make_cluster(
                "C1",
                disease_id="DOID_001",
                mechanism_class="JAK inhibitor",
                program_count=10,
                phase2_count=5,
            )
        ]

        features, _ = builder.build_from_programs_and_clusters(programs, clusters)

        assert features[0].same_stage_program_count == 5

    def test_empty_programs_and_clusters(self, builder):
        """Should handle empty inputs."""
        features, report = builder.build_from_programs_and_clusters([], [])

        assert len(features) == 0
        assert report["program_records"] == 0
        assert report["landscape_feature_records"] == 0

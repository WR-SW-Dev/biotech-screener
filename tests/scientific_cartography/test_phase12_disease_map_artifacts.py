"""Phase 12 Disease Map Artifacts tests.

Tests for per-disease artifact export using Phase 8-11 records.
"""

import json
from pathlib import Path

import pytest

from scientific_cartography.export.disease_map_artifact_exporter import DiseaseMapArtifactExporter
from scientific_cartography.schemas.asset_indication_map_schema import AssetIndicationMapRecord
from scientific_cartography.schemas.disease_ontology_schema import DiseaseOntologyRecord
from scientific_cartography.schemas.enhanced_cluster_schema import EnhancedCompetitiveClusterRecord
from scientific_cartography.schemas.landscape_context_schema import LandscapeContextFeatureRecord


@pytest.fixture
def exporter():
    """Disease map artifact exporter fixture."""
    return DiseaseMapArtifactExporter(
        as_of_date="2026-06-18",
        created_at_utc="2026-06-18T00:00:00Z",
    )


@pytest.fixture
def sample_disease_ontology():
    """Sample Phase 8 disease ontology records."""
    return [
        DiseaseOntologyRecord(
            raw_disease_name="Acute Pain",
            normalized_disease_name="Acute Pain",
            mondo_id="MONDO:0000001",
            therapeutic_area="Pain Management",
            parent_disease="Pain Conditions",
            confidence=0.95,
            source="mondo",
            source_refs=["mondo_ontology"],
            as_of_date="2026-06-18",
        ),
        DiseaseOntologyRecord(
            raw_disease_name="Multiple Myeloma",
            normalized_disease_name="Multiple Myeloma",
            mondo_id="MONDO:0000002",
            therapeutic_area="Oncology",
            parent_disease="Blood Cancers",
            confidence=0.98,
            source="mondo",
            source_refs=["mondo_ontology"],
            as_of_date="2026-06-18",
        ),
    ]


@pytest.fixture
def sample_asset_records():
    """Sample Phase 9 asset indication records."""
    return [
        # Acute Pain - approved
        AssetIndicationMapRecord(
            record_id="rec001",
            company_id="VRTX",
            ticker="VRTX",
            company_name="Vertex Pharmaceuticals",
            asset_id="asset_vx548",
            asset_name="VX-548",
            raw_indication="Acute Pain",
            normalized_disease_name="Acute Pain",
            mondo_id="MONDO:0000001",
            therapeutic_area="Pain Management",
            mechanism_class="NaV1.8 Inhibitor",
            target="SCN10A",
            modality="Small Molecule",
            clinical_stage="Approved",
            source_priority=3,
            source_type="ctgov",
            source_refs=["ctgov_ref"],
            overall_confidence=0.95,
            as_of_date="2026-06-18",
        ),
        # Acute Pain - phase 3
        AssetIndicationMapRecord(
            record_id="rec002",
            company_id="VRTX",
            ticker="VRTX",
            company_name="Vertex Pharmaceuticals",
            asset_id="asset_vx22",
            asset_name="VX-22",
            raw_indication="Acute Pain",
            normalized_disease_name="Acute Pain",
            mondo_id="MONDO:0000001",
            therapeutic_area="Pain Management",
            mechanism_class="TRPV1 Antagonist",
            target="TRPV1",
            modality="Small Molecule",
            clinical_stage="Phase 3",
            source_priority=3,
            source_type="ctgov",
            source_refs=["ctgov_ref2"],
            overall_confidence=0.90,
            as_of_date="2026-06-18",
        ),
        # Multiple Myeloma
        AssetIndicationMapRecord(
            record_id="rec003",
            company_id="ACLX",
            ticker="ACLX",
            company_name="Aclaris",
            asset_id="asset_atc",
            asset_name="ATI-2138",
            raw_indication="Multiple Myeloma",
            normalized_disease_name="Multiple Myeloma",
            mondo_id="MONDO:0000002",
            therapeutic_area="Oncology",
            mechanism_class="BCMA CAR-T",
            target="BCMA",
            modality="Cell Therapy",
            clinical_stage="Phase 2",
            source_priority=3,
            source_type="ctgov",
            source_refs=["ctgov_ref3"],
            overall_confidence=0.85,
            as_of_date="2026-06-18",
        ),
        # Unknown disease
        AssetIndicationMapRecord(
            record_id="rec004",
            company_id=None,
            ticker=None,
            company_name="Private Biotech",
            asset_id="asset_unkn",
            asset_name="UNKN-1",
            raw_indication="Rare Syndrome X",
            normalized_disease_name="Rare Syndrome X",
            mondo_id=None,
            therapeutic_area=None,
            mechanism_class=None,
            target=None,
            modality="Gene Therapy",
            clinical_stage="Preclinical",
            source_priority=8,
            source_type="manual",
            source_refs=["manual_ref"],
            overall_confidence=0.50,
            as_of_date="2026-06-18",
        ),
    ]


@pytest.fixture
def sample_clusters():
    """Sample Phase 10 cluster records."""
    return [
        EnhancedCompetitiveClusterRecord(
            cluster_id="c001",
            cluster_key="MONDO:0000001|NaV1.8 Inhibitor|SCN10A|Small Molecule",
            disease_key="MONDO:0000001",
            normalized_disease_name="Acute Pain",
            mondo_id="MONDO:0000001",
            mechanism_class="NaV1.8 Inhibitor",
            target="SCN10A",
            modality="Small Molecule",
            program_count=1,
            asset_count=1,
            company_count=1,
            ticker_count=1,
            as_of_date="2026-06-18",
        ),
    ]


@pytest.fixture
def sample_context_features():
    """Sample Phase 11 context feature records."""
    return [
        LandscapeContextFeatureRecord(
            feature_id="f001",
            source_record_id="rec001",
            cluster_id="c001",
            company_id="VRTX",
            asset_name="VX-548",
            normalized_disease_name="Acute Pain",
            mondo_id="MONDO:0000001",
            disease_competition_count=2,
            same_mechanism_competition_count=1,
            mechanism_novelty_category="novel_or_sparse",
            white_space_category="moderate_context",
            crowding_category="low",
            as_of_date="2026-06-18",
        ),
    ]


class TestDiseaseMapArtifactExporter:
    """Test disease map artifact exporter."""

    def test_exporter_initialization(self, exporter):
        """Exporter initializes with dates."""
        assert exporter.as_of_date == "2026-06-18"
        assert "2026-06-18T" in exporter.created_at_utc

    def test_make_safe_slug_from_disease_name(self, exporter):
        """Creates safe slug from disease name."""
        assert exporter._make_safe_slug("Acute Pain") == "acute-pain"
        assert exporter._make_safe_slug("Multiple Myeloma") == "multiple-myeloma"
        assert exporter._make_safe_slug("Rare Syndrome X") == "rare-syndrome-x"

    def test_make_safe_slug_with_mondo_id(self, exporter):
        """Creates safe slug from MONDO ID."""
        assert exporter._make_safe_slug("MONDO:0000001") == "mondo-0000001"

    def test_make_safe_slug_unknown_disease(self, exporter):
        """Defaults to unknown-disease for empty or unknown."""
        assert exporter._make_safe_slug("unknown") == "unknown-disease"
        assert exporter._make_safe_slug("") == "unknown-disease"

    def test_get_disease_key_priority(self, exporter):
        """Disease key uses mondo_id priority."""
        record = AssetIndicationMapRecord(
            record_id="test",
            mondo_id="MONDO:0000001",
            normalized_disease_name="Acute Pain",
            raw_indication="Pain",
        )
        assert exporter._get_disease_key(record) == "MONDO:0000001"

    def test_get_disease_key_fallback(self, exporter):
        """Disease key falls back to normalized name."""
        record = AssetIndicationMapRecord(
            record_id="test",
            mondo_id=None,
            normalized_disease_name="Acute Pain",
            raw_indication="Pain",
        )
        assert exporter._get_disease_key(record) == "Acute Pain"

    def test_builds_disease_index(
        self,
        exporter,
        sample_disease_ontology,
        sample_asset_records,
        sample_clusters,
        sample_context_features,
    ):
        """Builds disease index from all inputs."""
        ontology_dict = {}
        for r in sample_disease_ontology:
            key = r.mondo_id or r.normalized_disease_name
            ontology_dict[key] = r

        index = exporter._build_disease_index(
            sample_asset_records,
            ontology_dict,
            sample_clusters,
            sample_context_features,
        )

        # Should have 3 diseases
        assert len(index) >= 3

        # Acute Pain should have 2 asset records
        acute_pain_index = index.get("MONDO:0000001")
        assert acute_pain_index is not None
        assert len(acute_pain_index["asset_records"]) == 2

    def test_builds_disease_artifact(
        self,
        exporter,
        sample_disease_ontology,
        sample_asset_records,
        sample_clusters,
        sample_context_features,
    ):
        """Builds per-disease artifact."""
        ontology_dict = {(r.mondo_id or r.normalized_disease_name): r for r in sample_disease_ontology}
        index = exporter._build_disease_index(
            sample_asset_records,
            ontology_dict,
            sample_clusters,
            sample_context_features,
        )

        artifact = exporter._build_disease_artifact(
            "MONDO:0000001",
            index["MONDO:0000001"],
        )

        assert artifact["disease_key"] == "MONDO:0000001"
        assert artifact["disease"]["mondo_id"] == "MONDO:0000001"
        assert artifact["summary"]["program_count"] == 2
        assert artifact["summary"]["approved_incumbent_count"] == 1

    def test_disease_artifact_includes_standard_of_care(
        self,
        exporter,
        sample_disease_ontology,
        sample_asset_records,
        sample_clusters,
        sample_context_features,
    ):
        """Disease artifact includes approved incumbents."""
        ontology_dict = {(r.mondo_id or r.normalized_disease_name): r for r in sample_disease_ontology}
        index = exporter._build_disease_index(
            sample_asset_records,
            ontology_dict,
            sample_clusters,
            sample_context_features,
        )

        artifact = exporter._build_disease_artifact(
            "MONDO:0000001",
            index["MONDO:0000001"],
        )

        soc = artifact["standard_of_care"]
        assert "VX-548" in soc["approved_assets"]

    def test_disease_artifact_observed_tickers(
        self,
        exporter,
        sample_disease_ontology,
        sample_asset_records,
        sample_clusters,
        sample_context_features,
    ):
        """Disease artifact includes observed tickers."""
        ontology_dict = {(r.mondo_id or r.normalized_disease_name): r for r in sample_disease_ontology}
        index = exporter._build_disease_index(
            sample_asset_records,
            ontology_dict,
            sample_clusters,
            sample_context_features,
        )

        artifact = exporter._build_disease_artifact(
            "MONDO:0000001",
            index["MONDO:0000001"],
        )

        assert "VRTX" in artifact["observed_tickers"]

    def test_disease_artifact_includes_unknowns(
        self,
        exporter,
        sample_disease_ontology,
        sample_asset_records,
        sample_clusters,
        sample_context_features,
    ):
        """Disease artifact includes unknown/missing counts."""
        ontology_dict = {(r.mondo_id or r.normalized_disease_name): r for r in sample_disease_ontology}
        index = exporter._build_disease_index(
            sample_asset_records,
            ontology_dict,
            sample_clusters,
            sample_context_features,
        )

        artifact = exporter._build_disease_artifact(
            "MONDO:0000001",
            index["MONDO:0000001"],
        )

        assert "missing_mondo_id_count" in artifact["unknowns"]
        assert "missing_ticker_count" in artifact["unknowns"]

    def test_disease_artifact_governance_flags(
        self,
        exporter,
        sample_disease_ontology,
        sample_asset_records,
        sample_clusters,
        sample_context_features,
    ):
        """Disease artifact has correct governance flags."""
        ontology_dict = {(r.mondo_id or r.normalized_disease_name): r for r in sample_disease_ontology}
        index = exporter._build_disease_index(
            sample_asset_records,
            ontology_dict,
            sample_clusters,
            sample_context_features,
        )

        artifact = exporter._build_disease_artifact(
            "MONDO:0000001",
            index["MONDO:0000001"],
        )

        assert artifact["governance"]["read_only_diagnostic"] is True
        assert artifact["governance"]["production_model_change"] is False
        assert artifact["governance"]["ranker_change"] is False
        assert artifact["governance"]["selector_change"] is False

    def test_no_scoring_fields_in_artifact(
        self,
        exporter,
        sample_disease_ontology,
        sample_asset_records,
        sample_clusters,
        sample_context_features,
    ):
        """Disease artifact contains no scoring fields."""
        ontology_dict = {(r.mondo_id or r.normalized_disease_name): r for r in sample_disease_ontology}
        index = exporter._build_disease_index(
            sample_asset_records,
            ontology_dict,
            sample_clusters,
            sample_context_features,
        )

        artifact = exporter._build_disease_artifact(
            "MONDO:0000001",
            index["MONDO:0000001"],
        )

        # Check that governance fields explicitly mark no scoring
        assert artifact["governance"]["ranker_change"] is False
        assert artifact["governance"]["production_model_change"] is False

    def test_record_to_dict_flat(self, exporter, sample_asset_records):
        """Converts record to flat dict for CSV."""
        record = sample_asset_records[0]
        flat = exporter._record_to_dict(record)

        assert flat["ticker"] == "VRTX"
        assert flat["asset_name"] == "VX-548"
        assert isinstance(flat["source_refs"], str)  # JSON string
        assert isinstance(flat["warnings"], str)  # JSON string

    def test_builds_disease_csv_rows(
        self,
        exporter,
        sample_disease_ontology,
        sample_asset_records,
        sample_clusters,
        sample_context_features,
    ):
        """Builds CSV rows from artifact."""
        ontology_dict = {(r.mondo_id or r.normalized_disease_name): r for r in sample_disease_ontology}
        index = exporter._build_disease_index(
            sample_asset_records,
            ontology_dict,
            sample_clusters,
            sample_context_features,
        )

        artifact = exporter._build_disease_artifact(
            "MONDO:0000001",
            index["MONDO:0000001"],
        )

        rows = exporter._build_disease_csv_rows(artifact)
        assert len(rows) == 2
        assert all("ticker" in row for row in rows)

    def test_builds_disease_markdown(
        self,
        exporter,
        sample_disease_ontology,
        sample_asset_records,
        sample_clusters,
        sample_context_features,
    ):
        """Builds markdown report from artifact."""
        ontology_dict = {(r.mondo_id or r.normalized_disease_name): r for r in sample_disease_ontology}
        index = exporter._build_disease_index(
            sample_asset_records,
            ontology_dict,
            sample_clusters,
            sample_context_features,
        )

        artifact = exporter._build_disease_artifact(
            "MONDO:0000001",
            index["MONDO:0000001"],
        )

        md = exporter._build_disease_markdown(artifact)

        # Should have governance disclaimer
        assert "Read-only diagnostic" in md
        assert "Acute Pain" in md
        # Should NOT have forbidden action language
        assert " buy " not in md.lower()
        assert " sell " not in md.lower()
        # OK to have "investment recommendation" as part of disclaimer
        assert "Not intended as medical advice or investment recommendation" in md

    def test_preserves_unknown_disease(
        self,
        exporter,
        sample_disease_ontology,
        sample_asset_records,
        sample_clusters,
        sample_context_features,
    ):
        """Preserves unknown disease in artifact."""
        ontology_dict = {(r.mondo_id or r.normalized_disease_name): r for r in sample_disease_ontology}
        index = exporter._build_disease_index(
            sample_asset_records,
            ontology_dict,
            sample_clusters,
            sample_context_features,
        )

        # Should have unknown disease in index
        assert any("Rare Syndrome X" in str(k) for k in index.keys())

    def test_export_all_creates_directory_structure(
        self,
        exporter,
        sample_disease_ontology,
        sample_asset_records,
        sample_clusters,
        sample_context_features,
        tmp_path,
    ):
        """export_all creates expected directory structure."""
        exporter.export_all(
            sample_disease_ontology,
            sample_asset_records,
            sample_clusters,
            sample_context_features,
            tmp_path,
        )

        # Check top-level files
        assert (tmp_path / "disease_map_index.json").exists()
        assert (tmp_path / "disease_map_index.md").exists()

        # Check diseases directory
        assert (tmp_path / "diseases").exists()

        # Check per-disease artifacts
        acute_pain_dir = tmp_path / "diseases" / "acute-pain"
        assert acute_pain_dir.exists()
        assert (acute_pain_dir / "disease_map.json").exists()
        assert (acute_pain_dir / "disease_map.csv").exists()
        assert (acute_pain_dir / "disease_map.md").exists()

    def test_export_all_json_valid(
        self,
        exporter,
        sample_disease_ontology,
        sample_asset_records,
        sample_clusters,
        sample_context_features,
        tmp_path,
    ):
        """Exported JSON is valid and parseable."""
        exporter.export_all(
            sample_disease_ontology,
            sample_asset_records,
            sample_clusters,
            sample_context_features,
            tmp_path,
        )

        # Parse index JSON
        with open(tmp_path / "disease_map_index.json") as f:
            index = json.load(f)

        assert index["artifact_type"] == "scientific_cartography_disease_map_index"
        assert index["disease_count"] >= 2

        # Parse disease JSON
        acute_pain_path = tmp_path / "diseases" / "acute-pain" / "disease_map.json"
        with open(acute_pain_path) as f:
            disease_artifact = json.load(f)

        assert disease_artifact["artifact_type"] == "scientific_cartography_disease_map"
        assert disease_artifact["disease"]["normalized_disease_name"] == "Acute Pain"

    def test_index_includes_all_diseases(
        self,
        exporter,
        sample_disease_ontology,
        sample_asset_records,
        sample_clusters,
        sample_context_features,
        tmp_path,
    ):
        """Index includes all diseases."""
        exporter.export_all(
            sample_disease_ontology,
            sample_asset_records,
            sample_clusters,
            sample_context_features,
            tmp_path,
        )

        with open(tmp_path / "disease_map_index.json") as f:
            index = json.load(f)

        # Should include Acute Pain and Multiple Myeloma at minimum
        disease_names = [d["normalized_disease_name"] for d in index["diseases"]]
        assert "Acute Pain" in disease_names
        assert "Multiple Myeloma" in disease_names

    def test_index_markdown_readable(
        self,
        exporter,
        sample_disease_ontology,
        sample_asset_records,
        sample_clusters,
        sample_context_features,
        tmp_path,
    ):
        """Index markdown is readable and has governance disclaimer."""
        exporter.export_all(
            sample_disease_ontology,
            sample_asset_records,
            sample_clusters,
            sample_context_features,
            tmp_path,
        )

        with open(tmp_path / "disease_map_index.md") as f:
            md = f.read()

        assert "Scientific Cartography Disease Map Index" in md
        assert "Read-only diagnostic" in md
        assert "Acute Pain" in md

    def test_csv_deterministic(
        self,
        exporter,
        sample_disease_ontology,
        sample_asset_records,
        sample_clusters,
        sample_context_features,
        tmp_path,
    ):
        """CSV output is deterministic."""
        exporter.export_all(
            sample_disease_ontology,
            sample_asset_records,
            sample_clusters,
            sample_context_features,
            tmp_path,
        )

        csv_path = tmp_path / "diseases" / "acute-pain" / "disease_map.csv"
        with open(csv_path) as f:
            csv_content = f.read()

        # Should have header and data rows
        lines = csv_content.strip().split("\n")
        assert len(lines) >= 2
        assert "ticker" in lines[0]

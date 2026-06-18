"""Phase 10 Enhanced Cluster Enhancement tests.

Tests for diagnostic-only cluster enrichment using Phase 9 AssetIndicationMapRecord.
"""

import pytest

from scientific_cartography.build.enhanced_cluster_builder import EnhancedCompetitiveClusterBuilder
from scientific_cartography.schemas.asset_indication_map_schema import AssetIndicationMapRecord


@pytest.fixture
def builder():
    """Enhanced cluster builder fixture."""
    return EnhancedCompetitiveClusterBuilder(as_of_date="2026-06-17")


@pytest.fixture
def sample_records():
    """Sample Phase 9 asset indication map records."""
    return [
        # Public company, mapped disease, known mechanism/target/modality
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
            clinical_stage="Phase 3",
            source_priority=3,
            source_type="ctgov",
            source_refs=["clinicaltrials.gov/ct2/show/NCT12345"],
            overall_confidence=0.95,
            disease_ontology_confidence=1.0,
            as_of_date="2026-06-17",
        ),
        # Same company/asset, same disease, different source
        AssetIndicationMapRecord(
            record_id="rec002",
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
            clinical_stage="Phase 2",
            source_priority=4,
            source_type="fda_label",
            source_refs=["FDA approval label"],
            overall_confidence=0.90,
            disease_ontology_confidence=1.0,
            as_of_date="2026-06-17",
        ),
        # Different company, different disease
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
            source_refs=["clinicaltrials.gov/ct2/show/NCT54321"],
            overall_confidence=0.85,
            disease_ontology_confidence=0.95,
            as_of_date="2026-06-17",
        ),
        # Private company, unknown disease
        AssetIndicationMapRecord(
            record_id="rec004",
            company_id=None,
            ticker=None,
            company_name="Private Biotech Inc",
            asset_id="asset_pb1",
            asset_name="PB-1",
            raw_indication="Rare Genetic Syndrome X",
            normalized_disease_name="Rare Genetic Syndrome X",
            mondo_id=None,
            therapeutic_area=None,
            mechanism_class=None,
            target=None,
            modality="Gene Therapy",
            clinical_stage="Preclinical",
            source_priority=8,
            source_type="manual",
            source_refs=["company_database"],
            overall_confidence=0.50,
            disease_ontology_confidence=0.0,
            as_of_date="2026-06-17",
        ),
    ]


class TestEnhancedClusterSchema:
    """Test schema initialization and serialization."""

    def test_record_initialization(self):
        """Record initializes with required fields."""
        from scientific_cartography.schemas.enhanced_cluster_schema import EnhancedCompetitiveClusterRecord

        record = EnhancedCompetitiveClusterRecord(
            cluster_id="abc123",
            cluster_key="disease|mech|target|mod",
            disease_key="disease",
            normalized_disease_name="Test Disease",
        )

        assert record.cluster_id == "abc123"
        assert record.governance["read_only_diagnostic"] is True
        assert record.governance["production_model_change"] is False

    def test_record_to_dict(self):
        """Record serializes to dictionary."""
        from scientific_cartography.schemas.enhanced_cluster_schema import EnhancedCompetitiveClusterRecord

        record = EnhancedCompetitiveClusterRecord(
            cluster_id="test123",
            cluster_key="key",
            disease_key="MONDO:0000001",
            normalized_disease_name="Test Disease",
            mondo_id="MONDO:0000001",
            therapeutic_area="Oncology",
            program_count=5,
            asset_count=3,
            company_count=2,
            as_of_date="2026-06-17",
        )

        d = record.to_dict()
        assert d["cluster_id"] == "test123"
        assert d["mondo_id"] == "MONDO:0000001"
        assert d["program_count"] == 5


class TestEnhancedClusterBuilder:
    """Test builder and clustering behavior."""

    def test_builds_clusters_from_records(self, builder, sample_records):
        """Builds enhanced clusters from Phase 9 records."""
        clusters, coverage = builder.build_from_asset_indication_records(sample_records)

        # Should have 3 clusters (VRTX pain pain, ACLX myeloma, private unknown)
        assert len(clusters) == 3
        assert coverage.total_records == 4
        assert coverage.total_clusters == 3

    def test_groups_by_disease_mechanism_target_modality(self, builder, sample_records):
        """Groups records by mondo_id|mechanism|target|modality."""
        clusters, _ = builder.build_from_asset_indication_records(sample_records)

        # VRTX records should be in same cluster
        vrtx_clusters = [c for c in clusters if "SCN10A" in c.target]
        assert len(vrtx_clusters) == 1
        assert vrtx_clusters[0].program_count == 2

        # ACLX record in separate cluster
        aclx_clusters = [c for c in clusters if "BCMA" in c.target]
        assert len(aclx_clusters) == 1

    def test_uses_mondo_id_as_disease_key(self, builder, sample_records):
        """Uses mondo_id as primary disease key when available."""
        clusters, _ = builder.build_from_asset_indication_records(sample_records)

        # VRTX cluster should have mondo_id
        vrtx_clusters = [c for c in clusters if "SCN10A" in c.target]
        assert vrtx_clusters[0].mondo_id == "MONDO:0000001"
        assert vrtx_clusters[0].disease_key == "MONDO:0000001"

    def test_handles_unknown_disease_without_mondo(self, builder, sample_records):
        """Preserves unknown disease without mondo_id."""
        clusters, coverage = builder.build_from_asset_indication_records(sample_records)

        unknown_clusters = [c for c in clusters if c.normalized_disease_name == "Rare Genetic Syndrome X"]
        assert len(unknown_clusters) == 1
        assert unknown_clusters[0].mondo_id is None
        assert coverage.clusters_without_mondo_id >= 1

    def test_handles_unknown_mechanism_target_modality(self, builder, sample_records):
        """Uses 'unknown_*' buckets for missing mechanism/target/modality."""
        clusters, _ = builder.build_from_asset_indication_records(sample_records)

        unknown_clusters = [c for c in clusters if c.normalized_disease_name == "Rare Genetic Syndrome X"]
        cluster = unknown_clusters[0]

        assert cluster.mechanism_class == "unknown_mechanism"
        assert cluster.target == "unknown_target"
        assert cluster.modality == "Gene Therapy"  # provided

    def test_aggregates_sorted_public_tickers(self, builder, sample_records):
        """Aggregates and sorts public tickers."""
        clusters, _ = builder.build_from_asset_indication_records(sample_records)

        vrtx_clusters = [c for c in clusters if "SCN10A" in c.target]
        assert vrtx_clusters[0].public_tickers == ["VRTX"]
        assert vrtx_clusters[0].ticker_count == 1

        # Private company cluster has no tickers
        unknown_clusters = [c for c in clusters if c.normalized_disease_name == "Rare Genetic Syndrome X"]
        assert len(unknown_clusters[0].public_tickers) == 0
        assert unknown_clusters[0].ticker_count == 0

    def test_counts_unique_assets_companies_tickers(self, builder, sample_records):
        """Counts unique assets, companies, and tickers."""
        clusters, _ = builder.build_from_asset_indication_records(sample_records)

        vrtx_clusters = [c for c in clusters if "SCN10A" in c.target]
        assert vrtx_clusters[0].asset_count == 1  # VX-548
        assert vrtx_clusters[0].company_count == 1  # VRTX
        assert vrtx_clusters[0].ticker_count == 1

    def test_builds_clinical_stage_distribution(self, builder, sample_records):
        """Builds deterministic clinical stage distribution."""
        clusters, _ = builder.build_from_asset_indication_records(sample_records)

        vrtx_clusters = [c for c in clusters if "SCN10A" in c.target]
        stage_dist = vrtx_clusters[0].clinical_stage_distribution

        assert stage_dist.get("phase3") == 1
        assert stage_dist.get("phase2") == 1

    def test_builds_source_type_distribution(self, builder, sample_records):
        """Builds source_type distribution and source_priority_min."""
        clusters, _ = builder.build_from_asset_indication_records(sample_records)

        vrtx_clusters = [c for c in clusters if "SCN10A" in c.target]
        source_dist = vrtx_clusters[0].source_type_distribution

        assert source_dist.get("ctgov") == 1
        assert source_dist.get("fda_label") == 1
        assert vrtx_clusters[0].source_priority_min == 3  # ctgov is better

    def test_computes_confidence_min_max_mean(self, builder, sample_records):
        """Computes confidence stats descriptively only."""
        clusters, _ = builder.build_from_asset_indication_records(sample_records)

        vrtx_clusters = [c for c in clusters if "SCN10A" in c.target]
        cluster = vrtx_clusters[0]

        # Two records: 0.95 and 0.90 confidence
        assert cluster.confidence_min == 0.90
        assert cluster.confidence_max == 0.95
        assert 0.92 <= cluster.confidence_mean <= 0.93

    def test_mondo_mapping_coverage(self, builder, sample_records):
        """Tracks records with/without mondo_id."""
        clusters, coverage = builder.build_from_asset_indication_records(sample_records)

        vrtx_clusters = [c for c in clusters if "SCN10A" in c.target]
        assert vrtx_clusters[0].records_with_mondo_id == 2
        assert vrtx_clusters[0].records_without_mondo_id == 0

        unknown_clusters = [c for c in clusters if c.normalized_disease_name == "Rare Genetic Syndrome X"]
        assert unknown_clusters[0].records_with_mondo_id == 0
        assert unknown_clusters[0].records_without_mondo_id == 1

    def test_ticker_coverage_tracking(self, builder, sample_records):
        """Tracks records with/without ticker."""
        clusters, _ = builder.build_from_asset_indication_records(sample_records)

        unknown_clusters = [c for c in clusters if c.normalized_disease_name == "Rare Genetic Syndrome X"]
        assert unknown_clusters[0].records_with_ticker == 0
        assert unknown_clusters[0].records_without_ticker == 1

    def test_different_assets_not_collapsed(self, builder):
        """Different assets for same disease/mechanism/target/modality are separate clusters if different."""
        records = [
            AssetIndicationMapRecord(
                record_id="rec001",
                company_id="VRTX",
                asset_name="Asset1",
                normalized_disease_name="Disease",
                mondo_id="MONDO:0001",
                mechanism_class="Mech",
                target="Target",
                modality="Modality",
                source_priority=3,
                source_type="ctgov",
                as_of_date="2026-06-17",
            ),
            AssetIndicationMapRecord(
                record_id="rec002",
                company_id="ACLX",
                asset_name="Asset2",
                normalized_disease_name="Disease",
                mondo_id="MONDO:0001",
                mechanism_class="Mech",
                target="Target",
                modality="Modality",
                source_priority=3,
                source_type="ctgov",
                as_of_date="2026-06-17",
            ),
        ]

        clusters, _ = builder.build_from_asset_indication_records(records)

        # Same disease/mech/target/modality -> 1 cluster
        assert len(clusters) == 1
        assert clusters[0].program_count == 2
        assert clusters[0].asset_count == 2

    def test_different_diseases_not_collapsed(self, builder):
        """Different diseases for same mechanism/target/modality form separate clusters."""
        records = [
            AssetIndicationMapRecord(
                record_id="rec001",
                company_id="VRTX",
                asset_name="Asset1",
                normalized_disease_name="Disease1",
                mondo_id="MONDO:0001",
                mechanism_class="Mech",
                target="Target",
                modality="Modality",
                source_priority=3,
                source_type="ctgov",
                as_of_date="2026-06-17",
            ),
            AssetIndicationMapRecord(
                record_id="rec002",
                company_id="ACLX",
                asset_name="Asset2",
                normalized_disease_name="Disease2",
                mondo_id="MONDO:0002",
                mechanism_class="Mech",
                target="Target",
                modality="Modality",
                source_priority=3,
                source_type="ctgov",
                as_of_date="2026-06-17",
            ),
        ]

        clusters, _ = builder.build_from_asset_indication_records(records)

        # Different diseases -> 2 clusters
        assert len(clusters) == 2

    def test_coverage_report_counts(self, builder, sample_records):
        """Coverage report counts clusters, diseases, mechanisms, tickers."""
        _, coverage = builder.build_from_asset_indication_records(sample_records)

        assert coverage.total_records == 4
        assert coverage.total_clusters == 3
        assert coverage.unique_diseases == 3  # Pain, Myeloma, Rare Syndrome
        assert coverage.unique_mondo_ids == 2  # Two MONDO-mapped diseases
        assert coverage.unique_tickers == 2  # VRTX, ACLX

    def test_governance_flags_correct(self, builder, sample_records):
        """All governance flags are set correctly."""
        clusters, coverage = builder.build_from_asset_indication_records(sample_records)

        # Check records
        for cluster in clusters:
            assert cluster.governance["read_only_diagnostic"] is True
            assert cluster.governance["production_model_change"] is False
            assert cluster.governance["ranker_change"] is False

        # Check coverage
        assert coverage.governance["read_only_diagnostic"] is True
        assert coverage.governance["production_model_change"] is False

    def test_no_scoring_fields(self, builder, sample_records):
        """Records contain no scoring, ranking, or action fields."""
        clusters, _ = builder.build_from_asset_indication_records(sample_records)

        for cluster in clusters:
            # Check that no scoring-related attributes exist
            d = cluster.to_dict()

            forbidden_keys = [
                "score",
                "crowding",
                "white_space",
                "opportunity",
                "attractiveness",
                "conviction",
                "action",
                "buy_sell",
                "weight",
                "alpha",
            ]

            for key in forbidden_keys:
                assert key not in d, f"Forbidden field {key} found in cluster"

    def test_output_jsonl(self, builder, sample_records, tmp_path):
        """Writer outputs deterministic sorted JSONL."""
        clusters, _ = builder.build_from_asset_indication_records(sample_records)

        output_file = tmp_path / "clusters.jsonl"
        builder.write_jsonl(clusters, output_file)

        assert output_file.exists()

        # Verify sorted output
        lines = output_file.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_output_coverage_report(self, builder, sample_records, tmp_path):
        """Writer outputs coverage report as JSON."""
        clusters, coverage = builder.build_from_asset_indication_records(sample_records)

        output_file = tmp_path / "coverage.json"
        builder.write_coverage_report(coverage, output_file)

        assert output_file.exists()

        import json

        d = json.loads(output_file.read_text())
        assert d["total_records"] == 4
        assert d["total_clusters"] == 3

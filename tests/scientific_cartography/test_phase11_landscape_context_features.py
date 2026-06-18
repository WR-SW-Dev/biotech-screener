"""Phase 11 Landscape Context Features tests.

Tests for diagnostic-only context enrichment using Phase 9 and Phase 10 records.
"""

import pytest

from scientific_cartography.build.landscape_context_builder import LandscapeContextFeatureBuilder
from scientific_cartography.schemas.asset_indication_map_schema import AssetIndicationMapRecord
from scientific_cartography.schemas.enhanced_cluster_schema import EnhancedCompetitiveClusterRecord


@pytest.fixture
def builder():
    """Landscape context feature builder fixture."""
    return LandscapeContextFeatureBuilder(as_of_date="2026-06-18")


@pytest.fixture
def sample_asset_records():
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
            as_of_date="2026-06-18",
        ),
        # Same company/disease, different stage
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
            mechanism_class="NaV1.8 Inhibitor",
            target="SCN10A",
            modality="Small Molecule",
            clinical_stage="Phase 2",
            source_priority=3,
            source_type="ctgov",
            source_refs=["clinicaltrials.gov/ct2/show/NCT54321"],
            overall_confidence=0.90,
            as_of_date="2026-06-18",
        ),
        # Same disease, different mechanism
        AssetIndicationMapRecord(
            record_id="rec003",
            company_id="ACLX",
            ticker="ACLX",
            company_name="Aclaris",
            asset_id="asset_atc",
            asset_name="ATI-2138",
            raw_indication="Acute Pain",
            normalized_disease_name="Acute Pain",
            mondo_id="MONDO:0000001",
            therapeutic_area="Pain Management",
            mechanism_class="TRPV1 Antagonist",
            target="TRPV1",
            modality="Small Molecule",
            clinical_stage="Preclinical",
            source_priority=3,
            source_type="ctgov",
            source_refs=["ctgov_search"],
            overall_confidence=0.85,
            as_of_date="2026-06-18",
        ),
        # Different disease
        AssetIndicationMapRecord(
            record_id="rec004",
            company_id="GILD",
            ticker="GILD",
            company_name="Gilead",
            asset_id="asset_hcv",
            asset_name="GS-1234",
            raw_indication="Hepatitis C",
            normalized_disease_name="Hepatitis C",
            mondo_id="MONDO:0005154",
            therapeutic_area="Infectious Disease",
            mechanism_class="NS5A Inhibitor",
            target="NS5A",
            modality="Small Molecule",
            clinical_stage="Approved",
            source_priority=4,
            source_type="fda_label",
            source_refs=["fda_approval_label"],
            overall_confidence=0.98,
            as_of_date="2026-06-18",
        ),
        # Unknown disease
        AssetIndicationMapRecord(
            record_id="rec005",
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
            source_refs=["manual_entry"],
            overall_confidence=0.50,
            as_of_date="2026-06-18",
        ),
    ]


@pytest.fixture
def sample_enhanced_clusters():
    """Sample Phase 10 enhanced cluster records."""
    return [
        # Acute Pain with NaV inhibitor
        EnhancedCompetitiveClusterRecord(
            cluster_id="c001",
            cluster_key="MONDO:0000001|NaV1.8 Inhibitor|SCN10A|Small Molecule",
            disease_key="MONDO:0000001",
            normalized_disease_name="Acute Pain",
            mondo_id="MONDO:0000001",
            therapeutic_area="Pain Management",
            mechanism_class="NaV1.8 Inhibitor",
            target="SCN10A",
            modality="Small Molecule",
            program_count=2,
            asset_count=2,
            company_count=1,
            ticker_count=1,
            public_tickers=["VRTX"],
            company_names=["Vertex Pharmaceuticals"],
            asset_names=["VX-548", "VX-22"],
            clinical_stage_distribution={"phase3": 1, "phase2": 1},
            source_type_distribution={"ctgov": 2},
            source_priority_min=3,
            source_priority_distribution={3: 2},
            records_with_mondo_id=2,
            source_refs=["clinicaltrials.gov/ct2/show/NCT12345"],
            as_of_date="2026-06-18",
        ),
        # Acute Pain with TRPV1 antagonist
        EnhancedCompetitiveClusterRecord(
            cluster_id="c002",
            cluster_key="MONDO:0000001|TRPV1 Antagonist|TRPV1|Small Molecule",
            disease_key="MONDO:0000001",
            normalized_disease_name="Acute Pain",
            mondo_id="MONDO:0000001",
            therapeutic_area="Pain Management",
            mechanism_class="TRPV1 Antagonist",
            target="TRPV1",
            modality="Small Molecule",
            program_count=1,
            asset_count=1,
            company_count=1,
            ticker_count=1,
            public_tickers=["ACLX"],
            company_names=["Aclaris"],
            asset_names=["ATI-2138"],
            clinical_stage_distribution={"preclinical": 1},
            source_type_distribution={"ctgov": 1},
            source_priority_min=3,
            source_priority_distribution={3: 1},
            records_with_mondo_id=1,
            source_refs=["ctgov_search"],
            as_of_date="2026-06-18",
        ),
        # Hepatitis C with NS5A inhibitor
        EnhancedCompetitiveClusterRecord(
            cluster_id="c003",
            cluster_key="MONDO:0005154|NS5A Inhibitor|NS5A|Small Molecule",
            disease_key="MONDO:0005154",
            normalized_disease_name="Hepatitis C",
            mondo_id="MONDO:0005154",
            therapeutic_area="Infectious Disease",
            mechanism_class="NS5A Inhibitor",
            target="NS5A",
            modality="Small Molecule",
            program_count=1,
            asset_count=1,
            company_count=1,
            ticker_count=1,
            public_tickers=["GILD"],
            company_names=["Gilead"],
            asset_names=["GS-1234"],
            clinical_stage_distribution={"approved": 1},
            source_type_distribution={"fda_label": 1},
            source_priority_min=4,
            source_priority_distribution={4: 1},
            records_with_mondo_id=1,
            source_refs=["fda_approval_label"],
            as_of_date="2026-06-18",
        ),
    ]


class TestLandscapeContextSchema:
    """Test schema initialization and serialization."""

    def test_record_initialization(self):
        """Record initializes with required fields."""
        from scientific_cartography.schemas.landscape_context_schema import LandscapeContextFeatureRecord

        record = LandscapeContextFeatureRecord(
            feature_id="abc123",
            source_record_id="rec001",
        )

        assert record.feature_id == "abc123"
        assert record.source_record_id == "rec001"
        assert record.governance["read_only_diagnostic"] is True
        assert record.governance["production_model_change"] is False

    def test_record_to_dict(self):
        """Record serializes to dictionary."""
        from scientific_cartography.schemas.landscape_context_schema import LandscapeContextFeatureRecord

        record = LandscapeContextFeatureRecord(
            feature_id="test123",
            source_record_id="rec001",
            cluster_id="c001",
            company_id="VRTX",
            mechanism_novelty_category="well_represented",
            white_space_category="crowded_context",
            as_of_date="2026-06-18",
        )

        d = record.to_dict()
        assert d["feature_id"] == "test123"
        assert d["mechanism_novelty_category"] == "well_represented"
        assert d["governance"]["read_only_diagnostic"] is True


class TestLandscapeContextBuilder:
    """Test builder and context computation."""

    def test_builds_features_from_records(self, builder, sample_asset_records, sample_enhanced_clusters):
        """Builds context features from Phase 9/10 records."""
        features, coverage = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        # Should have 5 features (one per record)
        assert len(features) == 5
        assert coverage.total_features == 5

    def test_emits_one_feature_per_record(self, builder, sample_asset_records, sample_enhanced_clusters):
        """Emits exactly one feature per asset-indication record."""
        features, _ = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        # Count should match input records
        assert len(features) == len(sample_asset_records)

    def test_matches_records_to_clusters(self, builder, sample_asset_records, sample_enhanced_clusters):
        """Matches records to clusters using Phase 10 key logic."""
        features, coverage = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        # VRTX acute pain records should match cluster
        vrtx_features = [f for f in features if f.company_id == "VRTX"]
        assert len(vrtx_features) == 2
        assert all(f.cluster_id is not None for f in vrtx_features)
        assert all(f.cluster_id == "c001" for f in vrtx_features)

    def test_emits_feature_when_cluster_missing(self, builder, sample_asset_records, sample_enhanced_clusters):
        """Emits feature even when cluster is missing."""
        features, coverage = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        # Unknown disease record (rec005) should not have cluster
        unknown_features = [f for f in features if f.mondo_id is None]
        assert len(unknown_features) > 0
        unknown_feature = unknown_features[0]
        assert unknown_feature.cluster_id is None
        assert "cluster_not_found" in unknown_feature.warnings

    def test_computes_disease_competition_count(self, builder, sample_asset_records, sample_enhanced_clusters):
        """Computes disease_competition_count across disease key."""
        features, _ = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        # Acute Pain disease has 3 records
        pain_features = [f for f in features if f.normalized_disease_name == "Acute Pain"]
        assert len(pain_features) == 3
        assert all(f.disease_competition_count == 3 for f in pain_features)

    def test_computes_same_mechanism_competition_count(self, builder, sample_asset_records, sample_enhanced_clusters):
        """Computes same_mechanism_competition_count from cluster."""
        features, _ = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        # NaV inhibitor cluster has 2 programs
        nav_features = [f for f in features if f.mechanism_class == "NaV1.8 Inhibitor"]
        assert all(f.same_mechanism_competition_count == 2 for f in nav_features)

        # TRPV1 cluster has 1 program
        trpv_features = [f for f in features if f.mechanism_class == "TRPV1 Antagonist"]
        assert all(f.same_mechanism_competition_count == 1 for f in trpv_features)

    def test_categorizes_mechanism_novelty_deterministically(
        self, builder, sample_asset_records, sample_enhanced_clusters
    ):
        """Assigns mechanism_novelty_category deterministically."""
        features, _ = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        # NaV (2 programs) should be moderately_represented
        nav_features = [f for f in features if f.mechanism_class == "NaV1.8 Inhibitor"]
        assert all(f.mechanism_novelty_category == "moderately_represented" for f in nav_features)

        # TRPV1 (1 program) should be novel_or_sparse
        trpv_features = [f for f in features if f.mechanism_class == "TRPV1 Antagonist"]
        assert all(f.mechanism_novelty_category == "novel_or_sparse" for f in trpv_features)

    def test_categorizes_target_disease_evidence(self, builder, sample_asset_records, sample_enhanced_clusters):
        """Assigns target_disease_evidence_category deterministically."""
        features, _ = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        # FDA label (curated source) should be curated_or_regulatory
        hcv_feature = [f for f in features if f.mondo_id == "MONDO:0005154"][0]
        assert hcv_feature.target_disease_evidence_category == "curated_or_regulatory_source_present"

    def test_trial_design_strength_defaults_to_unknown(self, builder, sample_asset_records, sample_enhanced_clusters):
        """trial_design_strength_category defaults to unknown."""
        features, _ = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        # All features should have unknown trial design
        assert all(f.trial_design_strength_category == "unknown" for f in features)

    def test_next_readout_days_defaults_to_null(self, builder, sample_asset_records, sample_enhanced_clusters):
        """next_readout_days defaults to null when unavailable."""
        features, _ = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        # All features should have null next_readout_days
        assert all(f.next_readout_days is None for f in features)

    def test_categorizes_white_space(self, builder, sample_asset_records, sample_enhanced_clusters):
        """Assigns white_space_category deterministically."""
        features, _ = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        # Acute Pain (3 programs in disease) should be moderate_context
        pain_features = [f for f in features if f.normalized_disease_name == "Acute Pain"]
        assert all(f.white_space_category == "moderate_context" for f in pain_features)

        # HCV (1 program) should be sparse_context
        hcv_features = [f for f in features if f.mondo_id == "MONDO:0005154"]
        assert all(f.white_space_category == "sparse_context" for f in hcv_features)

    def test_categorizes_crowding(self, builder, sample_asset_records, sample_enhanced_clusters):
        """Assigns crowding_category deterministically."""
        features, _ = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        # NaV (2 programs, no approved) should be moderate
        nav_features = [f for f in features if f.mechanism_class == "NaV1.8 Inhibitor"]
        assert all(f.crowding_category == "moderate" for f in nav_features)

        # HCV approved should be moderate or high
        hcv_feature = [f for f in features if f.mondo_id == "MONDO:0005154"][0]
        assert hcv_feature.crowding_category in ["moderate", "high"]

    def test_preserves_record_fields(self, builder, sample_asset_records, sample_enhanced_clusters):
        """Preserves ticker/company/asset/disease fields."""
        features, _ = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        # Check VRTX record preservation (check both records)
        vrtx_features = [f for f in features if f.company_id == "VRTX"]
        assert len(vrtx_features) == 2
        for feature in vrtx_features:
            assert feature.ticker == "VRTX"
            assert feature.asset_name in ["VX-548", "VX-22"]
            assert feature.normalized_disease_name == "Acute Pain"

    def test_deduplicates_source_refs(self, builder, sample_asset_records, sample_enhanced_clusters):
        """Deduplicates source_refs."""
        # Create records with overlapping refs
        records = [sample_asset_records[0]]
        clusters = [
            EnhancedCompetitiveClusterRecord(
                cluster_id="c001",
                cluster_key="MONDO:0000001|NaV1.8 Inhibitor|SCN10A|Small Molecule",
                disease_key="MONDO:0000001",
                normalized_disease_name="Acute Pain",
                mondo_id="MONDO:0000001",
                source_refs=["clinicaltrials.gov/ct2/show/NCT12345", "manual_source"],
                as_of_date="2026-06-18",
            )
        ]

        features, _ = builder.build_from_records(records, clusters)
        feature = features[0]

        # Should have deduplicated refs
        assert len(feature.source_refs) == len(set(feature.source_refs))

    def test_coverage_report_counts_categories(self, builder, sample_asset_records, sample_enhanced_clusters):
        """Coverage report counts category distributions."""
        _, coverage = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        assert coverage.total_features == 5
        assert "moderately_represented" in coverage.category_counts_mechanism_novelty
        assert "well_represented" not in coverage.category_counts_mechanism_novelty
        assert "novel_or_sparse" in coverage.category_counts_mechanism_novelty

    def test_governance_flags_present_and_correct(self, builder, sample_asset_records, sample_enhanced_clusters):
        """Governance flags present and production/model changes false."""
        features, coverage = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        # Check records
        for feature in features:
            assert feature.governance["read_only_diagnostic"] is True
            assert feature.governance["production_model_change"] is False
            assert feature.governance["ranker_change"] is False
            assert feature.governance["selector_change"] is False

        # Check coverage
        assert coverage.governance["read_only_diagnostic"] is True
        assert coverage.governance["production_model_change"] is False

    def test_no_scoring_fields_in_output(self, builder, sample_asset_records, sample_enhanced_clusters):
        """Records contain no scoring, ranking, or action fields."""
        features, _ = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        forbidden_keys = [
            "score",
            "attractiveness",
            "conviction",
            "buy",
            "sell",
            "weight",
            "alpha",
        ]

        for feature in features:
            d = feature.to_dict()
            for key in forbidden_keys:
                assert key not in d, f"Forbidden field {key} found in feature"

    def test_output_jsonl(self, builder, sample_asset_records, sample_enhanced_clusters, tmp_path):
        """Writer outputs deterministic sorted JSONL."""
        features, _ = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        output_file = tmp_path / "features.jsonl"
        builder.write_jsonl(features, output_file)

        assert output_file.exists()
        lines = output_file.read_text().strip().split("\n")
        assert len(lines) == 5

    def test_output_coverage_report(self, builder, sample_asset_records, sample_enhanced_clusters, tmp_path):
        """Writer outputs coverage report as JSON."""
        features, coverage = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        output_file = tmp_path / "coverage.json"
        builder.write_coverage_report(coverage, output_file)

        assert output_file.exists()

        import json

        d = json.loads(output_file.read_text())
        assert d["total_features"] == 5
        assert d["records_with_cluster"] == 4
        assert d["records_without_cluster"] == 1

    def test_deterministic_sorting(self, builder, sample_asset_records, sample_enhanced_clusters):
        """Features are sorted deterministically by feature_id."""
        features, _ = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        feature_ids = [f.feature_id for f in features]
        assert feature_ids == sorted(feature_ids)

    def test_computes_cluster_supporting_counts(self, builder, sample_asset_records, sample_enhanced_clusters):
        """Copies supporting cluster counts for auditability."""
        features, _ = builder.build_from_records(sample_asset_records, sample_enhanced_clusters)

        # NaV feature should have cluster counts
        nav_feature = [f for f in features if f.mechanism_class == "NaV1.8 Inhibitor"][0]
        assert nav_feature.supporting_cluster_program_count == 2
        assert nav_feature.supporting_cluster_asset_count == 2
        assert nav_feature.supporting_cluster_company_count == 1

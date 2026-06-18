"""Landscape context feature schema for Phase 11 diagnostic enrichment.

LandscapeContextFeatureRecord provides diagnostic descriptors of competitive
and evidentiary context for each asset-indication record. This is a read-only
diagnostic reference layer built from Phase 9 and Phase 10 outputs.

No scoring, ranking, selection, sizing, or production model changes.
"""

from dataclasses import dataclass, field


@dataclass
class LandscapeContextFeatureRecord:
    """Diagnostic context feature record linking indication to competitive landscape.

    READ_ONLY_DIAGNOSTIC: This layer provides descriptive context about competitive
    and evidentiary surroundings for each company/asset/disease indication. It does
    not affect scoring, ranking, selection, sizing, or portfolio construction.

    Categories are deterministic and descriptive only—not scoring signals.
    """

    feature_id: str
    """Deterministic SHA256: source_record_id|cluster_id|as_of_date[:16]."""

    source_record_id: str
    """Phase 9 AssetIndicationMapRecord.record_id."""

    cluster_id: str | None = None
    """Phase 10 EnhancedCompetitiveClusterRecord.cluster_id; null if not found."""

    cluster_key: str | None = None
    """Phase 10 cluster_key: disease|mechanism|target|modality."""

    company_id: str | None = None
    """Company ID from source record."""

    ticker: str | None = None
    """Stock ticker if public company."""

    company_name: str | None = None
    """Company name from source record."""

    asset_id: str | None = None
    """Asset ID from source record."""

    asset_name: str = ""
    """Asset name from source record."""

    raw_indication: str = ""
    """Raw indication from source record."""

    normalized_disease_name: str = ""
    """Normalized disease name from Phase 9."""

    mondo_id: str | None = None
    """MONDO disease ID from Phase 9; null if unmapped."""

    therapeutic_area: str | None = None
    """Therapeutic area from Phase 9 ontology."""

    mechanism_class: str | None = None
    """Mechanism class from source record."""

    target: str | None = None
    """Drug target from source record."""

    modality: str | None = None
    """Modality from source record."""

    clinical_stage: str | None = None
    """Clinical stage from source record."""

    disease_competition_count: int = 0
    """Count of asset-indication records sharing same disease key."""

    same_mechanism_competition_count: int = 0
    """Count of records in same disease + same mechanism cluster."""

    same_stage_competition_count: int = 0
    """Count of records in same cluster and same clinical stage."""

    approved_incumbent_count: int = 0
    """Count of records in same disease with clinical_stage approved."""

    mechanism_novelty_category: str = "unknown"
    """Descriptive category: unknown, novel_or_sparse, moderately_represented, well_represented."""

    target_disease_evidence_category: str = "unknown"
    """Descriptive category: unknown, single_source, multi_source, curated_or_regulatory_source_present."""

    trial_design_strength_category: str = "unknown"
    """Descriptive category: unknown, basic_metadata_present. Defaults to unknown."""

    next_readout_days: int | None = None
    """Nullable: days until next readout; null if unavailable."""

    white_space_category: str = "unknown"
    """Descriptive category: unknown, sparse_context, moderate_context, crowded_context."""

    crowding_category: str = "unknown"
    """Descriptive category: unknown, low, moderate, high."""

    supporting_cluster_program_count: int = 0
    """Programs in matching cluster (copied from Phase 10)."""

    supporting_cluster_asset_count: int = 0
    """Assets in matching cluster (copied from Phase 10)."""

    supporting_cluster_company_count: int = 0
    """Companies in matching cluster (copied from Phase 10)."""

    supporting_cluster_ticker_count: int = 0
    """Tickers in matching cluster (copied from Phase 10)."""

    source_type_distribution: dict[str, int] = field(default_factory=dict)
    """Source type counts from cluster (for evidence support)."""

    clinical_stage_distribution: dict[str, int] = field(default_factory=dict)
    """Clinical stage distribution from cluster."""

    source_refs: list[str] = field(default_factory=list)
    """Deduplicated, sorted source references from record and cluster."""

    as_of_date: str = ""
    """Date of feature snapshot (YYYY-MM-DD)."""

    warnings: list[str] = field(default_factory=list)
    """Diagnostic warnings (cluster_not_found, trial_design_unavailable, etc.)."""

    governance: dict = field(
        default_factory=lambda: {
            "read_only_diagnostic": True,
            "context_features_only": True,
            "descriptive_not_scoring": True,
            "production_model_change": False,
            "ranker_change": False,
            "selector_change": False,
            "sizing_change": False,
            "final_score_change": False,
            "alpha_promotion": False,
        }
    )
    """Governance flags—all production changes are false."""

    def to_dict(self) -> dict:
        """Convert to dictionary for JSONL serialization."""
        return {
            "feature_id": self.feature_id,
            "source_record_id": self.source_record_id,
            "cluster_id": self.cluster_id,
            "cluster_key": self.cluster_key,
            "company_id": self.company_id,
            "ticker": self.ticker,
            "company_name": self.company_name,
            "asset_id": self.asset_id,
            "asset_name": self.asset_name,
            "raw_indication": self.raw_indication,
            "normalized_disease_name": self.normalized_disease_name,
            "mondo_id": self.mondo_id,
            "therapeutic_area": self.therapeutic_area,
            "mechanism_class": self.mechanism_class,
            "target": self.target,
            "modality": self.modality,
            "clinical_stage": self.clinical_stage,
            "disease_competition_count": self.disease_competition_count,
            "same_mechanism_competition_count": self.same_mechanism_competition_count,
            "same_stage_competition_count": self.same_stage_competition_count,
            "approved_incumbent_count": self.approved_incumbent_count,
            "mechanism_novelty_category": self.mechanism_novelty_category,
            "target_disease_evidence_category": self.target_disease_evidence_category,
            "trial_design_strength_category": self.trial_design_strength_category,
            "next_readout_days": self.next_readout_days,
            "white_space_category": self.white_space_category,
            "crowding_category": self.crowding_category,
            "supporting_cluster_program_count": self.supporting_cluster_program_count,
            "supporting_cluster_asset_count": self.supporting_cluster_asset_count,
            "supporting_cluster_company_count": self.supporting_cluster_company_count,
            "supporting_cluster_ticker_count": self.supporting_cluster_ticker_count,
            "source_type_distribution": self.source_type_distribution,
            "clinical_stage_distribution": self.clinical_stage_distribution,
            "source_refs": self.source_refs,
            "as_of_date": self.as_of_date,
            "warnings": self.warnings,
            "governance": self.governance,
        }


@dataclass
class LandscapeContextCoverageReport:
    """Coverage report for landscape context feature layer."""

    as_of_date: str
    """Report date (YYYY-MM-DD)."""

    total_features: int = 0
    """Total context features generated."""

    records_with_cluster: int = 0
    """Features with matching cluster found."""

    records_without_cluster: int = 0
    """Features with no matching cluster."""

    unique_companies: int = 0
    """Unique companies across all features."""

    unique_tickers: int = 0
    """Unique tickers across all features."""

    unique_assets: int = 0
    """Unique assets across all features."""

    unique_diseases: int = 0
    """Unique diseases across all features."""

    unique_mondo_ids: int = 0
    """Unique non-null MONDO IDs."""

    unique_mechanisms: int = 0
    """Unique mechanisms (excluding unknown)."""

    unique_targets: int = 0
    """Unique targets (excluding unknown)."""

    unique_modalities: int = 0
    """Unique modalities."""

    category_counts_mechanism_novelty: dict[str, int] = field(default_factory=dict)
    """Count of features by mechanism_novelty_category."""

    category_counts_target_disease_evidence: dict[str, int] = field(default_factory=dict)
    """Count of features by target_disease_evidence_category."""

    category_counts_trial_design_strength: dict[str, int] = field(default_factory=dict)
    """Count of features by trial_design_strength_category."""

    category_counts_white_space: dict[str, int] = field(default_factory=dict)
    """Count of features by white_space_category."""

    category_counts_crowding: dict[str, int] = field(default_factory=dict)
    """Count of features by crowding_category."""

    features_with_next_readout_days: int = 0
    """Features with non-null next_readout_days."""

    features_without_next_readout_days: int = 0
    """Features with null next_readout_days."""

    features_with_warnings: int = 0
    """Features with one or more warnings."""

    warnings: list[str] = field(default_factory=list)
    """Aggregate warnings across all features."""

    governance: dict = field(
        default_factory=lambda: {
            "read_only_diagnostic": True,
            "context_features_only": True,
            "descriptive_not_scoring": True,
            "production_model_change": False,
            "ranker_change": False,
            "selector_change": False,
            "sizing_change": False,
            "final_score_change": False,
            "alpha_promotion": False,
        }
    )
    """Governance flags."""

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "as_of_date": self.as_of_date,
            "total_features": self.total_features,
            "records_with_cluster": self.records_with_cluster,
            "records_without_cluster": self.records_without_cluster,
            "unique_companies": self.unique_companies,
            "unique_tickers": self.unique_tickers,
            "unique_assets": self.unique_assets,
            "unique_diseases": self.unique_diseases,
            "unique_mondo_ids": self.unique_mondo_ids,
            "unique_mechanisms": self.unique_mechanisms,
            "unique_targets": self.unique_targets,
            "unique_modalities": self.unique_modalities,
            "category_counts_mechanism_novelty": self.category_counts_mechanism_novelty,
            "category_counts_target_disease_evidence": self.category_counts_target_disease_evidence,
            "category_counts_trial_design_strength": self.category_counts_trial_design_strength,
            "category_counts_white_space": self.category_counts_white_space,
            "category_counts_crowding": self.category_counts_crowding,
            "features_with_next_readout_days": self.features_with_next_readout_days,
            "features_without_next_readout_days": self.features_without_next_readout_days,
            "features_with_warnings": self.features_with_warnings,
            "warnings": self.warnings,
            "governance": self.governance,
        }

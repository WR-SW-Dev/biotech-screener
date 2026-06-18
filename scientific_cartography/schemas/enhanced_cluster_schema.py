"""Enhanced competitive cluster schema with Phase 9 disease ontology enrichment.

EnhancedCompetitiveClusterRecord extends cluster data with MONDO disease mapping,
therapeutic area classification, and source priority distribution—diagnostic-only,
no scoring or portfolio features.
"""

from dataclasses import dataclass, field


@dataclass
class EnhancedCompetitiveClusterRecord:
    """Enhanced cluster record with Phase 8/9 disease ontology and source enrichment.

    READ_ONLY_DIAGNOSTIC: This layer enriches cluster structure with disease mapping
    and source distribution data. It does not affect scoring, ranking, selection, or
    portfolio construction.
    """

    cluster_id: str
    """Deterministic SHA256: mondo_id|mechanism_class|target|modality|as_of_date[:16]."""

    cluster_key: str = ""
    """Canonical cluster key: disease_key|mechanism_class|target|modality."""

    disease_key: str = ""
    """Primary disease identifier: mondo_id > normalized_disease_name > unknown."""

    normalized_disease_name: str = ""
    """Phase 8 canonical disease name (or raw_indication if unmapped)."""

    mondo_id: str | None = None
    """Phase 8 MONDO disease ID; null if unmapped."""

    therapeutic_area: str | None = None
    """Therapeutic area from Phase 8 ontology; null if unknown."""

    parent_disease: str | None = None
    """Parent disease category from Phase 8 hierarchy; null if none."""

    mechanism_class: str | None = None
    """Mechanism class (or 'unknown_mechanism')."""

    target: str | None = None
    """Drug target (or 'unknown_target')."""

    modality: str | None = None
    """Modality (or 'unknown_modality')."""

    program_count: int = 0
    """Total AssetIndicationMapRecords in cluster."""

    asset_count: int = 0
    """Unique asset_id or asset_name count."""

    company_count: int = 0
    """Unique company_id or company_name count."""

    ticker_count: int = 0
    """Unique non-null ticker count."""

    public_tickers: list[str] = field(default_factory=list)
    """Sorted list of public tickers (deduplicated)."""

    company_names: list[str] = field(default_factory=list)
    """Sorted list of company names (deduplicated)."""

    sponsor_names: list[str] = field(default_factory=list)
    """Sorted list of sponsor names (deduplicated)."""

    asset_names: list[str] = field(default_factory=list)
    """Sorted list of asset names (deduplicated)."""

    asset_ids: list[str] = field(default_factory=list)
    """Sorted list of asset IDs (deduplicated)."""

    clinical_stage_distribution: dict[str, int] = field(default_factory=dict)
    """Count of records by clinical stage (preclinical, phase1-3, filed, approved, unknown)."""

    source_type_distribution: dict[str, int] = field(default_factory=dict)
    """Count of records by source_type (ctgov, fda, ctgov, investor_deck, etc.)."""

    source_priority_min: int = 9
    """Best source priority in cluster (lower is better: 1=sec, 9=unknown)."""

    source_priority_distribution: dict[int, int] = field(default_factory=dict)
    """Count of records by source_priority (1-9)."""

    records_with_mondo_id: int = 0
    """Records with non-null mondo_id (Phase 8 mapped)."""

    records_without_mondo_id: int = 0
    """Records with null mondo_id (unmapped)."""

    records_with_ticker: int = 0
    """Records with non-null ticker."""

    records_without_ticker: int = 0
    """Records with null ticker."""

    records_with_target: int = 0
    """Records with non-null target."""

    records_without_target: int = 0
    """Records with null target."""

    records_with_mechanism: int = 0
    """Records with non-null mechanism_class."""

    records_without_mechanism: int = 0
    """Records with null mechanism_class."""

    confidence_min: float = 0.0
    """Minimum overall_confidence in cluster (descriptive only)."""

    confidence_max: float = 0.0
    """Maximum overall_confidence in cluster (descriptive only)."""

    confidence_mean: float = 0.0
    """Mean overall_confidence in cluster (descriptive only, not a scoring signal)."""

    source_refs: list[str] = field(default_factory=list)
    """Deduplicated, sorted source_refs from member records."""

    as_of_date: str = ""
    """Date of cluster snapshot (YYYY-MM-DD)."""

    warnings: list[str] = field(default_factory=list)
    """Diagnostic warnings (missing disease, missing mechanism, missing ticker, etc.)."""

    governance: dict = field(
        default_factory=lambda: {
            "read_only_diagnostic": True,
            "count_structure_only": True,
            "reference_cluster_layer_only": True,
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
            "cluster_id": self.cluster_id,
            "cluster_key": self.cluster_key,
            "disease_key": self.disease_key,
            "normalized_disease_name": self.normalized_disease_name,
            "mondo_id": self.mondo_id,
            "therapeutic_area": self.therapeutic_area,
            "parent_disease": self.parent_disease,
            "mechanism_class": self.mechanism_class,
            "target": self.target,
            "modality": self.modality,
            "program_count": self.program_count,
            "asset_count": self.asset_count,
            "company_count": self.company_count,
            "ticker_count": self.ticker_count,
            "public_tickers": self.public_tickers,
            "company_names": self.company_names,
            "sponsor_names": self.sponsor_names,
            "asset_names": self.asset_names,
            "asset_ids": self.asset_ids,
            "clinical_stage_distribution": self.clinical_stage_distribution,
            "source_type_distribution": self.source_type_distribution,
            "source_priority_min": self.source_priority_min,
            "source_priority_distribution": self.source_priority_distribution,
            "records_with_mondo_id": self.records_with_mondo_id,
            "records_without_mondo_id": self.records_without_mondo_id,
            "records_with_ticker": self.records_with_ticker,
            "records_without_ticker": self.records_without_ticker,
            "records_with_target": self.records_with_target,
            "records_without_target": self.records_without_target,
            "records_with_mechanism": self.records_with_mechanism,
            "records_without_mechanism": self.records_without_mechanism,
            "confidence_min": round(self.confidence_min, 4),
            "confidence_max": round(self.confidence_max, 4),
            "confidence_mean": round(self.confidence_mean, 4),
            "source_refs": self.source_refs,
            "as_of_date": self.as_of_date,
            "warnings": self.warnings,
            "governance": self.governance,
        }


@dataclass
class EnhancedClusterCoverageReport:
    """Coverage report for enhanced cluster layer."""

    as_of_date: str
    """Report date (YYYY-MM-DD)."""

    total_records: int = 0
    """Total AssetIndicationMapRecords processed."""

    total_clusters: int = 0
    """Total clusters formed."""

    unique_diseases: int = 0
    """Unique normalized_disease_name values."""

    unique_mondo_ids: int = 0
    """Unique non-null mondo_id values."""

    unique_therapeutic_areas: int = 0
    """Unique therapeutic_area values."""

    unique_mechanisms: int = 0
    """Unique mechanism_class values (excluding unknown)."""

    unique_targets: int = 0
    """Unique target values (excluding unknown)."""

    unique_modalities: int = 0
    """Unique modality values (excluding unknown)."""

    unique_assets: int = 0
    """Unique assets across all clusters."""

    unique_companies: int = 0
    """Unique companies across all clusters."""

    unique_tickers: int = 0
    """Unique non-null tickers across all clusters."""

    clusters_with_ticker: int = 0
    """Clusters with at least one non-null ticker."""

    clusters_without_ticker: int = 0
    """Clusters with no non-null tickers."""

    clusters_with_mondo_id: int = 0
    """Clusters with non-null mondo_id."""

    clusters_without_mondo_id: int = 0
    """Clusters with null mondo_id."""

    clusters_with_known_mechanism: int = 0
    """Clusters with non-'unknown_mechanism' mechanism."""

    clusters_with_known_target: int = 0
    """Clusters with non-'unknown_target' target."""

    records_by_source_type: dict[str, int] = field(default_factory=dict)
    """Count of records by source_type."""

    clusters_by_therapeutic_area: dict[str, int] = field(default_factory=dict)
    """Count of clusters by therapeutic_area."""

    clusters_by_stage_bucket: dict[str, int] = field(default_factory=dict)
    """Count of clusters by primary stage (approved, filed, phase1-3, etc.)."""

    warnings: list[str] = field(default_factory=list)
    """Diagnostic warnings."""

    governance: dict = field(
        default_factory=lambda: {
            "read_only_diagnostic": True,
            "count_structure_only": True,
            "reference_cluster_layer_only": True,
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
        """Convert to dictionary."""
        return {
            "as_of_date": self.as_of_date,
            "total_records": self.total_records,
            "total_clusters": self.total_clusters,
            "unique_diseases": self.unique_diseases,
            "unique_mondo_ids": self.unique_mondo_ids,
            "unique_therapeutic_areas": self.unique_therapeutic_areas,
            "unique_mechanisms": self.unique_mechanisms,
            "unique_targets": self.unique_targets,
            "unique_modalities": self.unique_modalities,
            "unique_assets": self.unique_assets,
            "unique_companies": self.unique_companies,
            "unique_tickers": self.unique_tickers,
            "clusters_with_ticker": self.clusters_with_ticker,
            "clusters_without_ticker": self.clusters_without_ticker,
            "clusters_with_mondo_id": self.clusters_with_mondo_id,
            "clusters_without_mondo_id": self.clusters_without_mondo_id,
            "clusters_with_known_mechanism": self.clusters_with_known_mechanism,
            "clusters_with_known_target": self.clusters_with_known_target,
            "records_by_source_type": self.records_by_source_type,
            "clusters_by_therapeutic_area": self.clusters_by_therapeutic_area,
            "clusters_by_stage_bucket": self.clusters_by_stage_bucket,
            "warnings": self.warnings,
            "governance": self.governance,
        }

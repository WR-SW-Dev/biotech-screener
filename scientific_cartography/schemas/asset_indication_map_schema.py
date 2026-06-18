"""Asset indication map schema for diagnostic reference layer.

AssetIndicationMapRecord enriches ProgramRecord with Phase 8 disease ontology
resolution and explicit governance/source tracking for read-only diagnostics.

Maps: company / ticker / asset → raw indication → canonical disease (MONDO)
with source evidence and confidence scoring.
"""

from dataclasses import dataclass, field


@dataclass
class AssetIndicationMapRecord:
    """Diagnostic mapping record linking company, asset, and disease with provenance.

    This is a READ-ONLY diagnostic/reference layer. It wraps and enhances
    ProgramRecord with Phase 8 disease ontology results and explicit governance.

    Does not alter scoring, ranking, selection, sizing, or portfolio construction.
    """

    record_id: str
    """Deterministic SHA256 hash: company_id|asset_id|disease_name|mondo_id|source_type|as_of_date[:16]."""

    company_id: str | None = None
    """Internal company ID if public; null if private/unknown."""

    ticker: str | None = None
    """Stock ticker if public company; null if private/unknown."""

    company_name: str | None = None
    """Canonical company name if available."""

    sponsor_name: str | None = None
    """Raw sponsor name from source."""

    asset_id: str | None = None
    """Internal asset identifier; null if new."""

    asset_name: str = ""
    """Asset/compound/program name."""

    asset_aliases: list[str] = field(default_factory=list)
    """Known aliases for asset."""

    raw_indication: str = ""
    """Raw disease/condition/indication from source."""

    normalized_disease_name: str = ""
    """Phase 8 canonical normalized disease name."""

    mondo_id: str | None = None
    """Phase 8 MONDO disease ID; null if unmapped."""

    therapeutic_area: str | None = None
    """Therapeutic area from Phase 8 ontology; null if unknown."""

    parent_disease: str | None = None
    """Parent disease category from Phase 8 hierarchy; null if none."""

    mechanism_class: str | None = None
    """Mechanism (e.g., JAK1 inhibitor); null if unknown."""

    target: str | None = None
    """Drug target (e.g., JAK1, IL13); null if unknown."""

    modality: str | None = None
    """Modality (small molecule, mAb, cell therapy); null if unknown."""

    clinical_stage: str | None = None
    """Clinical stage (preclinical, phase1-3, filed, approved); null if unknown."""

    source_priority: int = 9
    """Deterministic priority: 1=sec, 2=deck, 3=ctgov, 4=fda, 5=ot, 6=chembl, 7=pubmed, 8=manual, 9=unknown."""

    source_type: str = "unknown"
    """Source type: sec_filing, investor_deck, ctgov, fda_label, open_targets, chembl, pubmed, manual_override, unknown."""

    source_refs: list[str] = field(default_factory=list)
    """References to source documents/files."""

    evidence_text: str | None = None
    """Short evidence excerpt if available; null for derived records."""

    disease_ontology_confidence: float = 0.0
    """Phase 8 disease resolution confidence (0.0–1.0)."""

    overall_confidence: float = 0.0
    """Overall confidence considering source and disease resolution (0.0–1.0)."""

    as_of_date: str = ""
    """Record date (YYYY-MM-DD)."""

    warnings: list[str] = field(default_factory=list)
    """Warnings (ambiguous disease, missing fields, etc.)."""

    governance: dict = field(
        default_factory=lambda: {
            "read_only_diagnostic": True,
            "reference_mapping_layer_only": True,
            "production_model_change": False,
            "ranker_change": False,
            "selector_change": False,
            "sizing_change": False,
            "final_score_change": False,
            "alpha_promotion": False,
        }
    )
    """Governance flags (all production changes are false)."""

    def to_dict(self) -> dict:
        """Convert to dictionary for JSONL serialization."""
        return {
            "record_id": self.record_id,
            "company_id": self.company_id,
            "ticker": self.ticker,
            "company_name": self.company_name,
            "sponsor_name": self.sponsor_name,
            "asset_id": self.asset_id,
            "asset_name": self.asset_name,
            "asset_aliases": self.asset_aliases,
            "raw_indication": self.raw_indication,
            "normalized_disease_name": self.normalized_disease_name,
            "mondo_id": self.mondo_id,
            "therapeutic_area": self.therapeutic_area,
            "parent_disease": self.parent_disease,
            "mechanism_class": self.mechanism_class,
            "target": self.target,
            "modality": self.modality,
            "clinical_stage": self.clinical_stage,
            "source_priority": self.source_priority,
            "source_type": self.source_type,
            "source_refs": self.source_refs,
            "evidence_text": self.evidence_text,
            "disease_ontology_confidence": round(self.disease_ontology_confidence, 4),
            "overall_confidence": round(self.overall_confidence, 4),
            "as_of_date": self.as_of_date,
            "warnings": self.warnings,
            "governance": self.governance,
        }


@dataclass
class AssetIndicationMapCoverageReport:
    """Coverage report for asset indication mapping."""

    as_of_date: str
    """Record date (YYYY-MM-DD)."""

    total_records: int = 0
    """Total asset indication records."""

    unique_companies: int = 0
    """Count of unique companies."""

    unique_tickers: int = 0
    """Count of unique public tickers."""

    unique_assets: int = 0
    """Count of unique assets."""

    unique_raw_indications: int = 0
    """Count of unique raw disease names."""

    unique_mondo_diseases: int = 0
    """Count of unique MONDO-mapped diseases."""

    mapped_disease_count: int = 0
    """Records with mondo_id (Phase 8 resolved)."""

    unknown_disease_count: int = 0
    """Records with mondo_id=null."""

    records_by_source_type: dict[str, int] = field(default_factory=dict)
    """Count by source_type (ctgov, sec_filing, etc.)."""

    records_by_source_priority: dict[int, int] = field(default_factory=dict)
    """Count by source_priority (1-9)."""

    records_by_therapeutic_area: dict[str, int] = field(default_factory=dict)
    """Count by therapeutic_area."""

    records_by_clinical_stage: dict[str, int] = field(default_factory=dict)
    """Count by clinical_stage."""

    records_with_ticker: int = 0
    """Records with non-null ticker."""

    records_without_ticker: int = 0
    """Records with null ticker."""

    records_with_mondo_id: int = 0
    """Records with non-null mondo_id."""

    records_without_mondo_id: int = 0
    """Records with null mondo_id."""

    warnings: list[str] = field(default_factory=list)
    """Warnings during processing."""

    governance: dict = field(
        default_factory=lambda: {
            "read_only_diagnostic": True,
            "reference_mapping_layer_only": True,
            "production_model_change": False,
            "ranker_change": False,
            "selector_change": False,
            "sizing_change": False,
            "final_score_change": False,
            "alpha_promotion": False,
        }
    )
    """Governance flags (all false for production changes)."""

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "as_of_date": self.as_of_date,
            "total_records": self.total_records,
            "unique_companies": self.unique_companies,
            "unique_tickers": self.unique_tickers,
            "unique_assets": self.unique_assets,
            "unique_raw_indications": self.unique_raw_indications,
            "unique_mondo_diseases": self.unique_mondo_diseases,
            "mapped_disease_count": self.mapped_disease_count,
            "unknown_disease_count": self.unknown_disease_count,
            "records_by_source_type": self.records_by_source_type,
            "records_by_source_priority": self.records_by_source_priority,
            "records_by_therapeutic_area": self.records_by_therapeutic_area,
            "records_by_clinical_stage": self.records_by_clinical_stage,
            "records_with_ticker": self.records_with_ticker,
            "records_without_ticker": self.records_without_ticker,
            "records_with_mondo_id": self.records_with_mondo_id,
            "records_without_mondo_id": self.records_without_mondo_id,
            "warnings": self.warnings,
            "governance": self.governance,
        }

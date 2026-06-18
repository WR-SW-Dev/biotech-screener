"""Disease ontology reference record schema.

A DiseaseOntologyRecord standardizes raw disease names into canonical,
auditable disease references using MONDO as the primary ontology spine.

Each record preserves:
- Raw disease name for audit trail
- Normalized canonical name
- MONDO ID for cross-resource mapping
- Therapeutic area for domain context
- Confidence score for mapping quality
- Source provenance (MONDO, manual override, unmapped)
- Warnings for ambiguous or uncertain mappings
"""

from dataclasses import dataclass, field


@dataclass
class DiseaseOntologyRecord:
    """Canonical disease reference with MONDO mapping."""

    raw_disease_name: str
    """Raw disease name from source (ClinicalTrials.gov, filings, etc.)."""

    normalized_disease_name: str
    """Normalized canonical disease name (preferred MONDO term or raw if unmapped)."""

    mondo_id: str | None = None
    """MONDO disease ID (e.g., MONDO:0004980) if mapped."""

    therapeutic_area: str | None = None
    """Therapeutic category (Oncology, Immunology, Neurology, etc.)."""

    parent_disease: str | None = None
    """Parent disease category if hierarchical relationship exists."""

    synonyms: list[str] = field(default_factory=list)
    """MONDO and common synonyms for the disease."""

    source: str = "unmapped"
    """Data source: mondo, mondo_cache, mondo_synonym, manual_override, unmapped."""

    confidence: float = 0.0
    """Mapping confidence (0.0–1.0). 1.0 = exact curated match; <0.25 = uncertain."""

    source_refs: list[str] = field(default_factory=list)
    """Reference URLs, publication IDs, MONDO entry references."""

    as_of_date: str = ""
    """Date for records (YYYY-MM-DD)."""

    warnings: list[str] = field(default_factory=list)
    """Warnings: ambiguity, low confidence, preservation, etc."""

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "raw_disease_name": self.raw_disease_name,
            "normalized_disease_name": self.normalized_disease_name,
            "mondo_id": self.mondo_id,
            "therapeutic_area": self.therapeutic_area,
            "parent_disease": self.parent_disease,
            "synonyms": self.synonyms,
            "source": self.source,
            "confidence": round(self.confidence, 4),
            "source_refs": self.source_refs,
            "as_of_date": self.as_of_date,
            "warnings": self.warnings,
        }

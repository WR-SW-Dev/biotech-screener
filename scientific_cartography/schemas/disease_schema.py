"""Disease ontology schema for scientific cartography layer."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DiseaseRecord:
    """Canonical disease record with normalization metadata.

    A disease may have multiple normalized names depending on context.
    The canonical field is normalized_name; raw_name preserves the original source.
    Confidence ranges from 0.0 (low) to 1.0 (certain).
    """

    disease_id: str
    """Stable internal ID for this disease record."""

    raw_name: str
    """Original disease string from source (preserved exactly)."""

    normalized_name: str
    """Canonical normalized disease name."""

    mondo_id: Optional[str] = None
    """MONDO ID if available (e.g., MONDO:0004980 for atopic dermatitis)."""

    therapeutic_area: Optional[str] = None
    """Therapeutic area classification (e.g., oncology, dermatology, neurology)."""

    parent_disease: Optional[str] = None
    """Parent disease ID if this is a subtype."""

    synonyms: list[str] = field(default_factory=list)
    """Alternative names for this disease."""

    source: str = "manual_override"
    """Source priority: manual_override, mondo, ctgov, sec, opentargets, etc."""

    confidence: float = 1.0
    """Confidence in the normalization (0.0 to 1.0)."""

    as_of_date: str = ""
    """Date this record was created (YYYY-MM-DD)."""

    source_refs: list[str] = field(default_factory=list)
    """References to source documents/NCT IDs/filings."""

    def to_dict(self) -> dict:
        """Convert to dictionary for JSONL serialization."""
        return {
            "disease_id": self.disease_id,
            "raw_name": self.raw_name,
            "normalized_name": self.normalized_name,
            "mondo_id": self.mondo_id,
            "therapeutic_area": self.therapeutic_area,
            "parent_disease": self.parent_disease,
            "synonyms": self.synonyms,
            "source": self.source,
            "confidence": self.confidence,
            "as_of_date": self.as_of_date,
            "source_refs": self.source_refs,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DiseaseRecord":
        """Construct from dictionary."""
        return cls(
            disease_id=data["disease_id"],
            raw_name=data["raw_name"],
            normalized_name=data["normalized_name"],
            mondo_id=data.get("mondo_id"),
            therapeutic_area=data.get("therapeutic_area"),
            parent_disease=data.get("parent_disease"),
            synonyms=data.get("synonyms", []),
            source=data.get("source", "manual_override"),
            confidence=data.get("confidence", 1.0),
            as_of_date=data.get("as_of_date", ""),
            source_refs=data.get("source_refs", []),
        )

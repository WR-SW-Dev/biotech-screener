"""Asset-indication program schema for scientific cartography layer."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProgramRecord:
    """An asset-disease program record linking sponsor, asset, indication, and stage.

    One sponsor may have multiple programs (assets, indications).
    One asset may address multiple indications (diseases).
    Clinical stage is derived deterministically from trial data and explicit sourcing.
    """

    program_id: str
    """Stable hash ID: sha256(asset_id|company_id|disease_id|mechanism_class)[:16]."""

    asset_id: str
    """Internal asset identifier."""

    asset_name: str
    """Asset/drug name."""

    company_id: Optional[str] = None
    """Internal company ID for sponsor (if public)."""

    ticker: Optional[str] = None
    """Stock ticker of sponsor (if public)."""

    company_name: Optional[str] = None
    """Sponsor company name (preserves source exactly)."""

    disease_id: str = ""
    """Internal disease ID."""

    disease_name: str = ""
    """Disease/indication name."""

    mondo_id: Optional[str] = None
    """MONDO ID for disease."""

    therapeutic_area: Optional[str] = None
    """Therapeutic area."""

    indication_detail: Optional[str] = None
    """Detailed indication (e.g., moderate-to-severe atopic dermatitis)."""

    subpopulation: Optional[str] = None
    """Biomarker, refractory status, population detail."""

    line_of_therapy: Optional[str] = None
    """Line of therapy (1st line, 2nd line, etc.)."""

    biomarker: Optional[str] = None
    """Biomarker requirement if any."""

    modality: Optional[str] = None
    """Modality: small molecule, mAb, cell therapy, gene therapy, RNA, vaccine, etc."""

    mechanism_class: Optional[str] = None
    """Mechanism: JAK inhibitor, IL-13 mAb, BTK inhibitor, etc."""

    target: Optional[str] = None
    """Drug target (EGFR, IL13, TYK2, CD19, etc.)."""

    clinical_stage: Optional[str] = None
    """Stage: preclinical, phase1, phase2, phase3, filed, approved, discontinued."""

    trial_ids: list[str] = field(default_factory=list)
    """List of associated NCT IDs."""

    regulatory_status: Optional[str] = None
    """FDA status if available (approved, filed, etc.)."""

    source_priority: str = "manual"
    """Source: sec, ctgov, fda, manual, etc."""

    source_refs: list[str] = field(default_factory=list)
    """References to source documents."""

    confidence: float = 1.0
    """Confidence in mapping (0.0 to 1.0)."""

    as_of_date: str = ""
    """Date of record (YYYY-MM-DD)."""

    def to_dict(self) -> dict:
        """Convert to dictionary for JSONL serialization."""
        return {
            "program_id": self.program_id,
            "asset_id": self.asset_id,
            "asset_name": self.asset_name,
            "company_id": self.company_id,
            "ticker": self.ticker,
            "company_name": self.company_name,
            "disease_id": self.disease_id,
            "disease_name": self.disease_name,
            "mondo_id": self.mondo_id,
            "therapeutic_area": self.therapeutic_area,
            "indication_detail": self.indication_detail,
            "subpopulation": self.subpopulation,
            "line_of_therapy": self.line_of_therapy,
            "biomarker": self.biomarker,
            "modality": self.modality,
            "mechanism_class": self.mechanism_class,
            "target": self.target,
            "clinical_stage": self.clinical_stage,
            "trial_ids": self.trial_ids,
            "regulatory_status": self.regulatory_status,
            "source_priority": self.source_priority,
            "source_refs": self.source_refs,
            "confidence": self.confidence,
            "as_of_date": self.as_of_date,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProgramRecord":
        """Construct from dictionary."""
        return cls(
            program_id=data["program_id"],
            asset_id=data["asset_id"],
            asset_name=data["asset_name"],
            company_id=data.get("company_id"),
            ticker=data.get("ticker"),
            company_name=data.get("company_name"),
            disease_id=data.get("disease_id", ""),
            disease_name=data.get("disease_name", ""),
            mondo_id=data.get("mondo_id"),
            therapeutic_area=data.get("therapeutic_area"),
            indication_detail=data.get("indication_detail"),
            subpopulation=data.get("subpopulation"),
            line_of_therapy=data.get("line_of_therapy"),
            biomarker=data.get("biomarker"),
            modality=data.get("modality"),
            mechanism_class=data.get("mechanism_class"),
            target=data.get("target"),
            clinical_stage=data.get("clinical_stage"),
            trial_ids=data.get("trial_ids", []),
            regulatory_status=data.get("regulatory_status"),
            source_priority=data.get("source_priority", "manual"),
            source_refs=data.get("source_refs", []),
            confidence=data.get("confidence", 1.0),
            as_of_date=data.get("as_of_date", ""),
        )

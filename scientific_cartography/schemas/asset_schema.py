"""Asset record schema for scientific cartography layer."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AssetRecord:
    """A drug/asset record linking sponsor, name, modality, and mechanism."""

    asset_id: str
    """Stable internal asset ID."""

    asset_name: str
    """Asset/drug name (preserves source exactly)."""

    asset_aliases: list[str] = field(default_factory=list)
    """Alternative names for the asset."""

    sponsor_company_id: Optional[str] = None
    """Company ID of sponsor (if known/mapped)."""

    sponsor_name_raw: Optional[str] = None
    """Raw sponsor name from source (preserves exactly)."""

    ticker: Optional[str] = None
    """Sponsor ticker if public."""

    modality: Optional[str] = None
    """Modality: small molecule, mAb, cell therapy, gene therapy, RNA, vaccine, etc."""

    mechanism_class: Optional[str] = None
    """Mechanism: JAK inhibitor, IL-13 mAb, BTK inhibitor, etc."""

    target: Optional[str] = None
    """Drug target (EGFR, IL13, TYK2, CD19, etc.)."""

    source_refs: list[str] = field(default_factory=list)
    """References to source documents."""

    confidence: float = 1.0
    """Confidence in asset mapping (0.0 to 1.0)."""

    as_of_date: str = ""
    """Date of record (YYYY-MM-DD)."""

    def to_dict(self) -> dict:
        """Convert to dictionary for JSONL serialization."""
        return {
            "asset_id": self.asset_id,
            "asset_name": self.asset_name,
            "asset_aliases": self.asset_aliases,
            "sponsor_company_id": self.sponsor_company_id,
            "sponsor_name_raw": self.sponsor_name_raw,
            "ticker": self.ticker,
            "modality": self.modality,
            "mechanism_class": self.mechanism_class,
            "target": self.target,
            "source_refs": self.source_refs,
            "confidence": self.confidence,
            "as_of_date": self.as_of_date,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AssetRecord":
        """Construct from dictionary."""
        return cls(
            asset_id=data["asset_id"],
            asset_name=data["asset_name"],
            asset_aliases=data.get("asset_aliases", []),
            sponsor_company_id=data.get("sponsor_company_id"),
            sponsor_name_raw=data.get("sponsor_name_raw"),
            ticker=data.get("ticker"),
            modality=data.get("modality"),
            mechanism_class=data.get("mechanism_class"),
            target=data.get("target"),
            source_refs=data.get("source_refs", []),
            confidence=data.get("confidence", 1.0),
            as_of_date=data.get("as_of_date", ""),
        )

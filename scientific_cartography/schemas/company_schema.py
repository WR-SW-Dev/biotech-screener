"""Company record schema for scientific cartography layer."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CompanyRecord:
    """Canonical company record linking ticker, name, and metadata."""

    company_id: str
    """Stable internal company ID."""

    company_name: str
    """Company/sponsor name (preserves source exactly)."""

    ticker: Optional[str] = None
    """Stock ticker if public."""

    cik: Optional[str] = None
    """SEC CIK number if available."""

    aliases: list[str] = field(default_factory=list)
    """Alternative names (e.g., former names, subsidiary names)."""

    exchange: Optional[str] = None
    """Stock exchange if public (NYSE, NASDAQ, etc.)."""

    is_public: bool = False
    """Whether company is publicly traded."""

    as_of_date: str = ""
    """Date of record (YYYY-MM-DD)."""

    source_refs: list[str] = field(default_factory=list)
    """References to source documents/filings."""

    confidence: float = 1.0
    """Confidence in company metadata (0.0 to 1.0)."""

    def to_dict(self) -> dict:
        """Convert to dictionary for JSONL serialization."""
        return {
            "company_id": self.company_id,
            "company_name": self.company_name,
            "ticker": self.ticker,
            "cik": self.cik,
            "aliases": self.aliases,
            "exchange": self.exchange,
            "is_public": self.is_public,
            "as_of_date": self.as_of_date,
            "source_refs": self.source_refs,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CompanyRecord":
        """Construct from dictionary."""
        return cls(
            company_id=data["company_id"],
            company_name=data["company_name"],
            ticker=data.get("ticker"),
            cik=data.get("cik"),
            aliases=data.get("aliases", []),
            exchange=data.get("exchange"),
            is_public=data.get("is_public", False),
            as_of_date=data.get("as_of_date", ""),
            source_refs=data.get("source_refs", []),
            confidence=data.get("confidence", 1.0),
        )

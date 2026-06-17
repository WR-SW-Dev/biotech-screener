"""Clinical trial record schema for scientific cartography layer."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TrialRecord:
    """A clinical trial record from ClinicalTrials.gov or similar source."""

    nct_id: str
    """NCT identifier (e.g., NCT02345678)."""

    brief_title: str
    """Brief trial title."""

    official_title: Optional[str] = None
    """Official/full trial title."""

    sponsor: Optional[str] = None
    """Sponsor name (raw, preserved exactly)."""

    collaborators: list[str] = field(default_factory=list)
    """Collaborator names if any."""

    conditions: list[str] = field(default_factory=list)
    """Trial conditions/diseases."""

    interventions: list[str] = field(default_factory=list)
    """Intervention names (assets/drugs tested)."""

    phases: list[str] = field(default_factory=list)
    """Trial phases (Phase 1, Phase 2, etc.)."""

    overall_status: Optional[str] = None
    """Overall trial status (Active, Completed, Terminated, etc.)."""

    enrollment: Optional[int] = None
    """Enrollment count if available."""

    study_type: Optional[str] = None
    """Study type (Interventional, Observational, etc.)."""

    allocation: Optional[str] = None
    """Allocation method (Randomized, Non-randomized, etc.)."""

    masking: Optional[str] = None
    """Masking (Open Label, Single Blind, Double Blind, etc.)."""

    primary_purpose: Optional[str] = None
    """Primary purpose (Treatment, Prevention, Diagnostic, etc.)."""

    start_date: Optional[str] = None
    """Study start date (YYYY-MM-DD if known)."""

    primary_completion_date: Optional[str] = None
    """Primary completion date (YYYY-MM-DD if known)."""

    study_completion_date: Optional[str] = None
    """Study completion date (YYYY-MM-DD if known)."""

    primary_endpoints: list[str] = field(default_factory=list)
    """Primary endpoint descriptions."""

    secondary_endpoints: list[str] = field(default_factory=list)
    """Secondary endpoint descriptions."""

    has_results: bool = False
    """Whether trial has posted results."""

    source_ref: str = ""
    """Source reference (NCT ID, URL, or data source)."""

    as_of_date: str = ""
    """Date of record (YYYY-MM-DD)."""

    def to_dict(self) -> dict:
        """Convert to dictionary for JSONL serialization."""
        return {
            "nct_id": self.nct_id,
            "brief_title": self.brief_title,
            "official_title": self.official_title,
            "sponsor": self.sponsor,
            "collaborators": self.collaborators,
            "conditions": self.conditions,
            "interventions": self.interventions,
            "phases": self.phases,
            "overall_status": self.overall_status,
            "enrollment": self.enrollment,
            "study_type": self.study_type,
            "allocation": self.allocation,
            "masking": self.masking,
            "primary_purpose": self.primary_purpose,
            "start_date": self.start_date,
            "primary_completion_date": self.primary_completion_date,
            "study_completion_date": self.study_completion_date,
            "primary_endpoints": self.primary_endpoints,
            "secondary_endpoints": self.secondary_endpoints,
            "has_results": self.has_results,
            "source_ref": self.source_ref,
            "as_of_date": self.as_of_date,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TrialRecord":
        """Construct from dictionary."""
        return cls(
            nct_id=data["nct_id"],
            brief_title=data["brief_title"],
            official_title=data.get("official_title"),
            sponsor=data.get("sponsor"),
            collaborators=data.get("collaborators", []),
            conditions=data.get("conditions", []),
            interventions=data.get("interventions", []),
            phases=data.get("phases", []),
            overall_status=data.get("overall_status"),
            enrollment=data.get("enrollment"),
            study_type=data.get("study_type"),
            allocation=data.get("allocation"),
            masking=data.get("masking"),
            primary_purpose=data.get("primary_purpose"),
            start_date=data.get("start_date"),
            primary_completion_date=data.get("primary_completion_date"),
            study_completion_date=data.get("study_completion_date"),
            primary_endpoints=data.get("primary_endpoints", []),
            secondary_endpoints=data.get("secondary_endpoints", []),
            has_results=data.get("has_results", False),
            source_ref=data.get("source_ref", ""),
            as_of_date=data.get("as_of_date", ""),
        )

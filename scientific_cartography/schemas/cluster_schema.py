"""Competitive cluster record schema."""

from dataclasses import dataclass, field


@dataclass
class CompetitiveClusterRecord:
    """Competitive cluster of programs grouped by disease/mechanism/modality/target."""

    cluster_id: str
    """Deterministic SHA256 cluster identifier."""

    disease_id: str | None = None
    """Disease ID from normalized disease record."""

    disease_name: str | None = None
    """Disease name (normalized or "unknown")."""

    therapeutic_area: str | None = None
    """Therapeutic area from disease normalization."""

    mechanism_class: str | None = None
    """Mechanism class (e.g., JAK inhibitor, CD19 CAR-T, or "unknown")."""

    modality: str | None = None
    """Modality (e.g., small molecule, monoclonal antibody, or "unknown")."""

    target: str | None = None
    """Drug target if identified (e.g., JAK, IL13, CD19, or "unknown")."""

    clinical_stage_bucket: str | None = None
    """Primary clinical stage of cluster (approved, filed, phase3, ..., or None if mixed)."""

    cluster_key: str = ""
    """Canonical cluster key: disease_id|mechanism_class|modality|target."""

    program_count: int = 0
    """Total programs in cluster."""

    public_program_count: int = 0
    """Programs with public ticker."""

    private_or_unknown_program_count: int = 0
    """Programs without public ticker."""

    approved_count: int = 0
    """Programs in approved stage."""

    filed_count: int = 0
    """Programs in filed stage."""

    phase3_count: int = 0
    """Programs in phase 3."""

    phase2_count: int = 0
    """Programs in phase 2."""

    phase1_count: int = 0
    """Programs in phase 1."""

    preclinical_count: int = 0
    """Programs in preclinical stage."""

    discontinued_count: int = 0
    """Programs marked discontinued/inactive."""

    unknown_stage_count: int = 0
    """Programs with unknown clinical stage."""

    public_tickers: list[str] = field(default_factory=list)
    """Sorted list of public tickers in cluster (deduplicated)."""

    sponsor_names: list[str] = field(default_factory=list)
    """Sorted list of sponsor/company names in cluster (deduplicated)."""

    asset_names: list[str] = field(default_factory=list)
    """Sorted list of asset names in cluster (deduplicated)."""

    program_ids: list[str] = field(default_factory=list)
    """Sorted list of member program IDs."""

    source_refs: list[str] = field(default_factory=list)
    """Deduplicated, sorted source references from member programs."""

    as_of_date: str = ""
    """Date of cluster snapshot (YYYY-MM-DD)."""

    confidence: float = 0.0
    """Minimum confidence from member programs."""

    warnings: list[str] = field(default_factory=list)
    """Diagnostic warnings (unknown fields, missing data, etc.)."""

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "cluster_id": self.cluster_id,
            "disease_id": self.disease_id,
            "disease_name": self.disease_name,
            "therapeutic_area": self.therapeutic_area,
            "mechanism_class": self.mechanism_class,
            "modality": self.modality,
            "target": self.target,
            "clinical_stage_bucket": self.clinical_stage_bucket,
            "cluster_key": self.cluster_key,
            "program_count": self.program_count,
            "public_program_count": self.public_program_count,
            "private_or_unknown_program_count": self.private_or_unknown_program_count,
            "approved_count": self.approved_count,
            "filed_count": self.filed_count,
            "phase3_count": self.phase3_count,
            "phase2_count": self.phase2_count,
            "phase1_count": self.phase1_count,
            "preclinical_count": self.preclinical_count,
            "discontinued_count": self.discontinued_count,
            "unknown_stage_count": self.unknown_stage_count,
            "public_tickers": self.public_tickers,
            "sponsor_names": self.sponsor_names,
            "asset_names": self.asset_names,
            "program_ids": self.program_ids,
            "source_refs": self.source_refs,
            "as_of_date": self.as_of_date,
            "confidence": self.confidence,
            "warnings": self.warnings,
        }

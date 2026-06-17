"""Landscape feature record schema."""

from dataclasses import dataclass, field


@dataclass
class LandscapeFeatureRecord:
    """Diagnostic landscape features for a program in competitive context."""

    feature_id: str
    """Deterministic SHA256 feature identifier."""

    program_id: str | None = None
    """Program ID from ProgramRecord."""

    cluster_id: str | None = None
    """Cluster ID from CompetitiveClusterRecord."""

    ticker: str | None = None
    """Public ticker if available."""

    company_id: str | None = None
    """Company ID if available."""

    asset_id: str | None = None
    """Asset ID from program."""

    asset_name: str | None = None
    """Asset name from program."""

    disease_id: str | None = None
    """Disease ID."""

    disease_name: str | None = None
    """Disease name."""

    mechanism_class: str | None = None
    """Mechanism class from program."""

    modality: str | None = None
    """Modality from program."""

    target: str | None = None
    """Drug target from program."""

    clinical_stage: str | None = None
    """Clinical stage from program."""

    disease_program_count: int | None = None
    """Total programs targeting this disease."""

    mechanism_program_count: int | None = None
    """Total programs with same mechanism/modality/target."""

    same_stage_program_count: int | None = None
    """Total programs at same clinical stage in same mechanism cluster."""

    approved_incumbent_count: int | None = None
    """Approved programs in same cluster."""

    phase3_program_count: int | None = None
    """Phase 3 programs in same cluster."""

    phase2_program_count: int | None = None
    """Phase 2 programs in same cluster."""

    phase1_program_count: int | None = None
    """Phase 1 programs in same cluster."""

    public_program_count: int | None = None
    """Public company programs in same cluster."""

    private_or_unknown_program_count: int | None = None
    """Private/unknown company programs in same cluster."""

    mechanism_crowding_score: float | None = None
    """Diagnostic proxy for mechanism-level crowding (0.0 to 1.0)."""

    stage_crowding_score: float | None = None
    """Diagnostic proxy for stage-level crowding (0.0 to 1.0)."""

    white_space_score: float | None = None
    """Diagnostic proxy for relative low direct competition (0.0 to 1.0)."""

    differentiation_proxy_score: float | None = None
    """Diagnostic proxy for program differentiation (reserved, None in Phase 5)."""

    feature_confidence: float = 0.0
    """Confidence in computed features (0.0 to 1.0)."""

    feature_status: str = "computed"
    """Status: computed, partial, unknown."""

    source_refs: list[str] = field(default_factory=list)
    """Source references for features."""

    as_of_date: str = ""
    """Date of feature snapshot (YYYY-MM-DD)."""

    warnings: list[str] = field(default_factory=list)
    """Diagnostic warnings about feature computation."""

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "feature_id": self.feature_id,
            "program_id": self.program_id,
            "cluster_id": self.cluster_id,
            "ticker": self.ticker,
            "company_id": self.company_id,
            "asset_id": self.asset_id,
            "asset_name": self.asset_name,
            "disease_id": self.disease_id,
            "disease_name": self.disease_name,
            "mechanism_class": self.mechanism_class,
            "modality": self.modality,
            "target": self.target,
            "clinical_stage": self.clinical_stage,
            "disease_program_count": self.disease_program_count,
            "mechanism_program_count": self.mechanism_program_count,
            "same_stage_program_count": self.same_stage_program_count,
            "approved_incumbent_count": self.approved_incumbent_count,
            "phase3_program_count": self.phase3_program_count,
            "phase2_program_count": self.phase2_program_count,
            "phase1_program_count": self.phase1_program_count,
            "public_program_count": self.public_program_count,
            "private_or_unknown_program_count": self.private_or_unknown_program_count,
            "mechanism_crowding_score": self.mechanism_crowding_score,
            "stage_crowding_score": self.stage_crowding_score,
            "white_space_score": self.white_space_score,
            "differentiation_proxy_score": self.differentiation_proxy_score,
            "feature_confidence": self.feature_confidence,
            "feature_status": self.feature_status,
            "source_refs": self.source_refs,
            "as_of_date": self.as_of_date,
            "warnings": self.warnings,
        }

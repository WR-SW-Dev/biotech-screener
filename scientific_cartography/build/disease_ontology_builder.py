"""Build disease ontology reference map from program or disease-name data.

The DiseaseOntologyBuilder constructs a deterministic, auditable disease
ontology using MONDO as the primary spine. It resolves raw disease names
to canonical references with confidence scoring and source tracking.

Resolution priority:
1. Exact raw disease name match to ontology synonym
2. Existing DiseaseNormalizer high-confidence mapping
3. Manual override (if available)
4. Fallback to raw name preservation with low confidence + warning
"""

from dataclasses import dataclass, field
from typing import Optional

from scientific_cartography.normalize.disease_normalizer import DiseaseNormalizer
from scientific_cartography.schemas.disease_ontology_schema import DiseaseOntologyRecord


@dataclass
class DiseaseOntologyCoverageReport:
    """Coverage report for disease ontology mapping."""

    as_of_date: str
    """Date for records (YYYY-MM-DD)."""

    total_raw_diseases: int = 0
    """Total unique raw disease names processed."""

    mapped_count: int = 0
    """Count with confident MONDO mapping (confidence >= 0.75)."""

    unknown_count: int = 0
    """Count unmapped with low confidence (confidence < 0.25)."""

    ambiguous_count: int = 0
    """Count with ambiguous mapping (multiple possible matches)."""

    therapeutic_area_counts: dict[str, int] = field(default_factory=dict)
    """Counts by therapeutic area."""

    confidence_distribution: dict[str, int] = field(default_factory=dict)
    """Distribution of confidence scores (binned: 1.0, 0.75+, 0.5+, <0.25)."""

    warnings: list[str] = field(default_factory=list)
    """Warnings during processing."""

    governance: dict = field(default_factory=dict)
    """Governance flags (all false for Phase 8)."""

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "as_of_date": self.as_of_date,
            "total_raw_diseases": self.total_raw_diseases,
            "mapped_count": self.mapped_count,
            "unknown_count": self.unknown_count,
            "ambiguous_count": self.ambiguous_count,
            "therapeutic_area_counts": self.therapeutic_area_counts,
            "confidence_distribution": self.confidence_distribution,
            "warnings": self.warnings,
            "governance": self.governance,
        }


class DiseaseOntologyBuilder:
    """Build disease ontology records from programs or raw disease names.

    Conservative approach:
    - Uses existing DiseaseNormalizer for deterministic resolution
    - Preserves raw disease names for audit trail
    - Tracks source and confidence for each mapping
    - Deduplicates and aggregates synonyms
    """

    def __init__(
        self,
        as_of_date: str = "",
        disease_normalizer: Optional[DiseaseNormalizer] = None,
    ):
        """Initialize disease ontology builder.

        Args:
            as_of_date: Date for records (YYYY-MM-DD).
            disease_normalizer: Existing normalizer for deterministic resolution.
        """
        self.as_of_date = as_of_date
        self.disease_normalizer = disease_normalizer or DiseaseNormalizer(as_of_date=as_of_date)
        self._seen_raw_names: dict[str, DiseaseOntologyRecord] = {}
        self._warnings: list[str] = []

    def build_from_raw_diseases(
        self,
        raw_disease_names: list[str],
    ) -> tuple[list[DiseaseOntologyRecord], DiseaseOntologyCoverageReport]:
        """Build disease ontology records from raw disease name list.

        Args:
            raw_disease_names: List of raw disease names from source.

        Returns:
            Tuple of (ontology records, coverage report).
        """
        # Deduplicate raw disease names
        unique_names = set(n for n in raw_disease_names if n and n.strip())

        records = []
        for raw_name in sorted(unique_names):
            record = self._resolve_disease(raw_name)
            if record and raw_name not in self._seen_raw_names:
                records.append(record)
                self._seen_raw_names[raw_name] = record

        # Build coverage report
        coverage = self._build_coverage_report(list(unique_names), records)

        return records, coverage

    def build_from_programs(
        self,
        programs: list,
    ) -> tuple[list[DiseaseOntologyRecord], DiseaseOntologyCoverageReport]:
        """Build disease ontology records from program list.

        Extracts disease_name from each program, then builds ontology.

        Args:
            programs: List of program dicts with disease_name field.

        Returns:
            Tuple of (ontology records, coverage report).
        """
        # Extract unique raw disease names from programs
        raw_disease_names = set()
        for program in programs:
            if isinstance(program, dict):
                disease_name = program.get("disease_name")
            else:
                # Handle programrecord objects
                disease_name = getattr(program, "disease_name", None)

            if disease_name and disease_name.strip():
                raw_disease_names.add(disease_name.strip())

        return self.build_from_raw_diseases(list(raw_disease_names))

    def _resolve_disease(self, raw_disease_name: str) -> Optional[DiseaseOntologyRecord]:
        """Resolve a single raw disease name to ontology record.

        Uses DiseaseNormalizer for deterministic matching, then maps
        to DiseaseOntologyRecord with confidence and source tracking.

        Args:
            raw_disease_name: Raw disease name from source.

        Returns:
            DiseaseOntologyRecord if resolved, else None.
        """
        if not raw_disease_name or not raw_disease_name.strip():
            return None

        # Use existing DiseaseNormalizer for deterministic resolution
        normalized = self.disease_normalizer.normalize(raw_disease_name)

        # Map DiseaseNormalizer result to DiseaseOntologyRecord
        warnings = []

        # Determine confidence from normalizer result
        if normalized.confidence >= 0.90:
            confidence = 1.00  # Exact match
        elif normalized.confidence >= 0.80:
            confidence = 0.90  # High confidence
        elif normalized.confidence >= 0.70:
            confidence = 0.75  # Moderate confidence
        elif normalized.confidence > 0.0:
            confidence = 0.50  # Low confidence
        else:
            confidence = 0.0  # Unmapped or ambiguous
            if normalized.source == "unmapped":
                warnings.append(f"Disease not found in MONDO ontology: {raw_disease_name}")
            else:
                warnings.append(f"Low confidence mapping for: {raw_disease_name}")

        # Determine source label
        source_label = normalized.source
        if source_label not in ["mondo", "mondo_synonym", "mondo_substring", "manual_override", "unmapped"]:
            source_label = "normalized"

        record = DiseaseOntologyRecord(
            raw_disease_name=raw_disease_name,
            normalized_disease_name=normalized.normalized_name,
            mondo_id=normalized.mondo_id,
            therapeutic_area=normalized.therapeutic_area,
            parent_disease=None,  # Phase 8 placeholder for hierarchy
            synonyms=normalized.synonyms or [],
            source=source_label,
            confidence=confidence,
            source_refs=normalized.source_refs or [],
            as_of_date=self.as_of_date,
            warnings=warnings,
        )

        return record

    def _build_coverage_report(
        self,
        raw_disease_names: list[str],
        records: list[DiseaseOntologyRecord],
    ) -> DiseaseOntologyCoverageReport:
        """Build coverage report from processed records.

        Args:
            raw_disease_names: Original list of raw disease names.
            records: Processed ontology records.

        Returns:
            DiseaseOntologyCoverageReport.
        """
        report = DiseaseOntologyCoverageReport(as_of_date=self.as_of_date)

        report.total_raw_diseases = len(set(raw_disease_names))
        report.mapped_count = sum(1 for r in records if r.confidence >= 0.75)
        report.unknown_count = sum(1 for r in records if r.confidence < 0.25)
        report.ambiguous_count = sum(1 for r in records if r.warnings and "ambiguous" in " ".join(r.warnings).lower())

        # Therapeutic area counts
        for record in records:
            area = record.therapeutic_area or "unknown"
            report.therapeutic_area_counts[area] = report.therapeutic_area_counts.get(area, 0) + 1

        # Confidence distribution
        for record in records:
            if record.confidence >= 0.99:
                bin_key = "1.0"
            elif record.confidence >= 0.75:
                bin_key = "0.75+"
            elif record.confidence >= 0.5:
                bin_key = "0.5+"
            else:
                bin_key = "<0.25"

            report.confidence_distribution[bin_key] = report.confidence_distribution.get(bin_key, 0) + 1

        # Governance flags
        report.governance = {
            "read_only_diagnostic": True,
            "reference_data_layer_only": True,
            "production_model_change": False,
            "ranker_change": False,
            "selector_change": False,
            "sizing_change": False,
            "final_score_change": False,
            "alpha_promotion": False,
        }

        report.warnings = self._warnings

        return report

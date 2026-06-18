"""Build asset indication map records by enriching programs with Phase 8 disease ontology.

This layer wraps ProgramRecord and enriches with Phase 8 DiseaseOntologyBuilder results.
Remains read-only diagnostic — does not alter production scoring/ranking/selection.
"""

import hashlib
from typing import Optional

from scientific_cartography.build.disease_ontology_builder import DiseaseOntologyBuilder
from scientific_cartography.schemas.asset_indication_map_schema import (
    AssetIndicationMapCoverageReport,
    AssetIndicationMapRecord,
)
from scientific_cartography.schemas.program_schema import ProgramRecord


class AssetIndicationMapBuilder:
    """Build diagnostic asset indication map records from programs."""

    def __init__(
        self,
        as_of_date: str = "",
        disease_ontology_builder: Optional[DiseaseOntologyBuilder] = None,
    ):
        """Initialize builder.

        Args:
            as_of_date: Record date (YYYY-MM-DD).
            disease_ontology_builder: DiseaseOntologyBuilder for Phase 8 enrichment.
        """
        self.as_of_date = as_of_date
        self.disease_ontology_builder = disease_ontology_builder or DiseaseOntologyBuilder(as_of_date=as_of_date)
        self._seen_records: dict[str, AssetIndicationMapRecord] = {}
        self._warnings: list[str] = []

    def build_from_programs(
        self,
        programs: list[ProgramRecord],
    ) -> tuple[list[AssetIndicationMapRecord], AssetIndicationMapCoverageReport]:
        """Build asset indication map from ProgramRecords.

        Enriches each program with Phase 8 disease ontology resolution.

        Args:
            programs: List of ProgramRecord objects.

        Returns:
            Tuple of (map_records, coverage_report).
        """
        map_records = []
        seen_record_ids = set()

        # Process each program through Phase 8 disease enrichment
        for program in programs:
            record = self._create_map_record_from_program(program)

            if record:
                # Deduplicate by record_id
                if record.record_id not in seen_record_ids:
                    map_records.append(record)
                    self._seen_records[record.record_id] = record
                    seen_record_ids.add(record.record_id)

        # Build coverage report
        coverage = self._build_coverage_report(map_records)

        return map_records, coverage

    def _create_map_record_from_program(
        self,
        program: ProgramRecord,
    ) -> Optional[AssetIndicationMapRecord]:
        """Create asset indication map record from program by enriching with Phase 8.

        Args:
            program: ProgramRecord to enrich.

        Returns:
            AssetIndicationMapRecord or None if creation fails.
        """
        if not program.asset_name:
            self._warnings.append(f"Program {program.program_id}: missing asset_name")
            return None

        # Use Phase 8 DiseaseOntologyBuilder to resolve disease
        raw_indication = program.disease_name or ""
        disease_records, _ = self.disease_ontology_builder.build_from_raw_diseases(
            [raw_indication] if raw_indication else []
        )

        disease_record = disease_records[0] if disease_records else None

        # Extract Phase 8 enrichment
        normalized_disease_name = disease_record.normalized_disease_name if disease_record else raw_indication
        mondo_id = disease_record.mondo_id if disease_record else None
        therapeutic_area = disease_record.therapeutic_area if disease_record else None
        parent_disease = disease_record.parent_disease if disease_record else None
        disease_ontology_confidence = disease_record.confidence if disease_record else 0.0

        # Determine source priority (based on source_priority field)
        source_priority_map = {
            "sec": 1,
            "sec_filing": 1,
            "investor_deck": 2,
            "deck": 2,
            "ctgov": 3,
            "fda": 4,
            "fda_label": 4,
            "open_targets": 5,
            "chembl": 6,
            "pubmed": 7,
            "manual": 8,
            "manual_override": 8,
        }
        source_type = program.source_priority if program.source_priority else "unknown"
        source_priority = source_priority_map.get(source_type.lower(), 9)

        # Compute overall confidence
        # Consider both disease ontology confidence and original program confidence
        overall_confidence = (
            min(disease_ontology_confidence, program.confidence) if disease_ontology_confidence > 0 else 0.0
        )

        # Deterministic record_id
        record_id_base = (
            f"{program.company_id or 'unknown'}|"
            f"{program.asset_id or 'unknown'}|"
            f"{raw_indication}|"
            f"{mondo_id or 'unmapped'}|"
            f"{source_type}|"
            f"{self.as_of_date}"
        )
        record_id = hashlib.sha256(record_id_base.encode()).hexdigest()[:16]

        # Collect warnings
        warnings = []
        if disease_record and disease_record.warnings:
            warnings.extend(disease_record.warnings)
        if not mondo_id:
            warnings.append(f"Disease not mapped to MONDO: {raw_indication}")
        if not program.ticker:
            warnings.append(f"No ticker for company: {program.company_name}")

        # Create map record
        record = AssetIndicationMapRecord(
            record_id=record_id,
            company_id=program.company_id,
            ticker=program.ticker,
            company_name=program.company_name,
            sponsor_name=program.company_name,  # Use company_name as sponsor in lack of explicit field
            asset_id=program.asset_id,
            asset_name=program.asset_name,
            asset_aliases=[],  # Could be populated from asset resolver if available
            raw_indication=raw_indication,
            normalized_disease_name=normalized_disease_name,
            mondo_id=mondo_id,
            therapeutic_area=therapeutic_area,
            parent_disease=parent_disease,
            mechanism_class=program.mechanism_class,
            target=program.target,
            modality=program.modality,
            clinical_stage=program.clinical_stage,
            source_priority=source_priority,
            source_type=source_type,
            source_refs=program.source_refs or [],
            evidence_text=None,  # Not populated in Phase 9 (for future SEC/FDA/etc.)
            disease_ontology_confidence=disease_ontology_confidence,
            overall_confidence=overall_confidence,
            as_of_date=self.as_of_date or program.as_of_date,
            warnings=warnings,
        )

        return record

    def _build_coverage_report(
        self,
        records: list[AssetIndicationMapRecord],
    ) -> AssetIndicationMapCoverageReport:
        """Build coverage report from processed records.

        Args:
            records: List of AssetIndicationMapRecord.

        Returns:
            AssetIndicationMapCoverageReport.
        """
        report = AssetIndicationMapCoverageReport(as_of_date=self.as_of_date)

        # Track unique values
        unique_companies = set()
        unique_tickers = set()
        unique_assets = set()
        unique_raw_indications = set()
        unique_mondo_diseases = set()

        for record in records:
            if record.company_id:
                unique_companies.add(record.company_id)
            if record.ticker:
                unique_tickers.add(record.ticker)
            if record.asset_id:
                unique_assets.add(record.asset_id)
            if record.raw_indication:
                unique_raw_indications.add(record.raw_indication)
            if record.mondo_id:
                unique_mondo_diseases.add(record.mondo_id)

            # Count by source
            report.records_by_source_type[record.source_type] = (
                report.records_by_source_type.get(record.source_type, 0) + 1
            )
            report.records_by_source_priority[record.source_priority] = (
                report.records_by_source_priority.get(record.source_priority, 0) + 1
            )

            # Count by therapeutic area
            if record.therapeutic_area:
                report.records_by_therapeutic_area[record.therapeutic_area] = (
                    report.records_by_therapeutic_area.get(record.therapeutic_area, 0) + 1
                )

            # Count by stage
            if record.clinical_stage:
                report.records_by_clinical_stage[record.clinical_stage] = (
                    report.records_by_clinical_stage.get(record.clinical_stage, 0) + 1
                )

            # Count ticker / mondo presence
            if record.ticker:
                report.records_with_ticker += 1
            else:
                report.records_without_ticker += 1

            if record.mondo_id:
                report.records_with_mondo_id += 1
                report.mapped_disease_count += 1
            else:
                report.records_without_mondo_id += 1
                report.unknown_disease_count += 1

        # Set totals
        report.total_records = len(records)
        report.unique_companies = len(unique_companies)
        report.unique_tickers = len(unique_tickers)
        report.unique_assets = len(unique_assets)
        report.unique_raw_indications = len(unique_raw_indications)
        report.unique_mondo_diseases = len(unique_mondo_diseases)
        report.warnings = self._warnings

        return report

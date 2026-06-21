"""Build ProgramRecords from companies, trials, and resolved metadata."""

import hashlib
from typing import Optional

from scientific_cartography.normalize.asset_alias_resolver import AssetAliasResolver
from scientific_cartography.normalize.disease_normalizer import DiseaseNormalizer
from scientific_cartography.normalize.sponsor_resolver import SponsorResolver
from scientific_cartography.normalize.stage_normalizer import StageNormalizer
from scientific_cartography.schemas.company_schema import CompanyRecord
from scientific_cartography.schemas.program_schema import ProgramRecord
from scientific_cartography.schemas.trial_schema import TrialRecord


class AssetIndicationBuilder:
    """Build ProgramRecords from companies, trials, and normalizers."""

    def __init__(
        self,
        disease_normalizer: DiseaseNormalizer,
        stage_normalizer: StageNormalizer,
        asset_alias_resolver: AssetAliasResolver,
        sponsor_resolver: SponsorResolver,
        as_of_date: str = "",
    ):
        """Initialize builder.

        Args:
            disease_normalizer: DiseaseNormalizer for disease mapping.
            stage_normalizer: StageNormalizer for stage mapping.
            asset_alias_resolver: AssetAliasResolver for asset resolution.
            sponsor_resolver: SponsorResolver for company/ticker mapping.
            as_of_date: Date for records (YYYY-MM-DD).
        """
        self.disease_normalizer = disease_normalizer
        self.stage_normalizer = stage_normalizer
        self.asset_alias_resolver = asset_alias_resolver
        self.sponsor_resolver = sponsor_resolver
        self.as_of_date = as_of_date

    def build_from_trials(
        self,
        trials: list[TrialRecord],
        company_records: list[CompanyRecord],
    ) -> tuple[list[ProgramRecord], dict]:
        """Build ProgramRecords from trial data.

        Args:
            trials: List of TrialRecords.
            company_records: List of CompanyRecords for sponsor resolution.

        Returns:
            Tuple of (program_records, diagnostics_dict).
        """
        program_records = []
        diagnostics = {
            "total_trials": len(trials),
            "total_programs": 0,
            "programs_with_unknown_asset": 0,
            "programs_with_unknown_sponsor": 0,
            "programs_with_unknown_disease": 0,
            "programs_with_unknown_stage": 0,
            "warnings": [],
        }

        for trial in trials:
            # For each intervention/condition combination, create programs
            interventions = trial.interventions or []
            conditions = trial.conditions or []
            phases = trial.phases or []

            # Normalize trial stage
            trial_stage = None
            if phases:
                trial_stage = self.stage_normalizer.normalize(phases[0])

            # If no interventions or conditions, skip
            if not (interventions and conditions):
                if not interventions:
                    diagnostics["warnings"].append(f"Trial {trial.nct_id}: no interventions")
                if not conditions:
                    diagnostics["warnings"].append(f"Trial {trial.nct_id}: no conditions")
                continue

            # Create program for each intervention/condition pair
            for intervention in interventions:
                # Skip None or empty interventions
                if not intervention or not isinstance(intervention, str):
                    continue
                # Skip control/placebo interventions (not meaningful assets)
                intervention_lower = intervention.lower()
                if any(skip in intervention_lower for skip in ["placebo", "control", "vehicle", "sham"]):
                    continue
                for condition in conditions:
                    # Skip None or empty conditions
                    if not condition or not isinstance(condition, str):
                        continue
                    program = self._create_program_from_trial(
                        trial=trial,
                        intervention=intervention,
                        condition=condition,
                        trial_stage=trial_stage,
                        company_records=company_records,
                    )

                    if program:
                        program_records.append(program)
                        diagnostics["total_programs"] += 1

                        if not program.asset_name or program.mechanism_class is None:
                            diagnostics["programs_with_unknown_asset"] += 1
                        if not program.ticker and not program.company_id:
                            diagnostics["programs_with_unknown_sponsor"] += 1
                        if not program.disease_name or program.confidence < 0.5:
                            diagnostics["programs_with_unknown_disease"] += 1
                        if not program.clinical_stage:
                            diagnostics["programs_with_unknown_stage"] += 1

        return program_records, diagnostics

    def _create_program_from_trial(
        self,
        trial: TrialRecord,
        intervention: str,
        condition: str,
        trial_stage: Optional[str],
        company_records: list[CompanyRecord],
    ) -> Optional[ProgramRecord]:
        """Create single ProgramRecord from trial data.

        Args:
            trial: TrialRecord.
            intervention: Specific intervention name.
            condition: Specific condition name.
            trial_stage: Normalized stage from trial phases.
            company_records: Company records for sponsor resolution.

        Returns:
            ProgramRecord or None if creation fails.
        """
        # Local trial caches can carry an already-mapped screener ticker. Treat
        # that ticker as authoritative for ticker-bearing local records; sponsor
        # text can name an institution, collaborator, subsidiary, or comparator.
        trial_ticker = trial.ticker.strip().upper() if trial.ticker else None
        ticker_resolved = self.sponsor_resolver.resolve(trial_ticker) if trial_ticker else None
        ticker_resolution_source = "trial_ticker" if ticker_resolved and ticker_resolved.get("ticker") else None
        sponsor_resolved = (
            ticker_resolved
            if ticker_resolved and ticker_resolved.get("ticker")
            else self.sponsor_resolver.resolve(trial.sponsor or "Unknown")
        )
        if ticker_resolution_source is None:
            if sponsor_resolved and sponsor_resolved.get("ticker"):
                ticker_resolution_source = "sponsor_resolver"
            else:
                ticker_resolution_source = "unresolved"
        company_id = sponsor_resolved.get("company_id") if sponsor_resolved else None
        ticker = sponsor_resolved.get("ticker") if sponsor_resolved else None
        sponsor_is_public = sponsor_resolved.get("is_public", False) if sponsor_resolved else False
        ticker_resolution_confidence = sponsor_resolved.get("confidence", 0.0) if sponsor_resolved else 0.0
        ticker_resolution_warnings = sponsor_resolved.get("warnings", []) if sponsor_resolved else []

        # Resolve asset name
        asset_resolved = self.asset_alias_resolver.resolve(intervention, trial.sponsor)
        asset_name = intervention  # Use raw intervention name
        asset_confidence = asset_resolved.get("confidence", 0.0) if asset_resolved else 0.0

        # Normalize disease
        disease_record = self.disease_normalizer.normalize(condition)
        disease_name = disease_record.normalized_name
        disease_id = disease_record.disease_id
        mondo_id = disease_record.mondo_id
        disease_confidence = disease_record.confidence

        # Create stable program ID
        program_id = self._make_program_id(asset_name, company_id or trial.sponsor, disease_id)

        # Collect source references
        source_refs = [trial.nct_id] if trial.nct_id else []
        if trial.source_ref:
            source_refs.append(trial.source_ref)

        # Overall confidence is minimum of mappings
        overall_confidence = min(
            asset_confidence,
            (1.0 if sponsor_is_public or company_id else 0.7),
            disease_confidence,
            (0.8 if trial_stage else 0.6),
        )

        program = ProgramRecord(
            program_id=program_id,
            asset_id=(
                asset_resolved.get("asset_id", self._make_asset_id(asset_name))
                if asset_resolved
                else self._make_asset_id(asset_name)
            ),
            asset_name=asset_name,
            company_id=company_id,
            ticker=ticker,
            ticker_resolution_source=ticker_resolution_source,
            ticker_resolution_confidence=ticker_resolution_confidence,
            ticker_resolution_warnings=ticker_resolution_warnings,
            company_name=trial.sponsor,
            disease_id=disease_id,
            disease_name=disease_name,
            mondo_id=mondo_id,
            therapeutic_area=None,  # Will be computed later if needed
            indication_detail=condition,
            clinical_stage=trial_stage,
            trial_ids=[trial.nct_id] if trial.nct_id else [],
            regulatory_status=None,
            source_priority="ctgov",
            source_refs=source_refs,
            confidence=overall_confidence,
            as_of_date=self.as_of_date,
        )

        return program

    def _make_program_id(self, asset_name: str, sponsor_name: str, disease_id: str) -> str:
        """Create stable program ID from asset, sponsor, disease."""
        key = f"{asset_name}|{sponsor_name}|{disease_id}|{self.as_of_date}".lower().strip()
        hash_hex = hashlib.sha256(key.encode()).hexdigest()[:16]
        return f"PROGRAM_{hash_hex}"

    def _make_asset_id(self, asset_name: str) -> str:
        """Create stable asset ID."""
        normalized = asset_name.lower().strip()
        hash_hex = hashlib.sha256(normalized.encode()).hexdigest()[:16]
        return f"ASSET_{hash_hex}"

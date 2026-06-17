"""Ingest ClinicalTrials.gov data from local cache/fixtures only."""

import json
from pathlib import Path
from typing import Any, Optional

from scientific_cartography.schemas.trial_schema import TrialRecord


class CTGovIngest:
    """Parse ClinicalTrials.gov data from local caches/fixtures."""

    def __init__(self, as_of_date: str = ""):
        """Initialize ingester.

        Args:
            as_of_date: Date for records (YYYY-MM-DD).
        """
        self.as_of_date = as_of_date

    def ingest_from_json_file(self, json_path: Path) -> list[TrialRecord]:
        """Ingest single trial from JSON file.

        Supports both:
        - Single study object: {"protocolSection": {...}}
        - Array of studies: [{"protocolSection": {...}}, ...]
        - Fixture format: [{"nct_id": "NCT...", ...}, ...]

        Args:
            json_path: Path to JSON file.

        Returns:
            List of TrialRecords.
        """
        records = []
        if not json_path.exists():
            return records

        try:
            with open(json_path) as f:
                data = json.load(f)

            # Handle array
            if isinstance(data, list):
                for item in data:
                    record = self._parse_trial_object(item)
                    if record:
                        records.append(record)

            # Handle single study
            elif isinstance(data, dict):
                record = self._parse_trial_object(data)
                if record:
                    records.append(record)

        except Exception as e:
            print(f"Warning: Failed to ingest from {json_path}: {e}")

        return records

    def ingest_from_jsonl_file(self, jsonl_path: Path) -> list[TrialRecord]:
        """Ingest from JSONL file (one trial per line).

        Args:
            jsonl_path: Path to JSONL file.

        Returns:
            List of TrialRecords.
        """
        records = []
        if not jsonl_path.exists():
            return records

        try:
            with open(jsonl_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    data = json.loads(line)
                    record = self._parse_trial_object(data)
                    if record:
                        records.append(record)

        except Exception as e:
            print(f"Warning: Failed to ingest from {jsonl_path}: {e}")

        return records

    def _parse_trial_object(self, data: dict) -> Optional[TrialRecord]:
        """Parse trial object in any supported format.

        Handles:
        - API v2 format: {"protocolSection": {...}}
        - Simplified fixture format: {"nct_id": "NCT...", ...}

        Args:
            data: Trial data object.

        Returns:
            TrialRecord or None if unparseable.
        """
        if not isinstance(data, dict):
            return None

        # Check for simplified fixture format
        if "nct_id" in data:
            return self._parse_simplified_format(data)

        # Check for API v2 format
        if "protocolSection" in data:
            return self._parse_api_v2_format(data)

        return None

    def _parse_simplified_format(self, data: dict) -> Optional[TrialRecord]:
        """Parse simplified test fixture format.

        Args:
            data: Data with nct_id, brief_title, sponsor, conditions, interventions, phases.

        Returns:
            TrialRecord or None.
        """
        nct_id = data.get("nct_id", "").strip()
        if not nct_id:
            return None

        brief_title = data.get("brief_title", "").strip() or "Unknown"

        return TrialRecord(
            nct_id=nct_id,
            brief_title=brief_title,
            official_title=data.get("official_title"),
            sponsor=data.get("sponsor"),
            collaborators=data.get("collaborators", []),
            conditions=self._ensure_list(data.get("conditions", [])),
            interventions=self._ensure_list(data.get("interventions", [])),
            phases=self._ensure_list(data.get("phases", [])),
            overall_status=data.get("overall_status"),
            enrollment=data.get("enrollment"),
            study_type=data.get("study_type"),
            allocation=data.get("allocation"),
            masking=data.get("masking"),
            primary_purpose=data.get("primary_purpose"),
            start_date=data.get("start_date"),
            primary_completion_date=data.get("primary_completion_date"),
            study_completion_date=data.get("study_completion_date"),
            primary_endpoints=self._ensure_list(data.get("primary_endpoints", [])),
            secondary_endpoints=self._ensure_list(data.get("secondary_endpoints", [])),
            has_results=data.get("has_results", False),
            source_ref=nct_id,
            as_of_date=self.as_of_date,
        )

    def _parse_api_v2_format(self, data: dict) -> Optional[TrialRecord]:
        """Parse ClinicalTrials.gov API v2 format.

        Args:
            data: Data with protocolSection.

        Returns:
            TrialRecord or None.
        """
        protocol = data.get("protocolSection", {})
        id_section = protocol.get("identificationModule", {})
        status_section = protocol.get("statusModule", {})
        design_section = protocol.get("designModule", {})
        contacts_section = protocol.get("contactsLocationsModule", {})
        arms_section = protocol.get("armsInterventionsModule", {})
        outcomes_section = protocol.get("outcomesModule", {})

        nct_id = id_section.get("nctId", "").strip()
        if not nct_id:
            return None

        brief_title = id_section.get("briefTitle", "").strip() or "Unknown"
        official_title = id_section.get("officialTitle")

        sponsor_name = id_section.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name")

        conditions = []
        condition_list = id_section.get("conditionModule", {}).get("conditions", [])
        if isinstance(condition_list, list):
            conditions = [c.get("name") if isinstance(c, dict) else str(c) for c in condition_list if c]

        interventions = []
        intervention_list = arms_section.get("interventions", [])
        if isinstance(intervention_list, list):
            for interv in intervention_list:
                if isinstance(interv, dict):
                    name = interv.get("name")
                    if name:
                        interventions.append(name)

        phases = design_section.get("phases", []) or []
        if isinstance(phases, str):
            phases = [phases]

        overall_status = status_section.get("overallStatus")
        enrollment = status_section.get("enrollmentInfo", {}).get("count")
        study_type = design_section.get("studyType")
        allocation = design_section.get("allocation")
        masking = design_section.get("maskingInfo", {}).get("masking") if design_section.get("maskingInfo") else None
        primary_purpose = (
            design_section.get("primaryPurpose", {}).get("type") if design_section.get("primaryPurpose") else None
        )

        status_dates = status_section.get("statusDatesModule", {})
        start_date = status_dates.get("studyFirstPostDate")
        primary_completion_date = status_dates.get("primaryCompletionDateStruct", {}).get("date")
        study_completion_date = status_dates.get("completionDateStruct", {}).get("date")

        primary_endpoints = []
        secondary_endpoints = []

        if outcomes_section:
            primary_list = outcomes_section.get("primaryOutcomes", [])
            if isinstance(primary_list, list):
                primary_endpoints = [o.get("measure") for o in primary_list if isinstance(o, dict) and o.get("measure")]

            secondary_list = outcomes_section.get("secondaryOutcomes", [])
            if isinstance(secondary_list, list):
                secondary_endpoints = [
                    o.get("measure") for o in secondary_list if isinstance(o, dict) and o.get("measure")
                ]

        has_results = bool(data.get("resultsSection"))

        return TrialRecord(
            nct_id=nct_id,
            brief_title=brief_title,
            official_title=official_title,
            sponsor=sponsor_name,
            collaborators=[],
            conditions=conditions,
            interventions=interventions,
            phases=phases,
            overall_status=overall_status,
            enrollment=enrollment,
            study_type=study_type,
            allocation=allocation,
            masking=masking,
            primary_purpose=primary_purpose,
            start_date=start_date,
            primary_completion_date=primary_completion_date,
            study_completion_date=study_completion_date,
            primary_endpoints=primary_endpoints,
            secondary_endpoints=secondary_endpoints,
            has_results=has_results,
            source_ref=nct_id,
            as_of_date=self.as_of_date,
        )

    def _ensure_list(self, value: Any) -> list:
        """Ensure value is a list."""
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [value] if value.strip() else []
        return []

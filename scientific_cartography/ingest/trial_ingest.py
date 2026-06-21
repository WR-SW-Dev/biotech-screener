"""Ingest trial mappings and AACT snapshots (cache-only, point-in-time safe).

Phase 2 trial ingester. Combines two local data sources into
``TrialRecord`` objects keyed by ticker:

1. ``trial_mapping.csv`` — the ticker → NCT_ID mapping table maintained by the
   screener. Columns:
   ``ticker,nct_id,effective_start,effective_end,source,sponsor_name_at_map_time,mapping_confidence``

2. An AACT snapshot directory (``data/aact_snapshots/<snapshot_date>/``)
   containing ``studies.csv`` (phase / status / dates, optionally conditions
   and interventions) and ``sponsors.csv`` (lead + collaborator names).

The ingester is point-in-time aware: a mapping row whose ``effective_end`` is
before the requested ``as_of_date`` is dropped, so programs only reflect trials
that were still mapped as of that date. No network access is performed.
"""

import csv
from pathlib import Path
from typing import Optional

from scientific_cartography.schemas.trial_schema import TrialRecord


# Map raw mapping-source labels to canonical source_priority buckets.
_SOURCE_PRIORITY_MAP = {
    "clinicaltrials.gov": "ctgov",
    "ctgov": "ctgov",
    "company_ir": "company_ir",
    "sec": "sec",
    "fda": "fda",
    "manual": "manual",
}

# Map mapping_confidence labels to numeric confidence values.
_CONFIDENCE_MAP = {
    "high": 0.95,
    "medium": 0.80,
    "low": 0.60,
}


def _normalize_confidence(raw: Optional[str]) -> float:
    """Resolve a mapping_confidence label to a float in [0, 1]."""
    if not raw:
        return 0.60
    key = raw.strip().lower()
    return _CONFIDENCE_MAP.get(key, 0.60)


def _normalize_source(raw: Optional[str]) -> str:
    """Resolve a mapping source label to a canonical source_priority string."""
    if not raw:
        return "manual"
    return _SOURCE_PRIORITY_MAP.get(raw.strip().lower(), raw.strip().lower())


class TrialIngest:
    """Load trial mappings + an AACT snapshot into TrialRecords by ticker."""

    def __init__(self, as_of_date: str = ""):
        """Initialize trial ingester.

        Args:
            as_of_date: Point-in-time date (YYYY-MM-DD). Mapping rows whose
                ``effective_end`` precedes this date are excluded.
        """
        self.as_of_date = as_of_date

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def ingest(
        self,
        trial_mapping_csv: Path,
        snapshot_dir: Optional[Path] = None,
    ) -> dict[str, list[TrialRecord]]:
        """Ingest trial mappings merged with an AACT snapshot.

        Args:
            trial_mapping_csv: Path to ``trial_mapping.csv``.
            snapshot_dir: Directory containing ``studies.csv`` and
                ``sponsors.csv`` for one AACT snapshot. Optional; when
                omitted only mapping-table fields are populated.

        Returns:
            Dict mapping ticker (uppercase) → list of TrialRecords. Only
            trials still mapped as of ``as_of_date`` are included.
        """
        studies = self._load_studies(snapshot_dir)
        sponsors = self._load_sponsors(snapshot_dir)

        mappings = self._load_mappings(trial_mapping_csv)

        by_ticker: dict[str, list[TrialRecord]] = {}
        for row in mappings:
            ticker = (row.get("ticker") or "").strip().upper()
            nct_id = (row.get("nct_id") or "").strip()
            if not ticker or not nct_id:
                continue

            # Point-in-time filter: drop mappings that ended before as_of_date.
            effective_end = (row.get("effective_end") or "").strip()
            if effective_end and self.as_of_date and effective_end < self.as_of_date:
                continue

            study = studies.get(nct_id, {})
            trial = self._build_trial(ticker, nct_id, row, study, sponsors.get(nct_id, []))
            by_ticker.setdefault(ticker, []).append(trial)

        # Deterministic ordering within each ticker by NCT ID.
        for ticker in by_ticker:
            by_ticker[ticker].sort(key=lambda t: t.nct_id)
        return by_ticker

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------
    def _load_mappings(self, csv_path: Path) -> list[dict]:
        """Load trial_mapping.csv into a list of row dicts."""
        rows: list[dict] = []
        if not csv_path.exists():
            return rows
        try:
            with open(csv_path, newline="") as f:
                for row in csv.DictReader(f):
                    rows.append(row)
        except Exception as e:  # pragma: no cover - defensive
            print(f"Warning: Failed to ingest trial mapping {csv_path}: {e}")
        return rows

    def _load_studies(self, snapshot_dir: Optional[Path]) -> dict[str, dict]:
        """Load studies.csv → {nct_id: row_dict}."""
        studies: dict[str, dict] = {}
        if not snapshot_dir:
            return studies
        path = snapshot_dir / "studies.csv"
        if not path.exists():
            return studies
        try:
            with open(path, newline="") as f:
                for row in csv.DictReader(f):
                    nct_id = (row.get("nct_id") or "").strip()
                    if nct_id:
                        studies[nct_id] = row
        except Exception as e:  # pragma: no cover - defensive
            print(f"Warning: Failed to ingest studies {path}: {e}")
        return studies

    def _load_sponsors(self, snapshot_dir: Optional[Path]) -> dict[str, list[dict]]:
        """Load sponsors.csv → {nct_id: [row_dict, ...]}."""
        sponsors: dict[str, list[dict]] = {}
        if not snapshot_dir:
            return sponsors
        path = snapshot_dir / "sponsors.csv"
        if not path.exists():
            return sponsors
        try:
            with open(path, newline="") as f:
                for row in csv.DictReader(f):
                    nct_id = (row.get("nct_id") or "").strip()
                    if nct_id:
                        sponsors.setdefault(nct_id, []).append(row)
        except Exception as e:  # pragma: no cover - defensive
            print(f"Warning: Failed to ingest sponsors {path}: {e}")
        return sponsors

    # ------------------------------------------------------------------
    # Record construction
    # ------------------------------------------------------------------
    def _build_trial(
        self,
        ticker: str,
        nct_id: str,
        mapping_row: dict,
        study: dict,
        sponsor_rows: list[dict],
    ) -> TrialRecord:
        """Merge a mapping row with study/sponsor rows into a TrialRecord."""
        # Phase + status come from the AACT snapshot (study row).
        phases: list[str] = []
        overall_status: Optional[str] = None
        primary_completion_date: Optional[str] = None
        study_type: Optional[str] = None
        conditions: list[str] = []
        interventions: list[str] = []

        if study:
            phase_raw = (study.get("phase") or "").strip()
            if phase_raw:
                # AACT stores combined phases like "Phase 2/Phase 3" in one
                # cell; keep the raw string so StageNormalizer can split it.
                phases = [phase_raw]
            overall_status = (study.get("overall_status") or "").strip() or None
            primary_completion_date = (study.get("primary_completion_date") or "").strip() or None
            study_type = (study.get("study_type") or "").strip() or None

            # Optional columns (present in richer snapshots / fixtures).
            conditions = self._split_cell(study.get("conditions"))
            interventions = self._split_cell(study.get("interventions"))

        # Sponsor: prefer the mapping table's point-in-time sponsor name,
        # fall back to the AACT lead sponsor.
        sponsor = (mapping_row.get("sponsor_name_at_map_time") or "").strip() or None
        if not sponsor:
            sponsor = self._lead_sponsor_name(sponsor_rows)

        collaborators = [
            (r.get("name") or "").strip()
            for r in sponsor_rows
            if (r.get("lead_or_collaborator") or "").upper() == "COLLABORATOR"
            and (r.get("name") or "").strip()
        ]

        mapping_confidence = _normalize_confidence(mapping_row.get("mapping_confidence"))
        source_label = _normalize_source(mapping_row.get("source"))

        return TrialRecord(
            nct_id=nct_id,
            brief_title=f"{ticker} trial {nct_id}",
            sponsor=sponsor,
            ticker=ticker,
            collaborators=collaborators,
            conditions=conditions,
            interventions=interventions,
            phases=phases,
            overall_status=overall_status,
            study_type=study_type,
            primary_completion_date=primary_completion_date,
            source_ref=f"{source_label}:{nct_id}",
            as_of_date=self.as_of_date,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _lead_sponsor_name(sponsor_rows: list[dict]) -> Optional[str]:
        for r in sponsor_rows:
            if (r.get("lead_or_collaborator") or "").upper() == "LEAD":
                name = (r.get("name") or "").strip()
                if name:
                    return name
        return None

    @staticmethod
    def _split_cell(value) -> list[str]:
        """Split a CSV cell into a clean list (handles '|' and ';' delimiters)."""
        if not value:
            return []
        text = str(value).strip()
        if not text:
            return []
        for delim in ("|", ";"):
            if delim in text:
                return [p.strip() for p in text.split(delim) if p.strip()]
        return [text]

    # Exposed for the builder so it can carry provenance through.
    @staticmethod
    def normalize_source(raw: Optional[str]) -> str:
        """Public wrapper around the source-priority normalizer."""
        return _normalize_source(raw)

    @staticmethod
    def normalize_confidence(raw: Optional[str]) -> float:
        """Public wrapper around the confidence normalizer."""
        return _normalize_confidence(raw)

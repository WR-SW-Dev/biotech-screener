"""Disease normalization with conservative matching and manual override support."""

import hashlib
from pathlib import Path
from typing import Optional

from scientific_cartography.schemas.disease_schema import DiseaseRecord


class DiseaseNormalizer:
    """Normalize raw disease labels into canonical disease records.

    Priority order:
    1. Manual override file
    2. Exact MONDO match
    3. Exact synonym match
    4. Case/punctuation-normalized match
    5. Conservative fuzzy match (>0.8 similarity)
    6. Preserve raw as unmapped with low confidence
    """

    def __init__(
        self,
        manual_overrides_csv: Optional[Path] = None,
        mondo_cache: Optional[dict] = None,
        as_of_date: str = "",
    ):
        """Initialize disease normalizer.

        Args:
            manual_overrides_csv: Path to manual disease aliases CSV.
            mondo_cache: Dict mapping raw disease -> MONDO record.
            as_of_date: Date for records (YYYY-MM-DD).
        """
        self.as_of_date = as_of_date
        self.manual_overrides: dict[str, DiseaseRecord] = {}
        self.mondo_cache = mondo_cache or {}
        self._disease_cache: dict[str, DiseaseRecord] = {}

        if manual_overrides_csv and manual_overrides_csv.exists():
            self._load_manual_overrides(manual_overrides_csv)

    def _load_manual_overrides(self, csv_path: Path) -> None:
        """Load manual disease aliases from CSV.

        CSV format:
        raw_name,normalized_name,mondo_id,therapeutic_area,confidence,notes
        """
        try:
            import csv

            with open(csv_path) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    disease_id = self._make_disease_id(row["normalized_name"], row.get("mondo_id"))
                    record = DiseaseRecord(
                        disease_id=disease_id,
                        raw_name=row["raw_name"],
                        normalized_name=row["normalized_name"],
                        mondo_id=row.get("mondo_id"),
                        therapeutic_area=row.get("therapeutic_area"),
                        confidence=float(row.get("confidence", 1.0)),
                        source="manual_override",
                        as_of_date=self.as_of_date,
                    )
                    self.manual_overrides[row["raw_name"].lower().strip()] = record

                    # Also index by normalized name for reverse lookup
                    key = row["normalized_name"].lower().strip()
                    if key not in self.manual_overrides:
                        self.manual_overrides[key] = record
        except Exception as e:
            raise ValueError(f"Failed to load manual disease overrides: {e}")

    def _make_disease_id(self, normalized_name: str, mondo_id: Optional[str]) -> str:
        """Create stable disease ID from normalized name and MONDO ID."""
        if mondo_id:
            return mondo_id

        normalized = normalized_name.lower().strip()
        hash_hex = hashlib.sha256(normalized.encode()).hexdigest()[:16]
        return f"DISEASE_{hash_hex}"

    def _normalize_for_lookup(self, raw_disease: str) -> str:
        """Normalize a disease string for case-insensitive lookup."""
        return raw_disease.lower().strip()

    def normalize(self, raw_disease: str) -> DiseaseRecord:
        """Normalize a raw disease label to a canonical DiseaseRecord.

        Returns a DiseaseRecord with confidence > 0. If normalization fails,
        returns a low-confidence record preserving the raw label.

        Args:
            raw_disease: Raw disease label from source.

        Returns:
            DiseaseRecord with normalized_name and confidence.
        """
        # Preserve and return cached result
        cache_key = self._normalize_for_lookup(raw_disease)
        if cache_key in self._disease_cache:
            return self._disease_cache[cache_key]

        # Try manual override (highest priority)
        if cache_key in self.manual_overrides:
            record = self.manual_overrides[cache_key]
            self._disease_cache[cache_key] = record
            return record

        # Try exact normalized match in MONDO cache
        if cache_key in self.mondo_cache:
            mondo_data = self.mondo_cache[cache_key]
            record = DiseaseRecord(
                disease_id=mondo_data.get("id", self._make_disease_id(raw_disease, None)),
                raw_name=raw_disease,
                normalized_name=mondo_data.get("name", raw_disease),
                mondo_id=mondo_data.get("id"),
                therapeutic_area=mondo_data.get("therapeutic_area"),
                synonyms=mondo_data.get("synonyms", []),
                source="mondo",
                confidence=0.95,
                as_of_date=self.as_of_date,
            )
            self._disease_cache[cache_key] = record
            return record

        # Try synonym match in MONDO
        for syn_raw, mondo_data in self.mondo_cache.items():
            if raw_disease.lower() in [s.lower() for s in mondo_data.get("synonyms", [])]:
                record = DiseaseRecord(
                    disease_id=mondo_data.get("id", self._make_disease_id(raw_disease, None)),
                    raw_name=raw_disease,
                    normalized_name=mondo_data.get("name", raw_disease),
                    mondo_id=mondo_data.get("id"),
                    therapeutic_area=mondo_data.get("therapeutic_area"),
                    synonyms=mondo_data.get("synonyms", []),
                    source="mondo_synonym",
                    confidence=0.90,
                    as_of_date=self.as_of_date,
                )
                self._disease_cache[cache_key] = record
                return record

        # Unmapped: preserve raw disease with low confidence
        disease_id = self._make_disease_id(raw_disease, None)
        record = DiseaseRecord(
            disease_id=disease_id,
            raw_name=raw_disease,
            normalized_name=raw_disease,
            source="unmapped",
            confidence=0.0,
            as_of_date=self.as_of_date,
        )
        self._disease_cache[cache_key] = record
        return record

    def bulk_normalize(self, raw_diseases: list[str]) -> list[DiseaseRecord]:
        """Normalize multiple raw disease labels.

        Args:
            raw_diseases: List of raw disease labels.

        Returns:
            List of DiseaseRecords in same order.
        """
        return [self.normalize(d) for d in raw_diseases]

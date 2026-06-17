"""Resolve sponsor names to company records conservatively."""

import re
from typing import Optional

from scientific_cartography.schemas.company_schema import CompanyRecord


class SponsorResolver:
    """Resolve raw sponsor names to company records."""

    # Common corporate suffixes for conservative stripping
    CORPORATE_SUFFIXES = [
        # Comma-prefixed variants (highest priority)
        r",\s*incorporated\s*$",
        r",\s*inc\.?\s*$",
        r",\s*corporation\s*$",
        r",\s*corp\.?\s*$",
        r",\s*limited\s*$",
        r",\s*ltd\.?\s*$",
        # Space-prefixed variants
        r"\s+incorporated\s*$",
        r"\s+inc\.?\s*$",
        r"\s+corporation\s*$",
        r"\s+corp\.?\s*$",
        r"\s+limited\s*$",
        r"\s+ltd\.?\s*$",
        r"\s+limited\s+liability\s+company\s*$",
        r"\s+llc\s*$",
        r"\s+therapeutics\s*$",
        r"\s+pharmaceuticals\s*$",
        r"\s+biosciences\s*$",
        r"\s+biotech\s*$",
        r"\s+biopharm\s*$",
        r"\s+plc\s*$",
    ]

    def __init__(
        self,
        company_records: Optional[list[CompanyRecord]] = None,
        sponsor_aliases: Optional[dict[str, str]] = None,
    ):
        """Initialize sponsor resolver.

        Args:
            company_records: List of known CompanyRecords.
            sponsor_aliases: Dict mapping raw_sponsor_name -> company_id.
        """
        self.company_records = company_records or []
        self.sponsor_aliases = sponsor_aliases or {}
        self._build_lookup_indices()
        self._cache: dict[str, Optional[dict]] = {}

    def _build_lookup_indices(self) -> None:
        """Build lookup indices for fast company matching."""
        self.by_ticker = {}
        self.by_name = {}
        self.by_name_normalized = {}
        self.by_cik = {}

        for company in self.company_records:
            if company.ticker:
                self.by_ticker[company.ticker.lower()] = company

            if company.company_name:
                self.by_name[company.company_name.lower()] = company
                # Also index normalized (suffix-stripped) version
                normalized = self._strip_corporate_suffix(company.company_name)
                if normalized and normalized != company.company_name.lower():
                    self.by_name_normalized[normalized] = company

            if company.cik:
                self.by_cik[company.cik.lower()] = company

            # Index aliases
            for alias in company.aliases:
                self.by_name[alias.lower()] = company
                normalized = self._strip_corporate_suffix(alias)
                if normalized and normalized != alias.lower():
                    self.by_name_normalized[normalized] = company

    def _normalize_for_lookup(self, sponsor_name: str) -> str:
        """Normalize sponsor name for lookup (lowercase + strip whitespace)."""
        return sponsor_name.lower().strip()

    def _strip_corporate_suffix(self, name: str) -> str:
        """Strip common corporate suffixes from name (conservative).

        Args:
            name: Company or sponsor name.

        Returns:
            Name with corporate suffix removed (or original if no suffix).
        """
        normalized = self._normalize_for_lookup(name)
        for suffix_pattern in self.CORPORATE_SUFFIXES:
            result = re.sub(suffix_pattern, "", normalized, flags=re.IGNORECASE)
            if result != normalized:
                return result.strip()
        return normalized

    def resolve(self, raw_sponsor_name: str) -> Optional[dict]:
        """Resolve raw sponsor name to company record.

        Returns dict with keys:
        - company_id: internal ID
        - ticker: ticker if public
        - company_name: canonical name
        - confidence: 0.0 to 1.0
        - resolution_status: resolved_public, resolved_private_or_unknown, ambiguous, unknown
        - warnings: list of warning strings
        - is_public: whether mapped to public company

        Args:
            raw_sponsor_name: Raw sponsor name from trial.

        Returns:
            Dict with company info or None if completely unparseable.
        """
        # Check cache
        cache_key = self._normalize_for_lookup(raw_sponsor_name)
        if cache_key in self._cache:
            return self._cache[cache_key]

        warnings = []
        normalized = self._normalize_for_lookup(raw_sponsor_name)

        # Try manual sponsor alias (highest priority)
        if normalized in self.sponsor_aliases:
            company_id = self.sponsor_aliases[normalized]
            company = next((c for c in self.company_records if c.company_id == company_id), None)
            if company:
                result = {
                    "company_id": company.company_id,
                    "ticker": company.ticker,
                    "company_name": company.company_name,
                    "confidence": 0.95,
                    "resolution_status": "resolved_public" if company.is_public else "resolved_private_or_unknown",
                    "warnings": [],
                    "is_public": company.is_public,
                }
                self._cache[cache_key] = result
                return result

        # Try exact ticker match
        if normalized in self.by_ticker:
            company = self.by_ticker[normalized]
            result = {
                "company_id": company.company_id,
                "ticker": company.ticker,
                "company_name": company.company_name,
                "confidence": 0.95,
                "resolution_status": "resolved_public",
                "warnings": [],
                "is_public": True,
            }
            self._cache[cache_key] = result
            return result

        # Try exact company name match
        if normalized in self.by_name:
            company = self.by_name[normalized]
            result = {
                "company_id": company.company_id,
                "ticker": company.ticker,
                "company_name": company.company_name,
                "confidence": 0.90,
                "resolution_status": "resolved_public" if company.is_public else "resolved_private_or_unknown",
                "warnings": [],
                "is_public": company.is_public,
            }
            self._cache[cache_key] = result
            return result

        # Try CIK match if sponsor looks like CIK
        if raw_sponsor_name.isdigit():
            if normalized in self.by_cik:
                company = self.by_cik[normalized]
                result = {
                    "company_id": company.company_id,
                    "ticker": company.ticker,
                    "company_name": company.company_name,
                    "confidence": 0.90,
                    "resolution_status": "resolved_public" if company.is_public else "resolved_private_or_unknown",
                    "warnings": [],
                    "is_public": company.is_public,
                }
                self._cache[cache_key] = result
                return result

        # Try normalized (suffix-stripped) company name match
        normalized_sponsor = self._strip_corporate_suffix(raw_sponsor_name)
        if normalized_sponsor != normalized and normalized_sponsor in self.by_name_normalized:
            company = self.by_name_normalized[normalized_sponsor]
            result = {
                "company_id": company.company_id,
                "ticker": company.ticker,
                "company_name": company.company_name,
                "confidence": 0.85,  # Slightly lower confidence for suffix-stripped match
                "resolution_status": "resolved_public" if company.is_public else "resolved_private_or_unknown",
                "warnings": ["matched via normalized name (suffix stripped)"],
                "is_public": company.is_public,
            }
            self._cache[cache_key] = result
            return result

        # No match found
        warnings.append("Sponsor not found in known company list")
        result = {
            "company_id": None,
            "ticker": None,
            "company_name": raw_sponsor_name,
            "confidence": 0.0,
            "resolution_status": "unknown",
            "warnings": warnings,
            "is_public": False,
        }
        self._cache[cache_key] = result
        return result

    def bulk_resolve(self, sponsor_names: list[str]) -> list[Optional[dict]]:
        """Resolve multiple sponsor names.

        Args:
            sponsor_names: List of raw sponsor names.

        Returns:
            List of resolved company records in same order (may contain None).
        """
        return [self.resolve(name) for name in sponsor_names]

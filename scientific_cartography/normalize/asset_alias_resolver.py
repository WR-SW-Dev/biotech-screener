"""Resolve asset names conservatively with ambiguity preservation."""

import hashlib
from typing import Optional


class AssetAliasResolver:
    """Resolve asset names to canonical asset records conservatively."""

    def __init__(
        self,
        asset_aliases: Optional[dict[str, dict]] = None,
        as_of_date: str = "",
    ):
        """Initialize asset resolver.

        Args:
            asset_aliases: Dict mapping raw_name -> {normalized_name, asset_id, ...}
            as_of_date: Date for records (YYYY-MM-DD).
        """
        self.as_of_date = as_of_date
        self.asset_aliases = asset_aliases or {}
        self._cache: dict[str, Optional[dict]] = {}

    def _normalize_for_lookup(self, raw_asset: str) -> str:
        """Normalize asset string for lookup."""
        return raw_asset.lower().strip()

    def resolve(self, raw_asset_name: str, sponsor_name: Optional[str] = None) -> Optional[dict]:
        """Resolve a raw asset name to a canonical asset record.

        Returns dict with keys:
        - asset_name: normalized name
        - asset_id: stable ID
        - confidence: 0.0 to 1.0
        - resolution_status: resolved, ambiguous, unknown
        - warnings: list of warning strings
        - source_refs: list of source references

        Args:
            raw_asset_name: Raw asset name from source.
            sponsor_name: Optional sponsor name for context.

        Returns:
            Dict with asset info or None if resolution fails badly.
        """
        # Check cache
        cache_key = self._normalize_for_lookup(raw_asset_name)
        if cache_key in self._cache:
            return self._cache[cache_key]

        warnings = []

        # Try exact manual alias match
        if cache_key in self.asset_aliases:
            alias_data = self.asset_aliases[cache_key]
            result = {
                "asset_name": alias_data.get("normalized_name", raw_asset_name),
                "asset_id": alias_data.get("asset_id", self._make_asset_id(raw_asset_name)),
                "confidence": alias_data.get("confidence", 0.95),
                "resolution_status": "resolved",
                "warnings": [],
                "source_refs": alias_data.get("source_refs", []),
            }
            self._cache[cache_key] = result
            return result

        # Check for ambiguous matches (multiple possible assets)
        matching_aliases = [k for k in self.asset_aliases.keys() if cache_key in k or k in cache_key]
        if len(matching_aliases) > 1:
            warnings.append(f"Ambiguous asset name (matches {len(matching_aliases)} aliases)")
            result = {
                "asset_name": raw_asset_name,
                "asset_id": self._make_asset_id(raw_asset_name),
                "confidence": 0.0,
                "resolution_status": "ambiguous",
                "warnings": warnings,
                "source_refs": [],
            }
            self._cache[cache_key] = result
            return result

        # Unknown asset
        warnings.append("Asset name not found in alias dictionary")
        result = {
            "asset_name": raw_asset_name,
            "asset_id": self._make_asset_id(raw_asset_name),
            "confidence": 0.0,
            "resolution_status": "unknown",
            "warnings": warnings,
            "source_refs": [],
        }
        self._cache[cache_key] = result
        return result

    def _make_asset_id(self, asset_name: str) -> str:
        """Create stable asset ID from name."""
        normalized = asset_name.lower().strip()
        hash_hex = hashlib.sha256(normalized.encode()).hexdigest()[:16]
        return f"ASSET_{hash_hex}"

    def bulk_resolve(self, asset_names: list[str], sponsor_name: Optional[str] = None) -> list[Optional[dict]]:
        """Resolve multiple asset names.

        Args:
            asset_names: List of raw asset names.
            sponsor_name: Optional sponsor name for context.

        Returns:
            List of resolved asset records in same order (may contain None).
        """
        return [self.resolve(name, sponsor_name) for name in asset_names]

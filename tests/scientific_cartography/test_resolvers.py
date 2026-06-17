"""Tests for Phase 2 resolver modules."""

import pytest

from scientific_cartography.normalize.asset_alias_resolver import AssetAliasResolver
from scientific_cartography.normalize.sponsor_resolver import SponsorResolver
from scientific_cartography.schemas.company_schema import CompanyRecord


class TestAssetAliasResolver:
    """Test asset alias resolution."""

    @pytest.fixture
    def resolver(self):
        asset_aliases = {
            "asset a": {"normalized_name": "Asset A", "asset_id": "ASSET_111", "confidence": 0.95},
            "asset b": {"normalized_name": "Asset B", "asset_id": "ASSET_222", "confidence": 0.95},
        }
        return AssetAliasResolver(asset_aliases=asset_aliases, as_of_date="2026-06-16")

    def test_exact_match(self, resolver):
        """Should resolve exact alias match."""
        result = resolver.resolve("Asset A")

        assert result is not None
        assert result["asset_name"] == "Asset A"
        assert result["resolution_status"] == "resolved"
        assert result["confidence"] == 0.95

    def test_case_insensitive_match(self, resolver):
        """Should match case-insensitively."""
        result = resolver.resolve("asset a")

        assert result is not None
        assert result["asset_name"] == "Asset A"

    def test_unknown_asset(self, resolver):
        """Should preserve unknown assets."""
        result = resolver.resolve("Unknown Asset XYZ")

        assert result is not None
        assert result["asset_name"] == "Unknown Asset XYZ"
        assert result["resolution_status"] == "unknown"
        assert result["confidence"] == 0.0
        assert len(result["warnings"]) > 0

    def test_caching(self, resolver):
        """Repeated resolution should use cache."""
        result1 = resolver.resolve("Asset A")
        result2 = resolver.resolve("Asset A")

        # Should be same object from cache
        assert result1 is result2

    def test_bulk_resolve(self, resolver):
        """Should resolve multiple assets."""
        results = resolver.bulk_resolve(["Asset A", "Unknown X", "Asset B"])

        assert len(results) == 3
        assert results[0]["resolution_status"] == "resolved"
        assert results[1]["resolution_status"] == "unknown"
        assert results[2]["resolution_status"] == "resolved"


class TestSponsorResolver:
    """Test sponsor resolution to companies."""

    @pytest.fixture
    def company_records(self):
        return [
            CompanyRecord(
                company_id="COMP_111",
                ticker="COGT",
                company_name="Cognito Therapeutics",
                is_public=True,
                as_of_date="2026-06-16",
                aliases=["Cognito"],
            ),
            CompanyRecord(
                company_id="COMP_222",
                company_name="Academic Institution",
                is_public=False,
                as_of_date="2026-06-16",
            ),
        ]

    @pytest.fixture
    def resolver(self, company_records):
        return SponsorResolver(company_records=company_records)

    def test_exact_ticker_match(self, resolver):
        """Should resolve by exact ticker match."""
        result = resolver.resolve("COGT")

        assert result is not None
        assert result["ticker"] == "COGT"
        assert result["resolution_status"] == "resolved_public"
        assert result["is_public"] is True

    def test_exact_company_name_match(self, resolver):
        """Should resolve by exact company name match."""
        result = resolver.resolve("Cognito Therapeutics")

        assert result is not None
        assert result["company_name"] == "Cognito Therapeutics"
        assert result["resolution_status"] == "resolved_public"

    def test_alias_match(self, resolver):
        """Should resolve by company alias."""
        result = resolver.resolve("Cognito")

        assert result is not None
        assert result["company_name"] == "Cognito Therapeutics"

    def test_private_company_resolution(self, resolver):
        """Should resolve non-public companies."""
        result = resolver.resolve("Academic Institution")

        assert result is not None
        assert result["resolution_status"] == "resolved_private_or_unknown"
        assert result["is_public"] is False

    def test_unknown_sponsor(self, resolver):
        """Should preserve unknown sponsors."""
        result = resolver.resolve("Completely Unknown Sponsor XYZ")

        assert result is not None
        assert result["company_id"] is None
        assert result["ticker"] is None
        assert result["resolution_status"] == "unknown"
        assert result["confidence"] == 0.0

    def test_caching(self, resolver):
        """Repeated resolution should use cache."""
        result1 = resolver.resolve("Cognito Therapeutics")
        result2 = resolver.resolve("Cognito Therapeutics")

        assert result1 is result2

    def test_bulk_resolve(self, resolver):
        """Should resolve multiple sponsors."""
        results = resolver.bulk_resolve(["COGT", "Academic Institution", "Unknown X"])

        assert len(results) == 3
        assert results[0]["resolution_status"] == "resolved_public"
        assert results[1]["resolution_status"] == "resolved_private_or_unknown"
        assert results[2]["resolution_status"] == "unknown"

"""Tests for common.feature_registry -- centralized feature metadata."""

from __future__ import annotations

import pytest

from common.feature_registry import (
    _VALID_DTYPES,
    _VALID_SOURCES,
    FEATURE_REGISTRY,
    FeatureSpec,
    get_context_keys,
    get_feature_keys,
    get_features_by_source,
    get_snapshot_dynamic_columns,
    validate_registry,
)

# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------


class TestRegistryIntegrity:
    """Ensure the registry data itself is well-formed."""

    def test_all_features_have_valid_dtypes(self):
        for f in FEATURE_REGISTRY:
            assert f.dtype in _VALID_DTYPES, f"Feature '{f.name}' has invalid dtype '{f.dtype}'"

    def test_all_features_have_valid_sources(self):
        for f in FEATURE_REGISTRY:
            assert f.source in _VALID_SOURCES, f"Feature '{f.name}' has invalid source '{f.source}'"

    def test_no_duplicate_feature_names(self):
        names = [f.name for f in FEATURE_REGISTRY]
        assert len(names) == len(set(names)), f"Duplicate names: {[n for n in names if names.count(n) > 1]}"

    def test_validate_registry_clean(self):
        errors = validate_registry()
        assert errors == [], f"Registry validation errors: {errors}"

    def test_feature_count_regression_guard(self):
        """Catch accidental additions/removals. Update this count intentionally."""
        assert len(FEATURE_REGISTRY) == 29  # 28 + 1 (protocol_quality_score added)

    def test_feature_spec_is_frozen(self):
        f = FEATURE_REGISTRY[0]
        with pytest.raises(AttributeError):
            f.name = "hacked"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Helper function contracts
# ---------------------------------------------------------------------------


class TestGetFeatureKeys:
    """get_feature_keys() must match the legacy _FEATURE_KEYS tuple."""

    def test_returns_tuple(self):
        assert isinstance(get_feature_keys(), tuple)

    def test_all_strings(self):
        for k in get_feature_keys():
            assert isinstance(k, str)

    def test_matches_legacy_feature_keys(self):
        """Exact match against the legacy constant from loaders.py."""
        legacy = (
            "coinvest_score_z",
            "inst_delta_z",
            # insider_net_buy_value_90d: removed (closed lane)
            "alpha_60d",
            "de_alpha_60d",
            "de_rsi_14d",
            "short_interest_pct",
            "opt_event_premium",
            "opt_term_slope",
            "opt_atm_iv",
            "opt_front_iv",
            "opt_back_iv",
            "priced_move_pct",
            "implied_event_move",
            "opt_liquidity_state",
            "opt_iv_regime",
            "market_cap_mm",
            "vol_60d",
            "de_vol_60d",
            "selector_score",
            "catalyst_days",
            "close_price",
            "catalyst_family",
            "endpoint_strength_score",
            "design_quality_score",
            "execution_momentum",
            "binary_quality_score",
            "competitive_intensity_z",
            "program_diversification",
            "protocol_quality_score",
        )
        assert get_feature_keys() == legacy


class TestGetContextKeys:
    """get_context_keys() must match the legacy _CONTEXT_KEYS tuple."""

    def test_returns_tuple(self):
        assert isinstance(get_context_keys(), tuple)

    def test_matches_legacy_context_keys(self):
        legacy = (
            "market_cap_mm",
            "vol_60d",
            "implied_event_move",
            "opt_liquidity_state",
            "opt_atm_iv",
            "opt_front_iv",
            "opt_back_iv",
            "opt_iv_regime",
            "catalyst_family",
            "endpoint_strength_score",
            "design_quality_score",
            "execution_momentum",
            "binary_quality_score",
            "competitive_intensity_z",
            "program_diversification",
            "underlying_price",
        )
        assert get_context_keys() == legacy

    def test_context_keys_subset_of_feature_keys_plus_extras(self):
        """Every context key must be either a feature key or in the known extras."""
        feature_set = set(get_feature_keys())
        known_extras = {"underlying_price"}
        for k in get_context_keys():
            assert k in feature_set or k in known_extras, f"Context key '{k}' is not in feature_keys or known extras"


class TestGetFeaturesBySource:
    def test_returns_list_of_feature_specs(self):
        result = get_features_by_source("clinical")
        assert all(isinstance(f, FeatureSpec) for f in result)
        assert all(f.source == "clinical" for f in result)

    def test_clinical_count(self):
        clinical = get_features_by_source("clinical")
        assert len(clinical) == 7  # 6 clinical discriminators + protocol_quality_score

    def test_unknown_source_returns_empty(self):
        assert get_features_by_source("nonexistent") == []


class TestGetSnapshotDynamicColumns:
    def test_returns_tuple(self):
        assert isinstance(get_snapshot_dynamic_columns(), tuple)

    def test_snapshot_columns_subset_of_features(self):
        feature_set = set(get_feature_keys())
        for col in get_snapshot_dynamic_columns():
            assert col in feature_set

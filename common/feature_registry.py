"""Centralized feature registry for the biotech screener.

Single source of truth for feature names, types, and roles. Eliminates
manual synchronization of _FEATURE_KEYS, _CONTEXT_KEYS, and snapshot
columns across event_ev/loaders.py and run_screen_columns.py.

Usage::

    from common.feature_registry import get_feature_keys, get_context_keys

    # Drop-in replacements for the old tuples
    feature_keys = get_feature_keys()
    context_keys = get_context_keys()
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class FeatureSpec:
    """Metadata for a single feature used in the scoring pipeline.

    Attributes:
        name: Column name as it appears in rankings.csv / snapshots.
        dtype: Expected Python type string (``"float"``, ``"str"``, ``"int"``, ``"bool"``).
        source: Data provenance bucket (``"market"``, ``"clinical"``, ``"options"``,
                ``"institutional"``, ``"structure"``).
        context_eligible: If True the feature is forwarded to the Event EV
                          outcome / payoff models via ``split_context_features``.
        snapshot_column: If True the feature is one of the *dynamic* columns
                         that should appear in validation snapshots.
    """

    name: str
    dtype: str  # "float", "str", "int", "bool"
    source: str  # "market", "clinical", "options", "institutional", "structure"
    context_eligible: bool = False
    snapshot_column: bool = False


_VALID_DTYPES = frozenset({"float", "str", "int", "bool"})
_VALID_SOURCES = frozenset({"market", "clinical", "options", "institutional", "structure"})

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
# Order matches the original _FEATURE_KEYS / _CONTEXT_KEYS in event_ev/loaders.py
# so that the derived tuples are identical to the legacy constants.

FEATURE_REGISTRY: Tuple[FeatureSpec, ...] = (
    # --- Market / institutional features ---
    FeatureSpec("coinvest_score_z", "float", "institutional"),
    FeatureSpec("inst_delta_z", "float", "institutional"),
    # insider_net_buy_value_90d: REMOVED — lane closed (Form 4 revalidation 2026-04-05)
    FeatureSpec("alpha_60d", "float", "market"),
    FeatureSpec("de_alpha_60d", "float", "market"),
    FeatureSpec("de_rsi_14d", "float", "market"),
    FeatureSpec("short_interest_pct", "float", "market"),
    # --- Options features ---
    FeatureSpec("opt_event_premium", "bool", "options"),
    FeatureSpec("opt_term_slope", "float", "options"),
    FeatureSpec("opt_atm_iv", "float", "options", context_eligible=True),
    FeatureSpec("opt_front_iv", "float", "options", context_eligible=True),
    FeatureSpec("opt_back_iv", "float", "options", context_eligible=True),
    FeatureSpec("priced_move_pct", "float", "options"),
    FeatureSpec("implied_event_move", "float", "options", context_eligible=True),
    FeatureSpec("opt_liquidity_state", "str", "options", context_eligible=True),
    FeatureSpec("opt_iv_regime", "str", "options", context_eligible=True),
    # --- Market structure ---
    FeatureSpec("market_cap_mm", "float", "structure", context_eligible=True),
    FeatureSpec("vol_60d", "float", "market", context_eligible=True),
    FeatureSpec("de_vol_60d", "float", "market"),
    FeatureSpec("selector_score", "float", "structure"),
    FeatureSpec("catalyst_days", "float", "structure"),
    FeatureSpec("close_price", "float", "market"),
    FeatureSpec("catalyst_family", "str", "structure", context_eligible=True),
    # --- Clinical discriminators (outcome model p_hit updates) ---
    FeatureSpec("endpoint_strength_score", "float", "clinical", context_eligible=True),
    FeatureSpec("design_quality_score", "float", "clinical", context_eligible=True),
    FeatureSpec("execution_momentum", "float", "clinical", context_eligible=True),
    FeatureSpec("binary_quality_score", "float", "clinical", context_eligible=True),
    FeatureSpec("competitive_intensity_z", "float", "clinical", context_eligible=True),
    FeatureSpec("program_diversification", "float", "clinical", context_eligible=True),
)

# Explicit context key ordering — matches the legacy _CONTEXT_KEYS tuple
# in event_ev/loaders.py exactly. The order groups market/options features
# first (for the payoff model), then clinical discriminators.
# "underlying_price" is synthesized from close_price in loaders.py,
# so it lives in context but not in the feature extraction loop.
_CONTEXT_KEY_ORDER: Tuple[str, ...] = (
    # Market / options features (for payoff model)
    "market_cap_mm",
    "vol_60d",
    "implied_event_move",
    "opt_liquidity_state",
    "opt_atm_iv",
    "opt_front_iv",
    "opt_back_iv",
    "opt_iv_regime",
    "catalyst_family",
    # Clinical discriminators (for outcome model p_hit updates)
    "endpoint_strength_score",
    "design_quality_score",
    "execution_momentum",
    "binary_quality_score",
    "competitive_intensity_z",
    "program_diversification",
    # Synthesized (not in feature extraction loop)
    "underlying_price",
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_feature_keys() -> Tuple[str, ...]:
    """Return feature names in the same order as the legacy ``_FEATURE_KEYS``.

    Drop-in replacement for ``event_ev.loaders._FEATURE_KEYS``.
    """
    return tuple(f.name for f in FEATURE_REGISTRY)


def get_context_keys() -> Tuple[str, ...]:
    """Return context-eligible feature names plus extra synthesized keys.

    Drop-in replacement for ``event_ev.loaders._CONTEXT_KEYS``.
    The order matches the original constant exactly.
    """
    return _CONTEXT_KEY_ORDER


def get_snapshot_dynamic_columns() -> Tuple[str, ...]:
    """Return the subset of registry features flagged for snapshot output.

    These are the *dynamic* columns that should appear in
    ``SNAPSHOT_COLUMNS`` in ``run_screen_columns.py``.  The full
    ``SNAPSHOT_COLUMNS`` list also contains many static / identity /
    diagnostics columns that are NOT managed by this registry.
    """
    return tuple(f.name for f in FEATURE_REGISTRY if f.snapshot_column)


def get_features_by_source(source: str) -> List[FeatureSpec]:
    """Return all features from a given data source."""
    return [f for f in FEATURE_REGISTRY if f.source == source]


def validate_registry() -> List[str]:
    """Run basic integrity checks and return a list of error messages (empty = OK)."""
    errors: List[str] = []
    seen: set[str] = set()
    for f in FEATURE_REGISTRY:
        if f.name in seen:
            errors.append(f"Duplicate feature name: {f.name}")
        seen.add(f.name)
        if f.dtype not in _VALID_DTYPES:
            errors.append(f"Invalid dtype '{f.dtype}' for feature '{f.name}'")
        if f.source not in _VALID_SOURCES:
            errors.append(f"Invalid source '{f.source}' for feature '{f.name}'")

    # Context key order must be consistent with registry flags
    feature_set = set(f.name for f in FEATURE_REGISTRY)
    context_eligible = set(f.name for f in FEATURE_REGISTRY if f.context_eligible)
    known_synth = {"underlying_price"}
    for k in _CONTEXT_KEY_ORDER:
        if k not in feature_set and k not in known_synth:
            errors.append(f"Context key '{k}' not in registry or known synthetics")
        if k in feature_set and k not in context_eligible and k not in known_synth:
            errors.append(f"Context key '{k}' is in registry but not flagged context_eligible")

    return errors

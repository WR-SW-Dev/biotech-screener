"""
Ranker Engine — Spec 050: catalyst-window bounded ranking adjustment.

Pure function module. Activates only for names within the catalyst event
window that have sufficient data coverage. Produces a bounded adjustment
to the SelectorScore, capped at ±max_adjustment_pct.

Five blocks:
  1. Options/EventPremium       (default 35%)
  2. InstitutionalRefinement    (default 25%)
  3. AACT/Timeline Deltas       (default 20%)
  4. CatalystNuance             (default 10%)
  5. Microstructure/Attention   (default 10%)

Design constraints:
  - Deterministic: same inputs → same outputs
  - Bounded: |adjustment| <= max_adj * selector_score
  - Activation-gated: only fires when catalyst + data conditions met
  - Stdlib-only: no external dependencies
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, NamedTuple, Tuple

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert to float, handling None/str/NaN."""
    if val is None:
        return default
    try:
        if isinstance(val, str) and val.strip() == "":
            return default
        v = float(val)
        if v != v:
            return default
        return v
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RankerSignalSpec:
    """Specification for a ranker input signal."""

    name: str
    weight: float
    higher_is_better: bool = True
    categorical: bool = False
    value_map: Tuple[Tuple[str, float], ...] = ()


@dataclass(frozen=True)
class RankerConfig:
    """Immutable configuration for the ranker engine.

    Default weights reflect the Analyst Rank model (Spec 050):
      - 30% clinical quality
      - 25% catalyst timing/quality
      - 20% survivability/financing
      - 15% institutional confirmation
      - 5%  options/event-pricing overlay
      - 5%  competitive pipeline penalty

    Block names (options, institutional, aact, catalyst_nuance, microstructure)
    are internal slot names. The signal specs within each slot determine what
    is actually measured — the slot names do not constrain the signal content.
    """

    # --- Activation gates ---
    activation_max_catalyst_days: int = 120
    activation_min_catalyst_days: int = 1  # must have a real catalyst (>0)
    activation_require_options: bool = False  # analyst rank works for all top-30
    activation_eligible_buckets: Tuple[str, ...] = ("top10", "top30", "top60")

    # --- Bounding ---
    max_adjustment_pct: float = 0.15  # ±15% of selector_score

    # --- Block weights (must sum to 1.0) ---
    # Slot mapping: options→options_overlay, institutional→institutional_confirm,
    # aact→clinical_quality, catalyst_nuance→catalyst_timing, microstructure→survivability+competitive
    # clinical_50 blend: validated by PIT blend sweep (+2.34pp net, t=2.57, best bull at -0.11)
    options_weight: float = 0.05  # options/event-pricing overlay
    institutional_weight: float = 0.10  # institutional confirmation
    aact_weight: float = 0.50  # clinical quality (repurposed slot)
    catalyst_nuance_weight: float = 0.20  # catalyst timing/quality
    microstructure_weight: float = 0.15  # survivability + competitive penalty

    # --- Per-block signal specs ---

    # Slot: options → 5% options/event-pricing overlay
    options_signals: Tuple[RankerSignalSpec, ...] = (
        RankerSignalSpec("ovf_composite", 0.30),
        RankerSignalSpec("cheap_vol_score", 0.25),
        RankerSignalSpec("opt_rr_25d", 0.20),
        RankerSignalSpec("opt_event_premium", 0.15),
        RankerSignalSpec(
            "opt_iv_regime",
            0.10,
            categorical=True,
            value_map=(("LOW", 0.8), ("NORMAL", 0.5), ("HIGH", 0.3), ("EXTREME", 0.1), ("", 0.5)),
        ),
    )

    # Slot: institutional → 15% institutional confirmation
    institutional_signals: Tuple[RankerSignalSpec, ...] = (
        RankerSignalSpec("inst_delta_z", 0.45),
        RankerSignalSpec("coinvest_filing_age_days", 0.25, higher_is_better=False),
        RankerSignalSpec("coinvest_conviction", 0.15),
        RankerSignalSpec("inst_delta_net", 0.15),
    )

    # Slot: aact → 30% clinical quality
    aact_signals: Tuple[RankerSignalSpec, ...] = (
        RankerSignalSpec("endpoint_strength_score", 0.25),
        RankerSignalSpec("design_quality_score", 0.25),
        RankerSignalSpec("clinical_optionality_pct_dev", 0.20),
        RankerSignalSpec("program_diversification", 0.15),
        RankerSignalSpec(
            "single_asset_risk",
            0.15,
            higher_is_better=False,
            categorical=True,
            value_map=(("yes", 1.0), ("no", 0.0), ("", 0.5)),
        ),
    )

    # Slot: catalyst_nuance → 25% catalyst timing/quality
    catalyst_nuance_signals: Tuple[RankerSignalSpec, ...] = (
        RankerSignalSpec("catalyst_decay_w", 0.25),
        RankerSignalSpec("binary_quality_score", 0.25),
        RankerSignalSpec("cat_priority", 0.20, higher_is_better=False),
        RankerSignalSpec(
            "catalyst_family",
            0.15,
            categorical=True,
            value_map=(("REGULATORY", 1.0), ("CLINICAL", 0.6), ("SAFETY", 0.3), ("", 0.0)),
        ),
        RankerSignalSpec(
            "catalyst_type_tier",
            0.15,
            categorical=True,
            value_map=(("T1", 1.0), ("T2", 0.8), ("T3", 0.5), ("T4", 0.3), ("T5", 0.2), ("", 0.0)),
        ),
    )

    # Slot: microstructure → 20% survivability + 5% competitive penalty
    # Survivability signals have positive weight, competitive_intensity_z is
    # inverted (higher crowding → worse) via higher_is_better=False
    microstructure_signals: Tuple[RankerSignalSpec, ...] = (
        RankerSignalSpec("financial_score", 0.30),
        RankerSignalSpec(
            "severity",
            0.25,
            higher_is_better=False,
            categorical=True,
            value_map=(("NONE", 0.0), ("", 0.0), ("SEV1", 0.33), ("SEV2", 0.67), ("SEV3", 1.0)),
        ),
        RankerSignalSpec(
            "runway_bucket",
            0.25,
            categorical=True,
            value_map=(("adequate", 1.0), ("short", 0.4), ("critical", 0.0), ("", 0.5)),
        ),
        RankerSignalSpec("competitive_intensity_z", 0.20, higher_is_better=False),
    )

    # --- Missingness penalty per missing signal ---
    missing_signal_penalty: float = 0.10

    # --- Z-score bounds for numeric signals ---
    # Ranker uses [-2, 2] → [-0.5, 0.5] (centered adjustments). Tighter than
    # the selector ([-3, 3]) because the ranker operates on a pre-filtered
    # cohort (top-60) where extreme outliers are noise, not signal.
    z_score_clamp: float = 2.0


DEFAULT_RANKER_CONFIG = RankerConfig()


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


class RankerResult(NamedTuple):
    """Output for a single ticker."""

    ranker_active: bool
    ranker_adjustment: float  # bounded, added to selector_score
    final_score: float  # selector_score + ranker_adjustment
    options_block: float  # block sub-scores (informational)
    inst_block: float
    aact_block: float
    gate_reason: str  # "" if active, else reason gate failed


# ---------------------------------------------------------------------------
# Cohort statistics (within ranker-eligible subset)
# ---------------------------------------------------------------------------


class _RankerCohortStats(NamedTuple):
    mean: float
    std: float


def _compute_ranker_cohort_stats(
    rows: List[Dict[str, Any]],
    signal_name: str,
) -> _RankerCohortStats:
    """Compute mean/std for a signal across ranker-eligible rows."""
    vals: list[float] = []
    for row in rows:
        v = _safe_float(row.get(signal_name), default=float("nan"))
        if v == v:
            vals.append(v)
    if len(vals) < 2:
        return _RankerCohortStats(mean=0.0, std=1.0)
    mean = sum(vals) / len(vals)
    variance = sum((x - mean) ** 2 for x in vals) / len(vals)
    std = math.sqrt(variance) if variance > 0 else 1.0
    return _RankerCohortStats(mean=mean, std=std)


# ---------------------------------------------------------------------------
# Signal scoring (same pattern as selector, but centered on 0 for adjustment)
# ---------------------------------------------------------------------------


def _score_ranker_signal(
    row: Dict[str, Any],
    spec: RankerSignalSpec,
    cohort_stats: Dict[str, _RankerCohortStats],
    z_clamp: float = 2.0,
) -> Tuple[float, bool]:
    """Score a single ranker signal.

    Returns (score, is_missing). Score is centered around 0.0 for numeric
    signals (z-space, clamped to [-z_clamp, z_clamp] then rescaled to
    [-0.5, 0.5]), or [-0.5, 0.5] for categorical.

    The ranker uses z_clamp=2.0 (tighter than selector's 3.0) because it
    operates on a pre-filtered cohort where extreme outliers are noise.
    """
    raw = row.get(spec.name)

    if spec.categorical:
        vmap = dict(spec.value_map)
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            val = vmap.get("", None)
            if val is None:
                return (0.0, True)
            if not spec.higher_is_better:
                val = 1.0 - val
            # Center around 0.5 → shift to -0.5..+0.5 for adjustment math
            return (val - 0.5, False)
        key = str(raw).strip()
        if key in vmap:
            val = vmap[key]
            if not spec.higher_is_better:
                val = 1.0 - val
            return (val - 0.5, False)
        return (0.0, True)

    # Numeric: z-score
    fval = _safe_float(raw, default=float("nan"))
    if fval != fval:
        return (0.0, True)

    stats = cohort_stats.get(spec.name)
    if stats is None or stats.std == 0:
        return (0.0, False)

    z = (fval - stats.mean) / stats.std
    z = max(-z_clamp, min(z_clamp, z))

    if not spec.higher_is_better:
        z = -z

    # Normalize to [-0.5, 0.5] for aggregation
    score = z / (2.0 * z_clamp)
    return (score, False)


def _compute_ranker_block(
    row: Dict[str, Any],
    signals: Tuple[RankerSignalSpec, ...],
    cohort_stats: Dict[str, _RankerCohortStats],
    missing_penalty: float,
    z_clamp: float = 2.0,
) -> Tuple[float, int]:
    """Compute a weighted ranker block score centered around 0.

    Returns (block_score, missing_count).
    """
    total_weight = 0.0
    weighted_sum = 0.0
    missing_count = 0

    for spec in signals:
        score, is_missing = _score_ranker_signal(row, spec, cohort_stats, z_clamp=z_clamp)
        if is_missing:
            missing_count += 1
            score = -missing_penalty  # penalize missing toward negative
        weighted_sum += spec.weight * score
        total_weight += spec.weight

    if total_weight <= 0:
        return (0.0, missing_count)

    return (weighted_sum / total_weight, missing_count)


# ---------------------------------------------------------------------------
# Activation gate
# ---------------------------------------------------------------------------


def _check_activation_gate(
    row: Dict[str, Any],
    selector_rank_bucket: str,
    config: RankerConfig,
) -> Tuple[bool, str]:
    """Check whether ranker should activate for this row.

    Returns (active, reason). reason is "" if active.
    """
    # Bucket check
    if selector_rank_bucket not in config.activation_eligible_buckets:
        return (False, f"bucket={selector_rank_bucket}")

    # Catalyst days check
    cat_days = _safe_float(row.get("catalyst_days"), default=0.0)
    if cat_days < config.activation_min_catalyst_days:
        return (False, "no_catalyst")
    if cat_days > config.activation_max_catalyst_days:
        return (False, f"catalyst_too_far={int(cat_days)}d")

    # Options data check
    if config.activation_require_options:
        opt_raw = row.get("opt_has_data", "")
        # Handle both "1" and "1.0" (CSV round-trip artifact)
        try:
            opt_has = float(opt_raw) if opt_raw not in (None, "") else 0.0
        except (ValueError, TypeError):
            opt_has = 0.0
        if opt_has != 1.0:
            return (False, "no_options_data")

    return (True, "")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def compute_ranker_adjustments(
    rows: List[Dict[str, Any]],
    selector_scores: List[float],
    selector_buckets: List[str],
    config: RankerConfig = DEFAULT_RANKER_CONFIG,
) -> List[RankerResult]:
    """Compute ranker adjustments for all rows.

    Args:
        rows: csv_row dicts (same order as selector results).
        selector_scores: selector_score per row.
        selector_buckets: selector_rank_bucket per row.
        config: RankerConfig.

    Returns:
        List of RankerResult in same order as input.
    """
    if not rows:
        return []

    n = len(rows)

    # --- Identify ranker-eligible rows ---
    eligible_mask: list[bool] = []
    gate_reasons: list[str] = []
    for i in range(n):
        active, reason = _check_activation_gate(rows[i], selector_buckets[i], config)
        eligible_mask.append(active)
        gate_reasons.append(reason)

    eligible_rows = [rows[i] for i in range(n) if eligible_mask[i]]

    # --- Precompute cohort stats for ranker-eligible subset ---
    all_signals = (
        list(config.options_signals)
        + list(config.institutional_signals)
        + list(config.aact_signals)
        + list(config.catalyst_nuance_signals)
        + list(config.microstructure_signals)
    )
    cohort_stats: Dict[str, _RankerCohortStats] = {}
    for spec in all_signals:
        if not spec.categorical and spec.name not in cohort_stats:
            cohort_stats[spec.name] = _compute_ranker_cohort_stats(eligible_rows, spec.name)

    # --- Compute adjustments ---
    block_configs = [
        ("options", config.options_signals, config.options_weight),
        ("institutional", config.institutional_signals, config.institutional_weight),
        ("aact", config.aact_signals, config.aact_weight),
        ("catalyst_nuance", config.catalyst_nuance_signals, config.catalyst_nuance_weight),
        ("microstructure", config.microstructure_signals, config.microstructure_weight),
    ]

    total_block_weight = sum(bc[2] for bc in block_configs)
    if total_block_weight <= 0:
        total_block_weight = 1.0

    results: list[RankerResult] = []
    for i in range(n):
        if not eligible_mask[i]:
            results.append(
                RankerResult(
                    ranker_active=False,
                    ranker_adjustment=0.0,
                    final_score=selector_scores[i],
                    options_block=0.0,
                    inst_block=0.0,
                    aact_block=0.0,
                    gate_reason=gate_reasons[i],
                )
            )
            continue

        # Compute block scores
        raw_adj = 0.0
        block_scores: dict[str, float] = {}
        for block_name, signals, weight in block_configs:
            bscore, _ = _compute_ranker_block(
                rows[i],
                signals,
                cohort_stats,
                config.missing_signal_penalty,
                z_clamp=config.z_score_clamp,
            )
            block_scores[block_name] = round(bscore, 6)
            raw_adj += weight * bscore

        raw_adj /= total_block_weight

        # Bound the adjustment
        sel_score = selector_scores[i]
        max_abs = config.max_adjustment_pct * max(sel_score, 0.01)  # floor to avoid zero-mult
        bounded_adj = max(-max_abs, min(max_abs, raw_adj))

        results.append(
            RankerResult(
                ranker_active=True,
                ranker_adjustment=round(bounded_adj, 6),
                final_score=round(sel_score + bounded_adj, 6),
                options_block=block_scores.get("options", 0.0),
                inst_block=block_scores.get("institutional", 0.0),
                aact_block=block_scores.get("aact", 0.0),
                gate_reason="",
            )
        )

    return results


# ---------------------------------------------------------------------------
# Column constants
# ---------------------------------------------------------------------------

RANKER_COLUMNS = [
    "ranker_active",
    "ranker_adjustment",
    "final_score",
    "ranker_options_block",
    "ranker_inst_block",
    "ranker_aact_block",
]

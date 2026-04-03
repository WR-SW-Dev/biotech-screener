"""
Selector Engine — Spec 050: multi-block scoring for universe ranking.

Pure function module. Consumes csv_row dicts (already computed by Modules 1-5
and the decision engine overlays) and produces a SelectorScore per ticker.

Five blocks:
  1. ClinicalOptionality  (default 35%)
  2. CatalystArchitecture (default 25%)
  3. FinancialSurvivability (default 20%)
  4. InstitutionalFreshness (default 10%)
  5. MarketStructure       (default 10%)

Each block computes a normalized sub-score from its input signals.
The SelectorScore is the weighted sum of block scores, percentile-normalized
across the eligible cohort.

Design constraints:
  - Deterministic: Decimal arithmetic on scoring paths (CCFT)
  - PIT-safe: z-scoring uses same-snapshot cohort only
  - Fail-closed: missing signals → penalized, never crash
  - Stdlib-only: no external dependencies
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, NamedTuple, Tuple

# ---------------------------------------------------------------------------
# Decimal helpers (match decision_engine.py patterns)
# ---------------------------------------------------------------------------

_D = Decimal
_D0 = Decimal("0")
_D1 = Decimal("1")
_HALF = Decimal("0.5")


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert to float, handling None/str/NaN."""
    if val is None:
        return default
    try:
        if isinstance(val, str) and val.strip() == "":
            return default
        v = float(val)
        if v != v:  # NaN
            return default
        return v
    except (ValueError, TypeError):
        return default


def _safe_decimal(val: Any, default: Decimal = _D0) -> Decimal:
    """Convert to Decimal via str intermediary (CCFT determinism)."""
    if val is None:
        return default
    if isinstance(val, Decimal):
        return val
    try:
        if isinstance(val, str) and val.strip() == "":
            return default
        v = float(val)
        if v != v:
            return default
        return Decimal(str(v))
    except (ValueError, TypeError, ArithmeticError):
        return default


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BlockWeight:
    """A named block with its weight."""

    name: str
    weight: float


@dataclass(frozen=True)
class SignalSpec:
    """Specification for a single input signal within a block."""

    name: str  # csv_row key
    weight: float  # relative weight within the block
    higher_is_better: bool = True
    categorical: bool = False  # if True, mapped via value_map
    value_map: Tuple[Tuple[str, float], ...] = ()  # (value, score) pairs


@dataclass(frozen=True)
class SelectorConfig:
    """Immutable configuration for the selector engine.

    Block weights must sum to 1.0. Signal weights within each block are
    relative (normalized internally).
    """

    # --- Block weights ---
    block_weights: Tuple[BlockWeight, ...] = (
        BlockWeight("clinical", 0.35),
        BlockWeight("catalyst", 0.25),
        BlockWeight("survivability", 0.20),
        BlockWeight("institutional", 0.10),
        BlockWeight("market_structure", 0.10),
    )

    # --- Per-block signal specs ---
    clinical_signals: Tuple[SignalSpec, ...] = (
        SignalSpec("clinical_optionality_pct_dev", 0.30),
        SignalSpec("program_count", 0.10),
        SignalSpec("program_diversification", 0.10),
        SignalSpec("endpoint_strength_score", 0.15),
        SignalSpec("design_quality_score", 0.10),
        SignalSpec("readout_density_90", 0.10),
        SignalSpec(
            "single_asset_risk", 0.10, higher_is_better=False, categorical=True, value_map=(("yes", 1.0), ("no", 0.0))
        ),
        SignalSpec("execution_momentum", 0.05),
    )

    catalyst_signals: Tuple[SignalSpec, ...] = (
        SignalSpec("catalyst_decay_w", 0.30),
        SignalSpec("binary_quality_score", 0.25),
        SignalSpec("cat_priority", 0.20, higher_is_better=False),  # lower priority = better
        SignalSpec(
            "catalyst_strength",
            0.15,
            categorical=True,
            value_map=(("NEAR", 1.0), ("MID", 0.6), ("FAR", 0.3), ("MISSING", 0.0)),
        ),
        SignalSpec(
            "catalyst_family",
            0.10,
            categorical=True,
            value_map=(("REGULATORY", 1.0), ("CLINICAL", 0.7), ("SAFETY", 0.3), ("", 0.0), ("UNKNOWN", 0.0)),
        ),
    )

    survivability_signals: Tuple[SignalSpec, ...] = (
        SignalSpec("financial_score", 0.35),
        SignalSpec(
            "severity",
            0.35,
            higher_is_better=False,
            categorical=True,
            value_map=(("NONE", 0.0), ("", 0.0), ("SEV1", 0.33), ("SEV2", 0.67), ("SEV3", 1.0)),
        ),
        SignalSpec(
            "runway_bucket",
            0.30,
            categorical=True,
            value_map=(("adequate", 1.0), ("short", 0.4), ("critical", 0.0), ("", 0.5)),
        ),
    )

    institutional_signals: Tuple[SignalSpec, ...] = (
        SignalSpec("coinvest_score_z", 0.50),
        SignalSpec("inst_delta_z", 0.30),
        SignalSpec(
            "coinvest_recency_state", 0.20, categorical=True, value_map=(("fresh", 1.0), ("stale", 0.3), ("", 0.0))
        ),
    )

    market_structure_signals: Tuple[SignalSpec, ...] = (
        SignalSpec("de_vol_60d", 0.30, higher_is_better=False),
        SignalSpec("de_beta_xbi_60d", 0.25, higher_is_better=False),
        SignalSpec("de_drawdown", 0.25),  # less negative = better
        SignalSpec("de_rsi_14d", 0.20, higher_is_better=False),  # overbought penalized
    )

    # --- Missingness penalty per missing signal (subtracted from block score) ---
    missing_signal_penalty: float = 0.10

    # --- Rank bucket cutoffs ---
    top_10_cutoff: int = 10
    top_30_cutoff: int = 30
    top_60_cutoff: int = 60
    top_120_cutoff: int = 120


DEFAULT_SELECTOR_CONFIG = SelectorConfig()


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


class SelectorResult(NamedTuple):
    """Output for a single ticker."""

    selector_score: float  # [0, 1] percentile-normalized
    selector_rank_bucket: str  # top10/top30/top60/top120/below
    clinical_block: float  # block sub-score (pre-weighting)
    catalyst_block: float
    survivability_block: float
    institutional_block: float
    market_structure_block: float
    missing_count: int  # total missing signals across all blocks


# ---------------------------------------------------------------------------
# Cohort statistics for cross-sectional z-scoring
# ---------------------------------------------------------------------------


class _CohortStats(NamedTuple):
    mean: float
    std: float


def _compute_cohort_stats(
    rows: List[Dict[str, Any]],
    signal_name: str,
) -> _CohortStats:
    """Compute mean and std for a numeric signal across the cohort.

    Uses population std (ddof=0) to match existing z-scoring in run_screen.py.
    Ignores missing/blank values.
    """
    vals: list[float] = []
    for row in rows:
        v = _safe_float(row.get(signal_name), default=float("nan"))
        if v == v:  # not NaN
            vals.append(v)
    if len(vals) < 2:
        return _CohortStats(mean=0.0, std=1.0)  # degenerate cohort
    mean = sum(vals) / len(vals)
    variance = sum((x - mean) ** 2 for x in vals) / len(vals)
    std = math.sqrt(variance) if variance > 0 else 1.0
    return _CohortStats(mean=mean, std=std)


# ---------------------------------------------------------------------------
# Block scoring
# ---------------------------------------------------------------------------


def _score_signal(
    row: Dict[str, Any],
    spec: SignalSpec,
    cohort_stats: Dict[str, _CohortStats],
) -> Tuple[float, bool]:
    """Score a single signal for a row.

    Returns (score, is_missing). Score is in roughly [-2, 2] z-space for
    numeric signals, [0, 1] for categorical signals.
    """
    raw = row.get(spec.name)

    if spec.categorical:
        # Map via value_map
        vmap = dict(spec.value_map)
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            val = vmap.get("", None)
            if val is None:
                return (0.0, True)
            # For categorical with a "" mapping, it's "present but empty"
            if not spec.higher_is_better:
                val = 1.0 - val
            return (val, False)
        key = str(raw).strip()
        if key in vmap:
            val = vmap[key]
            if not spec.higher_is_better:
                val = 1.0 - val
            return (val, False)
        return (0.0, True)

    # Numeric: z-score using cohort stats
    fval = _safe_float(raw, default=float("nan"))
    if fval != fval:  # NaN → missing
        return (0.0, True)

    stats = cohort_stats.get(spec.name)
    if stats is None or stats.std == 0:
        return (0.0, False)

    z = (fval - stats.mean) / stats.std
    # Clamp to [-3, 3] to limit outlier influence
    z = max(-3.0, min(3.0, z))

    if not spec.higher_is_better:
        z = -z

    # Rescale z from [-3, 3] to [0, 1] for uniform block aggregation
    score = (z + 3.0) / 6.0
    return (score, False)


def _compute_block_score(
    row: Dict[str, Any],
    signals: Tuple[SignalSpec, ...],
    cohort_stats: Dict[str, _CohortStats],
    missing_penalty: float,
) -> Tuple[float, int]:
    """Compute a weighted block sub-score.

    Returns (block_score in [0, 1], missing_count).
    """
    total_weight = 0.0
    weighted_sum = 0.0
    missing_count = 0

    for spec in signals:
        score, is_missing = _score_signal(row, spec, cohort_stats)
        if is_missing:
            missing_count += 1
            # Missing signal: use neutral score (0.5) minus penalty
            score = max(0.0, 0.5 - missing_penalty)
        weighted_sum += spec.weight * score
        total_weight += spec.weight

    if total_weight <= 0:
        return (0.5, missing_count)  # degenerate: neutral

    block_score = weighted_sum / total_weight
    # Clamp to [0, 1]
    block_score = max(0.0, min(1.0, block_score))
    return (block_score, missing_count)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def compute_selector_scores(
    eligible_rows: List[Dict[str, Any]],
    config: SelectorConfig = DEFAULT_SELECTOR_CONFIG,
) -> List[SelectorResult]:
    """Compute selector scores for all eligible rows.

    Args:
        eligible_rows: list of csv_row dicts (one per eligible ticker).
            Each dict must contain the signal keys referenced by config.
        config: SelectorConfig with block/signal weights.

    Returns:
        List of SelectorResult in the same order as eligible_rows.
        Scores are percentile-normalized across the cohort.
    """
    if not eligible_rows:
        return []

    # --- Step 1: Precompute cohort statistics for numeric signals ---
    all_signal_specs = (
        list(config.clinical_signals)
        + list(config.catalyst_signals)
        + list(config.survivability_signals)
        + list(config.institutional_signals)
        + list(config.market_structure_signals)
    )
    cohort_stats: Dict[str, _CohortStats] = {}
    for spec in all_signal_specs:
        if not spec.categorical and spec.name not in cohort_stats:
            cohort_stats[spec.name] = _compute_cohort_stats(eligible_rows, spec.name)

    # --- Step 2: Compute raw block scores per row ---
    block_specs = {
        "clinical": config.clinical_signals,
        "catalyst": config.catalyst_signals,
        "survivability": config.survivability_signals,
        "institutional": config.institutional_signals,
        "market_structure": config.market_structure_signals,
    }

    block_weight_map = {bw.name: bw.weight for bw in config.block_weights}
    total_block_weight = sum(bw.weight for bw in config.block_weights)
    if total_block_weight <= 0:
        total_block_weight = 1.0

    raw_scores: list[float] = []
    block_details: list[dict] = []

    for row in eligible_rows:
        weighted_sum = 0.0
        row_blocks: dict[str, float] = {}
        total_missing = 0

        for block_name, signals in block_specs.items():
            bscore, bmissing = _compute_block_score(row, signals, cohort_stats, config.missing_signal_penalty)
            row_blocks[block_name] = round(bscore, 6)
            total_missing += bmissing
            bw = block_weight_map.get(block_name, 0.0)
            weighted_sum += bw * bscore

        raw_score = weighted_sum / total_block_weight
        raw_scores.append(raw_score)
        block_details.append({"blocks": row_blocks, "missing": total_missing})

    # --- Step 3: Percentile-normalize across cohort ---
    n = len(raw_scores)
    if n == 1:
        pctiles = [0.5]
    else:
        # Rank-based percentile (average ranks for ties)
        indexed = sorted(range(n), key=lambda i: raw_scores[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n and raw_scores[indexed[j]] == raw_scores[indexed[i]]:
                j += 1
            avg_rank = (i + j - 1) / 2.0
            for k in range(i, j):
                ranks[indexed[k]] = avg_rank
            i = j
        pctiles = [r / max(n - 1, 1) for r in ranks]

    # --- Step 4: Assign rank buckets ---
    # Sort by pctile descending to assign rank positions
    rank_order = sorted(range(n), key=lambda i: pctiles[i], reverse=True)
    rank_positions = [0] * n
    for pos, idx in enumerate(rank_order, start=1):
        rank_positions[idx] = pos

    results: list[SelectorResult] = []
    for i in range(n):
        pos = rank_positions[i]
        if pos <= config.top_10_cutoff:
            bucket = "top10"
        elif pos <= config.top_30_cutoff:
            bucket = "top30"
        elif pos <= config.top_60_cutoff:
            bucket = "top60"
        elif pos <= config.top_120_cutoff:
            bucket = "top120"
        else:
            bucket = "below"

        bd = block_details[i]
        results.append(
            SelectorResult(
                selector_score=round(pctiles[i], 6),
                selector_rank_bucket=bucket,
                clinical_block=bd["blocks"]["clinical"],
                catalyst_block=bd["blocks"]["catalyst"],
                survivability_block=bd["blocks"]["survivability"],
                institutional_block=bd["blocks"]["institutional"],
                market_structure_block=bd["blocks"]["market_structure"],
                missing_count=bd["missing"],
            )
        )

    return results


# ---------------------------------------------------------------------------
# Column constants (for integration with run_screen.py / DECISION_COLUMNS)
# ---------------------------------------------------------------------------

SELECTOR_COLUMNS = [
    "selector_score",
    "selector_rank_bucket",
    "selector_clinical_block",
    "selector_catalyst_block",
    "selector_survivability_block",
    "selector_institutional_block",
    "selector_market_block",
]


# ---------------------------------------------------------------------------
# Regime modulation (Spec 050 Phase 5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegimeModulation:
    """Regime-dependent attenuation parameters.

    Applied to selector/ranker/construction outputs — does NOT change
    the regime detection itself (switching policy is FROZEN).
    """

    regime_label: str = "UNKNOWN"
    # Multiplier on ranker max_adjustment_pct (1.0 = no change)
    ranker_max_adj_mult: float = 1.0
    # Multiplier on construction per-name caps (1.0 = no change)
    cap_tightening_mult: float = 1.0


# Default mappings: regime label → modulation parameters
_REGIME_MODULATION_MAP = {
    "BULL": RegimeModulation(regime_label="BULL", ranker_max_adj_mult=1.0, cap_tightening_mult=1.0),
    "SECTOR_ROTATION": RegimeModulation(
        regime_label="SECTOR_ROTATION", ranker_max_adj_mult=0.80, cap_tightening_mult=0.90
    ),
    "BEAR": RegimeModulation(regime_label="BEAR", ranker_max_adj_mult=0.67, cap_tightening_mult=0.80),
    "VOLATILITY_SPIKE": RegimeModulation(
        regime_label="VOLATILITY_SPIKE", ranker_max_adj_mult=0.67, cap_tightening_mult=0.80
    ),
}


def get_regime_modulation(regime_label: str) -> RegimeModulation:
    """Look up regime modulation parameters for a given regime label.

    Returns neutral modulation (all 1.0) for unknown regimes.
    """
    return _REGIME_MODULATION_MAP.get(
        regime_label,
        RegimeModulation(regime_label=regime_label),
    )

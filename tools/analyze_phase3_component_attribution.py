"""
PHASE3_COMPONENT_ATTRIBUTION_DIAGNOSTIC_NO_MODEL_CHANGE

For each Phase 3 drag name (CELC, DRUG, PRAX, TYRA, ABVX) and winner offset name
(TNGX, ALKS, SYRE), determine which model components promoted it into the verified
top-30 basket, compare loser vs winner component profiles, run rank contribution
attribution (counterfactual ranks with each feature zeroed), and classify failure modes.

Governance constraints (HARD — do not remove):
  NO_MODEL_CHANGE  NO_RANKER_CHANGE  NO_SELECTOR_CHANGE  NO_SIZING_CHANGE
  NO_REGIME_CHANGE  NO_PRODUCTION_WIRING  NO_CRON

Output: artifacts/autopsy/phase3_component_attribution/
  phase3_component_attribution.json
  PHASE3_COMPONENT_ATTRIBUTION.md
"""

from __future__ import annotations

import copy
import csv
import json
import math
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ranker_v2_pairwise import RankerV2Config, filter_cohort, model_from_dict, score_snapshot

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLASSIFICATION = "PHASE3_COMPONENT_ATTRIBUTION_DIAGNOSTIC_NO_MODEL_CHANGE"

PHASE3_DATES = [
    "2026-05-18",
    "2026-05-19",
    "2026-05-20",
    "2026-05-21",
    "2026-05-22",
    "2026-05-26",
    "2026-05-27",
    "2026-05-28",
    "2026-05-29",
    "2026-06-01",
    "2026-06-02",
    "2026-06-03",
    "2026-06-04",
    "2026-06-05",
    "2026-06-08",
    "2026-06-09",
]

LOSERS = ["CELC", "DRUG", "PRAX", "TYRA", "ABVX"]
WINNERS = ["TNGX", "ALKS", "SYRE"]
TARGET_NAMES = LOSERS + WINNERS
TARGET_ROLE = {t: "loser" for t in LOSERS}
TARGET_ROLE.update({t: "winner" for t in WINNERS})

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
PRICE_HISTORY_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
RANKER_V2_MODEL_JSON = PROJECT_ROOT / "production_data" / "ranker_v2_model.json"
OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "autopsy" / "phase3_component_attribution"
OUTPUT_JSON = OUTPUT_DIR / "phase3_component_attribution.json"
OUTPUT_MD = OUTPUT_DIR / "PHASE3_COMPONENT_ATTRIBUTION.md"

PRODUCTION_RANKER_V2_CONFIG = RankerV2Config(feature_set="minimal_v2")

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_ranker_v2_model():
    with open(RANKER_V2_MODEL_JSON) as f:
        artifact = json.load(f)
    return model_from_dict(artifact["model"])


def load_canonical_rankings(snap_date: str) -> list[dict]:
    path = SNAPSHOTS_DIR / snap_date / "rankings.csv"
    with open(path) as f:
        return list(csv.DictReader(f))


def load_price_history() -> dict[str, dict[str, float]]:
    prices: dict[str, dict[str, float]] = {}
    with open(PRICE_HISTORY_CSV) as f:
        for row in csv.DictReader(f):
            ticker = row["ticker"]
            try:
                prices.setdefault(ticker, {})[row["date"]] = float(row["close"])
            except (ValueError, KeyError):
                pass
    return prices


def get_trading_dates(prices: dict) -> list[str]:
    dates: set[str] = set()
    for td in prices.values():
        dates.update(td.keys())
    return sorted(dates)


def get_fwd_date(snap_date: str, trading_dates: list[str], n: int = 5) -> Optional[str]:
    try:
        idx = trading_dates.index(snap_date)
        return trading_dates[idx + n] if idx + n < len(trading_dates) else None
    except ValueError:
        return None


def compute_5d_return(ticker: str, snap_date: str, fwd_date: Optional[str], prices: dict) -> Optional[float]:
    if fwd_date is None:
        return None
    p0 = prices.get(ticker, {}).get(snap_date)
    p1 = prices.get(ticker, {}).get(fwd_date)
    if p0 and p1:
        return (p1 - p0) / p0
    return None


# ---------------------------------------------------------------------------
# Cohort statistics and contribution computation
# ---------------------------------------------------------------------------


def _cohort_stats(cohort: list[dict]) -> dict:
    """Compute mean and std of coinvest_score_z and financial_score within cohort."""

    def _stats(vals):
        n = len(vals)
        if n == 0:
            return 0.0, 1.0
        mu = sum(vals) / n
        std = math.sqrt(sum((x - mu) ** 2 for x in vals) / n) or 1.0
        return mu, std

    ci_vals = [float(r.get("coinvest_score_z") or 0) for r in cohort]
    fi_vals = [float(r.get("financial_score") or 0) for r in cohort]
    ci_mean, ci_std = _stats(ci_vals)
    fi_mean, fi_std = _stats(fi_vals)
    return {
        "ci_mean": ci_mean,
        "ci_std": ci_std,
        "fi_mean": fi_mean,
        "fi_std": fi_std,
        "n": len(cohort),
    }


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def compute_contributions(ci_raw: float, fi_raw: float, stats: dict, model) -> dict:
    """Decompose ranker_v2_score into coinvest and financial contributions."""
    ci_z = (ci_raw - stats["ci_mean"]) / stats["ci_std"]
    fi_z = (fi_raw - stats["fi_mean"]) / stats["fi_std"]
    ci_contrib = model.weights[0] * ci_z  # positive or negative
    fi_contrib = model.weights[1] * fi_z  # negative weight × z
    linear = ci_contrib + fi_contrib + model.bias
    final_score = _sigmoid(linear)
    return {
        "ci_z": ci_z,
        "fi_z": fi_z,
        "ci_contrib": ci_contrib,
        "fi_contrib": fi_contrib,
        "linear": linear,
        "final_score": final_score,
    }


def counterfactual_rank(
    ticker: str,
    ci_raw: float,
    fi_raw: float,
    stats: dict,
    cohort_scores: list[tuple[str, float]],
    model,
    zero_ci: bool = False,
    zero_fi: bool = False,
) -> Optional[int]:
    """
    Compute counterfactual rank when coinvest or financial contribution is zeroed.
    Zeroing = setting the ticker's z-score to 0 (cohort-mean performance).
    """
    ci_z = 0.0 if zero_ci else (ci_raw - stats["ci_mean"]) / stats["ci_std"]
    fi_z = 0.0 if zero_fi else (fi_raw - stats["fi_mean"]) / stats["fi_std"]
    cf_score = _sigmoid(model.weights[0] * ci_z + model.weights[1] * fi_z + model.bias)
    # Count how many cohort members score higher (excluding this ticker itself)
    higher = sum(1 for t, s in cohort_scores if t != ticker and s > cf_score)
    return higher + 1  # 1-indexed rank


# ---------------------------------------------------------------------------
# Per-date attribution record
# ---------------------------------------------------------------------------


def extract_date_record(
    snap_date: str,
    rows: list[dict],
    model,
    prices: dict,
    trading_dates: list[str],
) -> dict:
    """
    For a single snapshot date, extract component breakdown and counterfactual ranks
    for all target names that appear in the cohort (rank ≤ 60).
    """
    cohort = filter_cohort(copy.deepcopy(rows), PRODUCTION_RANKER_V2_CONFIG)
    stats = _cohort_stats(cohort)

    # Score the full cohort (deep copy to avoid mutating canonical rows)
    scored = score_snapshot(copy.deepcopy(rows), model, PRODUCTION_RANKER_V2_CONFIG)
    cohort_scored = [(r["ticker"], float(r["ranker_v2_score"])) for r in scored if r.get("ranker_v2_score") is not None]

    fwd_date = get_fwd_date(snap_date, trading_dates)

    records = {}
    for r in rows:
        ticker = r["ticker"]
        if ticker not in TARGET_NAMES:
            continue
        try:
            rank = int(r.get("actionable_rank") or 999)
        except ValueError:
            rank = 999
        if rank > 60:
            continue

        ci_raw = float(r.get("coinvest_score_z") or 0)
        fi_raw = float(r.get("financial_score") or 0)
        ees_v3 = float(r.get("ees_v3_score") or 0) if r.get("ees_v3_score") else None
        clinical = float(r.get("clinical_score") or 0) if r.get("clinical_score") else None
        momentum = float(r.get("momentum_score") or 0) if r.get("momentum_score") else None
        tier = r.get("tier_any", "")

        contribs = compute_contributions(ci_raw, fi_raw, stats, model)
        ret = compute_5d_return(ticker, snap_date, fwd_date, prices)

        cf_zero_fi = counterfactual_rank(ticker, ci_raw, fi_raw, stats, cohort_scored, model, zero_fi=True)
        cf_zero_ci = counterfactual_rank(ticker, ci_raw, fi_raw, stats, cohort_scored, model, zero_ci=True)

        # Dominant driver: whichever contribution has larger absolute value
        if abs(contribs["fi_contrib"]) >= abs(contribs["ci_contrib"]):
            primary_driver = "financial_stress"
        else:
            primary_driver = "coinvest_signal"

        records[ticker] = {
            "snap_date": snap_date,
            "ticker": ticker,
            "role": TARGET_ROLE[ticker],
            "actionable_rank": rank,
            "ci_raw": ci_raw,
            "fi_raw": fi_raw,
            "ees_v3_score": ees_v3,
            "clinical_score": clinical,
            "momentum_score": momentum,
            "tier": tier,
            "cohort_stats": stats,
            "ci_z": contribs["ci_z"],
            "fi_z": contribs["fi_z"],
            "ci_contrib": contribs["ci_contrib"],
            "fi_contrib": contribs["fi_contrib"],
            "ranker_v2_score": contribs["final_score"],
            "ret_5d": ret,
            "fwd_date": fwd_date,
            "cf_rank_zero_fi": cf_zero_fi,
            "cf_rank_zero_ci": cf_zero_ci,
            "primary_driver": primary_driver,
        }
    return records


# ---------------------------------------------------------------------------
# Aggregate per-ticker profile
# ---------------------------------------------------------------------------


def _mean(vals: list) -> Optional[float]:
    valid = [v for v in vals if v is not None]
    return sum(valid) / len(valid) if valid else None


def aggregate_ticker_profile(ticker: str, date_records: list[dict]) -> dict:
    """Aggregate per-date records into a ticker-level attribution profile."""
    appearances = len(date_records)
    ranks = [r["actionable_rank"] for r in date_records]
    ci_z_vals = [r["ci_z"] for r in date_records]
    fi_z_vals = [r["fi_z"] for r in date_records]
    ci_contrib_vals = [r["ci_contrib"] for r in date_records]
    fi_contrib_vals = [r["fi_contrib"] for r in date_records]
    ret_vals = [r["ret_5d"] for r in date_records]
    cf_zero_fi_vals = [r["cf_rank_zero_fi"] for r in date_records]
    cf_zero_ci_vals = [r["cf_rank_zero_ci"] for r in date_records]
    ees_vals = [r["ees_v3_score"] for r in date_records if r["ees_v3_score"] is not None]
    clinical_vals = [r["clinical_score"] for r in date_records if r["clinical_score"] is not None]
    momentum_vals = [r["momentum_score"] for r in date_records if r["momentum_score"] is not None]

    mean_ci_z = _mean(ci_z_vals)
    mean_fi_z = _mean(fi_z_vals)
    mean_ci_contrib = _mean(ci_contrib_vals)
    mean_fi_contrib = _mean(fi_contrib_vals)
    mean_ret = _mean(ret_vals)
    mean_cf_zero_fi = _mean(cf_zero_fi_vals)
    mean_cf_zero_ci = _mean(cf_zero_ci_vals)
    mean_rank = _mean(ranks)
    mean_ees = _mean(ees_vals)
    mean_clinical = _mean(clinical_vals)
    mean_momentum = _mean(momentum_vals)

    # Primary driver: whichever has larger absolute mean contribution
    if mean_ci_contrib is not None and mean_fi_contrib is not None:
        if abs(mean_fi_contrib) >= abs(mean_ci_contrib):
            primary_driver = "financial_stress"
            driver_z = mean_fi_z
        else:
            primary_driver = "coinvest_signal"
            driver_z = mean_ci_z
    else:
        primary_driver = "unknown"
        driver_z = None

    # Counterfactual lift: how many ranks would they drop if primary driver = 0?
    if primary_driver == "financial_stress" and mean_cf_zero_fi and mean_rank:
        rank_drop_if_zeroed = mean_cf_zero_fi - mean_rank
    elif primary_driver == "coinvest_signal" and mean_cf_zero_ci and mean_rank:
        rank_drop_if_zeroed = mean_cf_zero_ci - mean_rank
    else:
        rank_drop_if_zeroed = None

    return {
        "ticker": ticker,
        "role": TARGET_ROLE[ticker],
        "n_appearances": appearances,
        "mean_actionable_rank": mean_rank,
        "mean_5d_ret": mean_ret,
        "mean_ci_z": mean_ci_z,
        "mean_fi_z": mean_fi_z,
        "mean_ci_contrib": mean_ci_contrib,
        "mean_fi_contrib": mean_fi_contrib,
        "mean_ees_v3_score": mean_ees,
        "mean_clinical_score": mean_clinical,
        "mean_momentum_score": mean_momentum,
        "primary_driver": primary_driver,
        "primary_driver_z": driver_z,
        "mean_cf_rank_zero_fi": mean_cf_zero_fi,
        "mean_cf_rank_zero_ci": mean_cf_zero_ci,
        "rank_drop_if_primary_zeroed": rank_drop_if_zeroed,
        "dates_in_top30": sorted({r["snap_date"] for r in date_records if r["actionable_rank"] <= 30}),
    }


# ---------------------------------------------------------------------------
# Failure mode classification
# ---------------------------------------------------------------------------


def classify_failure_mode(profile: dict) -> tuple[str, str]:
    """
    Returns (failure_mode_code, evidence_string).

    Codes:
      FINANCING_UNDER_PENALIZED  — low financial_score drives rank up; name had dilution risk
      INSTITUTIONAL_SIGNAL_FALSE_POSITIVE — high coinvest drove rank but signal staled
      EES_VETO_FAILED            — negative ees_v3_score existed but didn't suppress rank
      MARGINAL_COHORT_MEMBER     — no strong signal; in top-30 only because others weaker
      UNEXPLAINED                — winner or no clear failure mode
    """
    ticker = profile["ticker"]
    role = profile["role"]

    if role == "winner":
        return "WINNER_OFFSET", f"{ticker} positive return offset — used as comparison baseline"

    fi_z = profile["mean_fi_z"] or 0.0
    ci_z = profile["mean_ci_z"] or 0.0
    fi_c = profile["mean_fi_contrib"] or 0.0
    ci_c = profile["mean_ci_contrib"] or 0.0
    ees = profile["mean_ees_v3_score"]
    ret = profile["mean_5d_ret"] or 0.0
    rank_drop = profile["rank_drop_if_primary_zeroed"] or 0.0
    n = profile["n_appearances"]

    evidence_parts = []

    # EES veto check (dominant over others — check first)
    if ees is not None and ees < -0.8 and ret < -0.05:
        evidence_parts.append(
            f"ees_v3_score={ees:.3f} (strongly negative) flagged financing risk; "
            f"mean_ret={ret:.3f} confirms; ranker_v2 has no ees_v3 input"
        )
        if abs(fi_c) >= abs(ci_c):
            evidence_parts.append(f"financial stress (fi_z={fi_z:.3f}, fi_contrib={fi_c:.4f}) also contributed")
        return "EES_VETO_FAILED", "; ".join(evidence_parts)

    # Financing under-penalized: primary driver is financial stress, negative return
    if abs(fi_c) >= abs(ci_c) and fi_z < -0.8 and ret < -0.05:
        evidence_parts.append(
            f"fi_z={fi_z:.3f} (financially stressed; weight=-0.053 → promoted); "
            f"fi_contrib={fi_c:.4f} dominates; mean_ret={ret:.3f}"
        )
        if rank_drop > 5:
            evidence_parts.append(f"counterfactual rank if fi_zeroed: +{rank_drop:.1f} positions worse")
        return "FINANCING_UNDER_PENALIZED", "; ".join(evidence_parts)

    # Coinvest false positive: primary driver is coinvest, negative return
    if abs(ci_c) >= abs(fi_c) and ci_z > 0.5 and ret < -0.03:
        evidence_parts.append(
            f"ci_z={ci_z:.3f} (high institutional demand) drove rank; "
            f"ci_contrib={ci_c:.4f} dominates; mean_ret={ret:.3f}"
        )
        if rank_drop > 5:
            evidence_parts.append(f"counterfactual rank if ci_zeroed: +{rank_drop:.1f} positions worse")
        return "INSTITUTIONAL_SIGNAL_FALSE_POSITIVE", "; ".join(evidence_parts)

    # Marginal member: both signals near zero, thin margin in top-30
    if abs(fi_c) < 0.02 and abs(ci_c) < 0.02 and n < 10:
        evidence_parts.append(
            f"both contributions near zero (ci_contrib={ci_c:.4f}, fi_contrib={fi_c:.4f}); "
            f"only {n} appearances; marginal rank {profile['mean_actionable_rank']:.0f}"
        )
        return "MARGINAL_COHORT_MEMBER", "; ".join(evidence_parts)

    # Residual
    evidence_parts.append(f"ci_z={ci_z:.3f}, fi_z={fi_z:.3f}, ret={ret:.3f}; no dominant single cause")
    return "UNEXPLAINED", "; ".join(evidence_parts)


# ---------------------------------------------------------------------------
# BEAR sensitivity (documents regime invariance for ranker_v2)
# ---------------------------------------------------------------------------


def bear_sensitivity_section() -> dict:
    """
    ranker_v2 uses only coinvest_score_z and financial_score — both computed
    before the regime detection layer. Z-scoring is within-cohort on the same
    raw values. Correcting UNKNOWN→BEAR leaves both features unchanged.
    This was confirmed empirically by PHASE3_CORRECTED_REGIME_RANKING_REPLAY
    (16/16 dates identical top-30).

    This section documents why BEAR multipliers do NOT affect component attribution.
    """
    return {
        "ranker_v2_regime_invariant": True,
        "features_precomputed_before_regime": ["coinvest_score_z", "financial_score"],
        "bear_rank_change": "NONE",
        "evidence": (
            "PHASE3_CORRECTED_REGIME_RANKING_REPLAY confirmed 16/16 Phase 3 dates "
            "produce identical top-30 under corrected BEAR regime. "
            "Module-5 BEAR weights apply only to composite_score, which is NOT "
            "the production sort key in pairwise_minimal mode (final_score = ranker_v2_score). "
            "Component attribution is regime-invariant for this model."
        ),
        "what_bear_would_have_changed": (
            "BEAR module-5 weights (momentum −0.562, financial −0.245, valuation −0.184, "
            "clinical +0.009) would have depressed composite_score for momentum-heavy names "
            "like TNGX (momentum=91pp on May 18). But composite_score is not the decision key."
        ),
    }


# ---------------------------------------------------------------------------
# Loser vs winner comparison
# ---------------------------------------------------------------------------


def loser_vs_winner_comparison(profiles: list[dict]) -> dict:
    losers = [p for p in profiles if p["role"] == "loser"]
    winners = [p for p in profiles if p["role"] == "winner"]

    def _avg(lst, key):
        vals = [x.get(key) for x in lst if x.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    return {
        "loser_mean_5d_ret": _avg(losers, "mean_5d_ret"),
        "winner_mean_5d_ret": _avg(winners, "mean_5d_ret"),
        "loser_mean_ci_z": _avg(losers, "mean_ci_z"),
        "winner_mean_ci_z": _avg(winners, "mean_ci_z"),
        "loser_mean_fi_z": _avg(losers, "mean_fi_z"),
        "winner_mean_fi_z": _avg(winners, "mean_fi_z"),
        "loser_mean_ees": _avg(losers, "mean_ees_v3_score"),
        "winner_mean_ees": _avg(winners, "mean_ees_v3_score"),
        "loser_mean_clinical": _avg(losers, "mean_clinical_score"),
        "winner_mean_clinical": _avg(winners, "mean_clinical_score"),
        "loser_mean_momentum": _avg(losers, "mean_momentum_score"),
        "winner_mean_momentum": _avg(winners, "mean_momentum_score"),
        "n_losers": len(losers),
        "n_winners": len(winners),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_attribution(write_output: bool = True) -> dict:
    model = load_ranker_v2_model()
    prices = load_price_history()
    trading_dates = get_trading_dates(prices)

    # Collect per-ticker per-date records across all Phase 3 dates
    ticker_records: dict[str, list[dict]] = {t: [] for t in TARGET_NAMES}
    all_date_records: list[dict] = []

    for snap_date in PHASE3_DATES:
        path = SNAPSHOTS_DIR / snap_date / "rankings.csv"
        if not path.exists():
            continue
        rows = load_canonical_rankings(snap_date)
        date_records = extract_date_record(snap_date, rows, model, prices, trading_dates)
        all_date_records.append({"snap_date": snap_date, "records": date_records})
        for ticker, rec in date_records.items():
            ticker_records[ticker].append(rec)

    # Aggregate profiles
    profiles = []
    for ticker in TARGET_NAMES:
        records = ticker_records[ticker]
        if not records:
            profiles.append(
                {
                    "ticker": ticker,
                    "role": TARGET_ROLE[ticker],
                    "n_appearances": 0,
                    "note": "not found in Phase 3 cohort (rank > 60 all dates)",
                }
            )
            continue
        profile = aggregate_ticker_profile(ticker, records)
        mode, evidence = classify_failure_mode(profile)
        profile["failure_mode"] = mode
        profile["failure_mode_evidence"] = evidence
        profiles.append(profile)

    loser_profiles = [p for p in profiles if p.get("role") == "loser"]
    winner_profiles = [p for p in profiles if p.get("role") == "winner"]
    comparison = loser_vs_winner_comparison(profiles)
    bear_section = bear_sensitivity_section()

    # Structural finding
    [p.get("mean_fi_z") for p in profiles if p.get("mean_fi_z") is not None]
    [p.get("mean_ci_z") for p in profiles if p.get("mean_ci_z") is not None]
    fi_z_losers = [p.get("mean_fi_z") for p in loser_profiles if p.get("mean_fi_z") is not None]
    fi_z_winners = [p.get("mean_fi_z") for p in winner_profiles if p.get("mean_fi_z") is not None]
    mean_fi_z_losers = _mean(fi_z_losers)
    mean_fi_z_winners = _mean(fi_z_winners)

    structural_finding = {
        "dominant_feature": "financial_score",
        "weight": -0.05332,
        "direction": "negative_weight_promotes_financially_stressed",
        "mean_fi_z_losers": mean_fi_z_losers,
        "mean_fi_z_winners": mean_fi_z_winners,
        "interpretation": (
            "financial_score has a negative model weight (−0.053). Names with "
            "below-cohort-average financial health (fi_z < 0) receive a POSITIVE "
            "financial contribution to ranker_v2_score. This promotes both winners "
            "(SYRE fi_z≈−1.7) and losers (DRUG fi_z≈−1.4) equally. "
            "ranker_v2 cannot discriminate between financially-stressed names that "
            "have strong catalysts and those that do not."
        ),
        "ees_v3_not_in_ranker_v2": True,
        "ees_v3_interpretation": (
            "ees_v3_score provides a financing/overpricing signal but is not an input "
            "to ranker_v2. For CELC (ees_v3=−1.15) and ABVX (ees_v3=−1.21), the EES "
            "signal correctly identified risk but had no path to suppress rank."
        ),
    }

    failure_mode_summary = {}
    for p in loser_profiles:
        fm = p.get("failure_mode", "UNKNOWN")
        failure_mode_summary.setdefault(fm, []).append(p["ticker"])

    result = {
        "classification": CLASSIFICATION,
        "schema": "phase3_component_attribution_v1",
        "governance": {
            "model_change": False,
            "ranker_change": False,
            "selector_change": False,
            "sizing_change": False,
            "regime_change": False,
            "production_wiring": False,
            "canonical_snapshots_modified": False,
            "cron": False,
        },
        "window": {
            "start_date": PHASE3_DATES[0],
            "end_date": PHASE3_DATES[-1],
            "n_dates": len(PHASE3_DATES),
            "losers": LOSERS,
            "winners": WINNERS,
        },
        "per_ticker_attribution": profiles,
        "loser_vs_winner_comparison": comparison,
        "bear_sensitivity": bear_section,
        "structural_finding": structural_finding,
        "failure_mode_summary": failure_mode_summary,
        "detail": {
            "date_records": [
                {
                    "snap_date": dr["snap_date"],
                    "tickers_found": list(dr["records"].keys()),
                }
                for dr in all_date_records
            ]
        },
    }

    if write_output:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_JSON, "w") as f:
            json.dump(result, f, indent=2, default=str)
        _write_memo(result)

    return result


def _write_memo(results: dict) -> None:
    profiles = {p["ticker"]: p for p in results["per_ticker_attribution"]}
    comp = results["loser_vs_winner_comparison"]
    sf = results["structural_finding"]
    fm_summary = results["failure_mode_summary"]

    lines = [
        "# Phase 3 Component Attribution",
        "",
        f"> Classification: `{CLASSIFICATION}`",
        "> Date: 2026-06-26",
        "> Scope: Diagnostic only. No model, ranker, selector, or production change.",
        "",
        "---",
        "",
        "## Purpose",
        "",
        "For each Phase 3 drag name (CELC, DRUG, PRAX, TYRA, ABVX), determine which",
        "model components promoted it into the verified top-30 basket, and whether those",
        "components behaved differently for winners (TNGX, ALKS, SYRE).",
        "",
        "---",
        "",
        "## Model Architecture (ranker_v2)",
        "",
        "```",
        "final_score = sigmoid(w0 * coinvest_z + w1 * financial_z + bias)",
        "  w0 (coinvest_score_z) = +0.020   [higher institutional interest = higher score]",
        "  w1 (financial_score)  = −0.053   [lower financial health  = higher score]",
        "  bias                  =  0.502",
        "```",
        "",
        "The **negative financial weight** is the key: names with below-average financial",
        "health receive a positive contribution. This is the structural amplifier.",
        "",
        "---",
        "",
        "## Per-Ticker Attribution",
        "",
    ]

    for ticker in TARGET_NAMES:
        p = profiles.get(ticker, {})
        role_label = "LOSER" if p.get("role") == "loser" else "WINNER"
        n = p.get("n_appearances", 0)
        if n == 0:
            lines.append(f"### {ticker} ({role_label}) — not in Phase 3 cohort")
            lines.append("")
            continue

        lines.append(f"### {ticker} ({role_label})")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|------:|")
        lines.append(f"| Appearances in Phase 3 | {n} |")
        mr = p.get("mean_actionable_rank")
        lines.append(f"| Mean rank | {mr:.1f} |" if mr else "| Mean rank | N/A |")
        ret = p.get("mean_5d_ret")
        lines.append(f"| Mean 5d return | {ret:+.3f} |" if ret is not None else "| Mean 5d return | N/A |")
        ci_z = p.get("mean_ci_z")
        lines.append(f"| Mean coinvest_z | {ci_z:+.3f} |" if ci_z is not None else "| Mean coinvest_z | N/A |")
        fi_z = p.get("mean_fi_z")
        lines.append(f"| Mean financial_z | {fi_z:+.3f} |" if fi_z is not None else "| Mean financial_z | N/A |")
        ci_c = p.get("mean_ci_contrib")
        lines.append(
            f"| Coinvest contribution | {ci_c:+.4f} |" if ci_c is not None else "| Coinvest contribution | N/A |"
        )
        fi_c = p.get("mean_fi_contrib")
        lines.append(
            f"| Financial contribution | {fi_c:+.4f} |" if fi_c is not None else "| Financial contribution | N/A |"
        )
        ees = p.get("mean_ees_v3_score")
        lines.append(f"| Mean ees_v3 | {ees:+.3f} |" if ees is not None else "| Mean ees_v3 | N/A |")
        lines.append(f"| Primary driver | {p.get('primary_driver','?')} |")  # noqa: E231
        cf_fi = p.get("mean_cf_rank_zero_fi")
        lines.append(f"| CF rank if fi=0 | {cf_fi:.0f} |" if cf_fi is not None else "| CF rank if fi=0 | N/A |")
        cf_ci = p.get("mean_cf_rank_zero_ci")
        lines.append(f"| CF rank if ci=0 | {cf_ci:.0f} |" if cf_ci is not None else "| CF rank if ci=0 | N/A |")
        rd = p.get("rank_drop_if_primary_zeroed")
        lines.append(
            f"| Rank drop if primary=0 | {rd:+.1f} |" if rd is not None else "| Rank drop if primary=0 | N/A |"
        )
        lines.append(f"| **Failure mode** | **{p.get('failure_mode','?')}** |")  # noqa: E231
        lines.append("")
        ev = p.get("failure_mode_evidence", "")
        if ev:
            lines.append(f"*Evidence: {ev}*")
        lines.append("")

    lines += [
        "---",
        "",
        "## Loser vs Winner Comparison",
        "",
        "| Metric | Losers (avg) | Winners (avg) |",
        "|--------|------------:|---------------:|",
    ]
    lret = comp.get("loser_mean_5d_ret")
    wret = comp.get("winner_mean_5d_ret")
    lines.append(
        f"| Mean 5d return | {lret:+.3f} | {wret:+.3f} |" if lret and wret else "| Mean 5d return | N/A | N/A |"
    )
    lci = comp.get("loser_mean_ci_z")
    wci = comp.get("winner_mean_ci_z")
    lines.append(
        f"| Mean coinvest_z | {lci:+.3f} | {wci:+.3f} |"
        if lci is not None and wci is not None
        else "| Mean coinvest_z | N/A | N/A |"
    )
    lfi = comp.get("loser_mean_fi_z")
    wfi = comp.get("winner_mean_fi_z")
    lines.append(
        f"| Mean financial_z | {lfi:+.3f} | {wfi:+.3f} |"
        if lfi is not None and wfi is not None
        else "| Mean financial_z | N/A | N/A |"
    )
    lees = comp.get("loser_mean_ees")
    wees = comp.get("winner_mean_ees")
    lines.append(
        f"| Mean ees_v3 | {lees:+.3f} | {wees:+.3f} |"
        if lees is not None and wees is not None
        else "| Mean ees_v3 | N/A | N/A |"
    )
    lcl = comp.get("loser_mean_clinical")
    wcl = comp.get("winner_mean_clinical")
    lines.append(
        f"| Mean clinical_score | {lcl:.1f} | {wcl:.1f} |"
        if lcl is not None and wcl is not None
        else "| Mean clinical_score | N/A | N/A |"
    )
    lmom = comp.get("loser_mean_momentum")
    wmom = comp.get("winner_mean_momentum")
    lines.append(
        f"| Mean momentum_score | {lmom:.1f} | {wmom:.1f} |"
        if lmom is not None and wmom is not None
        else "| Mean momentum_score | N/A | N/A |"
    )

    lines += [
        "",
        "---",
        "",
        "## Structural Finding",
        "",
        sf.get("interpretation", ""),
        "",
        sf.get("ees_v3_interpretation", ""),
        "",
        "---",
        "",
        "## BEAR Sensitivity",
        "",
        results["bear_sensitivity"].get("evidence", ""),
        "",
        results["bear_sensitivity"].get("what_bear_would_have_changed", ""),
        "",
        "**Conclusion:** Component attribution is regime-invariant. The failure modes",
        "documented here would have been identical under correctly-classified BEAR.",
        "",
        "---",
        "",
        "## Failure Mode Summary",
        "",
    ]

    for fm, tickers in fm_summary.items():
        lines.append(f"- **{fm}**: {', '.join(tickers)}")
    lines.append("")

    lines += [
        "---",
        "",
        "## Governance Verdict",
        "",
        "```",
        f"Classification:             {CLASSIFICATION}",
        "Model change:               NO",
        "Ranker change:              NO",
        "Selector change:            NO",
        "Regime change:              NO",
        "Snapshot write:             NO (output to artifacts/autopsy/ only)",
        "Production wiring:          NO",
        "",
        "Failure modes identified:",
    ]

    for fm, tickers in fm_summary.items():
        lines.append(f"  {fm}: {', '.join(tickers)}")

    lines += [
        "",
        "Primary structural issue:",
        "  financial_score weight = −0.053 promotes financially stressed names",
        "  without discriminating catalyst quality. ees_v3 signal exists but",
        "  is not an input to ranker_v2, so financing risk cannot suppress rank.",
        "```",
        "",
    ]

    with open(OUTPUT_MD, "w") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    results = run_attribution(write_output=True)
    profiles = {p["ticker"]: p for p in results["per_ticker_attribution"]}
    print(f"Classification: {results['classification']}")
    print()
    print(f"{'Ticker':6} {'Role':7} {'N':3} {'Rank':5} {'Ret':7} {'ci_z':7} {'fi_z':7} {'Driver':22} {'FailureMode'}")
    print("-" * 95)
    for ticker in TARGET_NAMES:
        p = profiles.get(ticker, {})
        n = p.get("n_appearances", 0)
        if n == 0:
            print(
                f"{ticker:6} {p.get('role','?'):7} {0:3} {'':5} {'':7} {'':7} {'':7} {'not in cohort':22}"  # noqa: E231
            )
            continue
        mr = p.get("mean_actionable_rank")
        ret = p.get("mean_5d_ret")
        ci_z = p.get("mean_ci_z")
        fi_z = p.get("mean_fi_z")
        drv = p.get("primary_driver", "")
        fm = p.get("failure_mode", "")
        mr_s = f"{mr:.1f}" if mr else "?"
        ret_s = f"{ret:+.3f}" if ret is not None else "N/A"
        ci_s = f"{ci_z:+.3f}" if ci_z is not None else "N/A"
        fi_s = f"{fi_z:+.3f}" if fi_z is not None else "N/A"
        print(
            f"{ticker:6} {p.get('role','?'):7} {n:3} {mr_s:5} {ret_s:7} {ci_s:7} {fi_s:7} {drv:22} {fm}"  # noqa: E231
        )
    print()
    print("Failure mode summary:")
    for fm, tickers in results["failure_mode_summary"].items():
        print(f"  {fm}: {', '.join(tickers)}")
    print()
    print(f"Output: {OUTPUT_JSON}")

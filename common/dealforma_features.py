"""DealForma deal comp features — Spec 046.

Phase 1: comp matching for dashboard context.
Phase 2: shadow features for IC testing.

All features use announcement_date for PIT safety.
"""

from __future__ import annotations

import json
import math
import statistics
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPS_PATH = REPO_ROOT / "production_data" / "dealforma_comps.json"
BIG_PHARMA_PATH = REPO_ROOT / "production_data" / "big_pharma_acquirers.json"

# Fallback top-20 pharma acquirers by biopharma revenue
_DEFAULT_BIG_PHARMA = {
    "Pfizer",
    "Merck",
    "Johnson & Johnson",
    "J&J",
    "Roche",
    "Novartis",
    "AbbVie",
    "AstraZeneca",
    "Eli Lilly",
    "Lilly",
    "Bristol-Myers Squibb",
    "BMS",
    "Bristol Myers Squibb",
    "Sanofi",
    "GSK",
    "GlaxoSmithKline",
    "Amgen",
    "Gilead",
    "Gilead Sciences",
    "Regeneron",
    "Vertex",
    "Biogen",
    "Takeda",
    "Bayer",
    "Novo Nordisk",
    "Daiichi Sankyo",
}


def _load_comps(path: Path | None = None) -> dict:
    p = path or COMPS_PATH
    if not p.exists():
        return {"deals": [], "as_of_date": None}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _load_big_pharma() -> set[str]:
    if BIG_PHARMA_PATH.exists():
        with open(BIG_PHARMA_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return set(data) if isinstance(data, list) else set(data.get("names", []))
    return _DEFAULT_BIG_PHARMA


def _days_between(d1: str, d2: str) -> int:
    """Days between two YYYY-MM-DD date strings."""
    dt1 = datetime.strptime(d1, "%Y-%m-%d")
    dt2 = datetime.strptime(d2, "%Y-%m-%d")
    return (dt2 - dt1).days


def _recency_weight(announcement_date: str, as_of_date: str, half_life_days: int = 180) -> float:
    """Exponential decay weight with given half-life."""
    days_ago = _days_between(announcement_date, as_of_date)
    if days_ago < 0:
        return 0.0
    return math.exp(-0.693 * days_ago / half_life_days)


def _match_bucket(
    deal: dict, therapeutic_area: str | None, stage: str | None, modality: str | None = None, strict: bool = True
) -> bool:
    """Check if a deal matches the given TA + stage bucket."""
    if not therapeutic_area:
        return False
    deal_ta = (deal.get("therapeutic_area") or "").lower()
    target_ta = therapeutic_area.lower()
    if deal_ta != target_ta:
        return False
    if strict and stage:
        deal_stage = (deal.get("stage") or "").lower()
        target_stage = stage.lower()
        if deal_stage != target_stage:
            return False
    if modality:
        deal_mod = (deal.get("modality") or "").lower()
        target_mod = modality.lower()
        if deal_mod != target_mod:
            return False
    return True


# ---------------------------------------------------------------------------
# Phase 1: Dashboard comp context
# ---------------------------------------------------------------------------


def get_deal_comps(
    ticker: str,
    therapeutic_area: str | None,
    stage: str | None,
    modality: str | None = None,
    as_of_date: str | None = None,
    lookback_months: int = 24,
    comps_data: dict | None = None,
) -> dict:
    """Get deal comp context for a single ticker — dashboard card data.

    Returns dict with:
      - recent_deals: list of matching deals
      - median_upfront_mm: median upfront value
      - median_total_mm: median total value
      - top_acquirers: most active acquirers
      - licensing_mna_split: ratio
      - cvr_prevalence: fraction with CVR/earnout
      - n_comps: number of comps found
      - bucket: the match criteria used
    """
    data = comps_data or _load_comps()
    deals = data.get("deals", [])
    aod = as_of_date or data.get("as_of_date") or date.today().isoformat()
    cutoff = _cutoff_date(aod, lookback_months)

    # PIT filter + time window
    windowed = [
        d
        for d in deals
        if d.get("announcement_date") and d["announcement_date"] >= cutoff and d["announcement_date"] <= aod
    ]

    # Try strict bucket first (TA + stage), fallback to TA-only
    matched = [d for d in windowed if _match_bucket(d, therapeutic_area, stage, modality, strict=True)]
    bucket_desc = f"{therapeutic_area} + {stage}"
    if modality:
        bucket_desc += f" + {modality}"

    if len(matched) < 5 and modality:
        matched = [d for d in windowed if _match_bucket(d, therapeutic_area, stage, None, strict=True)]
        bucket_desc = f"{therapeutic_area} + {stage}"

    if len(matched) < 5:
        matched = [d for d in windowed if _match_bucket(d, therapeutic_area, None, None, strict=False)]
        bucket_desc = f"{therapeutic_area} (all stages)"

    # Exclude self (if ticker matches target_ticker)
    matched = [d for d in matched if (d.get("target_ticker") or "").upper() != ticker.upper()]

    # Sort by date, most recent first
    matched.sort(key=lambda d: d["announcement_date"], reverse=True)

    # Median values
    upfronts = [d["upfront_value_mm"] for d in matched if d.get("upfront_value_mm") is not None]
    totals = [d["total_value_mm"] for d in matched if d.get("total_value_mm") is not None]

    # Top acquirers
    acquirer_counts: dict[str, int] = {}
    for d in matched:
        acq = d.get("acquirer")
        if acq:
            acquirer_counts[acq] = acquirer_counts.get(acq, 0) + 1
    top_acquirers = sorted(acquirer_counts.items(), key=lambda x: -x[1])[:5]

    # Licensing vs M&A split
    n_mna = sum(1 for d in matched if d.get("deal_type") == "M&A")
    n_lic = sum(1 for d in matched if d.get("deal_type") == "licensing")
    n_other = len(matched) - n_mna - n_lic

    # CVR/earnout prevalence
    n_cvr = sum(1 for d in matched if d.get("has_cvr") or d.get("has_earnout"))

    return {
        "ticker": ticker.upper(),
        "bucket": bucket_desc,
        "n_comps": len(matched),
        "lookback_months": lookback_months,
        "as_of_date": aod,
        "recent_deals": [
            {
                "deal_type": d.get("deal_type"),
                "announcement_date": d.get("announcement_date"),
                "acquirer": d.get("acquirer"),
                "target": d.get("target"),
                "stage": d.get("stage"),
                "upfront_value_mm": d.get("upfront_value_mm"),
                "total_value_mm": d.get("total_value_mm"),
                "has_cvr": d.get("has_cvr", False),
                "indication": d.get("indication"),
            }
            for d in matched[:15]
        ],
        "median_upfront_mm": round(statistics.median(upfronts), 1) if upfronts else None,
        "median_total_mm": round(statistics.median(totals), 1) if totals else None,
        "top_acquirers": [{"name": name, "count": cnt} for name, cnt in top_acquirers],
        "deal_type_split": {"M&A": n_mna, "licensing": n_lic, "other": n_other},
        "cvr_prevalence": round(n_cvr / len(matched), 3) if matched else None,
    }


# ---------------------------------------------------------------------------
# Phase 2: Shadow features
# ---------------------------------------------------------------------------


def compute_shadow_features(
    ticker: str,
    therapeutic_area: str | None,
    stage: str | None,
    modality: str | None = None,
    biological_target: str | None = None,
    as_of_date: str | None = None,
    comps_data: dict | None = None,
) -> dict:
    """Compute Phase 2 shadow features for a single ticker.

    Returns dict with shadow feature values.
    All features are raw (not z-scored) — z-score at universe level.
    """
    data = comps_data or _load_comps()
    deals = data.get("deals", [])
    aod = as_of_date or data.get("as_of_date") or date.today().isoformat()
    big_pharma = _load_big_pharma()

    cutoff_24m = _cutoff_date(aod, 24)
    cutoff_12m = _cutoff_date(aod, 12)

    # PIT filter
    all_pit = [d for d in deals if d.get("announcement_date") and d["announcement_date"] <= aod]

    # --- deal_activity_score_24m ---
    # Recency-weighted count of deals in same TA+stage bucket (24mo)
    bucket_deals_24m = [
        d
        for d in all_pit
        if d["announcement_date"] >= cutoff_24m
        and _match_bucket(d, therapeutic_area, stage, None, strict=True)
        and (d.get("target_ticker") or "").upper() != ticker.upper()
    ]
    deal_activity_score = sum(
        _recency_weight(d["announcement_date"], aod, half_life_days=180) for d in bucket_deals_24m
    )

    # --- mna_count_same_ta_stage_24m ---
    mna_count = sum(1 for d in bucket_deals_24m if d.get("deal_type") == "M&A")

    # --- licensing_heat_same_target_12m ---
    licensing_heat = 0
    if biological_target:
        bio_target_lower = biological_target.lower()
        licensing_heat = sum(
            1
            for d in all_pit
            if d["announcement_date"] >= cutoff_12m
            and d.get("deal_type") == "licensing"
            and (d.get("biological_target") or "").lower() == bio_target_lower
            and (d.get("target_ticker") or "").upper() != ticker.upper()
        )

    # --- big_pharma_interest_flag ---
    big_pharma_interest = 0
    bucket_deals_12m = [
        d
        for d in all_pit
        if d["announcement_date"] >= cutoff_12m and _match_bucket(d, therapeutic_area, None, modality, strict=False)
    ]
    for d in bucket_deals_12m:
        acq = d.get("acquirer") or ""
        if any(bp.lower() in acq.lower() for bp in big_pharma):
            big_pharma_interest = 1
            break

    # --- commercial_comp_revenue_multiple ---
    rev_multiples = [
        d["revenue_multiple"]
        for d in all_pit
        if d["announcement_date"] >= cutoff_24m
        and d.get("revenue_multiple") is not None
        and _match_bucket(d, therapeutic_area, None, None, strict=False)
        and d.get("stage") in ("approved", "commercial")
    ]
    commercial_comp_multiple = round(statistics.median(rev_multiples), 2) if rev_multiples else None

    # --- n_comps_in_bucket (confidence indicator) ---
    n_comps = len(bucket_deals_24m)

    return {
        "ticker": ticker.upper(),
        "as_of_date": aod,
        "deal_activity_score_24m": round(deal_activity_score, 3),
        "mna_count_same_ta_stage_24m": mna_count,
        "licensing_heat_same_target_12m": licensing_heat,
        "big_pharma_interest_flag": big_pharma_interest,
        "commercial_comp_revenue_multiple": commercial_comp_multiple,
        "n_comps_in_bucket": n_comps,
    }


def compute_universe_shadow_features(
    universe_rows: list[dict],
    comps_data: dict | None = None,
    as_of_date: str | None = None,
) -> list[dict]:
    """Compute shadow features for entire universe + z-score.

    universe_rows: list of dicts with at least 'ticker', 'therapeutic_area',
                   'lead_program_phase' (or 'stage'), optionally 'modality',
                   'biological_target'.

    Returns list of dicts with raw features + dealability_prior_score (z-scored).
    """
    data = comps_data or _load_comps()
    results = []

    for row in universe_rows:
        ticker = row.get("ticker", "")
        ta = row.get("therapeutic_area") or row.get("ta")
        stage = row.get("lead_program_phase") or row.get("stage")
        modality = row.get("modality")
        bio_target = row.get("biological_target")

        features = compute_shadow_features(
            ticker=ticker,
            therapeutic_area=ta,
            stage=stage,
            modality=modality,
            biological_target=bio_target,
            as_of_date=as_of_date,
            comps_data=data,
        )
        results.append(features)

    # Z-score dealability_prior_score
    _add_dealability_zscore(results)
    return results


def _add_dealability_zscore(results: list[dict]) -> None:
    """Compute dealability_prior_score as z-scored composite, clipped to [-3, 3]."""
    if not results:
        return

    # Composite = deal_activity_score_24m + mna_count + licensing_heat + big_pharma_interest
    for r in results:
        r["_raw_composite"] = (
            r["deal_activity_score_24m"]
            + r["mna_count_same_ta_stage_24m"]
            + r["licensing_heat_same_target_12m"]
            + r["big_pharma_interest_flag"] * 2  # extra weight for big pharma
        )

    composites = [r["_raw_composite"] for r in results]
    if len(composites) < 2:
        for r in results:
            r["dealability_prior_score"] = 0.0
            del r["_raw_composite"]
        return

    mu = statistics.mean(composites)
    sd = statistics.stdev(composites)

    for r in results:
        if sd > 0:
            z = (r["_raw_composite"] - mu) / sd
            r["dealability_prior_score"] = round(max(-3.0, min(3.0, z)), 4)
        else:
            r["dealability_prior_score"] = 0.0
        del r["_raw_composite"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cutoff_date(as_of_date: str, months: int) -> str:
    """Approximate cutoff date N months before as_of_date."""
    dt = datetime.strptime(as_of_date, "%Y-%m-%d")
    year = dt.year
    month = dt.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(dt.day, 28)  # safe for all months
    return f"{year:04d}-{month:02d}-{day:02d}"

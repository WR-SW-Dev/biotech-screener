"""Purple Book biologics competition features — Spec 047.

Phase 1: dashboard context for biologic competition.
Phase 2: shadow features for IC testing.

All features use licensing_date for PIT safety.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PURPLE_BOOK_PATH = REPO_ROOT / "production_data" / "purple_book.json"


def _load_purple_book(path: Path | None = None) -> dict:
    p = path or PURPLE_BOOK_PATH
    if not p.exists():
        return {"products": [], "reference_product_map": {}, "as_of_date": None}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Phase 1: Dashboard context
# ---------------------------------------------------------------------------


def get_biologic_competition(
    ticker: str,
    as_of_date: str | None = None,
    pb_data: dict | None = None,
) -> dict:
    """Get biologic competition context for a single ticker — dashboard card.

    Returns dict with:
      - products: list of this company's licensed biologics
      - biosimilar_exposure: list of reference products facing biosimilar competition
      - total_biosimilar_count: total biosimilars against company's products
      - total_interchangeable_count: total interchangeables
      - exclusivity_status: list of products with exclusivity info
      - is_biologic_company: whether company has any licensed biologics
    """
    data = pb_data or _load_purple_book()
    products = data.get("products", [])
    ref_map = data.get("reference_product_map", {})
    aod = as_of_date or data.get("as_of_date")

    ticker_upper = ticker.upper()

    # Find all products for this ticker
    company_products = [p for p in products if (p.get("resolved_ticker") or "").upper() == ticker_upper]

    if not company_products:
        return {
            "ticker": ticker_upper,
            "is_biologic_company": False,
            "n_products": 0,
            "products": [],
            "biosimilar_exposure": [],
            "total_biosimilar_count": 0,
            "total_interchangeable_count": 0,
            "exclusivity_status": [],
        }

    # Separate reference products from biosimilars
    own_reference = [p for p in company_products if not p["is_biosimilar"] and not p["is_interchangeable"]]
    own_biosimilars = [p for p in company_products if p["is_biosimilar"] or p["is_interchangeable"]]

    # For each of our reference products, find biosimilar competition
    biosimilar_exposure = []
    total_biosimilar = 0
    total_interchangeable = 0

    for ref in own_reference:
        bla = ref["bla_number"]
        ref_entry = ref_map.get(bla, {})
        biosims = ref_entry.get("biosimilars", [])
        interchangeables = ref_entry.get("interchangeables", [])

        # PIT filter
        if aod:
            biosims = [b for b in biosims if not b.get("licensing_date") or b["licensing_date"] <= aod]
            interchangeables = [
                b for b in interchangeables if not b.get("licensing_date") or b["licensing_date"] <= aod
            ]

        n_bio = len(biosims)
        n_inter = len(interchangeables)
        total_biosimilar += n_bio
        total_interchangeable += n_inter

        if n_bio > 0 or n_inter > 0:
            biosimilar_exposure.append(
                {
                    "product_name": ref.get("product_name_proprietary"),
                    "bla_number": bla,
                    "biosimilar_count": n_bio,
                    "interchangeable_count": n_inter,
                    "biosimilar_names": [b.get("product_name") for b in biosims],
                    "interchangeable_names": [b.get("product_name") for b in interchangeables],
                }
            )

    # Exclusivity status
    exclusivity_status = []
    for ref in own_reference:
        exp_date = ref.get("exclusivity_expiry_date")
        if exp_date:
            expired = exp_date <= aod if aod else None
            exclusivity_status.append(
                {
                    "product_name": ref.get("product_name_proprietary"),
                    "exclusivity_expiry_date": exp_date,
                    "expired": expired,
                }
            )

    return {
        "ticker": ticker_upper,
        "is_biologic_company": True,
        "n_products": len(company_products),
        "n_reference_products": len(own_reference),
        "n_own_biosimilars": len(own_biosimilars),
        "products": [
            {
                "product_name": p.get("product_name_proprietary"),
                "nonproprietary_name": p.get("product_name_nonproprietary"),
                "bla_number": p.get("bla_number"),
                "licensing_date": p.get("licensing_date"),
                "is_biosimilar": p.get("is_biosimilar", False),
                "is_interchangeable": p.get("is_interchangeable", False),
                "category": p.get("product_category"),
            }
            for p in company_products[:20]
        ],
        "biosimilar_exposure": biosimilar_exposure,
        "total_biosimilar_count": total_biosimilar,
        "total_interchangeable_count": total_interchangeable,
        "exclusivity_status": exclusivity_status,
    }


# ---------------------------------------------------------------------------
# Phase 2: Shadow features
# ---------------------------------------------------------------------------


def compute_shadow_features(
    ticker: str,
    as_of_date: str | None = None,
    pb_data: dict | None = None,
) -> dict:
    """Compute Phase 2 shadow features for a single ticker."""
    comp = get_biologic_competition(ticker, as_of_date, pb_data)

    is_biologic = 1 if comp["is_biologic_company"] else 0
    is_reference = 1 if comp.get("n_reference_products", 0) > 0 else 0
    biosimilar_count = comp["total_biosimilar_count"]
    interchangeable_count = comp["total_interchangeable_count"]
    has_biosimilar = 1 if biosimilar_count > 0 else 0
    has_interchangeable = 1 if interchangeable_count > 0 else 0

    exclusivity_known = 0
    exclusivity_expired = 0
    for ex in comp.get("exclusivity_status", []):
        exclusivity_known = 1
        if ex.get("expired"):
            exclusivity_expired = 1
            break

    return {
        "ticker": ticker.upper(),
        "as_of_date": as_of_date,
        "is_fda_licensed_biologic": is_biologic,
        "is_reference_product": is_reference,
        "biosimilar_count": biosimilar_count,
        "interchangeable_count": interchangeable_count,
        "has_biosimilar_competition": has_biosimilar,
        "has_interchangeable_competition": has_interchangeable,
        "reference_product_exclusivity_known": exclusivity_known,
        "reference_product_exclusivity_expired": exclusivity_expired,
    }


def compute_universe_shadow_features(
    tickers: list[str],
    as_of_date: str | None = None,
    pb_data: dict | None = None,
) -> list[dict]:
    """Compute shadow features for entire universe + z-score composite."""
    data = pb_data or _load_purple_book()
    results = []

    for ticker in tickers:
        features = compute_shadow_features(ticker, as_of_date, data)
        results.append(features)

    _add_competition_pressure_zscore(results)
    return results


def _add_competition_pressure_zscore(results: list[dict]) -> None:
    """Compute biologic_competition_pressure_score as z-scored composite."""
    if not results:
        return

    for r in results:
        r["_raw_pressure"] = (
            r["biosimilar_count"] + r["interchangeable_count"] * 2 + r["reference_product_exclusivity_expired"] * 3
        )

    pressures = [r["_raw_pressure"] for r in results]
    if len(pressures) < 2:
        for r in results:
            r["biologic_competition_pressure_score"] = 0.0
            del r["_raw_pressure"]
        return

    mu = statistics.mean(pressures)
    sd = statistics.stdev(pressures)

    for r in results:
        if sd > 0:
            z = (r["_raw_pressure"] - mu) / sd
            r["biologic_competition_pressure_score"] = round(max(-3.0, min(3.0, z)), 4)
        else:
            r["biologic_competition_pressure_score"] = 0.0
        del r["_raw_pressure"]

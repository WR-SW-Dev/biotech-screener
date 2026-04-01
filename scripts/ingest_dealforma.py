"""Ingest DealForma CSV export → production_data/dealforma_comps.json.

Validates required fields, normalizes schema, stamps PIT date.
Designed for manual CSV export first; API path later if warranted.

Usage:
    python scripts/ingest_dealforma.py path/to/dealforma_export.csv
    python scripts/ingest_dealforma.py path/to/export.csv --as-of-date 2026-04-01
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROD_DATA = REPO_ROOT / "production_data"
OUTPUT_PATH = PROD_DATA / "dealforma_comps.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("ingest_dealforma")

REQUIRED_FIELDS = {"deal_type", "announcement_date"}
DEAL_TYPES = {"M&A", "licensing", "asset_purchase", "venture", "IPO", "follow_on", "spin_out", "academic"}
STAGES = {"preclinical", "phase_1", "phase_2", "phase_3", "approved", "commercial"}

# Column mapping: DealForma export column → internal field
# Adjust these when the actual export schema is known
COLUMN_MAP = {
    "deal_id": "deal_id",
    "Deal ID": "deal_id",
    "deal_type": "deal_type",
    "Deal Type": "deal_type",
    "Type": "deal_type",
    "announcement_date": "announcement_date",
    "Announcement Date": "announcement_date",
    "Date": "announcement_date",
    "close_date": "close_date",
    "Close Date": "close_date",
    "acquirer": "acquirer",
    "Acquirer": "acquirer",
    "Buyer": "acquirer",
    "target": "target",
    "Target": "target",
    "Seller": "target",
    "target_ticker": "target_ticker",
    "Target Ticker": "target_ticker",
    "Ticker": "target_ticker",
    "therapeutic_area": "therapeutic_area",
    "Therapeutic Area": "therapeutic_area",
    "TA": "therapeutic_area",
    "indication": "indication",
    "Indication": "indication",
    "modality": "modality",
    "Modality": "modality",
    "stage": "stage",
    "Stage": "stage",
    "Phase": "stage",
    "biological_target": "biological_target",
    "Biological Target": "biological_target",
    "Target (Bio)": "biological_target",
    "territory": "territory",
    "Territory": "territory",
    "upfront_value_mm": "upfront_value_mm",
    "Upfront ($M)": "upfront_value_mm",
    "Upfront Value": "upfront_value_mm",
    "total_value_mm": "total_value_mm",
    "Total Value ($M)": "total_value_mm",
    "Total Deal Value": "total_value_mm",
    "contingent_value_mm": "contingent_value_mm",
    "Contingent ($M)": "contingent_value_mm",
    "has_cvr": "has_cvr",
    "CVR": "has_cvr",
    "has_earnout": "has_earnout",
    "Earnout": "has_earnout",
    "revenue_multiple": "revenue_multiple",
    "Revenue Multiple": "revenue_multiple",
    "source_url": "source_url",
    "URL": "source_url",
}

DEAL_TYPE_NORMALIZE = {
    "m&a": "M&A",
    "merger": "M&A",
    "acquisition": "M&A",
    "license": "licensing",
    "licensing": "licensing",
    "asset purchase": "asset_purchase",
    "asset_purchase": "asset_purchase",
    "venture": "venture",
    "ipo": "IPO",
    "follow-on": "follow_on",
    "follow_on": "follow_on",
    "spin-out": "spin_out",
    "spin_out": "spin_out",
    "spinout": "spin_out",
    "academic": "academic",
    "research": "academic",
}

STAGE_NORMALIZE = {
    "preclinical": "preclinical",
    "pre-clinical": "preclinical",
    "discovery": "preclinical",
    "phase 1": "phase_1",
    "phase_1": "phase_1",
    "phase i": "phase_1",
    "phase 1/2": "phase_1",
    "phase 2": "phase_2",
    "phase_2": "phase_2",
    "phase ii": "phase_2",
    "phase 2/3": "phase_2",
    "phase 3": "phase_3",
    "phase_3": "phase_3",
    "phase iii": "phase_3",
    "approved": "approved",
    "marketed": "commercial",
    "commercial": "commercial",
}


def _parse_float(v: str | None) -> float | None:
    if not v or v.strip() in ("", "-", "N/A", "n/a", "NA", "Undisclosed"):
        return None
    try:
        return float(v.strip().replace(",", "").replace("$", ""))
    except ValueError:
        return None


def _parse_bool(v: str | None) -> bool:
    if not v:
        return False
    return v.strip().lower() in ("true", "1", "yes", "y")


def _parse_date(v: str | None) -> str | None:
    if not v or v.strip() in ("", "-", "N/A"):
        return None
    v = v.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y", "%B %d, %Y", "%m/%d/%y"):
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    log.warning("Could not parse date: %s", v)
    return None


def _normalize_deal_type(v: str | None) -> str | None:
    if not v:
        return None
    return DEAL_TYPE_NORMALIZE.get(v.strip().lower(), v.strip())


def _normalize_stage(v: str | None) -> str | None:
    if not v:
        return None
    return STAGE_NORMALIZE.get(v.strip().lower(), v.strip())


def ingest_csv(csv_path: Path, as_of_date: str) -> dict:
    """Parse DealForma CSV, validate, normalize, return JSON-serializable dict."""
    records = []
    skipped = 0
    warnings = []

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        raw_cols = reader.fieldnames or []
        log.info("CSV columns: %s", raw_cols)

        # Build column mapping for this file
        col_map = {}
        for raw_col in raw_cols:
            if raw_col in COLUMN_MAP:
                col_map[raw_col] = COLUMN_MAP[raw_col]
            elif raw_col.strip() in COLUMN_MAP:
                col_map[raw_col] = COLUMN_MAP[raw_col.strip()]

        unmapped = [c for c in raw_cols if c not in col_map]
        if unmapped:
            log.info("Unmapped columns (ignored): %s", unmapped)

        for i, row in enumerate(reader):
            # Map columns
            mapped = {}
            for raw_col, internal_col in col_map.items():
                mapped[internal_col] = row.get(raw_col, "").strip()

            # Validate required fields
            missing = [f for f in REQUIRED_FIELDS if not mapped.get(f)]
            if missing:
                skipped += 1
                if skipped <= 5:
                    log.warning("Row %d skipped — missing: %s", i + 1, missing)
                continue

            # Normalize
            record = {
                "deal_id": mapped.get("deal_id") or f"df_{i+1:05d}",
                "deal_type": _normalize_deal_type(mapped.get("deal_type")),
                "announcement_date": _parse_date(mapped.get("announcement_date")),
                "close_date": _parse_date(mapped.get("close_date")),
                "acquirer": mapped.get("acquirer") or None,
                "target": mapped.get("target") or None,
                "target_ticker": (mapped.get("target_ticker") or "").upper() or None,
                "therapeutic_area": mapped.get("therapeutic_area") or None,
                "indication": mapped.get("indication") or None,
                "modality": mapped.get("modality") or None,
                "stage": _normalize_stage(mapped.get("stage")),
                "biological_target": mapped.get("biological_target") or None,
                "territory": mapped.get("territory") or None,
                "upfront_value_mm": _parse_float(mapped.get("upfront_value_mm")),
                "total_value_mm": _parse_float(mapped.get("total_value_mm")),
                "contingent_value_mm": _parse_float(mapped.get("contingent_value_mm")),
                "has_cvr": _parse_bool(mapped.get("has_cvr")),
                "has_earnout": _parse_bool(mapped.get("has_earnout")),
                "revenue_multiple": _parse_float(mapped.get("revenue_multiple")),
                "source_url": mapped.get("source_url") or None,
            }

            # Skip if announcement_date failed to parse
            if not record["announcement_date"]:
                skipped += 1
                continue

            # PIT filter: exclude deals announced after as_of_date
            if record["announcement_date"] > as_of_date:
                skipped += 1
                continue

            records.append(record)

    # Validate deal types
    unknown_types = set()
    for r in records:
        if r["deal_type"] and r["deal_type"] not in DEAL_TYPES:
            unknown_types.add(r["deal_type"])
    if unknown_types:
        warnings.append(f"Unknown deal_type values: {unknown_types}")
        log.warning("Unknown deal_type values: %s", unknown_types)

    # Stats
    type_counts = {}
    for r in records:
        dt = r["deal_type"] or "unknown"
        type_counts[dt] = type_counts.get(dt, 0) + 1

    ta_counts = {}
    for r in records:
        ta = r["therapeutic_area"] or "unknown"
        ta_counts[ta] = ta_counts.get(ta, 0) + 1

    n_with_upfront = sum(1 for r in records if r["upfront_value_mm"] is not None)
    n_with_total = sum(1 for r in records if r["total_value_mm"] is not None)
    n_with_ticker = sum(1 for r in records if r["target_ticker"])
    unique_tickers = sorted(set(r["target_ticker"] for r in records if r["target_ticker"]))

    result = {
        "schema": "dealforma_comps.v1",
        "as_of_date": as_of_date,
        "ingested_at": datetime.utcnow().isoformat() + "Z",
        "source_file": csv_path.name,
        "n_records": len(records),
        "n_skipped": skipped,
        "warnings": warnings,
        "stats": {
            "by_type": type_counts,
            "by_ta": dict(sorted(ta_counts.items(), key=lambda x: -x[1])[:20]),
            "n_with_upfront": n_with_upfront,
            "n_with_total_value": n_with_total,
            "n_with_ticker": n_with_ticker,
            "unique_tickers": len(unique_tickers),
            "tickers": unique_tickers[:50],
        },
        "deals": records,
    }

    return result


def main():
    parser = argparse.ArgumentParser(description="Ingest DealForma CSV export")
    parser.add_argument("csv_path", type=Path, help="Path to DealForma CSV export")
    parser.add_argument("--as-of-date", default=date.today().isoformat(), help="PIT date filter (default: today)")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="Output JSON path")
    args = parser.parse_args()

    if not args.csv_path.exists():
        log.error("CSV file not found: %s", args.csv_path)
        sys.exit(1)

    log.info("Ingesting %s with as_of_date=%s", args.csv_path, args.as_of_date)
    result = ingest_csv(args.csv_path, args.as_of_date)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    log.info(
        "Done: %d deals ingested, %d skipped → %s",
        result["n_records"],
        result["n_skipped"],
        args.output,
    )
    log.info("Type breakdown: %s", result["stats"]["by_type"])
    log.info("Tickers with match: %d", result["stats"]["n_with_ticker"])


if __name__ == "__main__":
    main()

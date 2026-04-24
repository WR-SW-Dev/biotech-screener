"""On-demand insider Form 4 feature enrichment for rankings.csv.

Reuses the existing parser/aggregator in ``tools.fetch_form4_insider``. At
rankings-assembly time, for each ranking row, we load that ticker's raw Form 4
JSON (if present), call ``compute_insider_features(txns, as_of_date)`` with the
production date, and extract ``insider_net_buy_value_90d`` only. All windows
anchor on ``filing_date`` (PIT-safe), matching the existing pipeline.

Semantics:
  * Raw file missing           → ``""`` (NA; "not fetched / no coverage")
  * Raw file present, no P/A
    or S/D in the 90d window   → ``0.0`` (real zero; "fetched, no activity")

The distinction matters for QA and any future modeling work: blank means
"unknown", zero means "known-silent". Do not collapse them downstream.

This is a diagnostic pass-through column. It is NOT added to
``common.feature_registry.FEATURE_REGISTRY`` — the scoring lane for
insider_net_buy_value_90d was closed 2026-04-05 and stays closed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from tools.fetch_form4_insider import InsiderTransaction, compute_insider_features

INSIDER_FIELD = "insider_net_buy_value_90d"


def load_ticker_raw_txns(
    raw_dir: Path,
    ticker: str,
) -> Optional[list]:
    """Load a ticker's raw Form 4 transactions. None if file is missing or unreadable."""
    raw_file = raw_dir / f"{ticker}.json"
    if not raw_file.exists():
        return None
    try:
        data = json.loads(raw_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return [InsiderTransaction(**t) for t in data]


def compute_insider_net_buy_value_90d(
    raw_dir: Path,
    ticker: str,
    as_of_date: str,
) -> Optional[float]:
    """Compute one ticker's insider_net_buy_value_90d at as_of_date.

    Returns:
        None if the raw JSON file does not exist (or is unreadable).
        A float otherwise — 0.0 when no P/A or S/D rows fall in the 90d
        filing_date window.
    """
    txns = load_ticker_raw_txns(raw_dir, ticker)
    if txns is None:
        return None
    feats = compute_insider_features(txns, as_of_date, windows=(90,))
    return float(feats.get(INSIDER_FIELD, 0.0))


def enrich_rows_with_insider_net_buy_value(
    rows: Iterable[Dict[str, Any]],
    as_of_date: str,
    raw_dir: Path,
) -> None:
    """Mutate each row in place to add ``insider_net_buy_value_90d``.

    Row order is preserved; row count is preserved; no other fields are touched.
    Missing raw file → empty string (NA); present-but-inactive → 0.0 (float).
    """
    for row in rows:
        ticker = row.get("ticker")
        if not ticker:
            row[INSIDER_FIELD] = ""
            continue
        value = compute_insider_net_buy_value_90d(raw_dir, ticker, as_of_date)
        row[INSIDER_FIELD] = "" if value is None else value

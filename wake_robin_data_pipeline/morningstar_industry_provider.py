"""Morningstar industry classification provider (PIT-stamped cache).

Fetches Morningstar Global Equity Classification Structure (MGECS) industry
group labels for the biotech universe via the Morningstar Direct REST API.

Cache structure:
    cache/morningstar_industry/{as_of_date}.json

PIT contract: once a date's cache is written, it is never overwritten.

Usage:
    provider = MorningstarIndustryProvider(token="eyJ...")
    result = provider.fetch_and_cache(tickers, as_of_date)
    # result["classifications"]["VRTX"] == "Biotechnology"

Env var: MORNINGSTAR_JWT — Bearer token for Morningstar Direct API.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CACHE_DIR = Path("cache/morningstar_industry")

# Morningstar Direct API base
API_BASE = "https://www.us-api.morningstar.com"

# Lookup endpoint: resolve ticker → Morningstar secId
SECURITY_LOOKUP_URL = f"{API_BASE}/ecm-mip-service/v1/securities/lookup"

# Stock header endpoint: returns classification data
STOCK_HEADER_URL = f"{API_BASE}/sal/sal-service/v1/stock/header"

# Fallback: known Morningstar MGECS industry groups for healthcare equities.
# Used when API is unavailable and no cache exists.
YAHOO_TO_MSTAR_INDUSTRY_GROUP: Dict[str, str] = {
    "Biotechnology": "Biotechnology",
    "Drug Manufacturers - General": "Drug Manufacturers—General",
    "Drug Manufacturers - Specialty & Generic": "Drug Manufacturers—Specialty & Generic",
    "Diagnostics & Research": "Diagnostics & Research",
    "Medical Devices": "Medical Devices",
    "Medical Instruments & Supplies": "Medical Instruments & Supplies",
    "Health Information Services": "Health Information Services",
    "Medical Care Facilities": "Medical Care Facilities",
}

# Rate limit: seconds between API calls
RATE_LIMIT_SEC = 0.25

# Schema version for cache files
SCHEMA_VERSION = "morningstar_industry.v1"

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    requests = None  # type: ignore[assignment]
    REQUESTS_AVAILABLE = False


def _make_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def _resolve_sec_id(ticker: str, headers: Dict[str, str]) -> Optional[str]:
    """Resolve ticker to Morningstar secId via lookup API."""
    try:
        resp = requests.get(
            SECURITY_LOOKUP_URL,
            params={"q": ticker, "type": "Stock", "limit": "5"},
            headers=headers,
            timeout=15,
        )
        if resp.status_code != 200:
            logger.debug("Lookup %s returned %d", ticker, resp.status_code)
            return None
        data = resp.json()
        # Look for US-listed match
        results = data if isinstance(data, list) else data.get("results", [])
        for r in results:
            sec_id = r.get("securityId") or r.get("secId") or r.get("id")
            exchange = (r.get("exchange") or r.get("exchangeId") or "").upper()
            sym = (r.get("ticker") or r.get("symbol") or "").upper()
            if sym == ticker.upper() and exchange in ("XNAS", "XNYS", "NAS", "NYS", "NASDAQ", "NYSE", ""):
                return sec_id
        # Fallback: first result
        if results:
            return results[0].get("securityId") or results[0].get("secId") or results[0].get("id")
        return None
    except Exception as e:
        logger.debug("Lookup %s failed: %s", ticker, e)
        return None


def _fetch_classification(sec_id: str, headers: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Fetch industry classification from Morningstar stock header API."""
    try:
        url = f"{STOCK_HEADER_URL}/{sec_id}"
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            logger.debug("Header %s returned %d", sec_id, resp.status_code)
            return None
        data = resp.json()
        result = {}
        # Extract classification fields (varies by endpoint version)
        for key in ("sectorName", "sector", "sectorCode"):
            if key in data:
                result["sector"] = str(data[key])
                break
        for key in ("industryGroupName", "industryGroup"):
            if key in data:
                result["industry_group"] = str(data[key])
                break
        for key in ("industryName", "industry"):
            if key in data:
                result["industry"] = str(data[key])
                break
        return result if result else None
    except Exception as e:
        logger.debug("Header %s failed: %s", sec_id, e)
        return None


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------


def _cache_path(cache_dir: Path, as_of: date) -> Path:
    return cache_dir / f"{as_of.isoformat()}.json"


def load_industry_cache(
    as_of: date,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> Optional[Dict[str, Any]]:
    """Load PIT-stamped industry classification cache.

    Returns the full cache dict or None if missing/corrupt.
    """
    path = _cache_path(cache_dir, as_of)
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("schema") != SCHEMA_VERSION:
            logger.warning("Schema mismatch in %s", path)
            return None
        if data.get("as_of_date") != as_of.isoformat():
            logger.warning("Date mismatch in %s", path)
            return None
        return data
    except Exception:
        return None


def _write_cache(
    cache_dir: Path,
    as_of: date,
    classifications: Dict[str, str],
    *,
    n_api: int = 0,
    n_fallback: int = 0,
    n_missing: int = 0,
) -> Path:
    """Write PIT-stamped cache. Never overwrites existing file."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, as_of)
    if path.exists():
        logger.info("Cache already exists: %s (PIT write-once)", path)
        return path
    data = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of.isoformat(),
        "n_tickers": len(classifications),
        "n_api": n_api,
        "n_fallback": n_fallback,
        "n_missing": n_missing,
        "classifications": classifications,
    }
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        tmp.replace(path)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    return path


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class MorningstarIndustryProvider:
    """Fetch and cache Morningstar industry group classifications.

    Args:
        token: Morningstar Direct JWT Bearer token. Falls back to
            ``MORNINGSTAR_JWT`` env var if not provided.
        cache_dir: Directory for PIT-stamped cache files.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        cache_dir: Path = DEFAULT_CACHE_DIR,
    ):
        self.token = token or os.environ.get("MORNINGSTAR_JWT", "")
        self.cache_dir = cache_dir

    def fetch_and_cache(
        self,
        tickers: List[str],
        as_of: date,
        *,
        yahoo_industries: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Fetch industry classifications and write PIT-stamped cache.

        Args:
            tickers: Universe tickers to classify.
            as_of: PIT date stamp.
            yahoo_industries: Optional dict {ticker: yahoo_industry} for
                fallback mapping when API is unavailable.

        Returns:
            Cache dict with "classifications" key: {ticker: industry_group}.
        """
        # Check existing cache (PIT write-once)
        existing = load_industry_cache(as_of, self.cache_dir)
        if existing is not None:
            logger.info(
                "Using existing cache for %s (%d tickers)",
                as_of,
                existing["n_tickers"],
            )
            return existing

        classifications: Dict[str, str] = {}
        n_api = 0
        n_fallback = 0
        n_missing = 0
        yahoo_map = yahoo_industries or {}

        can_api = bool(self.token) and REQUESTS_AVAILABLE
        if can_api:
            headers = _make_headers(self.token)
        else:
            logger.warning(
                "Morningstar API unavailable (token=%s, requests=%s). " "Using Yahoo→Morningstar fallback only.",
                "set" if self.token else "missing",
                REQUESTS_AVAILABLE,
            )

        for ticker in sorted(set(t.upper() for t in tickers)):
            # Try API first
            if can_api:
                sec_id = _resolve_sec_id(ticker, headers)
                if sec_id:
                    cls = _fetch_classification(sec_id, headers)
                    if cls and cls.get("industry_group"):
                        classifications[ticker] = cls["industry_group"]
                        n_api += 1
                        time.sleep(RATE_LIMIT_SEC)
                        continue
                time.sleep(RATE_LIMIT_SEC)

            # Fallback: Yahoo industry → Morningstar industry group mapping
            yahoo_ind = yahoo_map.get(ticker, "")
            mstar_group = YAHOO_TO_MSTAR_INDUSTRY_GROUP.get(yahoo_ind, "")
            if mstar_group:
                classifications[ticker] = mstar_group
                n_fallback += 1
            else:
                n_missing += 1

        path = _write_cache(
            self.cache_dir,
            as_of,
            classifications,
            n_api=n_api,
            n_fallback=n_fallback,
            n_missing=n_missing,
        )
        logger.info(
            "Wrote industry cache: %s (api=%d, fallback=%d, missing=%d)",
            path,
            n_api,
            n_fallback,
            n_missing,
        )
        return load_industry_cache(as_of, self.cache_dir) or {
            "schema": SCHEMA_VERSION,
            "as_of_date": as_of.isoformat(),
            "n_tickers": len(classifications),
            "classifications": classifications,
        }


# ---------------------------------------------------------------------------
# Convenience: load classifications as {ticker: industry_group}
# ---------------------------------------------------------------------------


def load_industry_classifications(
    as_of: date,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> Dict[str, str]:
    """Load industry_group mapping from PIT cache.

    Returns {ticker: industry_group} dict, empty if cache not found.
    """
    cache = load_industry_cache(as_of, cache_dir)
    if cache is None:
        return {}
    return cache.get("classifications", {})

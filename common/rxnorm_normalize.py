"""RxNorm drug name normalization — shared utility for entity resolution.

Maps messy drug names (CTgov interventions, sponsor codes, brand names,
generic names) to canonical RxNorm concepts (RxCUI + normalized name).

Provides a persistent local cache to avoid repeated API calls for the
same drug name across enrichment tools.

Usage:
    from common.rxnorm_normalize import RxNormNormalizer

    normalizer = RxNormNormalizer()
    result = normalizer.normalize("KEYTRUDA")
    # {'rxcui': '1547220', 'name': 'pembrolizumab', 'tty': 'IN', 'source': 'api'}

    # Batch normalize
    results = normalizer.normalize_batch(["KEYTRUDA", "pembrolizumab", "MK-3475"])
    # All three resolve to the same RxCUI
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = REPO_ROOT / "data" / "enrichment" / "rxnorm_cache.json"

logger = logging.getLogger("rxnorm_normalize")

RXNORM_API = "https://rxnav.nlm.nih.gov/REST"

# Patterns to clean CTgov intervention names before querying
_CLEAN_PATTERNS = [
    (re.compile(r"\s*\(.*?\)\s*", re.IGNORECASE), " "),  # Remove parenthetical
    (re.compile(r"\b\d+\s*(mg|mcg|ml|iu|units?)\b", re.IGNORECASE), ""),  # Remove dosage
    (re.compile(r"\b(injection|infusion|tablet|capsule|solution|suspension|cream|gel|patch)\b", re.IGNORECASE), ""),
    (re.compile(r"\b(placebo|sham|standard of care|best supportive care)\b", re.IGNORECASE), ""),
    (re.compile(r"\s+"), " "),  # Collapse whitespace
]

# Names that should never be looked up (not drugs)
_EXCLUDE = frozenset(
    {
        "placebo",
        "sham",
        "standard of care",
        "best supportive care",
        "observation",
        "no intervention",
        "active comparator",
        "control",
        "surgery",
        "radiation",
        "chemotherapy",
        "immunotherapy",
    }
)


def _clean_drug_name(raw: str) -> str:
    """Clean a CTgov intervention name for RxNorm lookup."""
    cleaned = raw.strip()
    for pattern, repl in _CLEAN_PATTERNS:
        cleaned = pattern.sub(repl, cleaned)
    return cleaned.strip()


def _is_excludable(name: str) -> bool:
    """Check if a name should be excluded from lookup."""
    return name.lower().strip() in _EXCLUDE or len(name) < 3


class RxNormNormalizer:
    """Persistent RxNorm normalizer with local JSON cache."""

    def __init__(self, cache_path: Path = CACHE_PATH):
        self._cache_path = cache_path
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._load_cache()

    def _load_cache(self):
        if self._cache_path.exists():
            try:
                with open(self._cache_path, encoding="utf-8") as f:
                    self._cache = json.load(f)
                logger.info("Loaded RxNorm cache: %d entries", len(self._cache))
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    def _save_cache(self):
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._cache_path, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, indent=2, default=str)

    def _api_get(self, url: str) -> Any:
        req = urllib.request.Request(url, headers={"User-Agent": "biotech-screener/1.0", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except Exception:
            return None

    def _query_approximate(self, term: str) -> Optional[Dict[str, str]]:
        """Query RxNorm approximate term endpoint."""
        encoded = urllib.parse.quote(term)
        data = self._api_get(f"{RXNORM_API}/approximateTerm.json?term={encoded}&maxEntries=1")
        if not data:
            return None

        candidates = data.get("approximateGroup", {}).get("candidate", [])
        if not candidates:
            return None

        rxcui = candidates[0].get("rxcui", "")
        score = candidates[0].get("score", "")

        if not rxcui:
            return None

        # Get properties for the RxCUI
        props = self._api_get(f"{RXNORM_API}/rxcui/{rxcui}/properties.json")
        if props and props.get("properties"):
            p = props["properties"]
            return {
                "rxcui": rxcui,
                "name": p.get("name", ""),
                "tty": p.get("tty", ""),  # Term type (IN=ingredient, BN=brand, etc.)
                "score": score,
            }

        return {"rxcui": rxcui, "name": "", "tty": "", "score": score}

    def _query_exact(self, term: str) -> Optional[Dict[str, str]]:
        """Query RxNorm exact match endpoint."""
        encoded = urllib.parse.quote(term)
        data = self._api_get(f"{RXNORM_API}/rxcui.json?name={encoded}")
        if not data:
            return None

        ids = data.get("idGroup", {}).get("rxnormId", [])
        if not ids:
            return None

        rxcui = ids[0]
        props = self._api_get(f"{RXNORM_API}/rxcui/{rxcui}/properties.json")
        if props and props.get("properties"):
            p = props["properties"]
            return {
                "rxcui": rxcui,
                "name": p.get("name", ""),
                "tty": p.get("tty", ""),
                "score": "100",
            }

        return {"rxcui": rxcui, "name": term, "tty": "", "score": "100"}

    def normalize(self, raw_name: str, skip_cache: bool = False) -> Dict[str, Any]:
        """Normalize a drug name to RxNorm concept.

        Returns dict with: rxcui, name, tty, source, raw_name, cleaned_name.
        Returns {'rxcui': None, ...} if no match found.
        """
        cleaned = _clean_drug_name(raw_name)

        if _is_excludable(cleaned):
            return {"rxcui": None, "name": None, "raw_name": raw_name, "source": "excluded"}

        # Check cache
        cache_key = cleaned.lower()
        if not skip_cache and cache_key in self._cache:
            result = dict(self._cache[cache_key])
            result["source"] = "cache"
            result["raw_name"] = raw_name
            return result

        # Try exact match first
        result = self._query_exact(cleaned)
        source = "exact"

        # Fall back to approximate
        if not result:
            result = self._query_approximate(cleaned)
            source = "approximate"
            time.sleep(0.1)

        if result:
            entry = {
                "rxcui": result["rxcui"],
                "name": result["name"],
                "tty": result["tty"],
                "score": result.get("score", ""),
            }
            self._cache[cache_key] = entry
            return {**entry, "source": source, "raw_name": raw_name, "cleaned_name": cleaned}

        # No match
        entry = {"rxcui": None, "name": None, "tty": None}
        self._cache[cache_key] = entry
        return {**entry, "source": "not_found", "raw_name": raw_name, "cleaned_name": cleaned}

    def normalize_batch(
        self,
        names: List[str],
        rate_limit: float = 0.15,
    ) -> List[Dict[str, Any]]:
        """Normalize a list of drug names. Saves cache after completion."""
        results = []
        for i, name in enumerate(names):
            result = self.normalize(name)
            results.append(result)
            if result["source"] not in ("cache", "excluded"):
                time.sleep(rate_limit)
            if (i + 1) % 50 == 0:
                logger.info("  Normalized %d/%d names", i + 1, len(names))

        self._save_cache()
        return results

    def get_all_names(self, rxcui: str) -> List[str]:
        """Get all known names/synonyms for an RxCUI."""
        data = self._api_get(f"{RXNORM_API}/rxcui/{rxcui}/allProperties.json?prop=names")
        if not data:
            return []

        props = data.get("propConceptGroup", {}).get("propConcept", [])
        return [p.get("propValue", "") for p in props if p.get("propValue")]

    @property
    def cache_size(self) -> int:
        return len(self._cache)

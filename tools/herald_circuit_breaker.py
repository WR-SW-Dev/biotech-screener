#!/usr/bin/env python3
"""Herald Circuit Breaker — Rate-limit protection with exponential backoff and cache fallback.

Prevents retry storms when external APIs (press release sources, newswires) return
HTTP 429 (rate-limit). Uses:

  1. Exponential backoff with jitter: 2^attempt * base (2s) + random jitter (0-1s)
  2. Cache fallback: when rate-limited, serve last-successful response if available
  3. Circuit breaker state: track domains in "open" state (recently rate-limited)
     to avoid hammering them

Usage:
    from tools.herald_circuit_breaker import CircuitBreaker
    breaker = CircuitBreaker()
    content = breaker.fetch(url)  # returns cached content if 429 occurs
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "herald_cache"
CIRCUIT_BREAKER_STATE_PATH = PROJECT_ROOT / "data" / "herald_cache" / "circuit_breaker_state.json"

# Circuit breaker thresholds
BACKOFF_BASE_SECONDS = 2
MAX_BACKOFF_SECONDS = 300  # 5 minutes
CIRCUIT_OPEN_DURATION_SECONDS = 300  # 5 minutes before retry
JITTER_MAX_SECONDS = 1.0


class CircuitBreaker:
    """Protects Herald from rate-limiting retry storms."""

    def __init__(self):
        """Initialize circuit breaker with persistent state."""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._circuit_state = self._load_circuit_state()

    def _domain_key(self, url: str) -> str:
        """Extract domain key from URL."""
        return urlparse(url).netloc or url

    def _cache_key(self, url: str) -> str:
        """Generate cache file name from URL."""
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
        return f"url_{url_hash}.json"

    def _get_cache_path(self, url: str) -> Path:
        """Get cache file path for a URL."""
        return CACHE_DIR / self._cache_key(url)

    def _load_circuit_state(self) -> dict[str, Any]:
        """Load circuit breaker state (which domains are open)."""
        if CIRCUIT_BREAKER_STATE_PATH.exists():
            try:
                with open(CIRCUIT_BREAKER_STATE_PATH) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_circuit_state(self) -> None:
        """Persist circuit breaker state."""
        CIRCUIT_BREAKER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CIRCUIT_BREAKER_STATE_PATH, "w") as f:
            json.dump(self._circuit_state, f, indent=2, default=str)

    def _is_circuit_open(self, domain: str) -> bool:
        """Check if a domain's circuit is currently open (recently rate-limited)."""
        if domain not in self._circuit_state:
            return False
        state = self._circuit_state[domain]
        opened_at = state.get("opened_at", 0)
        now = time.time()
        if now - opened_at > CIRCUIT_OPEN_DURATION_SECONDS:
            del self._circuit_state[domain]
            self._save_circuit_state()
            logger.info("Circuit closed for %s (cooldown expired)", domain)
            return False
        return True

    def _open_circuit(self, domain: str) -> None:
        """Mark a domain as rate-limited (open circuit)."""
        self._circuit_state[domain] = {
            "opened_at": time.time(),
            "reason": "rate_limit_429",
        }
        self._save_circuit_state()
        logger.warning("Circuit opened for %s (rate-limited)", domain)

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff with jitter.

        2^attempt * base + random jitter, capped at MAX_BACKOFF_SECONDS.
        """
        base_backoff = BACKOFF_BASE_SECONDS * (2**attempt)
        capped = min(base_backoff, MAX_BACKOFF_SECONDS)
        jitter = random.uniform(0, JITTER_MAX_SECONDS)
        return capped + jitter

    def _load_cached_response(self, url: str) -> Optional[str]:
        """Load cached response for a URL (cache fallback on 429)."""
        cache_path = self._get_cache_path(url)
        if not cache_path.exists():
            return None
        try:
            with open(cache_path) as f:
                data = json.load(f)
            cached_at = data.get("cached_at", 0)
            age_seconds = time.time() - cached_at
            logger.info("Cache hit for %s (age %.1fs)", url, age_seconds)
            return data.get("content")
        except (json.JSONDecodeError, IOError):
            return None

    def _save_cached_response(self, url: str, content: str) -> None:
        """Save successful response to cache."""
        cache_path = self._get_cache_path(url)
        data = {
            "url": url,
            "content": content,
            "cached_at": time.time(),
        }
        try:
            with open(cache_path, "w") as f:
                json.dump(data, f, default=str)
        except IOError as e:
            logger.warning("Failed to cache response for %s: %s", url, e)

    def fetch(self, url: str, fetch_fn, max_retries: int = 3, use_cache_fallback: bool = True) -> Optional[str]:
        """Fetch URL with circuit breaker, exponential backoff, and cache fallback.

        Args:
            url: URL to fetch
            fetch_fn: Callable that performs the actual fetch; should raise
                     requests.exceptions on error or return content on success.
                     Must accept (url, attempt_num) as arguments.
            max_retries: Maximum number of retry attempts
            use_cache_fallback: If True, serve cached content on rate-limit

        Returns:
            Response content, or None if fetch fails
        """
        domain = self._domain_key(url)

        # Check if circuit is open (domain recently rate-limited)
        if self._is_circuit_open(domain):
            logger.warning("Circuit open for %s, using cache fallback", domain)
            cached = self._load_cached_response(url)
            if cached and use_cache_fallback:
                return cached
            return None

        for attempt in range(max_retries):
            try:
                content = fetch_fn(url, attempt)
                # Success — save to cache
                self._save_cached_response(url, content)
                return content
            except RateLimitError:
                # HTTP 429 — open circuit and use cache
                self._open_circuit(domain)
                if use_cache_fallback:
                    cached = self._load_cached_response(url)
                    if cached:
                        logger.warning("Rate-limited on %s, serving cached response", url)
                        return cached
                return None
            except (ConnectionError, TimeoutError) as e:
                # Transient error — backoff and retry
                if attempt < max_retries - 1:
                    wait = self._calculate_backoff(attempt)
                    logger.info(
                        "Transient error on %s, backing off %.1fs (attempt %d/%d): %s",
                        url,
                        wait,
                        attempt + 1,
                        max_retries,
                        e,
                    )
                    time.sleep(wait)
                    continue
                logger.warning("Failed to fetch %s after %d attempts: %s", url, max_retries, e)
                return None
            except Exception as e:
                # Unknown error — fail immediately
                logger.error("Unexpected error fetching %s: %s", url, e)
                return None

        return None


class RateLimitError(Exception):
    """Raised when HTTP 429 (rate-limit) is encountered."""

    pass


if __name__ == "__main__":
    import sys

    # Health check: list circuit state
    breaker = CircuitBreaker()
    state = breaker._load_circuit_state()
    if state:
        print("Circuit Breaker State:")
        for domain, info in state.items():
            opened_at = info.get("opened_at", 0)
            age_seconds = time.time() - opened_at
            print(f"  {domain}: OPEN ({age_seconds:.0f}s ago)")
    else:
        print("Circuit Breaker: All circuits closed (healthy)")
    sys.exit(0)

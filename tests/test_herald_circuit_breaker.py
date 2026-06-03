"""Tests for Herald Circuit Breaker (exponential backoff + cache fallback).

Phase 1 Priority 4: Prevent rate-limit retry storms.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.herald_circuit_breaker import CircuitBreaker, RateLimitError


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Create a temporary cache directory for testing."""
    cache_dir = tmp_path / "herald_cache"
    cache_dir.mkdir()
    return cache_dir


@pytest.fixture
def breaker(temp_cache_dir):
    """Create a circuit breaker with temp cache."""
    cb = CircuitBreaker()
    cb._circuit_state = {}
    # Override paths for testing
    with patch("tools.herald_circuit_breaker.CACHE_DIR", temp_cache_dir):
        with patch("tools.herald_circuit_breaker.CIRCUIT_BREAKER_STATE_PATH", temp_cache_dir / "state.json"):
            yield cb


# ---------------------------------------------------------------------------
# Cache Management
# ---------------------------------------------------------------------------


def test_cache_key_generates_consistent_hash():
    """Cache key is consistent for the same URL."""
    cb = CircuitBreaker()
    url = "https://ir.acme.com/news"
    key1 = cb._cache_key(url)
    key2 = cb._cache_key(url)
    assert key1 == key2
    assert key1.startswith("url_")


def test_save_and_load_cached_response(breaker, temp_cache_dir):
    """Save and load cached response."""
    url = "https://ir.example.com/news"
    content = "<html>Press Releases</html>"

    with patch("tools.herald_circuit_breaker.CACHE_DIR", temp_cache_dir):
        breaker._save_cached_response(url, content)
        loaded = breaker._load_cached_response(url)

    assert loaded == content


def test_load_cached_response_returns_none_if_missing(breaker):
    """Loading non-existent cache returns None."""
    loaded = breaker._load_cached_response("https://nonexistent.com/news")
    assert loaded is None


def test_cached_response_includes_timestamp(breaker, temp_cache_dir):
    """Cached response includes timestamp for age tracking."""
    url = "https://ir.example.com/news"
    content = "test"

    with patch("tools.herald_circuit_breaker.CACHE_DIR", temp_cache_dir):
        before_time = time.time()
        breaker._save_cached_response(url, content)
        after_time = time.time()

        cache_file = temp_cache_dir / breaker._cache_key(url)
        data = json.loads(cache_file.read_text())

        assert data["cached_at"] >= before_time
        assert data["cached_at"] <= after_time


# ---------------------------------------------------------------------------
# Circuit Breaker State
# ---------------------------------------------------------------------------


def test_circuit_initially_closed(breaker):
    """New circuit breaker has no open circuits."""
    assert not breaker._is_circuit_open("example.com")
    assert not breaker._is_circuit_open("newdomain.com")


def test_circuit_opens_on_rate_limit(breaker):
    """Circuit opens when rate-limited."""
    domain = "example.com"
    breaker._open_circuit(domain)
    assert breaker._is_circuit_open(domain)


def test_circuit_closes_after_timeout(breaker):
    """Circuit closes after CIRCUIT_OPEN_DURATION expires."""
    domain = "example.com"
    breaker._open_circuit(domain)
    assert breaker._is_circuit_open(domain)

    # Mock time to pass the cooldown period
    with patch("time.time", return_value=time.time() + 400):  # 400s > 300s cooldown
        assert not breaker._is_circuit_open(domain)


def test_circuit_state_persists(breaker, temp_cache_dir):
    """Circuit state is persisted to disk."""
    domain = "example.com"

    with patch("tools.herald_circuit_breaker.CIRCUIT_BREAKER_STATE_PATH", temp_cache_dir / "state.json"):
        breaker._open_circuit(domain)
        state_file = temp_cache_dir / "state.json"
        assert state_file.exists()

        data = json.loads(state_file.read_text())
        assert domain in data
        assert data[domain]["reason"] == "rate_limit_429"


# ---------------------------------------------------------------------------
# Exponential Backoff
# ---------------------------------------------------------------------------


def test_backoff_increases_exponentially():
    """Backoff time increases exponentially with attempt."""
    cb = CircuitBreaker()

    # Mock random.uniform to return 0 jitter for deterministic testing
    with patch("random.uniform", return_value=0.0):
        backoff_0 = cb._calculate_backoff(0)  # 2^0 * 2 = 2
        backoff_1 = cb._calculate_backoff(1)  # 2^1 * 2 = 4
        backoff_2 = cb._calculate_backoff(2)  # 2^2 * 2 = 8

    assert backoff_0 == pytest.approx(2.0, abs=0.01)
    assert backoff_1 == pytest.approx(4.0, abs=0.01)
    assert backoff_2 == pytest.approx(8.0, abs=0.01)
    assert backoff_2 > backoff_1 > backoff_0


def test_backoff_capped_at_max():
    """Backoff is capped at MAX_BACKOFF_SECONDS."""
    cb = CircuitBreaker()

    with patch("random.uniform", return_value=0.0):
        # Attempt 8: 2^8 * 2 = 512s, but capped at 300s
        backoff = cb._calculate_backoff(8)

    assert backoff <= 301  # Capped at 300 + jitter


def test_backoff_includes_jitter():
    """Backoff includes random jitter."""
    cb = CircuitBreaker()

    # Get multiple backoff samples
    backoffs = [cb._calculate_backoff(0) for _ in range(10)]

    # Jitter should cause variation
    assert len(set(backoffs)) > 1, "Jitter should produce different values"
    # All should be >= base backoff (2s) and <= 2s + max jitter (1s)
    assert all(b >= 2.0 for b in backoffs)
    assert all(b <= 3.5 for b in backoffs)


# ---------------------------------------------------------------------------
# Fetch with Circuit Breaker
# ---------------------------------------------------------------------------


def test_fetch_success_caches_response(breaker, temp_cache_dir):
    """Successful fetch saves response to cache."""
    url = "https://ir.example.com/news"
    content = "<html>News</html>"

    def mock_fetch_fn(url, attempt):
        return content

    with patch("tools.herald_circuit_breaker.CACHE_DIR", temp_cache_dir):
        result = breaker.fetch(url, mock_fetch_fn)

    assert result == content
    # Verify cached
    cached = breaker._load_cached_response(url)
    assert cached == content


def test_fetch_rate_limit_opens_circuit(breaker):
    """Rate-limit (429) opens circuit."""
    url = "https://ir.example.com/news"
    domain = breaker._domain_key(url)

    def mock_fetch_fn(url, attempt):
        raise RateLimitError("HTTP 429")

    breaker.fetch(url, mock_fetch_fn)
    assert breaker._is_circuit_open(domain)


def test_fetch_rate_limit_serves_cache_fallback(breaker, temp_cache_dir):
    """Rate-limit serves cached content if available."""
    url = "https://ir.example.com/news"
    cached_content = "<html>Cached News</html>"

    # Pre-populate cache
    with patch("tools.herald_circuit_breaker.CACHE_DIR", temp_cache_dir):
        breaker._save_cached_response(url, cached_content)

    def mock_fetch_fn(url, attempt):
        raise RateLimitError("HTTP 429")

    with patch("tools.herald_circuit_breaker.CACHE_DIR", temp_cache_dir):
        result = breaker.fetch(url, mock_fetch_fn)

    assert result == cached_content


def test_fetch_rate_limit_returns_none_without_cache(breaker):
    """Rate-limit returns None if no cached content."""
    url = "https://ir.example.com/news"

    def mock_fetch_fn(url, attempt):
        raise RateLimitError("HTTP 429")

    result = breaker.fetch(url, mock_fetch_fn)
    assert result is None


def test_fetch_circuit_open_serves_cache(breaker, temp_cache_dir):
    """When circuit is open, fetch serves cache without attempting."""
    url = "https://ir.example.com/news"
    cached_content = "<html>Cached</html>"
    domain = breaker._domain_key(url)

    # Open circuit and cache
    with patch("tools.herald_circuit_breaker.CACHE_DIR", temp_cache_dir):
        breaker._open_circuit(domain)
        breaker._save_cached_response(url, cached_content)

    fetch_attempt_count = [0]

    def mock_fetch_fn(url, attempt):
        fetch_attempt_count[0] += 1
        raise RateLimitError("HTTP 429")

    with patch("tools.herald_circuit_breaker.CACHE_DIR", temp_cache_dir):
        result = breaker.fetch(url, mock_fetch_fn)

    # Should NOT have called fetch_fn (circuit was open)
    assert fetch_attempt_count[0] == 0
    assert result == cached_content


def test_fetch_transient_error_retries_with_backoff(breaker):
    """Transient errors trigger backoff and retry."""
    url = "https://ir.example.com/news"

    attempt_times = []
    max_attempts = 3

    def mock_fetch_fn(url, attempt):
        attempt_times.append(time.time())
        if len(attempt_times) < max_attempts:
            raise ConnectionError("Transient connection error")
        return "<html>Success</html>"

    sleep_durations = []

    def mock_sleep(duration):
        sleep_durations.append(duration)

    with patch("time.sleep", side_effect=mock_sleep):
        result = breaker.fetch(url, mock_fetch_fn, max_retries=max_attempts)

    assert result == "<html>Success</html>"
    assert len(sleep_durations) == max_attempts - 1  # N-1 retries
    # Each backoff should increase
    assert sleep_durations[0] < sleep_durations[1]


def test_fetch_unknown_error_fails_immediately(breaker):
    """Unknown errors cause immediate failure."""
    url = "https://ir.example.com/news"

    def mock_fetch_fn(url, attempt):
        raise ValueError("Unknown error")

    result = breaker.fetch(url, mock_fetch_fn, max_retries=5)
    assert result is None


def test_fetch_respects_max_retries(breaker):
    """Fetch respects max_retries limit."""
    url = "https://ir.example.com/news"
    attempt_count = [0]

    def mock_fetch_fn(url, attempt):
        attempt_count[0] += 1
        raise ConnectionError("Transient")

    with patch("time.sleep"):
        breaker.fetch(url, mock_fetch_fn, max_retries=3)

    # Should have attempted 3 times
    assert attempt_count[0] == 3


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


def test_domain_key_extracts_netloc():
    """Domain key extraction handles various URL formats."""
    cb = CircuitBreaker()
    assert cb._domain_key("https://www.globenewswire.com/search") == "www.globenewswire.com"
    assert cb._domain_key("https://ir.acme.com/news") == "ir.acme.com"
    assert cb._domain_key("http://example.com:8080/path") == "example.com:8080"


def test_different_domains_independent(breaker):
    """Different domains have independent circuit state."""
    domain_a = "example.com"
    domain_b = "other.com"

    breaker._open_circuit(domain_a)
    assert breaker._is_circuit_open(domain_a)
    assert not breaker._is_circuit_open(domain_b)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

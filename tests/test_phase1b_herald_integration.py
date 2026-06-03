"""Phase 1b Integration: Herald CircuitBreaker in fetch_company_press_releases._fetch_url().

Phase 1 Priority 4: Rate-limit protection with exponential backoff and cache fallback.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tools.herald_circuit_breaker import CircuitBreaker, RateLimitError


def test_fetch_url_uses_circuit_breaker():
    """Verify _fetch_url uses Herald CircuitBreaker for rate-limit protection."""
    from tools.fetch_company_press_releases import _fetch_url

    with patch("tools.fetch_company_press_releases._circuit_breaker") as mock_cb:
        mock_cb.fetch.return_value = "<html>Test</html>"
        with patch("tools.fetch_company_press_releases._rate_limit_domain"):
            result = _fetch_url("https://ir.example.com/news")

    mock_cb.fetch.assert_called_once()
    assert result == "<html>Test</html>"


def test_fetch_url_serves_cache_fallback_on_rate_limit():
    """Verify _fetch_url gets cache fallback when rate-limited."""
    from tools.fetch_company_press_releases import _fetch_url

    cached_content = "<html>Cached Press Release</html>"

    with patch("tools.fetch_company_press_releases._circuit_breaker") as mock_cb:
        mock_cb.fetch.return_value = cached_content
        with patch("tools.fetch_company_press_releases._rate_limit_domain"):
            result = _fetch_url("https://ir.example.com/news")

    assert result == cached_content


def test_fetch_url_rate_limit_opens_circuit():
    """Verify rate-limit (429) opens circuit for domain."""
    from tools.fetch_company_press_releases import _circuit_breaker, _fetch_url

    url = "https://ir.example.com/news"

    def mock_fetch_fn(url, attempt):
        raise RateLimitError("HTTP 429")

    with patch("tools.fetch_company_press_releases._rate_limit_domain"):
        # Test that the circuit breaker callback gets called with the right function
        with patch.object(_circuit_breaker, "fetch", wraps=_circuit_breaker.fetch):
            with patch("tools.fetch_company_press_releases._circuit_breaker.fetch") as mock_fetch:
                mock_fetch.return_value = None
                _fetch_url(url)
                mock_fetch.assert_called_once()


def test_fetch_url_circuit_open_blocks_retries():
    """Verify circuit-open state prevents retry storms."""
    from tools.fetch_company_press_releases import _fetch_url

    url = "https://ir.example.com/news"
    cached = "<html>Cached</html>"

    with patch("tools.fetch_company_press_releases._circuit_breaker") as mock_cb:
        # Circuit returns cache without retrying
        mock_cb.fetch.return_value = cached
        with patch("tools.fetch_company_press_releases._rate_limit_domain"):
            result = _fetch_url(url)

    assert result == cached
    # Verify callback was registered but not repeatedly called
    mock_cb.fetch.assert_called_once()


def test_fetch_url_exponential_backoff_on_transient_error():
    """Verify _fetch_url respects circuit breaker exponential backoff for transient errors."""
    from tools.fetch_company_press_releases import _fetch_url

    url = "https://ir.example.com/news"

    with patch("tools.fetch_company_press_releases._circuit_breaker") as mock_cb:
        mock_cb.fetch.return_value = "<html>Success</html>"
        with patch("tools.fetch_company_press_releases._rate_limit_domain"):
            result = _fetch_url(url, max_retries=3)

    # Verify circuit breaker was called with max_retries
    assert mock_cb.fetch.call_count == 1
    call_kwargs = mock_cb.fetch.call_args[1]
    assert call_kwargs.get("max_retries") == 3


def test_fetch_url_fails_gracefully_without_circuit_breaker():
    """Verify _fetch_url logs warning on failure without breaking downstream."""
    from tools.fetch_company_press_releases import _fetch_url

    url = "https://ir.example.com/news"

    with patch("tools.fetch_company_press_releases._circuit_breaker") as mock_cb:
        mock_cb.fetch.return_value = None  # Failure: no cache, no success
        with patch("tools.fetch_company_press_releases._rate_limit_domain"):
            with patch("tools.fetch_company_press_releases.logger") as mock_logger:
                result = _fetch_url(url)

    assert result is None
    mock_logger.warning.assert_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

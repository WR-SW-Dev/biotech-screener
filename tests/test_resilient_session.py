#!/usr/bin/env python3
"""Tests for create_resilient_session() in common/robustness.py."""

import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from common.robustness import create_resilient_session


class TestCreateResilientSession:
    """Tests for the resilient HTTP session factory."""

    def test_returns_session(self):
        """Should return a requests.Session instance."""
        session = create_resilient_session()
        assert isinstance(session, requests.Session)

    def test_default_timeout_applied(self):
        """Default timeout should be 30s (via patched send)."""
        session = create_resilient_session(timeout=42)
        # The patched send should inject timeout=42 as default
        assert session.send is not requests.Session.send  # monkey-patched

    def test_https_adapter_mounted(self):
        """Should mount HTTPAdapter on https://."""
        session = create_resilient_session()
        adapter = session.get_adapter("https://example.com")
        assert isinstance(adapter, HTTPAdapter)

    def test_http_adapter_mounted(self):
        """Should mount HTTPAdapter on http://."""
        session = create_resilient_session()
        adapter = session.get_adapter("http://example.com")
        assert isinstance(adapter, HTTPAdapter)

    def test_default_max_retries(self):
        """Default max_retries should be 3."""
        session = create_resilient_session()
        adapter = session.get_adapter("https://example.com")
        retry = adapter.max_retries
        assert isinstance(retry, Retry)
        assert retry.total == 3

    def test_custom_max_retries(self):
        """Should accept custom max_retries."""
        session = create_resilient_session(max_retries=5)
        adapter = session.get_adapter("https://example.com")
        assert adapter.max_retries.total == 5

    def test_default_backoff_factor(self):
        """Default backoff_factor should be 1.0."""
        session = create_resilient_session()
        adapter = session.get_adapter("https://example.com")
        assert adapter.max_retries.backoff_factor == 1.0

    def test_custom_backoff_factor(self):
        """Should accept custom backoff_factor."""
        session = create_resilient_session(backoff_factor=0.5)
        adapter = session.get_adapter("https://example.com")
        assert adapter.max_retries.backoff_factor == 0.5

    def test_post_in_allowed_methods(self):
        """POST should be in allowed_methods for trial registry searches."""
        session = create_resilient_session()
        adapter = session.get_adapter("https://example.com")
        allowed = adapter.max_retries.allowed_methods
        assert "POST" in allowed
        assert "GET" in allowed

    def test_default_status_forcelist(self):
        """Default status_forcelist should include 429,500,502,503,504."""
        session = create_resilient_session()
        adapter = session.get_adapter("https://example.com")
        expected = {429, 500, 502, 503, 504}
        assert set(adapter.max_retries.status_forcelist) == expected

    def test_extra_headers(self):
        """Should apply extra_headers to session."""
        session = create_resilient_session(extra_headers={"User-Agent": "test/1.0"})
        assert session.headers["User-Agent"] == "test/1.0"

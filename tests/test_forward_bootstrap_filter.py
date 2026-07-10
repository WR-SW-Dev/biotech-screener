"""Test the --forward-only-from window filter (mandate resolution command)."""

from __future__ import annotations

from tools.run_forward_bootstrap import filter_forward_windows

WINDOWS = [
    {"snap_date": "2026-06-18"},
    {"snap_date": "2026-06-26"},
    {"snap_date": "2026-06-29"},
    {"snap_date": "2026-07-06"},
]


def test_filter_excludes_pre_mandate_windows():
    kept = filter_forward_windows(WINDOWS, "2026-06-29")
    assert [w["snap_date"] for w in kept] == ["2026-06-29", "2026-07-06"]


def test_filter_none_returns_all():
    assert filter_forward_windows(WINDOWS, None) == WINDOWS


def test_filter_boundary_is_inclusive():
    kept = filter_forward_windows(WINDOWS, "2026-06-26")
    assert "2026-06-26" in [w["snap_date"] for w in kept]

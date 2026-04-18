"""Unit tests for common.alert_dedupe (Spec 063 Phase 3)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common.alert_dedupe import SCHEMA_VERSION, AlertDedupeStore


def _t(h=0, m=0, s=0):
    """Helper: UTC datetime on 2026-04-17 at H:M:S."""
    return datetime(2026, 4, 17, h, m, s, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Empty / corrupt state
# ---------------------------------------------------------------------------
def test_new_key_sends(tmp_path: Path):
    store = AlertDedupeStore(tmp_path / "sent.json")
    d = store.decide("k1", abs_move_pct=10.0, rel_move_pct=8.0, now=_t(14, 30))
    assert d.should_send is True
    assert d.reason == "new"


def test_missing_file_starts_empty(tmp_path: Path):
    store = AlertDedupeStore(tmp_path / "does_not_exist.json")
    assert store.snapshot() == {"schema": SCHEMA_VERSION, "entries": {}}


def test_corrupt_json_starts_fresh(tmp_path: Path):
    p = tmp_path / "sent.json"
    p.write_text("not valid json", encoding="utf-8")
    store = AlertDedupeStore(p)
    assert store.snapshot()["entries"] == {}


def test_unknown_schema_starts_fresh(tmp_path: Path):
    p = tmp_path / "sent.json"
    p.write_text(json.dumps({"schema": "ancient.v0", "entries": {"k": {}}}), encoding="utf-8")
    store = AlertDedupeStore(p)
    assert store.snapshot()["entries"] == {}


# ---------------------------------------------------------------------------
# Suppression within the window
# ---------------------------------------------------------------------------
def test_same_key_within_window_is_suppressed(tmp_path: Path):
    store = AlertDedupeStore(tmp_path / "sent.json", window_hours=4.0)
    store.record_sent(
        "k1", ticker="CGON", severity="HIGH", news_status="NONE", abs_move_pct=10.0, rel_move_pct=8.0, now=_t(14, 0)
    )
    d = store.decide("k1", abs_move_pct=10.0, rel_move_pct=8.0, now=_t(15, 0))
    assert d.should_send is False
    assert d.reason == "suppressed_recent"


def test_same_key_after_window_resends(tmp_path: Path):
    store = AlertDedupeStore(tmp_path / "sent.json", window_hours=4.0)
    store.record_sent(
        "k1", ticker="CGON", severity="HIGH", news_status="NONE", abs_move_pct=10.0, rel_move_pct=8.0, now=_t(10, 0)
    )
    d = store.decide("k1", abs_move_pct=10.0, rel_move_pct=8.0, now=_t(14, 30))
    assert d.should_send is True
    assert d.reason == "expired"


# ---------------------------------------------------------------------------
# Step-up: move widening
# ---------------------------------------------------------------------------
def test_widened_abs_resends_within_window(tmp_path: Path):
    store = AlertDedupeStore(tmp_path / "sent.json", step_up_pp=3.0)
    store.record_sent(
        "k1", ticker="CGON", severity="HIGH", news_status="NONE", abs_move_pct=10.0, rel_move_pct=8.0, now=_t(14, 0)
    )
    d = store.decide("k1", abs_move_pct=13.5, rel_move_pct=8.0, now=_t(14, 30))
    assert d.should_send is True
    assert d.reason == "widened_abs"


def test_widened_abs_uses_absolute_magnitude(tmp_path: Path):
    """A -6% that worsens to -10% should count as widening."""
    store = AlertDedupeStore(tmp_path / "sent.json", step_up_pp=3.0)
    store.record_sent(
        "k1", ticker="KROS", severity="HIGH", news_status="NONE", abs_move_pct=-6.0, rel_move_pct=-4.0, now=_t(14, 0)
    )
    d = store.decide("k1", abs_move_pct=-10.0, rel_move_pct=-4.0, now=_t(14, 30))
    assert d.should_send is True
    assert d.reason == "widened_abs"


def test_widened_rel_resends_within_window(tmp_path: Path):
    store = AlertDedupeStore(tmp_path / "sent.json", step_up_pp=3.0)
    store.record_sent(
        "k1", ticker="CGON", severity="HIGH", news_status="NONE", abs_move_pct=10.0, rel_move_pct=5.0, now=_t(14, 0)
    )
    d = store.decide("k1", abs_move_pct=10.0, rel_move_pct=8.5, now=_t(14, 30))
    assert d.should_send is True
    assert d.reason == "widened_rel"


def test_small_widening_below_threshold_is_suppressed(tmp_path: Path):
    store = AlertDedupeStore(tmp_path / "sent.json", step_up_pp=3.0)
    store.record_sent(
        "k1", ticker="CGON", severity="HIGH", news_status="NONE", abs_move_pct=10.0, rel_move_pct=8.0, now=_t(14, 0)
    )
    # +2pp — below the 3pp step-up
    d = store.decide("k1", abs_move_pct=12.0, rel_move_pct=9.0, now=_t(14, 30))
    assert d.should_send is False


def test_first_time_rel_context_is_step_up(tmp_path: Path):
    """If prior send had no XBI data and this one does, treat as widening."""
    store = AlertDedupeStore(tmp_path / "sent.json", step_up_pp=3.0)
    store.record_sent(
        "k1", ticker="CGON", severity="HIGH", news_status="NONE", abs_move_pct=10.0, rel_move_pct=None, now=_t(14, 0)
    )
    d = store.decide("k1", abs_move_pct=10.0, rel_move_pct=8.0, now=_t(14, 30))
    assert d.should_send is True
    assert d.reason == "widened_rel"


# ---------------------------------------------------------------------------
# Round-trip persistence
# ---------------------------------------------------------------------------
def test_roundtrip_through_disk(tmp_path: Path):
    path = tmp_path / "sent.json"
    s1 = AlertDedupeStore(path)
    s1.record_sent(
        "k1", ticker="CGON", severity="HIGH", news_status="NONE", abs_move_pct=10.0, rel_move_pct=8.0, now=_t(14, 0)
    )
    s1.save()

    s2 = AlertDedupeStore(path)
    d = s2.decide("k1", abs_move_pct=10.0, rel_move_pct=8.0, now=_t(15, 0))
    assert d.should_send is False
    assert d.reason == "suppressed_recent"


def test_atomic_write_does_not_leave_temp_files(tmp_path: Path):
    path = tmp_path / "sent.json"
    s = AlertDedupeStore(path)
    s.record_sent(
        "k", ticker="X", severity="HIGH", news_status="NONE", abs_move_pct=10.0, rel_move_pct=None, now=_t(14, 0)
    )
    s.save()
    # Only the final file should remain
    files = [p.name for p in tmp_path.iterdir()]
    assert files == ["sent.json"]


def test_record_sent_preserves_first_sent_at(tmp_path: Path):
    s = AlertDedupeStore(tmp_path / "sent.json")
    s.record_sent(
        "k", ticker="X", severity="HIGH", news_status="NONE", abs_move_pct=10.0, rel_move_pct=None, now=_t(14, 0)
    )
    s.record_sent(
        "k", ticker="X", severity="HIGH", news_status="OFFICIAL", abs_move_pct=13.0, rel_move_pct=None, now=_t(15, 0)
    )
    entry = s.snapshot()["entries"]["k"]
    assert entry["first_sent_at"] == "2026-04-17T14:00:00Z"
    assert entry["last_sent_at"] == "2026-04-17T15:00:00Z"
    # Severity/news/status fields updated to most recent
    assert entry["news_status"] == "OFFICIAL"
    assert entry["abs_move_pct"] == 13.0


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------
def test_prune_removes_stale_entries(tmp_path: Path):
    s = AlertDedupeStore(tmp_path / "sent.json")
    old = datetime.now(timezone.utc) - timedelta(days=14)
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    s.record_sent(
        "old", ticker="OLD", severity="HIGH", news_status="NONE", abs_move_pct=10.0, rel_move_pct=None, now=old
    )
    s.record_sent(
        "new", ticker="NEW", severity="HIGH", news_status="NONE", abs_move_pct=10.0, rel_move_pct=None, now=recent
    )
    removed = s.prune_older_than(days=7)
    assert removed == 1
    assert "new" in s.snapshot()["entries"]
    assert "old" not in s.snapshot()["entries"]


def test_prune_drops_entries_with_bad_timestamps(tmp_path: Path):
    p = tmp_path / "sent.json"
    p.write_text(
        json.dumps(
            {
                "schema": SCHEMA_VERSION,
                "entries": {
                    "bad": {"ticker": "X", "last_sent_at": "not a date"},
                    "missing": {"ticker": "Y"},
                },
            }
        ),
        encoding="utf-8",
    )
    s = AlertDedupeStore(p)
    removed = s.prune_older_than(days=7)
    assert removed == 2
    assert s.snapshot()["entries"] == {}


# ---------------------------------------------------------------------------
# Corrupt entries don't crash decide()
# ---------------------------------------------------------------------------
def test_decide_tolerates_bad_entry(tmp_path: Path):
    p = tmp_path / "sent.json"
    p.write_text(
        json.dumps(
            {
                "schema": SCHEMA_VERSION,
                "entries": {"k": {"ticker": "X", "last_sent_at": "oops"}},
            }
        ),
        encoding="utf-8",
    )
    s = AlertDedupeStore(p)
    d = s.decide("k", abs_move_pct=10.0, rel_move_pct=None, now=_t(14, 0))
    # Corrupt → treat as new, don't crash
    assert d.should_send is True
    assert d.reason == "new"

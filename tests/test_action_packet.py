"""Tests for action packet generator."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from tools.action_packet import assign_bucket, build_action_packet, render_action_markdown, write_action_packet


def _write_rankings(snap_dir: Path, rows: list[dict]) -> Path:
    """Write a rankings.csv from a list of dicts."""
    if not rows:
        # Write header-only
        csv_path = snap_dir / "rankings.csv"
        csv_path.write_text(
            "ticker,actionable_rank,target_weight_pct,eligible,catalyst_days,catalyst_mode,tier_any,tier_dev,alpha_cohort_key,catalyst_reason_detail,archetype\n"
        )
        return csv_path

    fieldnames = list(rows[0].keys())
    csv_path = snap_dir / "rankings.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def _write_metadata(snap_dir: Path, **overrides) -> Path:
    meta = {
        "version": "v1.3.0",
        "as_of_date": "2026-03-08",
        "clinical_sort_telemetry": {"ruleset_id": "e966af9d"},
    }
    meta.update(overrides)
    meta_path = snap_dir / "metadata.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f)
    return meta_path


def _make_row(
    ticker: str,
    rank: int,
    weight: float = 0.0,
    eligible: str = "1",
    catalyst_days: str = "60",
    catalyst_mode: str = "specific_days",
    tier: str = "A",
    archetype: str = "drug_developer",
) -> dict:
    return {
        "ticker": ticker,
        "actionable_rank": str(rank),
        "target_weight_pct": str(weight),
        "eligible": eligible,
        "catalyst_days": catalyst_days,
        "catalyst_mode": catalyst_mode,
        "tier_any": tier,
        "tier_dev": tier,
        "alpha_cohort_key": "drug_developer",
        "catalyst_reason_detail": f"{ticker} Phase 3",
        "archetype": archetype,
    }


class TestBucketAssignment:
    def test_binary_now(self):
        assert assign_bucket(15, "specific_days") == "binary_now"

    def test_binary_now_boundary(self):
        assert assign_bucket(30, "specific_days") == "binary_now"

    def test_build_window(self):
        assert assign_bucket(60, "specific_days") == "build_window"

    def test_build_window_boundary(self):
        assert assign_bucket(90, "blended_window") == "build_window"

    def test_less_binary(self):
        assert assign_bucket(120, "specific_days") == "less_binary"

    def test_less_binary_boundary(self):
        assert assign_bucket(180, "specific_days") == "less_binary"

    def test_core_high_days(self):
        assert assign_bucket(300, "specific_days") == "core"

    def test_core_no_upcoming(self):
        assert assign_bucket(15, "no_upcoming") == "core"

    def test_core_missing(self):
        assert assign_bucket(60, "missing") == "core"

    def test_core_none_days(self):
        assert assign_bucket(None, "specific_days") == "core"


class TestBuildActionPacket:
    def test_build_basic(self, tmp_path):
        snap = tmp_path / "2026-03-08"
        snap.mkdir()
        _write_rankings(
            snap,
            [
                _make_row("AAAA", 1, 5.0, catalyst_days="15"),
                _make_row("BBBB", 2, 4.0, catalyst_days="60"),
                _make_row("CCCC", 3, 3.0, catalyst_days="120"),
                _make_row("DDDD", 4, 2.0, catalyst_days="300"),
            ],
        )
        _write_metadata(snap)

        packet = build_action_packet(snap, top_n=60)
        assert packet["schema"] == "action_packet.v1"
        assert "binary_now" in packet["buckets"]
        assert "build_window" in packet["buckets"]
        assert "less_binary" in packet["buckets"]
        assert "core" in packet["buckets"]
        total = sum(b["count"] for b in packet["buckets"].values())
        assert total == 4

    def test_top_n_limit(self, tmp_path):
        snap = tmp_path / "2026-03-08"
        snap.mkdir()
        rows = [_make_row(f"T{i:03d}", i, catalyst_days="60") for i in range(1, 21)]
        _write_rankings(snap, rows)
        _write_metadata(snap)

        packet = build_action_packet(snap, top_n=5)
        total = sum(b["count"] for b in packet["buckets"].values())
        assert total == 5

    def test_ineligible_excluded(self, tmp_path):
        snap = tmp_path / "2026-03-08"
        snap.mkdir()
        _write_rankings(
            snap,
            [
                _make_row("ELIG", 1, 5.0, eligible="1", catalyst_days="60"),
                _make_row("SKIP", 2, 4.0, eligible="0", catalyst_days="60"),
            ],
        )
        _write_metadata(snap)

        packet = build_action_packet(snap, top_n=60)
        total = sum(b["count"] for b in packet["buckets"].values())
        assert total == 1
        all_tickers = [n["ticker"] for b in packet["buckets"].values() for n in b["names"]]
        assert "ELIG" in all_tickers
        assert "SKIP" not in all_tickers

    def test_in_portfolio_flag(self, tmp_path):
        snap = tmp_path / "2026-03-08"
        snap.mkdir()
        _write_rankings(
            snap,
            [
                _make_row("AAAA", 1, 5.0, catalyst_days="60"),
                _make_row("BBBB", 2, 0.0, catalyst_days="60"),
            ],
        )
        _write_metadata(snap)

        packet = build_action_packet(snap, top_n=60)
        names = packet["buckets"]["build_window"]["names"]
        by_ticker = {n["ticker"]: n for n in names}
        assert by_ticker["AAAA"]["in_portfolio"] is True
        assert by_ticker["BBBB"]["in_portfolio"] is False

    def test_empty_snapshot(self, tmp_path):
        snap = tmp_path / "2026-03-08"
        snap.mkdir()
        _write_rankings(snap, [])
        _write_metadata(snap)

        packet = build_action_packet(snap, top_n=60)
        assert packet["schema"] == "action_packet.v1"
        for b in packet["buckets"].values():
            assert b["count"] == 0
            assert b["names"] == []

    def test_provenance_fields(self, tmp_path):
        snap = tmp_path / "2026-03-08"
        snap.mkdir()
        _write_rankings(snap, [_make_row("AAAA", 1, 5.0)])
        _write_metadata(snap)

        packet = build_action_packet(snap, top_n=60)
        assert packet["ruleset_id"] == "e966af9d"
        assert packet["engine_version"] == "v1.3.0"
        assert packet["as_of_date"] == "2026-03-08"


class TestRenderMarkdown:
    def test_has_tables(self, tmp_path):
        snap = tmp_path / "2026-03-08"
        snap.mkdir()
        _write_rankings(
            snap,
            [
                _make_row("AAAA", 1, 5.0, catalyst_days="15"),
                _make_row("BBBB", 2, 4.0, catalyst_days="60"),
                _make_row("CCCC", 3, 3.0, catalyst_days="120"),
                _make_row("DDDD", 4, 2.0, catalyst_days="300"),
            ],
        )
        _write_metadata(snap)

        packet = build_action_packet(snap, top_n=60)
        md = render_action_markdown(packet)

        assert "|" in md
        assert "Binary Now" in md
        assert "Build Window" in md
        assert "Less Binary" in md
        assert "Core" in md


class TestWriteActionPacket:
    def test_writes_files(self, tmp_path):
        snap = tmp_path / "2026-03-08"
        snap.mkdir()
        _write_rankings(snap, [_make_row("AAAA", 1, 5.0, catalyst_days="60")])
        _write_metadata(snap)

        json_path = write_action_packet(snap, top_n=60)
        assert json_path.exists()
        assert (snap / "ACTION.md").exists()

        data = json.loads(json_path.read_text())
        assert data["schema"] == "action_packet.v1"

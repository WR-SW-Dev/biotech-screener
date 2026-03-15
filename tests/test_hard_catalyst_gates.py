"""Tests for hard-catalyst production gates (Spec 018)."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.run_daily_production import (
    GateConfig,
    check_hard_carry_state,
    check_hard_catalyst_supply,
    check_hard_options_coverage,
    check_hard_queue_actionability,
    check_hard_queue_artifacts,
)


def _write_queue_json(path: Path, rows: list, summary: dict | None = None):
    """Write a minimal options_review_queue.json."""
    if summary is None:
        n_hard = sum(1 for r in rows if str(r.get("is_hard_catalyst", "0")) == "1")
        summary = {"n_total": len(rows), "n_hard_catalyst": n_hard}
    data = {"schema_version": "options_review_queue.v2", "hard_only": True, "summary": summary, "rows": rows}
    path.write_text(json.dumps(data))


def _write_queue_csv(path: Path, rows: list):
    """Write minimal queue CSV with header."""
    if not rows:
        path.write_text("ticker\n")
        return
    fields = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _hard_row(ticker="TEST", cat_days="60", iv="0.85", cvs="1.3", reasons="hard_catalyst;cheap_straddle"):
    return {
        "ticker": ticker,
        "is_hard_catalyst": "1",
        "catalyst_days": cat_days,
        "opt_atm_iv": iv,
        "cheap_vol_score": cvs,
        "review_reasons": reasons,
        "market_model_disagreement": "",
        "ts_flag": "",
        "ts_flag_type": "",
    }


CONFIG = GateConfig()


# --- check_hard_queue_artifacts ---


class TestHardQueueArtifacts:
    def test_pass_both_exist(self, tmp_path):
        _write_queue_json(tmp_path / "options_review_queue.json", [])
        _write_queue_csv(tmp_path / "options_review_queue.csv", [])
        r = check_hard_queue_artifacts(tmp_path)
        assert r.status == "PASS"

    def test_fail_json_missing(self, tmp_path):
        _write_queue_csv(tmp_path / "options_review_queue.csv", [])
        r = check_hard_queue_artifacts(tmp_path)
        assert r.status == "FAIL"

    def test_fail_json_malformed(self, tmp_path):
        (tmp_path / "options_review_queue.json").write_text("{bad json")
        _write_queue_csv(tmp_path / "options_review_queue.csv", [])
        r = check_hard_queue_artifacts(tmp_path)
        assert r.status == "FAIL"


# --- check_hard_catalyst_supply ---


class TestHardCatalystSupply:
    def test_pass(self, tmp_path):
        rows = [_hard_row(f"T{i}", cat_days=str(30 + i)) for i in range(10)]
        _write_queue_json(tmp_path / "options_review_queue.json", rows)
        r = check_hard_catalyst_supply(tmp_path, CONFIG)
        assert r.status == "PASS"

    def test_warn_low_hard(self, tmp_path):
        rows = [_hard_row(f"T{i}", cat_days=str(30 + i)) for i in range(5)]
        _write_queue_json(tmp_path / "options_review_queue.json", rows)
        r = check_hard_catalyst_supply(tmp_path, CONFIG)
        assert r.status == "WARN"

    def test_fail_too_few(self, tmp_path):
        rows = [_hard_row("T1", cat_days="30"), _hard_row("T2", cat_days="60")]
        _write_queue_json(tmp_path / "options_review_queue.json", rows)
        r = check_hard_catalyst_supply(tmp_path, CONFIG)
        assert r.status == "FAIL"

    def test_fail_zero_near_term(self, tmp_path):
        rows = [_hard_row(f"T{i}", cat_days="150") for i in range(10)]
        _write_queue_json(tmp_path / "options_review_queue.json", rows)
        r = check_hard_catalyst_supply(tmp_path, CONFIG)
        assert r.status == "FAIL"


# --- check_hard_options_coverage ---


class TestHardOptionsCoverage:
    def test_pass_high_coverage(self, tmp_path):
        rows = [_hard_row(f"T{i}") for i in range(10)]
        _write_queue_json(tmp_path / "options_review_queue.json", rows)
        r = check_hard_options_coverage(tmp_path, CONFIG)
        assert r.status == "PASS"

    def test_warn_low_iv_coverage(self, tmp_path):
        rows = [_hard_row(f"T{i}", iv="0.8") for i in range(5)]
        rows += [_hard_row(f"T{i+5}", iv="") for i in range(5)]
        _write_queue_json(tmp_path / "options_review_queue.json", rows)
        r = check_hard_options_coverage(tmp_path, CONFIG)
        assert r.status == "WARN"

    def test_fail_very_low_iv(self, tmp_path):
        rows = [_hard_row(f"T{i}", iv="0.8") for i in range(2)]
        rows += [_hard_row(f"T{i+2}", iv="") for i in range(8)]
        _write_queue_json(tmp_path / "options_review_queue.json", rows)
        r = check_hard_options_coverage(tmp_path, CONFIG)
        assert r.status == "FAIL"

    def test_warn_zero_reviewable(self, tmp_path):
        rows = [_hard_row(f"T{i}", reasons="hard_catalyst") for i in range(10)]
        _write_queue_json(tmp_path / "options_review_queue.json", rows)
        r = check_hard_options_coverage(tmp_path, CONFIG)
        assert r.status == "WARN"


# --- check_hard_carry_state ---


class TestHardCarryState:
    def test_pass_no_backslides(self, tmp_path):
        snap_dir = tmp_path / "snapshots" / "2026-03-15"
        snap_dir.mkdir(parents=True)
        state_dir = tmp_path / "snapshots" / "state"
        state_dir.mkdir(parents=True)
        state = {"BIIB": {"estimated_event_date": "2026-04-03", "catalyst_source": "SEC_8K_FILING"}}
        (state_dir / "hard_catalyst_carry.json").write_text(json.dumps(state))

        # Rankings with BIIB showing hard source (carry worked)
        with open(snap_dir / "rankings.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["ticker", "catalyst_source"])
            w.writeheader()
            w.writerow({"ticker": "BIIB", "catalyst_source": "SEC_8K_FILING"})

        r = check_hard_carry_state(snap_dir, "2026-03-15")
        assert r.status == "PASS"
        assert r.value["n_backslides"] == 0

    def test_fail_backslide(self, tmp_path):
        snap_dir = tmp_path / "snapshots" / "2026-03-15"
        snap_dir.mkdir(parents=True)
        state_dir = tmp_path / "snapshots" / "state"
        state_dir.mkdir(parents=True)
        state = {"BIIB": {"estimated_event_date": "2026-04-03", "catalyst_source": "SEC_8K_FILING"}}
        (state_dir / "hard_catalyst_carry.json").write_text(json.dumps(state))

        # Rankings with BIIB showing soft source (backslide!)
        with open(snap_dir / "rankings.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["ticker", "catalyst_source"])
            w.writeheader()
            w.writerow({"ticker": "BIIB", "catalyst_source": "CTGOV_CALENDAR"})

        r = check_hard_carry_state(snap_dir, "2026-03-15")
        assert r.status == "FAIL"
        assert r.value["n_backslides"] == 1

    def test_fail_unreadable(self, tmp_path):
        snap_dir = tmp_path / "snapshots" / "2026-03-15"
        snap_dir.mkdir(parents=True)
        state_dir = tmp_path / "snapshots" / "state"
        state_dir.mkdir(parents=True)
        (state_dir / "hard_catalyst_carry.json").write_text("{bad json")
        r = check_hard_carry_state(snap_dir, "2026-03-15")
        assert r.status == "FAIL"

    def test_warn_absent_with_hard_queue(self, tmp_path):
        snap_dir = tmp_path / "snapshots" / "2026-03-15"
        snap_dir.mkdir(parents=True)
        # No state dir, but queue has hard rows
        _write_queue_json(snap_dir / "options_review_queue.json", [_hard_row("BIIB")])
        r = check_hard_carry_state(snap_dir, "2026-03-15")
        assert r.status == "WARN"


# --- check_hard_queue_actionability ---


class TestHardQueueActionability:
    def test_pass_enough_reviewable(self, tmp_path):
        rows = [
            _hard_row("A", reasons="hard_catalyst;cheap_straddle"),
            _hard_row("B", reasons="hard_catalyst;high_disagreement"),
            _hard_row("C", reasons="hard_catalyst;extreme_skew"),
        ]
        _write_queue_json(tmp_path / "options_review_queue.json", rows)
        r = check_hard_queue_actionability(tmp_path, CONFIG)
        assert r.status == "PASS"
        assert r.value["n_reviewable"] == 3

    def test_warn_few_reviewable(self, tmp_path):
        rows = [
            _hard_row("A", reasons="hard_catalyst;cheap_straddle"),
            _hard_row("B", reasons="hard_catalyst"),
        ]
        _write_queue_json(tmp_path / "options_review_queue.json", rows)
        r = check_hard_queue_actionability(tmp_path, CONFIG)
        assert r.status == "WARN"

    def test_warn_zero_reviewable(self, tmp_path):
        rows = [_hard_row("A", reasons="hard_catalyst")]
        _write_queue_json(tmp_path / "options_review_queue.json", rows)
        r = check_hard_queue_actionability(tmp_path, CONFIG)
        assert r.status == "WARN"

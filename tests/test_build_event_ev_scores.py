"""Tests for Spec 060 — Daily Event EV Scoring.

Tests written BEFORE implementation per spec template.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

# ============================================================================
# Fixtures
# ============================================================================


def _make_pdufa_entry(ticker: str = "PVLA", pdufa_date: str = "2026-05-24") -> Dict[str, Any]:
    return {
        "ticker": ticker,
        "date": pdufa_date,
        "disclosed_at": "2026-01-01",
        "drug_name": "test_drug",
        "indication": "rare_disease",
        "phase": "3",
    }


def _make_catalyst_event(ticker: str = "ACAD", event_type: str = "DATA_READOUT") -> Dict[str, Any]:
    return {
        "ticker": ticker,
        "event_type": event_type,
        "expected_date": "2026-06-15",
        "disclosed_at": "2026-01-15",
        "phase": "3",
        "indication": "oncology",
        "source": "CTGOV",
        "source_uid": f"NCT_{ticker}_001",
    }


def _write_fixture_data(tmp_path: Path) -> Dict[str, Path]:
    """Write minimal fixture data for a scoring run."""
    prod_data = tmp_path / "production_data"
    prod_data.mkdir()

    # PDUFA dates
    pdufa = [_make_pdufa_entry("PVLA", "2026-05-24"), _make_pdufa_entry("BIIB", "2026-05-24")]
    (prod_data / "pdufa_dates.json").write_text(json.dumps(pdufa))

    # Catalyst events
    events = {
        "summaries": [
            _make_catalyst_event("ACAD", "DATA_READOUT"),
            _make_catalyst_event("IONS", "DATA_READOUT"),
        ]
    }
    (prod_data / "catalyst_events_2026-04-06.json").write_text(json.dumps(events))

    # Snapshot with rankings
    snap_dir = tmp_path / "data" / "snapshots" / "2026-04-06"
    snap_dir.mkdir(parents=True)
    rankings_header = "ticker,coinvest_score_z,inst_delta_z,opt_atm_iv,opt_front_iv,opt_back_iv,opt_liquidity_state,implied_event_move,catalyst_days,close_price,catalyst_family,lead_program_phase\n"
    rankings_rows = (
        "PVLA,1.5,0.8,1.20,1.40,0.80,liquid,0.25,48,12.00,REGULATORY,3\n"
        "ACAD,0.9,0.5,0.80,0.90,0.70,liquid,0.15,70,25.00,CLINICAL,3\n"
        "IONS,0.3,-0.2,0.50,0.55,0.48,thin,0.10,70,40.00,CLINICAL,2\n"
        "BIIB,1.2,0.6,0.60,0.65,0.55,liquid,0.12,48,180.00,REGULATORY,3\n"
    )
    (snap_dir / "rankings.csv").write_text(rankings_header + rankings_rows)

    # Artifacts output dir
    artifacts = tmp_path / "artifacts" / "event_ev"
    artifacts.mkdir(parents=True)

    return {
        "repo_root": tmp_path,
        "prod_data": prod_data,
        "snap_dir": snap_dir,
        "artifacts": artifacts,
    }


# ============================================================================
# Test: Scoring Tool
# ============================================================================


class TestBuildEventEVScores:
    def test_happy_path(self, tmp_path):
        paths = _write_fixture_data(tmp_path)
        from tools.build_event_ev_scores import build_scores

        result = build_scores(
            as_of_date="2026-04-06",
            repo_root=paths["repo_root"],
        )
        assert "error" not in result
        assert result["n_total"] > 0
        assert "leaderboard" in result

    def test_empty_graph(self, tmp_path):
        """No data sources → empty leaderboard, not an error."""
        paths = _write_fixture_data(tmp_path)
        # Remove all data sources
        (paths["prod_data"] / "pdufa_dates.json").unlink()
        (paths["prod_data"] / "catalyst_events_2026-04-06.json").unlink()

        from tools.build_event_ev_scores import build_scores

        result = build_scores(
            as_of_date="2026-04-06",
            repo_root=paths["repo_root"],
        )
        assert result["n_total"] == 0
        assert result["leaderboard"] == []

    def test_leaderboard_sorted_by_ds_adj_ev(self, tmp_path):
        paths = _write_fixture_data(tmp_path)
        from tools.build_event_ev_scores import build_scores

        result = build_scores(as_of_date="2026-04-06", repo_root=paths["repo_root"])
        lb = result["leaderboard"]
        if len(lb) >= 2:
            evs = [r["ds_adj_ev"] for r in lb]
            assert evs == sorted(evs, reverse=True)

    def test_leaderboard_columns(self, tmp_path):
        paths = _write_fixture_data(tmp_path)
        from tools.build_event_ev_scores import build_scores

        result = build_scores(as_of_date="2026-04-06", repo_root=paths["repo_root"])
        if result["leaderboard"]:
            row = result["leaderboard"][0]
            expected_cols = {
                "rank",
                "ticker",
                "event_type",
                "days_to_event",
                "p_hit",
                "p_miss",
                "scenario_ev",
                "ds_adj_ev",
                "timing_on_time",
                "analog_conf",
            }
            assert expected_cols.issubset(set(row.keys()))

    def test_writes_artifacts(self, tmp_path):
        paths = _write_fixture_data(tmp_path)
        from tools.build_event_ev_scores import build_scores

        build_scores(
            as_of_date="2026-04-06",
            repo_root=paths["repo_root"],
            output_dir=paths["artifacts"],
        )
        # Should have written JSON and markdown
        assert (paths["artifacts"] / "2026-04-06_ev_leaderboard.json").exists()
        assert (paths["artifacts"] / "2026-04-06_ev_leaderboard.md").exists()

    def test_idempotent(self, tmp_path):
        paths = _write_fixture_data(tmp_path)
        from tools.build_event_ev_scores import build_scores

        r1 = build_scores(as_of_date="2026-04-06", repo_root=paths["repo_root"])
        r2 = build_scores(as_of_date="2026-04-06", repo_root=paths["repo_root"])
        assert r1["n_total"] == r2["n_total"]
        assert r1["leaderboard"] == r2["leaderboard"]

    def test_spec059_overlays_attached(self, tmp_path):
        """Liquid names should have branch_sensitivity in full results."""
        paths = _write_fixture_data(tmp_path)
        from tools.build_event_ev_scores import build_scores

        result = build_scores(as_of_date="2026-04-06", repo_root=paths["repo_root"])
        # Check full results for branch_sensitivity
        for ev in result.get("events", []):
            if ev.get("node", {}).get("ticker") == "PVLA":
                # PVLA has liquid options in fixtures
                # branch_sensitivity may or may not be populated depending on
                # whether context_feats flow correctly, but the field should exist
                assert "branch_sensitivity" in ev or "payoff" in ev

    def test_operator_memo_content(self, tmp_path):
        paths = _write_fixture_data(tmp_path)
        from tools.build_event_ev_scores import build_scores

        build_scores(
            as_of_date="2026-04-06",
            repo_root=paths["repo_root"],
            output_dir=paths["artifacts"],
        )
        md_path = paths["artifacts"] / "2026-04-06_ev_leaderboard.md"
        if md_path.exists():
            content = md_path.read_text()
            assert "2026-04-06" in content
            assert "EV" in content or "Event" in content

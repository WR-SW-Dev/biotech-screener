"""Tests for common.promotion_gate — Checklist v2 validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.promotion_gate import GATE_NAMES, load_checklist_results, validate_checklist_v2, validate_promotion_packet

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

FULL_PASS_SIGNAL = {
    "gate1_pass": True,
    "selector_delta_pp": 1.85,
    "selector_tstat": 3.56,
    "ranker_ic": 0.106,
    "n_periods": 67,
    "gate2_pass": True,
    "incremental_nw_t": 2.34,
    "incremental_verdict": "SIGNIFICANT",
    "univariate_nw_t": 3.05,
    "gate3_pass": True,
    "boot_mean": 0.019,
    "ci_lower": 0.004,
    "ci_upper": 0.034,
    "ci_excludes_zero": True,
    "prob_positive": 0.98,
    "gate4_pass": True,
    "fdr_q": 0.096,
    "gate5_pass": True,
    "worst_slice_name": "2021",
    "worst_slice_delta": 0.003,
    "all_slices_positive": True,
}

PARTIAL_FAIL_SIGNAL = {
    "gate1_pass": True,
    "selector_delta_pp": 1.37,
    "selector_tstat": 1.91,
    "ranker_ic": -0.019,
    "n_periods": 67,
    "gate2_pass": False,
    "incremental_nw_t": 1.45,
    "incremental_verdict": "NOT_SIGNIFICANT",
    "univariate_nw_t": 1.98,
    "gate3_pass": True,
    "boot_mean": 0.014,
    "ci_lower": 0.001,
    "ci_upper": 0.027,
    "ci_excludes_zero": True,
    "prob_positive": 0.96,
    "gate4_pass": False,
    "fdr_q": 0.35,
    "gate5_pass": True,
    "worst_slice_name": "2020",
    "worst_slice_delta": 0.001,
    "all_slices_positive": True,
}


# ---------------------------------------------------------------------------
# validate_checklist_v2
# ---------------------------------------------------------------------------


def test_validate_full_pass():
    results = {"signals": {"coinvest_score_z": FULL_PASS_SIGNAL}}
    check = validate_checklist_v2(results, "coinvest_score_z")
    assert check.overall_pass is True
    assert check.n_passed == 5
    assert check.n_failed == 0
    assert len(check.gates) == 5
    assert all(g.passed for g in check.gates)


def test_validate_partial_fail():
    results = {"signals": {"insider_signal": PARTIAL_FAIL_SIGNAL}}
    check = validate_checklist_v2(results, "insider_signal")
    assert check.overall_pass is False
    assert check.n_passed == 3
    assert check.n_failed == 2
    # Gate 2 and Gate 4 should fail
    gate_ids_failed = [g.gate_id for g in check.gates if not g.passed]
    assert "gate2" in gate_ids_failed
    assert "gate4" in gate_ids_failed


def test_validate_missing_signal():
    results = {"signals": {"other": FULL_PASS_SIGNAL}}
    check = validate_checklist_v2(results, "missing_signal")
    assert check.overall_pass is False
    assert check.n_skipped == 5
    assert "No data found" in check.summary


def test_validate_missing_gates():
    """Signal with only gate1 data — other gates should be 'skipped'."""
    partial = {"gate1_pass": True, "selector_delta_pp": 1.0, "selector_tstat": 2.0}
    results = {"signals": {"partial_sig": partial}}
    check = validate_checklist_v2(results, "partial_sig")
    assert check.overall_pass is False
    assert check.n_passed == 1
    assert check.n_skipped == 4


def test_gate_names_complete():
    """All 5 gates have human-readable names."""
    assert len(GATE_NAMES) == 5
    for i in range(1, 6):
        assert f"gate{i}" in GATE_NAMES


# ---------------------------------------------------------------------------
# ChecklistResult serialization
# ---------------------------------------------------------------------------


def test_checklist_result_to_dict():
    results = {"signals": {"test_sig": FULL_PASS_SIGNAL}}
    check = validate_checklist_v2(results, "test_sig")
    d = check.to_dict()
    assert d["signal_name"] == "test_sig"
    assert d["overall_pass"] is True
    assert len(d["gates"]) == 5
    assert all(isinstance(g, dict) for g in d["gates"])
    assert d["gates"][0]["gate_id"] == "gate1"


# ---------------------------------------------------------------------------
# load_checklist_results
# ---------------------------------------------------------------------------


def test_load_checklist_results_found(tmp_path):
    data = {"signals": {"sig1": FULL_PASS_SIGNAL}}
    path = tmp_path / "checklist_v2_results.json"
    path.write_text(json.dumps(data))
    loaded = load_checklist_results(path)
    assert loaded is not None
    assert "signals" in loaded


def test_load_checklist_results_missing(tmp_path):
    path = tmp_path / "nonexistent.json"
    assert load_checklist_results(path) is None


# ---------------------------------------------------------------------------
# validate_promotion_packet
# ---------------------------------------------------------------------------


def test_validate_packet_with_checklist(tmp_path):
    """Packet with valid checklist passes."""
    packet_path = tmp_path / "PROMOTION_PACKET.json"
    packet_path.write_text(json.dumps({"version": 1}))

    checklist_path = tmp_path / "checklist_v2_results.json"
    checklist_path.write_text(json.dumps({"signals": {"sig1": FULL_PASS_SIGNAL}}))

    result = validate_promotion_packet(packet_path)
    assert result["valid"] is True


def test_validate_packet_missing_checklist(tmp_path):
    """Packet without checklist fails."""
    packet_path = tmp_path / "PROMOTION_PACKET.json"
    packet_path.write_text(json.dumps({"version": 1}))

    result = validate_promotion_packet(packet_path)
    assert result["valid"] is False
    assert "Missing" in result["reason"]


def test_validate_packet_with_failing_signal(tmp_path):
    """Packet with failing signal fails."""
    packet_path = tmp_path / "PROMOTION_PACKET.json"
    packet_path.write_text(json.dumps({"version": 1}))

    checklist_path = tmp_path / "checklist_v2_results.json"
    checklist_path.write_text(json.dumps({"signals": {"insider": PARTIAL_FAIL_SIGNAL}}))

    result = validate_promotion_packet(packet_path)
    assert result["valid"] is False
    assert result.get("failures")


def test_validate_packet_not_found(tmp_path):
    result = validate_promotion_packet(tmp_path / "missing.json")
    assert result["valid"] is False


# ---------------------------------------------------------------------------
# Gate failure reasons
# ---------------------------------------------------------------------------


def test_gate1_failure_reason():
    data = {"gate1_pass": False, "selector_tstat": 1.2, "selector_delta_pp": 0.5}
    results = {"signals": {"weak": data}}
    check = validate_checklist_v2(results, "weak")
    g1 = check.gates[0]
    assert not g1.passed
    assert "selector t-stat" in g1.reason


def test_gate2_failure_reason():
    data = {**FULL_PASS_SIGNAL, "gate2_pass": False, "incremental_nw_t": 1.50}
    results = {"signals": {"weak": data}}
    check = validate_checklist_v2(results, "weak")
    g2 = next(g for g in check.gates if g.gate_id == "gate2")
    assert not g2.passed
    assert "incremental NW-t" in g2.reason


def test_gate4_failure_reason():
    data = {**FULL_PASS_SIGNAL, "gate4_pass": False, "fdr_q": 0.35}
    results = {"signals": {"weak": data}}
    check = validate_checklist_v2(results, "weak")
    g4 = next(g for g in check.gates if g.gate_id == "gate4")
    assert not g4.passed
    assert "FDR q=" in g4.reason

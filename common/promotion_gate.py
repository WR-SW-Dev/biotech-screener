"""Promotion Checklist v2 — reusable gate for signal promotion.

Encodes the five-gate battery that every signal must pass before promotion:
  1. Signal card (selector delta, ranker IC)
  2. Fama-MacBeth incremental (NW-t >= 1.96 with controls)
  3. Block bootstrap (95% CI excludes zero)
  4. BH FDR (q < 0.10 within rerun family)
  5. LOSO robustness (worst-slice positive)

Can be called programmatically from promote_ruleset.py, CI workflows,
or research scripts. Does NOT run the actual statistical tests — it
validates a completed checklist result artifact.

Usage:
    from common.promotion_gate import validate_checklist_v2, load_checklist_results

    results = load_checklist_results(path)
    verdict = validate_checklist_v2(results, signal_name="coinvest_score_z")
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "promotion_gate.v1"

# Gate thresholds (Spec 055 standard)
GATE1_TSTAT_MIN = 1.64  # signal card selector t-stat
GATE2_NW_T_MIN = 1.96  # FM incremental Newey-West t-stat
GATE3_CI_EXCLUDES_ZERO = True  # bootstrap CI must exclude zero
GATE4_FDR_Q_MAX = 0.10  # BH FDR q-value threshold
GATE5_WORST_SLICE_POSITIVE = True  # LOSO worst slice must be positive

GATE_NAMES = {
    "gate1": "Signal Card (selector delta + ranker IC)",
    "gate2": "Fama-MacBeth Incremental (NW-t >= 1.96)",
    "gate3": "Block Bootstrap (95% CI excludes zero)",
    "gate4": "BH FDR (q < 0.10)",
    "gate5": "LOSO Robustness (worst-slice positive)",
}


@dataclass
class GateResult:
    """Result of a single gate evaluation."""

    gate_id: str
    gate_name: str
    passed: bool
    evidence: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass
class ChecklistResult:
    """Result of the full Checklist v2 evaluation."""

    signal_name: str
    schema: str = SCHEMA_VERSION
    gates: List[GateResult] = field(default_factory=list)
    overall_pass: bool = False
    n_passed: int = 0
    n_failed: int = 0
    n_skipped: int = 0
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "signal_name": self.signal_name,
            "overall_pass": self.overall_pass,
            "n_passed": self.n_passed,
            "n_failed": self.n_failed,
            "n_skipped": self.n_skipped,
            "summary": self.summary,
            "gates": [
                {
                    "gate_id": g.gate_id,
                    "gate_name": g.gate_name,
                    "passed": g.passed,
                    "evidence": g.evidence,
                    "reason": g.reason,
                }
                for g in self.gates
            ],
        }


def load_checklist_results(path: Path) -> Optional[Dict[str, Any]]:
    """Load a checklist_v2_results.json file."""
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def validate_checklist_v2(
    results: Dict[str, Any],
    signal_name: str,
) -> ChecklistResult:
    """Validate a completed checklist result against the v2 thresholds.

    Args:
        results: The full checklist output (from checklist_v2_rerun.py or equivalent).
                 Expected structure: {"signals": {"signal_name": {"gate1": {...}, ...}}}
        signal_name: Which signal to validate.

    Returns:
        ChecklistResult with per-gate verdicts and overall pass/fail.
    """
    checklist = ChecklistResult(signal_name=signal_name)

    # Extract signal data
    signals = results.get("signals", {})
    if signal_name not in signals:
        # Try top-level (some formats store per-signal at root)
        sig_data = results if results.get("gate1_pass") is not None else {}
    else:
        sig_data = signals[signal_name]

    if not sig_data:
        checklist.summary = f"No data found for signal '{signal_name}'"
        checklist.n_skipped = 5
        return checklist

    # Gate 1: Signal Card
    g1 = _check_gate1(sig_data)
    checklist.gates.append(g1)

    # Gate 2: FM Incremental
    g2 = _check_gate2(sig_data)
    checklist.gates.append(g2)

    # Gate 3: Bootstrap
    g3 = _check_gate3(sig_data)
    checklist.gates.append(g3)

    # Gate 4: FDR
    g4 = _check_gate4(sig_data)
    checklist.gates.append(g4)

    # Gate 5: LOSO
    g5 = _check_gate5(sig_data)
    checklist.gates.append(g5)

    # Tally
    checklist.n_passed = sum(1 for g in checklist.gates if g.passed)
    checklist.n_failed = sum(1 for g in checklist.gates if not g.passed and g.reason != "skipped")
    checklist.n_skipped = sum(1 for g in checklist.gates if g.reason == "skipped")
    checklist.overall_pass = checklist.n_failed == 0 and checklist.n_skipped == 0
    checklist.summary = (
        f"{signal_name}: {checklist.n_passed}/5 PASS, "
        f"{checklist.n_failed} FAIL, {checklist.n_skipped} SKIP → "
        f"{'PROMOTE' if checklist.overall_pass else 'BLOCK'}"
    )

    return checklist


def _check_gate1(data: Dict[str, Any]) -> GateResult:
    """Gate 1: Signal card — selector delta + t-stat."""
    passed = data.get("gate1_pass", False)
    evidence = {
        "selector_delta_pp": data.get("selector_delta_pp"),
        "selector_tstat": data.get("selector_tstat"),
        "ranker_ic": data.get("ranker_ic"),
        "n_periods": data.get("n_periods"),
    }
    reason = ""
    if not passed:
        t = data.get("selector_tstat") or 0
        if t < GATE1_TSTAT_MIN:
            reason = f"selector t-stat {t:.2f} < {GATE1_TSTAT_MIN}"
        elif (data.get("selector_delta_pp") or 0) <= 0:
            reason = "selector delta <= 0"
        else:
            reason = "gate1_pass=False in source data"
    return GateResult(gate_id="gate1", gate_name=GATE_NAMES["gate1"], passed=passed, evidence=evidence, reason=reason)


def _check_gate2(data: Dict[str, Any]) -> GateResult:
    """Gate 2: FM incremental — NW-t >= 1.96."""
    if "gate2_pass" not in data:
        return GateResult(gate_id="gate2", gate_name=GATE_NAMES["gate2"], passed=False, reason="skipped")
    passed = data.get("gate2_pass", False)
    evidence = {
        "incremental_nw_t": data.get("incremental_nw_t"),
        "incremental_verdict": data.get("incremental_verdict"),
        "univariate_nw_t": data.get("univariate_nw_t"),
    }
    reason = ""
    if not passed:
        t = data.get("incremental_nw_t") or 0
        reason = f"incremental NW-t {t:.2f} < {GATE2_NW_T_MIN}"
    return GateResult(gate_id="gate2", gate_name=GATE_NAMES["gate2"], passed=passed, evidence=evidence, reason=reason)


def _check_gate3(data: Dict[str, Any]) -> GateResult:
    """Gate 3: Block bootstrap — CI excludes zero."""
    if "gate3_pass" not in data:
        return GateResult(gate_id="gate3", gate_name=GATE_NAMES["gate3"], passed=False, reason="skipped")
    passed = data.get("gate3_pass", False)
    evidence = {
        "boot_mean": data.get("boot_mean"),
        "ci_lower": data.get("ci_lower"),
        "ci_upper": data.get("ci_upper"),
        "ci_excludes_zero": data.get("ci_excludes_zero"),
        "prob_positive": data.get("prob_positive"),
    }
    reason = ""
    if not passed:
        ci_low = data.get("ci_lower")
        reason = f"bootstrap CI includes zero (lower={ci_low})"
    return GateResult(gate_id="gate3", gate_name=GATE_NAMES["gate3"], passed=passed, evidence=evidence, reason=reason)


def _check_gate4(data: Dict[str, Any]) -> GateResult:
    """Gate 4: BH FDR — q < 0.10."""
    if "gate4_pass" not in data:
        return GateResult(gate_id="gate4", gate_name=GATE_NAMES["gate4"], passed=False, reason="skipped")
    passed = data.get("gate4_pass", False)
    evidence = {
        "fdr_q": data.get("fdr_q"),
    }
    reason = ""
    if not passed:
        q = data.get("fdr_q")
        reason = f"FDR q={q} >= {GATE4_FDR_Q_MAX}"
    return GateResult(gate_id="gate4", gate_name=GATE_NAMES["gate4"], passed=passed, evidence=evidence, reason=reason)


def _check_gate5(data: Dict[str, Any]) -> GateResult:
    """Gate 5: LOSO — worst-slice positive."""
    if "gate5_pass" not in data:
        return GateResult(gate_id="gate5", gate_name=GATE_NAMES["gate5"], passed=False, reason="skipped")
    passed = data.get("gate5_pass", False)
    evidence = {
        "worst_slice_name": data.get("worst_slice_name"),
        "worst_slice_delta": data.get("worst_slice_delta"),
        "all_slices_positive": data.get("all_slices_positive"),
    }
    reason = ""
    if not passed:
        worst = data.get("worst_slice_name", "?")
        delta = data.get("worst_slice_delta")
        reason = f"worst LOSO slice '{worst}' delta={delta}"
    return GateResult(gate_id="gate5", gate_name=GATE_NAMES["gate5"], passed=passed, evidence=evidence, reason=reason)


def validate_promotion_packet(packet_path: Path) -> Dict[str, Any]:
    """Validate that a promotion packet includes Checklist v2 results.

    Checks for the presence and validity of checklist_v2_results.json
    alongside the standard gate summary.

    Returns:
        {"valid": bool, "reason": str, "checklist_results": Optional[Dict]}
    """
    if not packet_path.exists():
        return {"valid": False, "reason": f"Packet not found: {packet_path}"}

    # Look for checklist results in the same directory
    packet_dir = packet_path.parent
    checklist_path = packet_dir / "checklist_v2_results.json"

    if not checklist_path.exists():
        return {
            "valid": False,
            "reason": "Missing checklist_v2_results.json in promotion packet directory",
            "checklist_path": str(checklist_path),
        }

    data = load_checklist_results(checklist_path)
    if not data:
        return {
            "valid": False,
            "reason": "Cannot parse checklist_v2_results.json",
        }

    # Check that signals in the packet have been evaluated
    signals = data.get("signals", {})
    if not signals:
        return {
            "valid": False,
            "reason": "No signals found in checklist_v2_results.json",
        }

    # Validate each signal
    failures = []
    for sig_name, sig_data in signals.items():
        result = validate_checklist_v2({"signals": {sig_name: sig_data}}, sig_name)
        if not result.overall_pass:
            failures.append(f"{sig_name}: {result.summary}")

    if failures:
        return {
            "valid": False,
            "reason": f"Checklist v2 failures: {'; '.join(failures)}",
            "failures": failures,
            "checklist_results": data,
        }

    return {
        "valid": True,
        "reason": "All signals pass Checklist v2",
        "checklist_results": data,
    }

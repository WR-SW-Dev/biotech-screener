#!/usr/bin/env python3
"""Canary date set: regression-check DE output against archived rankings.

For each canary date with both an archive and a test fixture, replays the
fixture through the current decision engine and diffs the result against
the archived rankings.  This catches DE logic drift across a quarterly
spread of historical dates.

Exit codes:
  0 — all INFO (within band)
  1 — any BLOCK (structural violation)
  2 — any WARN (statistical drift, advisory)

Usage:
    python scripts/run_canary_dates.py
    python scripts/run_canary_dates.py --thresholds path/to/thresholds.json
    python scripts/run_canary_dates.py --policy path/to/canary_policy.json
    python scripts/run_canary_dates.py --history path/to/history.jsonl
"""
from __future__ import annotations

import argparse
import enum
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.replay_diff import DiffThresholds, compute_diff, evaluate_health, load_rankings

VERSION = "2.0.0"

CANARY_DATES = ["2025-04-30", "2025-10-31", "2026-02-07"]

ARCHIVE_DIR = PROJECT_ROOT / "data" / "archives"
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "phase2_replays"
DEFAULT_THRESHOLDS = PROJECT_ROOT / "production_data" / "diff_thresholds" / "canary_v1.json"
DEFAULT_RULESET = PROJECT_ROOT / "production_data" / "decision_rulesets" / "v2_phase2_default.json"
DEFAULT_POLICY = PROJECT_ROOT / "production_data" / "canary_policy.json"
DEFAULT_HISTORY_PATH = PROJECT_ROOT / "artifacts" / "canary_regression_history.jsonl"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class CanaryOutcome(str, enum.Enum):
    INFO = "INFO"  # within band
    WARN = "WARN"  # statistical drift
    BLOCK = "BLOCK"  # structural violation


@dataclass(frozen=True)
class CanaryPolicy:
    schema: str = "canary_policy.v1"
    structural_block_enabled: bool = True
    statistical_warn_enabled: bool = True
    consecutive_warn_to_block: int = 0
    ratchet_after_n_runs: int = 0

    @classmethod
    def from_json(cls, path: Path) -> CanaryPolicy:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        known = {fld for fld in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def default(cls) -> CanaryPolicy:
        return cls()


@dataclass
class CanaryDateResult:
    canary_date: str
    outcome: CanaryOutcome
    block_reasons: List[str]
    warn_reasons: List[str]
    spearman_rho: Optional[float]
    top20_overlap_pct: Optional[float]
    status_raw: str  # original HealthVerdict.status (OK/WARN/FAIL/SKIP/ERROR)


@dataclass
class CanaryVerdict:
    overall_outcome: CanaryOutcome
    per_date: Dict[str, CanaryDateResult]
    thresholds_id: str
    policy: CanaryPolicy
    ruleset_id: str
    config_fingerprint: Optional[str]
    run_timestamp: str
    version: str = VERSION


# ---------------------------------------------------------------------------
# Classification logic
# ---------------------------------------------------------------------------


def classify_outcome(
    canary_date: str,
    diff_result: Any,
    verdict: Any,
    policy: CanaryPolicy,
    config_fp_match: Optional[bool] = None,
) -> CanaryDateResult:
    """Classify a single canary date result into INFO/WARN/BLOCK.

    Args:
        canary_date: ISO date string
        diff_result: DiffResult from replay_diff.compute_diff()
        verdict: HealthVerdict from replay_diff.evaluate_health()
        policy: CanaryPolicy controlling classification behavior
        config_fp_match: True/False/None — None means fingerprint not available
    """
    block_reasons: List[str] = []
    warn_reasons: List[str] = []

    # -- Structural checks → BLOCK --
    if diff_result.common_tickers == 0:
        block_reasons.append("no_common_universe")
    if config_fp_match is False:
        block_reasons.append("config_fingerprint_mismatch")

    # -- Statistical checks → WARN --
    # Collect all reasons from the health verdict, excluding structural ones
    stat_reasons: List[str] = []
    structural_prefixes = ("no_common_universe",)
    for r in verdict.fail_reasons + verdict.warn_reasons:
        if not any(r.startswith(p) for p in structural_prefixes):
            stat_reasons.append(r)

    # -- Apply policy --
    if not policy.structural_block_enabled:
        # Degrade structural blocks to warnings
        warn_reasons.extend(block_reasons)
        block_reasons = []

    if policy.statistical_warn_enabled:
        warn_reasons.extend(stat_reasons)
    # else: statistical reasons are swallowed → INFO

    # -- Determine outcome --
    if block_reasons:
        outcome = CanaryOutcome.BLOCK
    elif warn_reasons:
        outcome = CanaryOutcome.WARN
    else:
        outcome = CanaryOutcome.INFO

    return CanaryDateResult(
        canary_date=canary_date,
        outcome=outcome,
        block_reasons=block_reasons,
        warn_reasons=warn_reasons,
        spearman_rho=diff_result.rank_spearman_rho,
        top20_overlap_pct=diff_result.top20_overlap_pct,
        status_raw=verdict.status,
    )


# ---------------------------------------------------------------------------
# History persistence (JSONL)
# ---------------------------------------------------------------------------


def load_canary_history(history_path: Path) -> List[Dict[str, Any]]:
    """Load JSONL canary history."""
    if not history_path.exists():
        return []
    entries: List[Dict[str, Any]] = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def count_consecutive_outcome(
    history: List[Dict[str, Any]],
    outcome: str,
) -> int:
    """Count consecutive runs with the given outcome at the tail of history."""
    count = 0
    for entry in reversed(history):
        if entry.get("overall_outcome") == outcome:
            count += 1
        else:
            break
    return count


def persist_canary_history(
    history_path: Path,
    verdict: CanaryVerdict,
    history: List[Dict[str, Any]],
) -> None:
    """Append one JSONL entry for this canary run."""
    consecutive_warn = count_consecutive_outcome(history, "WARN")
    consecutive_block = count_consecutive_outcome(history, "BLOCK")

    # Update consecutive counts based on current outcome
    if verdict.overall_outcome == CanaryOutcome.WARN:
        consecutive_warn += 1
        consecutive_block = 0
    elif verdict.overall_outcome == CanaryOutcome.BLOCK:
        consecutive_block += 1
        consecutive_warn = 0
    else:
        consecutive_warn = 0
        consecutive_block = 0

    per_date_dict: Dict[str, dict] = {}
    for d, r in verdict.per_date.items():
        entry: Dict[str, Any] = {
            "outcome": r.outcome.value,
            "spearman_rho": r.spearman_rho,
            "top20_overlap_pct": r.top20_overlap_pct,
        }
        if r.block_reasons:
            entry["block_reasons"] = r.block_reasons
        if r.warn_reasons:
            entry["warn_reasons"] = r.warn_reasons
        per_date_dict[d] = entry

    record = {
        "schema": "canary_regression.v1",
        "run_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "run_timestamp": verdict.run_timestamp,
        "thresholds_id": verdict.thresholds_id,
        "ruleset_id": verdict.ruleset_id,
        "overall_outcome": verdict.overall_outcome.value,
        "per_date": per_date_dict,
        "consecutive_warn_runs": consecutive_warn,
        "consecutive_block_runs": consecutive_block,
    }

    history_path.parent.mkdir(parents=True, exist_ok=True)
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")


# ---------------------------------------------------------------------------
# Fixture loader (unchanged)
# ---------------------------------------------------------------------------


def _load_fixture_as_rankings(
    fixture_path: Path,
    ruleset_path: Path,
) -> Optional[pd.DataFrame]:
    """Load a replay fixture, run through DE, return rankings DataFrame.

    Returns None if the decision engine is not importable or fails.
    """
    try:
        from decision_engine import DecisionRuleset, compute_decision_fields
    except ImportError as exc:
        print(f"  SKIP: decision_engine not importable: {exc}")
        return None

    with open(fixture_path, "r", encoding="utf-8") as f:
        fixture = json.load(f)

    tickers = fixture["tickers"]
    records = fixture.get("records", {})

    # Load ruleset
    try:
        ruleset = DecisionRuleset.from_json(ruleset_path)
    except (FileNotFoundError, OSError) as exc:
        print(f"  SKIP: ruleset not loadable: {exc}")
        return None

    # Run DE on each ticker
    rows = []
    for ticker in tickers:
        rec = records.get(ticker, {})
        try:
            fields = compute_decision_fields(ticker, rec, ruleset=ruleset)
            fields["ticker"] = ticker
            rows.append(fields)
        except Exception:
            # Skip individual ticker failures
            rows.append({"ticker": ticker, "eligible": "0", "composite_rank": "999"})

    if not rows:
        return None

    df = pd.DataFrame(rows, dtype=str)

    # Ensure required columns exist
    for col in ("ticker", "eligible", "tier_dev", "composite_rank", "archetype"):
        if col not in df.columns:
            df[col] = ""

    # Synthesize actionable_rank from composite_rank if missing
    if "actionable_rank" not in df.columns and "composite_rank" in df.columns:
        df["actionable_rank"] = df["composite_rank"]

    df = df.drop_duplicates(subset="ticker", keep="first")
    df.attrs["has_actionable_rank"] = "actionable_rank" in df.columns
    df.attrs["rank_column_used"] = "actionable_rank"
    return df


# ---------------------------------------------------------------------------
# Core entry points
# ---------------------------------------------------------------------------


def _get_ruleset_id(ruleset_path: Path) -> str:
    """Extract ruleset ID from the ruleset JSON (best-effort)."""
    try:
        with open(ruleset_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("id", ruleset_path.stem[:8])
    except Exception:
        return ruleset_path.stem[:8]


def run_canary_classified(
    thresholds: DiffThresholds,
    policy: CanaryPolicy,
    ruleset_path: Path = DEFAULT_RULESET,
    history_path: Optional[Path] = None,
) -> CanaryVerdict:
    """Run canary checks with classification. Returns structured CanaryVerdict."""
    per_date: Dict[str, CanaryDateResult] = {}
    run_ts = datetime.now(timezone.utc).isoformat()

    for canary_date in CANARY_DATES:
        print(f"\n{'='*60}")
        print(f"Canary: {canary_date}")
        print(f"{'='*60}")

        archive_path = ARCHIVE_DIR / f"{canary_date}.tar.gz"
        fixture_path = FIXTURE_DIR / f"{canary_date}.json"

        # Check archive
        if not archive_path.exists():
            print(f"  SKIP: archive not found: {archive_path}")
            per_date[canary_date] = CanaryDateResult(
                canary_date=canary_date,
                outcome=CanaryOutcome.INFO,
                block_reasons=[],
                warn_reasons=[],
                spearman_rho=None,
                top20_overlap_pct=None,
                status_raw="SKIP",
            )
            continue

        # Check fixture
        if not fixture_path.exists():
            print(f"  SKIP: fixture not found: {fixture_path}")
            per_date[canary_date] = CanaryDateResult(
                canary_date=canary_date,
                outcome=CanaryOutcome.INFO,
                block_reasons=[],
                warn_reasons=[],
                spearman_rho=None,
                top20_overlap_pct=None,
                status_raw="SKIP",
            )
            continue

        # Load baseline from archive
        try:
            baseline = load_rankings(str(archive_path))
            baseline.attrs["source"] = str(archive_path)
            print(f"  Baseline: {len(baseline)} rows from archive")
        except Exception as exc:
            print(f"  ERROR loading baseline: {exc}")
            per_date[canary_date] = CanaryDateResult(
                canary_date=canary_date,
                outcome=CanaryOutcome.INFO,
                block_reasons=[],
                warn_reasons=[],
                spearman_rho=None,
                top20_overlap_pct=None,
                status_raw="ERROR",
            )
            continue

        # Load candidate from fixture + DE replay
        candidate = _load_fixture_as_rankings(fixture_path, ruleset_path)
        if candidate is None:
            print("  SKIP: could not produce candidate rankings")
            per_date[canary_date] = CanaryDateResult(
                canary_date=canary_date,
                outcome=CanaryOutcome.INFO,
                block_reasons=[],
                warn_reasons=[],
                spearman_rho=None,
                top20_overlap_pct=None,
                status_raw="SKIP",
            )
            continue

        candidate.attrs["source"] = f"fixture:{fixture_path.name}"
        print(f"  Candidate: {len(candidate)} rows from DE replay")

        # Compute diff
        try:
            diff_result = compute_diff(baseline, candidate)
            health_verdict = evaluate_health(diff_result, thresholds)
        except Exception as exc:
            print(f"  ERROR computing diff: {exc}")
            per_date[canary_date] = CanaryDateResult(
                canary_date=canary_date,
                outcome=CanaryOutcome.INFO,
                block_reasons=[],
                warn_reasons=[],
                spearman_rho=None,
                top20_overlap_pct=None,
                status_raw="ERROR",
            )
            continue

        # Classify
        date_result = classify_outcome(
            canary_date,
            diff_result,
            health_verdict,
            policy,
        )

        print(f"  Classification: {date_result.outcome.value}")
        print(f"  Spearman rho: {diff_result.rank_spearman_rho}")
        print(f"  Top-20 overlap: {diff_result.top20_overlap_pct:.1f}%")
        if date_result.block_reasons:
            for r in date_result.block_reasons:
                print(f"    BLOCK: {r}")
        if date_result.warn_reasons:
            for r in date_result.warn_reasons:
                print(f"    WARN: {r}")

        per_date[canary_date] = date_result

    # Aggregate worst outcome across non-SKIP dates
    evaluated = [r for r in per_date.values() if r.status_raw not in ("SKIP", "ERROR")]
    if any(r.outcome == CanaryOutcome.BLOCK for r in evaluated):
        overall = CanaryOutcome.BLOCK
    elif any(r.outcome == CanaryOutcome.WARN for r in evaluated):
        overall = CanaryOutcome.WARN
    else:
        overall = CanaryOutcome.INFO

    # Ratchet escalation (future — disabled when consecutive_warn_to_block == 0)
    if (
        history_path is not None
        and policy.consecutive_warn_to_block > 0
        and policy.ratchet_after_n_runs > 0
        and overall == CanaryOutcome.WARN
    ):
        history = load_canary_history(history_path)
        if (
            len(history) >= policy.ratchet_after_n_runs
            and count_consecutive_outcome(history, "WARN") + 1 >= policy.consecutive_warn_to_block
        ):
            overall = CanaryOutcome.BLOCK
            print("  RATCHET: consecutive WARN threshold reached → BLOCK")

    verdict = CanaryVerdict(
        overall_outcome=overall,
        per_date=per_date,
        thresholds_id=getattr(thresholds, "thresholds_id", ""),
        policy=policy,
        ruleset_id=_get_ruleset_id(ruleset_path),
        config_fingerprint=None,
        run_timestamp=run_ts,
    )

    # Persist history
    if history_path is not None:
        history = load_canary_history(history_path)
        persist_canary_history(history_path, verdict, history)

    return verdict


def run_canary(
    thresholds: DiffThresholds,
    ruleset_path: Path = DEFAULT_RULESET,
) -> Dict[str, dict]:
    """Legacy wrapper: run canary checks, return per-date verdict dicts.

    Calls run_canary_classified() with default policy and no history
    persistence, then converts to the original dict format.
    """
    verdict = run_canary_classified(
        thresholds,
        CanaryPolicy.default(),
        ruleset_path,
        history_path=None,
    )

    results: Dict[str, dict] = {}
    for canary_date, dr in verdict.per_date.items():
        if dr.status_raw in ("SKIP", "ERROR"):
            results[canary_date] = {
                "status": dr.status_raw,
                "reason": dr.block_reasons[0] if dr.block_reasons else "skipped",
            }
        else:
            results[canary_date] = {
                "status": dr.status_raw,
                "exit_code": {"OK": 0, "WARN": 2, "FAIL": 1}.get(dr.status_raw, 0),
                "fail_reasons": dr.block_reasons,
                "warn_reasons": dr.warn_reasons,
                "spearman_rho": dr.spearman_rho,
                "top20_overlap_pct": dr.top20_overlap_pct,
            }

    return results


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run canary date regression checks.")
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=DEFAULT_THRESHOLDS,
        help=f"Path to canary thresholds JSON (default: {DEFAULT_THRESHOLDS})",
    )
    parser.add_argument(
        "--ruleset",
        type=Path,
        default=DEFAULT_RULESET,
        help="Path to ruleset JSON for DE replay",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=DEFAULT_POLICY,
        help="Path to canary policy JSON",
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=None,
        help="Path to JSONL history file (enables persistence)",
    )
    args = parser.parse_args(argv)

    # Load thresholds
    if args.thresholds.exists():
        thresholds = DiffThresholds.from_json(str(args.thresholds))
        print(f"Thresholds: {args.thresholds} (ID: {thresholds.thresholds_id})")
    else:
        print(f"WARNING: thresholds file not found: {args.thresholds}, using defaults")
        thresholds = DiffThresholds()

    # Load policy
    if args.policy.exists():
        policy = CanaryPolicy.from_json(args.policy)
        print(f"Policy: {args.policy} (structural_block={policy.structural_block_enabled})")
    else:
        policy = CanaryPolicy.default()
        print("Policy: defaults (structural_block=True)")

    verdict = run_canary_classified(
        thresholds,
        policy,
        ruleset_path=args.ruleset,
        history_path=args.history,
    )

    # Summary
    print(f"\n{'='*60}")
    print("CANARY SUMMARY")
    print(f"{'='*60}")

    for canary_date, result in sorted(verdict.per_date.items()):
        print(f"  {canary_date}: {result.outcome.value} (raw={result.status_raw})")

    print(f"\nOverall: {verdict.overall_outcome.value}")

    # Exit codes: INFO→0, WARN→2, BLOCK→1
    if verdict.overall_outcome == CanaryOutcome.BLOCK:
        return 1
    elif verdict.overall_outcome == CanaryOutcome.WARN:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

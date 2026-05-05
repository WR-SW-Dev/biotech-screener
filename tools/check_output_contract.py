"""Daily-snapshot output-contract checker.

Read-only verification that a given snapshot date contains the full set of
artifacts the daily production pipeline is supposed to emit. Intended uses:

    1. Backstop cron (Stage B) — re-runs missing tail diagnostics when the
       wrapper-tail of cron_daily_production.sh failed to execute.
    2. Catch-up gate (Stage B) — replaces the directory-existence check in
       cron_evening_catchup.sh so partial snapshots are re-attempted.
    3. Manual audit — confirm a past snapshot is complete before quoting
       any of its numbers.

The checker makes NO API calls, runs NO producers, and writes NO files. It
inspects the snapshot directory and a small set of repo-relative ledger paths,
then prints a single JSON object to stdout and exits with one of three codes.

Usage:
    python tools/check_output_contract.py --as-of 2026-05-01
    python tools/check_output_contract.py --as-of 2026-05-01 --strict

Exit codes:
    0  PASS  — every required artifact present and non-empty
    2  WARN  — required artifacts present, optional ones missing (under
              --strict this becomes 1)
    1  FAIL  — at least one required artifact missing or empty, OR the
              snapshot directory itself does not exist
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_ROOT = REPO_ROOT / "data" / "snapshots"


REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "rankings.csv",
    "rankings.csv.sha256",
    "metadata.json",
    "inputs_manifest.json",
    "rank_change_alerts.json",
    "snapshot_integrity_report.json",
    "feature_coverage_report.json",
    "distribution_drift_report.json",
    "sentinel_ticker_report.json",
)

OPTIONAL_ARTIFACTS: tuple[str, ...] = (
    "ranker_shadow_comparison.json",
    "decision_portfolio.json",
    "decision_portfolio.csv",
    "decision_ruleset.json",
)


@dataclass
class ArtifactStatus:
    name: str
    status: str  # "OK" | "MISSING" | "EMPTY"
    size_bytes: int = 0


@dataclass
class ContractReport:
    as_of_date: str
    snapshot_dir: str
    snapshot_exists: bool
    required: List[ArtifactStatus] = field(default_factory=list)
    optional: List[ArtifactStatus] = field(default_factory=list)
    missing_required: List[str] = field(default_factory=list)
    missing_optional: List[str] = field(default_factory=list)
    overall: str = "FAIL"  # "PASS" | "WARN" | "FAIL"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "as_of_date": self.as_of_date,
            "snapshot_dir": self.snapshot_dir,
            "snapshot_exists": self.snapshot_exists,
            "required": [a.__dict__ for a in self.required],
            "optional": [a.__dict__ for a in self.optional],
            "missing_required": self.missing_required,
            "missing_optional": self.missing_optional,
            "overall": self.overall,
        }


def _check_artifact(snapshot_dir: Path, name: str) -> ArtifactStatus:
    p = snapshot_dir / name
    if not p.exists():
        return ArtifactStatus(name=name, status="MISSING", size_bytes=0)
    size = p.stat().st_size
    if size == 0:
        return ArtifactStatus(name=name, status="EMPTY", size_bytes=0)
    return ArtifactStatus(name=name, status="OK", size_bytes=size)


def check_contract(as_of_date: str, snapshot_root: Path = SNAPSHOT_ROOT) -> ContractReport:
    snap = snapshot_root / as_of_date
    report = ContractReport(
        as_of_date=as_of_date,
        snapshot_dir=str(snap),
        snapshot_exists=snap.is_dir(),
    )

    if not report.snapshot_exists:
        report.missing_required = list(REQUIRED_ARTIFACTS)
        report.missing_optional = list(OPTIONAL_ARTIFACTS)
        report.overall = "FAIL"
        return report

    for name in REQUIRED_ARTIFACTS:
        st = _check_artifact(snap, name)
        report.required.append(st)
        if st.status != "OK":
            report.missing_required.append(name)

    for name in OPTIONAL_ARTIFACTS:
        st = _check_artifact(snap, name)
        report.optional.append(st)
        if st.status != "OK":
            report.missing_optional.append(name)

    if report.missing_required:
        report.overall = "FAIL"
    elif report.missing_optional:
        report.overall = "WARN"
    else:
        report.overall = "PASS"

    return report


def _exit_code(report: ContractReport, strict: bool) -> int:
    if report.overall == "PASS":
        return 0
    if report.overall == "WARN":
        return 1 if strict else 2
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Snapshot output-contract checker (read-only).")
    parser.add_argument("--as-of", default=str(date.today()), help="Snapshot date (YYYY-MM-DD).")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Promote WARN to FAIL exit (use for catch-up gating).",
    )
    parser.add_argument(
        "--snapshot-root",
        default=str(SNAPSHOT_ROOT),
        help="Override snapshot root (for testing).",
    )
    args = parser.parse_args(argv)

    report = check_contract(args.as_of, snapshot_root=Path(args.snapshot_root))
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return _exit_code(report, strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())

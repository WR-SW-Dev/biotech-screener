"""Snapshot integrity verifier (Tier 1).

Read-only consumer of the manifests written alongside each daily snapshot.
Re-hashes rankings.csv and every dependency in inputs_manifest.json, compares
to recorded SHA-256s, and reports any drift.

This is NOT a replay tool — it does not re-run any pipeline step, makes no
API calls, and writes only to its own report files. Its job is to detect
whether the bytes on disk for a past snapshot still match what the pipeline
recorded at the time of that run.

Usage:
    python tools/verify_snapshot_integrity.py --as-of-date 2026-04-28
    python tools/verify_snapshot_integrity.py --as-of-date 2026-04-28 --strict

--strict turns WARN into FAIL (e.g. for CI gates).

Outputs:
    data/snapshots/{as_of_date}/snapshot_integrity_verification.json
    data/snapshots/{as_of_date}/snapshot_integrity_verification.md

Exit codes:
    0  PASS — every recorded hash matches; required inputs all present
    2  WARN — hashes match but one or more soft-warnings (git drift, optional
       input missing). Becomes 1 under --strict.
    1  FAIL — at least one hard failure: rankings hash mismatch, required dep
       missing, dep hash mismatch, or unparseable manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class CheckResult:
    name: str
    severity: str  # "PASS" | "WARN" | "FAIL"
    detail: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


def _sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _read_recorded_rankings_sha(sha_path: Path) -> Optional[str]:
    """rankings.csv.sha256 format: '<hex>  rankings.csv'."""
    if not sha_path.exists():
        return None
    text = sha_path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    return text.split()[0].strip().lower()


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _current_git_sha() -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def verify(as_of_date: str, snapshot_dir: Path) -> List[CheckResult]:
    results: List[CheckResult] = []

    # 1. Rankings.csv hash
    rankings_path = snapshot_dir / "rankings.csv"
    sha_path = snapshot_dir / "rankings.csv.sha256"
    if not rankings_path.exists():
        results.append(CheckResult("rankings_csv_present", "FAIL", "rankings.csv missing"))
        return results
    recorded = _read_recorded_rankings_sha(sha_path)
    actual = _sha256_file(rankings_path)
    if recorded is None:
        results.append(
            CheckResult(
                "rankings_csv_sha",
                "WARN",
                f"rankings.csv.sha256 missing or empty; actual={actual}",
            )
        )
    elif recorded.lower() == actual.lower():
        results.append(CheckResult("rankings_csv_sha", "PASS", f"sha256={actual}"))
    else:
        results.append(
            CheckResult(
                "rankings_csv_sha",
                "FAIL",
                f"hash mismatch: recorded={recorded}, actual={actual}",
            )
        )

    # 2. Inputs manifest — re-hash each dependency
    inputs_path = snapshot_dir / "inputs_manifest.json"
    if not inputs_path.exists():
        results.append(CheckResult("inputs_manifest", "FAIL", "inputs_manifest.json missing"))
        return results
    try:
        inputs = _load_json(inputs_path)
    except (json.JSONDecodeError, OSError) as e:
        results.append(CheckResult("inputs_manifest", "FAIL", f"unparseable inputs_manifest.json: {e}"))
        return results

    deps = inputs.get("dependencies", [])
    n_total = 0
    n_match = 0
    n_mismatch = 0
    n_required_missing = 0
    n_optional_missing = 0
    n_no_recorded_hash = 0
    mismatches: List[str] = []
    required_missing_keys: List[str] = []

    for dep in deps:
        n_total += 1
        key = dep.get("key", "?")
        path_str = dep.get("path") or ""
        path = Path(path_str)
        required = bool(dep.get("required", False))
        recorded_sha = (dep.get("sha256") or "").lower() or None
        if not path.exists():
            if required:
                n_required_missing += 1
                required_missing_keys.append(key)
            else:
                n_optional_missing += 1
            continue
        if recorded_sha is None:
            # File present but no recorded hash; nothing to compare
            n_no_recorded_hash += 1
            continue
        actual_sha = _sha256_file(path).lower()
        if actual_sha == recorded_sha:
            n_match += 1
        else:
            n_mismatch += 1
            mismatches.append(f"{key} (path={path}): recorded={recorded_sha}, actual={actual_sha}")

    if n_required_missing > 0:
        results.append(
            CheckResult(
                "required_inputs_present",
                "FAIL",
                f"{n_required_missing} required input(s) missing: {', '.join(required_missing_keys)}",
                extra={"missing": required_missing_keys},
            )
        )
    else:
        results.append(CheckResult("required_inputs_present", "PASS", "all required inputs present"))

    if n_optional_missing > 0:
        results.append(
            CheckResult(
                "optional_inputs_present",
                "WARN",
                f"{n_optional_missing} optional input(s) missing (non-blocking)",
            )
        )
    else:
        results.append(CheckResult("optional_inputs_present", "PASS", "all optional inputs present"))

    if n_mismatch > 0:
        results.append(
            CheckResult(
                "dep_hashes",
                "FAIL",
                f"{n_mismatch} dep hash mismatch(es); first: {mismatches[0]}",
                extra={
                    "n_total": n_total,
                    "n_match": n_match,
                    "n_mismatch": n_mismatch,
                    "mismatches": mismatches[:10],
                },
            )
        )
    else:
        results.append(
            CheckResult(
                "dep_hashes",
                "PASS",
                f"{n_match}/{n_total} deps verified, {n_no_recorded_hash} had no recorded hash",
                extra={
                    "n_total": n_total,
                    "n_match": n_match,
                    "n_no_recorded_hash": n_no_recorded_hash,
                },
            )
        )

    # 3. Run manifest — git block
    run_path = snapshot_dir / "run_manifest.json"
    if not run_path.exists():
        results.append(CheckResult("run_manifest", "WARN", "run_manifest.json missing — git check skipped"))
        return results
    try:
        run_manifest = _load_json(run_path)
    except (json.JSONDecodeError, OSError) as e:
        results.append(CheckResult("run_manifest", "FAIL", f"unparseable run_manifest.json: {e}"))
        return results

    recorded_git = (run_manifest.get("git") or {}).get("commit_sha")
    current_git = _current_git_sha()
    if recorded_git and current_git:
        if recorded_git == current_git:
            results.append(CheckResult("git_sha", "PASS", f"git sha matches: {current_git}"))
        else:
            results.append(
                CheckResult(
                    "git_sha",
                    "WARN",
                    f"git drift: recorded={recorded_git[:8]}..., current={current_git[:8]}... — code moved on after snapshot",
                )
            )
    elif recorded_git:
        results.append(CheckResult("git_sha", "WARN", "current git sha unavailable — comparison skipped"))
    else:
        results.append(CheckResult("git_sha", "WARN", "run_manifest has no git.commit_sha"))

    return results


def overall_severity(results: List[CheckResult]) -> str:
    if any(r.severity == "FAIL" for r in results):
        return "FAIL"
    if any(r.severity == "WARN" for r in results):
        return "WARN"
    return "PASS"


def write_outputs(
    snapshot_dir: Path,
    as_of_date: str,
    results: List[CheckResult],
    overall: str,
) -> None:
    json_out = {
        "schema": "snapshot_integrity_verification.v1",
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "checks": [asdict(r) for r in results],
    }
    (snapshot_dir / "snapshot_integrity_verification.json").write_text(json.dumps(json_out, indent=2), encoding="utf-8")

    md_lines = [
        f"# Snapshot integrity — {as_of_date}",
        "",
        f"**Overall:** {overall}",
        "",
        "| Check | Severity | Detail |",
        "|---|---|---|",
    ]
    for r in results:
        detail = r.detail.replace("|", "\\|")
        md_lines.append(f"| {r.name} | {r.severity} | {detail} |")
    md_lines += [
        "",
        f"_Generated by `tools/verify_snapshot_integrity.py` at {json_out['generated_at']}._",
        "",
    ]
    (snapshot_dir / "snapshot_integrity_verification.md").write_text("\n".join(md_lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat WARN as FAIL (exit 1 instead of 2)",
    )
    args = parser.parse_args()
    as_of = args.as_of_date

    snapshot_dir = REPO_ROOT / "data" / "snapshots" / as_of
    if not snapshot_dir.exists():
        print(f"ERROR: snapshot dir missing: {snapshot_dir}", file=sys.stderr)
        return 1

    results = verify(as_of, snapshot_dir)
    overall = overall_severity(results)
    write_outputs(snapshot_dir, as_of, results, overall)

    print(f"Snapshot integrity for {as_of}: {overall}")
    for r in results:
        print(f"  [{r.severity}] {r.name}: {r.detail}")

    if overall == "FAIL":
        return 1
    if overall == "WARN":
        return 1 if args.strict else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

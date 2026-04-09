#!/usr/bin/env python3
"""Promotion Battery — unified evidence packet for ruleset promotion.

Runs in order:
  1. Per-snapshot bucketed verdict (for each bucket)
  2. Weekly live-sim verdict (policy + global top-K)
  3. Difference audit summary

Outputs:
    {out_dir}/PROMOTION_PACKET.json
    {out_dir}/PROMOTION_PACKET.md

Usage:
    python3 scripts/research/run_promotion_battery.py \
        --candidate-root data/snapshots_reranked_v1100/ \
        --baseline-root data/snapshots_reranked_baseline/ \
        --date-manifest output/research/date_manifest.csv \
        --out-dir output/promotion_battery/
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from scripts.research.eval_by_bucket import ALL_BUCKETS
from scripts.research.promotion_weekly_gate import run_gate as run_weekly_gate
from scripts.research.run_bucketed_verdict import run_bucketed_verdict

SCHEMA_VERSION = "promotion_packet.v1"
DEFAULT_POLICY_PATH = PROJECT_ROOT / "production_data" / "portfolio_policy.json"
DEFAULT_PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"


def _read_date_manifest(path: Path) -> List[str]:
    """Read date manifest — CSV with 'date' column or one date per line."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    lines = text.splitlines()
    if "date" in lines[0].lower():
        dates = []
        for row in csv.DictReader(lines):
            for key in row:
                if key.strip().lower() == "date":
                    val = row[key].strip()
                    if val:
                        dates.append(val)
                    break
        return sorted(dates)
    return sorted(line.strip() for line in lines if line.strip())


def run_bucketed_verdicts(
    candidate_dir: Path,
    baseline_dir: Path,
    *,
    buckets: Optional[List[str]] = None,
    horizons: Optional[List[int]] = None,
    oos_cutoff: str = "2025-01-01",
    price_csv: Optional[Path] = None,
    top_k: int = 20,
    cost_bps: float = 30.0,
    metric_key: str = "mean_hedged_return",
) -> Dict[str, Dict]:
    """Run bucketed verdict for each bucket, catching per-bucket errors."""
    results: Dict[str, Dict] = {}
    for bucket in buckets or list(ALL_BUCKETS):
        try:
            results[bucket] = run_bucketed_verdict(
                candidate_dir=candidate_dir,
                baseline_dir=baseline_dir,
                bucket=bucket,
                horizons=horizons,
                oos_cutoff=oos_cutoff,
                price_csv=price_csv,
                top_k=top_k,
                cost_bps=cost_bps,
                metric_key=metric_key,
            )
        except Exception as exc:
            results[bucket] = {"verdict": "ERROR", "error": str(exc)}
    return results


def run_weekly_sim_verdict(
    baseline_root: Path,
    candidate_root: Path,
    policy_path: Optional[Path],
    price_csv: Optional[Path],
    date_manifest: Optional[Path],
    *,
    rebal_every: int = 1,
    cost_bps: float = 30.0,
    global_top_k: int = 20,
    buffer_ranks: int = 30,
) -> Dict[str, Any]:
    """Run weekly live-sim gate. Returns gate result dict."""
    if date_manifest is None:
        return {"error": "no date manifest provided", "verdict": "SKIP"}
    dates = _read_date_manifest(date_manifest)
    if len(dates) < 2:
        return {"error": f"need >= 2 dates, got {len(dates)}", "verdict": "SKIP"}
    return run_weekly_gate(
        baseline_root=baseline_root,
        candidate_root=candidate_root,
        policy_path=policy_path or DEFAULT_POLICY_PATH,
        price_csv=price_csv or DEFAULT_PRICE_CSV,
        dates=dates,
        rebal_every=rebal_every,
        cost_bps=cost_bps,
        global_top_k=global_top_k,
        buffer_ranks=buffer_ranks,
    )


MANIFEST_PATH = PROJECT_ROOT / "production_data" / "decision_rulesets" / "manifest.json"
DAILY_PRODUCTION_SCRIPT = PROJECT_ROOT / "tools" / "run_daily_production.py"

SMOKE_REQUIRED_FILES = ("rankings.csv", "metadata.json", "run_manifest.json")
SMOKE_PROVENANCE_KEYS = ("ruleset_id", "engine_version", "git_sha")


def _get_manifest_active_id(manifest_path: Path = MANIFEST_PATH) -> Optional[str]:
    """Return the active ruleset ID from the manifest, or None."""
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest.get("rulesets", []):
        if entry.get("status") == "active":
            return entry.get("id")
    return None


def check_smoke_snapshot(
    snapshot_date_dir: Path,
    expected_ruleset_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate that a smoke snapshot has required files and correct provenance.

    Returns dict with status, snapshot_ok, provenance_ok, detail.
    """
    result: Dict[str, Any] = {
        "status": "PASS",
        "snapshot_ok": True,
        "provenance_ok": True,
        "detail": "",
    }
    # Check required files
    missing = [f for f in SMOKE_REQUIRED_FILES if not (snapshot_date_dir / f).is_file()]
    if missing:
        result["status"] = "FAIL"
        result["snapshot_ok"] = False
        result["detail"] = f"Missing snapshot files: {', '.join(missing)}"
        return result

    # Check provenance in metadata.json
    try:
        meta = json.loads((snapshot_date_dir / "metadata.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        result["status"] = "FAIL"
        result["provenance_ok"] = False
        result["detail"] = f"metadata.json unreadable: {exc}"
        return result

    missing_keys = [k for k in SMOKE_PROVENANCE_KEYS if not meta.get(k)]
    if missing_keys:
        result["status"] = "FAIL"
        result["provenance_ok"] = False
        result["detail"] = f"Missing provenance keys: {', '.join(missing_keys)}"
        return result

    if expected_ruleset_id and meta.get("ruleset_id") != expected_ruleset_id:
        result["status"] = "FAIL"
        result["provenance_ok"] = False
        result["detail"] = f"ruleset_id mismatch: metadata={meta.get('ruleset_id')}, " f"expected={expected_ruleset_id}"
        return result

    result["detail"] = f"OK: ruleset_id={meta['ruleset_id']}, engine={meta['engine_version']}"
    return result


def run_post_promotion_smoke(
    as_of_date: str,
    *,
    expected_ruleset_id: Optional[str] = None,
    timeout_seconds: int = 600,
) -> Dict[str, Any]:
    """Run daily production in a temp workspace and verify snapshot provenance.

    Returns a dict suitable for inclusion in the promotion packet.
    """
    if expected_ruleset_id is None:
        expected_ruleset_id = _get_manifest_active_id()

    with tempfile.TemporaryDirectory(prefix="smoke_snap_") as snap_tmp:
        snap_dir = Path(snap_tmp)
        cmd = [
            sys.executable,
            str(DAILY_PRODUCTION_SCRIPT),
            "--as-of-date",
            as_of_date,
            "--snapshot-dir",
            str(snap_dir),
            "--skip-price-refresh",
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=str(PROJECT_ROOT),
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "FAIL",
                "exit_code": -1,
                "snapshot_ok": False,
                "provenance_ok": False,
                "detail": f"Smoke run timed out after {timeout_seconds}s",
            }

        exit_code = proc.returncode
        stdout_tail = "\n".join(proc.stdout.splitlines()[-200:]) if proc.stdout else ""
        stderr_tail = "\n".join(proc.stderr.splitlines()[-50:]) if proc.stderr else ""

        # Exit 0 (PASS) or 2 (WARN) are acceptable
        if exit_code not in (0, 2):
            return {
                "status": "FAIL",
                "exit_code": exit_code,
                "snapshot_ok": False,
                "provenance_ok": False,
                "detail": f"Daily production exited {exit_code}",
                "stdout_tail": stdout_tail,
                "stderr_tail": stderr_tail,
            }

        # Check snapshot was created
        snapshot_date_dir = snap_dir / as_of_date
        snap_check = check_smoke_snapshot(snapshot_date_dir, expected_ruleset_id)

        status = snap_check["status"]
        if status == "PASS" and exit_code == 2:
            status = "WARN"

        return {
            "status": status,
            "exit_code": exit_code,
            "snapshot_ok": snap_check["snapshot_ok"],
            "provenance_ok": snap_check["provenance_ok"],
            "detail": snap_check["detail"],
            "stdout_tail": stdout_tail,
        }


def compute_overall_verdict(
    bucket_verdicts: Dict[str, Dict],
    weekly_verdict: Dict[str, Any],
) -> str:
    """PASS if weekly PASS + all buckets PROMOTE; FAIL if weekly FAIL or any ARCHIVE."""
    weekly_v = weekly_verdict.get("verdict", "SKIP")
    bucket_vs = [v.get("verdict", "ERROR") for v in bucket_verdicts.values()]
    if weekly_v == "FAIL" or "ARCHIVE" in bucket_vs:
        return "FAIL"
    if weekly_v == "PASS" and all(v == "PROMOTE" for v in bucket_vs):
        return "PASS"
    return "NEEDS_MORE"


def build_packet(
    bucket_verdicts: Dict[str, Dict],
    weekly_verdict: Dict[str, Any],
    overall: str,
    *,
    candidate_id: Optional[str] = None,
    baseline_id: Optional[str] = None,
    smoke_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the full promotion packet dict."""
    bv_map = {bk: bv.get("verdict", "ERROR") for bk, bv in bucket_verdicts.items()}
    packet: Dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "overall_verdict": overall,
        "candidate_id": candidate_id,
        "baseline_id": baseline_id,
        "bucket_verdicts": bucket_verdicts,
        "weekly_verdict": weekly_verdict,
        "summary": {
            "buckets_total": len(bv_map),
            "buckets_promote": sum(1 for v in bv_map.values() if v == "PROMOTE"),
            "buckets_archive": sum(1 for v in bv_map.values() if v == "ARCHIVE"),
            "buckets_needs_more": sum(1 for v in bv_map.values() if v == "NEEDS_MORE"),
            "weekly": weekly_verdict.get("verdict", "SKIP"),
        },
    }
    if smoke_result is not None:
        smoke_status = smoke_result.get("status", "SKIP")
        packet["post_promotion_smoke"] = {
            "status": smoke_status,
            "smoke_ok": smoke_status in ("PASS", "WARN"),
            "exit_code": smoke_result.get("exit_code"),
            "snapshot_ok": smoke_result.get("snapshot_ok", False),
            "provenance_ok": smoke_result.get("provenance_ok", False),
            "detail": smoke_result.get("detail", ""),
        }
    return packet


def write_packet_json(packet: Dict[str, Any], out_path: Path) -> Path:
    """Write PROMOTION_PACKET.json."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(packet, f, indent=2, default=str)
    return out_path


def write_packet_md(packet: Dict[str, Any], out_path: Path) -> Path:
    """Write PROMOTION_PACKET.md."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    overall = packet["overall_verdict"]
    cand_id = packet.get("candidate_id") or "\u2014"
    base_id = packet.get("baseline_id") or "\u2014"
    summary = packet.get("summary", {})
    lines = [
        "# Promotion Battery",
        "",
        f"**Overall Verdict**: **{overall}**",
        f"**Candidate**: {cand_id} | **Baseline**: {base_id}",
        "",
        "## Per-Snapshot Bucketed Verdicts",
        "",
        "| Bucket | Verdict | Primary Delta (pp) | Guardrail Delta (pp) |",
        "|--------|---------|-------------------|---------------------|",
    ]
    for bk, bv in packet.get("bucket_verdicts", {}).items():
        verdict = bv.get("verdict", "ERROR")
        oos = bv.get("oos_delta", {})
        hs = sorted(oos.keys(), key=lambda x: int(x)) if oos else []
        pri = f"{oos[hs[-1]]:+.3f}" if hs else "\u2014"
        grd = f"{oos[hs[-2]]:+.3f}" if len(hs) >= 2 else "\u2014"
        lines.append(f"| {bk} | {verdict} | {pri} | {grd} |")
    lines.append("")
    # Weekly
    weekly = packet.get("weekly_verdict", {})
    weekly_v = weekly.get("verdict", "SKIP")
    lines.extend(["## Weekly Live-Sim Verdict", "", f"**Verdict**: **{weekly_v}**", ""])
    for mode_key, mode_label in (("policy", "Policy"), ("global", "Global Top-K")):
        mode_data = weekly.get(mode_key)
        if not mode_data:
            continue
        checks = mode_data.get("gate", {}).get("checks", [])
        lines.extend(
            [
                f"### {mode_label} Checks",
                "",
                "| Check | Threshold | Actual | Result |",
                "|-------|-----------|--------|--------|",
            ]
        )
        for c in checks:
            result_str = "PASS" if c["pass"] else "FAIL"
            lines.append(f"| {c['name']} | {c['threshold']} | {c['actual']} " f"| {result_str} |")
        lines.append("")
    # Smoke gate
    smoke = packet.get("post_promotion_smoke")
    if smoke:
        smoke_status = smoke.get("status", "SKIP")
        lines.extend(
            [
                "## Post-Promotion Smoke Gate",
                "",
                f"**Status**: **{smoke_status}**",
                f"- Exit code: {smoke.get('exit_code', '—')}",
                f"- Snapshot OK: {smoke.get('snapshot_ok', False)}",
                f"- Provenance OK: {smoke.get('provenance_ok', False)}",
                f"- Detail: {smoke.get('detail', '—')}",
                "",
            ]
        )

    # Audit
    wk_total = wk_pass = 0
    for mk in ("policy", "global"):
        for c in weekly.get(mk, {}).get("gate", {}).get("checks", []):
            wk_total += 1
            wk_pass += int(c.get("pass", False))
    lines.extend(
        [
            "## Difference Audit",
            "",
            f"- Buckets: {summary.get('buckets_promote', 0)} PROMOTE, "
            f"{summary.get('buckets_archive', 0)} ARCHIVE, "
            f"{summary.get('buckets_needs_more', 0)} NEEDS_MORE",
            f"- Weekly: {weekly_v} with {wk_pass} checks passed / {wk_total} total",
            "",
        ]
    )
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def run_promotion_battery(
    candidate_root: Path,
    baseline_root: Path,
    *,
    date_manifest: Optional[Path] = None,
    policy_path: Optional[Path] = None,
    price_csv: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    buckets: Optional[List[str]] = None,
    horizons: Optional[List[int]] = None,
    oos_cutoff: str = "2025-01-01",
    top_k: int = 20,
    cost_bps: float = 30.0,
    rebal_every: int = 1,
    global_top_k: int = 20,
    buffer_ranks: int = 30,
    candidate_id: Optional[str] = None,
    baseline_id: Optional[str] = None,
    metric_key: str = "mean_hedged_return",
    smoke_as_of_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Run full promotion battery and return the packet dict."""
    pcv = price_csv or DEFAULT_PRICE_CSV
    bv = run_bucketed_verdicts(
        candidate_dir=candidate_root,
        baseline_dir=baseline_root,
        buckets=buckets,
        horizons=horizons,
        oos_cutoff=oos_cutoff,
        price_csv=pcv,
        top_k=top_k,
        cost_bps=cost_bps,
        metric_key=metric_key,
    )
    wv = run_weekly_sim_verdict(
        baseline_root=baseline_root,
        candidate_root=candidate_root,
        policy_path=policy_path,
        price_csv=pcv,
        date_manifest=date_manifest,
        rebal_every=rebal_every,
        cost_bps=cost_bps,
        global_top_k=global_top_k,
        buffer_ranks=buffer_ranks,
    )

    # Post-promotion smoke gate
    smoke: Optional[Dict[str, Any]] = None
    if smoke_as_of_date:
        print(f"\n[Smoke] Running post-promotion smoke for {smoke_as_of_date} ...")
        smoke = run_post_promotion_smoke(
            smoke_as_of_date,
            expected_ruleset_id=candidate_id,
        )
        print(f"  Smoke: {smoke['status']} — {smoke.get('detail', '')}")

    overall = compute_overall_verdict(bv, wv)
    # Smoke FAIL downgrades the overall verdict
    if smoke and smoke.get("status") == "FAIL":
        overall = "FAIL"

    packet = build_packet(
        bv,
        wv,
        overall,
        candidate_id=candidate_id,
        baseline_id=baseline_id,
        smoke_result=smoke,
    )
    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        write_packet_json(packet, Path(out_dir) / "PROMOTION_PACKET.json")
        write_packet_md(packet, Path(out_dir) / "PROMOTION_PACKET.md")
    return packet


def main() -> None:
    p = argparse.ArgumentParser(description="Run full promotion evidence battery")
    p.add_argument("--candidate-root", type=Path, required=True)
    p.add_argument("--baseline-root", type=Path, required=True)
    p.add_argument(
        "--date-manifest", type=Path, default=None, help="Date manifest for weekly sim (CSV or one-per-line)"
    )
    p.add_argument("--policy", type=Path, default=None)
    p.add_argument("--price-csv", type=Path, default=None)
    p.add_argument("--out-dir", type=Path, default=PROJECT_ROOT / "output" / "promotion_battery")
    p.add_argument("--buckets", type=str, default=None, help="Comma-separated bucket names (default: all)")
    p.add_argument("--horizons", type=str, default="84,126")
    p.add_argument("--oos-cutoff", type=str, default="2025-01-01")
    p.add_argument("--top-k", type=int, default=20)
    p.add_argument("--cost-bps", type=float, default=30.0)
    p.add_argument("--rebal-every", type=int, default=1)
    p.add_argument("--global-top-k", type=int, default=20)
    p.add_argument("--buffer-ranks", type=int, default=30)
    p.add_argument("--candidate-id", type=str, default=None)
    p.add_argument("--baseline-id", type=str, default=None)
    p.add_argument("--metric-key", type=str, default="mean_hedged_return")
    p.add_argument(
        "--smoke-as-of-date",
        type=str,
        default=None,
        help="Run post-promotion smoke gate with this as-of-date (e.g. 2026-03-10)",
    )
    args = p.parse_args()

    horizons = [int(h.strip()) for h in args.horizons.split(",")]
    buckets = [b.strip() for b in args.buckets.split(",")] if args.buckets else None
    packet = run_promotion_battery(
        candidate_root=args.candidate_root,
        baseline_root=args.baseline_root,
        date_manifest=args.date_manifest,
        policy_path=args.policy,
        price_csv=args.price_csv,
        out_dir=args.out_dir,
        buckets=buckets,
        horizons=horizons,
        oos_cutoff=args.oos_cutoff,
        top_k=args.top_k,
        cost_bps=args.cost_bps,
        rebal_every=args.rebal_every,
        global_top_k=args.global_top_k,
        buffer_ranks=args.buffer_ranks,
        candidate_id=args.candidate_id,
        baseline_id=args.baseline_id,
        metric_key=args.metric_key,
        smoke_as_of_date=args.smoke_as_of_date,
    )
    s = packet["summary"]
    print(f"\nOverall verdict: {packet['overall_verdict']}")
    print(
        f"  Buckets: {s['buckets_promote']} PROMOTE, "
        f"{s['buckets_archive']} ARCHIVE, {s['buckets_needs_more']} NEEDS_MORE"
    )
    print(f"  Weekly: {s['weekly']}")
    print(f"  Output: {args.out_dir}")


if __name__ == "__main__":
    main()

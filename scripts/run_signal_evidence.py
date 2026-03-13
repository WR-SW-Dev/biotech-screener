#!/usr/bin/env python3
"""Signal Evidence Packet Harness.

Produces a governance-grade evidence packet comparing baseline vs candidate
rankings across a curated date manifest. Composes existing tools
(eval_forward_returns, rerank_snapshots) — no reimplementation.

Output schema: signal_evidence.v1
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))
sys.path.insert(0, str(PROJECT_DIR / "scripts" / "research"))

from eval_forward_returns import EvalSummary, evaluate
from outcome_provenance import get_git_sha

from governance.hashing import hash_file

SCHEMA_VERSION = "signal_evidence.v1"
DEFAULT_HORIZONS = [20, 63, 84]
DEFAULT_TOP_K = 20
DEFAULT_COST_BPS = 30
DEFAULT_BENCHMARK = "xbi"
MIN_COVERAGE_FRACTION = 0.50

# Recommendation thresholds (pp = percentage points)
PROMISING_HEDGED_PP = 0.20
GUARDRAIL_FLOOR_PP = -0.05
REJECT_FLOOR_PP = -0.05


# ---------------------------------------------------------------------------
# Date manifest loading
# ---------------------------------------------------------------------------


def load_date_manifest(path: Path) -> List[str]:
    """Load date manifest from a text file or CSV with a ``date`` column.

    Returns sorted list of YYYY-MM-DD strings.  Fails if the file is missing,
    empty, or contains no parseable dates.
    """
    if not path.exists():
        raise FileNotFoundError(f"Date manifest not found: {path}")

    text = path.read_text().strip()
    if not text:
        raise ValueError(f"Date manifest is empty: {path}")

    lines = text.splitlines()

    # Detect CSV with header containing "date"
    if "," in lines[0] and "date" in lines[0].lower():
        reader = csv.DictReader(lines)
        # normalise header names
        date_col = None
        for col in reader.fieldnames or []:
            if col.strip().lower() == "date":
                date_col = col
                break
        if date_col is None:
            raise ValueError(f"CSV manifest has no 'date' column: {path}")
        dates = [row[date_col].strip() for row in reader if row[date_col].strip()]
    else:
        dates = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]

    if not dates:
        raise ValueError(f"Date manifest contains no dates: {path}")

    # Validate format
    for d in dates:
        try:
            datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Invalid date in manifest: {d!r}")

    return sorted(set(dates))


# ---------------------------------------------------------------------------
# PIT validation
# ---------------------------------------------------------------------------


def _validate_pit(snapshot_root: Path, dates: List[str]) -> Tuple[bool, List[Dict[str, str]]]:
    """Check metadata.json as_of_date matches snapshot directory date.

    Returns (all_ok, list_of_mismatch_dicts).
    """
    mismatches: List[Dict[str, str]] = []
    for d in dates:
        meta_path = snapshot_root / d / "metadata.json"
        if not meta_path.exists():
            continue  # skip missing — handled elsewhere
        try:
            meta = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            mismatches.append({"date": d, "detail": "metadata.json unreadable"})
            continue
        as_of = meta.get("as_of_date", "")
        if as_of and as_of != d:
            mismatches.append(
                {
                    "date": d,
                    "detail": f"as_of_date={as_of} != snapshot_dir={d}",
                }
            )
    return len(mismatches) == 0, mismatches


# ---------------------------------------------------------------------------
# Recommendation logic
# ---------------------------------------------------------------------------


def compute_recommendation(
    delta_by_horizon: Dict[int, Dict[str, Any]],
    horizons: List[int],
    coverage_fraction: float,
) -> Tuple[str, str]:
    """Apply promotion battery thresholds to produce a recommendation.

    Returns (recommendation, detail_string).
    """
    if coverage_fraction < MIN_COVERAGE_FRACTION:
        return "NEEDS_MORE", (f"Coverage {coverage_fraction:.0%} below minimum {MIN_COVERAGE_FRACTION:.0%}")

    primary_horizon = max(horizons)
    primary = delta_by_horizon.get(primary_horizon, {})
    primary_hedged = primary.get("hedged_pp", 0.0) or 0.0

    # Check reject first
    if primary_hedged < REJECT_FLOOR_PP:
        return "REJECT", (
            f"Primary horizon {primary_horizon}d delta hedged {primary_hedged:+.2f}pp "
            f"< {REJECT_FLOOR_PP:+.2f}pp floor"
        )

    # Check guardrails on all horizons
    guardrail_violations = []
    for h in horizons:
        h_delta = delta_by_horizon.get(h, {})
        h_hedged = h_delta.get("hedged_pp", 0.0) or 0.0
        if h_hedged < GUARDRAIL_FLOOR_PP:
            guardrail_violations.append(f"{h}d={h_hedged:+.2f}pp")

    # Check promising
    if primary_hedged >= PROMISING_HEDGED_PP and not guardrail_violations:
        return "PROMISING", (
            f"Primary horizon {primary_horizon}d delta hedged {primary_hedged:+.2f}pp "
            f">= {PROMISING_HEDGED_PP:+.2f}pp with no guardrail violations"
        )

    # NEEDS_MORE
    parts = [f"Primary horizon {primary_horizon}d delta hedged {primary_hedged:+.2f}pp"]
    if guardrail_violations:
        parts.append(f"guardrail violations: {', '.join(guardrail_violations)}")
    if primary_hedged < PROMISING_HEDGED_PP:
        parts.append(f"below {PROMISING_HEDGED_PP:+.2f}pp threshold")
    return "NEEDS_MORE", "; ".join(parts)


# ---------------------------------------------------------------------------
# Delta computation
# ---------------------------------------------------------------------------


def _safe_delta(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return round(a - b, 6)


def compute_deltas(
    baseline: EvalSummary,
    candidate: EvalSummary,
    horizons: List[int],
) -> Dict[int, Dict[str, Any]]:
    """Compute per-horizon ablation deltas (candidate - baseline)."""
    result = {}
    for h in horizons:
        bh = baseline.by_horizon.get(h, {})
        ch = candidate.by_horizon.get(h, {})
        result[h] = {
            "ic": _safe_delta(ch.get("mean_ic"), bh.get("mean_ic")),
            "hedged_pp": _safe_delta(ch.get("mean_hedged_return"), bh.get("mean_hedged_return")),
            "net_pp": _safe_delta(ch.get("mean_net_return"), bh.get("mean_net_return")),
            "turnover": _safe_delta(ch.get("mean_turnover"), bh.get("mean_turnover")),
            "excess_pp": _safe_delta(ch.get("mean_excess_return"), bh.get("mean_excess_return")),
        }
    return result


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


def compute_coverage(
    manifest_dates: List[str],
    baseline_skips: List[Dict[str, str]],
    candidate_skips: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Compute coverage summary from skip lists."""
    base_skip_dates = {s["date"] for s in baseline_skips}
    cand_skip_dates = {s["date"] for s in candidate_skips}
    all_skipped = base_skip_dates | cand_skip_dates

    base_evaluated = set(manifest_dates) - base_skip_dates
    cand_evaluated = set(manifest_dates) - cand_skip_dates
    both_evaluated = base_evaluated & cand_evaluated

    skipped_details = []
    for d in sorted(all_skipped):
        detail: Dict[str, Any] = {"date": d}
        if d in base_skip_dates:
            match = next((s for s in baseline_skips if s["date"] == d), None)
            detail["baseline_reason"] = match["reason"] if match else "unknown"
        if d in cand_skip_dates:
            match = next((s for s in candidate_skips if s["date"] == d), None)
            detail["candidate_reason"] = match["reason"] if match else "unknown"
        skipped_details.append(detail)

    return {
        "manifest_dates": len(manifest_dates),
        "baseline_evaluated": len(base_evaluated),
        "candidate_evaluated": len(cand_evaluated),
        "both_evaluated": len(both_evaluated),
        "skipped_dates": skipped_details,
    }


# ---------------------------------------------------------------------------
# Registry fingerprint (optional — graceful fallback)
# ---------------------------------------------------------------------------


def _get_registry_fingerprint() -> str:
    try:
        from decision_engine_codes import registry_fingerprint

        return registry_fingerprint()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def build_evidence_provenance(
    baseline_id: str,
    candidate_id: str,
    date_manifest: Path,
    baseline_root: Path,
    candidate_root: Path,
    price_csv: Path,
) -> Dict[str, Any]:
    """Build provenance block for the evidence packet."""
    return {
        "code_version": get_git_sha(),
        "baseline_id": baseline_id,
        "candidate_id": candidate_id,
        "date_manifest": str(date_manifest),
        "date_manifest_sha256": hash_file(date_manifest),
        "baseline_root": str(baseline_root),
        "candidate_root": str(candidate_root),
        "price_csv_sha256": hash_file(price_csv) if price_csv.exists() else None,
        "registry_fingerprint": _get_registry_fingerprint(),
    }


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def render_markdown(packet: Dict[str, Any]) -> str:
    """Render human-readable summary from evidence packet."""
    lines = [
        "# Signal Evidence Report",
        "",
        f"**Generated**: {packet['generated_at']}",
        f"**Baseline**: `{packet['provenance']['baseline_id']}`",
        f"**Candidate**: `{packet['provenance']['candidate_id']}`",
        f"**Recommendation**: **{packet['recommendation']}**",
        "",
        f"> {packet['recommendation_detail']}",
        "",
        "## Coverage",
        "",
        f"- Manifest dates: {packet['coverage']['manifest_dates']}",
        f"- Baseline evaluated: {packet['coverage']['baseline_evaluated']}",
        f"- Candidate evaluated: {packet['coverage']['candidate_evaluated']}",
        f"- Both evaluated: {packet['coverage']['both_evaluated']}",
        "",
    ]

    if packet["coverage"]["skipped_dates"]:
        lines.append("### Skipped Dates")
        lines.append("")
        for s in packet["coverage"]["skipped_dates"]:
            parts = [s["date"]]
            if "baseline_reason" in s:
                parts.append(f"baseline: {s['baseline_reason']}")
            if "candidate_reason" in s:
                parts.append(f"candidate: {s['candidate_reason']}")
            lines.append(f"- {' | '.join(parts)}")
        lines.append("")

    lines.append("## Deltas (candidate - baseline)")
    lines.append("")
    lines.append("| Horizon | IC | Hedged (pp) | Net (pp) | Excess (pp) | Turnover |")
    lines.append("|--------:|---:|------------:|---------:|------------:|---------:|")

    for h_str, d in sorted(packet["delta"]["by_horizon"].items(), key=lambda x: int(x[0])):

        def _fmt(v: Optional[float]) -> str:
            return f"{v:+.4f}" if v is not None else "n/a"

        lines.append(
            f"| {h_str}d | {_fmt(d.get('ic'))} | {_fmt(d.get('hedged_pp'))} "
            f"| {_fmt(d.get('net_pp'))} | {_fmt(d.get('excess_pp'))} "
            f"| {_fmt(d.get('turnover'))} |"
        )

    lines.append("")
    lines.append("## PIT Validation")
    lines.append("")
    pit = packet["pit_validation"]
    lines.append(f"- Baseline OK: {pit['baseline_ok']}")
    lines.append(f"- Candidate OK: {pit['candidate_ok']}")
    if pit["mismatches"]:
        for m in pit["mismatches"]:
            lines.append(f"  - {m['source']}: {m['date']} — {m['detail']}")

    lines.append("")
    lines.append("## Config")
    lines.append("")
    for k, v in sorted(packet["config"].items()):
        lines.append(f"- {k}: {v}")

    lines.append("")
    lines.append("---")
    lines.append(f"*Schema: {packet['schema']} | Code: {packet['provenance']['code_version']}*")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core orchestrator
# ---------------------------------------------------------------------------


def run_evidence(
    baseline_root: Path,
    candidate_root: Path,
    date_manifest: Path,
    price_csv: Path,
    horizons: List[int],
    top_k: int,
    cost_bps: float,
    benchmark: str,
    candidate_id: str,
    baseline_id: str,
    out_dir: Path,
    rerank_spec: Optional[Path] = None,
    oos_cutoff: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the full evidence pipeline and return the packet dict.

    Steps:
      1. Load date manifest
      2. Optional rerank
      3. Evaluate baseline + candidate
      4. Compute deltas, coverage, PIT validation, recommendation
      5. Write outputs
    """
    # 1. Load manifest
    manifest_dates = load_date_manifest(date_manifest)

    # 2. Optional rerank
    if rerank_spec is not None:
        _run_rerank(rerank_spec, baseline_root, candidate_root, manifest_dates)

    # OOS filtering
    eval_dates: Optional[Set[str]] = set(manifest_dates)
    if oos_cutoff:
        eval_dates = {d for d in manifest_dates if d >= oos_cutoff}
        if not eval_dates:
            raise ValueError(f"No manifest dates >= OOS cutoff {oos_cutoff}")

    # 3. Evaluate baseline
    base_summary, base_results, base_skips = evaluate(
        snapshot_root=baseline_root,
        price_csv=price_csv,
        horizons=horizons,
        top_k=top_k,
        cost_bps=cost_bps,
        allowed_dates=eval_dates,
        benchmark=benchmark,
        anchor_mode="next_trading_day",
    )

    # 4. Evaluate candidate
    cand_summary, cand_results, cand_skips = evaluate(
        snapshot_root=candidate_root,
        price_csv=price_csv,
        horizons=horizons,
        top_k=top_k,
        cost_bps=cost_bps,
        allowed_dates=eval_dates,
        benchmark=benchmark,
        anchor_mode="next_trading_day",
    )

    # 5. Compute deltas
    delta_by_horizon = compute_deltas(base_summary, cand_summary, horizons)

    # 6. PIT validation
    base_pit_ok, base_pit_mismatches = _validate_pit(baseline_root, manifest_dates)
    cand_pit_ok, cand_pit_mismatches = _validate_pit(candidate_root, manifest_dates)
    all_pit_mismatches = [{"source": "baseline", **m} for m in base_pit_mismatches] + [
        {"source": "candidate", **m} for m in cand_pit_mismatches
    ]

    # 7. Coverage
    coverage = compute_coverage(manifest_dates, base_skips, cand_skips)

    # Coverage fraction for recommendation
    n_manifest = len(eval_dates) if eval_dates else len(manifest_dates)
    coverage_fraction = coverage["both_evaluated"] / n_manifest if n_manifest > 0 else 0.0

    # 8. Recommendation
    recommendation, rec_detail = compute_recommendation(
        delta_by_horizon,
        horizons,
        coverage_fraction,
    )

    # 9. Assemble packet
    packet: Dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "provenance": build_evidence_provenance(
            baseline_id=baseline_id,
            candidate_id=candidate_id,
            date_manifest=date_manifest,
            baseline_root=baseline_root,
            candidate_root=candidate_root,
            price_csv=price_csv,
        ),
        "config": {
            "horizons": horizons,
            "top_k": top_k,
            "cost_bps": cost_bps,
            "benchmark": benchmark,
            "oos_cutoff": oos_cutoff,
        },
        "baseline": base_summary.to_dict().get("by_horizon", {}),
        "candidate": cand_summary.to_dict().get("by_horizon", {}),
        "delta": {
            "by_horizon": {str(h): v for h, v in delta_by_horizon.items()},
        },
        "pit_validation": {
            "baseline_ok": base_pit_ok,
            "candidate_ok": cand_pit_ok,
            "mismatches": all_pit_mismatches,
        },
        "coverage": coverage,
        "recommendation": recommendation,
        "recommendation_detail": rec_detail,
    }

    # 10. Write outputs
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "signal_evidence.json"
    json_path.write_text(json.dumps(packet, indent=2, sort_keys=True, default=str) + "\n")

    md_path = out_dir / "signal_evidence.md"
    md_path.write_text(render_markdown(packet))

    return packet


def _run_rerank(
    rerank_spec: Path,
    baseline_root: Path,
    candidate_root: Path,
    manifest_dates: List[str],
) -> None:
    """Import and run rerank_snapshots.rerank() for each manifest date."""
    from rerank_snapshots import rerank

    from decision_engine import DecisionRuleset

    ruleset_data = json.loads(rerank_spec.read_text())
    ruleset = DecisionRuleset.from_dict(ruleset_data)

    for d in manifest_dates:
        src_dir = baseline_root / d
        dst_dir = candidate_root / d
        if not src_dir.exists():
            continue

        rankings_path = src_dir / "rankings.csv"
        if not rankings_path.exists():
            continue

        # Read baseline rankings
        with open(rankings_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Rerank
        reranked = rerank(rows, ruleset)

        # Write candidate
        dst_dir.mkdir(parents=True, exist_ok=True)
        if reranked:
            fieldnames = list(reranked[0].keys())
            with open(dst_dir / "rankings.csv", "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(reranked)

        # Copy metadata
        meta_src = src_dir / "metadata.json"
        if meta_src.exists():
            (dst_dir / "metadata.json").write_text(meta_src.read_text())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate signal evidence packet (baseline vs candidate).",
    )
    p.add_argument("--baseline-root", type=Path, required=True, help="Root directory of baseline snapshots")
    p.add_argument("--candidate-root", type=Path, required=True, help="Root directory of candidate snapshots")
    p.add_argument("--date-manifest", type=Path, required=True, help="Path to date manifest file")
    p.add_argument(
        "--price-csv",
        type=Path,
        default=PROJECT_DIR / "production_data" / "price_history.csv",
        help="Path to price_history.csv",
    )
    p.add_argument("--horizons", type=str, default="20,63,84", help="Comma-separated forward horizons")
    p.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    p.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS)
    p.add_argument("--benchmark", type=str, default=DEFAULT_BENCHMARK)
    p.add_argument("--candidate-id", type=str, required=True, help="Candidate ruleset ID")
    p.add_argument("--baseline-id", type=str, required=True, help="Baseline ruleset ID")
    p.add_argument("--out-dir", type=Path, required=True, help="Output directory for evidence packet")
    p.add_argument("--rerank-spec", type=Path, default=None, help="Optional path to ruleset JSON for auto-reranking")
    p.add_argument("--oos-cutoff", type=str, default=None, help="OOS cutoff date (YYYY-MM-DD)")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    horizons = [int(h.strip()) for h in args.horizons.split(",")]

    packet = run_evidence(
        baseline_root=args.baseline_root,
        candidate_root=args.candidate_root,
        date_manifest=args.date_manifest,
        price_csv=args.price_csv,
        horizons=horizons,
        top_k=args.top_k,
        cost_bps=args.cost_bps,
        benchmark=args.benchmark,
        candidate_id=args.candidate_id,
        baseline_id=args.baseline_id,
        out_dir=args.out_dir,
        rerank_spec=args.rerank_spec,
        oos_cutoff=args.oos_cutoff,
    )

    rec = packet["recommendation"]
    cov = packet["coverage"]
    print(f"Evidence packet written to {args.out_dir}/")
    print(f"  Recommendation: {rec}")
    print(f"  Coverage: {cov['both_evaluated']}/{cov['manifest_dates']} dates")
    print(f"  Detail: {packet['recommendation_detail']}")


if __name__ == "__main__":
    main()

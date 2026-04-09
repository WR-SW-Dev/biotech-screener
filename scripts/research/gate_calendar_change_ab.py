#!/usr/bin/env python3
"""A/B gate for calendar changes.

Compares baseline (current production calendar) vs candidate (proposed edit)
using weekly-rebalanced live-sim. Emits AB_RECEIPT.md/.json with pass/fail
verdict. Exit code: 0 = PASS or HYGIENE_OVERRIDE, 1 = FAIL, 2 = WARN.

Pass bars (same as eval_calendar_expansion_ab):
  - Cumulative hedged delta >= +0.20pp
  - Mean weekly hedged delta >= -0.05pp
  - Turnover increase <= +0.25pp

Hygiene override: if edit class is HYGIENE_ONLY and ordinary verdict is WARN
(or FAIL only on cumulative bar while guardrail + turnover pass), elevate to
HYGIENE_OVERRIDE instead of blocking.

Usage:
    python3 scripts/research/gate_calendar_change_ab.py \
        --snapshot-root data/snapshots_reranked_v1100 \
        --baseline-calendar production_data/pdufa_dates.json \
        --candidate-calendar /tmp/pdufa_dates_candidate.json \
        --out-dir output/research/calendar_ab_gate
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "research"))

from eval_calendar_expansion_ab import (
    PRICE_HISTORY_DEFAULT,
    aggregate,
    discover_dates,
    load_calendar,
    load_prices,
    run_arm,
    write_results_csv,
)
from live_shadow_portfolio import BUCKET_NAMES, load_policy

# ---------------------------------------------------------------------------
# Acceptance bars
# ---------------------------------------------------------------------------

CUM_HEDGED_DELTA_THRESHOLD = 0.0020  # +0.20pp
MEAN_HEDGED_DELTA_THRESHOLD = -0.0005  # -0.05pp
TURNOVER_DELTA_THRESHOLD = 0.0025  # +0.25pp

# Fields that affect ranking/signal if changed
_SIGNAL_FIELDS = frozenset(
    {
        "pdufa_date",
        "event_type",
        "source",
        "confidence",
        "program",
        "drug_name",
        "indication",
        "submission_type",
    }
)

# Fields that are metadata-only (safe to change without affecting signal)
_METADATA_FIELDS = frozenset(
    {
        "as_of_disclosed_at",
        "curated_disclosed_at",
        "source_url",
        "notes",
    }
)


# ---------------------------------------------------------------------------
# Edit classification
# ---------------------------------------------------------------------------


def _entry_key(entry: Dict[str, str]) -> str:
    """Canonical key for a calendar entry."""
    return f"{entry.get('ticker', '')}|{entry.get('pdufa_date', '')}|{entry.get('event_type', 'PDUFA')}"


def classify_calendar_edits(
    baseline: List[Dict[str, str]],
    candidate: List[Dict[str, str]],
    as_of_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare baseline vs candidate calendar and classify the edit set.

    Returns:
        {
            "edit_class": "HYGIENE_ONLY" | "SIGNAL_BEARING" | "MIXED",
            "n_added": int,
            "n_removed": int,
            "n_modified": int,
            "n_deduped": int,
            "changed_tickers": [{ticker, edit_type, is_past_dated, is_metadata_only, reason}, ...],
        }
    """
    base_by_key = {}
    base_key_counts: Dict[str, int] = {}
    for entry in baseline:
        k = _entry_key(entry)
        base_by_key[k] = entry
        base_key_counts[k] = base_key_counts.get(k, 0) + 1

    cand_by_key = {}
    cand_key_counts: Dict[str, int] = {}
    for entry in candidate:
        k = _entry_key(entry)
        cand_by_key[k] = entry
        cand_key_counts[k] = cand_key_counts.get(k, 0) + 1

    base_keys = set(base_by_key)
    cand_keys = set(cand_by_key)

    removed_keys = base_keys - cand_keys
    added_keys = cand_keys - base_keys
    common_keys = base_keys & cand_keys

    changed_tickers: List[Dict[str, Any]] = []
    has_signal_bearing = False
    has_hygiene = False
    n_modified = 0
    n_deduped = 0

    # Removed entries
    for k in sorted(removed_keys):
        entry = base_by_key[k]
        ticker = entry.get("ticker", "")
        pdufa = entry.get("pdufa_date", "")
        is_past = as_of_date is not None and pdufa < as_of_date
        is_dup = base_key_counts.get(k, 0) > 1

        if is_past:
            reason = "past-dated removal"
            has_hygiene = True
        elif is_dup:
            reason = "dedup removal"
            has_hygiene = True
            n_deduped += 1
        else:
            reason = "future event removal"
            has_signal_bearing = True

        changed_tickers.append(
            {
                "ticker": ticker,
                "pdufa_date": pdufa,
                "edit_type": "REMOVED",
                "is_past_dated": is_past,
                "is_metadata_only": False,
                "reason": reason,
            }
        )

    # Added entries
    for k in sorted(added_keys):
        entry = cand_by_key[k]
        ticker = entry.get("ticker", "")
        pdufa = entry.get("pdufa_date", "")
        has_signal_bearing = True
        changed_tickers.append(
            {
                "ticker": ticker,
                "pdufa_date": pdufa,
                "edit_type": "ADDED",
                "is_past_dated": False,
                "is_metadata_only": False,
                "reason": "new future event",
            }
        )

    # Modified entries (same key, different content)
    for k in sorted(common_keys):
        b = base_by_key[k]
        c = cand_by_key[k]
        diff_fields = set()
        for field in set(b) | set(c):
            if field.startswith("_"):
                continue
            if str(b.get(field, "")).strip() != str(c.get(field, "")).strip():
                diff_fields.add(field)

        if not diff_fields:
            continue

        n_modified += 1
        ticker = b.get("ticker", "")
        pdufa = b.get("pdufa_date", "")
        is_metadata = diff_fields.issubset(_METADATA_FIELDS)
        has_signal = bool(diff_fields & _SIGNAL_FIELDS)

        if is_metadata:
            reason = f"metadata-only change ({', '.join(sorted(diff_fields))})"
            has_hygiene = True
        elif has_signal:
            reason = f"signal field change ({', '.join(sorted(diff_fields & _SIGNAL_FIELDS))})"
            has_signal_bearing = True
        else:
            reason = f"field change ({', '.join(sorted(diff_fields))})"
            has_hygiene = True

        changed_tickers.append(
            {
                "ticker": ticker,
                "pdufa_date": pdufa,
                "edit_type": "MODIFIED",
                "is_past_dated": as_of_date is not None and pdufa < as_of_date,
                "is_metadata_only": is_metadata,
                "reason": reason,
            }
        )

    # Dedup count: entries that disappeared due to count reduction
    for k in sorted(base_keys & cand_keys):
        base_count = base_key_counts.get(k, 0)
        cand_count = cand_key_counts.get(k, 0)
        if cand_count < base_count:
            n_deduped += base_count - cand_count

    # Classify
    if has_signal_bearing and has_hygiene:
        edit_class = "MIXED"
    elif has_signal_bearing:
        edit_class = "SIGNAL_BEARING"
    elif has_hygiene:
        edit_class = "HYGIENE_ONLY"
    elif not changed_tickers:
        edit_class = "HYGIENE_ONLY"  # no changes = trivially hygiene
    else:
        edit_class = "HYGIENE_ONLY"

    return {
        "edit_class": edit_class,
        "n_added": len(added_keys),
        "n_removed": len(removed_keys),
        "n_modified": n_modified,
        "n_deduped": n_deduped,
        "changed_tickers": changed_tickers,
    }


# ---------------------------------------------------------------------------
# Hygiene override
# ---------------------------------------------------------------------------


def apply_hygiene_override(
    verdict_data: Dict[str, Any],
    edit_class: str,
) -> Dict[str, Any]:
    """Apply hygiene override policy to the verdict.

    Rules:
    - HYGIENE_ONLY + WARN → HYGIENE_OVERRIDE
    - HYGIENE_ONLY + FAIL (only cumulative fails, guardrail + turnover pass) → HYGIENE_OVERRIDE
    - Everything else: keep original verdict
    - PASS stays PASS (no override needed)

    Returns updated verdict_data with 'final_verdict' and 'override_applied' fields.
    """
    original = verdict_data["verdict"]
    override_applied = False
    override_reason = ""

    if edit_class == "HYGIENE_ONLY":
        guardrail_ok = verdict_data.get("mean_hedged_pass", False)
        turnover_ok = verdict_data.get("turnover_pass", False)

        if original == "WARN":
            override_applied = True
            override_reason = "HYGIENE_ONLY edit set + guardrail/turnover pass"
        elif original == "FAIL" and guardrail_ok and turnover_ok:
            # Only cumulative bar failed — safe to override for hygiene
            override_applied = True
            override_reason = "HYGIENE_ONLY edit set + only cumulative bar failed + guardrail/turnover pass"

    final_verdict = "HYGIENE_OVERRIDE" if override_applied else original

    return {
        **verdict_data,
        "final_verdict": final_verdict,
        "override_applied": override_applied,
        "override_reason": override_reason,
        "edit_class": edit_class,
    }


# ---------------------------------------------------------------------------
# Diagnostic block
# ---------------------------------------------------------------------------


def build_diagnostic_block(
    edit_info: Dict[str, Any],
    base_results: List[Dict[str, Any]],
    cand_results: List[Dict[str, Any]],
    base_agg: Dict[str, Any],
    cand_agg: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a deterministic diagnostic block explaining the delta.

    Returns dict with:
    - edit_classification, diff_summary, changed_tickers
    - bucket_attribution (per-bucket cumulative hedged delta)
    - top_contributing_periods (sorted by abs delta)
    - interpretation
    """
    # Diff summary
    diff_summary = {
        "n_added": edit_info["n_added"],
        "n_removed": edit_info["n_removed"],
        "n_modified": edit_info["n_modified"],
        "n_deduped": edit_info["n_deduped"],
    }

    # Bucket attribution
    bucket_attr: List[Dict[str, Any]] = []
    for b in BUCKET_NAMES:
        bk_base = base_agg.get(f"{b}_mean_hedged")
        bk_cand = cand_agg.get(f"{b}_mean_hedged")
        delta = _safe_delta(bk_cand, bk_base)
        bucket_attr.append({"bucket": b, "base": bk_base, "candidate": bk_cand, "delta": delta})

    # Top contributing periods (weeks with biggest absolute delta)
    top_periods: List[Dict[str, Any]] = []
    n_common = min(len(base_results), len(cand_results))
    for i in range(n_common):
        bh = base_results[i].get("hedged_return")
        ch = cand_results[i].get("hedged_return")
        if bh is not None and ch is not None:
            delta = ch - bh
            if abs(delta) > 1e-8:
                top_periods.append(
                    {
                        "entry_date": base_results[i].get("entry_date", ""),
                        "exit_date": base_results[i].get("exit_date", ""),
                        "base_hedged": round(bh, 6),
                        "cand_hedged": round(ch, 6),
                        "delta": round(delta, 6),
                    }
                )
    top_periods.sort(key=lambda x: -abs(x["delta"]))
    top_periods = top_periods[:10]

    # Interpretation
    all_past_dated = all(
        ct.get("is_past_dated", False) or ct.get("is_metadata_only", False) for ct in edit_info["changed_tickers"]
    )
    cum_delta = _safe_delta(cand_agg.get("cum_hedged"), base_agg.get("cum_hedged"))

    if not edit_info["changed_tickers"]:
        interpretation = "No calendar differences detected."
    elif all_past_dated and cum_delta is not None and abs(cum_delta) < 0.005:
        interpretation = "Loss appears consistent with removing stale inventory. " "No active signal change detected."
    elif all_past_dated:
        interpretation = (
            "Changes are limited to past-dated/metadata entries but show "
            "measurable delta, likely from indirect ranking effects."
        )
    elif edit_info["edit_class"] == "HYGIENE_ONLY":
        interpretation = (
            "Hygiene-only changes with indirect portfolio effects. "
            "Delta is noise from stale entry removal, not signal change."
        )
    elif edit_info["edit_class"] == "SIGNAL_BEARING":
        interpretation = (
            "Signal-bearing changes detected. Delta reflects actual " "regulatory calendar signal modification."
        )
    else:
        interpretation = (
            "Mixed edit set — contains both hygiene and signal-bearing changes. " "Delta attribution is ambiguous."
        )

    return {
        "edit_classification": edit_info["edit_class"],
        "diff_summary": diff_summary,
        "changed_tickers": edit_info["changed_tickers"],
        "bucket_attribution": bucket_attr,
        "top_contributing_periods": top_periods,
        "interpretation": interpretation,
    }


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def compute_verdict(
    base_agg: Dict[str, Any],
    cand_agg: Dict[str, Any],
    *,
    cum_threshold: float = CUM_HEDGED_DELTA_THRESHOLD,
    mean_threshold: float = MEAN_HEDGED_DELTA_THRESHOLD,
    turnover_threshold: float = TURNOVER_DELTA_THRESHOLD,
) -> Dict[str, Any]:
    """Compute pass/fail verdict from aggregated results."""
    cum_delta = _safe_delta(cand_agg.get("cum_hedged"), base_agg.get("cum_hedged"))
    mean_delta = _safe_delta(cand_agg.get("mean_hedged"), base_agg.get("mean_hedged"))
    turnover_delta = _safe_delta(cand_agg.get("mean_turnover"), base_agg.get("mean_turnover"))

    cum_pass = cum_delta is not None and cum_delta >= cum_threshold
    mean_pass = mean_delta is not None and mean_delta >= mean_threshold
    turnover_pass = turnover_delta is not None and turnover_delta <= turnover_threshold

    all_pass = cum_pass and mean_pass and turnover_pass

    # WARN: guardrail + turnover pass but cumulative doesn't clear
    if not all_pass and mean_pass and turnover_pass:
        verdict = "WARN"
    elif all_pass:
        verdict = "PASS"
    else:
        verdict = "FAIL"

    return {
        "verdict": verdict,
        "cum_hedged_delta": cum_delta,
        "cum_hedged_pass": cum_pass,
        "mean_hedged_delta": mean_delta,
        "mean_hedged_pass": mean_pass,
        "turnover_delta": turnover_delta,
        "turnover_pass": turnover_pass,
    }


def _safe_delta(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return a - b


def _fmt_pct(v: Optional[float], dp: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.{dp}f}%"


def _fmt_pp(v: Optional[float]) -> str:
    if v is None:
        return "—"
    d = v * 100
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.2f}pp"


# ---------------------------------------------------------------------------
# Receipt writer
# ---------------------------------------------------------------------------


def write_ab_receipt(
    verdict_data: Dict[str, Any],
    base_agg: Dict[str, Any],
    cand_agg: Dict[str, Any],
    baseline_n: int,
    candidate_n: int,
    n_periods: int,
    out_dir: Path,
    *,
    diagnostic: Optional[Dict[str, Any]] = None,
) -> Path:
    """Write AB_RECEIPT.md + .json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    v = verdict_data
    display_verdict = v.get("final_verdict", v["verdict"])

    lines = [
        "# Calendar Change A/B Receipt",
        "",
        f"**Verdict**: {display_verdict}",
        f"**Baseline calendar**: {baseline_n} entries",
        f"**Candidate calendar**: {candidate_n} entries",
        f"**Periods evaluated**: {n_periods}",
        "",
    ]

    # Override notice
    if v.get("override_applied"):
        lines.append(f"> **Hygiene Override**: {v.get('override_reason', '')}")
        lines.append(f"> Original A/B verdict was {v['verdict']}.")
        lines.append("")

    lines.extend(
        [
            "## Pass Bars",
            "",
            "| Criterion | Threshold | Actual | Status |",
            "|-----------|-----------|--------|--------|",
            f"| Cumulative hedged delta | >= +0.20pp | {_fmt_pp(v['cum_hedged_delta'])} "
            f"| {'PASS' if v['cum_hedged_pass'] else 'FAIL'} |",
            f"| Mean weekly hedged delta | >= -0.05pp | {_fmt_pp(v['mean_hedged_delta'])} "
            f"| {'PASS' if v['mean_hedged_pass'] else 'FAIL'} |",
            f"| Turnover increase | <= +0.25pp | {_fmt_pp(v['turnover_delta'])} "
            f"| {'PASS' if v['turnover_pass'] else 'FAIL'} |",
            "",
            "## Returns",
            "",
            "| Metric | Baseline | Candidate | Delta |",
            "|--------|----------|-----------|-------|",
            f"| Mean weekly hedged | {_fmt_pct(base_agg.get('mean_hedged'))} "
            f"| {_fmt_pct(cand_agg.get('mean_hedged'))} "
            f"| {_fmt_pp(v['mean_hedged_delta'])} |",
            f"| Cumulative hedged | {_fmt_pct(base_agg.get('cum_hedged'))} "
            f"| {_fmt_pct(cand_agg.get('cum_hedged'))} "
            f"| {_fmt_pp(v['cum_hedged_delta'])} |",
            f"| Mean turnover | {_fmt_pct(base_agg.get('mean_turnover'))} "
            f"| {_fmt_pct(cand_agg.get('mean_turnover'))} "
            f"| {_fmt_pp(v['turnover_delta'])} |",
            "",
        ]
    )

    # Bucket attribution
    lines.extend(["## Bucket Attribution (cumulative hedged)", ""])
    lines.append("| Bucket | Baseline | Candidate | Delta |")
    lines.append("|--------|----------|-----------|-------|")
    for b in BUCKET_NAMES:
        bk_base = base_agg.get(f"{b}_mean_hedged")
        bk_cand = cand_agg.get(f"{b}_mean_hedged")
        delta = _safe_delta(bk_cand, bk_base)
        lines.append(f"| {b} | {_fmt_pct(bk_base)} | {_fmt_pct(bk_cand)} | {_fmt_pp(delta)} |")
    lines.append("")

    # Diagnostic block
    if diagnostic:
        lines.extend(_render_diagnostic_md(diagnostic))

    # Verdict message
    if display_verdict == "PASS":
        lines.append("**PASS**: Candidate calendar meets all pass bars. Safe to promote.")
    elif display_verdict == "HYGIENE_OVERRIDE":
        lines.append(
            "**HYGIENE_OVERRIDE**: Edit set is hygiene-only. "
            f"Original A/B verdict was {v['verdict']} but override applied — "
            "safe to promote."
        )
    elif display_verdict == "WARN":
        lines.append(
            "**WARN**: Candidate does not hurt (guardrail + turnover OK) but "
            "cumulative hedged delta is below +0.20pp. Impact is limited."
        )
    else:
        failed = []
        if not v["mean_hedged_pass"]:
            failed.append("mean hedged guardrail")
        if not v["turnover_pass"]:
            failed.append("turnover")
        if not v["cum_hedged_pass"]:
            failed.append("cumulative hedged")
        lines.append(f"**FAIL**: Candidate fails {', '.join(failed)}. " "Do not promote this calendar change.")

    lines.extend(["", "---", "*Generated by gate_calendar_change_ab.py*"])

    md_path = out_dir / "AB_RECEIPT.md"
    md_path.write_text("\n".join(lines))

    json_data = {
        "schema": "calendar_change_ab_gate.v2",
        "verdict": display_verdict,
        "ab_verdict": v["verdict"],
        "override_applied": v.get("override_applied", False),
        "override_reason": v.get("override_reason", ""),
        "edit_class": v.get("edit_class", ""),
        "baseline_n": baseline_n,
        "candidate_n": candidate_n,
        "n_periods": n_periods,
        "bars": {
            "cum_hedged_delta": v["cum_hedged_delta"],
            "cum_hedged_pass": v["cum_hedged_pass"],
            "mean_hedged_delta": v["mean_hedged_delta"],
            "mean_hedged_pass": v["mean_hedged_pass"],
            "turnover_delta": v["turnover_delta"],
            "turnover_pass": v["turnover_pass"],
        },
        "base_agg": base_agg,
        "cand_agg": cand_agg,
    }
    if diagnostic:
        json_data["diagnostic"] = diagnostic

    json_path = out_dir / "AB_RECEIPT.json"
    with open(json_path, "w") as f:
        json.dump(json_data, f, indent=2, default=str)
        f.write("\n")

    return md_path


def _render_diagnostic_md(diag: Dict[str, Any]) -> List[str]:
    """Render the diagnostic block as markdown lines."""
    lines = ["## Diagnostic", ""]

    # Edit classification
    lines.append(f"**Edit classification**: {diag.get('edit_classification', '?')}")
    lines.append("")

    # Diff summary
    ds = diag.get("diff_summary", {})
    lines.append("**Diff summary**:")
    lines.append(
        f"  Added: {ds.get('n_added', 0)}, "
        f"Removed: {ds.get('n_removed', 0)}, "
        f"Modified: {ds.get('n_modified', 0)}, "
        f"Deduped: {ds.get('n_deduped', 0)}"
    )
    lines.append("")

    # Changed tickers
    ct = diag.get("changed_tickers", [])
    if ct:
        lines.append("**Changed tickers**:")
        lines.append("")
        lines.append("| Ticker | Date | Edit | Past-dated | Metadata-only | Reason |")
        lines.append("|--------|------|------|------------|---------------|--------|")
        for c in ct:
            pd = "yes" if c.get("is_past_dated") else "no"
            mo = "yes" if c.get("is_metadata_only") else "no"
            lines.append(
                f"| {c['ticker']} | {c.get('pdufa_date', '')} "
                f"| {c.get('edit_type', '')} | {pd} | {mo} | {c.get('reason', '')} |"
            )
        lines.append("")

    # Bucket attribution
    ba = diag.get("bucket_attribution", [])
    if ba:
        lines.append("**Bucket attribution (cumulative hedged delta)**:")
        lines.append("")
        lines.append("| Bucket | Delta |")
        lines.append("|--------|-------|")
        for b in ba:
            lines.append(f"| {b['bucket']} | {_fmt_pp(b.get('delta'))} |")
        lines.append("")

    # Top contributing periods
    tp = diag.get("top_contributing_periods", [])
    if tp:
        lines.append("**Top contributing periods**:")
        lines.append("")
        lines.append("| Entry | Exit | Base Hedged | Cand Hedged | Delta |")
        lines.append("|-------|------|------------|------------|-------|")
        for p in tp[:5]:
            lines.append(
                f"| {p['entry_date']} | {p['exit_date']} "
                f"| {_fmt_pct(p.get('base_hedged'))} "
                f"| {_fmt_pct(p.get('cand_hedged'))} "
                f"| {_fmt_pp(p.get('delta'))} |"
            )
        lines.append("")

    # Interpretation
    interp = diag.get("interpretation", "")
    if interp:
        lines.append(f"**Interpretation**: {interp}")
        lines.append("")

    return lines


# ---------------------------------------------------------------------------
# Gate runner
# ---------------------------------------------------------------------------


def run_calendar_ab_gate(
    snapshot_root: Path,
    baseline_calendar_path: Path,
    candidate_calendar_path: Path,
    policy_path: Path,
    price_csv: Path,
    out_dir: Path,
    *,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    cost_bps: float = 30.0,
) -> Tuple[str, Path]:
    """Run the full A/B gate. Returns (final_verdict, receipt_path)."""
    baseline_cal = load_calendar(baseline_calendar_path)
    candidate_cal = load_calendar(candidate_calendar_path)
    print(f"Baseline calendar: {len(baseline_cal)} entries")
    print(f"Candidate calendar: {len(candidate_cal)} entries")

    # Classify edits
    # Default as_of_date to today so past-dated detection works out of the box
    from datetime import date as _date

    as_of = date_from or _date.today().isoformat()
    edit_info = classify_calendar_edits(baseline_cal, candidate_cal, as_of_date=as_of)
    print(f"Edit class: {edit_info['edit_class']}")
    print(
        f"  Added: {edit_info['n_added']}, Removed: {edit_info['n_removed']}, "
        f"Modified: {edit_info['n_modified']}, Deduped: {edit_info['n_deduped']}"
    )

    dates = discover_dates(snapshot_root)
    if date_from:
        dates = [d for d in dates if d >= date_from]
    if date_to:
        dates = [d for d in dates if d <= date_to]
    print(f"Snapshot dates: {len(dates)}")

    if len(dates) < 2:
        print("ERROR: Need at least 2 snapshot dates.")
        sys.exit(1)

    print("Loading prices...")
    prices = load_prices(price_csv)
    print(f"  {len(prices)} tickers loaded")

    policy = load_policy(policy_path)

    print("\nRunning baseline arm...")
    base_results, _ = run_arm("baseline", snapshot_root, dates, prices, policy, baseline_cal, cost_bps)
    print(f"  {len(base_results)} periods")

    print("\nRunning candidate arm...")
    cand_results, _ = run_arm("candidate", snapshot_root, dates, prices, policy, candidate_cal, cost_bps)
    print(f"  {len(cand_results)} periods")

    # Write raw results
    all_results = base_results + cand_results
    csv_path = out_dir / "RESULTS.csv"
    write_results_csv(all_results, csv_path)

    base_agg = aggregate(base_results)
    cand_agg = aggregate(cand_results)

    # Compute verdict + override
    verdict_data = compute_verdict(base_agg, cand_agg)
    verdict_data = apply_hygiene_override(verdict_data, edit_info["edit_class"])

    # Build diagnostic
    diagnostic = build_diagnostic_block(edit_info, base_results, cand_results, base_agg, cand_agg)

    md_path = write_ab_receipt(
        verdict_data,
        base_agg,
        cand_agg,
        len(baseline_cal),
        len(candidate_cal),
        base_agg["n_periods"],
        out_dir,
        diagnostic=diagnostic,
    )

    final_verdict = verdict_data.get("final_verdict", verdict_data["verdict"])
    return final_verdict, md_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(description="A/B gate for calendar changes")
    p.add_argument("--snapshot-root", type=Path, required=True)
    p.add_argument(
        "--baseline-calendar",
        type=Path,
        default=PROJECT_ROOT / "production_data" / "pdufa_dates.json",
    )
    p.add_argument("--candidate-calendar", type=Path, required=True)
    p.add_argument(
        "--policy",
        type=Path,
        default=PROJECT_ROOT / "production_data" / "portfolio_policy.json",
    )
    p.add_argument("--price-csv", type=Path, default=PRICE_HISTORY_DEFAULT)
    p.add_argument("--date-from", type=str, default=None)
    p.add_argument("--date-to", type=str, default=None)
    p.add_argument("--cost-bps", type=float, default=30.0)
    p.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / "output" / "research" / "calendar_ab_gate",
    )
    args = p.parse_args()

    verdict, md_path = run_calendar_ab_gate(
        args.snapshot_root,
        args.baseline_calendar,
        args.candidate_calendar,
        args.policy,
        args.price_csv,
        args.out_dir,
        date_from=args.date_from,
        date_to=args.date_to,
        cost_bps=args.cost_bps,
    )

    print(f"\nReceipt: {md_path}")
    print(f"Verdict: {verdict}")

    if verdict in ("PASS", "HYGIENE_OVERRIDE"):
        sys.exit(0)
    elif verdict == "WARN":
        sys.exit(2)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()

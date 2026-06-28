#!/usr/bin/env python3
"""
weekly_validation_summary.py — DEM Top-30 EW weekly forward validation summary.

Reads captures.jsonl + fills.jsonl, computes non-overlapping 5d weekly windows,
and prints + writes WEEKLY_SUMMARY.md.

Usage:
    python3 tools/weekly_validation_summary.py
    python3 tools/weekly_validation_summary.py --since 2026-06-01
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date as ddate
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = REPO_ROOT / "artifacts" / "forward_validation"
CAPTURES_LEDGER = ARTIFACTS / "captures.jsonl"
FILLS_LEDGER = ARTIFACTS / "fills.jsonl"
SUMMARY_PATH = ARTIFACTS / "WEEKLY_SUMMARY.md"
CANDIDATE_FILE = ARTIFACTS / "CANDIDATE.json"


def week_key(date_str: str) -> str:
    d = ddate.fromisoformat(date_str)
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="DEM Top-30 EW weekly validation summary")
    parser.add_argument("--since", help="Only show windows from YYYY-MM-DD onward")
    args = parser.parse_args()

    captures = load_jsonl(CAPTURES_LEDGER)
    fills_list = load_jsonl(FILLS_LEDGER)

    if not captures:
        print("No captures found. Run run_forward_validation.py first.")
        return 1

    # Latest fill per capture_date (last entry wins)
    fills: dict[str, dict] = {}
    for f in fills_list:
        fills[f["capture_date"]] = f

    # Candidate info
    candidate = {}
    if CANDIDATE_FILE.exists():
        candidate = json.loads(CANDIDATE_FILE.read_text())

    # Non-overlapping weekly 5d windows: earliest capture per ISO week with completed 5d fill
    by_week: dict[str, dict] = {}
    for cap in sorted(captures, key=lambda c: c["date"]):
        date = cap["date"]
        if args.since and date < args.since:
            continue
        fill = fills.get(date, {})
        xs5 = fill.get("xs_5d")
        if xs5 is None:
            continue
        wk = week_key(date)
        if wk not in by_week:
            by_week[wk] = {
                "week": wk,
                "date": date,
                "basket_5d": fill.get("basket_5d"),
                "xbi_5d": fill.get("xbi_5d"),
                "xs_5d": xs5,
                "end_date": fill.get("end_date_5d"),
                "quality": cap.get("data_quality", "?"),
                "control_b30": fill.get("control_bottom30_5d"),
                "control_boot_pct": fill.get("control_bootstrap_pct_5d"),
            }

    rows = list(by_week.values())
    n = len(rows)

    if n == 0:
        print("No completed 5d windows yet.")
        return 0

    xs_vals = [r["xs_5d"] for r in rows]
    basket_vals = [r["basket_5d"] for r in rows if r["basket_5d"] is not None]
    xbi_vals = [r["xbi_5d"] for r in rows if r["xbi_5d"] is not None]

    mean_xs = sum(xs_vals) / n
    variance = sum((x - mean_xs) ** 2 for x in xs_vals) / max(n - 1, 1)
    std_xs = variance**0.5
    t_stat = mean_xs / (std_xs / n**0.5) if std_xs > 0 else 0.0
    hit_rate = sum(1 for x in xs_vals if x > 0) / n
    cum_xs = sum(xs_vals)
    cum_basket = sum(basket_vals)
    cum_xbi = sum(xbi_vals)

    # Gate status
    def gate_status(n_windows: int, required: int, label: str) -> str:
        if n_windows >= required:
            return f"[CLEARED] {label}"
        return f"[{n_windows}/{required}] {label}"

    gates = [
        gate_status(n, 20, "Directional proof (XS>0, hit>50%)"),
        gate_status(n, 40, "Strong evidence (t>1.5)"),
        gate_status(n, 52, "Investable evidence (t near 2.0)"),
    ]

    # Build markdown
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    lines = [
        "# DEM Top-30 EW — Weekly Forward Validation Summary",
        "",
        f"**Updated:** {now}  ",
        f"**Model hash:** `{candidate.get('model_hash', 'unknown')}`  ",
        f"**Ruleset:** `{candidate.get('ruleset_hash', 'unknown')}`  ",
        f"**Candidate registered:** {candidate.get('registered', 'unknown')}  ",
        "**Test:** Equal-weight Top-30 by `actionable_rank` vs XBI (5-day non-overlapping windows)  ",
        "",
        "---",
        "",
        "## Summary Statistics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Non-overlapping 5d windows | **{n}** |",
        f"| Mean weekly excess (basket − XBI) | **{mean_xs:+.3%}** |",
        f"| Std weekly excess | {std_xs:.3%} |",
        f"| t-stat | **{t_stat:.2f}** |",
        f"| Hit rate (excess > 0) | **{hit_rate:.0%}** |",
        f"| Cumulative excess | **{cum_xs:+.2%}** |",
        f"| Cumulative basket | {cum_basket:+.2%} |",
        f"| Cumulative XBI | {cum_xbi:+.2%} |",
        "",
        "## Gate Progress",
        "",
    ]
    for g in gates:
        lines.append(f"- {g}")

    lines += [
        "",
        "---",
        "",
        "## Weekly Detail",
        "",
        "| Week | Capture Date | Basket | XBI | Excess | Hit | Boot% | B30 | Quality |",
        "|------|-------------|--------|-----|--------|-----|-------|-----|---------|",
    ]

    cum = 0.0
    for r in rows:
        cum += r["xs_5d"]
        hit_sym = "+" if r["xs_5d"] > 0 else "-"
        boot_s = f"{r['control_boot_pct']:.0%}" if r["control_boot_pct"] is not None else "—"
        b30_s = f"{r['control_b30']:+.2%}" if r["control_b30"] is not None else "—"
        lines.append(
            f"| {r['week']} | {r['date']} | {r['basket_5d']:+.2%} | {r['xbi_5d']:+.2%} | "
            f"{r['xs_5d']:+.2%} | {hit_sym} | {boot_s} | {b30_s} | {r['quality']} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Adversarial Controls (once ≥20 windows)",
        "",
        f"Boot% = fraction of {1000}-sample random baskets the Top-30 EW beats in excess-vs-XBI.  ",
        "B30 = equal-weight bottom-30 basket return over the same window.  ",
        "",
        "| Control | Current average |",
        "|---------|----------------|",
    ]

    boot_vals = [r["control_boot_pct"] for r in rows if r["control_boot_pct"] is not None]
    b30_vals = [r["control_b30"] for r in rows if r["control_b30"] is not None]

    if boot_vals:
        avg_boot = sum(boot_vals) / len(boot_vals)
        lines.append(f"| Bootstrap percentile (avg) | {avg_boot:.0%} |")
    else:
        lines.append("| Bootstrap percentile (avg) | — (pending) |")

    if b30_vals:
        avg_b30 = sum(b30_vals) / len(b30_vals)
        lines.append(f"| Bottom-30 avg excess vs XBI | {avg_b30:+.2%} |")
    else:
        lines.append("| Bottom-30 avg excess vs XBI | — (pending) |")

    lines += [
        "",
        "---",
        "",
        "## Interpretation Notes",
        "",
        f"- t={t_stat:.2f} across {n} independent weekly periods.",
        "  One-tailed 95% threshold: ~1.65. Two-tailed 95%: 1.96.",
    ]

    if t_stat >= 1.96:
        lines.append("  **Two-tailed 95% cleared. Operator review of investability gate required.**")
    elif t_stat >= 1.65:
        lines.append("  One-tailed 95% cleared. Two-tailed gate not yet met.")
    else:
        lines.append("  Neither one- nor two-tailed threshold cleared. Accumulating evidence.")

    lines += [
        "",
        "- Do not promote EES, expectation-gap, or options-layer signals based on this record.",
        "- Do not reinterpret historical evidence as forward evidence.",
        "- A bad week is not refutation; a good week is not confirmation.",
        "- Investability requires explicit operator clearance at the 52-window gate.",
        "",
        "*Protocol: `docs/FORWARD_VALIDATION_PROTOCOL.md`*",
    ]

    summary_text = "\n".join(lines) + "\n"

    # Print to stdout
    print(summary_text)

    # Write to file
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(summary_text, encoding="utf-8")
    print(f"\nWritten: {SUMMARY_PATH}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())

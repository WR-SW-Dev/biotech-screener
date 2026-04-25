#!/usr/bin/env python3
"""diff_cohort_expansion_artifact.py — Tuesday-morning post-mortem on Saturday's manager additions.

Compares Monday's first organic cron-built snapshot against Saturday's manual
rebuild, to measure how much of the rank movement from the 4 new managers
(Fairmount/Vestal/Kynam/Soleus, added 2026-04-25) was cohort-expansion
artifact vs persistent signal.

Writes: artifacts/manager_cohort_expansion_2026_04_28.md

Designed to be run once on 2026-04-28 by cron_one_shot_2026_04_28.sh.

Usage (also runnable manually):
    python tools/diff_cohort_expansion_artifact.py \
        --saturday 2026-04-25 \
        --monday 2026-04-27
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SATURDAY_ENTRANTS = ["ABVX", "BCAX", "MIRM", "NBIX"]
SATURDAY_DROPOUTS = ["KYMR", "NAMS", "PTCT", "DYN"]
PHANTOM_DELTA_NAMES = ["ELVN", "GERN", "NRIX", "TYRA", "COGT"]

NEW_MANAGER_CIKS = {
    "0001802528": "Fairmount",
    "0001974915": "Vestal Point",
    "0001907884": "Kynam",
    "0001802630": "Soleus",
}


def safe_float(x):
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


def load_rankings(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def rank_by(rows: list[dict], col: str) -> dict:
    keyed = [(r["ticker"], safe_float(r.get(col, ""))) for r in rows]
    valid = sorted([(tk, v) for tk, v in keyed if v is not None], key=lambda x: -x[1])
    return {tk: (i + 1, v) for i, (tk, v) in enumerate(valid)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--saturday", default="2026-04-25", help="Saturday rebuild snapshot date")
    p.add_argument("--monday", default="2026-04-27", help="Monday's first organic cron snapshot date")
    p.add_argument(
        "--out", default=None, help="Output markdown path (default: artifacts/manager_cohort_expansion_<monday>.md)"
    )
    args = p.parse_args()

    sat_csv = REPO_ROOT / "data" / "snapshots" / args.saturday / "rankings.csv"
    mon_csv = REPO_ROOT / "data" / "snapshots" / args.monday / "rankings.csv"
    mon_manifest = REPO_ROOT / "data" / "snapshots" / args.monday / "run_manifest.json"

    if not sat_csv.exists():
        print(f"FATAL: Saturday snapshot missing at {sat_csv}", file=sys.stderr)
        return 2
    if not mon_csv.exists():
        print(f"FATAL: Monday snapshot missing at {mon_csv} — did the {args.monday} cron run?", file=sys.stderr)
        return 2

    sat_rows = load_rankings(sat_csv)
    mon_rows = load_rankings(mon_csv)

    # Quarantine context: read cohort_state.json from each snapshot if present
    def load_cohort_state(snap_date: str) -> dict | None:
        p = REPO_ROOT / "data" / "snapshots" / snap_date / "cohort_state.json"
        if not p.exists():
            return None
        try:
            return json.load(open(p))
        except (OSError, json.JSONDecodeError):
            return None

    sat_cohort = load_cohort_state(args.saturday)
    mon_cohort = load_cohort_state(args.monday)

    sat_rank = rank_by(sat_rows, "selector_score")
    mon_rank = rank_by(mon_rows, "selector_score")

    sat_top30 = {tk for tk, (rk, _) in sat_rank.items() if rk <= 30}
    mon_top30 = {tk for tk, (rk, _) in mon_rank.items() if rk <= 30}

    persisted = sorted(set(SATURDAY_ENTRANTS) & mon_top30)
    reverted = sorted(set(SATURDAY_ENTRANTS) - mon_top30)
    monday_new = sorted(mon_top30 - sat_top30)
    monday_dropped = sorted(sat_top30 - mon_top30)

    sat_id = {r["ticker"]: safe_float(r.get("inst_delta_z", "")) for r in sat_rows}
    mon_id = {r["ticker"]: safe_float(r.get("inst_delta_z", "")) for r in mon_rows}

    sat_co = {r["ticker"]: safe_float(r.get("coinvest_score_z", "")) for r in sat_rows}
    mon_co = {r["ticker"]: safe_float(r.get("coinvest_score_z", "")) for r in mon_rows}

    sec_13f_gate = None
    if mon_manifest.exists():
        try:
            mf = json.load(open(mon_manifest))
            for g in mf.get("gates", []):
                if g.get("name", "").lower() == "sec_13f_cache":
                    sec_13f_gate = g
                    break
        except (OSError, json.JSONDecodeError) as e:
            sec_13f_gate = {"error": str(e)}

    out_path = args.out or (REPO_ROOT / "artifacts" / f"manager_cohort_expansion_{args.monday}.md")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    a = lines.append
    a("# Manager-cohort expansion artifact analysis")
    a("")
    a(f"Generated: {date.today().isoformat()}")
    a(f"Saturday rebuild: {args.saturday} (38 → 42 managers, manual snapshot)")
    a(f"Monday organic:   {args.monday} (first cron-built snapshot post-expansion)")
    a("")
    a("## Quarantine state (from cohort_state.json)")
    a("")
    if sat_cohort:
        nm = sat_cohort.get("new_manager_names") or sat_cohort.get("new_manager_ciks") or []
        v = sat_cohort.get("validity", {})
        a(
            f"**Saturday {args.saturday}:** quarantined — institutional_cohort_changed={sat_cohort.get('institutional_cohort_changed')}"
        )
        a(f"  - new managers: {nm}")
        a(f"  - coinvest_score_z_valid: {v.get('coinvest_score_z_valid')}")
        a(f"  - inst_delta_z_valid: **{v.get('inst_delta_z_valid')}**")
        a(f"  - rank_delta_valid: **{v.get('rank_delta_valid')}**")
        if v.get("valid_from_snapshot"):
            a(f"  - valid_from_snapshot: {v.get('valid_from_snapshot')}")
    else:
        a(
            f"**Saturday {args.saturday}:** ⚠ no cohort_state.json found — was this snapshot built from a clean cohort, or was the marker not emitted?"
        )
    a("")
    if mon_cohort:
        nm = mon_cohort.get("new_manager_names") or mon_cohort.get("new_manager_ciks") or []
        v = mon_cohort.get("validity", {})
        a(
            f"**Monday {args.monday}:** ⚠ has cohort_state.json — institutional_cohort_changed={mon_cohort.get('institutional_cohort_changed')}"
        )
        a(f"  - new managers flagged: {nm}")
        a(f"  - inst_delta_z_valid: {v.get('inst_delta_z_valid')}, rank_delta_valid: {v.get('rank_delta_valid')}")
        a(
            "  - **Implication:** Monday is ALSO quarantined. Either a manager was added between Saturday and Monday, or run_screen.py is propagating cohort_pending.json into every fresh snapshot. Investigate before drawing any conclusions from this diff."
        )
    else:
        a(f"**Monday {args.monday}:** clean — no cohort_state.json, deltas vs Saturday are decision-grade.")
    a("")
    a("## sec_13f_cache gate (Monday)")
    if sec_13f_gate is None:
        a(f"  ⚠ run_manifest.json not found at {mon_manifest.relative_to(REPO_ROOT)}")
    elif "error" in sec_13f_gate:
        a(f"  ⚠ Could not parse manifest: {sec_13f_gate['error']}")
    else:
        a(f"  status: **{sec_13f_gate.get('status')}**")
        a(f"  detail: {sec_13f_gate.get('detail', '')}")
    a("")
    a("## Top-30 cohort changes")
    a("")
    a(f"Saturday top-30 entrants ({len(SATURDAY_ENTRANTS)}): {SATURDAY_ENTRANTS}")
    a(f"  - persisted into Monday top-30: {persisted}")
    a(f"  - reverted out of Monday top-30: {reverted}")
    a("")
    a("Monday top-30 vs Saturday top-30:")
    a(f"  - new on Monday (not in Saturday top-30): {monday_new}")
    a(f"  - dropped on Monday (was in Saturday top-30): {monday_dropped}")
    a(f"  - cohort overlap: {len(sat_top30 & mon_top30)}/30")
    a("")
    a("## inst_delta_z collapse on the 5 phantom-delta names")
    a("")
    a(
        "Saturday rebuild artificially inflated inst_delta_z because new managers' holdings looked like 'new institutional buys'. Monday's run uses Saturday as prior, so the artifact should collapse toward zero."
    )
    a("")
    a("| Ticker | Sat inst_delta_z | Mon inst_delta_z | Δ (collapse if negative) |")
    a("|---|---|---|---|")
    for tk in PHANTOM_DELTA_NAMES:
        s = sat_id.get(tk)
        m = mon_id.get(tk)
        if s is not None and m is not None:
            d = m - s
            a(f"| {tk} | {s:+.3f} | {m:+.3f} | {d:+.3f} |")
        else:
            a(f"| {tk} | {'?' if s is None else f'{s:+.3f}'} | {'?' if m is None else f'{m:+.3f}'} | — |")
    a("")
    a("## Coinvest_score_z impact for the 4 cohort entrants")
    a("")
    a("| Ticker | Sat coinvest_z | Mon coinvest_z | Δ |")
    a("|---|---|---|---|")
    for tk in SATURDAY_ENTRANTS:
        s = sat_co.get(tk)
        m = mon_co.get(tk)
        if s is not None and m is not None:
            d = m - s
            a(f"| {tk} | {s:+.3f} | {m:+.3f} | {d:+.3f} |")
        else:
            a(f"| {tk} | {'?' if s is None else f'{s:+.3f}'} | {'?' if m is None else f'{m:+.3f}'} | — |")
    a("")
    a("## Verdict")
    a("")
    if len(reverted) >= 3:
        a(
            f"⚠ **Cohort-expansion artifact dominated.** {len(reverted)}/4 Saturday entrants reverted on Monday — the rank movement was largely phantom inst_delta, not persistent signal."
        )
    elif len(persisted) >= 3:
        a(
            f"✓ **Persistent signal.** {len(persisted)}/4 Saturday entrants stayed in Monday's top-30. The new managers genuinely shifted the cohort."
        )
    else:
        a(f"~ **Mixed signal.** {len(persisted)}/4 Saturday entrants persisted. Worth manual review.")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

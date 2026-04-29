#!/usr/bin/env python3
"""Read-only audit: false clinical catalysts caused by CT.gov registry artifacts.

Goal
----
Find names currently receiving catalyst_near / build_window / binary_now credit
where the mapped CT.gov trial event is NOT a true binary alpha catalyst:
open-label extensions, long-term safety extensions, PK subtrials, expanded
access, observational/registry studies, etc.

Scope
-----
- Latest data/snapshots/YYYY-MM-DD/rankings.csv only
- production_data/trial_records.json
- Read-only. No model changes. No reruns. No new feeds.

Outputs
-------
- artifacts/audit/false_clinical_catalyst_audit_<date>.md
- artifacts/audit/false_clinical_catalyst_audit_<date>.json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SNAP_DIR = REPO / "data" / "snapshots"
TRIAL_RECORDS = REPO / "production_data" / "trial_records.json"
AUDIT_DIR = REPO / "artifacts" / "audit"

# CT.gov-sourced event types we audit. SEC-filed DATA_READOUT, PDUFA, ADCOM
# come from primary sources and are out of scope.
CTGOV_EVENT_TYPES = {"CT_PRIMARY_COMPLETION", "CT_STUDY_COMPLETION"}
CTGOV_SOURCES = {"CTGOV_CALENDAR", "CTGOV_PCD_FAR"}

# Title regex patterns by category (high-confidence false catalysts).
PATTERNS = [
    (
        "ole_or_long_term_extension",
        re.compile(
            r"\b(open[\s-]?label\s+extension|long[\s-]?term\s+(safety|extension)|"
            r"\bOLE\b|extension\s+(study|trial)|rollover\s+study)",
            re.IGNORECASE,
        ),
    ),
    (
        "pk_subtrial",
        re.compile(
            r"\b(PK\s+sub[\s-]?trial|pharmacokinetic[s]?\s+(sub[\s-]?study|sub[\s-]?trial)|"
            r"\bPK\s+(study|profile|profil)|pharmacokinetic\s+study|food\s+effect)",
            re.IGNORECASE,
        ),
    ),
    (
        "pediatric_pk_bridge",
        re.compile(
            r"\b(pediatric|paediatric|adolescent).{0,40}(PK|pharmacokinetic|bridge|bridging)",
            re.IGNORECASE,
        ),
    ),
    (
        "expanded_access_or_post_trial",
        re.compile(
            r"\b(expanded\s+access|post[\s-]?trial\s+access|compassionate\s+use|" r"managed\s+access|early\s+access)",
            re.IGNORECASE,
        ),
    ),
    (
        "observational_or_registry",
        re.compile(
            r"\b(observational|registry|natural\s+history|surveillance|real[\s-]?world|" r"non[\s-]?interventional)",
            re.IGNORECASE,
        ),
    ),
    (
        "post_marketing",
        re.compile(
            r"\b(post[\s-]?marketing|post[\s-]?approval|phase\s*4|phase\s*IV)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "healthy_volunteers_or_food_effect",
        re.compile(
            r"\b(healthy\s+(subjects|volunteers)|food[\s-]?effect|relative\s+bioavailability|"
            r"drug[\s-]?drug\s+interaction)",
            re.IGNORECASE,
        ),
    ),
]

# Study-type signals that are nearly always non-alpha
NON_ALPHA_STUDY_TYPES = {"EXPANDED_ACCESS", "OBSERVATIONAL"}

# Status signals: a COMPLETED trial whose primary completion is in the future
# (or whose results aren't yet posted) can still be alpha. But APPROVED_FOR_MARKETING
# / AVAILABLE means the drug has cleared regulatory review for that indication.
NON_ALPHA_STATUSES = {"APPROVED_FOR_MARKETING", "AVAILABLE", "WITHDRAWN", "TERMINATED"}


def latest_snapshot_dir() -> Path:
    candidates = sorted(
        p
        for p in SNAP_DIR.glob("2026-*")
        if p.is_dir() and not p.name.endswith(("backup", "morning_backup_1730")) and "__" not in p.name
    )
    if not candidates:
        raise SystemExit("No snapshot directories found")
    # last one with a real rankings.csv
    for p in reversed(candidates):
        if (p / "rankings.csv").exists():
            return p
    raise SystemExit("No snapshot with rankings.csv")


def load_trials() -> dict[str, list[dict]]:
    raw = json.loads(TRIAL_RECORDS.read_text())
    out: dict[str, list[dict]] = {}
    for r in raw:
        out.setdefault(r["ticker"], []).append(r)
    return out


def classify_trial(trial: dict) -> tuple[str, list[str]]:
    """Return (verdict, reasons). Verdict ∈ {'false','ambiguous','valid'}."""
    title = trial.get("title") or ""
    study_type = (trial.get("study_type") or "").upper()
    status = (trial.get("status") or "").upper()
    phase = (trial.get("phase") or "").upper()

    flags: list[str] = []

    if study_type in NON_ALPHA_STUDY_TYPES:
        flags.append(f"study_type={study_type}")
    if status in NON_ALPHA_STATUSES:
        flags.append(f"status={status}")
    for label, pat in PATTERNS:
        if pat.search(title):
            flags.append(f"title:{label}")

    # Phase/title sanity: "TERMINATED" is non-alpha forward, but we already flagged.
    # Phase 1 healthy-volunteer studies are non-alpha for the parent ticker.
    if phase == "PHASE1" and re.search(r"\b(healthy|food[\s-]?effect|PK)\b", title, re.IGNORECASE):
        flags.append("phase1_pk_healthy")

    if flags:
        return "false", flags

    # Ambiguous: phase missing, or N/A, or status not a forward-looking pivotal state
    if phase in ("", "N/A", "NA") and study_type == "INTERVENTIONAL":
        return "ambiguous", ["phase=N/A interventional"]
    if status in ("ACTIVE_NOT_RECRUITING", "RECRUITING", "ENROLLING_BY_INVITATION", "NOT_YET_RECRUITING"):
        # forward-looking — but title might still indicate non-alpha
        return "valid", []
    if status == "COMPLETED" and not flags:
        return "ambiguous", ["completed but no clear flag — verify readout pending"]
    return "ambiguous", [f"unclassified: phase={phase} status={status}"]


def find_catalyst_trials(ticker: str, catalyst_date_iso: str, trials: dict[str, list[dict]]) -> list[dict]:
    """Find trials for ticker whose primary_completion_date or completion_date
    matches catalyst_date_iso (within ±2 days to absorb minor drift)."""
    if not catalyst_date_iso:
        return []
    try:
        target = datetime.strptime(catalyst_date_iso, "%Y-%m-%d").date()
    except ValueError:
        return []
    out = []
    for t in trials.get(ticker, []):
        for key in ("primary_completion_date", "completion_date"):
            d = t.get(key)
            if not d:
                continue
            try:
                td = datetime.strptime(d, "%Y-%m-%d").date()
            except ValueError:
                continue
            if abs((td - target).days) <= 2:
                out.append(t)
                break
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshot", default=None, help="Override snapshot date (YYYY-MM-DD).")
    args = p.parse_args()

    snap = SNAP_DIR / args.snapshot if args.snapshot else latest_snapshot_dir()
    snap_date = snap.name
    rankings_path = snap / "rankings.csv"
    if not rankings_path.exists():
        raise SystemExit(f"No rankings.csv at {rankings_path}")

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    trials = load_trials()
    rows = list(csv.DictReader(open(rankings_path)))

    # Filter: catalyst-bucket-credited rows sourced from CT.gov.
    # Spec scope: "catalyst_near / build_window / binary_now". Use the bucket
    # field directly — `catalyst_in_window=1` is a narrower 30d flag and would
    # miss build_window names like KALV (62d out, still tier-A 'catalyst_near').
    SCOPE_BUCKETS = {"binary_now", "build_window"}
    candidates = [
        r
        for r in rows
        if r.get("catalyst_bucket") in SCOPE_BUCKETS
        and (r.get("catalyst_source") in CTGOV_SOURCES or r.get("catalyst_event_type") in CTGOV_EVENT_TYPES)
    ]

    findings = []
    for r in candidates:
        ticker = r["ticker"]
        cat_date = r.get("catalyst_date") or r.get("next_catalyst_date") or ""
        matches = find_catalyst_trials(ticker, cat_date, trials)
        if not matches:
            findings.append(
                {
                    "ticker": ticker,
                    "actionable_rank": _int(r.get("actionable_rank")),
                    "tier_any": r.get("tier_any"),
                    "tier_dev": r.get("tier_dev"),
                    "catalyst_date": cat_date,
                    "catalyst_days": _int(r.get("catalyst_days")),
                    "catalyst_bucket": r.get("catalyst_bucket"),
                    "catalyst_event_type": r.get("catalyst_event_type"),
                    "catalyst_source": r.get("catalyst_source"),
                    "lead_phase": r.get("lead_program_phase"),
                    "development_stage": r.get("development_stage"),
                    "matched_trials": [],
                    "verdict": "ambiguous",
                    "verdict_reasons": ["no trial in cache matched catalyst_date — investigate mapping"],
                }
            )
            continue

        # If multiple trials match the date, take the union of verdicts; if any
        # match looks like a real binary readout we keep verdict='valid'. But for
        # transparency we list them all.
        per_trial = []
        any_valid = False
        all_flags: list[str] = []
        for t in matches:
            v, flags = classify_trial(t)
            per_trial.append(
                {
                    "nct_id": t.get("nct_id"),
                    "title": t.get("title"),
                    "phase": t.get("phase"),
                    "status": t.get("status"),
                    "study_type": t.get("study_type"),
                    "primary_completion_date": t.get("primary_completion_date"),
                    "verdict": v,
                    "flags": flags,
                }
            )
            if v == "valid":
                any_valid = True
            all_flags.extend(flags)

        # Aggregate verdict
        if any_valid:
            agg_verdict = "valid"
        elif all(pt["verdict"] == "false" for pt in per_trial):
            agg_verdict = "false"
        else:
            agg_verdict = "ambiguous"

        findings.append(
            {
                "ticker": ticker,
                "actionable_rank": _int(r.get("actionable_rank")),
                "tier_any": r.get("tier_any"),
                "tier_dev": r.get("tier_dev"),
                "catalyst_date": cat_date,
                "catalyst_days": _int(r.get("catalyst_days")),
                "catalyst_bucket": r.get("catalyst_bucket"),
                "catalyst_event_type": r.get("catalyst_event_type"),
                "catalyst_source": r.get("catalyst_source"),
                "lead_phase": r.get("lead_program_phase"),
                "development_stage": r.get("development_stage"),
                "matched_trials": per_trial,
                "verdict": agg_verdict,
                "verdict_reasons": sorted(set(all_flags)),
            }
        )

    # Bucket by verdict
    high_confidence_false = [f for f in findings if f["verdict"] == "false"]
    ambiguous = [f for f in findings if f["verdict"] == "ambiguous"]
    likely_valid = [f for f in findings if f["verdict"] == "valid"]

    # KALV seed check — confirm its 2026-06-30 event maps to OLE / PK regardless
    # of whether it's currently inside the in-window catalyst set.
    kalv_finding = next((f for f in findings if f["ticker"] == "KALV"), None)
    if kalv_finding is None:
        kalv_row = next((r for r in rows if r["ticker"] == "KALV"), None)
        if kalv_row is not None:
            cat_date = kalv_row.get("catalyst_date") or kalv_row.get("next_catalyst_date") or ""
            matches = find_catalyst_trials("KALV", cat_date, trials)
            per_trial = []
            any_valid = False
            all_flags: list[str] = []
            for t in matches:
                v, flags = classify_trial(t)
                per_trial.append(
                    {
                        "nct_id": t.get("nct_id"),
                        "title": t.get("title"),
                        "phase": t.get("phase"),
                        "status": t.get("status"),
                        "study_type": t.get("study_type"),
                        "primary_completion_date": t.get("primary_completion_date"),
                        "verdict": v,
                        "flags": flags,
                    }
                )
                if v == "valid":
                    any_valid = True
                all_flags.extend(flags)
            agg = (
                "valid"
                if any_valid
                else ("false" if matches and all(pt["verdict"] == "false" for pt in per_trial) else "ambiguous")
            )
            kalv_finding = {
                "ticker": "KALV",
                "actionable_rank": _int(kalv_row.get("actionable_rank")),
                "tier_any": kalv_row.get("tier_any"),
                "tier_dev": kalv_row.get("tier_dev"),
                "catalyst_date": cat_date,
                "catalyst_days": _int(kalv_row.get("catalyst_days")),
                "catalyst_bucket": kalv_row.get("catalyst_bucket"),
                "catalyst_event_type": kalv_row.get("catalyst_event_type"),
                "catalyst_source": kalv_row.get("catalyst_source"),
                "catalyst_in_window": kalv_row.get("catalyst_in_window"),
                "lead_phase": kalv_row.get("lead_program_phase"),
                "development_stage": kalv_row.get("development_stage"),
                "matched_trials": per_trial,
                "verdict": agg,
                "verdict_reasons": sorted(set(all_flags)),
                "_note": "out-of-window seed check — included for spec confirmation only",
            }

    out_json = {
        "schema": "false_clinical_catalyst_audit.v1",
        "as_of_snapshot": snap_date,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rankings_path": str(rankings_path.relative_to(REPO)),
        "trial_records_path": str(TRIAL_RECORDS.relative_to(REPO)),
        "n_in_window_total": int(sum(1 for r in rows if r.get("catalyst_in_window") == "1")),
        "n_ctgov_candidates_audited": len(candidates),
        "n_high_confidence_false": len(high_confidence_false),
        "n_ambiguous": len(ambiguous),
        "n_likely_valid": len(likely_valid),
        "kalv_seed_check": kalv_finding,
        "findings_high_confidence_false": sorted(high_confidence_false, key=lambda f: (f["actionable_rank"] or 9999)),
        "findings_ambiguous": sorted(ambiguous, key=lambda f: (f["actionable_rank"] or 9999)),
        "findings_likely_valid": sorted(likely_valid, key=lambda f: (f["actionable_rank"] or 9999)),
    }

    out_path_json = AUDIT_DIR / f"false_clinical_catalyst_audit_{snap_date}.json"
    out_path_json.write_text(json.dumps(out_json, indent=2, default=str))

    # Markdown
    lines: list[str] = []
    lines.append(f"# False Clinical Catalyst Audit — {snap_date}")
    lines.append("")
    lines.append(f"Snapshot: `{rankings_path.relative_to(REPO)}`  ")
    lines.append(f"Trial cache: `{TRIAL_RECORDS.relative_to(REPO)}`  ")
    lines.append("Read-only. No model changes.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- In-window catalysts (all sources): **{out_json['n_in_window_total']}**")
    lines.append(f"- CT.gov candidates audited: **{out_json['n_ctgov_candidates_audited']}**")
    lines.append(f"  - High-confidence FALSE: **{out_json['n_high_confidence_false']}**")
    lines.append(f"  - Ambiguous (manual review): **{out_json['n_ambiguous']}**")
    lines.append(f"  - Likely valid: **{out_json['n_likely_valid']}**")
    lines.append("")
    lines.append("## KALV seed check")
    lines.append("")
    if kalv_finding:
        lines.append(_render_finding_md(kalv_finding))
        lines.append(f"  ⇒ aggregate verdict: **{kalv_finding['verdict']}**")
    else:
        lines.append("- KALV not in catalyst-in-window candidate set this snapshot.")
    lines.append("")
    lines.append("## High-confidence false catalysts")
    lines.append("")
    for f in out_json["findings_high_confidence_false"]:
        lines.append(_render_finding_md(f))
    lines.append("")
    lines.append("## Ambiguous catalysts (manual review)")
    lines.append("")
    for f in out_json["findings_ambiguous"]:
        lines.append(_render_finding_md(f))
    lines.append("")
    lines.append("## Likely valid catalysts (sanity)")
    lines.append("")
    lines.append(f"_{len(out_json['findings_likely_valid'])} entries — see JSON for full list. Top 20 by rank shown:_")
    lines.append("")
    for f in out_json["findings_likely_valid"][:20]:
        rank = f["actionable_rank"] or "-"
        nct_ids = ",".join(t["nct_id"] for t in f["matched_trials"])
        lines.append(f"- `{f['ticker']}` rank {rank} — {f['catalyst_event_type']} {f['catalyst_date']} ({nct_ids})")
    lines.append("")
    lines.append("## Recommended next implementation spec")
    lines.append("")
    lines.append(
        "If high-confidence-false count is materially non-zero (>5), draft a "
        "`spec_NNN_catalyst_classifier.md` proposing a CT.gov catalyst-quality gate that "
        "(1) filters trials by study_type + title regex before assigning catalyst credit, "
        "(2) downgrades `catalyst_bucket` from `binary_now` / `build_window` to "
        "`registry_only` for OLE/PK/expanded-access matches, and "
        "(3) preserves the original CT.gov date as a context field rather than a tier driver. "
        "Alpha-affecting → Checklist v2 required before promotion."
    )
    lines.append("")

    out_path_md = AUDIT_DIR / f"false_clinical_catalyst_audit_{snap_date}.md"
    out_path_md.write_text("\n".join(lines))

    # Console
    print(f"[false_clinical_catalyst_audit] {snap_date}")
    print(
        f"  candidates: {len(candidates)}  | false={len(high_confidence_false)} amb={len(ambiguous)} valid={len(likely_valid)}"
    )
    print(f"  json: {out_path_json.relative_to(REPO)}")
    print(f"  md:   {out_path_md.relative_to(REPO)}")
    return 0


def _int(v):
    try:
        return int(v) if v not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None


def _render_finding_md(f: dict) -> str:
    rank = f["actionable_rank"] or "-"
    head = (
        f"### {f['ticker']} (rank {rank}) — {f.get('catalyst_event_type', '?')} "
        f"{f.get('catalyst_date', '?')} ({f.get('catalyst_bucket', '?')})"
    )
    out = [head, ""]
    out.append(
        f"- tier_any/dev: `{f['tier_any']}/{f['tier_dev']}`  | "
        f"phase: `{f['lead_phase']}`  | stage: `{f['development_stage']}`  | "
        f"days: `{f['catalyst_days']}`  | source: `{f.get('catalyst_source')}`"
    )
    if not f["matched_trials"]:
        out.append("- _no trial matched catalyst_date in trial_records cache_")
    else:
        for t in f["matched_trials"]:
            flags = ", ".join(t["flags"]) if t["flags"] else "(no flags)"
            title = (t["title"] or "")[:120]
            out.append(
                f"  - `{t['nct_id']}` [{t['phase']}/{t['status']}/{t['study_type']}] "
                f"pri_comp={t['primary_completion_date']} → **{t['verdict']}** ({flags})  "
                f"\n    _{title}_"
            )
    out.append(f"- **why_flagged**: {', '.join(f['verdict_reasons']) or '—'}")
    out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())

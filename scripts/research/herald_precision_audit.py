#!/usr/bin/env python3
"""Herald Precision Audit — Spec 053.

Systematic quality audit of Herald press release classification and
Catalyst History event ledger. Identifies:
  A. Placeholder dates, forward dates, staleness
  B. Ticker contamination (pre-IPO recycling)
  C. Confidence inconsistency (categorical vs numeric)
  D. Herald classification: noise leakage, negation misclass, sev/conf mismatch
  E. April cluster spotlight (ORKA, ARTV, CLYM, PHVS, ABUS)

Read-only — does not modify any production data.

Output:
    artifacts/herald_audit/{date}_audit.json

Usage:
    python scripts/research/herald_precision_audit.py --as-of-date 2026-04-04
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("herald_audit")

SCHEMA_VERSION = "herald_precision_audit.v1"
APRIL_CLUSTER = ["ORKA", "ARTV", "CLYM", "PHVS", "ABUS"]

QUARTER_STARTS = frozenset({"01-01", "04-01", "07-01", "10-01"})

GUIDANCE_LANGUAGE = [
    "expect",
    "anticipat",
    "guidance",
    "projected",
    "planned",
    "estimated",
    "target",
    "intend",
    "aim",
    "goal",
    "upcoming",
    "forthcoming",
]

NOISE_PATTERNS = [
    "market valuation",
    "market value",
    "market outlook",
    "market segmentation",
    "market dynamics",
    "market overview",
    "competitive analysis",
    "competitive landscape",
    "value chain",
    "supply chain analysis",
    "key players",
    "cagr",
    "forecast period",
    "billion by 20",
    "million by 20",
    "price target",
    "initiates coverage",
    "maintains buy",
    "maintains sell",
    "maintains hold",
    "downgrades",
    "upgrades to",
    "analyst report",
    "equity research",
    "masterbatch",
    "market opportunity",
    "regional market",
    "global market size",
    "market trends",
    "market share",
]

SAFETY_NEGATION_PATTERNS = [
    "lifts clinical hold",
    "lift clinical hold",
    "lifted clinical hold",
    "clinical hold lifted",
    "clinical hold has been lifted",
    "removes clinical hold",
    "removal of clinical hold",
    "clinical hold removed",
    "resolves clinical hold",
    "hold has been resolved",
    "partial hold lifted",
    "partial hold removed",
    "removes partial clinical hold",
]

CONFIDENCE_MAP = {
    "HIGH": 0.9,
    "MED": 0.6,
    "MEDIUM": 0.6,
    "LOW": 0.3,
}


# ── Core Functions ───────────────────────────────────────────────────


def normalize_confidence(raw) -> float:
    """Normalize confidence to 0-1 float scale."""
    upper = str(raw).strip().upper()
    if upper in CONFIDENCE_MAP:
        return CONFIDENCE_MAP[upper]
    try:
        val = float(raw)
        return max(0.0, min(1.0, val))
    except (ValueError, TypeError):
        return 0.5


def classify_date_type(event_date: str, pit_available_at: str, event_name: str) -> str:
    """Classify event date as 'actual', 'guidance', or 'placeholder'."""
    # Placeholder: quarter-start + guidance language
    if event_date[5:] in QUARTER_STARTS:
        name_lower = (event_name or "").lower()
        if any(g in name_lower for g in GUIDANCE_LANGUAGE):
            return "placeholder"

    # Guidance: event_date > pit_available_at (forward-looking)
    if event_date > pit_available_at:
        return "guidance"

    return "actual"


# ── Audit Module A: Date-Confidence ─────────────────────────────────


def detect_placeholder_dates(events: List[Dict]) -> List[Dict]:
    """Flag events with quarter-start dates + guidance language."""
    findings = []
    for ev in events:
        ed = ev.get("event_date", "")
        if len(ed) < 10:
            continue
        if ed[5:] not in QUARTER_STARTS:
            continue
        name_lower = (ev.get("event_name") or "").lower()
        if any(g in name_lower for g in GUIDANCE_LANGUAGE):
            findings.append(
                {
                    "event_id": ev.get("event_id", ""),
                    "ticker": ev.get("ticker", ""),
                    "event_date": ed,
                    "event_name": ev.get("event_name", "")[:100],
                    "reason": "quarter-start date with guidance language",
                }
            )
    return findings


def detect_forward_dates(events: List[Dict]) -> List[Dict]:
    """Flag events where event_date > pit_available_at."""
    findings = []
    for ev in events:
        ed = ev.get("event_date", "")
        pa = ev.get("pit_available_at", "")
        if not ed or not pa or len(ed) < 10 or len(pa) < 10:
            continue
        if ed > pa:
            try:
                d_event = date.fromisoformat(ed[:10])
                d_pit = date.fromisoformat(pa[:10])
                delta = (d_event - d_pit).days
            except ValueError:
                delta = -1
            findings.append(
                {
                    "event_id": ev.get("event_id", ""),
                    "ticker": ev.get("ticker", ""),
                    "event_date": ed,
                    "pit_available_at": pa,
                    "delta_days": delta,
                    "reason": "event_date after pit_available_at (forward-looking guidance)",
                }
            )
    return findings


def detect_staleness(
    events: List[Dict],
    resolved_keys: Set[Tuple[str, str]],
    as_of: str,
) -> List[Dict]:
    """Flag past events (>30d old) with no CRT resolution."""
    findings = []
    actionable_types = {
        "DATA_READOUT",
        "FDA_PDUFA_DATE",
        "REGULATORY_DECISION",
        "ADVISORY_COMMITTEE",
    }
    try:
        as_of_date = date.fromisoformat(as_of)
    except ValueError:
        return findings

    for ev in events:
        ed = ev.get("event_date", "")
        et = ev.get("event_type", "")
        if et not in actionable_types:
            continue
        if len(ed) < 10:
            continue
        try:
            ev_date = date.fromisoformat(ed[:10])
        except ValueError:
            continue
        if ev_date >= as_of_date:
            continue
        days_stale = (as_of_date - ev_date).days
        if days_stale < 30:
            continue
        ticker = ev.get("ticker", "")
        if (ticker, ed[:10]) in resolved_keys:
            continue
        findings.append(
            {
                "event_id": ev.get("event_id", ""),
                "ticker": ticker,
                "event_date": ed,
                "event_type": et,
                "days_stale": days_stale,
                "reason": "past actionable event with no CRT resolution",
            }
        )
    return findings


# ── Audit Module B: Ticker Contamination ────────────────────────────


def detect_pre_ipo_events(events: List[Dict], ipo_dates: Dict[str, Dict]) -> List[Dict]:
    """Flag events from before a ticker's first_price_date (recycling)."""
    findings = []
    for ev in events:
        ticker = ev.get("ticker", "")
        ed = ev.get("event_date", "")
        if not ticker or len(ed) < 10:
            continue
        ipo = ipo_dates.get(ticker)
        if not ipo:
            continue  # fail-open
        fpd = ipo.get("first_price_date", "")
        if not fpd:
            continue
        if ed[:10] < fpd:
            findings.append(
                {
                    "event_id": ev.get("event_id", ""),
                    "ticker": ticker,
                    "event_date": ed,
                    "first_price_date": fpd,
                    "reason": "event_date before ticker IPO (likely ticker recycling)",
                }
            )
    return findings


# ── Audit Module C: Confidence Consistency ──────────────────────────


def detect_mixed_confidence(events: List[Dict]) -> Dict[str, Any]:
    """Detect inconsistent confidence representations."""
    n_cat = 0
    n_num = 0
    n_unparseable = 0
    examples_cat = []
    examples_num = []

    for ev in events:
        raw = str(ev.get("confidence", ""))
        upper = raw.strip().upper()
        if upper in CONFIDENCE_MAP:
            n_cat += 1
            if len(examples_cat) < 3:
                examples_cat.append({"ticker": ev.get("ticker"), "confidence": raw})
        else:
            try:
                float(raw)
                n_num += 1
                if len(examples_num) < 3:
                    examples_num.append({"ticker": ev.get("ticker"), "confidence": raw})
            except (ValueError, TypeError):
                n_unparseable += 1

    return {
        "has_mixed": n_cat > 0 and n_num > 0,
        "n_categorical": n_cat,
        "n_numeric": n_num,
        "n_unparseable": n_unparseable,
        "examples_categorical": examples_cat,
        "examples_numeric": examples_num,
        "normalization_map": CONFIDENCE_MAP,
    }


# ── Audit Module D: Herald Classification ───────────────────────────


def detect_noise_leakage(records: List[Dict]) -> List[Dict]:
    """Detect headlines that should have been caught by noise filter."""
    findings = []
    for rec in records:
        hl = (rec.get("headline") or "").lower()
        cat = rec.get("event_category", "")
        if rec.get("informational_only"):
            continue
        for pattern in NOISE_PATTERNS:
            if pattern in hl:
                findings.append(
                    {
                        "ticker": rec.get("ticker", ""),
                        "headline": rec.get("headline", "")[:120],
                        "event_category": cat,
                        "confidence": rec.get("confidence"),
                        "pattern_matched": pattern,
                    }
                )
                break
    return findings


def detect_negation_misclass(records: List[Dict]) -> List[Dict]:
    """Detect safety-classified records with negation context."""
    findings = []
    for rec in records:
        cat = rec.get("event_category", "")
        if cat != "safety" and not rec.get("safety_signal_flag"):
            continue
        hl = (rec.get("headline") or "").lower()
        for neg in SAFETY_NEGATION_PATTERNS:
            if neg in hl:
                findings.append(
                    {
                        "ticker": rec.get("ticker", ""),
                        "headline": rec.get("headline", "")[:120],
                        "classified_category": cat,
                        "classified_outcome": rec.get("event_outcome_guess", ""),
                        "should_be_category": "regulatory",
                        "should_be_outcome": "hit",
                        "negation_pattern": neg,
                    }
                )
                break
    return findings


def detect_high_severity_low_confidence(records: List[Dict]) -> List[Dict]:
    """Flag records with critical/high severity but low confidence."""
    findings = []
    for rec in records:
        sev = (rec.get("severity") or "").lower()
        conf = rec.get("confidence", 1.0)
        if sev in ("critical", "high") and conf < 0.5:
            findings.append(
                {
                    "ticker": rec.get("ticker", ""),
                    "headline": rec.get("headline", "")[:120],
                    "severity": sev,
                    "confidence": conf,
                    "needs_review": rec.get("needs_review", False),
                }
            )
    return findings


# ── Audit Module E: April Cluster ───────────────────────────────────


def audit_april_cluster(
    events: List[Dict],
    classified: List[Dict],
    ipo_dates: Dict[str, Dict],
) -> Dict[str, Any]:
    """Focused audit on April cluster tickers."""
    result = {}
    for ticker in APRIL_CLUSTER:
        t_events = [e for e in events if e.get("ticker") == ticker]
        t_classified = [r for r in classified if r.get("ticker") == ticker]
        t_contamination = detect_pre_ipo_events(t_events, ipo_dates)
        t_placeholders = detect_placeholder_dates(t_events)
        t_forward = detect_forward_dates(t_events)
        t_noise = detect_noise_leakage(t_classified)
        t_negation = detect_negation_misclass(t_classified)

        result[ticker] = {
            "n_catalyst_events": len(t_events),
            "n_classified_records": len(t_classified),
            "n_contamination": len(t_contamination),
            "n_placeholder_dates": len(t_placeholders),
            "n_forward_dates": len(t_forward),
            "n_noise_leakage": len(t_noise),
            "n_negation_misclass": len(t_negation),
            "findings": {
                "contamination": t_contamination,
                "placeholders": t_placeholders[:5],
                "forward_dates": t_forward[:5],
                "noise": t_noise,
                "negation": t_negation,
            },
        }
    return result


# ── Data Loading ─────────────────────────────────────────────────────


def load_catalyst_events(
    path: Optional[Path] = None,
) -> List[Dict]:
    """Load catalyst history events."""
    p = path or PROJECT_ROOT / "data" / "catalyst_history" / "catalyst_history_events.jsonl"
    if not p.exists():
        log.warning("Catalyst events not found: %s", p)
        return []
    events = []
    for line in p.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    log.info("Loaded %d catalyst events", len(events))
    return events


def load_classified_records(
    classified_dir: Optional[Path] = None,
) -> List[Dict]:
    """Load all classified records from Herald output."""
    d = classified_dir or PROJECT_ROOT / "data" / "press_releases" / "classified"
    if not d.exists():
        log.warning("Classified dir not found: %s", d)
        return []
    records = []
    for f in sorted(d.glob("classified_*.jsonl")):
        for line in f.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    log.info("Loaded %d classified records from %s", len(records), d)
    return records


def load_ipo_dates(
    path: Optional[Path] = None,
) -> Dict[str, Dict]:
    """Load IPO dates mapping."""
    p = path or PROJECT_ROOT / "production_data" / "ipo_dates.json"
    if not p.exists():
        log.warning("ipo_dates.json not found: %s", p)
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "tickers" in data:
        return data["tickers"]
    return data


def load_crt_resolutions(
    res_dir: Optional[Path] = None,
) -> Set[Tuple[str, str]]:
    """Load existing CRT resolution keys (ticker, catalyst_date)."""
    d = res_dir or PROJECT_ROOT / "data" / "snapshots" / "resolutions"
    keys: Set[Tuple[str, str]] = set()
    if not d.exists():
        return keys
    for month_dir in d.iterdir():
        if not month_dir.is_dir():
            continue
        for f in month_dir.glob("*.json"):
            try:
                rec = json.loads(f.read_text())
                keys.add((rec.get("ticker", ""), rec.get("catalyst_date", "")))
            except (json.JSONDecodeError, OSError):
                pass
    log.info("Loaded %d CRT resolutions", len(keys))
    return keys


# ── Main Orchestrator ────────────────────────────────────────────────


def build_audit_report(
    as_of_date: str,
    events: Optional[List[Dict]] = None,
    classified: Optional[List[Dict]] = None,
    ipo_dates: Optional[Dict[str, Dict]] = None,
) -> Dict[str, Any]:
    """Run all audit modules and produce unified report."""
    if events is None:
        events = load_catalyst_events()
    if classified is None:
        classified = load_classified_records()
    if ipo_dates is None:
        ipo_dates = load_ipo_dates()
    resolutions = load_crt_resolutions()

    # A: Date-confidence
    placeholders = detect_placeholder_dates(events)
    forward_dates = detect_forward_dates(events)
    stale = detect_staleness(events, resolutions, as_of_date)

    # B: Ticker contamination
    contamination = detect_pre_ipo_events(events, ipo_dates)

    # C: Confidence
    confidence_audit = detect_mixed_confidence(events)

    # D: Herald classification
    noise = detect_noise_leakage(classified)
    negation = detect_negation_misclass(classified)
    sev_conf = detect_high_severity_low_confidence(classified)

    # E: April cluster
    april = audit_april_cluster(events, classified, ipo_dates)

    # F: Summary
    summary = {
        "total_catalyst_events": len(events),
        "total_classified_records": len(classified),
        "findings": {
            "placeholder_dates": len(placeholders),
            "forward_dates": len(forward_dates),
            "stale_unresolved": len(stale),
            "ticker_contamination": len(contamination),
            "confidence_mixed": confidence_audit["has_mixed"],
            "noise_leakage": len(noise),
            "negation_misclass": len(negation),
            "high_sev_low_conf": len(sev_conf),
        },
        "severity": "HIGH" if (len(contamination) > 0 or len(noise) > 0) else "MEDIUM",
    }

    return {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "date_audit": {
            "placeholders": placeholders[:50],
            "n_placeholders": len(placeholders),
            "forward_dates_sample": forward_dates[:50],
            "n_forward_dates": len(forward_dates),
            "stale_sample": stale[:50],
            "n_stale": len(stale),
        },
        "ticker_audit": {
            "contamination": contamination,
            "n_contamination": len(contamination),
        },
        "confidence_audit": confidence_audit,
        "herald_audit": {
            "noise_leakage": noise,
            "negation_misclass": negation,
            "high_sev_low_conf_sample": sev_conf[:20],
            "n_high_sev_low_conf": len(sev_conf),
        },
        "april_cluster": april,
    }


def print_summary(report: Dict):
    """Print human-readable summary."""
    s = report["summary"]
    f = s["findings"]
    print(f"\n{'='*60}")
    print("HERALD PRECISION AUDIT")
    print(f"{'='*60}")
    print(f"  As-of date:          {report['as_of_date']}")
    print(f"  Catalyst events:     {s['total_catalyst_events']}")
    print(f"  Classified records:  {s['total_classified_records']}")
    print(f"  Overall severity:    {s['severity']}")
    print("\n  Findings:")
    print(f"    Placeholder dates:   {f['placeholder_dates']}")
    print(f"    Forward dates:       {f['forward_dates']}")
    print(f"    Stale unresolved:    {f['stale_unresolved']}")
    print(f"    Ticker contamination:{f['ticker_contamination']}")
    print(f"    Confidence mixed:    {f['confidence_mixed']}")
    print(f"    Noise leakage:       {f['noise_leakage']}")
    print(f"    Negation misclass:   {f['negation_misclass']}")
    print(f"    High sev / low conf: {f['high_sev_low_conf']}")

    april = report.get("april_cluster", {})
    if april:
        print("\n  April Cluster:")
        for ticker in APRIL_CLUSTER:
            tc = april.get(ticker, {})
            issues = (
                tc.get("n_contamination", 0)
                + tc.get("n_placeholder_dates", 0)
                + tc.get("n_noise_leakage", 0)
                + tc.get("n_negation_misclass", 0)
            )
            print(
                f"    {ticker:<6} events={tc.get('n_catalyst_events', 0):>3}  "
                f"classified={tc.get('n_classified_records', 0):>3}  issues={issues}"
            )


def main():
    parser = argparse.ArgumentParser(description="Herald Precision Audit (Spec 053)")
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    report = build_audit_report(args.as_of_date)

    out_dir = Path(args.output_dir) if args.output_dir else PROJECT_ROOT / "artifacts" / "herald_audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.as_of_date}_audit.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    log.info("Wrote %s", out_path)

    print_summary(report)


if __name__ == "__main__":
    main()

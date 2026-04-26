#!/usr/bin/env python3
"""
build_pdufa_dates_extracted.py — Phase 1 extracted PDUFA sidecar.

Reads the latest SEC 8-K catalyst cache, filters/dedupes/caps per ticker, and
writes:
  - production_data/pdufa_dates_extracted.json    (latest snapshot, overwritten daily)
  - artifacts/regulatory/pdufa_dates_extracted_{as_of}.json
                                                  (dated audit snapshot, append-only)
  - artifacts/regulatory/pdufa_extracted_vs_canonical_{as_of}.csv
  - artifacts/regulatory/pdufa_extracted_vs_canonical_{as_of}.md

Phase 1 contract:
  - Does NOT touch production_data/pdufa_dates.json.
  - Does NOT touch run_screen.py / scoring / selectors / event ledger.
  - Does NOT auto-promote.
  - drug_name / indication left empty (no NER in Phase 1).
  - Submission/review type best-effort from event_name regex.

Usage:
  python -m tools.build_pdufa_dates_extracted --as-of-date 2026-04-27
  python -m tools.build_pdufa_dates_extracted --as-of-date 2026-04-27 --max-stale-days 7
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    force=True,
)
logger = logging.getLogger("build_pdufa_dates_extracted")

# ── Project paths ────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[1]
SEC_8K_CACHE_DIR = PROJECT_ROOT / "cache" / "sec" / "8k_catalysts"
PDUFA_CANONICAL_PATH = PROJECT_ROOT / "production_data" / "pdufa_dates.json"
PDUFA_EXTRACTED_PATH = PROJECT_ROOT / "production_data" / "pdufa_dates_extracted.json"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts" / "regulatory"

# ── Filter rules ─────────────────────────────────────────────────────────────
ACCEPTED_CONFIDENCE = {"HIGH", "MED"}
ACCEPTED_PRECISION = {"DAY"}
STALE_AFTER_DAYS = 30  # drop events whose date is more than N days in the past
MAX_PER_TICKER = 3  # cap at 3 nearest-future PDUFAs per ticker

# Status priority: extended/resubmission_accepted > upcoming > unset.
_STATUS_PRIORITY = {"extended": 3, "resubmission_accepted": 2, "upcoming": 1, "": 0, None: 0}
_CONF_PRIORITY = {"HIGH": 2, "MED": 1, "LOW": 0, "": 0, None: 0}

# Best-effort submission_type extraction from event_name.
_SUBMISSION_RE = re.compile(r"\b(sBLA|sNDA|BLA|NDA)\b", re.IGNORECASE)


def _find_latest_cache(cache_dir: Path, as_of: date, max_stale_days: int) -> Optional[Path]:
    """Find the freshest 8-K cache within max_stale_days of as_of."""
    if not cache_dir.exists():
        return None
    candidates: List[Tuple[date, Path]] = []
    for p in cache_dir.glob("8k_catalysts_*.json"):
        # Filename: 8k_catalysts_{ISO_DATE}_{PATTERN_VERSION}.json
        stem = p.stem  # 8k_catalysts_2026-04-24_b2bdaf75
        parts = stem.split("_")
        if len(parts) < 4:
            continue
        try:
            file_date = datetime.strptime(parts[2], "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_date > as_of:
            continue
        if (as_of - file_date).days > max_stale_days:
            continue
        candidates.append((file_date, p))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1].stat().st_mtime), reverse=True)
    return candidates[0][1]


def _load_cache_events(path: Path) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _load_canonical(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        records = json.load(f)
    return {(r.get("ticker") or "").upper(): r for r in records if r.get("ticker")}


def _extract_submission_type(event_name: str) -> str:
    m = _SUBMISSION_RE.search(event_name or "")
    if not m:
        return ""
    raw = m.group(1).lower()
    return {"snda": "sNDA", "sbla": "sBLA", "nda": "NDA", "bla": "BLA"}[raw]


def filter_and_dedupe(events: List[Dict[str, Any]], as_of: date) -> List[Dict[str, Any]]:
    """
    Apply Phase 1 filter/dedup rules:
      1. event_type == FDA_PDUFA_DATE
      2. date_precision in {DAY}
      3. confidence in {HIGH, MED}
      4. event_date >= as_of - STALE_AFTER_DAYS
      5. dedupe per (ticker, event_date) by status/conf priority
      6. cap MAX_PER_TICKER nearest-future per ticker
    """
    stale_cutoff = (as_of - timedelta(days=STALE_AFTER_DAYS)).isoformat()

    # Stage 1: filter
    kept: List[Dict[str, Any]] = []
    for e in events:
        if e.get("event_type") != "FDA_PDUFA_DATE":
            continue
        if e.get("date_precision") not in ACCEPTED_PRECISION:
            continue
        if e.get("confidence") not in ACCEPTED_CONFIDENCE:
            continue
        ed = e.get("event_date") or ""
        if not ed or ed < stale_cutoff:
            continue
        kept.append(e)

    # Stage 2: dedupe per (ticker, event_date)
    by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for e in kept:
        ticker = (e.get("ticker") or "").upper()
        key = (ticker, e.get("event_date") or "")
        cur = by_key.get(key)
        if cur is None:
            by_key[key] = e
            continue
        new_score = (
            _STATUS_PRIORITY.get(e.get("event_status"), 0),
            _CONF_PRIORITY.get(e.get("confidence"), 0),
            e.get("disclosed_at") or "",
        )
        cur_score = (
            _STATUS_PRIORITY.get(cur.get("event_status"), 0),
            _CONF_PRIORITY.get(cur.get("confidence"), 0),
            cur.get("disclosed_at") or "",
        )
        if new_score > cur_score:
            by_key[key] = e

    # Stage 3: cap per-ticker, keep nearest-future first
    by_ticker: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for (ticker, _ed), e in by_key.items():
        by_ticker[ticker].append(e)

    capped: List[Dict[str, Any]] = []
    for ticker, evs in by_ticker.items():
        evs.sort(key=lambda x: x.get("event_date") or "")
        capped.extend(evs[:MAX_PER_TICKER])

    # Stage 4: sort output by event_date asc
    capped.sort(key=lambda x: (x.get("event_date") or "", x.get("ticker") or ""))
    return capped


def to_sidecar_record(event: Dict[str, Any], pattern_version: Optional[str], extracted_at_iso: str) -> Dict[str, Any]:
    """Convert a cache event dict into the sidecar schema."""
    submission_type = _extract_submission_type(event.get("event_name", ""))
    return {
        "ticker": (event.get("ticker") or "").upper(),
        "pdufa_date": event.get("event_date") or "",
        "event_type": "PDUFA",
        "event_status": event.get("event_status") or "upcoming",
        "submission_type": submission_type,
        "review_type": "",  # not extracted from regex
        "confidence": event.get("confidence") or "",
        "date_precision": event.get("date_precision") or "",
        "prior_date": event.get("prior_date") or None,
        "source": event.get("source") or "SEC_8K_FILING",
        "source_url": "",  # accession not in cached events; populated in a later phase
        "accession": event.get("accession") or "",
        "filing_form": event.get("filing_form") or "",
        "as_of_disclosed_at": event.get("disclosed_at") or "",
        "extracted_at": extracted_at_iso,
        "drug_name": "",  # Phase 1: empty (NER deferred)
        "indication": "",  # Phase 1: empty (NER deferred)
        "notes": (
            f"Auto-extracted from SEC 8-K cache; "
            f"pattern_version={pattern_version or 'unknown'}; "
            f"event_name={(event.get('event_name') or '')[:120]}"
        ),
    }


def classify_diff(record: Dict[str, Any], canonical: Dict[str, Dict[str, Any]]) -> Tuple[str, Optional[str]]:
    """Bucket extracted record vs canonical pdufa_dates.json."""
    ticker = record["ticker"]
    cano = canonical.get(ticker)
    cano_date = (cano or {}).get("pdufa_date")
    status = record.get("event_status") or ""
    pdufa_date = record.get("pdufa_date") or ""

    if status in ("extended", "resubmission_accepted"):
        if cano is None:
            return ("EXTENDED_NOT_IN_CANONICAL", None)
        if cano_date == pdufa_date:
            return ("EXTENDED_MATCHES_CANONICAL", cano_date)
        return ("EXTENDED_CONFLICTS_CANONICAL", cano_date)

    if cano is None:
        return ("NEW_CANDIDATE", None)
    if cano_date == pdufa_date:
        return ("MATCHES_CANONICAL", cano_date)
    return ("CONFLICTS_CANONICAL", cano_date)


def write_diff_artifacts(
    sidecar_records: List[Dict[str, Any]],
    canonical: Dict[str, Dict[str, Any]],
    as_of: date,
    artifacts_dir: Path,
) -> Dict[str, int]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    csv_path = artifacts_dir / f"pdufa_extracted_vs_canonical_{as_of.isoformat()}.csv"
    md_path = artifacts_dir / f"pdufa_extracted_vs_canonical_{as_of.isoformat()}.md"

    rows = []
    by_class: Dict[str, int] = defaultdict(int)
    for r in sidecar_records:
        cls, cano_date = classify_diff(r, canonical)
        by_class[cls] += 1
        rows.append(
            {
                "ticker": r["ticker"],
                "pdufa_date": r["pdufa_date"],
                "event_status": r["event_status"],
                "prior_date": r.get("prior_date") or "",
                "confidence": r["confidence"],
                "submission_type": r["submission_type"],
                "filing_form": r["filing_form"],
                "as_of_disclosed_at": r["as_of_disclosed_at"],
                "canonical_pdufa_date": cano_date or "",
                "diff_classification": cls,
            }
        )
    rows.sort(key=lambda x: (x["diff_classification"], x["ticker"], x["pdufa_date"]))

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=(
                list(rows[0].keys())
                if rows
                else [
                    "ticker",
                    "pdufa_date",
                    "event_status",
                    "prior_date",
                    "confidence",
                    "submission_type",
                    "filing_form",
                    "as_of_disclosed_at",
                    "canonical_pdufa_date",
                    "diff_classification",
                ]
            ),
        )
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    md_lines = [
        f"# PDUFA Extracted vs Canonical — {as_of.isoformat()}",
        "",
        "**DRY-RUN.** `production_data/pdufa_dates.json` is NOT modified.",
        "",
        "## Summary",
        "",
        f"- Total extracted records: **{len(sidecar_records)}**",
    ]
    for k in sorted(by_class.keys()):
        md_lines.append(f"- {k}: **{by_class[k]}**")
    md_lines.append("")
    md_lines.append("## Rows (top 50)")
    md_lines.append("")
    md_lines.append("| Class | Ticker | PDUFA | Status | Prior | Conf | Submission | Form | Filed | Canonical |")
    md_lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows[:50]:
        md_lines.append(
            f"| {r['diff_classification']} | {r['ticker']} | {r['pdufa_date']} | "
            f"{r['event_status']} | {r['prior_date']} | {r['confidence']} | "
            f"{r['submission_type']} | {r['filing_form']} | {r['as_of_disclosed_at']} | "
            f"{r['canonical_pdufa_date']} |"
        )
    md_lines.append("")
    md_lines.append(f"_Full set in `{csv_path.name}` ({len(rows)} rows)._")
    md_lines.append("")
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    return dict(by_class)


def build_extracted_sidecar(as_of: date, max_stale_days: int = 7) -> Dict[str, Any]:
    """Main entry point. Returns a summary dict."""
    cache_path = _find_latest_cache(SEC_8K_CACHE_DIR, as_of, max_stale_days)
    if cache_path is None:
        logger.warning(
            f"No SEC 8-K cache within {max_stale_days} days of {as_of.isoformat()}; " f"writing empty sidecar."
        )
        events = []
        pattern_version = None
        cache_path_str = ""
    else:
        events = _load_cache_events(cache_path)
        # Pattern version embedded in filename: 8k_catalysts_{date}_{pv}.json
        try:
            pattern_version = cache_path.stem.rsplit("_", 1)[-1]
        except Exception:
            pattern_version = None
        cache_path_str = str(cache_path)
        logger.info(f"Loaded {len(events)} cached events from {cache_path_str} " f"(pattern_version={pattern_version})")

    canonical = _load_canonical(PDUFA_CANONICAL_PATH)
    logger.info(f"Canonical pdufa_dates.json: {len(canonical)} records")

    filtered = filter_and_dedupe(events, as_of)
    logger.info(f"After filter/dedupe/cap: {len(filtered)} events from {len(events)} cached")

    extracted_at_iso = datetime.now(timezone.utc).isoformat()
    sidecar_records = [to_sidecar_record(e, pattern_version, extracted_at_iso) for e in filtered]

    # Write latest snapshot (overwrites)
    PDUFA_EXTRACTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    PDUFA_EXTRACTED_PATH.write_text(json.dumps(sidecar_records, indent=2), encoding="utf-8")
    logger.info(f"Wrote latest snapshot → {PDUFA_EXTRACTED_PATH}")

    # Write dated audit snapshot
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    dated_path = ARTIFACTS_DIR / f"pdufa_dates_extracted_{as_of.isoformat()}.json"
    dated_path.write_text(json.dumps(sidecar_records, indent=2), encoding="utf-8")
    logger.info(f"Wrote dated snapshot → {dated_path}")

    # Diff artifacts
    by_class = write_diff_artifacts(sidecar_records, canonical, as_of, ARTIFACTS_DIR)

    summary = {
        "as_of_date": as_of.isoformat(),
        "extracted_at": extracted_at_iso,
        "cache_path": cache_path_str,
        "pattern_version": pattern_version,
        "n_cached_events": len(events),
        "n_after_filter": len(filtered),
        "n_records_written": len(sidecar_records),
        "diff_buckets": by_class,
        "latest_snapshot_path": str(PDUFA_EXTRACTED_PATH),
        "dated_snapshot_path": str(dated_path),
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of-date",
        default=date.today().isoformat(),
        help="ISO date (default: today)",
    )
    parser.add_argument(
        "--max-stale-days",
        type=int,
        default=7,
        help="Use cache up to N days old if today's missing (default: 7)",
    )
    args = parser.parse_args()
    try:
        as_of = datetime.strptime(args.as_of_date, "%Y-%m-%d").date()
    except ValueError:
        logger.error(f"Invalid --as-of-date: {args.as_of_date!r}")
        return 2

    summary = build_extracted_sidecar(as_of, max_stale_days=args.max_stale_days)
    print()
    print("=" * 60)
    print(f"Extracted PDUFA Sidecar — {as_of.isoformat()}")
    print("=" * 60)
    print(f"  Cache:                {summary['cache_path'] or '(none)'}")
    print(f"  Pattern version:      {summary['pattern_version']}")
    print(f"  Cached events:        {summary['n_cached_events']}")
    print(f"  After filter/dedupe:  {summary['n_after_filter']}")
    print(f"  Records written:      {summary['n_records_written']}")
    print(f"  Latest snapshot:      {summary['latest_snapshot_path']}")
    print(f"  Dated snapshot:       {summary['dated_snapshot_path']}")
    print(f"  Diff buckets:         {summary['diff_buckets']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

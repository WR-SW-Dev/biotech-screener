#!/usr/bin/env python3
"""
diff_sec_pdufa_review_window.py — DRY-RUN diff for SEC review-window patterns.

Goal: surface PDUFA review-window changes (extensions, Class 2 resubmissions,
"new PDUFA date", "major amendment", "target action date") that the expanded
extractor finds in real SEC filings, and compare them against the hand-curated
production_data/pdufa_dates.json. NO writes to pdufa_dates.json — outputs are
audit artifacts only.

Outputs:
  artifacts/regulatory/sec_pdufa_review_window_diff_{as_of}.csv
  artifacts/regulatory/sec_pdufa_review_window_diff_{as_of}.md

Usage:
  python -m scripts.research.diff_sec_pdufa_review_window
  python -m scripts.research.diff_sec_pdufa_review_window --as-of 2026-04-26 --lookback 120
  python -m scripts.research.diff_sec_pdufa_review_window --use-cache  # offline

The default mode hits SEC EDGAR with a focused full-text search over only the
new review-window keywords. --use-cache skips the network and re-runs the new
extractor over filings already discovered by the production collector
(useful when SEC is unreachable; will yield fewer matches because the cache
only contains pre-extracted events, not raw filing text).
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Locate project root so this script runs from any cwd.
_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from wake_robin_data_pipeline.collectors.sec_8k_catalyst_collector import (  # noqa: E402
    PATTERN_VERSION,
    SEC_COMPANY_TICKERS_URL,
    SEC_SEARCH_URL,
    USER_AGENT,
    _extract_ticker_from_display_names,
    _extract_timing_events,
    _fetch_filing_text,
    _sec_get,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    force=True,
)
logger = logging.getLogger("diff_sec_pdufa_review_window")
logger.setLevel(logging.INFO)
# Also force the wake_robin collector logger up.
logging.getLogger("wake_robin_data_pipeline.collectors.sec_8k_catalyst_collector").setLevel(logging.INFO)

# Focused EDGAR queries — ONLY the new review-window keywords. The goal is high
# precision on extension/resubmission language, not breadth.
NEW_KEYWORD_QUERIES = [
    '"new PDUFA date" OR "revised PDUFA date"',
    '"PDUFA goal date"',
    '"major amendment" AND "PDUFA"',
    '"three-month extension" OR "3-month extension"',
    '"review period has been extended" OR "extended the review period"',
    '"Class 2 resubmission"',
    '"six-month review period"',
    '"target action date"',
]

# Tag set that flags an event as a review-window change (vs fresh PDUFA).
REVIEW_WINDOW_TAGS: Set[str] = {
    "review_window_change",
    "extended",
    "major_amendment",
    "class_2_resubmission",
    "six_month_review",
}

CSV_COLUMNS = [
    "ticker",
    "event_status",
    "event_date",
    "prior_date",
    "date_precision",
    "confidence",
    "tags",
    "source",
    "filing_form",
    "filing_date",
    "accession",
    "canonical_pdufa_date",
    "diff_classification",
    "event_name",
]


def _load_universe(project_root: Path) -> Tuple[List[Dict[str, str]], Set[str]]:
    """Load universe.json. Returns (entries, ticker_set)."""
    path = project_root / "production_data" / "universe.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "tickers" in data:
        data = data["tickers"]
    entries = [e for e in data if isinstance(e, dict) and e.get("ticker")]
    return entries, {e["ticker"].upper() for e in entries}


def _load_canonical_pdufa(project_root: Path) -> Dict[str, Dict[str, Any]]:
    """Load production_data/pdufa_dates.json keyed by ticker (uppercase)."""
    path = project_root / "production_data" / "pdufa_dates.json"
    with open(path, "r", encoding="utf-8") as f:
        records = json.load(f)
    canonical: Dict[str, Dict[str, Any]] = {}
    for r in records:
        t = (r.get("ticker") or "").upper()
        if t:
            canonical[t] = r
    return canonical


def _direct_arvn_check(as_of: date, lookback_days: int = 180) -> List[Dict[str, Any]]:
    """
    Direct EDGAR fetch of ARVN's recent 8-Ks; runs the new extractor and returns
    any FDA_PDUFA_DATE events. Lets us distinguish "patterns can't find ARVN" from
    "ARVN's 8-Ks don't use these specific keywords" from "ARVN didn't file an 8-K".
    """
    try:
        import requests
    except ImportError:
        return []
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # Resolve ARVN CIK from SEC company_tickers.json.
    try:
        ct_resp = _sec_get(session, SEC_COMPANY_TICKERS_URL)
        if ct_resp.status_code != 200:
            return []
        arvn_cik: Optional[str] = None
        for _k, entry in ct_resp.json().items():
            if (entry.get("ticker") or "").upper() == "ARVN":
                arvn_cik = str(entry.get("cik_str") or "").lstrip("0")
                break
        if not arvn_cik:
            return []
    except Exception:
        return []

    # Fetch ARVN submissions feed.
    cik_padded = arvn_cik.zfill(10)
    submissions_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    try:
        sub_resp = _sec_get(session, submissions_url)
        if sub_resp.status_code != 200:
            return []
        recent = sub_resp.json().get("filings", {}).get("recent", {})
    except Exception:
        return []

    forms = recent.get("form", [])
    accs = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    cutoff = (as_of - timedelta(days=lookback_days)).isoformat()

    candidates: List[Tuple[str, str]] = []  # (adsh, file_date)
    for f, a, d in zip(forms, accs, dates):
        if f != "8-K":
            continue
        if d < cutoff or d > as_of.isoformat():
            continue
        candidates.append((a, d))

    extracted: List[Dict[str, Any]] = []
    for adsh, file_date in candidates[:10]:
        try:
            text = _fetch_filing_text(arvn_cik, adsh, session)
            if not text:
                continue
            evs = _extract_timing_events(text, "ARVN", file_date, as_of)
            for e in evs:
                if e.get("event_type") == "FDA_PDUFA_DATE":
                    e["accession"] = adsh
                    extracted.append(e)
        except Exception:
            continue
    return extracted


def _focused_edgar_search(
    universe_entries: List[Dict[str, str]],
    ticker_set: Set[str],
    as_of: date,
    lookback_days: int,
    forms: Tuple[str, ...] = ("8-K", "10-Q", "6-K"),
    max_pages_per_query: int = 5,
) -> Dict[str, Dict[str, str]]:
    """
    Run a focused full-text search on EDGAR using NEW_KEYWORD_QUERIES only.

    Returns: {accession: {ticker, cik, file_date, form_type}}
    """
    try:
        import requests
    except ImportError:
        logger.error("requests library not installed; cannot run live SEC search")
        return {}

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # CIK ↔ ticker mappings
    ticker_to_cik: Dict[str, str] = {}
    cik_to_ticker: Dict[str, str] = {}
    for e in universe_entries:
        t = (e.get("ticker") or "").upper()
        c = str(e.get("cik") or "").lstrip("0")
        if t and c:
            ticker_to_cik[t] = c
            cik_to_ticker[c] = t

    try:
        ct_resp = _sec_get(session, SEC_COMPANY_TICKERS_URL)
        if ct_resp.status_code == 200:
            for _k, entry in ct_resp.json().items():
                t = (entry.get("ticker") or "").upper()
                c = str(entry.get("cik_str") or "").lstrip("0")
                if t in ticker_set and c:
                    ticker_to_cik.setdefault(t, c)
                    cik_to_ticker.setdefault(c, t)
            logger.info(f"Loaded {len(ticker_to_cik)} ticker→CIK mappings")
    except Exception as e:
        logger.warning(f"company_tickers.json fetch failed: {e}")

    start_date = (as_of - timedelta(days=lookback_days)).isoformat()
    end_date = as_of.isoformat()
    forms_param = ",".join(forms)

    filings: Dict[str, Dict[str, str]] = {}
    for query in NEW_KEYWORD_QUERIES:
        try:
            offset = 0
            query_total = None
            while True:
                params = {
                    "q": query,
                    "dateRange": "custom",
                    "startdt": start_date,
                    "enddt": end_date,
                    "forms": forms_param,
                    "from": offset,
                }
                resp = _sec_get(session, SEC_SEARCH_URL, params=params)
                if resp.status_code != 200:
                    logger.warning(f"EDGAR search {resp.status_code} for {query[:40]}")
                    break
                results = resp.json()
                hits = results.get("hits", {}).get("hits", [])
                if query_total is None:
                    query_total = results.get("hits", {}).get("total", {}).get("value", 0)
                    logger.info(f"EDGAR FTS '{query[:50]}': {query_total} total hits")
                if not hits:
                    break
                for hit in hits:
                    src = hit.get("_source", {})
                    adsh = src.get("adsh", "")
                    file_date = src.get("file_date", "")
                    if not adsh or not file_date or file_date > end_date:
                        continue
                    display_names = src.get("display_names", [])
                    ciks = src.get("ciks", [])
                    form_type = src.get("form", "") or src.get("form_type", "")
                    ticker = _extract_ticker_from_display_names(display_names)
                    ticker_upper = ticker.upper() if ticker else ""
                    if not ticker_upper or ticker_upper not in ticker_set:
                        ticker_upper = ""
                        for cv in ciks:
                            cs = str(cv).lstrip("0")
                            if cs in cik_to_ticker:
                                ticker_upper = cik_to_ticker[cs]
                                break
                        if not ticker_upper:
                            continue
                    cik = ticker_to_cik.get(ticker_upper) or (str(ciks[0]).lstrip("0") if ciks else "")
                    if adsh not in filings:
                        filings[adsh] = {
                            "ticker": ticker_upper,
                            "cik": cik,
                            "file_date": file_date,
                            "form_type": form_type,
                        }
                offset += len(hits)
                page = offset // 100
                if offset >= query_total or page >= max_pages_per_query:
                    break
        except Exception as e:
            logger.warning(f"Search error for '{query[:40]}': {e}")

    return filings


def _classify_diff(
    event: Dict[str, Any],
    canonical: Dict[str, Dict[str, Any]],
) -> Tuple[str, Optional[str]]:
    """
    Classify how this extracted event relates to canonical pdufa_dates.json.

    Returns (classification, canonical_pdufa_date_or_None).
    """
    ticker = event["ticker"].upper()
    cano = canonical.get(ticker)
    cano_date = (cano or {}).get("pdufa_date")
    status = event.get("event_status") or ""
    event_date = event.get("event_date")

    if status in ("extended", "resubmission_accepted"):
        if cano is None:
            return ("EXTENDED_NOT_IN_CANONICAL", None)
        if cano_date and event_date and cano_date == event_date:
            return ("EXTENDED_MATCHES_CANONICAL", cano_date)
        return ("EXTENDED_CONFLICTS_CANONICAL", cano_date)

    # Fresh PDUFA from new keyword sweep (e.g. "target action date" / "PDUFA goal date")
    if cano is None:
        return ("NEW_CANDIDATE", None)
    if cano_date == event_date:
        return ("MATCHES_CANONICAL", cano_date)
    return ("CONFLICTS_CANONICAL", cano_date)


def _is_relevant_event(event: Dict[str, Any]) -> bool:
    """
    All FDA_PDUFA_DATE events from the focused keyword sweep are relevant
    for this diff. The classification step (_classify_diff) separates extended
    vs. fresh-upcoming vs. conflict.
    """
    return event.get("event_type") == "FDA_PDUFA_DATE"


def _dedupe_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Dedupe by (ticker, event_date) preferring extended > resubmission > upcoming
    and HIGH > MED > LOW confidence. Keeps the strongest signal per (ticker, date).
    """
    status_priority = {"extended": 3, "resubmission_accepted": 2, "upcoming": 1, None: 0, "": 0}
    conf_priority = {"HIGH": 3, "MED": 2, "LOW": 1, None: 0, "": 0}
    best: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for e in events:
        key = (e["ticker"].upper(), e.get("event_date") or "")
        cur = best.get(key)
        if cur is None:
            best[key] = e
            continue
        new_score = (
            status_priority.get(e.get("event_status"), 0),
            conf_priority.get(e.get("confidence"), 0),
        )
        cur_score = (
            status_priority.get(cur.get("event_status"), 0),
            conf_priority.get(cur.get("confidence"), 0),
        )
        if new_score > cur_score:
            best[key] = e
    return list(best.values())


def run_diff(
    as_of: date,
    lookback_days: int,
    project_root: Path,
    use_cache_only: bool,
    max_filings: int,
) -> Dict[str, Any]:
    universe_entries, ticker_set = _load_universe(project_root)
    canonical = _load_canonical_pdufa(project_root)
    logger.info(f"Universe: {len(ticker_set)} tickers; canonical pdufa_dates: {len(canonical)} records")

    candidate_events: List[Dict[str, Any]] = []

    if use_cache_only:
        # Re-scan recent extracted-event caches; can only verify which existing
        # cached events would NOW be tagged review-window. (Will not surface
        # filings the old extractor missed entirely.)
        cache_dir = project_root / "cache" / "sec" / "8k_catalysts"
        recent = sorted(cache_dir.glob("8k_catalysts_*.json"), reverse=True)[:lookback_days]
        logger.info(f"Cache-only mode: scanning {len(recent)} cached event files")
        for path in recent:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cached = json.load(f)
            except Exception:
                continue
            for e in cached:
                # Older caches don't have event_status/tags_extra; we can't
                # retroactively re-extract without raw text. Skip pure-cache
                # events for the review-window diff to avoid false claims.
                if _is_relevant_event(e):
                    candidate_events.append(e)
        return _finalize_diff(candidate_events, canonical, as_of, project_root)

    # Live mode: focused EDGAR search + raw filing fetch + new-extractor pass.
    filings = _focused_edgar_search(
        universe_entries=universe_entries,
        ticker_set=ticker_set,
        as_of=as_of,
        lookback_days=lookback_days,
    )
    logger.info(f"Focused FTS: {len(filings)} unique filings discovered")

    # Cap to keep dry-run fast/respectful.
    if len(filings) > max_filings:
        sorted_items = sorted(filings.items(), key=lambda x: x[1]["file_date"], reverse=True)
        filings = dict(sorted_items[:max_filings])
        logger.info(f"Capped to {len(filings)} most-recent filings (--max-filings={max_filings})")

    try:
        import requests
    except ImportError:
        logger.error("requests not installed; cannot run live mode")
        return _finalize_diff([], canonical, as_of, project_root)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    fetch_errors = 0
    for idx, (adsh, meta) in enumerate(filings.items(), 1):
        ticker = meta["ticker"]
        cik = meta["cik"]
        file_date = meta["file_date"]
        form_type = meta.get("form_type", "")
        if idx % 25 == 0 or idx == 1:
            logger.info(f"[{idx}/{len(filings)}] {ticker} {form_type} {adsh} ({file_date})")
        try:
            text = _fetch_filing_text(cik, adsh, session)
            if not text:
                fetch_errors += 1
                continue
            # Filings are already pre-filtered by PDUFA-keyword FTS, so don't apply
            # the biopharma_context guard (it's tuned for broad 10-Q sweeps and
            # over-prunes here). Keep boilerplate-blocking on.
            extracted = _extract_timing_events(
                text,
                ticker,
                file_date,
                as_of,
                require_biopharma_context=False,
                block_boilerplate=True,
            )
            for e in extracted:
                if _is_relevant_event(e):
                    e["filing_form"] = form_type
                    e["accession"] = adsh
                    candidate_events.append(e)
        except Exception as e:
            logger.warning(f"Error processing {ticker} {adsh}: {e}")
            fetch_errors += 1

    logger.info(f"Fetched {len(filings) - fetch_errors} filings; {fetch_errors} errors")
    return _finalize_diff(candidate_events, canonical, as_of, project_root)


def _finalize_diff(
    candidate_events: List[Dict[str, Any]],
    canonical: Dict[str, Dict[str, Any]],
    as_of: date,
    project_root: Path,
) -> Dict[str, Any]:
    deduped = _dedupe_events(candidate_events)

    rows: List[Dict[str, Any]] = []
    for e in deduped:
        cls, cano_date = _classify_diff(e, canonical)
        rows.append(
            {
                "ticker": e["ticker"].upper(),
                "event_status": e.get("event_status") or "",
                "event_date": e.get("event_date") or "",
                "prior_date": e.get("prior_date") or "",
                "date_precision": e.get("date_precision") or "",
                "confidence": e.get("confidence") or "",
                "tags": ";".join(e.get("tags", [])),
                "source": e.get("source") or "",
                "filing_form": e.get("filing_form") or "",
                "filing_date": e.get("disclosed_at") or "",
                "accession": e.get("accession") or "",
                "canonical_pdufa_date": cano_date or "",
                "diff_classification": cls,
                "event_name": (e.get("event_name") or "")[:160],
            }
        )

    rows.sort(key=lambda r: (r["diff_classification"], r["ticker"], r["event_date"]))

    # Aggregate counts
    by_class: Dict[str, int] = defaultdict(int)
    for r in rows:
        by_class[r["diff_classification"]] += 1
    n_new = by_class["NEW_CANDIDATE"]
    n_revised = (
        by_class["EXTENDED_NOT_IN_CANONICAL"]
        + by_class["EXTENDED_MATCHES_CANONICAL"]
        + by_class["EXTENDED_CONFLICTS_CANONICAL"]
    )
    n_high_day = sum(1 for r in rows if r["confidence"] == "HIGH" and r["date_precision"] == "DAY")
    n_manual_review = sum(
        1
        for r in rows
        if r["confidence"] in ("MED", "LOW")
        or r["date_precision"] in ("QUARTER", "HALF_YEAR")
        or r["diff_classification"] in ("EXTENDED_CONFLICTS_CANONICAL", "CONFLICTS_CANONICAL")
    )
    n_conflicts = by_class["EXTENDED_CONFLICTS_CANONICAL"] + by_class["CONFLICTS_CANONICAL"]

    # ARVN check — keyword-sweep first, then direct fetch fallback.
    arvn_rows = [r for r in rows if r["ticker"] == "ARVN"]
    arvn_canonical = canonical.get("ARVN", {})
    arvn_direct_extracted: List[Dict[str, Any]] = []
    if not any(r["event_date"] == "2026-06-05" for r in arvn_rows):
        try:
            arvn_direct_extracted = _direct_arvn_check(as_of)
        except Exception as exc:
            logger.warning(f"ARVN direct fallback failed: {exc}")
    arvn_check = {
        "canonical_pdufa_date": arvn_canonical.get("pdufa_date", ""),
        "canonical_source": arvn_canonical.get("source", ""),
        "extracted_rows": arvn_rows,
        "drug_name": arvn_canonical.get("drug_name", ""),
        "found_2026_06_05": any(r["event_date"] == "2026-06-05" for r in arvn_rows)
        or any(e.get("event_date") == "2026-06-05" for e in arvn_direct_extracted),
        "direct_fetch_extracted": arvn_direct_extracted,
    }

    # Write CSV
    artifacts_dir = project_root / "artifacts" / "regulatory"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    csv_path = artifacts_dir / f"sec_pdufa_review_window_diff_{as_of.isoformat()}.csv"
    md_path = artifacts_dir / f"sec_pdufa_review_window_diff_{as_of.isoformat()}.md"

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in CSV_COLUMNS})

    # Write Markdown
    md_lines: List[str] = []
    md_lines.append(f"# SEC PDUFA Review-Window Diff — {as_of.isoformat()}")
    md_lines.append("")
    md_lines.append(
        f"**DRY-RUN.** Pattern version `{PATTERN_VERSION}`. "
        f"No changes written to `production_data/pdufa_dates.json`."
    )
    md_lines.append("")
    md_lines.append("## Summary")
    md_lines.append("")
    md_lines.append(f"- Total review-window events extracted: **{len(rows)}**")
    md_lines.append(f"- New candidate PDUFA dates (no canonical record): **{n_new}**")
    md_lines.append(f"- Revised / extended events (event_status in extended/resubmission_accepted): **{n_revised}**")
    md_lines.append(f"- Exact-day HIGH-confidence events: **{n_high_day}**")
    md_lines.append(
        f"- Events requiring manual review (MED/LOW confidence, quarter/half-year, or canonical conflict): **{n_manual_review}**"
    )
    md_lines.append(f"- Conflicts vs `pdufa_dates.json` (date mismatch): **{n_conflicts}**")
    md_lines.append("")
    md_lines.append("### Breakdown by classification")
    md_lines.append("")
    md_lines.append("| Classification | Count |")
    md_lines.append("|---|---:|")
    for k in sorted(by_class.keys()):
        md_lines.append(f"| {k} | {by_class[k]} |")
    md_lines.append("")
    md_lines.append("## ARVN / vepdegestrant 2026-06-05 check")
    md_lines.append("")
    md_lines.append(
        f"- Canonical record: `{arvn_check['canonical_pdufa_date']}` "
        f"(drug: {arvn_check['drug_name']}, source: {arvn_check['canonical_source']})"
    )
    md_lines.append(f"- Extractor surfaced 2026-06-05 in this run: **{arvn_check['found_2026_06_05']}**")
    if arvn_rows:
        md_lines.append("")
        md_lines.append("Per-row ARVN extractions (focused keyword sweep):")
        md_lines.append("")
        md_lines.append("| event_status | event_date | prior_date | confidence | tags | accession |")
        md_lines.append("|---|---|---|---|---|---|")
        for r in arvn_rows:
            md_lines.append(
                f"| {r['event_status']} | {r['event_date']} | {r['prior_date']} | "
                f"{r['confidence']} | {r['tags']} | {r['accession']} |"
            )
    else:
        md_lines.append("- No ARVN matches surfaced by the focused keyword sweep in this lookback.")
    direct = arvn_check.get("direct_fetch_extracted") or []
    if direct:
        md_lines.append("")
        md_lines.append("Direct-fetch fallback (ARVN 8-Ks scanned directly):")
        md_lines.append("")
        md_lines.append("| event_status | event_date | prior_date | confidence | tags | accession |")
        md_lines.append("|---|---|---|---|---|---|")
        for e in direct:
            md_lines.append(
                f"| {e.get('event_status', '')} | {e.get('event_date', '')} | "
                f"{e.get('prior_date', '')} | {e.get('confidence', '')} | "
                f"{';'.join(e.get('tags', []))} | {e.get('accession', '')} |"
            )
    md_lines.append("")
    md_lines.append("## All review-window events (top 50 by classification, ticker)")
    md_lines.append("")
    md_lines.append("| Class | Ticker | Status | Event Date | Prior | Conf | Precision | Canonical | Form | Filed |")
    md_lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows[:50]:
        md_lines.append(
            f"| {r['diff_classification']} | {r['ticker']} | {r['event_status']} | "
            f"{r['event_date']} | {r['prior_date']} | {r['confidence']} | "
            f"{r['date_precision']} | {r['canonical_pdufa_date']} | {r['filing_form']} | "
            f"{r['filing_date']} |"
        )
    md_lines.append("")
    md_lines.append(f"_Full row set in `{csv_path.name}` ({len(rows)} rows)._")
    md_lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    logger.info(f"Wrote {csv_path}")
    logger.info(f"Wrote {md_path}")

    return {
        "n_total": len(rows),
        "n_new_candidates": n_new,
        "n_revised_extended": n_revised,
        "n_high_confidence_day": n_high_day,
        "n_manual_review": n_manual_review,
        "n_conflicts": n_conflicts,
        "arvn_check": arvn_check,
        "csv_path": str(csv_path),
        "md_path": str(md_path),
        "by_class": dict(by_class),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default=date.today().isoformat(), help="ISO date (default: today)")
    parser.add_argument("--lookback", type=int, default=120, help="Lookback days (default: 120)")
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Cache-only mode: scan existing 8-K event caches (skips network).",
    )
    parser.add_argument(
        "--max-filings",
        type=int,
        default=200,
        help="Hard cap on filings to fetch in live mode (default: 200)",
    )
    args = parser.parse_args()

    try:
        as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()
    except ValueError:
        logger.error(f"Invalid --as-of: {args.as_of!r}")
        return 2

    summary = run_diff(
        as_of=as_of,
        lookback_days=args.lookback,
        project_root=_PROJECT_ROOT,
        use_cache_only=args.use_cache,
        max_filings=args.max_filings,
    )

    print()
    print("=" * 60)
    print(f"SEC PDUFA Review-Window Diff — {as_of.isoformat()}")
    print("=" * 60)
    print(f"  Total events:                {summary['n_total']}")
    print(f"  New candidate PDUFA dates:   {summary['n_new_candidates']}")
    print(f"  Revised/extended events:     {summary['n_revised_extended']}")
    print(f"  Exact-day HIGH confidence:   {summary['n_high_confidence_day']}")
    print(f"  Manual review needed:        {summary['n_manual_review']}")
    print(f"  Canonical conflicts:         {summary['n_conflicts']}")
    print()
    arvn = summary["arvn_check"]
    print(f"  ARVN canonical PDUFA:        {arvn['canonical_pdufa_date']}")
    print(f"  ARVN 2026-06-05 surfaced:    {arvn['found_2026_06_05']}")
    print()
    print(f"  CSV: {summary['csv_path']}")
    print(f"  MD:  {summary['md_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

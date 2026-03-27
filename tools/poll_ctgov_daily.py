#!/usr/bin/env python3
"""CTgov daily trial status poller — detect meaningful trial transitions.

Polls the CT.gov API v2 for the universe tickers, diffs against the last
known trial_records cache, and writes a staging file with material changes.

Material transitions detected:
  - Phase advancement (e.g., Phase 2 → Phase 3)
  - Phase regression / protocol amendment
  - Trial termination / withdrawal / suspension
  - New enrollment status (recruiting → active_not_recruiting → completed)
  - Primary completion date shift (>= 14 days)
  - New trial appeared for a ticker
  - Trial status changed (any status field change)
  - Results posted (first results_first_posted date)

Read-only — does not modify the production cache. Writes a staging diff
that the pipeline can optionally ingest.

Output:
    artifacts/ctgov_daily/{date}_diff.json
    artifacts/ctgov_daily/{date}_diff.md

Usage:
    python tools/poll_ctgov_daily.py
    python tools/poll_ctgov_daily.py --as-of-date 2026-03-27
    python tools/poll_ctgov_daily.py --dry-run  # fetch + diff but don't write
    python tools/poll_ctgov_daily.py --cached-only  # diff against cache without API calls
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("ctgov_daily")

SCHEMA_VERSION = "ctgov_daily_diff.v1"
CACHE_DIR = REPO_ROOT / "cache" / "ctgov"
ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "ctgov_daily"

# Phase ordering for advancement detection
PHASE_ORDER = {
    "EARLY_PHASE1": 0,
    "PHASE1": 1,
    "PHASE1_PHASE2": 2,
    "PHASE2": 3,
    "PHASE2_PHASE3": 4,
    "PHASE3": 5,
    "PHASE4": 6,
    "NA": -1,
}

# Status transitions that are material
TERMINAL_STATUSES = {"TERMINATED", "WITHDRAWN", "SUSPENDED"}
COMPLETION_STATUSES = {"COMPLETED"}
ACTIVE_STATUSES = {"RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION", "NOT_YET_RECRUITING"}

# PCD shift threshold (days)
PCD_SHIFT_THRESHOLD = 14


# ---------------------------------------------------------------------------
# Load cached state
# ---------------------------------------------------------------------------
def load_latest_cache(cache_dir: Path) -> tuple:
    """Load the most recent trial_records cache. Returns (date, records_by_nct)."""
    candidates = sorted(p for p in cache_dir.glob("trial_records_*.json") if not p.name.endswith(".meta.json"))
    if not candidates:
        return None, {}
    latest = candidates[-1]
    cache_date = latest.stem.replace("trial_records_", "")

    with open(latest, encoding="utf-8") as f:
        records = json.load(f)

    by_nct: Dict[str, Dict] = {}
    for r in records:
        nct = r.get("nct_id")
        if nct:
            by_nct[nct] = r
    return cache_date, by_nct


def load_universe_tickers() -> Set[str]:
    """Load ticker set from universe.json."""
    path = REPO_ROOT / "production_data" / "universe.json"
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {r.get("ticker", "") for r in data if r.get("ticker")}


# ---------------------------------------------------------------------------
# Fetch from CT.gov API v2
# ---------------------------------------------------------------------------
def fetch_trials_for_ticker(ticker: str, sponsor_map: Dict[str, List[str]]) -> List[Dict]:
    """Fetch current trials for a ticker from CT.gov API v2."""
    import urllib.parse
    import urllib.request

    sponsors = sponsor_map.get(ticker, [ticker])
    all_trials = []

    for sponsor in sponsors:
        params = urllib.parse.urlencode(
            {
                "query.spons": sponsor,
                "pageSize": "100",
                "format": "json",
            }
        )
        url = f"https://clinicaltrials.gov/api/v2/studies?{params}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "biotech-screener/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())

            studies = data.get("studies", [])
            for study in studies:
                proto = study.get("protocolSection", {})
                ident = proto.get("identificationModule", {})
                status_mod = proto.get("statusModule", {})
                design = proto.get("designModule", {})
                conditions = proto.get("conditionsModule", {})
                sponsor_mod = proto.get("sponsorCollaboratorsModule", {})

                phases = design.get("phases", [])
                phase = phases[0] if phases else "NA"

                record = {
                    "ticker": ticker,
                    "nct_id": ident.get("nctId", ""),
                    "title": ident.get("briefTitle", ""),
                    "status": status_mod.get("overallStatus", ""),
                    "phase": phase,
                    "primary_completion_date": (status_mod.get("primaryCompletionDateStruct", {}).get("date", "")),
                    "pcd_type": (status_mod.get("primaryCompletionDateStruct", {}).get("type", "")),
                    "completion_date": (status_mod.get("completionDateStruct", {}).get("date", "")),
                    "last_update_posted": (status_mod.get("lastUpdatePostDateStruct", {}).get("date", "")),
                    "enrollment": (status_mod.get("enrollmentInfo", {}).get("count")),
                    "conditions": conditions.get("conditions", []),
                    "sponsor": sponsor_mod.get("leadSponsor", {}).get("name", ""),
                    "results_first_posted": (status_mod.get("resultsFirstPostDateStruct", {}).get("date", "")),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
                if record["nct_id"]:
                    all_trials.append(record)

        except Exception as e:
            logger.warning("Failed to fetch for %s (sponsor=%s): %s", ticker, sponsor, e)

    return all_trials


def load_sponsor_map() -> Dict[str, List[str]]:
    """Load ticker → sponsor name mapping from collect_ctgov_data.py."""
    try:
        from collect_ctgov_data import TICKER_TO_SPONSORS

        return dict(TICKER_TO_SPONSORS)
    except ImportError:
        return {}


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------
def classify_change(
    nct_id: str,
    cached: Optional[Dict],
    current: Dict,
) -> Optional[Dict[str, Any]]:
    """Classify the change for one trial. Returns change dict or None."""
    codes: List[str] = []
    details: Dict[str, Any] = {
        "nct_id": nct_id,
        "ticker": current.get("ticker", ""),
        "title": current.get("title", "")[:80],
    }

    if cached is None:
        codes.append("NEW_TRIAL")
        details["phase"] = current.get("phase", "")
        details["status"] = current.get("status", "")
        return {**details, "codes": codes}

    # Phase change
    c_phase = current.get("phase", "NA")
    p_phase = cached.get("phase", "NA")
    if c_phase != p_phase:
        c_ord = PHASE_ORDER.get(c_phase, -1)
        p_ord = PHASE_ORDER.get(p_phase, -1)
        if c_ord > p_ord and p_ord >= 0:
            codes.append("PHASE_ADVANCEMENT")
        elif c_ord < p_ord and c_ord >= 0:
            codes.append("PHASE_REGRESSION")
        else:
            codes.append("PHASE_CHANGED")
        details["prior_phase"] = p_phase
        details["current_phase"] = c_phase

    # Status change
    c_status = current.get("status", "")
    p_status = cached.get("status", "")
    if c_status != p_status:
        if c_status in TERMINAL_STATUSES:
            codes.append("TRIAL_TERMINATED")
        elif c_status in COMPLETION_STATUSES and p_status not in COMPLETION_STATUSES:
            codes.append("TRIAL_COMPLETED")
        elif c_status in ACTIVE_STATUSES and p_status not in ACTIVE_STATUSES:
            codes.append("BECAME_ACTIVE")
        elif p_status in ACTIVE_STATUSES and c_status not in ACTIVE_STATUSES:
            codes.append("BECAME_INACTIVE")
        else:
            codes.append("STATUS_CHANGED")
        details["prior_status"] = p_status
        details["current_status"] = c_status

    # PCD shift
    c_pcd = current.get("primary_completion_date", "")
    p_pcd = cached.get("primary_completion_date", "")
    if c_pcd and p_pcd and c_pcd != p_pcd:
        try:
            from datetime import datetime as dt

            # Handle partial dates (YYYY-MM or YYYY-MM-DD)
            c_d = (
                dt.strptime(c_pcd[:10], "%Y-%m-%d") if len(c_pcd) >= 10 else dt.strptime(c_pcd[:7] + "-01", "%Y-%m-%d")
            )
            p_d = (
                dt.strptime(p_pcd[:10], "%Y-%m-%d") if len(p_pcd) >= 10 else dt.strptime(p_pcd[:7] + "-01", "%Y-%m-%d")
            )
            shift_days = (c_d - p_d).days
            if abs(shift_days) >= PCD_SHIFT_THRESHOLD:
                codes.append("PCD_SHIFTED")
                details["prior_pcd"] = p_pcd
                details["current_pcd"] = c_pcd
                details["pcd_shift_days"] = shift_days
        except (ValueError, TypeError):
            pass

    # Results posted
    c_results = current.get("results_first_posted", "")
    p_results = cached.get("results_first_posted", "")
    if c_results and not p_results:
        codes.append("RESULTS_POSTED")
        details["results_date"] = c_results

    if not codes:
        return None

    details["codes"] = codes
    details["phase"] = current.get("phase", "")
    details["status"] = current.get("status", "")
    return details


def compute_diff(
    cached_by_nct: Dict[str, Dict],
    current_trials: List[Dict],
    universe_tickers: Set[str],
) -> List[Dict[str, Any]]:
    """Compute diff between cached and current trial state."""
    changes = []
    seen_ncts: Set[str] = set()

    for trial in current_trials:
        nct = trial.get("nct_id", "")
        ticker = trial.get("ticker", "")
        if not nct or ticker not in universe_tickers:
            continue

        seen_ncts.add(nct)
        cached = cached_by_nct.get(nct)
        change = classify_change(nct, cached, trial)
        if change:
            changes.append(change)

    return changes


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------
def format_diff_md(result: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"# CTgov Daily Diff — {result['as_of_date']}")
    lines.append("")
    lines.append(
        f"Cache: {result['cache_date']} | Polled: {result['n_tickers_polled']} tickers | "
        f"Trials: {result['n_trials_fetched']} | Changes: {result['n_changes']}"
    )
    lines.append("")

    changes = result.get("changes", [])
    if not changes:
        lines.append("No material trial changes detected.")
        lines.append("")
        return "\n".join(lines)

    # Group by code
    from collections import Counter

    code_counts = Counter()
    for c in changes:
        for code in c.get("codes", []):
            code_counts[code] += 1

    lines.append("## Change Summary")
    lines.append("")
    for code, count in code_counts.most_common():
        lines.append(f"- {code}: {count}")
    lines.append("")

    lines.append("## Changes")
    lines.append("")
    lines.append("| Ticker | NCT ID | Phase | Status | Codes | Detail |")
    lines.append("|--------|--------|-------|--------|-------|--------|")
    for c in changes:
        codes_str = ", ".join(c.get("codes", []))
        detail_parts = []
        if "prior_phase" in c:
            detail_parts.append(f"{c['prior_phase']}→{c['current_phase']}")
        if "prior_status" in c:
            detail_parts.append(f"{c['prior_status']}→{c['current_status']}")
        if "pcd_shift_days" in c:
            detail_parts.append(f"PCD {c['pcd_shift_days']:+d}d")
        if "results_date" in c:
            detail_parts.append(f"results {c['results_date']}")
        detail = "; ".join(detail_parts) if detail_parts else "-"
        lines.append(
            f"| {c['ticker']} | {c['nct_id']} | {c.get('phase', '')} | "
            f"{c.get('status', '')} | {codes_str} | {detail} |"
        )
    lines.append("")

    lines.append(f"*Generated: {result.get('generated_at', '')}*")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
def poll_ctgov_daily(
    as_of_date: Optional[str] = None,
    *,
    dry_run: bool = False,
    cached_only: bool = False,
    max_tickers: Optional[int] = None,
) -> Dict[str, Any]:
    """Poll CTgov API and compute diff against cache."""
    if as_of_date is None:
        as_of_date = date.today().isoformat()

    # Load cached state
    cache_date, cached_by_nct = load_latest_cache(CACHE_DIR)
    if not cache_date:
        return {"error": "no cached trial records found"}
    logger.info("Loaded cache: %s (%d trials)", cache_date, len(cached_by_nct))

    # Load universe
    universe = load_universe_tickers()
    if not universe:
        return {"error": "empty universe"}

    # Get tickers that have cached trials
    cached_tickers = {r.get("ticker") for r in cached_by_nct.values() if r.get("ticker")}
    poll_tickers = sorted(universe & cached_tickers)
    if max_tickers:
        poll_tickers = poll_tickers[:max_tickers]

    logger.info("Will poll %d tickers", len(poll_tickers))

    # Fetch current state (dedup by NCT ID)
    all_current: List[Dict] = []
    seen_ncts: Set[str] = set()
    if not cached_only:
        sponsor_map = load_sponsor_map()
        for i, ticker in enumerate(poll_tickers):
            trials = fetch_trials_for_ticker(ticker, sponsor_map)
            for t in trials:
                nct = t.get("nct_id", "")
                if nct and nct not in seen_ncts:
                    seen_ncts.add(nct)
                    all_current.append(t)
            if (i + 1) % 50 == 0:
                logger.info("  Fetched %d/%d tickers (%d unique trials)", i + 1, len(poll_tickers), len(all_current))
            time.sleep(0.2)  # Rate limit
        logger.info("Fetched %d unique trials for %d tickers", len(all_current), len(poll_tickers))
    else:
        # In cached-only mode, just compare two cache files
        logger.info("Cached-only mode: skipping API calls")
        # Use the latest cache as "current" — this mode is for testing the diff logic
        all_current = list(cached_by_nct.values())

    # Compute diff
    changes = compute_diff(cached_by_nct, all_current, universe)
    logger.info("Changes detected: %d", len(changes))

    result = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "cache_date": cache_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers_polled": len(poll_tickers),
        "n_trials_fetched": len(all_current),
        "n_changes": len(changes),
        "cached_only": cached_only,
        "changes": changes,
    }

    # Write artifacts
    if not dry_run:
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        json_path = ARTIFACTS_DIR / f"{as_of_date}_diff.json"
        md_path = ARTIFACTS_DIR / f"{as_of_date}_diff.md"

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)
        logger.info("Wrote %s", json_path)

        md_path.write_text(format_diff_md(result), encoding="utf-8")
        logger.info("Wrote %s", md_path)

        result["_json_path"] = str(json_path)
        result["_md_path"] = str(md_path)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="CTgov daily trial status poller")
    parser.add_argument("--as-of-date", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Fetch + diff but don't write artifacts")
    parser.add_argument("--cached-only", action="store_true", help="Diff two cache versions without API calls")
    parser.add_argument("--max-tickers", type=int, default=None, help="Limit number of tickers to poll (for testing)")
    args = parser.parse_args()

    result = poll_ctgov_daily(
        args.as_of_date,
        dry_run=args.dry_run,
        cached_only=args.cached_only,
        max_tickers=args.max_tickers,
    )

    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)

    logger.info(
        "CTgov daily: %d changes from %d trials (%d tickers)",
        result["n_changes"],
        result["n_trials_fetched"],
        result["n_tickers_polled"],
    )


if __name__ == "__main__":
    main()

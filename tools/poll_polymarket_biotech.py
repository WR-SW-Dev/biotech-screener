#!/usr/bin/env python3
"""poll_polymarket_biotech.py — Daily SHADOW collector for Polymarket biotech events.

Fetches active and recently-closed biotech-relevant prediction markets from
Polymarket's public Gamma API, matches them against today's catalyst calendar
in the latest snapshot, and writes a daily JSONL.

SHADOW / DIAGNOSTIC ONLY. No selector, no ranker, no Event EV scoring path.
No trading endpoints. No authenticated endpoints. Read-only.

Failure mode: API errors / timeouts / parse failures all log a warning and
exit 0 with no output file. Idempotent — re-running on the same day overwrites
the day's JSONL with current snapshot of PM state.

Usage:
    python tools/poll_polymarket_biotech.py --dry-run
    python tools/poll_polymarket_biotech.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("poll_polymarket_biotech")

REPO = Path(__file__).resolve().parents[1]
SNAPSHOTS_DIR = REPO / "data" / "snapshots"
OUT_DIR = REPO / "data" / "polymarket"

GAMMA_BASE = "https://gamma-api.polymarket.com"
TAG_SLUGS = ["fda", "medicine", "drug", "science"]
SCIENCE_KEYWORDS = ("fda", "approve", "phase", "trial", "drug", "vaccine", "pdufa", "adcom")
HTTP_TIMEOUT = 12
MAX_EVENTS_PER_TAG = 100
RECENT_CLOSED_DAYS = 30

COMPANY_STOPWORDS = {
    "inc", "inc.", "corp", "corp.", "corporation", "co", "co.", "ltd", "plc",
    "therapeutics", "biosciences", "pharmaceuticals", "pharma", "biotech",
    "holdings", "labs", "laboratories", "sciences", "n.v.", "nv", "se", "ag",
}


def _safe_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _company_tokens(name: str) -> List[str]:
    """Extract significant tokens from a company name (lowercased, stopwords removed)."""
    if not name:
        return []
    n = name.lower().replace(",", " ").replace(".", " ")
    return [t for t in n.split() if len(t) >= 3 and t not in COMPANY_STOPWORDS]


def _fetch_events_for_tag(tag_slug: str) -> List[Dict[str, Any]]:
    """Fetch up to MAX_EVENTS_PER_TAG events for a tag. Returns [] on any error."""
    url = f"{GAMMA_BASE}/events"
    params = {"limit": MAX_EVENTS_PER_TAG, "tag_slug": tag_slug}
    try:
        r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        d = r.json()
        if not isinstance(d, list):
            logger.warning("tag=%s returned non-list: %r", tag_slug, type(d).__name__)
            return []
        return d
    except (requests.RequestException, ValueError) as e:
        logger.warning("tag=%s fetch failed: %s", tag_slug, e)
        return []


def _is_biotech_relevant(event: Dict[str, Any], tag_slug: str) -> bool:
    """Filter event to biotech-relevant. Strict keyword match for noisy 'science' tag."""
    if tag_slug == "science":
        title = (event.get("title") or "").lower()
        return any(k in title for k in SCIENCE_KEYWORDS)
    return True


def _is_recent_or_active(event: Dict[str, Any], today: date) -> bool:
    """Keep active events + recently-closed (last RECENT_CLOSED_DAYS)."""
    if event.get("active") and not event.get("closed"):
        return True
    end = event.get("endDate")
    if not end:
        return False
    try:
        end_d = datetime.fromisoformat(end.replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return False
    return (today - end_d).days <= RECENT_CLOSED_DAYS


def _classify_match(
    pm_event: Dict[str, Any],
    pm_market: Dict[str, Any],
    cal_row: Dict[str, str],
    today: date,
) -> Optional[str]:
    """Return match confidence: HIGH/MEDIUM/LOW or None for REJECT.

    HIGH:    company token in PM title AND |end_date - cat_date| <= 14 days
    MEDIUM:  company token in PM title AND |date delta| 15-60 days
    LOW:     company token in PM title (any date)
    REJECT:  no company token match
    """
    title = (pm_event.get("title") or pm_market.get("question") or "").lower()
    if not title:
        return None
    toks = _company_tokens(cal_row.get("company_name", ""))
    if not toks or not any(t in title for t in toks):
        return None
    pm_end = pm_event.get("endDate") or pm_market.get("endDate") or ""
    cat_date = cal_row.get("next_catalyst_date") or ""
    try:
        pm_d = datetime.fromisoformat(pm_end.replace("Z", "+00:00")).date()
        cat_d = date.fromisoformat(cat_date)
        delta = abs((pm_d - cat_d).days)
    except (TypeError, ValueError):
        return "LOW"
    if delta <= 14:
        return "HIGH"
    if delta <= 60:
        return "MEDIUM"
    return "LOW"


def _resolution_rule_hash(pm_market: Dict[str, Any], pm_event: Dict[str, Any]) -> str:
    """Hash question + description so PM-side rule changes are detectable."""
    payload = (pm_market.get("question") or "") + "||" + (
        pm_market.get("description") or pm_event.get("description") or ""
    )
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:16]


def _yes_prob(pm_market: Dict[str, Any]) -> Optional[float]:
    """Resolve YES probability via outcomes index, not positional."""
    outs = pm_market.get("outcomes")
    prices = pm_market.get("outcomePrices")
    if isinstance(outs, str):
        try:
            outs = json.loads(outs)
        except (TypeError, ValueError):
            outs = None
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except (TypeError, ValueError):
            prices = None
    if not isinstance(outs, list) or not isinstance(prices, list):
        return None
    for i, o in enumerate(outs):
        if isinstance(o, str) and o.lower() == "yes" and i < len(prices):
            return _safe_float(prices[i])
    return None


def _latest_snapshot_dir() -> Optional[Path]:
    if not SNAPSHOTS_DIR.exists():
        return None
    candidates = sorted(
        d for d in SNAPSHOTS_DIR.iterdir()
        if d.is_dir() and not d.name.startswith("_") and "__pre" not in d.name
        and (d / "rankings.csv").exists()
    )
    return candidates[-1] if candidates else None


def _load_calendar() -> List[Dict[str, str]]:
    snap = _latest_snapshot_dir()
    if not snap:
        logger.warning("No snapshot with rankings.csv found in %s", SNAPSHOTS_DIR)
        return []
    rows: List[Dict[str, str]] = []
    with open(snap / "rankings.csv") as f:
        for r in csv.DictReader(f):
            if r.get("has_catalyst_signal") in ("1", "True", "true") and r.get("next_catalyst_date"):
                rows.append(r)
    logger.info("Loaded %d calendar rows from %s", len(rows), snap.name)
    return rows


def _model_p_hit(cal_row: Dict[str, str]) -> Optional[float]:
    """Return our internal p_hit if available in the snapshot row.

    Conservative — current production rankings.csv does not export a clean
    per-ticker p_hit; the EV layer's p_hit is computed elsewhere and not
    joined back. Returns None for now so the gap field is honest about
    its absence. Update when the EV outcome binder lands.
    """
    return None


def _collect() -> List[Dict[str, Any]]:
    today = date.today()
    pm_events: Dict[str, Dict[str, Any]] = {}
    for tag in TAG_SLUGS:
        for e in _fetch_events_for_tag(tag):
            if not _is_biotech_relevant(e, tag):
                continue
            if not _is_recent_or_active(e, today):
                continue
            eid = str(e.get("id") or e.get("slug") or "")
            if not eid or eid in pm_events:
                continue
            pm_events[eid] = e
    logger.info("Polymarket biotech events (active + recent-closed): %d", len(pm_events))

    calendar = _load_calendar()
    asof_ts = datetime.now(timezone.utc).isoformat()

    out: List[Dict[str, Any]] = []
    for eid, e in pm_events.items():
        markets = e.get("markets") or []
        if not isinstance(markets, list):
            continue
        for m in markets:
            if not isinstance(m, dict):
                continue
            best = None
            for cal_row in calendar:
                conf = _classify_match(e, m, cal_row, today)
                if conf is None:
                    continue
                rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}[conf]
                if best is None or rank > best[0]:
                    best = (rank, conf, cal_row)
            yes_prob = _yes_prob(m)
            no_prob = (1.0 - yes_prob) if yes_prob is not None else None
            bid = _safe_float(m.get("bestBid"))
            ask = _safe_float(m.get("bestAsk"))
            spread = (ask - bid) if (bid is not None and ask is not None) else None
            mid = ((ask + bid) / 2.0) if (bid is not None and ask is not None) else None
            row: Dict[str, Any] = {
                "as_of_ts": asof_ts,
                "polymarket_event_id": eid,
                "polymarket_market_id": str(m.get("id") or ""),
                "polymarket_slug": e.get("slug") or m.get("slug"),
                "polymarket_question": m.get("question") or e.get("title"),
                "polymarket_yes_prob": yes_prob,
                "polymarket_no_prob": no_prob,
                "polymarket_mid_yes": mid,
                "polymarket_bid_yes": bid,
                "polymarket_ask_yes": ask,
                "polymarket_spread": spread,
                "polymarket_volume": _safe_float(m.get("volumeNum") or m.get("volume")),
                "polymarket_liquidity": _safe_float(m.get("liquidityNum") or m.get("liquidity")),
                "polymarket_open_interest": _safe_float(e.get("openInterest")),
                "polymarket_resolution_date": e.get("endDate") or m.get("endDate"),
                "polymarket_resolution_rule_hash": _resolution_rule_hash(m, e),
                "polymarket_match_confidence": "REJECT",
                "matched_ticker": None,
                "matched_company": None,
                "matched_catalyst_date": None,
                "matched_event_type": None,
                "model_p_hit": None,
                "model_minus_polymarket_p_hit": None,
            }
            if best is not None:
                _, conf, cal_row = best
                row["polymarket_match_confidence"] = conf
                row["matched_ticker"] = cal_row.get("ticker")
                row["matched_company"] = cal_row.get("company_name")
                row["matched_catalyst_date"] = cal_row.get("next_catalyst_date")
                row["matched_event_type"] = cal_row.get("catalyst_event_type")
            out.append(row)

    # Multi-program ambiguity gate: a ticker matched by ≥2 PM markets cannot
    # be HIGH because we have no drug-name binding on the calendar side.
    # Demote all of that ticker's HIGH matches to MEDIUM. Keeps semantics
    # honest without an alias map.
    ticker_match_counts: Dict[str, int] = {}
    for r in out:
        t = r.get("matched_ticker")
        if t and r.get("polymarket_match_confidence") != "REJECT":
            ticker_match_counts[t] = ticker_match_counts.get(t, 0) + 1
    for r in out:
        t = r.get("matched_ticker")
        if t and ticker_match_counts.get(t, 0) >= 2 and r.get("polymarket_match_confidence") == "HIGH":
            r["polymarket_match_confidence"] = "MEDIUM"
            r["match_demoted_reason"] = "multi_program_ambiguity"

    # Populate model gap only for HIGH/MEDIUM after gating
    for r in out:
        conf = r.get("polymarket_match_confidence")
        if conf in ("HIGH", "MEDIUM") and r.get("matched_ticker"):
            cal_row = next((c for c in calendar if c.get("ticker") == r["matched_ticker"]), None)
            if cal_row is not None:
                p_hit = _model_p_hit(cal_row)
                r["model_p_hit"] = p_hit
                yp = r.get("polymarket_yes_prob")
                if p_hit is not None and yp is not None:
                    r["model_minus_polymarket_p_hit"] = p_hit - yp
    return out


def _write(rows: List[Dict[str, Any]], today: date) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"shadow_{today.isoformat()}.jsonl"
    with open(out_path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":"), sort_keys=True) + "\n")
    return out_path


def _summarize(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "REJECT": 0}
    for r in rows:
        c = r.get("polymarket_match_confidence", "REJECT")
        counts[c] = counts.get(c, 0) + 1
    return counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Report only; do not write JSONL")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    try:
        rows = _collect()
    except Exception as e:  # fail soft
        logger.warning("Collector failed: %s", e)
        return 0

    counts = _summarize(rows)
    print(f"Polymarket biotech rows: {len(rows)}  HIGH={counts['HIGH']}  MEDIUM={counts['MEDIUM']}  LOW={counts['LOW']}  REJECT={counts['REJECT']}")
    for r in rows:
        if r["polymarket_match_confidence"] in ("HIGH", "MEDIUM"):
            print(
                f"  {r['polymarket_match_confidence']:6s}  {r['matched_ticker']:6s}  "
                f"yes_prob={r['polymarket_yes_prob']}  vol=${r['polymarket_volume'] or 0:,.0f}  "
                f"\"{(r['polymarket_question'] or '')[:60]}\"  end={(r['polymarket_resolution_date'] or '')[:10]}"
            )

    if args.dry_run:
        print("DRY-RUN: no JSONL written.")
        return 0

    today = date.today()
    out_path = _write(rows, today)
    print(f"Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

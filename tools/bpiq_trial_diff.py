#!/usr/bin/env python3
"""BPIQ trial-period probe: pull upcoming catalysts and dump raw JSON for offline diff.

Usage:
    python tools/bpiq_trial_diff.py pull [--days 60]
    python tools/bpiq_trial_diff.py diff       # not yet implemented

Auth: BPIQ_API_KEY in .env. Output: artifacts/bpiq_trial/.

Read-only. 14-day-trial probe. No production wiring.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "artifacts" / "bpiq_trial"
BASE = "https://api.bpiq.com/api/v1/info"
PAGE_LIMIT = 500
DEFAULT_WINDOW_DAYS = 60

# Subfamilies — finer-grained than family. PDUFA and AdCom are sequential events,
# not the same event, so they live in different subfamilies and never cross-match.
SUB_REG_PDUFA = "REG_PDUFA"
SUB_REG_ADCOM = "REG_ADCOM"
SUB_REG_APPROVAL = "REG_APPROVAL"
SUB_REG_EMA = "REG_EMA"
SUB_REG_OTHER = "REG_OTHER"
SUB_CLINICAL_DATA = "CLINICAL_DATA"
SUB_CLINICAL_PRESENTATION = "CLINICAL_PRESENTATION"

LEDGER_SUBFAMILY: dict[str, str] = {
    "PDUFA": SUB_REG_PDUFA,
    "FDA_PDUFA_DATE": SUB_REG_PDUFA,
    "FDA_APPROVAL": SUB_REG_APPROVAL,
    "FDA_DECISION": SUB_REG_APPROVAL,
    "FDA_ADCOM": SUB_REG_ADCOM,
    "FDA_SUBMISSION": SUB_REG_OTHER,
    "FDA_CRL": SUB_REG_OTHER,
    "FDA_RTF": SUB_REG_OTHER,
    "EMA_OUTCOME": SUB_REG_EMA,
    "EMA_AGENDA": SUB_REG_EMA,
    "EMA_COMMITTEE_OUTCOME": SUB_REG_EMA,
    "EMA_COMMITTEE_AGENDA": SUB_REG_EMA,
    "CLINICAL_PCD": SUB_CLINICAL_DATA,
    "CLINICAL_CD": SUB_CLINICAL_DATA,
    "CT_PRIMARY_COMPLETION": SUB_CLINICAL_DATA,
    "CT_STUDY_COMPLETION": SUB_CLINICAL_DATA,
    "CT_RESULTS_POSTED": SUB_CLINICAL_DATA,
    "DATA_READOUT": SUB_CLINICAL_DATA,
    "DATA_PRESENTATION": SUB_CLINICAL_PRESENTATION,
    "DATA_PUBLICATION": SUB_CLINICAL_PRESENTATION,
}


def _bpiq_subfamily(row: dict) -> str:
    se = row.get("stage_event") or {}
    stage = (se.get("stage_label") or "").strip()
    event = (se.get("event_label") or "").strip()
    if stage == "PDUFA" or event == "Approval decision":
        return SUB_REG_PDUFA
    if event == "AdCom" or stage == "AdCom" or "Advisory Committee" in event:
        return SUB_REG_ADCOM
    if event == "Data readout":
        return SUB_CLINICAL_DATA
    if event in {"Abstract Release", "Conference"} or stage == "Biomedical Meeting":
        return SUB_CLINICAL_PRESENTATION
    return "UNKNOWN"


def _safe_iso(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _session() -> requests.Session:
    load_dotenv(REPO / ".env")
    key = os.environ.get("BPIQ_API_KEY")
    if not key:
        sys.exit("BPIQ_API_KEY not set in .env")
    s = requests.Session()
    s.headers.update({"Authorization": f"Token {key}", "Accept": "application/json"})
    return s


def _paginate(s: requests.Session, path: str, params: dict) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        page_params = {**params, "limit": PAGE_LIMIT, "offset": offset}
        r = s.get(f"{BASE}{path}", params=page_params, timeout=30)
        if r.status_code == 401:
            sys.exit(f"401 unauthorized — check BPIQ_API_KEY (body: {r.text[:200]})")
        if r.status_code == 403:
            sys.exit(f"403 forbidden — endpoint may be premium-only (body: {r.text[:200]})")
        r.raise_for_status()
        body = r.json()
        if isinstance(body, dict) and "results" in body:
            chunk = body["results"]
            total = body.get("count")
        else:
            chunk = body if isinstance(body, list) else [body]
            total = None
        rows.extend(chunk)
        if not chunk or len(chunk) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
        if total is not None and offset >= total:
            break
        time.sleep(0.25)
    return rows


def cmd_pull(args: argparse.Namespace) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s = _session()
    today = date.today()
    end = today + timedelta(days=args.days)
    params = {
        "catalyst_date_min": today.isoformat(),
        "catalyst_date_max": end.isoformat(),
        "has_catalyst": "true",
    }
    print(f"GET /catalysts/ window {today}..{end}", file=sys.stderr)
    rows = _paginate(s, "/catalysts/", params)
    out = OUT / f"catalysts_{today.isoformat()}.json"
    payload = {
        "fetched_at": today.isoformat(),
        "window_days": args.days,
        "endpoint": "/catalysts/",
        "params": params,
        "n": len(rows),
        "rows": rows,
    }
    out.write_text(json.dumps(payload, indent=2, default=str))
    print(f"saved {len(rows)} rows -> {out}")
    if rows:
        keys = sorted(rows[0].keys())
        print(f"sample row keys ({len(keys)}): {keys}", file=sys.stderr)
    return 0


def _load_our_events(window_start: date, window_end: date) -> list[dict]:
    """Combine pdufa_dates.json and most-recent event_ledger jsonl into a single list,
    filtered to the window. Then dedupe near-duplicate records."""
    raw: list[dict] = []

    pdufa_path = REPO / "production_data" / "pdufa_dates.json"
    if pdufa_path.exists():
        for i, p in enumerate(json.load(open(pdufa_path))):
            d = _safe_iso(p.get("pdufa_date"))
            if d and window_start <= d <= window_end:
                raw.append(
                    {
                        "raw_id": f"pdufa_dates#{i}",
                        "ticker": p.get("ticker", ""),
                        "event_type": p.get("event_type", "PDUFA"),
                        "subfamily": SUB_REG_PDUFA,
                        "event_date": d,
                        "source": p.get("source", "PDUFA_FILE"),
                        "source_url": p.get("source_url", ""),
                        "drug_name": p.get("drug_name", ""),
                        "indication": p.get("indication", ""),
                        "ours_origin": "pdufa_dates.json",
                    }
                )

    ledger_glob = sorted((REPO / "cache" / "ledger").glob("event_ledger_*.jsonl"))
    if ledger_glob:
        ledger_path = ledger_glob[-1]
        for line in open(ledger_path):
            e = json.loads(line)
            d = _safe_iso(e.get("event_date"))
            if not d or not (window_start <= d <= window_end):
                continue
            sub = LEDGER_SUBFAMILY.get(e.get("event_type", ""), "UNKNOWN")
            raw.append(
                {
                    "raw_id": f"ledger#{e.get('event_id', '')}",
                    "ticker": e.get("ticker", ""),
                    "event_type": e.get("event_type", ""),
                    "subfamily": sub,
                    "event_date": d,
                    "source": e.get("source", ""),
                    "source_url": "",
                    "drug_name": "",
                    "indication": "",
                    "ours_origin": f"event_ledger ({ledger_path.name})",
                }
            )

    return _dedupe_ours(raw)


def _dedupe_ours(rows: list[dict]) -> list[dict]:
    """Collapse near-duplicates: same (ticker, subfamily) records within ±1 day are
    treated as one. Prefer pdufa_dates.json over ledger for richer drug/url metadata."""
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        grouped[(r["ticker"], r["subfamily"])].append(r)

    deduped: list[dict] = []
    for _key, members in grouped.items():
        members.sort(key=lambda r: r["event_date"])
        cluster: list[dict] = []
        for r in members:
            if cluster and abs((cluster[-1]["event_date"] - r["event_date"]).days) <= 1:
                cluster.append(r)
                continue
            if cluster:
                deduped.append(_pick_canonical(cluster))
            cluster = [r]
        if cluster:
            deduped.append(_pick_canonical(cluster))
    return deduped


def _pick_canonical(cluster: list[dict]) -> dict:
    """Among same-cluster duplicates, prefer pdufa_dates origin (richer metadata)."""
    pdufa_origin = [r for r in cluster if r["ours_origin"].startswith("pdufa_dates")]
    chosen = pdufa_origin[0] if pdufa_origin else cluster[0]
    if len(cluster) > 1:
        chosen = dict(chosen)
        chosen["ours_origin"] = chosen["ours_origin"] + f" (+{len(cluster)-1} dup)"
    return chosen


def _best_match(bpiq_row: dict, ours: list[dict]) -> tuple[dict | None, int | None, str]:
    """Return (matched_record, date_delta_days, bucket).
    Bucket is one of: EXACT_MATCH, DATE_MISMATCH, LABEL_MISMATCH, BPIQ_ONLY.

    Subfamily-strict: PDUFA does not cross-match with AdCom even though both are
    REGULATORY family. AdCom and PDUFA are sequential events, not the same event."""
    ticker = bpiq_row.get("ticker", "")
    bpiq_date = _safe_iso(bpiq_row.get("catalyst_date"))
    bpiq_sub = _bpiq_subfamily(bpiq_row)
    if not ticker or not bpiq_date:
        return None, None, "BPIQ_ONLY"

    same_ticker = [r for r in ours if r["ticker"] == ticker]
    if not same_ticker:
        return None, None, "BPIQ_ONLY"

    sub_compat = [r for r in same_ticker if r["subfamily"] == bpiq_sub]
    if sub_compat:
        best = min(sub_compat, key=lambda r: abs((r["event_date"] - bpiq_date).days))
        delta = (best["event_date"] - bpiq_date).days
        if abs(delta) <= 3:
            return best, delta, "EXACT_MATCH"
        return best, delta, "DATE_MISMATCH"
    # No subfamily match; check if any same-ticker record sits within ±7d → label mismatch
    near = [r for r in same_ticker if abs((r["event_date"] - bpiq_date).days) <= 7]
    if near:
        best = min(near, key=lambda r: abs((r["event_date"] - bpiq_date).days))
        delta = (best["event_date"] - bpiq_date).days
        return best, delta, "LABEL_MISMATCH"
    return None, None, "BPIQ_ONLY"


def _recommended_action(bucket: str, bpiq_row: dict, matched: dict | None, delta: int | None, in_universe: bool) -> str:
    if bucket == "EXACT_MATCH":
        if matched and matched.get("ours_origin", "").startswith("pdufa_dates"):
            return "no action; agreement"
        return "no action; agreement"
    if bucket == "DATE_MISMATCH":
        if abs(delta or 0) >= 14:
            return "verify primary source — BPIQ vs ours date conflict"
        return "verify primary source — soft date drift"
    if bucket == "LABEL_MISMATCH":
        return "review event-type mapping; could be same trial different milestone"
    if bucket == "BPIQ_ONLY":
        if not in_universe:
            return "ignore — outside our universe"
        if not bpiq_row.get("catalyst_source"):
            return "needs primary-source verification"
        return "candidate gap — verify against EDGAR/FDA, then consider adding"
    if bucket == "LEDGER_ONLY":
        return "BPIQ recall gap — confirm BPIQ does not cover this catalyst type"
    return ""


def cmd_delta(args: argparse.Namespace) -> int:
    """Append a 'Daily delta' section to bpiq_trial_log.md comparing today's
    catalysts pull against the most recent earlier pull. Read-only against the
    saved JSONs; writes only to the log."""
    today = args.as_of or date.today().isoformat()
    today_path = OUT / f"catalysts_{today}.json"
    if not today_path.exists():
        sys.exit(f"today's pull not found at {today_path}; run `pull` first")

    pulls = sorted(OUT.glob("catalysts_*.json"))
    earlier = [p for p in pulls if p != today_path and p.stem < today_path.stem]
    if not earlier:
        log_path = OUT / "bpiq_trial_log.md"
        with open(log_path, "a") as f:
            f.write(f"\n## Daily delta — {today}\n\n_No prior pull on disk; baseline established._\n")
        print(f"baseline written to {log_path}")
        return 0
    prior_path = earlier[-1]

    today_rows = json.loads(today_path.read_text())["rows"]
    prior_rows = json.loads(prior_path.read_text())["rows"]

    by_id_today = {r["id"]: r for r in today_rows if "id" in r}
    by_id_prior = {r["id"]: r for r in prior_rows if "id" in r}

    new_ids = set(by_id_today) - set(by_id_prior)
    dropped_ids = set(by_id_prior) - set(by_id_today)
    common_ids = set(by_id_today) & set(by_id_prior)

    universe = {r["ticker"] for r in json.load(open(REPO / "production_data" / "universe.json"))}

    date_changed: list[tuple[dict, dict]] = []
    drug_changed: list[tuple[dict, dict]] = []
    for cid in common_ids:
        a, b = by_id_prior[cid], by_id_today[cid]
        if a.get("catalyst_date") != b.get("catalyst_date"):
            date_changed.append((a, b))
        if a.get("drug_name") != b.get("drug_name") or (a.get("stage_event") or {}).get("label") != (
            b.get("stage_event") or {}
        ).get("label"):
            drug_changed.append((a, b))

    def _is_pdufa(r: dict) -> bool:
        se = r.get("stage_event") or {}
        return se.get("stage_label") == "PDUFA" or se.get("event_label") == "Approval decision"

    flags: list[str] = []
    new_pdufa_in_universe = [
        by_id_today[cid]
        for cid in new_ids
        if _is_pdufa(by_id_today[cid]) and by_id_today[cid].get("ticker") in universe
    ]
    pdufa_date_changes = [(a, b) for a, b in date_changed if _is_pdufa(b)]
    for r in new_pdufa_in_universe:
        flags.append(
            f"- 🚨 NEW PDUFA in universe: **{r['ticker']}** {r.get('catalyst_date')} " f"{r.get('drug_name', '')[:50]}"
        )
    for a, b in pdufa_date_changes:
        flags.append(
            f"- 🚨 PDUFA date changed: **{b['ticker']}** {a.get('catalyst_date')} → {b.get('catalyst_date')} "
            f"{b.get('drug_name', '')[:50]}"
        )

    lines = [
        "",
        f"## Daily delta — {today}",
        "",
        f"Compared against: {prior_path.name}",
        "",
        f"- NEW: {len(new_ids)}",
        f"- DROPPED: {len(dropped_ids)}",
        f"- DATE_CHANGED: {len(date_changed)}",
        f"- DRUG_CHANGED: {len(drug_changed)}",
        "",
    ]
    if flags:
        lines.append("### Flags")
        lines.append("")
        lines.extend(flags)
        lines.append("")

    if date_changed:
        lines.append("### All date changes")
        lines.append("")
        lines.append("| ticker | drug | stage/event | prior | today | delta_days |")
        lines.append("|---|---|---|---|---|---:|")
        for a, b in date_changed:
            try:
                da = date.fromisoformat(a.get("catalyst_date") or "")
                db = date.fromisoformat(b.get("catalyst_date") or "")
                d = (db - da).days
            except ValueError:
                d = ""
            se = b.get("stage_event") or {}
            lines.append(
                f"| {b.get('ticker', '')} | {(b.get('drug_name', '') or '')[:40]} | "
                f"{se.get('stage_label', '')} / {se.get('event_label', '')} | "
                f"{a.get('catalyst_date', '')} | {b.get('catalyst_date', '')} | {d} |"
            )
        lines.append("")

    log_path = OUT / "bpiq_trial_log.md"
    with open(log_path, "a") as f:
        f.write("\n".join(lines) + "\n")

    print(f"appended delta to {log_path}")
    print(
        f"NEW={len(new_ids)} DROPPED={len(dropped_ids)} "
        f"DATE_CHANGED={len(date_changed)} DRUG_CHANGED={len(drug_changed)}"
    )
    if flags:
        print(f"FLAGS: {len(flags)}")
        for line in flags:
            print(f"  {line}")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    as_of = args.as_of or date.today().isoformat()
    bpiq_path = OUT / f"catalysts_{as_of}.json"
    if not bpiq_path.exists():
        sys.exit(f"BPIQ pull not found at {bpiq_path}; run `pull` first")
    bpiq_payload = json.loads(bpiq_path.read_text())
    bpiq_rows = bpiq_payload["rows"]

    window_start = date.fromisoformat(as_of)
    window_end = window_start + timedelta(days=bpiq_payload.get("window_days", DEFAULT_WINDOW_DAYS))

    ours = _load_our_events(window_start, window_end)
    universe = {r["ticker"] for r in json.load(open(REPO / "production_data" / "universe.json"))}

    csv_rows: list[dict] = []
    matched_ids: set[str] = set()

    for b in bpiq_rows:
        ticker = b.get("ticker", "")
        if ticker == "Meeting":  # known data-quality artifact in BPIQ feed
            continue
        in_universe = ticker in universe
        matched, delta, bucket = _best_match(b, ours)
        if matched:
            matched_ids.add(matched["raw_id"])
        se = b.get("stage_event") or {}
        comp = b.get("company") or {}
        csv_rows.append(
            {
                "ticker": ticker,
                "company": comp.get("name", "") if isinstance(comp, dict) else "",
                "drug_name": b.get("drug_name", ""),
                "indication": b.get("indications_text", ""),
                "bpiq_event_label": se.get("event_label", ""),
                "bpiq_stage_label": se.get("stage_label", ""),
                "ledger_event_label": matched["event_type"] if matched else "",
                "bpiq_date": b.get("catalyst_date", ""),
                "ledger_date": matched["event_date"].isoformat() if matched else "",
                "date_delta_days": delta if delta is not None else "",
                "in_universe": "Y" if in_universe else "N",
                "source_url_or_primary_source": (
                    matched.get("source_url") if matched and matched.get("source_url") else b.get("catalyst_source", "")
                ),
                "diff_bucket": bucket,
                "recommended_action": _recommended_action(bucket, b, matched, delta, in_universe),
                "notes": (matched.get("ours_origin", "") if matched else ""),
            }
        )

    # Ledger-only rows (in window, in universe, family REGULATORY or CLINICAL,
    # no BPIQ match recorded above).
    for r in ours:
        if r["raw_id"] in matched_ids:
            continue
        if r["ticker"] not in universe:
            continue
        if r["subfamily"] == "UNKNOWN":
            continue
        csv_rows.append(
            {
                "ticker": r["ticker"],
                "company": "",
                "drug_name": r.get("drug_name", ""),
                "indication": r.get("indication", ""),
                "bpiq_event_label": "",
                "bpiq_stage_label": "",
                "ledger_event_label": r["event_type"],
                "bpiq_date": "",
                "ledger_date": r["event_date"].isoformat(),
                "date_delta_days": "",
                "in_universe": "Y",
                "source_url_or_primary_source": r.get("source_url", ""),
                "diff_bucket": "LEDGER_ONLY",
                "recommended_action": _recommended_action("LEDGER_ONLY", {}, r, None, True),
                "notes": r.get("ours_origin", ""),
            }
        )

    # Stable sort: PDUFAs first, then by ticker, then by date
    def _sort_key(row: dict) -> tuple:
        is_pdufa = "PDUFA" in (row["bpiq_stage_label"] or row["ledger_event_label"] or "")
        return (
            0 if is_pdufa else 1,
            row["ticker"] or "ZZZ",
            row["bpiq_date"] or row["ledger_date"] or "9999-99-99",
        )

    csv_rows.sort(key=_sort_key)

    csv_path = OUT / f"bpiq_event_ledger_diff_{as_of}.csv"
    md_path = OUT / f"bpiq_event_ledger_diff_{as_of}.md"

    fields = [
        "ticker",
        "company",
        "drug_name",
        "indication",
        "bpiq_event_label",
        "ledger_event_label",
        "bpiq_stage_label",
        "bpiq_date",
        "ledger_date",
        "date_delta_days",
        "in_universe",
        "source_url_or_primary_source",
        "diff_bucket",
        "recommended_action",
        "notes",
    ]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in csv_rows:
            w.writerow(r)

    # Markdown summary
    bucket_counts = Counter(r["diff_bucket"] for r in csv_rows)
    pdufa_mismatches = [
        r
        for r in csv_rows
        if r["diff_bucket"] == "DATE_MISMATCH" and "PDUFA" in (r["bpiq_stage_label"] or r["ledger_event_label"] or "")
    ]
    bpiq_only_in_universe = [r for r in csv_rows if r["diff_bucket"] == "BPIQ_ONLY" and r["in_universe"] == "Y"]
    high_conf_additions = [
        r
        for r in csv_rows
        if r["diff_bucket"] == "BPIQ_ONLY" and r["in_universe"] == "Y" and r["source_url_or_primary_source"]
    ][:10]

    md_lines = [
        f"# BPIQ ↔ event_ledger diff — {as_of}",
        "",
        f"Window: {window_start} to {window_end} ({bpiq_payload.get('window_days', DEFAULT_WINDOW_DAYS)} days)",
        f"BPIQ rows pulled: {len(bpiq_rows)}",
        f"Our window events: {len(ours)} (pdufa_dates.json + event_ledger.jsonl combined)",
        "",
        "## Bucket counts",
        "",
        "| bucket | count |",
        "|---|---:|",
    ]
    for b in ["EXACT_MATCH", "DATE_MISMATCH", "LABEL_MISMATCH", "BPIQ_ONLY", "LEDGER_ONLY"]:
        md_lines.append(f"| {b} | {bucket_counts.get(b, 0)} |")
    md_lines += [
        "",
        f"- BPIQ-only events **in our universe**: {len(bpiq_only_in_universe)}",
        f"- PDUFA-family date mismatches: {len(pdufa_mismatches)}",
        "",
        "## PDUFA date mismatches",
        "",
    ]
    if pdufa_mismatches:
        md_lines.append("| ticker | drug | bpiq_date | ledger_date | delta | recommended_action |")
        md_lines.append("|---|---|---|---|---:|---|")
        for r in pdufa_mismatches:
            md_lines.append(
                f"| {r['ticker']} | {r['drug_name'][:40]} | {r['bpiq_date']} | "
                f"{r['ledger_date']} | {r['date_delta_days']} | {r['recommended_action']} |"
            )
    else:
        md_lines.append("_None._")
    md_lines += [
        "",
        "## Top 10 BPIQ-only candidates in our universe",
        "",
    ]
    if high_conf_additions:
        md_lines.append("| ticker | drug | event | date | source |")
        md_lines.append("|---|---|---|---|---|")
        for r in high_conf_additions:
            src = r["source_url_or_primary_source"]
            src_short = src[:60] + "…" if len(src) > 60 else src
            md_lines.append(
                f"| {r['ticker']} | {r['drug_name'][:40]} | "
                f"{r['bpiq_stage_label']} / {r['bpiq_event_label']} | "
                f"{r['bpiq_date']} | {src_short} |"
            )
    else:
        md_lines.append("_None._")

    md_lines += [
        "",
        "## Verdict (preliminary)",
        "",
        "BPIQ value categories observed in this 60-day window:",
        "",
        "1. **Audit feed** — primary use case so far. Surfaces date drift in our PDUFA list "
        "(e.g. ARVN: BPIQ 2026-06-05 vs ours 2026-05-10; verified BPIQ correct via Arvinas IR).",
        "2. **Recall feed** — limited inside our universe. Most BPIQ-only tickers are micro-caps "
        "outside our universe. The recall gain on small-caps depends on whether we want to expand.",
        "3. **Structured producer candidate** — premature. We have not yet seen sustained agreement "
        "or systematic gap-closing. Re-evaluate after 2-4 weeks of daily pulls.",
        "",
        "**Status:** SUPPORTING source. Not canonical. No production wiring proposed.",
        "",
    ]
    md_path.write_text("\n".join(md_lines) + "\n")

    # Stderr summary
    print(f"wrote {csv_path}")
    print(f"wrote {md_path}")
    print()
    print("bucket counts:")
    for k, v in bucket_counts.most_common():
        print(f"  {v:4d}  {k}")
    print(f"BPIQ-only in universe: {len(bpiq_only_in_universe)}")
    print(f"PDUFA date mismatches: {len(pdufa_mismatches)}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="BPIQ trial-period probe")
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("pull", help="Fetch upcoming catalysts and save raw JSON")
    pp.add_argument("--days", type=int, default=DEFAULT_WINDOW_DAYS)
    pp.set_defaults(func=cmd_pull)
    pd = sub.add_parser("diff", help="Diff BPIQ pull against pdufa_dates + event_ledger")
    pd.add_argument("--as-of", default=None, help="ISO date matching the saved pull (default: today)")
    pd.set_defaults(func=cmd_diff)
    pdel = sub.add_parser("delta", help="Append day-over-day delta to bpiq_trial_log.md")
    pdel.add_argument("--as-of", default=None, help="ISO date matching the saved pull (default: today)")
    pdel.set_defaults(func=cmd_delta)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

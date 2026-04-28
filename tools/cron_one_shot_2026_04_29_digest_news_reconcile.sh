#!/usr/bin/env bash
# cron_one_shot_2026_04_29_digest_news_reconcile.sh — One-shot reconciliation
# of yesterday's intraday mover digest (2026-04-28) "news=NONE" finding
# against today's freshly-refreshed 8-K cache.
#
# Background: on 2026-04-28 the intraday digest flagged 27 movers, 7 HIGH
# severity (ERAS -46.84%, KNSA +22.18%, RVMD +10.50%, etc.) all labeled
# news=NONE because the news-enrichment layer is a phantom (per
# spec_063_news_enrichment_phantom_2026_04_20). Today's 8-K cache snapshot
# was written at 07:04 ET — before market open — so it missed every
# same-day 8-K that materialized during the trading day.
#
# This one-shot fires after tomorrow's morning 8-K refresh (~07:04 ET) and
# checks whether 8-K events with disclosed_at >= 2026-04-28 exist for the
# three top movers (ERAS, KNSA, RVMD). Writes a markdown + JSON artifact
# to artifacts/audit/digest_news_reconcile_2026-04-29.{md,json}.
#
# Read-only. Diagnostic. No mutations.
#
# Self-skips on any other date and on re-invocations (marker file).
#
# Cron entry (annual recurrence is fine — the marker file prevents re-runs):
#   0 8 29 4 * /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_one_shot_2026_04_29_digest_news_reconcile.sh >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/one_shot.log 2>&1

set -euo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
TARGET_DATE="2026-04-29"
DIGEST_DATE="2026-04-28"
MARKER="${REPO_ROOT}/logs/.one_shot_${TARGET_DATE}_digest_news_reconcile.done"
AUDIT_LOG="${REPO_ROOT}/logs/audit_digest_news_reconcile_${TARGET_DATE}.log"
ARTIFACT_DIR="${REPO_ROOT}/artifacts/audit"
ARTIFACT_MD="${ARTIFACT_DIR}/digest_news_reconcile_${TARGET_DATE}.md"
ARTIFACT_JSON="${ARTIFACT_DIR}/digest_news_reconcile_${TARGET_DATE}.json"
LOG_PREFIX="[$(date -Iseconds)]"

if [ -f "$MARKER" ]; then
    echo "${LOG_PREFIX} SKIP: already fired (marker $MARKER exists)"
    exit 0
fi

TODAY=$(date +%Y-%m-%d)
if [ "$TODAY" != "$TARGET_DATE" ]; then
    echo "${LOG_PREFIX} SKIP: today=${TODAY} != target=${TARGET_DATE}"
    exit 0
fi

echo "${LOG_PREFIX} Firing digest-news reconciliation for ${DIGEST_DATE} digest vs ${TARGET_DATE} 8-K cache"

cd "$REPO_ROOT"
mkdir -p "$ARTIFACT_DIR"

/usr/bin/python3 - <<'PYEOF' > "${AUDIT_LOG}" 2>&1
import json
import os
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path("/mnt/c/Projects/biotech_screener/biotech-screener")
TARGET_DATE = "2026-04-29"
DIGEST_DATE = "2026-04-28"
TICKERS = ["ERAS", "KNSA", "RVMD"]
EXTERNAL_CATALYSTS = {
    "ERAS": "Phase I ERAS-0015 patient death + RVMD IP threat (-46.84% intraday)",
    "KNSA": "Q1 2026 earnings beat + Goldman PT raise to $60 (+22.18% intraday)",
    "RVMD": "Adversarial benefit from ERAS reversal; named plaintiff in IP threat (+10.50% intraday)",
}

ARTIFACT_DIR = REPO_ROOT / "artifacts" / "audit"
ARTIFACT_MD = ARTIFACT_DIR / f"digest_news_reconcile_{TARGET_DATE}.md"
ARTIFACT_JSON = ARTIFACT_DIR / f"digest_news_reconcile_{TARGET_DATE}.json"

# Find latest 8-K cache file for today
cache_dir = REPO_ROOT / "cache" / "sec" / "8k_catalysts"
candidates = sorted(
    p for p in cache_dir.iterdir()
    if p.is_file() and p.name.startswith(f"8k_catalysts_{TARGET_DATE}_") and p.suffix == ".json"
)

report = {
    "target_date": TARGET_DATE,
    "digest_date": DIGEST_DATE,
    "tickers_checked": TICKERS,
    "external_catalysts_known": EXTERNAL_CATALYSTS,
    "cache_files_found": [p.name for p in candidates],
    "ticker_findings": {},
    "summary": {},
    "generated_at": datetime.now(timezone.utc).isoformat(),
}

if not candidates:
    print(f"NO 8-K CACHE FILE FOUND for {TARGET_DATE}; expected at {cache_dir}")
    report["summary"]["status"] = "no_cache_file"
    report["summary"]["recommendation"] = (
        "8-K refresh did not run or produced no file. Check tools/cron_data_extras.sh "
        "and tools/run_agent_direct.py logs."
    )
else:
    latest = candidates[-1]
    print(f"Reading {latest.name}")
    with open(latest, encoding="utf-8") as f:
        events = json.load(f)
    print(f"  Total events in file: {len(events)}")

    total_hits = 0
    for ticker in TICKERS:
        hits = [
            e for e in events
            if e.get("ticker") == ticker
            and (e.get("disclosed_at") or "") >= DIGEST_DATE
        ]
        report["ticker_findings"][ticker] = {
            "external_catalyst": EXTERNAL_CATALYSTS[ticker],
            "hits_disclosed_since_digest_date": len(hits),
            "events": [
                {
                    "event_type": e.get("event_type", ""),
                    "confidence": e.get("confidence", ""),
                    "disclosed_at": e.get("disclosed_at", ""),
                    "event_name": (e.get("event_name") or "")[:200],
                }
                for e in hits[:10]
            ],
        }
        total_hits += len(hits)
        print(f"\n  {ticker}: {len(hits)} event(s) disclosed >= {DIGEST_DATE}")
        for e in hits[:5]:
            etype = e.get("event_type", "?")
            conf = e.get("confidence", "?")
            disc = (e.get("disclosed_at") or "?")[:10]
            ename = (e.get("event_name") or "")[:100]
            print(f"    {etype:<20} conf={conf:<5} disc={disc} | {ename}")

    report["summary"]["total_hits"] = total_hits
    report["summary"]["status"] = "captured" if total_hits > 0 else "still_missing"
    if total_hits == 0:
        report["summary"]["recommendation"] = (
            f"No 8-K events for {TICKERS} disclosed since {DIGEST_DATE} are in today's cache. "
            "Catalysts confirmed by external lookup (Google Finance) on 2026-04-28 evening "
            "may still be in the press-release pipeline. Spec 070 (Google Finance fallback) "
            "would have surfaced them in the original digest."
        )
    elif total_hits >= len(TICKERS):
        report["summary"]["recommendation"] = (
            f"All {len(TICKERS)} tickers have at least one event captured. "
            "Yesterday's digest could have surfaced these via the existing 8-K cache "
            "if lookup_same_day_news() were wired to read from it. "
            "Spec 063's phantom layer remains the gap."
        )
    else:
        report["summary"]["recommendation"] = (
            f"{total_hits} event(s) across {sum(1 for t in TICKERS if report['ticker_findings'][t]['hits_disclosed_since_digest_date'] > 0)} of {len(TICKERS)} tickers "
            "are now in cache. Partial capture; remainder may need Spec 070 fallback."
        )

# Write JSON artifact
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True))

# Write Markdown artifact
md_lines = [
    f"# Digest news reconciliation — {DIGEST_DATE} digest vs {TARGET_DATE} 8-K cache",
    "",
    f"**Status**: {report['summary'].get('status', 'unknown')}",
    "",
    "## External catalysts (known from 2026-04-28 evening manual lookup)",
    "",
]
for t in TICKERS:
    md_lines.append(f"- **{t}**: {EXTERNAL_CATALYSTS[t]}")
md_lines.append("")
md_lines.append("## 8-K cache findings")
md_lines.append("")
md_lines.append(f"Cache files inspected: {report['cache_files_found']}")
md_lines.append("")
for t in TICKERS:
    f = report["ticker_findings"].get(t, {})
    md_lines.append(f"### {t} — {f.get('hits_disclosed_since_digest_date', 0)} event(s) >= {DIGEST_DATE}")
    md_lines.append("")
    for e in f.get("events", []):
        md_lines.append(
            f"- `{e['event_type']}` conf=`{e['confidence']}` disc={e['disclosed_at'][:10]}: {e['event_name']}"
        )
    md_lines.append("")
md_lines.append("## Recommendation")
md_lines.append("")
md_lines.append(report["summary"].get("recommendation", "(no recommendation)"))
md_lines.append("")
ARTIFACT_MD.write_text("\n".join(md_lines))

print(f"\nArtifact JSON: {ARTIFACT_JSON}")
print(f"Artifact MD:   {ARTIFACT_MD}")
print(f"\nSummary: {report['summary']}")
PYEOF

echo "${LOG_PREFIX} Reconciliation report ↓↓↓"
cat "${AUDIT_LOG}"
echo "${LOG_PREFIX} Reconciliation report ↑↑↑"

touch "$MARKER"
echo "${LOG_PREFIX} Marker written: $MARKER"

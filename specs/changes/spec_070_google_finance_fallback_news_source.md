# Spec 070 — Google Finance Fallback News Source for Intraday Digest (2026-04-28)

**Status:** Spec only. **No production code changes from this document.**
**Author:** drafted 2026-04-28 in response to today's intraday digest finding.
**Constraint:** alpha-stack frozen per `policy_alpha_freeze_2026_04_04.md`. **This spec is alpha-neutral** because the intraday digest is a post-snapshot operator-facing diagnostic, not a scoring/selector/ranker input. No Checklist v2 required.

## 0. Why this spec exists

Today's `Intraday Mover Digest 2026-04-28` flagged 27 unique movers, 7 HIGH severity, with **27/27 labeled `news=NONE`** — including ERAS −46.84%, KNSA +22.18%, and RVMD +10.50%. Per `spec_063_news_enrichment_phantom_2026_04_20`, the `news=NONE` label is the as-designed phantom-layer state: `lookup_same_day_news()` reads from `artifacts/herald/{classified,raw}/` and `artifacts/grok_biotech_watch/`, neither of which exists or is written by any producer.

Manual investigation confirmed real same-day catalysts existed for all three top movers but were not in any local cache:
- **ERAS −46.84%**: Phase I ERAS-0015 readout had a treatment-related patient death and Revolution Medicines threatened to sue them over a licensed Chinese drug (IP dispute).
- **KNSA +22.18%**: Q1 2026 earnings beat + Goldman Sachs PT raise to $60.
- **RVMD +10.50%**: Adversarial benefit from ERAS reversal; named plaintiff in IP threat.

These catalysts were findable on the public web. Yahoo Finance, SEC EDGAR, Benzinga, and StreetInsider all returned 403/503 to the WebFetch tool's user-agent. **Google Finance returned the headlines cleanly** for all three tickers, with publication, age, and short summaries — even when the underlying source (Seeking Alpha, IBT, Stocktwits, Benzinga) blocked direct access.

This spec proposes adding Google Finance as a fallback news source for the intraday digest's enrichment layer.

## 1. Scope and gates

- **Post-snapshot, operator-facing only.** The intraday digest is not a scoring/selector/ranker input. This spec does not touch `rankings.csv`, scoring, ranker, selector, eligibility, EES, Event EV, or QA gates.
- **Alpha-neutral.** No Checklist v2 required.
- **Fallback only.** If `lookup_same_day_news()` ever finds existing herald/grok output, that path takes precedence. Google Finance fires only when the existing path returns empty.
- **Read-only enrichment.** Output is added to the digest as an additional `news_status` value (e.g., `EXTERNAL_SOURCE: google_finance`); no mutation of digest classification logic, severity gates, or alert dedupe.

**Pre-implementation gate**: confirm with operator that adding a fourth-party data source is acceptable. Google Finance's terms and rate behavior should be reviewed before the producer ships.

## 2. Inputs

```
data/snapshots/{as_of_date}/intraday_mover_digest.json   # current digest (mover list)
common/alert_dedupe.py                                    # existing dedupe state
production_data/universe.json                             # ticker → CIK + company name
```

**Network egress**:
- `https://www.google.com/finance/quote/{TICKER}:{EXCHANGE}` — primary fallback
- No SEC EDGAR direct calls (blocked by user-agent restrictions in observed test).
- No Yahoo Finance (returned 503 in observed test).

## 3. Outputs

Augments existing digest output:
```
data/snapshots/{as_of_date}/intraday_mover_digest.json
```

New fields per mover record:
```
news_status              # existing — extended enum: NONE | HERALD_HIT | GROK_HIT | EXTERNAL_SOURCE
external_news_source     # new — "google_finance" when fallback fires; null otherwise
external_news_headlines  # new — list of {headline, publication, age_text} (max 5)
external_news_fetched_at # new — ISO timestamp of the fallback fetch
external_news_age_minutes # new — staleness vs digest_generated_at, for operator triage
```

The existing `news_status="NONE"` output is preserved when the fallback fails or returns nothing actionable.

## 4. Fallback logic

```
For each mover in digest:
  if existing herald/grok lookup returned non-empty:
    use that, skip fallback
    continue

  call google_finance_fetch(ticker, exchange, max_age_hours=24)
  if returns headlines:
    record news_status = "EXTERNAL_SOURCE"
    record external_news_source = "google_finance"
    record headlines (max 5, ordered by recency)
  else:
    record news_status = "NONE" (unchanged)
```

**Rate behavior**: at most one Google Finance fetch per mover per digest run. Today's digest has 27 movers; tomorrow's median is ~15. Even at 30 movers/run × 16 daily runs = 480 fetches/day. Add 2-second jitter between fetches to avoid concurrent-request throttling.

**Failure modes**:
- 4xx/5xx from Google Finance → log to `logs/intraday_mover_news_fallback.log`, fall through to `news_status=NONE`. Does NOT block the digest.
- Empty headline list → `news_status=NONE`, no error.
- Parse error → log + `news_status=NONE`.
- Timeout (>5s) → abandon, log, `news_status=NONE`.

**Determinism**: the fetcher is non-deterministic across runs (Google Finance ranking changes). Cache parsed headlines per `(ticker, hour_bucket)` for 60 minutes to stabilize within-hour digest re-runs.

## 5. Headline parsing

Google Finance HTML returns headlines as a structured list; each item has:
- Title (visible text)
- Publication (visible text near the title)
- Relative timestamp (e.g., "3 minutes ago", "7 hours ago", "1 day ago")

Parse via BeautifulSoup. Rejects:
- Non-English headlines (heuristic: ASCII-ratio < 0.7).
- Headlines with no publication attribution.
- Headlines older than `max_age_hours` (default 24).

Convert relative timestamps to absolute `external_news_fetched_at` minus `delta_from_relative_text`.

## 6. Operator-facing changes

Digest markdown gains a `Recent News` line per mover when `news_status=EXTERNAL_SOURCE`:

```
ERAS  -46.84%  rel -45.66pp  HIGH
  Recent News (google_finance, 3 min ago):
    - "Erasca: Strong Data Overshadowed By A Patient Death And A Patent Fight" (Seeking Alpha)
    - "Why Is Cancer Drug Developer Erasca Stock Plunging On Tuesday?" (Benzinga)
    - "Erasca, Inc. (ERAS) Discusses Preliminary Phase I Data and Differentiation of Pan-RAS Molecular Glue ERAS-0015" (Seeking Alpha)
```

Email subject and body unchanged in structure; just the per-mover block expands.

## 7. Tests

- Unit test for `google_finance_fetch()` with a recorded HTML fixture: returns expected headlines, publication, age.
- Unit test for the relative-timestamp parser: `"3 minutes ago"`, `"7 hours ago"`, `"1 day ago"`, `"yesterday"`, `"2 days ago"`, `"4 weeks ago"`, edge cases.
- Integration test: digest with three mover tickers, two miss herald, fallback fires for both, output JSON has `external_news_source="google_finance"` and ≤5 headlines.
- Failure-mode tests:
  - 503 response → digest still emits with `news_status=NONE`, no exception.
  - Empty headline list → `news_status=NONE`, no exception.
  - Timeout → `news_status=NONE`, log entry written.

## 8. Non-goals

- **No changes to scoring / selector / ranker / EES / Event EV.** This is operator-facing diagnostic only.
- **No new alpha lane.** Headlines do not feed back into any model.
- **No long-term archival.** Headlines are stored in the digest JSON snapshot only; no separate news database.
- **No headline classification.** Spec 070 is fetch-and-display; semantic classification (catalyst type, tier, severity) belongs to the existing herald/grok pipeline if it ever resumes.
- **No replacement of herald/grok.** When those producers come online, they take precedence. This is a fallback, not a replacement.
- **No SEC EDGAR direct integration.** WebFetch returned 403 to the SEC user-agent; either the producer adopts a polite browser UA per SEC's fair access policy in a future spec, or the existing 8-K catalyst extraction (which already runs daily) covers SEC content.

## 9. Decision rule after first 30 days

- **Hit rate ≥ 60%** (fallback returns ≥1 headline for ≥60% of `NONE`-bound movers): keep the fallback, plan to expand to other operator-facing surfaces (e.g., trapops, cohort_churn_alert).
- **Hit rate 30–60%**: keep, but lower max_age_hours and tighten the headline-quality filter.
- **Hit rate < 30%**: retire. Diagnose whether Google Finance is rejecting the producer's user-agent, the headline parse is brittle, or biotech-specific names just don't surface there.

## 10. References

- `MEMORY.md`: `spec_063_news_enrichment_phantom_2026_04_20.md`, `spec_063_intraday_mover_watch.md`, `policy_alpha_freeze_2026_04_04.md`
- Existing producer: `tools/cron_intraday_mover.sh`, `common/alert_email.py`, `common/alert_dedupe.py`
- Source spec: `specs/changes/spec_063_intraday_mover_watch.md` (the digest itself)
- Today's evidence: `Intraday Mover Digest 2026-04-28` showing 27/27 `news=NONE` while real catalysts existed for the top three movers

# Audit Finding — Press-Release Feed Collision (2026-05-02)

**Severity:** YELLOW (evidence-trail contamination, not scoring-path contamination)
**Discovered during:** investigation of `production_qa.classifier_escalation_pool` FAIL on 2026-04-30
**Reporter:** Hermes audit session 2026-05-02
**Affects:** `artifacts/event_feedback/`, `data/press_releases/classified/`
**Does NOT affect:** `run_screen.py`, `module_5_composite*`, `common/`, B6 selector, ranker, snapshots, ruleset 2a3e79eb

---

## TL;DR

The press-release ingestion pipeline is feeding ~67% noise into the classifier
because 88% of universe tickers (300/341) have no `company_ir_url` configured
and fall back to a GlobeNewswire **keyword search by ticker symbol** that has
no issuer filter. Short tickers like `DRUG`, `LAB`, `RARE`, `TECH`, `DAWN`
match every press release on the wire mentioning those English words.

This explains the `classifier_escalation_pool` trend
(73 → 139 → 345 → 408 over 11 days, "other" share 46.6% → 51.7%).
The classifier is doing the right thing by escalating; the feed is wrong.

The scoring path is unaffected. The event-feedback ledger
(`artifacts/event_feedback/`) has limited noise contamination. Calibration
evidence (`build_calibration_evidence.py`) may inherit one level of noise
through postmortem inputs but was not deeply traced.

---

## How the failure was found

1. `production_qa_check.py` reported `classifier_escalation_pool` FAIL on
   2026-04-30: `pool=408, clean=30/30, other=51.7%, hard_coll_pool=903
   [other_share=51.7% (>50)]`
2. Trend analysis of prior reports
   (`artifacts/production_qa/2026-04-{19,20,21,28,30}_report.md`) showed
   pool size and "other" share rising monotonically since the
   2026-04-19 classifier-hardening cutover. Not a one-day spike.
3. Sample inspection of `artifacts/production_qa/hard_collisions_*.json`
   showed the "other" headlines were systematically not biotech news at all
   — restaurant chains, swimming halls, SpaceX token airdrops, EMF-blocking
   underwear, skin-tag removers.
4. The headlines were tagged with biotech tickers (TECH, RARE, LAB, DAWN, etc.)
   that happen to be English words.
5. `production_data/company_ir_sources.json` showed the source: 88% of
   tickers have empty `company_ir_url` and fall back to
   `https://www.globenewswire.com/Search?keyword=<TICKER>` — a substring
   keyword search with no issuer filter.

## Mechanism (definitive)

Path: `tools/cron_data_refresh.sh` → `tools/fetch_company_press_releases.py`
→ reads `production_data/company_ir_sources.json` → for each ticker:

```
1. company_ir_url     → empty for 300/341 (88%) of tickers
2. press_release_rss  → empty for 341/341 (100%) of tickers  ← all empty
3. backup_sources[0]  → uniformly globenewswire.com/Search?keyword=<TICKER>
```

GlobeNewswire's keyword search returns ALL releases mentioning the string,
regardless of issuer or industry. Each match is tagged with the biotech
ticker that triggered the search (`PressRelease.ticker` in
`fetch_company_press_releases.py:46`), persisted to
`data/press_releases/raw/`, then classified.

The classifier (`tools/classify_press_releases.py`) correctly identifies most
of these as not fitting any biotech event category and routes them to
`other` → escalation pool grows → QA threshold trips.

### Sampled "other" headlines (4 days, 40 records, May 2026)

| Ticker | Biotech (per universe)            | Sampled headline                                         |
|--------|-----------------------------------|----------------------------------------------------------|
| TECH   | Bio-Techne                        | SailPoint Names Carahsoft Distribution Partner of Year   |
| TECH   | Bio-Techne                        | Bread Financial Declares Dividends                       |
| RARE   | Ultragenyx                        | WeRide Self-Driving WRD 3.0 Champion at China Comp       |
| RARE   | Ultragenyx                        | Critical Metals Closes Tanbreez Acquisition              |
| LAB    | Standard BioTools                 | TRT UK guide / Kraig Biocraft Spider Silk                |
| LAB    | Standard BioTools                 | EMF-blocking boxer underwear claims                      |
| DAWN   | Day One Biopharma                 | Hall of Fame Partners International Swimming Hall        |
| DAWN   | Day One Biopharma                 | Zoomex SpaceX Token Airdrop Carnival                     |
| DRUG   | Bright Minds Biosciences          | Natura Pro Skin Tag Remover Claims                       |
| FOLD   | Amicus Therapeutics               | Abits Group Bitcoin Mining 760 PH/s                      |
| ARCT   | (universe entry blank)            | Arctic Wolf Decipio Credential Theft Tool                |
| NAUT   | (universe entry blank)            | Veson + Veracity Emissions Reporting Partnership         |

Theme distribution across all 40 sampled headlines:
- 67.5% "unmatched" (no biotech keyword fit at all)
- 12.5% corp/admin
- 7.5% partnership/license
- Remainder: scattered across regulatory, financing, M&A, etc.

## Severity assessment

### NOT contaminated (scoring path)

Trace via `grep -rEln 'press_releases/classified' run_screen.py module_5*
common/ run_phase2*`:

- `run_screen.py` — does NOT import classified press releases
- `module_5_composite*` — does NOT import
- `common/` — does NOT import
- `run_phase2*` — does NOT import

B6 selector (0.65 × coinvest + 0.35 × inst_delta), ranker, snapshot,
ruleset 2a3e79eb v1.13.0 are all clean.

### PARTIALLY contaminated (evidence/feedback path)

Two production consumers found:

1. `tools/build_event_feedback.py` writes
   `artifacts/event_feedback/*.jsonl`. At line 225–234, the Herald-match
   loop accepts ANY `event_category` (including `other`) and only adds a
   `+1.0` confidence bonus when category is `clinical|regulatory|safety`.
   So a noise headline matching ticker+date window can become the best
   Herald match if no real biotech release occurred in that window.
   `_map_source_class()` at line 239–251 then labels these
   `OFFICIAL_COMPANY_IR` based on `source_type == "company_ir"` — false
   provenance.

2. `tools/build_intraday_mover_watch.py` reads
   `artifacts/herald/classified/<date>.json` (a different, shorter-lived
   path). Whether that has the same collision problem was not deeply
   traced; flagged for follow-up.

Research / QA / audit consumers (do not feed scoring):
- `tools/production_qa_check.py` (the check that flagged this)
- `tools/audit_escalation_pool.py`
- `tools/reclassify_press_release_cache.py`
- `tools/shadow_classify_over_raw.py`
- `tools/herald_crt_intake.py`
- `scripts/research/herald_*` (4 scripts — calibration / ground truth /
  precision)

### Possibly contaminated (governance evidence)

Not deeply traced: `tools/build_calibration_evidence.py` reads
postmortems and signal artifacts. If postmortems incorporate
`event_feedback/` rows, calibration evidence inherits one level of
noise. Worth confirming separately.

## Recommended remediation

### Tier A — high leverage, low effort

**A.1 Backfill `company_ir_url` for the 300 tickers without one.**
Data-curation task, not code. The fetcher already prefers IR URLs over
backups; the field is just unpopulated. Even partial backfill (top 100 by
position weight) would cut false-positive volume dramatically.

**A.2 Replace ticker-keyword backup with proper issuer search.**
GlobeNewswire supports `?orgId=...` queries that filter by source.
Limited-scope edit in `_extract_globenewswire_releases` /
`fetch_ticker_releases` in `fetch_company_press_releases.py`.

**A.3 Add post-fetch sanity filter (cheapest fix).**
After fetch, drop any release whose body or headline does NOT mention the
company's actual name (from the `company` field in
`company_ir_sources.json`). Three-line addition in `fetch_ticker_releases`.
Catches >90% of the noise immediately.

### Tier B — defensive depth

**B.1 Filter `category == "other"` in build_event_feedback Herald matcher.**
Line ~226 of `build_event_feedback.py`. Single-line change. Makes the
matcher robust to upstream feed-quality regressions even if A.1–A.3 lapse.

**B.2 CIK-based filter for SEC 8-K source.**
`fetch_company_press_releases.py:50` lists `sec_8k` as a `source_type` but
its wiring was not traced in this audit. SEC filings are CIK-resolved by
construction; if the path exists, it's already collision-immune.

**B.3 Prefer paid feeds (Bellringer / BPIQ / Grok) for catalyst-class names.**
Per `.env` vars, these are configured but the fetcher relies on web
scraping. Ingestion strategy decision — not a one-line change.

### Tier C — DO NOT do

**C.1 Loosen the `>50% other` threshold in `production_qa_check.py`.**
Wrong fix. The threshold is correctly catching feed-quality decay.
Loosening it hides the underlying problem.

**C.2 Drop the classifier_escalation_pool QA check entirely.**
It is the only mechanism currently catching the feed-quality drift.

**C.3 Rebuild prior `event_feedback` artifacts.**
The contamination is bounded ("other"-classified rows accepted as
fallback when no real biotech release in window). The artifacts are
governance evidence, not model inputs. Patching the matcher (B.1) is
sufficient; backfill is unnecessary.

## What governance gates apply

Per CLAUDE.md:
- Backtest systems NEVER directly modify production screening behavior.
- All data fixtures must be canonical, complete, frozen, timestamped.

The feed change touches data fixtures (CCFT principle: complete, no silent
nulls or missing fields without explicit flags). Pre-implementation
checklist:

- Phase / spec lock document required (per repo convention
  `docs(model): lock Phase N`).
- Tests: unit test for the post-fetch sanity filter (mock company name
  presence/absence in headline body); integration test verifying noise
  rejection rate on a fixture.
- MODEL_DOCUMENTATION.md update: mention the feed-quality issue in the
  L-items section if not already present (none of L1–L18 cover this; this
  may warrant a new L-item).

## Verification artifacts

Files inspected (all read-only):
- `artifacts/production_qa/2026-04-{19,20,21,28,30}_report.md`
- `artifacts/production_qa/hard_collisions_2026-04-{20,21,28,30}.json`
- `tools/production_qa_check.py` (lines 323–438)
- `tools/fetch_company_press_releases.py` (lines 1–500)
- `tools/build_event_feedback.py` (lines 1–250)
- `tools/build_intraday_mover_watch.py` (greps only)
- `production_data/company_ir_sources.json` (schema + 12 collision-ticker entries)

No production state was modified by this audit.

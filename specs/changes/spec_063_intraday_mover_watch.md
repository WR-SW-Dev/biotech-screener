# Spec 063 — Near-Real-Time Intraday Mover Watch

**Status**: Phase 1 scaffolding complete. Provider strategy revised 2026-04-17 from Polygon-primary to Alpaca-primary.
**Author**: Claude / arrenchulz
**Date**: 2026-04-17
**Ruleset impact**: NO (read-only monitoring/alerting)
**Alpha stack impact**: NO — no scoring, ranking, event-ledger, or execution change
**Depends on**: `price_action_watch` (watchlist construction), Spec 044/053 (Herald), `grok_biotech_watch`, OpenClaw Cron (Spec 037)

---

## Objective

Create an OpenClaw-managed **near-real-time intraday** agent
(`intraday_mover_watch`) that polls delayed-or-real-time quotes for the
current model-relevant watchlist plus XBI, flags large absolute intraday
moves and large relative moves vs XBI, checks for same-day
official/supporting news via Herald and Grok, and delivers:

- immediate **HIGH**-severity alert emails during market hours
- one end-of-day digest email and artifact per trading day

This is an **operator alerting layer only**. It must remain read-only and
must never feed intraday quotes or news observations back into rankings, the
event ledger, construction, or execution policy.

### Why "near-real-time," not "real-time"

The primary production backend (Alpaca Basic) returns **15-minute delayed
quotes** via its REST snapshot endpoint and IEX-only real-time via
websocket. That delay is acceptable for this use case: biotech catalyst
moves do not fade in 15 minutes, press releases publish at known
timestamps, and Herald/CRT polling already runs on a slower cadence. The
agent is a catalyst-linkage alerting layer, not a trading-timing layer.
Any future upgrade to a consolidated-tape real-time feed is a provider
change only; the spec does not need to change.

## Context

`price_action_watch` (built via `tools/build_price_action_watch.py`) already
monitors a capped, model-relevant watchlist for big moves and writes daily
alert artifacts. It is, however, **daily/close-based**: it reads
`production_data/price_history.csv`, which carries no share volume (its
"RVOL" is a volatility proxy — see `build_price_action_watch.py:167`).

Herald (Spec 044, audited in Spec 053) is the source-grounded press-release
lane with company IR / major wire / FDA / SEC / CTGov hierarchy.
`grok_biotech_watch` is the watchlist-scoped search monitor with DEM
enrichment, dedupe, throttling, and email plumbing.

The gap is narrow: **real-time intraday quotes, a benchmark-relative trigger
vs XBI, and intraday catalyst linkage.** Everything else — watchlist scoping,
alert artifacts, email plumbing, news enrichment, dedupe, and OpenClaw cron
wrapping — already exists.

## Policy Constraints

1. **Read-only.** No writes outside `artifacts/intraday_mover_watch/` and
   `agents/intraday_mover_watch/memory/`. No mutation of production data.
2. **Not alpha.** No new features enter the scoring stack. No signal is
   derived from intraday quotes. Alpha stack freeze (2026-04-04) respected.
3. **Source hierarchy enforced.** Herald first (official); Grok only as
   supporting/unverified enrichment. Web/search chatter is never treated as
   a confirmed catalyst.
4. **No execution coupling.** No auto-escalation into review queue or trade
   plan. Alerts are operator-facing only.
5. **Graceful degradation.** Quote API down → `NO_DATA`. XBI missing → skip
   relative classification, keep absolute. SMTP missing → artifacts only.
   Herald stale → `news_status=UNKNOWN_SOURCE_STATE`.
6. **Watchlist reuse, not redefinition.** Watchlist construction rules are
   imported from / shared with `build_price_action_watch.py`. This spec does
   not invent a new universe.

---

## Scope of First PR

Spec-only. The following deliverables are **not** part of this PR and will
be staged behind Polygon credentialing:

- `tools/build_intraday_mover_watch.py`
- `common/realtime_quote_client.py`
- `agents/intraday_mover_watch/{SOUL,TOOLS,AGENTS,HEARTBEAT}.md`
- `tests/test_intraday_mover_watch.py`
- `tests/test_realtime_quote_client.py`
- OpenClaw cron registration

This matches the repo-native pattern: checked-in spec before new agent code.

---

## Deliverables (post-credentialing)

| # | File | Type |
|---|------|------|
| 1 | `specs/changes/spec_063_intraday_mover_watch.md` | **This spec (Phase 0)** |
| 2 | `common/realtime_quote_client.py` | Provider-agnostic intraday quote adapter |
| 3 | `tools/build_intraday_mover_watch.py` | CLI entry point and main builder |
| 4 | `agents/intraday_mover_watch/SOUL.md` | Agent identity |
| 5 | `agents/intraday_mover_watch/TOOLS.md` | Tool manifest |
| 6 | `agents/intraday_mover_watch/AGENTS.md` | Upstream/downstream context |
| 7 | `agents/intraday_mover_watch/HEARTBEAT.md` | Run cadence + health checks |
| 8 | `tests/test_realtime_quote_client.py` | Provider contract tests |
| 9 | `tests/test_intraday_mover_watch.py` | Builder + classifier tests |
| 10 | OpenClaw cron entries | `intraday-mover-watch-open/core/digest` |

---

## Provider Strategy

### Primary: Alpaca Basic (no separate exchange license required)

**Alpaca is the production intraday provider for Phase 2.** Alpaca's free
("Basic") Trading API plan includes:

- **15-minute-delayed US equity snapshots** via REST
  (`GET /v2/stocks/snapshots?symbols=...`)
- Real-time IEX-only quotes via websocket (not used in Phase 2)

Snapshot endpoint returns, per symbol: `latestTrade`, `latestQuote`,
`minuteBar`, `dailyBar`, `prevDailyBar` — exactly the fields this agent
needs. The 15-min delay is acknowledged in the "Why near-real-time"
objective note.

### Optional future upgrade: Polygon/Massive

If a paid consolidated-tape feed is purchased later (Polygon Developer,
Massive, or equivalent), `PolygonMassiveQuoteClient` already exists in
`common/realtime_quote_client.py` and will be selected automatically by the
factory when `MASSIVE_API_KEY` / `POLYGON_API_KEY` is set. No spec change
required.

### Explicit non-goals

- **`wake_robin_data_pipeline/market_data_provider.py` (Morningstar +
  yfinance fallback) is NOT suitable for production intraday alerting.** It
  is daily-oriented and the integration guide flags it as unsuitable for
  intraday.
- **yfinance is not a production answer for this agent.** Acceptable only
  as a dev-mode fallback behind `BIOTECH_INTRADAY_DEV_FALLBACK=1` for local
  smoke tests. Post-fixture-capture, it must not be used for serious
  validation runs.
- **Finnhub and Alpha Vantage are not adopted** in this spec. Their free
  tiers either lack clean delayed-intraday entitlements or require
  premium-tier licensing; adopting them would need a separate provider
  evaluation.

### Adapter contract

`common/realtime_quote_client.py` exposes a provider-agnostic interface:

```python
class RealtimeQuoteClient(Protocol):
    def get_quotes(self, tickers: Iterable[str]) -> dict[str, QuoteRecord]: ...
    def health(self) -> HealthStatus: ...

@dataclass(frozen=True)
class QuoteRecord:
    ticker: str
    last: float
    prev_close: float
    open: float
    high: float
    low: float
    volume: int
    avg_volume_20d: int | None
    quote_ts: str          # ISO8601 UTC
    market_status: Literal["pre", "open", "post", "closed", "unknown"]
    source: Literal["alpaca", "polygon", "massive", "dev_fallback"]
```

Implementations:

- `AlpacaQuoteClient` — production primary (Alpaca Basic, 15-min delayed REST)
- `PolygonMassiveQuoteClient` — optional upgrade path (activates if a paid
  Polygon/Massive key is present and selected over Alpaca explicitly)
- `DevFallbackQuoteClient` — yfinance, gated by `BIOTECH_INTRADAY_DEV_FALLBACK=1`
- `NullQuoteClient` — default no-op when no credentials configured

Factory selection order:

1. `APCA_API_KEY_ID` + `APCA_API_SECRET_KEY` present → `AlpacaQuoteClient`
2. else `MASSIVE_API_KEY` / `POLYGON_API_KEY` present → `PolygonMassiveQuoteClient`
3. else `BIOTECH_INTRADAY_DEV_FALLBACK=1` → `DevFallbackQuoteClient`
4. else → `NullQuoteClient`

### Credentials

- `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` — Alpaca Basic credentials
  (primary). Obtain via alpaca.markets account creation; no separate
  exchange license required.
- Missing credentials → agent emits `status=NO_DATA` and one WARN
  notification per trading day (no repeat spam).
- The previous `BIOTECH_INTRADAY_REALTIME_TIER` gate is **removed**; it was
  specific to the Polygon-consolidated-real-time path. Alpaca Basic's
  entitlement is explicit and documented, not a tier we need to confirm
  at runtime.

---

## Watchlist Construction

**Imported verbatim from `build_price_action_watch.py`.** This spec does not
fork the universe definition. Expected inputs:

- `data/snapshots/{date}/rankings.csv`
- `data/snapshots/{date}/review_queue.csv`
- `artifacts/live_shadow/positions/{date}.json`
- `artifacts/live_shadow/trade_plan/{date}/trade_plan.csv`
- `artifacts/catalyst_delta/{date}_delta.json`
- A-tier names with `catalyst_days <= 30`

Cap: `WATCHLIST_MAX = 40`, prioritized by `actionable_rank`.

XBI is always added to the fetch list (not to the watchlist itself).

---

## Core Formulas

For each ticker `t` at poll time:

```
stock_abs_move_pct   = 100.0 * (last_t / prev_close_t - 1.0)
xbi_abs_move_pct     = 100.0 * (last_xbi / prev_close_xbi - 1.0)
rel_move_vs_xbi_pct  = stock_abs_move_pct - xbi_abs_move_pct
gap_pct              = 100.0 * (open_t / prev_close_t - 1.0)
intraday_range_pct   = 100.0 * (high_t / low_t - 1.0)
rvol                 = volume_t / avg_volume_20d_t    # true volume from Polygon
```

If `avg_volume_20d` is unavailable for a ticker, `rvol` is set to `None` and
the `INTRADAY_RVOL_SPIKE` code is skipped (not faked).

---

## Thresholds (policy-chosen, not fit)

```
ABS_MOVE_MEDIUM_UP   = +5.0
ABS_MOVE_HIGH_UP     = +10.0
ABS_MOVE_MEDIUM_DOWN = -5.0
ABS_MOVE_HIGH_DOWN   = -10.0

REL_MOVE_MEDIUM_UP   = +4.0   # percentage points vs XBI
REL_MOVE_HIGH_UP     = +7.0
REL_MOVE_MEDIUM_DOWN = -4.0
REL_MOVE_HIGH_DOWN   = -7.0

RVOL_SPIKE           = 2.5
MIN_PRICE            = 1.00
DEDUP_WINDOW_HOURS   = 4
WATCHLIST_MAX        = 40
MAX_IMMEDIATE_EMAILS_PER_HOUR = 5
```

Absolute thresholds align with `price_action_watch` semantics. Relative
thresholds are tighter because XBI-normalized moves are more informative
intraday than raw sector-driven moves. No threshold fitting; tuning requires
a new spec.

---

## Alert Codes

```
INTRADAY_ABS_MOVE_UP_MEDIUM
INTRADAY_ABS_MOVE_UP_HIGH
INTRADAY_ABS_MOVE_DOWN_MEDIUM
INTRADAY_ABS_MOVE_DOWN_HIGH

INTRADAY_REL_MOVE_UP_MEDIUM
INTRADAY_REL_MOVE_UP_HIGH
INTRADAY_REL_MOVE_DOWN_MEDIUM
INTRADAY_REL_MOVE_DOWN_HIGH

INTRADAY_RVOL_SPIKE
INTRADAY_MOVE_WITH_OFFICIAL_NEWS
INTRADAY_MOVE_WITH_SUPPORTING_NEWS
INTRADAY_MOVE_NO_OFFICIAL_NEWS
INTRADAY_NEWS_SECTOR_ONLY
```

### Severity

- **HIGH**: any HIGH abs move; any HIGH rel move; MEDIUM move + official
  same-day catalyst
- **MEDIUM**: MEDIUM abs/rel move without official news; RVOL spike +
  MEDIUM move
- **LOW**: small follow-on, duplicate topic, or sector-only explanation

---

## News Classification Contract

```
{
    "news_status": "OFFICIAL" | "SUPPORTING" | "SECTOR_ONLY" | "NONE" | "UNKNOWN_SOURCE_STATE",
    "source_rank": 1 | 2 | 3 | 4 | None,
    "source_type": "company_ir" | "wire" | "fda" | "sec" | "ctgov" | "grok" | None,
    "headline": str,
    "published_at_utc": str,
    "url": str,
    "summary": str,
    "confidence": "high" | "medium" | "low",
    "is_same_day": bool,
    "catalyst_tag": "topline" | "approval" | "financing" | "crl" | "adcom" | "none",
}
```

### Lookup order

1. **Herald classified** same-day ticker match → `OFFICIAL`, source_rank 1-3
2. **Herald raw PR** same-day → `OFFICIAL`, source_rank 2
3. **Grok watch** same-day → `SUPPORTING`, source_rank 4
4. none → `NONE`; if `xbi_abs_move_pct` explains the move, upgrade to
   `SECTOR_ONLY`

Grok-only evidence is **never labeled official**.

---

## Artifact Schema

### Per-poll

`artifacts/intraday_mover_watch/{YYYY-MM-DD}T{HH-MM-SS}Z_poll.json`

```
{
  "schema": "intraday_mover_watch.v1",
  "as_of_ts": "2026-04-17T14:30:00Z",
  "market_status": "open",
  "provider": "polygon",
  "watchlist_size": 37,
  "n_triggered": 4,
  "xbi_abs_move_pct": -1.72,
  "thresholds": {...},
  "rows": [ {row schema below} ]
}
```

### Row schema

```
{
  "ticker", "tier", "actionable_rank", "catalyst_days", "is_hard_catalyst",
  "last", "prev_close", "stock_abs_move_pct", "rel_move_vs_xbi_pct",
  "gap_pct", "rvol",
  "trigger_codes": [...],
  "severity": "HIGH" | "MEDIUM" | "LOW",
  "news_status", "headline", "summary", "source_type", "source_rank", "url",
  "dedupe_key"
}
```

### End-of-day

- `artifacts/intraday_mover_watch/{date}_digest.json`
- `artifacts/intraday_mover_watch/{date}_digest.md`

Sections: top 5 absolute movers; top 5 relative movers vs XBI; movers with
official catalyst; movers with no official explanation; counts by severity.

---

## Dedupe

```
dedupe_key = sha256(f"{ticker}|{direction_bucket}|{severity}|{headline_or_none}|{trade_date}")
```

Suppress repeat emails within 4 hours **unless** any of:

- severity stepped up (MEDIUM → HIGH)
- news_status improved (NONE → OFFICIAL, SUPPORTING → OFFICIAL)
- abs move widened by ≥ +3.0pp from last sent
- rel move widened by ≥ +3.0pp from last sent

Matches Grok watch dedupe philosophy and 4h suppression window.

---

## Email Behavior

### Immediate alert (HIGH only, ≤5/hour)

Subject: `[HIGH] {TICKER} {±X.X%} intraday ({±Y.Ypp} vs XBI) — {news_tag}`

Body: ticker, tier/rank, catalyst_days, price, intraday move, rel vs XBI,
RVOL, news block (status, source, headline, publish time), interpretation
line ("Read-only alert only. Not a trade recommendation."), artifact path.

### End-of-day digest (16:15 ET)

One email per trading day. Uses the same SMTP plumbing as Herald / Grok.

---

## OpenClaw Cron Registration

Verdict-first delivery, isolated session, light context, announce-on-run,
per Spec 037 conventions.

```
openclaw cron add \
  --name "intraday-mover-watch-open" \
  --cron "35,50 9 * * 1-5" \
  --session isolated --light-context --announce \
  --message "Run intraday mover watch. Poll Polygon quotes for watchlist + XBI, check same-day Herald/Grok, return verdict + top movers."

openclaw cron add \
  --name "intraday-mover-watch-core" \
  --cron "5,20,35,50 10-15 * * 1-5" \
  --session isolated --light-context --announce \
  --message "Run intraday mover watch. Poll Polygon quotes for watchlist + XBI, check same-day Herald/Grok, return verdict + top movers."

openclaw cron add \
  --name "intraday-mover-watch-digest" \
  --cron "15 16 * * 1-5" \
  --session isolated --light-context --announce \
  --message "Summarize today's intraday mover watch artifacts. Return verdict, top movers, counts, official-news hits, artifact link."
```

Retry/backoff handled by the OpenClaw wrapper. No job-level retry loops in
the builder beyond small provider-call retries.

---

## Delivery Contract (per OpenClaw run)

- one-line verdict: `OK` | `WARN` | `ACTION REQUIRED` | `NO DATA` | `FAIL`
- 2–5 bullets
- one artifact pointer

Example:

```
INTRADAY MOVERS: ACTION REQUIRED
- 3 HIGH movers, 2 with official same-day PRs
- SRPT +7.6% (+9.3pp vs XBI), official company IR update
- KROS -8.1% (-6.4pp vs XBI), no official same-day source found
- XBI -1.7%; 2 names moved >7pp idiosyncratically
- Artifact: artifacts/intraday_mover_watch/2026-04-17T14-30-00Z_poll.json
```

---

## Failure Handling

| Failure | Behavior |
|---|---|
| Alpaca unavailable | Empty artifact, `status=NO_DATA`, one WARN/day |
| `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` missing | Same as above; dev fallback only if flag set |
| Polygon/Massive unavailable (when selected) | Same behavior as Alpaca unavailable |
| XBI quote missing | Skip relative classification; absolute alerts still emit |
| SMTP missing | Artifacts written; email skipped with warn |
| Herald stale/missing | `news_status=UNKNOWN_SOURCE_STATE`; mover alert still sends |
| Grok unavailable | No enrichment; core watcher never fails on this |
| Market closed | No polling artifact unless `--digest-only` |

---

## Acceptance Criteria

1. Watchlist matches `price_action_watch` construction exactly (shared code,
   not re-implemented).
2. Intraday alerts use **live provider snapshots** (Alpaca primary;
   Polygon/Massive if a paid feed is later configured), not
   `price_history.csv`.
3. Every triggered ticker computes both absolute intraday move and relative
   move vs XBI.
4. Every immediate alert includes one of: official same-day source,
   supporting source, or explicit "no official same-day catalyst found."
5. Duplicate alerts suppressed for 4h unless severity or news quality
   improves, or move widens by ≥3pp.
6. EOD digest emitted once per weekday and written to artifact store.
7. Agent is fully read-only; no scoring / ranking / event-ledger / trade
   plan code paths are modified.
8. yfinance / Morningstar-based daily provider is never wired as the primary
   live quote source.

---

## Test Plan

### Unit

- `test_compute_intraday_metrics`
- `test_rel_move_vs_xbi`
- `test_severity_thresholds`
- `test_dedupe_step_up_resend`
- `test_news_lookup_prefers_herald_over_grok`
- `test_no_xbi_falls_back_to_abs_only`
- `test_digest_rollup_counts`
- `test_rvol_none_when_avg_volume_missing`
- `test_grok_only_never_labeled_official`

### Provider contract

- `test_polygon_quote_client_happy_path` (recorded fixtures)
- `test_polygon_rate_limit_backoff`
- `test_polygon_missing_key_noisy_once`
- `test_dev_fallback_requires_flag`

### Fixture scenarios

- broad biotech selloff (XBI down sharp; individual alerts should be
  suppressed unless idiosyncratic)
- isolated upside mover with official PR
- isolated downside mover with no news
- duplicate alert within 4h (suppressed)
- severity step-up on second poll (resent)
- XBI quote missing (abs alerts still emit)

### Manual acceptance

One replay day produces: ≥1 official-news-linked mover, ≥1 "no official
same-day source" mover, one clean EOD digest, no duplicate spam.

---

## Rollout

| Phase | Gate | Scope |
|---|---|---|
| **0** | Spec merged | Spec-only |
| **1** | — | Builder, classifier, digest, provider-agnostic adapter, all clients (Alpaca/Polygon/Dev/Null), tests. **Complete 2026-04-17.** |
| **1.5** | Alpaca account + `APCA_API_KEY_ID`/`APCA_API_SECRET_KEY` in `.env` | Capture real Alpaca snapshot fixtures (1 biotech, 1 XBI, 1 missing/illiquid). Add fixture-backed integration test for parsed fields. One credentialed dry-run during market hours with email off. |
| **2** | Phase 1.5 validated | SMTP wiring, immediate HIGH alerts with throttle, EOD digest send. Reuse Herald SMTP recipients. Still no cron registration. |
| **3** | Phase 2 stable ≥10 trading days, 1–2 manual market-hours runs pass | OpenClaw cron registration (open window + core 15-min cadence + 16:15 ET digest). |
| **4** | Optional | Premarket gap mode, halt/resume detection, sector peer-relative beyond XBI, options cross-check via Spec 059 snapshots, Polygon/Massive upgrade if paid feed acquired. |

---

## Invariants (MUST hold across all phases)

- No write to `production_data/`, `rankings.csv`, event ledger, trade plan,
  or review queue from this agent.
- No scoring feature is derived from intraday quotes.
- No Grok-only evidence is labeled `OFFICIAL`.
- No yfinance / Morningstar path is the primary live source.
- No threshold fit to realized returns.
- Every email has a corresponding artifact.

---

## Open Questions

**Resolved in Phase 1:**

- ~~Share `WATCHLIST_MAX=40` via a common module~~ → `common/watchlist_config.py` shared between this agent and `price_action_watch`.
- ~~Initial provider choice~~ → Alpaca Basic (15-min delayed REST). Polygon/Massive kept as future paid-upgrade option.

**Remaining for Phase 2+:**

1. SMTP recipient list — confirm that reusing Herald's `ALERT_EMAIL_TO` is correct, or whether a separate `INTRADAY_ALERT_EMAIL_TO` is wanted.
2. Whether premarket (09:00–09:30 ET) gap detection belongs in Phase 4 or is a separate spec.
3. Whether to add Alpaca websocket IEX real-time as a secondary client for the "core hours" window (the REST snapshot path is sufficient for Phase 2, so this is deferred).

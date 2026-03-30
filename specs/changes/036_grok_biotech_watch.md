# Change Spec: Grok Biotech Watch with Email Alerts

**Status**: IN_PROGRESS
**Author**: dschulz
**Date**: 2026-03-30
**Ruleset impact**: NO (read-only alerting, does not affect scoring or rankings)

---

## Objective

Build a watchlist-scoped Grok/xAI search monitor that finds catalyst-relevant
news on model-held names, enriches matches with DEM context (tier, rank,
catalyst proximity, policy status), and emails actionable alerts to
`dschulz@wakerobin.co`. The goal is fast surface-level awareness of catalyst
developments on near-term names, not a replacement for the PIT-safe event stack.

## PIT / Data Constraints

- [x] No lookahead — reads only current snapshot and Grok search results
- [x] Data source: xAI Grok API (web search), local snapshots + artifacts
- [x] Not a scoring input — alerts are informational only, never fed back into DEM
- [x] Known gaps: Grok search coverage depends on xAI's web index; rate limits apply

## Inputs

| Input | Source | Schema |
|-------|--------|--------|
| Watchlist tickers | rankings.csv, positions.json, trade_plan.csv, review_queue.csv | ticker sets |
| Catalyst context | rankings.csv fields: tier_dev, actionable_rank, catalyst_days, catalyst_family, is_hard_catalyst | CSV columns |
| Policy status | artifacts/policy_shadow/ | JSON |
| Search results | xAI Grok API (chat completions with search) | JSON |

## Outputs

| Output | Destination | Schema |
|--------|-------------|--------|
| Alert JSON | artifacts/grok_watch/{date}_alerts.json | grok_watch.v1 |
| Alert MD | artifacts/grok_watch/{date}_alerts.md | markdown |
| Email | dschulz@wakerobin.co | HTML/text |

## Invariants

1. Read-only: never modifies rankings, scoring, rulesets, or production data
2. Watchlist-scoped: only searches for names in the current model watchlist (max ~40)
3. Deduped: same topic never fires the same alert twice within 4 hours
4. Rate-aware: respects xAI API rate limits; degrades to NO_DATA, never crashes

## Failure Modes

| Scenario | Expected behavior |
|----------|-------------------|
| xAI API down / rate limited | Log warning, write empty artifact, skip email |
| No XAI_API_KEY | Fail fast with clear error message |
| SMTP credentials missing | Write artifact but skip email, log warning |
| No matching results | Write artifact with n_alerts=0, no email sent |
| Snapshot missing | Return error, no crash |

## Alert Severity Rules

**HIGH** (immediate email):
- Official company / FDA / trial registry source
- Explicit catalyst language (topline, PDUFA, CRL, adcom, hold, approval)
- Credible source + near-term catalyst (<=14 days)

**MEDIUM** (daily digest):
- Credible biotech journalist / analyst source
- Catalyst keyword without official confirmation

**LOW** (daily digest only):
- General chatter, no official confirmation
- No catalyst proximity

## Delivery Policy

- **Immediate**: HIGH severity only, max 5 emails per hour
- **Daily digest**: all severities, grouped by ticker, deduped, after production run
- **Subject format**: `[HIGH] PVLA — Phase 3/topline chatter, 3d to readout`

## Non-Goals

- Not a historical research source
- Not a data source for scoring — alert-only
- Not monitoring all 354 universe tickers — watchlist-scoped only
- Not replacing the event ledger or catalyst stack
- Not performing sentiment analysis or NLP scoring

---

## Implementation Log

### 2026-03-30 — initial build
- Files: tools/build_grok_biotech_watch.py, agents/grok_biotech_watch/*, specs/changes/036_grok_biotech_watch.md
- Env: XAI_API_KEY, SMTP_HOST/PORT/USER/PASSWORD, ALERT_EMAIL_TO in .env.example

# Biotech Domain Checks

Use this reference when a review involves biotech-specific model, data, clinical, event EV, or production artifacts.

## 1. Alpha vs plumbing distinction

Classify the claimed benefit precisely:

- **Alpha improvement:** forward IC, hit rate, spread, XBI-relative excess return, drawdown-adjusted return, or selection quality improves out of sample.
- **Expectation-layer improvement:** market-implied expectation estimation becomes more complete or believable, but not necessarily predictive.
- **Plumbing improvement:** existing data becomes exported, normalized, cached, or consumed correctly.
- **Observability improvement:** logging, provenance, coverage reports, or diagnostics improve confidence without changing ranker/selector behavior.
- **Presentation improvement:** output is easier to read but signal quality is unchanged.

Default language: “This improves plumbing/coverage, not proven alpha,” unless validation proves otherwise.

## 2. Event EV / expectation-layer checks

For event EV and expectation gap work, ask:

- Are market expectation fields available at the relevant snapshot date?
- Are `close_price`, `market_cap_mm`, `short_interest_pct`, options/straddle/priced-move fields, and liquidity fields source-dated or snapshot-safe?
- Is `priced_move_pct` clearly labeled if derived from straddle price or implied move?
- Is the expectation model consuming the newly wired fields, or are they merely exported?
- Is historical backfill required before research claims are valid?
- Is the model estimating market-implied expectations rather than ranking biotech attractiveness?
- Is insider activity treated carefully as crowd-belief or information-flow context, not automatically as a selector signal?

Decision bias:

- Exporting existing fields can be a good plumbing change.
- Field coverage gains do not equal alpha.
- A starved expectation model can justify wiring, but not promotion of a trading signal.

## 3. CT.gov / FDA / catalyst checks

For clinical/catalyst changes, verify:

- CT.gov evidence is anchored to `lastUpdatePostDateStruct.date` or an equivalent observable source date.
- Effective date is next trading day when appropriate.
- Timeline push/pull logic uses a noise band; do not overreact to trivial date shifts.
- Trial status changes distinguish upgrade, downgrade, severe negative, and administrative edits.
- ACTUAL primary completion dates and results-posting events are handled separately from estimated dates.
- Endpoint, population, phase, indication, mechanism, and comparator mapping are not inferred beyond evidence.
- FDA/regulatory catalysts are source-dated and not backfilled from later outcomes.
- Post-event knowledge does not enter pre-event snapshots.

Common failure mode: a clinical event is real, but the date at which the market could know it is wrong.

## 4. PIT/provenance checks

Require evidence for:

- snapshot date
- source date
- effective date
- input hashes
- generated artifact exclusion/inclusion policy
- universe membership as of date
- delisted ticker handling
- price source and adjustment status
- replay determinism

Red flags:

- future data filtered only by run date rather than snapshot date
- source files refreshed during historical replay
- generated sidecars included as inputs by accident
- stale XBI or price histories silently reused
- universe loaded from a different path than production
- missing forward snapshot treated as IC = 0 instead of unobservable

## 5. Corporate-action and survivorship checks

Before accepting biotech backtest results, ask whether the names include:

- reverse splits
- spinouts
- mergers/acquisitions
- ticker changes
- delistings
- bankruptcies or liquidation events
- special distributions
- raw vs split-adjusted price mismatches
- stale tickers still appearing in screen output

Default rule: a spectacular single-name return in biotech is suspicious until corporate-action-cleaned.

## 6. Backtest validity checks

For claimed model improvement, ask for:

- baseline comparison against current production/ranker/selector
- multiple dates and regimes, not one favorable window
- XBI-relative performance, not only raw return
- horizon match to intended signal half-life
- selection count stability
- sample size and confidence interval or t-stat caveat
- turnover and implementation friction
- ablation showing which feature drives the gain
- failure-period analysis, not just aggregate success

Do not overstate small IC changes with unstable sample size.

## 7. Hermes/Wake Robin production checks

For production-path changes, check:

- deterministic output projection before/after
- schema compatibility for downstream consumers
- `rankings.csv` column changes and null coverage
- snapshot overwrite guards
- no unexpected writes during historical replay
- cache warm scope and timeout behavior
- CI and targeted tests
- lint environment limitations clearly labeled
- rollback/revert path
- no cron expansion without explicit approval

If a change affects `final_score`, rankers, selectors, gates, portfolio, or trading language, treat blast radius as high until proven otherwise.

## 8. Portfolio/risk checks

When a change might affect actionability, check:

- liquidity and ADV guardrails
- market cap and float constraints
- concentration and correlated catalyst exposure
- XBI regime and beta exposure
- short interest as both risk and possible catalyst amplifier
- options-implied move vs internal event EV
- slippage and turnover
- crowding by elite managers
- drawdown and left-tail event risk

Council output may recommend monitoring or research prioritization, but not automatic trading.

## 9. Recursive improvement checks

When a review reveals a failure, near miss, or repeated manual debate, ask whether Hermes/Wake Robin should learn a durable guardrail.

Good candidates:

- repeated feature-starvation checks become coverage monitors
- repeated source-date debates become required artifact fields
- corporate-action surprises become suspect-return audits
- stale ticker or delisting drift becomes universe-loader tests
- cache/replay mistakes become no-live-fetch replay assertions
- recurring “alpha vs plumbing” confusion becomes promotion-gate language

Bad candidates:

- changing a model weight because one review found a persuasive story
- adding a new ranker rule from one anecdote
- automating production promotion after the council agrees
- expanding cron because a manual check was annoying
- treating documentation improvement as predictive evidence

The goal is compounding review quality: fewer repeated debates, earlier detection of false alpha, and cleaner evidence for future biotech decisions.

# Biotech IC Council Review Rubric

Use this rubric for strict merge, hold, revert, or production-readiness decisions.

## Severity levels

### S0 — blocker

Use when the issue can create false historical alpha, contaminate production, mutate trading-adjacent state, expose credentials, or make deterministic replay impossible.

Examples:

- point-in-time leakage
- forward returns, later trial outcomes, or future source dates entering features
- raw split/unadjusted corporate-action artifact driving IC, spread, or returns
- reverse split, spinout, merger, ticker change, or delisting not handled in a backtest window
- production snapshot overwrite without guardrails
- credential exposure in scripts, logs, process args, CI, or provider detection
- cron/automation writes without explicit operator approval
- schema change that breaks downstream consumers without migration
- brokerage/trading action implied by model output
- historical replay performs live fetches or refreshes mutable sources

Default decision: reject, revert, or hold pending fix.

### S1 — high

Use when the issue could materially distort research conclusions or production reliability but is bounded and fixable.

Examples:

- untested fallback behavior
- incomplete delisting or stale-universe handling
- stale XBI, price, clinical, or universe source
- fragile JSON/CSV construction
- generated artifacts included in input hashes unintentionally
- validation only on a favorable date/window
- insufficient corporate-action screen
- CT.gov/FDA event has weak source-date or effective-date proof
- expectation-layer fields exported but not confirmed consumed
- production wrapper can fail after writing partial artifacts

Default decision: hold pending validation, or merge as research-only if isolated.

### S2 — medium

Use when the issue weakens confidence but does not obviously invalidate the result.

Examples:

- missing secondary window
- unclear metric naming
- weak documentation
- incomplete monitoring plan
- limited fixture coverage
- non-critical output field coverage gap
- no ablation for a plausible but bounded feature change
- insufficient explanation of XBI-relative vs raw return

Default decision: watch or require post-merge monitoring.

### S3 — low

Use when the issue is cosmetic, documentation-only, or easily reversible.

Examples:

- wording ambiguity
- harmless formatting drift
- non-semantic refactor with passing tests
- documentation-only memo with no production path

Default decision: approve with notes.

## Merge gates by change type

### Alpha/model changes

Require:

- baseline comparison against current production ranker/selector
- out-of-sample or forward validation appropriate to horizon
- alternate window/regime check, including XBI-relative framing
- corporate-action, delisting, and survivorship artifact screen
- PIT source-date proof
- ablation or reasoned attribution for the claimed improvement
- selection count, turnover, and implementation-friction review
- clear rollback path

### Event EV / expectation-layer changes

Require:

- field coverage before/after for expected inputs
- proof newly exported fields are actually consumed by the expectation model
- distinction between market-implied expectation estimation and alpha selection
- historical backfill plan if research uses prior snapshots
- null/coverage behavior for small caps and options-unavailable names
- no claim of alpha without separate forward validation

### Feature/plumbing changes

Require:

- field coverage before/after
- schema compatibility check
- downstream consumer check
- representative historical replay if historical artifacts are affected
- no claim of new alpha unless separately validated
- production snapshot check after first live run if applicable

### Production/reliability changes

Require:

- targeted tests
- deterministic replay or stable output projection
- failure-mode test
- no unintended artifact writes
- no cron expansion unless explicitly approved
- cache/fallback behavior tested if touched
- rollback command or revert path

### Clinical/catalyst changes

Require:

- source-date anchored clinical/regulatory evidence
- next-trading-day effective-date logic where appropriate
- endpoint/population/phase/indication/mechanism mapping check
- event timing and severity/noise-band justification
- ACTUAL vs ESTIMATED dates separated
- no use of post-event knowledge in pre-event snapshots

### Portfolio/risk changes

Require:

- liquidity and ADV guardrail check
- concentration, beta, and sector exposure check
- turnover/slippage consideration
- options/priced-move interpretation separated from alpha signal
- short-interest/crowding risk considered
- drawdown/regime stress where relevant

## Decision language

Use precise language:

- “This improves plumbing/coverage, not proven alpha.”
- “This improves expectation estimation, not selector validity.”
- “This is research-valid but not production-ready.”
- “This should merge only behind a no-production-impact flag.”
- “This is blocked because it can create false historical alpha.”
- “This is blocked until corporate-action contamination is ruled out.”
- “No consensus: human operator should decide after the listed validation.”

## Recursive self-improvement gates

Use these gates when a review recommends future changes to tests, monitors, rubrics, or model behavior.

### Process-only recursive improvements

Approve when the item:

- clarifies a recurring manual judgment
- improves review consistency
- does not alter production behavior or model outputs
- has a named failure mode or ambiguity it addresses

Examples:

- add a checklist for corporate-action screening
- add standard language separating expectation-layer plumbing from alpha
- add a postmortem template section for source-date evidence

### Deterministic guardrail improvements

Hold for implementation review unless the guardrail is already implemented and tested. Require:

- exact failure mode
- deterministic pass/fail condition
- fixture or representative test case
- no unintended production writes
- no model-output changes unless explicitly scoped

Examples:

- CI check for source_date > snapshot_date
- replay assertion that historical runs do not live-fetch mutable sources
- schema/null-coverage check for `rankings.csv` expectation fields
- corporate-action audit for extreme biotech returns

### Model-affecting recursive improvements

Treat as a new model or portfolio proposal. Require a full council review before merge.

Examples:

- changing final_score weights based on a postmortem
- promoting an expectation-gap rule into a selector
- changing catalyst severity weights after one event
- changing portfolio sizing or risk gates

Default language: “This learning is valid, but encoding it into the model requires separate alpha validation.”

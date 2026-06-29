# Recursive Self-Improvement Protocol

Use this reference when a Biotech IC Council review should produce durable improvements to Hermes/Wake Robin review quality, tests, monitors, or promotion standards.

## 1. Definition

Recursive self-improvement means converting each review into better future review machinery. It does not mean autonomous model rewrites, automatic production promotion, or trading actions.

Good recursive improvement:

- turns repeated manual concerns into tests, fixtures, monitors, schemas, or checklists
- makes false alpha harder to accept next time
- improves point-in-time replay and source-date discipline
- makes backtest contamination easier to detect
- clarifies when a change is alpha, plumbing, expectation-layer, or governance-only
- improves post-merge monitoring and rollback criteria

Bad recursive improvement:

- silently changes model weights, thresholds, rankers, selectors, gates, or final_score
- lets an LLM approve its own future changes
- expands cron or production writes without operator approval
- treats a process improvement as alpha
- adds complexity without a named failure mode

## 2. Learning loop

Apply this loop at the end of each review:

1. **Observe:** What evidence, failure, near miss, or uncertainty appeared?
2. **Classify:** Is it alpha, PIT/provenance, clinical/catalyst, production, portfolio/risk, or review-process related?
3. **Encode:** Can it become a unit test, fixture, CI guard, schema check, dashboard monitor, runbook step, memo template, or review rubric update?
4. **Constrain:** Is the proposed improvement read-only/process-only, deterministic guardrail, or model-affecting?
5. **Validate:** What proves the improvement works without creating false confidence?
6. **Review again:** Any model-affecting improvement must return to the council as a separate proposal.

## 3. Improvement classes

### Safe process improvement

Use for low-risk changes that improve human review quality.

Examples:

- add a checklist item for spinouts after discovering RNA-like contamination
- add a runbook note that expectation-layer field wiring is not alpha
- add a standard section for source-date/effective-date evidence
- add a template line for XBI-relative returns

Default treatment: acceptable as documentation/governance unless it implies production behavior.

### Safe deterministic guardrail

Use for objective checks that can run without changing model behavior.

Examples:

- regression fixture for reverse split contamination
- source-date assertion for CT.gov deltas
- snapshot replay check that fails on live fetch evidence
- rankings.csv null-coverage report for expectation-layer fields
- schema compatibility check for downstream consumers
- corporate-action suspect-name audit for extreme returns

Default treatment: good candidate for future PR, but still require tests and no-production-impact review.

### Model-affecting improvement

Use for changes that alter prediction, ranking, selection, scoring, event EV math, gates, thresholds, or portfolio actionability.

Examples:

- new feature in final_score
- changed selector threshold
- changed event severity weights
- new expectation-gap trading/ranking rule
- changed sizing or risk policy

Default treatment: must be reviewed as a new alpha/model or portfolio/risk proposal. Do not bundle into a process-cleanup merge.

## 4. Recursive improvement decision tests

Before recommending a recursive improvement, answer:

- What exact prior failure or near miss does this address?
- Would this have caught the current issue earlier?
- Is it deterministic enough to test?
- Is it cheaper than repeated manual review?
- Could it block valid alpha because of overfitting to one incident?
- Does it preserve point-in-time replay?
- Does it avoid changing the model unless separately approved?

Reject or defer broad improvements that cannot name a failure mode.

## 5. Biotech-specific examples

### Corporate-action learning

If a backtest is distorted by a reverse split, spinout, or delisting:

- recommend a corporate-action suspect audit for extreme single-name returns
- add fixture names and dates if known
- require split-adjusted/raw price comparison in future validation
- do not mark the alpha signal invalid until recomputed on cleaned data

### CT.gov/FDA source-date learning

If a catalyst review lacks source-date proof:

- recommend a required `source_date`, `effective_date`, and observable-source field in future artifacts
- add a next-trading-day effective-date fixture
- mark post-event knowledge as an S0 blocker if it enters historical features

### Expectation-layer learning

If field wiring improves coverage:

- recommend coverage monitoring and consumption checks
- distinguish export coverage from model consumption
- require historical backfill before historical research claims
- do not create a selector/ranker rule without forward validation

### Production replay learning

If a replay uses live sources or mutable caches:

- recommend a no-live-fetch replay assertion
- add input-hash and generated-artifact boundary checks
- require stable projection of decision-relevant fields
- treat cron expansion as separate operator-approved work

## 6. Output language

Use precise phrasing:

- “Recursive follow-up: convert this manual concern into a deterministic guardrail.”
- “This is a process improvement, not model improvement.”
- “This should become a fixture before the next similar promotion review.”
- “Do not encode this as a model rule until forward validation supports it.”
- “The system learned a review standard, not an alpha signal.”

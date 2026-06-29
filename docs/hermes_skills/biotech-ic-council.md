---
name: biotech-ic-council
---

# Biotech IC Council

## Mission

Run a small, read-only biotech investment committee review that extracts the useful deliberation protocol from a multi-agent council, but keeps the workflow deterministic, narrow, and safe for serious biotech research governance.

Treat the council as both a **promotion-gate reviewer** and a **recursive self-improvement loop**. Its job is to make false alpha harder to accept, protect point-in-time replay, and convert every review into a sharper future process.

The council must separate:

- real biotech alpha vs better plumbing
- research-valid diagnostics vs production-ready changes
- clinical/catalyst evidence vs narrative enthusiasm
- market-expectation estimation vs selector/ranker alpha
- portfolio usefulness vs implementation risk
- one-off bug fixes vs durable improvements to tests, monitors, schemas, and review standards

Never mutate files, run production, change cron, touch credentials, place trades, send orders, or approve deployment solely from this review. Recommend validation, decision gates, and future process improvements only.

## Default council seats

Use exactly five seats unless the user requests otherwise:

1. **Alpha skeptic** — asks whether the change plausibly improves forward biotech alpha rather than merely improving coverage, narrative quality, or complexity. Tests the claim against IC, spread, hit rate, excess return, turnover, regimes, and out-of-sample/forward evidence.
2. **PIT/provenance auditor** — hunts source-date leakage, effective-date mistakes, stale or future snapshots, generated-artifact contamination, missing hashes, delisting drift, reverse splits, spinouts, mergers, raw/unadjusted price artifacts, and forward-return contamination.
3. **Clinical/catalyst reviewer** — reviews CT.gov, FDA, endpoint, population, phase, indication, mechanism, trial-status deltas, timeline push/pull, results-posting, and catalyst-severity logic. Separates true clinical information from post-hoc market interpretation.
4. **Production reliability reviewer** — checks determinism, schema stability, tests, CI, snapshot hygiene, cron safety, fallback behavior, cache behavior, output compatibility, and rollback path.
5. **Portfolio/risk reviewer** — evaluates liquidity, market cap, short interest, crowding, priced move/options interpretation, sector regime, XBI-relative risk, concentration, turnover, drawdown, and whether the change affects sizing or only ranking/review.

## Recursive self-improvement rule

Every review must produce a small learning artifact. The council should not only decide whether this change is acceptable; it must also identify how this review should make the system harder to fool next time.

For each review, ask:

- What failure mode did this reveal or almost reveal?
- Should this become a unit test, fixture, regression test, CI gate, dashboard check, schema assertion, runbook step, or review checklist item?
- Did the evidence change any prior assumption about biotech alpha, event EV, PIT safety, corporate actions, or production risk?
- What should be watched in the next live snapshot or forward validation window?
- What would prevent this same debate from recurring manually?

Separate recursive improvements into three classes:

- **safe process improvement:** documentation, checklist, manual review, naming, runbook, dashboard note.
- **safe deterministic guardrail:** test, fixture, schema assertion, provenance check, null-coverage check, replay check.
- **model-affecting improvement:** changes features, weights, thresholds, rankers, selectors, final_score, gates, event EV calculations, or portfolio actionability. These require their own future IC review.

Do not recommend self-modifying models, automatic promotion, automatic trading, or autonomous production rewrites. Recursive improvement means disciplined feedback loops, not uncontrolled agent mutation.

## Hard safety boundaries

- Stay read-only unless the user explicitly asks for a separate implementation task.
- Do not recommend live trading, order placement, brokerage integration, or automatic portfolio action from council output.
- Do not treat a council recommendation as approval to merge into production; require explicit human/operator approval.
- Do not allow cron, credential, production snapshot, or trading-adjacent changes to pass without an explicit blast-radius and rollback discussion.
- Do not infer missing tests, missing data coverage, or missing source dates. Mark them `unobserved`.
- Do not let better feature coverage be described as alpha unless supported by forward/out-of-sample validation.
- Do not accept raw returns from biotech names without checking splits, reverse splits, spinouts, M&A, delistings, and special distributions.
- Do not accept catalyst claims without source-date/effective-date discipline.
- Do not propose recursive changes that silently alter `final_score`, selectors, rankers, gates, event EV math, or portfolio policy. Those are new model changes and require separate review.

## Biotech-specific review anchors

When relevant, explicitly check these domains:

- **Hermes/Wake Robin artifacts:** `rankings.csv`, snapshots, sidecars, provenance metadata, `run_screen.py`, production wrapper, universe loader, price history, clinical cache, event outputs, final_score, selector/ranker/gates.
- **Event EV / expectation layer:** distinguish market-implied expectation features (`short_interest_pct`, `priced_move_pct`, `market_cap_mm`, `close_price`, options/straddle fields) from alpha selectors. Ask whether the change improves expected-move estimation, not whether it directly predicts returns.
- **Clinical delta logic:** CT.gov `lastUpdatePostDateStruct.date`, next-trading-day effective dating, trial status upgrades/downgrades, timeline push/pull, ACTUAL date confirmation, results posted, severity/noise-band thresholds.
- **PIT discipline:** source dates must be observable on or before the snapshot date; forward returns must never enter features; generated outputs must not feed input hashes unless intentionally frozen.
- **Corporate actions:** reverse splits, spinouts, M&A, delistings, ticker changes, stale tickers, split-adjusted vs raw prices, and survivorship bias.
- **Backtest validity:** regime mix, secondary windows, XBI-relative returns, selection count stability, IC with sample size, Newey-West/t-stat claims, false precision, and single-date cherry-picks.
- **Production reliability:** deterministic replay, schema compatibility, output diff projection, cache timeouts, fallback sources, CI status, lint/test environment limitations, and rollback command.
- **Portfolio/risk:** ADV/liquidity, small-cap slippage, crowded elite-manager ownership, short-interest squeeze/fragility, options-implied move, concentration, drawdown, and whether the result should affect sizing.
- **Learning loop:** convert repeated manual concerns into durable tests, fixtures, monitors, provenance checks, runbook steps, or promotion-gate criteria.

## Review workflow

### 1. Restatement gate

Begin by restating the proposed change in one paragraph and classify it as one or more of:

- alpha/model change
- event ev / expectation-layer change
- research-only diagnostic
- feature/plumbing change
- clinical/catalyst logic change
- production/reliability change
- data/provenance change
- portfolio/risk policy change
- documentation/governance-only change
- recursive self-improvement / review-process change

Then state the likely blast radius:

- no production impact
- output/schema impact
- ranking/selector/scoring impact
- event ev / expectation-layer impact
- clinical/catalyst artifact impact
- snapshot/provenance impact
- cron/automation impact
- portfolio/trading impact
- future review/test/process impact
- unknown until validated

If the proposal is ambiguous, proceed with best-effort assumptions rather than stalling, and list the assumptions.

### 2. Evidence inventory

Create a compact inventory of available and missing evidence:

- inputs reviewed: diffs, files, logs, metrics, tests, screenshots, pasted claims
- claimed benefit
- observed metrics and windows
- affected fields/artifacts
- affected dates/snapshots/universe
- source-date/effective-date evidence
- corporate-action/delisting evidence
- known missing checks
- production or schema impact
- alpha claim vs plumbing claim
- prior failure or recurring concern this addresses
- proposed future guardrail, if any

### 3. Blind first round

Write one short independent assessment from each seat before synthesis. Each seat must include:

- stance: support / oppose / hold / needs-validation
- strongest concern
- required validation
- biotech-alpha relevance
- learning-loop implication

Do not let later seats defer to earlier seats. Preserve disagreement.

### 4. Cross-examination

List the strongest challenge each seat would pose to another seat. Use this to expose hidden assumptions, especially:

- is this real forward biotech alpha or just better coverage?
- could this be PIT leakage, survivorship bias, stale data, or corporate-action noise?
- does the result survive alternate dates, horizons, and XBI regimes?
- are event dates source-dated and effective-dated correctly?
- is the expectation layer being confused with the selector/ranker?
- does the production path preserve deterministic replay?
- could this increase turnover, crowding, slippage, or false conviction?
- should this concern become a durable test, monitor, fixture, or checklist item?

### 5. Dissent and novelty gate

Explicitly identify:

- strongest credible reason to reject or delay the change
- strongest credible reason to continue or merge the change
- most likely hidden failure mode
- evidence that would change the council's mind
- whether the change improves alpha, improves confidence, improves observability, or merely improves presentation
- what this review teaches the system that it did not previously encode

If no credible dissent exists, state why the change is low-risk and what bounded validation still applies.

### 6. Decision matrix

Return a table with these rows:

- alpha validity
- expectation-layer validity, if relevant
- PIT/provenance safety
- clinical/catalyst validity, if relevant
- corporate-action/delisting safety
- production readiness
- portfolio/risk safety
- test adequacy
- rollback clarity
- recursive improvement value

Use status values only: `pass`, `watch`, `fail`, `unobserved`.

### 7. Recursive improvement register

Create a compact register of future improvements surfaced by the review. Include only items supported by evidence or clear repeated risk.

For each item, specify:

- improvement: what should change in future process or infrastructure
- class: safe process improvement / safe deterministic guardrail / model-affecting improvement
- owner: human operator / future PR / future research memo / future production review
- trigger: when it should be revisited
- alpha relevance: how it improves biotech alpha, reduces false alpha, improves expectation accuracy, or protects production integrity

Bias toward small, testable, reversible improvements. Do not create broad automation mandates.

### 8. Final IC recommendation

Choose exactly one final recommendation:

- **merge / approve** — evidence is sufficient and blast radius is controlled.
- **merge only as research-only** — useful diagnostic, not production-approved.
- **merge only as plumbing / no-alpha-claim** — improves coverage, export, observability, or expectation estimation, but does not yet prove alpha.
- **hold pending validation** — promising but missing required proof.
- **reject / revert** — likely harmful, misleading, leaky, or outside mandate.
- **no consensus** — irreducible disagreement; escalate to human operator.

Include:

- required pre-merge checks
- post-merge monitoring checks
- rollback trigger
- recursive follow-up
- one-sentence alpha thesis
- one-sentence risk thesis
- decision-owner note: what the human operator must decide

## Required output format

Use this structure:

```markdown
## Biotech IC Council Review

### 1. Restatement Gate
...

### 2. Evidence Inventory
...

### 3. Blind First Round
| Seat | Stance | Strongest concern | Required validation | Biotech-alpha relevance | Learning-loop implication |
|---|---|---|---|---|---|
...

### 4. Cross-Examination
...

### 5. Dissent and Novelty Gate
...

### 6. Decision Matrix
| Dimension | Status | Rationale |
|---|---|---|
...

### 7. Recursive Improvement Register
| Improvement | Class | Owner | Trigger | Alpha relevance |
|---|---|---|---|---|
...

### 8. Final IC Recommendation
**Recommendation:** ...

**Required pre-merge checks:** ...
**Post-merge monitoring:** ...
**Rollback trigger:** ...
**Recursive follow-up:** ...
**Alpha thesis:** ...
**Risk thesis:** ...
**Decision-owner note:** ...
```

## Supporting references

- Use `references/review-rubric.md` for strict severity levels, merge gates, blocker classification, and recursive improvement gates.
- Use `references/biotech-domain-checks.md` when the review involves event EV, CT.gov/FDA catalyst logic, corporate actions, expectation-layer fields, Hermes/Wake Robin artifacts, or backtest validity.
- Use `references/recursive-improvement.md` when the review asks how the system should learn from failures, postmortems, repeated manual checks, or promotion-gate debates.

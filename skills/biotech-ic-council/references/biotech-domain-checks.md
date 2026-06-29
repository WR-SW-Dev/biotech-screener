# IC Council — Biotech Domain Checks

Companion reference for `skills/biotech-ic-council/SKILL.md`. Load this when a review touches event EV / the expectation layer, CT.gov/FDA catalyst logic, corporate actions, expectation-layer fields, Hermes/Wake Robin artifacts, or backtest validity. It expands the "Biotech-specific review anchors" section of the skill into concrete, checkable items.

These are checks, not authorizations. The council applies them read-only; any change they implicate to scoring, ranking, gates, or sizing still requires a separate model-change review.

## Event EV / expectation layer

The expectation layer estimates how much of a catalyst is already priced. It is NOT an alpha selector — keep the two separate in every finding.

- Confirm expectation features are used to answer "is this already priced?" — not "does this predict return?". A change that improves expected-move estimation is plumbing, not alpha, unless forward-validated.
- Verify the market-implied fields are present and sane: `short_interest_pct`, `priced_move_pct`, `market_cap_mm`, `close_price`, and any options/straddle-implied move fields.
- Watch for the recurring confusion (`IC_EXPECTATION_*`): an expectation feature being credited as ranker/selector alpha. Flag it.
- Insider net-buying coverage is the known weak spot — if a finding leans on it, confirm coverage exists rather than assuming it.

## Clinical / catalyst logic (CT.gov + FDA)

- Effective dating: a CT.gov change is observable via `lastUpdatePostDateStruct.date`; the feature must take effect on the **next trading day**, never the event day itself (no same-day leakage).
- Distinguish trial-status **upgrades vs downgrades**, timeline **push vs pull**, and confirm `ACTUAL` date confirmation vs estimated/anticipated.
- Treat "results posted" as a distinct event from a status flip — they have different severity.
- Severity / noise-band thresholds: confirm the change respects the documented bands rather than re-deriving them. Any change to the bands themselves is model-affecting (needs a Spec).
- Separate true clinical information from post-hoc market interpretation: a price move is not clinical evidence.

## Corporate actions

Every biotech price series must be checked for corporate-action contamination before any return is trusted:

- reverse splits and forward splits (split-adjusted vs raw price)
- spinouts and special distributions
- M&A (cash, stock, CVR) — confirm the terminal date and whether the name is mid-deal
- delistings and ticker changes — confirm the last valid candle and `DATA_STALE` handling
- survivorship bias — confirm delisted names are retained in historical universes, not silently dropped

If raw (unadjusted) prices could have entered a feature, that is a BLOCKER (`IC_CORP_ACTION_*`).

## PIT discipline

- Source dates must be observable on or before the snapshot date. A future-dated source in a historical snapshot is PIT leakage.
- Forward returns must never enter features under any circumstance.
- Generated outputs must not feed input hashes unless the freeze is intentional and documented.
- When provenance evidence (source_date, effective_date, hashes) is missing, mark `unobserved` — do not infer it.

## Hermes / Wake Robin artifacts

Know which artifact a finding touches and its blast radius:

- `rankings.csv` (the production sort surface), snapshots, sidecars, provenance metadata
- `run_screen.py`, the production wrapper, the universe loader, price history, clinical cache, event outputs
- `final_score`, the selector, the ranker, and the gates — any change here is model-affecting, full council, Spec-gated.

Architecture reminder for context (do not re-litigate it in a review): the production pipeline is `universe → A4 selector (sel_score) → clinical_50 ranker (final_score) → actionable_rank → DEM top-30`. "DEM" is the stored production top-30 of the current ranker, not a separate baseline algorithm. Do not present the production top-30 as a competitor "baseline" to its own selector overlay (failure mode `IC_BACKTEST_` / F-2026-010).

## Backtest validity

When a finding cites backtest evidence, check:

- **Regime mix** — is the result concentrated in a few rally months? Report ex-best-months performance, not just the headline.
- **Secondary windows** — does the edge survive outside the primary window and outside extraordinary XBI rallies?
- **XBI-relative** — are returns excess vs XBI, or is "alpha" actually beta/convexity?
- **Selection-count stability** — does the top-N count drift run to run?
- **IC with sample size** — an IC claim needs n and a t-stat; reject false precision and single-date cherry-picks.
- **Newey-West / t-stat** — confirm the standard-error treatment matches the overlap structure.
- Confirm the IC tool declares **which score field** it measures and that the field matches the production sort key (final_score), per failure mode F-2026-002.

## Production reliability

- Deterministic replay must hold: same inputs → same outputs.
- Schema compatibility and an output-diff projection for any change touching `rankings.csv` or snapshot outputs.
- Cache timeouts and fallback sources behave safely on miss.
- CI status is read and **stated explicitly** — never assumed green. A red or unobserved CI blocks any production-path approval above `hold`.
- A rollback command/path is named for every production change.

## Portfolio / risk

- ADV / liquidity and small-cap slippage realism.
- Crowding in elite-manager-owned names; short-interest squeeze/fragility.
- Options-implied move vs the model's expected move.
- Concentration and drawdown; whether the change should affect **sizing** (Spec-gated) or only ranking/review.

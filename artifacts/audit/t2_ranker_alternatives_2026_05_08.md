# T2 — Investment-Thesis Ranking Alternatives Catalog
**Date:** 2026-05-08
**Author:** T2 [researcher]
**Task:** Investment-thesis ranking alternatives (Task #2 in ranking-alternatives research queue)
**Status:** Research memo — no code changes, no production artifact writes, no promotions recommended

---

## Scope and constraints

This memo catalogs 10 candidate ranker designs from investment logic. For each, it answers:
1. What mispricing does it exploit?
2. Why should it make money?
3. What would falsify it?
4. What data does it require?
5. What is the main overfitting risk?
6. What production role could it eventually serve?
7. Reasons not to test or implement yet.

**Hard constraints honored throughout:**
- No code changes, no production artifact writes
- No recommendation to implement or promote
- Uncertainty marked explicitly
- All claims grounded in existing evidence from memory, specs, and artifacts — not inference from field names alone

**Production baseline context:**
The live 2-feature pairwise ranker (`production_data/ranker_v2_model.json`, `model_variant = deployed_live_pilot`) uses:
- Feature 1: `coinvest_score_z` — trained weight +0.0613, **deployed (capped) weight +0.02**
- Feature 2: `financial_score` — weight -0.0533 (unchanged from trained)
- Bias: +0.5019
- Architecture: pairwise logistic, cohort top-60, no catalyst-window gate, EW scoring
- Selector (v1.14.0, ruleset `8887576e`): `coinvest_score_z` 100%, `inst_delta_z` 0% (demoted 2026-05-04)

---

## Alternative 1 — Current minimal ranker baseline (coinvest + financial_score)

### What mispricing does it exploit?
Smart-money consensus (13F institutional co-investment) as a quality screen for names the market undervalues; combined with a financial-stress overlay that penalizes names with "safe" balance sheets — i.e., profitable names that do not need a catalyst to prove value. The thesis: biotech mispricing is concentrated in high-conviction-institutional, high-stress-upside names, not in comfortable balance-sheet names.

### Why should it make money?
- Institutional co-investment reflects aggregated fundamental due diligence from specialist biotech investors — an information advantage over retail and generalist capital.
- The negative `financial_score` weight penalizes names that have already "earned" their valuation through existing revenue. Those names' upside is capped relative to pre-revenue names facing a binary catalyst.
- The combination is consistent with a release-valve / binary-optionality thesis: select the names where specialist capital has taken conviction AND the stock has maximum binary upside.

### Why it should (and should not) make money — evidence from production:
**Supporting:** Ranker IC = +0.106 (coinvest_score_z in ranker); selector Δ = +1.75pp (t=3.05) for coinvest_score_z. Forward-return test (8 snapshots, 2026-05-01): production top-30 outperformed coinvest-only top-30 by +0.31pp median (coinvest-eligible comparator), +0.88pp vs coinvest-full — though 4/8 sign test and +0.10pp rescued-vs-suppressed differential make this INCONCLUSIVE.

**Against:** The coinvest weight is capped (0.02 vs trained 0.613) specifically because the selector already uses coinvest as its primary dimension. The ranker effectively re-sorts on the same signal that passed the gate, with a partial financial overlay. Whether this adds value beyond the selector alone is unproven (see Task #1 anatomy note: `coinvest_score_z` explains 92.7% of selector variance — the ranker inherits a narrowed, already-coinvest-sorted cohort).

### What would falsify it?
- Rescued-vs-suppressed differential (production deviations from coinvest-only) is persistently ≤ 0 over ≥30 resolved snapshots.
- IC of coinvest_score_z within the selector-passed cohort (not full universe) is indistinguishable from zero.
- `financial_score` coefficient sign reverses in forward validation (i.e., financially-stressed names underperform within the cohort).

### Data required:
Already in production. No new fields needed.

### Main overfitting risk:
Family C cap (+0.02) was derived from a live-pilot calibration whose full derivation may not be documented. If the cap is artifact of a particular time window rather than a principled double-count correction, the deployed vector may not generalize. Additionally, 36 training dates (pre-PIT-fix period) means the trained model's backward-looking calibration could be partially contaminated.

### Production role:
Current production ranker. Baseline for all ablations.

### Reasons not to change:
Architecture frozen (`policy_freeze_architecture_2026_04_19.md`). Forward evidence insufficient (n=8). Cohort quarantine active through ~2026-05-15. Any modification requires Checklist v2.

---

## Alternative 2 — Orthogonal ranker (signals not already in selector)

### What mispricing does it exploit?
The selector saturates on `coinvest_score_z`. An orthogonal ranker would attempt to rank within the coinvest-filtered cohort using signals that capture a *different* dimension of return predictability — one the selector cannot have already sorted out.

The orthogonality hypothesis: after coinvest filtering, the residual return spread within the cohort is driven by factors the selector is blind to (catalyst timing, financial stress, event quality, expectation gap). A ranker built on those orthogonal factors adds an independent second predictor.

### Why should it make money?
If the return distribution within the selected cohort has structure that coinvest_score_z does not explain (which is plausible given the selector restricts its range), then a ranker trained on that structure captures alpha that the selector cannot. The two-layer pipeline becomes truly two-factor: selection on institutional quality + ranking on something the market has priced differently.

### Why it should (and should not) make money — uncertainty:
**Supporting:** The D8/D9 finding (vNext 2026-05-01) showed clinical_quality IC ≈ +0.20 conditional on manager gate, after orthogonality test (D7) — the first empirical evidence that orthogonal signal exists within the gated cohort. Spec 081 documents the hypothesis formally.

**Against:** If coinvest quality is monotonically predictive at all levels of granularity (not just for selection), then restricting the ranker to orthogonal signals means discarding the single strongest available predictor. The current cap-not-eliminate design is a practical resolution of this tension, not a proof that orthogonal signals add value. The n=7 resolved observations behind the D8/D9 finding are not promotion-grade.

**Risk of circular reasoning:** An "orthogonal ranker" defined post-hoc by searching for signals that correlate with returns after controlling for coinvest is susceptible to data-snooping. The right path is: commit to a specific investment-logic hypothesis first (see alternatives 3–9 below), then test whether that signal is orthogonal.

### What would falsify it?
- Ablation comparison B0 vs B3 (Spec 081 battery): orthogonal ranker (financial_score + catalyst_decay_w, no coinvest) has IC ≤ baseline (coinvest + financial_score).
- All candidate orthogonal features tested individually have IC ≤ 0 within the selected cohort.

### Data required:
Depends on which orthogonal signals are chosen. At minimum, the Spec 081 ablation battery (variants B0–B5) needs: catalyst_decay_w in production, ≥30 resolved outcomes post-PIT, post-13F cohort window.

### Main overfitting risk:
Selecting "orthogonal" features based on sample IC correlation with residualized coinvest is a form of in-sample search. Any feature found this way requires out-of-sample validation on unseen snapshots, not just more of the same panel.

### Production role:
Future ranker candidate — only after Spec 081 ablation runs and clears evidence thresholds.

### Reasons not to test yet:
Post-13F cohort window not closed (~2026-05-15). n(resolved outcomes post-PIT) ≈ 7. False-catalyst hygiene (Spec 078) not yet in production — any signal correlated with catalyst quality will be contaminated by ~18.8% false-catalyst rate. Architecture frozen.

---

## Alternative 3 — Catalyst-timing ranker (catalyst_decay_w / days_to_catalyst / event imminence)

### What mispricing does it exploit?
The market prices a near-term catalyst (27-day PDUFA) and a far-out catalyst (300-day Phase 3 completion) at different option-time-values. Within the selected cohort, names with imminent catalysts should attract more capital and realize more of their binary upside sooner. A timing-weighted ranker prioritizes names whose binary release valve is near, rather than distributing equal probability-weight to a name that must wait 10 months.

The specific mispricing: the current ranker is blind to timing within the selector-passed cohort. A 27-day and a 300-day name with identical coinvest and financial scores receive identical ranker output. If time-discounted option value is predictive of forward return (a reasonable biotech thesis), this is a systematic gap.

### Why should it make money?
- Pre-catalyst run-ups are documented across biotech literature. Names with near-term catalysts attract trading activity, analyst upgrades, and speculative positioning.
- `catalyst_decay_w = exp(-days_to_catalyst / decay_half_life)` is a principled time-discount of the binary event.
- The selector already gates on `catalyst_in_window` as a threshold — but the ranker does not distinguish within the passed cohort by timing gradient. A timing ranker completes the thesis: select names with near-term catalysts, then rank by how near.

**Key uncertainty:** The selector's `selector_catalyst_block` already carries a 0.25 default weight and uses `catalyst_decay_w`. Top-30% representation is FLAT across proximity buckets (0-30/31-60/61-120/120+) — suggesting the selector has already absorbed the proximity sweet spot (Phase A catalyst verdict, 2026-05-04). Whether there is *additional* timing gradient within the passed cohort beyond what `selector_catalyst_block` captures is the empirical question.

### What would falsify it?
- Within selector-passed cohort, Spearman(catalyst_decay_w, fwd_return) ≤ 0 after NW correction.
- Adding timing to the ranker (Spec 080 variants A1–A3) does not improve IC vs baseline (A0) by a margin that survives FDR correction.
- Timing signal is dominated by false-catalyst contamination: after Spec 078 hygiene, IC drops to ≤ 0.

### Data required:
- `catalyst_decay_w` in production (confirm via `specs/changes/` — known to be computed)
- `days_to_catalyst_norm` — confirm available
- `catalyst_score` — available in rankings.csv
- Spec 078 Lanes A+B must ship first (false-catalyst gate)
- Post-13F cohort window closed (~2026-05-15)
- ≥30 resolved catalyst outcomes post-PIT (~2026-06-15 at current rate)

### Main overfitting risk:
- **False-catalyst contamination:** 18.8% of CT.gov-derived catalysts are false at universe level. `catalyst_decay_w` trained on false catalysts will learn a noisy timing signal. Spec 078 must ship first.
- **Double-counting with selector:** if `catalyst_decay_w` is already the primary driver of selector scores, adding it to the ranker amplifies the same dimension again (different from coinvest double-count — this is a harder case because timing varies more continuously within the cohort).
- **Decay_half_life hyperparameter:** Spec 080 suggests testing 60d/90d/120d. Any one of those optimized in-sample is an overfitting vector. Must fix and test, not search.

### Production role:
Future ranker candidate (3rd feature, Spec 080). Requires Checklist v2.

### Reasons not to test yet:
Spec 078 false-catalyst gate not in production. Post-13F window not closed. n(resolved outcomes) ≈ 7 (need ≥30). Architecture frozen. Spec 080 pre-conditions all unmet.

---

## Alternative 4 — Catalyst-quality ranker (catalyst_score / binary_quality / event family / source confidence)

### What mispricing does it exploit?
Not all catalysts are equal: a regulatory approval decision (PDUFA) has different resolution probability and stock-impact distribution than a Phase 2 data readout, which differs from a Phase 3 completion, which differs from a "CORPORATE_UPDATE" event. The market may not fully distinguish event quality within nominal catalyst buckets. A ranker that assigns higher scores to higher-quality event families (REG > CLINICAL data readout > SAFETY/OTHER) exploits this within-cohort quality variation.

Secondary mispricing: source reliability. If CT.gov-derived catalysts are 18.8% false at the universe level, a catalyst-quality score that reliably identifies high-confidence events would rank higher the names where the catalyst is real — generating alpha purely from data quality arbitrage.

### Why should it make money?
- Phase A catalyst audit (2026-05-04): `catalyst_score` shows conditional ρ = +0.19 within top-coinvest tertile, range [+0.09, +0.26], **17/17 snapshots positive**. This is more stable than clinical's +0.07–0.08. This is the strongest existing within-cohort descriptive correlation among tested candidates.
- `CORPORATE_UPDATE` events have 0/6 hit rate in the resolved outcome set — even with n=8, this is the only directional signal in the catalyst quality audit and points toward downweighting low-quality event families.
- Investment logic: higher-quality catalysts generate larger price moves on resolution (REG approval/rejection is more binary than Phase 2 interim readout), so ranking higher on event quality captures more of the binary distribution.

### What would falsify it?
- After false-catalyst hygiene, `catalyst_score` IC within the selected cohort drops to ≤ 0.
- `CORPORATE_UPDATE` 0/6 pattern does not replicate (n grows to ≥30 with mixed results).
- Catalyst quality is already captured by `selector_catalyst_block` (Phase A audit found the selector_catalyst_block carries 0.25 weight that already encodes most catalyst quality). Residual IC of `catalyst_score` after controlling for selector score is ≤ 0.

**Structural concern:** The Phase A verdict explicitly notes it is "hard to disentangle from selector_catalyst_block which already encodes most of it." This is the key falsification risk — if selector already saturates on catalyst quality, ranker reuse is double-counting.

### Data required:
- `catalyst_score` in production (confirmed in rankings.csv)
- `binary_quality_score`, `event_family` (REG/CLIN/SAFETY) — confirmed computed
- Spec 078 Lanes A+B (false-catalyst hygiene) — required
- `calendar_confidence` — D9 test showed IC = +0.014, t = +0.34 (FAIL) → not the right feature for this alternative
- `cat_priority` (source priority) — available

### Main overfitting risk:
- **Post-hoc family assignment:** event families (REG/CLIN/SAFETY) are partially derived from source classification. If CT.gov classification itself has 18.8% error, any feature downstream of that classification inherits the noise.
- **Small n per family:** REGULATORY events are sparse (PDUFA concentration). Training a ranker weight on event family with sparse REG count is fragile.
- **Confounding with calendar:** near-term PDUFA events also tend to have higher coinvest quality — if the ranker sees both catalyst quality and timing together, the catalyst quality weight may be capturing timing noise.

### Production role:
Ranker shadow candidate — same gate as timing (Spec 080/081 ablation battery, requires Checklist v2). Single candidate feature: `catalyst_score` per Phase A verdict.

### Reasons not to test yet:
Spec 078 not shipped. Post-13F window open. n(resolved outcomes) ≈ 7. False-catalyst contamination is directly load-bearing for this alternative. Architecture frozen.

---

## Alternative 5 — Financial-stress/upside ranker (preserve or refine negative financial_score)

### What mispricing does it exploit?
Within the coinvest-selected cohort (high institutional conviction), names with stressed balance sheets (high burn rate, low runway, pre-revenue) face a binary choice: catalyst HIT → stock re-rates significantly, catalyst MISS → dilution or halt. The market may discount stressed names relative to their expected-value because retail investors avoid bankruptcy risk. Specialist institutional investors who have done the diligence (coinvest) accept that discount — and the ranker captures the remaining discount by downweighting the "safe" names (high financial_score) relative to the "stressed-upside" names.

This is the *existing* financial_score rationale — the question is whether it should be refined, preserved as-is, or deprecated.

### Current evidence:
- Production deployed: `financial_score` weight = -0.0533. Verified in `production_data/ranker_v2_model.json`.
- The negative weight means: higher `financial_score` → lower ranker score. **Directionality interpretation note (unresolved):** `financial_score` is the rank-norm of Module 5 output. Whether high Module 5 score = "safe/profitable" (to be penalized in stressed-upside thesis) or "financially healthy in a survival sense" must be verified against `docs/MODEL_DOCUMENTATION.md` before claiming the sign is correct. This is an open design question per Spec 081 §5 item 1.
- Forward-return test (8 snapshots): financial_score contributes to production score but the test cannot decompose its individual marginal contribution.

### Why should it make money?
If `financial_score` correctly penalizes financially-safe (profitable, high-revenue, capital-efficient) names within the biotech cohort, it directs capital toward the pre-revenue, high-burn names where institutional conviction (coinvest) has established that the binary catalyst is real. These names' expected values are underpriced relative to P(HIT) because the market applies an additional distress discount.

**Risk of direction error:** If Module 5's `financial_score` actually measures *financial health* positively (high score = healthy balance sheet = good for survival = should rank higher), then the -0.0533 weight is counterproductive. This must be verified empirically, not inferred from the field name.

### What would falsify it?
- After verifying Module 5 directionality: `financial_score` sign is actually wrong — high Module 5 score = distressed, not safe.
- Within the selected cohort, higher `financial_score` predicts better forward returns (contradicts stress-upside thesis).
- Ablation B1 (financial_score only) underperforms B0 (baseline with coinvest cap) — financial_score adds noise without the coinvest anchor.

### Data required:
- Module 5 rank-norm construction documentation — `docs/MODEL_DOCUMENTATION.md` directionality verification (Spec 081 §5 item 1)
- Existing production feature (no new data needed)

### Main overfitting risk:
Module 5 is a composite of multiple financial metrics. The rank-norm transformation compresses outliers but may also compress regime sensitivity (e.g., 2022 biotech bear vs 2024 recovery). If the -0.0533 weight was fit in a period where financial stress correlated with returns but that relationship reversed (e.g., macro rate-sensitivity change), the sign could be wrong in forward data.

### Production role:
Currently active in production. Preserve pending directionality verification. If verified correct: keep as-is, consider refining normalization. If verified wrong: this is an urgent production fix (not an alpha question — a correctness question), flagged for T8 reviewer.

### Reasons not to change:
Architecture frozen. Directionality verification is a prerequisite for any decision. If the sign is wrong it is a production correctness issue, not a research-only question.

---

## Alternative 6 — Event-EV ranker (event_ev_p_hit × expected_return)

### What mispricing does it exploit?
Expected value of a binary catalyst event: P(HIT) × move_on_HIT + P(MISS) × move_on_MISS. If the market prices the stock at implied EV < true EV (per our internal Bayesian model), the name is undervalued and should rank higher. This is the cleanest investment-logic formulation: rank names by their EV gap, not by institutional consensus or financial structure.

### Why should it make money?
- If `event_ev_p_hit` calibrated correctly predicts biotech catalyst HIT probability better than market-implied probability, ranking by EV gap captures pure expectation mispricing.
- The mechanism is well-understood: market consensus is risk-averse and underbets clinical success in Phase 2/3; specialist models with FDA precedent, endpoint history, and biomarker data can outperform consensus P(HIT).
- The EV formulation is theoretically superior to the current ranker because it integrates both probability and magnitude.

### Current evidence — BLOCKED:
- `event_ev_p_hit` is the correct field (Bayesian posterior per-event P(HIT) from `event_ev/outcome_model.py`).
- Post-PIT HIT/MISS bound records: n = 7 (as of 2026-05-06 post-Spec 077 scope).
- Calibration threshold: ≥30 post-PIT HIT/MISS with bound `event_ev_p_hit` — earliest ~2026-07-01.
- `prediction_composite_score` was confirmed as the WRONG field for EV calibration (it is a screener/stock-quality composite, near-degenerate, 12 distinct values, 79% in 4 buckets, Brier WORSE than baseline).
- Spec 077 scoped 2026-05-06: forward-only binding via node_id exact / (ticker, date ±7d) fallback. Backfill not safe (30% match rate).

### What would falsify it?
- Brier score of `event_ev_p_hit` vs realized HIT/MISS outcomes is ≥ 0.25 (base rate predictor) after calibration sample matures.
- EV gap (model_p_hit − market_implied_probability) does not predict forward returns after controlling for coinvest and financial_score.
- `event_ev_p_hit` is highly correlated with `coinvest_score_z` — would represent double-counting.

### Data required:
- Spec 077 (event_ev_p_hit binder) must ship and accumulate ≥30 bound records (~2026-07-01)
- Polymarket or options-implied P(HIT) as the market comparator (currently sparse — see Alternative 7)
- `expected_move_on_hit` / `expected_move_on_miss` from expression layer (partially available via OVF framework)

### Main overfitting risk:
With n=7 current, any ICor calibration metric on `event_ev_p_hit` is anecdotal. The Bayesian model's priors (FDA precedent, endpoint type, prior PoS) may be fit to a historical period that does not generalize. Promotion requires full Checklist v2 including LOSO and year-stability — not achievable until late 2026 at earliest.

### Production role:
Future ranker candidate — earliest eligible horizon ~Q4 2026. Potentially highest thesis-coherence of all alternatives if calibrated. Currently: EV diagnostics only, shadow monitoring only.

### Reasons not to test yet:
n=7 bound records. Spec 077 not yet shipped (forward-binding only). Backfill not safe. Calibration requires ≥30 records. Architecture frozen. This is a 2026-Q4 horizon question at earliest.

---

## Alternative 7 — Expectation-gap ranker (options-implied move vs internal model, Polymarket yes-probability)

### What mispricing does it exploit?
The expectation-gap thesis: where the market's implied probability of a binary outcome (from options pricing, prediction markets, or analyst consensus) diverges from the internal model's P(HIT), the stock is mispriced by the size of the gap. A ranker that orders names by gap magnitude should outperform a ranker that orders by absolute P(HIT).

This directly addresses the problem Alternative 6 leaves open: without knowing market-implied P(HIT), raw P(HIT) is not a gap signal, just a quality signal.

### Why should it make money?
- If the internal model has genuinely superior signal (biomarker data, FDA precedent, endpoint strength), then systematic divergence from market-implied probability represents a recurring extractable edge.
- Prediction markets (Polymarket) may be better-calibrated than options-implied for rare binary events, but if they differ from the internal model, the gap is exploitable.

### Evidence — EES v3 CLOSED, Polymarket ANECDOTAL:
**EES v3 is structurally invalid and this lane is closed for the current formulation.** Three convergent residualization tests (linear, bin/decile, full non-parametric) show zero IC after controlling for `priced_move_pct`. The root cause: `conditional_misprice_score` (0.70 weight in EES v3) has Spearman -0.978 with `priced_move_pct` — it is a monotonic transform of the market's own implied move, not an independent expectation-error signal. The general rule: **you cannot extract expectation error from expectation alone.** Future revisits require external inputs: IV-vs-realized history, cross-sectional dispersion, microstructure flow. None of those are available now.

**Polymarket verdict (2026-05-05): ANECDOTAL_SHADOW / NO VERDICT.** n=1 small/mid biotech with recoverable price history (AXSM). Below 25-event minimum. Re-test threshold: <25 = anecdote, 25-50 = shadow, >50 = eligible for formal test. **Collector kept at `tools/poll_polymarket_biotech.py` for prospective capture only — no cron scheduled.**

The expectation-gap signal also requires `model_p_hit` in rankings.csv (currently null, pending EV outcome-binder from Spec 077). Without that, the gap cannot be computed even prospectively.

### What would falsify it?
- Options-based expectation gap (IV-vs-realized, cross-sectional dispersion) shows zero IC after full non-parametric residualization with ≥50 matched events.
- Polymarket gap (model − pm_yes_prob) shows zero IC after n ≥ 50 matched events.
- Gap signal is dominated by liquidity noise or market-maker model risk.

### Data required:
- IV-vs-realized history: no historical store exists — would need to be built from scratch
- Cross-sectional dispersion: available in principle from the options overlay, but patchy coverage (29% liquid as of 2026-05-05)
- Polymarket matched events: currently n=1 small/mid biotech with history; collector running prospectively
- `model_p_hit` in rankings.csv: blocked on Spec 077

### Main overfitting risk:
Any gap signal derived from the same `priced_move_pct` that EES v3 collapsed into is permanently closed. New gap signals must be constructed from sources independent of implied move. The EES failure is the canonical overfitting example for this family of alternatives — the gap looked real before residualization and disappeared entirely after.

### Production role:
SHADOW ONLY until independent external source is available. Polymarket path: prospective capture only, ≥50 events minimum before shadow research. IV-vs-realized path: 1-3 day data engineering task (per Polymarket memory), low priority given other gates.

### Reasons not to test yet:
EES formulation closed. Polymarket n=1. `model_p_hit` not bound. Architecture frozen. This is the most structurally difficult alternative — worth flagging for long-horizon tracking, not near-term research.

---

## Alternative 8 — Risk-adjusted ranker (liquidity, dilution risk, false-catalyst risk, stale-source risk, execution stress)

### What mispricing does it exploit?
Not an alpha signal — a risk-control layer. The thesis: within the coinvest-selected cohort, some names have substantially higher execution risk (liquidity constraints, dilution probability, stale-data-driven false signals). A ranker that adjusts down these risky names produces a portfolio that is equally alpha-seeking but has lower realized variance and drawdown — net-of-cost performance improves.

### Why should it make money?
Risk-control signals do not generate expected alpha by themselves but reduce expected loss relative to a naive ranker. If downside risk from high-dilution names is asymmetric (MISS → -60%; HIT → +30%), downweighting those names in favor of less asymmetric names with similar coinvest quality improves the Sharpe even without improving mean return.

**Key structural point:** per memory `feedback_runway_severity_architecture.md`, severity/runway are designed as cross-layer control variables, not alpha sources. They are already in the eligibility layer (`severity` gate, `runway_bucket` minimum). Adding them to the ranker explicitly would make them do double duty as both a gate (binary eligibility) and a gradient (continuous ranker adjustment) — which is architecturally sound IF the eligibility layer is too coarse.

### What would falsify it?
- Within the passed cohort, `severity`, `runway_bucket`, and related risk indicators have IC ≤ 0 vs forward returns (no remaining gradient after eligibility filtering).
- Adding risk controls to the ranker increases turnover without improving risk-adjusted returns.
- Risk controls are already captured via the eligibility gate — the passed cohort has homogeneous risk profiles.

### Data required:
- `severity` (already in production)
- `runway_bucket` (already in production)
- Dilution probability: partially captured via financial_score / runway; no dedicated field confirmed
- False-catalyst rate per-name: not currently a production field (would require Spec 078 output per name, not just universe-level rate)
- Execution stress: `de_vol_60d`, `de_beta_xbi_60d` — available in rankings.csv

### Main overfitting risk:
Risk controls are easy to over-tune: the universe is small (~300 names, ~30 in portfolio), and any risk factor that happened to correlate with poor outcomes in the training window will look good in-sample. The test is whether the risk-adjusted ranker reduces *prospective* drawdown, not whether it retroactively explains poor names.

### Production role:
Risk-control overlay, not primary ranker. Possible implementation path: extend the eligibility gate rather than adding to the ranker (less invasive). Would require explicit review of `severity` gate logic vs current gate.

### Reasons not to test yet:
Architecture frozen. The eligibility gate already carries severity/runway. Any ranker change requires Checklist v2. Suggest auditing whether the existing eligibility gate is already sufficient before proposing ranker-level risk adjustment.

---

## Alternative 9 — Hybrid two-stage ranker (imminence/quality first; financial stress adjustment within high-confidence names)

### What mispricing does it exploit?
A structured interaction of Alternatives 3 and 5: first sort by event imminence (timing) or event quality within the coinvest cohort, then apply financial-stress adjustment as a secondary rank within names at comparable timing/quality tiers. The thesis: within names with equal near-term catalysts, the stressed-upside names have higher expected returns because the stress discount remains even after the timing signal has already concentrated capital on near-term events.

### Why should it make money?
The individual investment logics for timing (Alternative 3) and stress-upside (Alternative 5) are complementary, not collinear. A PDUFA-in-30-days with stressed balance sheet should rank above a PDUFA-in-30-days with profitable balance sheet (stress-upside effect) AND above a PDUFA-in-90-days with stressed balance sheet (timing effect). A two-stage ranker operationalizes both effects without conflating them into a single linear score.

**Warning:** This alternative is HIGH RISK of being the same failure mode as EES v3. EES v3 was constructed as a multi-component formula with interaction logic that appeared principled but collapsed to a monotonic transform of implied move. A "two-stage interaction" ranker that is fit on historical pairs will find whatever interactions existed in that period — including spurious ones.

### What would falsify it?
- The interaction term (timing × financial_stress) has IC ≤ 0 within the selected cohort after controlling for each component individually.
- The two-stage ranker does not outperform either Alternative 3 or Alternative 5 alone.
- Turnover from the interaction layer is high without proportional return improvement.

### Data required:
- Pre-requisites for Alternatives 3 (timing) and 5 (financial_score directionality) must both be satisfied first.
- Both single-feature ablations (B1 and B2 from Spec 081) must run before a joint interaction is tested.
- Order: first test A3 and A5 independently; if both show IC > 0, test the interaction.

### Main overfitting risk:
Interactions are the most fragile component of a small-sample ranker. With ≤50 post-PIT resolved pairs, an interaction term has 1 degree of freedom for every ~20 observations — deeply underpowered. Do not fit interaction terms until single-feature ablations have cleared evidence thresholds.

### Production role:
Future research candidate only — meaningful horizon is 2026-Q4 or later, after Alternatives 3 and 5 are individually validated.

### Reasons not to test yet:
Pre-requisites for both components unmet. Interaction testing requires all single-feature ablations first. Architecture frozen. Sample too small for interaction modeling.

---

## Alternative 10 — "No ranker" comparator (selector-only or deterministic ordering)

### What mispricing does it exploit?
This is a null hypothesis alternative, not an alpha-seeking design. The selector-only ordering asks: does the pairwise ranker add any value at all, or does the top-30 by selector score alone perform equivalently? If the ranker adds noise without adding signal, the simplest correct design is to remove it.

### Why this matters:
- The forward-return test (8 snapshots, 2026-05-01) found: rescued-vs-suppressed differential = +0.10pp ≈ 0. Production deviations from coinvest-only did not earn alpha in that window. This is not yet conclusive (n=8, cohort-quarantine active) but it is the only forward evidence available.
- A selector-only portfolio (top-30 by coinvest_score_z or selector_score) is the natural baseline. If the ranker's marginal contribution is unproven, the burden of proof lies with the ranker, not with the selector-only design.

### Variants:
1. **Top-30 by selector_score**: pure selector ordering, no ranker
2. **Top-30 by coinvest_score_z**: direct coinvest quality sort
3. **Deterministic ranking**: alphabetical or last-alphabetical (negative control)
4. **Random within selector-passed cohort**: establishes floor IC

### What would falsify the null (i.e., prove the ranker is needed)?
- At the 2026-05-22 re-run (≥30 resolved snapshots): rescued-vs-suppressed differential is persistently > +0.50pp with sign-test ≥ 7/10 — crosses the meaningful threshold.
- Within-cohort IC of the ranker score (excluding selector_score influence) is NW-corrected t ≥ 1.96.

### Data required:
Already in production. No new fields. This ablation requires only the forward-return panel and a counterfactual ranker-off run.

### Main risk:
- If the null is confirmed (ranker adds no value), removing the ranker is a production change that requires operator sign-off, not a research conclusion. The ranker may provide value in stabilizing the top-30 roster even if its point-in-time IC is near zero.
- The selector-only comparator may outperform in the current window due to cohort-distortion from the 2026-04-25 manager change (which directly affects coinvest_score_z). Wait for quarantine to clear.

### Production role:
This is the mandatory baseline comparator for all ablation tests. Every alternative must be compared against the selector-only ordering, not just the 2-feature ranker. Spec 081 includes this as variant B0-implied baseline.

### Reasons not to conclude from current evidence:
n=8 snapshots, SE = ~0.5pp on median. Post-13F quarantine active. The +0.31pp production edge over coinvest-eligible is within 1 SE of zero. Re-run at 2026-05-22 is the correct gate.

---

## Summary table

| # | Alternative | Investment thesis | Main falsification | Data gate | Earliest test | Role |
|---|---|---|---|---|---|---|
| 1 | Baseline (coinvest + financial) | Quality selection + stress-upside penalty | Rescued-vs-suppressed ≤ 0 at ≥30 snaps | Already in production | Baseline: always active | Production |
| 2 | Orthogonal ranker | Second independent predictor after coinvest filtering | B3 IC ≤ B0 in Spec 081 | Post-13F + n≥30 + Spec 078 | ~2026-06-30 | Future candidate |
| 3 | Catalyst timing | Time-discounted option value | Timing IC ≤ 0 after Spec 078 hygiene | Spec 078 + post-13F + n≥30 | ~2026-06-30 | Future candidate |
| 4 | Catalyst quality | Event-family quality arbitrage | `catalyst_score` residual IC ≤ 0 after selector control | Spec 078 + n≥30 | ~2026-06-30 | Shadow candidate |
| 5 | Financial-stress/upside | Stress discount within coinvest cohort | `financial_score` sign wrong (production correctness risk) | Module 5 directionality verification | Immediate audit item | Active (verify sign) |
| 6 | Event-EV ranker | EV gap between internal P(HIT) and price | Brier ≥ 0.25 at calibration maturity | Spec 077 + n≥30 HIT/MISS | ~2026-Q4 | Future candidate |
| 7 | Expectation gap | Model vs market P(HIT) divergence | Zero IC after residualization (EES v3 closed) | EES formulation closed; Polymarket n=1 | 2026+ (prospective only) | Shadow-only / diagnostic |
| 8 | Risk-adjusted | Reduce downside without sacrificing alpha | No IC gradient within passed cohort | Existing eligibility audit first | Eligibility audit next | Risk-control overlay |
| 9 | Hybrid two-stage | Timing × financial stress interaction | Interaction IC ≤ component IC | Requires alternatives 3 + 5 validated first | 2026-Q4+ | Future research only |
| 10 | No-ranker comparator | Ranker adds no value (null) | Rescued-vs-suppressed > +0.50pp at n≥30 | 2026-05-22 re-run | 2026-05-22 | Mandatory baseline |

---

## Investment logic confidence assessment

| Alternative | Logic confidence | Evidence confidence | Combined |
|---|---|---|---|
| 1 (baseline) | HIGH | LOW-MEDIUM (n=8 inconclusive) | MEDIUM |
| 2 (orthogonal) | MEDIUM | LOW (D8/D9 preliminary, n=7) | LOW-MEDIUM |
| 3 (timing) | HIGH | BLOCKED (false-cat contamination) | BLOCKED |
| 4 (catalyst quality) | MEDIUM-HIGH | SHADOW (conditional ρ=+0.19 descriptive) | SHADOW |
| 5 (financial stress) | MEDIUM | UNVERIFIED (sign unconfirmed) | REQUIRES AUDIT |
| 6 (event EV) | VERY HIGH | BLOCKED (n=7) | BLOCKED |
| 7 (expectation gap) | HIGH (theory) | CLOSED (EES); ANECDOTAL (PM) | NO-GO current formulation |
| 8 (risk-adjusted) | HIGH | NOT TESTED in ranker role | RISK-CONTROL ONLY |
| 9 (hybrid two-stage) | MEDIUM | NONE | RESEARCH ONLY |
| 10 (no ranker) | N/A (null) | 4/8 sign-test, +0.10pp diff | OBSERVE |

---

## Handoff summary (T2 → T4, T5, T6, T7)

**Alternatives documented:** All 10 as specified in Task #2.

**Investment logic confidence:**
- Alternatives 1, 3, 6, 8 have high thesis coherence; 3 and 6 are blocked by data.
- Alternative 5 has an unresolved correctness question (financial_score sign direction) that is load-bearing for the current production ranker — this is the highest-urgency finding and should be routed to T8 for human review.
- Alternative 7 (expectation gap) is closed for current EES formulation per `ees_v3_structural_failure_2026_04_30.md`. Only prospective paths remain.
- Alternative 4 (catalyst quality) has the strongest existing within-cohort descriptive correlation (`catalyst_score` ρ=+0.19, 17/17 snapshots positive) — but is gated on false-catalyst hygiene first.

**Blockers for T4 (quant risk analysis):**
- Alternative 5: `financial_score` directionality must be verified before risk assessment is meaningful.
- Alternatives 3 and 6: data gates (Spec 078 + Spec 077) define the risk assessment timeline.
- Alternative 7: risk assessment is straightforward — EES v3 is the canonical overfitting postmortem for this family.

**Blockers for T5 (ablation protocol):**
- Spec 081 B0–B5 ablation battery design is already drafted (Spec 081 §4). T5 should adopt it.
- Spec 080 defines evaluation protocol for timing alternatives — T5 should adopt its §5 metric definitions.
- Alternative 10 (no-ranker comparator) must be included as a mandatory baseline in every ablation run.

**Items flagged for T8 (human gate):**
1. **Alternative 5 sign direction** — if `financial_score` directionality is wrong, this is a production correctness issue requiring immediate operator attention, not a research question.
2. **Architecture frozen scope** — all alternatives except baseline require operator sign-off to proceed beyond shadow research.
3. **Alternative 7 (expectation gap) EES formulation** — confirm "closed" is the standing policy for all pmv-derived expectation-error variants.

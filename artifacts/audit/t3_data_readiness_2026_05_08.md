# T3 — Data Readiness and PIT Validity (2026-05-08)

**Prepared by:** T3 [researcher] | **Date:** 2026-05-08 | **Scope:** Read-only audit. No code changes. No backtests. No IC computations.

---

## Summary counts

| Metric | Value |
|---|---|
| Post-PIT-valid snapshots | 17 clean production snapshots (2026-04-17 to 2026-05-08) |
| Total canonical snapshot dirs | 163 (all dates, no variants) |
| Post-PIT resolved catalysts (HIT/MISS only) | 12 total — HIT: 7, MISS: 5 |
| Bound event_ev_p_hit records | 0 non-null (field exists; all null) |
| Latest snapshot catalyst_quality coverage | 261/299 (87.3%) — binary_alpha=87, registry_only=174, blank=38 |
| Options liquid coverage | 87/299 (29.1%) — matches last audit 2026-05-05 |
| Polymarket tracked events | 25 in alpha_event_study; 20/25 have zero price history; 1 SMID biotech usable |
| XBI benchmark data available | YES — `data/snapshots/_forward_returns_panel.csv` (xbi_return_5d, excess_return_5d, 5,949 rows through 2026-05-08) |

---

## Readiness matrix

| # | Alternative | Data available | PIT-safe? | Post-13F-safe? | Blockers | Min sample threshold | Earliest test date | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | Current baseline (coinvest_score_z + financial_score) | YES — both in all 299 rows | YES | YES | 17 snapshots insufficient for Checklist v2 | ≥50 post-PIT snapshots for Checklist v2 | ~2026-07-31 | SHADOW_RESEARCH_ONLY |
| 2 | Orthogonal ranker (non-coinvest features; Spec 081) | PARTIAL — design only, no candidate features identified | UNCERTAIN | UNCERTAIN | Spec 081 architecture-only; no testable candidate signals; Checklist v2 required | ≥30 matched forward returns per candidate | Not determinable | BLOCKED — design not resolved |
| 3 | Catalyst-timing ranker (catalyst_decay_w; Spec 080) | YES — catalyst_decay_w=299/299 | YES | YES | n=12 post-PIT HIT/MISS vs ≥30 threshold; Spec 071 Lane 2 must ship first; post-13F window required | ≥30 post-PIT HIT/MISS post-13F | ~2026-07-15 | BLOCKED — sample insufficient (12/30) |
| 4 | Catalyst-quality ranker (catalyst_quality, catalyst_score) | YES — catalyst_quality=261/299; catalyst_score=299/299 | YES | YES | Same ≥30 outcome threshold as #3; Spec 079 calibration gate not met | ≥30 post-PIT resolved with catalyst_quality pre-event | ~2026-07-15 | BLOCKED — sample insufficient |
| 5 | Financial-stress/upside ranker (financial_score primary) | YES — financial_score=299/299; runway_severity_score=299/299 | YES | YES | Sign-direction unverified (Spec 074); 90d rolling window needs ~50 snapshots; Checklist v2 required | Checklist v2 battery | ~2026-07-31 | SHADOW_RESEARCH_ONLY |
| 6 | Event-EV ranker (event_ev_p_hit; Spec 077/079) | MATURING — binder shipped (forward-only); 0 non-null bound records; prospective sample accumulation pending | YES (forward-only) | YES | Binder operational but prospective EV artifact coverage has not yet reached post-PIT resolved events; 0/30 bound records accumulated | ≥30 post-PIT HIT/MISS with non-null event_ev_p_hit | ~2026-07-01 (estimated) | BLOCKED — 0/30 bound records (sample accumulation) |
| 7 | Expectation-gap ranker (conditional_misprice_score, EES v3) | PRESENT but invalid | NO | N/A | EES v3 closed 2026-04-30: pmv-derived (Spearman -0.978), IC≈0 after pmv control; do not revive | Requires non-pmv external inputs not available | Not determinable | BLOCKED — formulation closed; do not revive |
| 8 | Risk-adjusted ranker (short_interest, vol, runway) | PARTIAL — short_interest_pct=294/299; vol_classification=251/299; runway_severity_score=299/299 | UNCERTAIN for short interest | YES | Risk management is NOT alpha per standing policy; Checklist v2 required; no prior evidence | Checklist v2; standing policy blocks | Not determinable | BLOCKED — policy prohibition; no evidence basis |
| 9 | Hybrid two-stage ranker (Spec 072 vNext) | PARTIAL — coinvest_score_z=299/299; catalyst_quality=261/299; clinical_design_quality=225/299 | YES | POST_13F_ONLY — prereq: cohort-window close ~2026-05-15 | Spec 072 diagnostic-only (D1–D9); non-negotiable orthogonality constraint; 13F refresh pending | ~30 post-13F snapshots minimum | ~2026-07-01 | BLOCKED — 13F refresh pending |
| 10 | No-ranker comparator (selector-only ordering) | YES — selector_score computable from existing rankings | YES | YES | Needs isolation from selector changes; descriptive only at n=17 | 17 snapshots (AVAILABLE NOW) for descriptive; ~50 for Checklist v2 | NOW (descriptive); ~2026-07-31 (Checklist v2) | SHADOW_RESEARCH_ONLY — testable now descriptively |

---

## Detail: post-PIT snapshots

Total canonical production snapshot dirs: 163 (2024-10-18 to 2026-05-08).
Pre-PIT-audit (contaminated): 146. Post-PIT-valid clean: 17.

First clean snapshot: **2026-04-17**.

Post-PIT clean dates: 2026-04-17, 2026-04-20, 2026-04-21, 2026-04-22, 2026-04-23, 2026-04-24, 2026-04-25, 2026-04-27, 2026-04-28, 2026-04-29, 2026-04-30, 2026-05-01, 2026-05-04, 2026-05-05, 2026-05-06, 2026-05-07, 2026-05-08.

Excluded variant directories (not counted): `2026-04-22__stale_pit_cache`, `2026-04-22__stale_trials`, `2026-04-28.morning_backup_1730`, `2026-04-28__pre_20260428T214751Z`.

Active ruleset: v1.14.0, id `8887576e`.

---

## Detail: resolved catalyst outcomes

Total postmortem files: 158 across 36 date directories (2026-03-02 to 2026-05-01).

All-dates breakdown: HIT=26, MISS=20, NEEDS_REVIEW=25, DELAYED=21, null/unresolved=66.

**Post-PIT HIT/MISS (catalyst_date ≥ 2026-04-17, price data confirmed):**

| Ticker | Date | Outcome |
|---|---|---|
| BIIB | 2026-04-17 | HIT |
| CATX | 2026-04-20 | MISS |
| EPRX | 2026-04-21 | MISS |
| NTLA | 2026-04-27 | HIT |
| RVMD | 2026-04-30 | HIT |
| ARVN | 2026-04-30 | HIT |
| CNTA | 2026-04-30 | HIT |
| DNLI | 2026-04-30 | HIT |
| BCRX | 2026-05-01 | HIT |
| AMLX | 2026-05-07 | MISS |
| MNKD | 2026-05-06 | MISS |
| MRNA | 2026-05-06 | MISS |

Post-PIT HIT/MISS total: **12** (HIT=7, MISS=5). Future-dated excluded: ARGX_2026-05-15, UTHR_2026-05-31 (no price data, resolution_date is future).

Note: BCRX postmortem shows CT_PRIMARY_COMPLETION catalyst source but outcome resolved via PDUFA approval — possible false-catalyst instance that registered as HIT by coincidence. Flagged for T4.

Postmortem pipeline broken April 3 – May 2 (detection fix 2026-05-02); 80 backfilled records cover pre-PIT dates only.

---

## Detail: event_ev_p_hit bound records

Bound non-null event_ev_p_hit records: **0**.

Spec 077 shipped the `_bind_event_ev_p_hit` binder (2026-05-06, forward-only). Field exists in all 17 post-PIT resolution files as of the check date. All values are null.

**Binder is operational.** The binder ran correctly on 37 resolution records and recorded null where no matching EV artifact was found — this is correct behavior, not a binder failure. The binding logic uses: (1) exact node_id match; (2) (ticker, expected_date ±7d) fallback if unambiguous. Historical backfill was intentionally not performed because the join failure rate (~70% on pre-PIT records) made backfilled values unsafe. No backfill was done and none should be done without exact node_id evidence.

**Root cause of 0 non-null:** EV artifact coverage for the specific events that resolved 2026-04-27 to 2026-05-01 is not present in `artifacts/event_ev/`. For a non-null binding, an EV artifact must exist with (a) matching node_id or (b) unambiguous (ticker, expected_date ±7d) match. The prospective EV artifact pipeline has not yet produced artifacts covering those resolved events.

**The blocker is prospective sample accumulation / EV artifact coverage — not a missing join fix.** As new events resolve and the event_ev pipeline produces artifacts for those events, forward-only bindings will populate. The 70% historical join failure rate is historical context for why backfill is unsafe; it is NOT the current production blocker.

ev_validation_ledger.jsonl: 581 matched records total (HIT=504, MISS=77), spanning 2020–2026. None are bound in postmortem resolution records with event_ev_p_hit (these are pre-binder records; backfill not applied per policy).

**Gap to ≥30 threshold: 30/30 records missing.** Estimated arrival ~2026-07-01 per Spec 079 (requires prospective EV artifact coverage to reach 30 new post-PIT resolved events at ~3–4 HIT/MISS per month). Monthly binder health check per Spec 096.

---

## Detail: catalyst quality coverage

Column `catalyst_quality` in rankings.csv 2026-05-08:
- `binary_alpha`: 87 tickers (clean hard catalysts — most reliable)
- `registry_only`: 174 tickers (may contain false positives from unimplemented Lane 2 patterns)
- blank: 38 tickers
- Coverage: 261/299 = **87.3%**

Spec 071 Lane 1 SHIPPED (commit `c08b6062`). Zero suppressions on 2026-05-06. Spec 078 Lanes A+B SHIPPED (commit `02f10a76`). Zero current victims.

Spec 071 Lane 2 NOT implemented (OLE/PK-subtrial/observational classifier; requires Checklist v2). Remaining false-positive rate in `registry_only` is [UNCERTAIN] — between 0% and ~15%.

---

## Detail: 13F quarantine

`inst_delta_z` weight = 0.00 in selector since 2026-05-04. `inst_delta_regime` = "transition" for all 299 rows in latest snapshot — manager registry expanded 2026-04-25 (+4 managers); prior/current institutional summaries use different manager sets.

**Quarantine lifts:** Q1 2026 13F refresh expected ~2026-05-15. First clean post-13F snapshot: ~2026-05-20 (one-cycle contamination rule applies to the refresh snapshot itself).

`coinvest_score_z` is computed from institutional_summary.json (static, not delta) — unaffected by 13F quarantine.

---

## Detail: options coverage

| Gate | Count | Rate |
|---|---|---|
| opt_liquidity_ok=1 (liquid) | 87/299 | 29.1% |
| Full tier (all gates) | 74/299 | 24.7% |
| opt_has_data=0 (absent) | 11/299 | 3.7% |
| priced_move_pct non-null | 251/299 | 84.0% |

Most tickers fail OI gate. MIN_OI gate is an unpatched open item from options audit 2026-05-05. Options as alpha: Spec 053 closed. Options overlay (Spec 059) shadow-only.

---

## Detail: Polymarket

25 total events in alpha_event_study_2026-05-05.json. 20/25 have history_pts=0 (no usable price data). 5 events have price history; only AXSM (252 pts) is SMID biotech. 12 prospective records in shadow_2026-05-04.jsonl; model_p_hit=null for all 12.

**Verdict: ANECDOTAL_ONLY.** Effective usable sample for SMID biotech: 1 event (AXSM). Below the 25-event shadow threshold.

---

## Detail: clinical

| Field | Coverage |
|---|---|
| clinical_quality | 299/299 populated; 225/299 (75.3%) non-zero |
| clinical_design_quality | 225/299 populated |
| clinical_quality_score | 0/299 — exists in header but writes no values |

Current verdict: Selector NO_GO; Ranker SHADOW only on `clinical_design_quality`; EV non-evaluable until event_ev_p_hit binder operational.

---

## Detail: XBI/IBB benchmark

**YES — available.**

- `data/indices_prices.csv`: XBI+SPY daily 2023-12-22 to 2026-01-15 (518 rows; stale for recent comparisons)
- `data/snapshots/_forward_returns_panel.csv`: per-ticker rows with `xbi_return_5d` and `excess_return_5d`, 2026-04-14 to 2026-05-08 (5,949 rows, active post-PIT benchmark)
- Postmortem files embed `excess_vs_xbi_t1/t3/t5` at resolution time

---

## Detail: false-catalyst hygiene

Spec 071 Lane 1 SHIPPED 2026-05-06 (`c08b6062`): WITHDRAWN/APPROVED_FOR_MARKETING CTGOV statuses hard-rejected. Zero suppressions on 2026-05-06 validation diff.

Spec 078 Lanes A+B SHIPPED 2026-05-06 (`02f10a76`): CORPORATE_UPDATE veto + calendar_confidence gate. Zero current victims. `catalyst_quality` field now distinguishes binary_alpha from registry_only.

No explicit `is_false_catalyst` column in rankings.csv. `binary_alpha` (87 tickers) is the clean hard-catalyst gate. `registry_only` (174) may contain false positives at [UNCERTAIN] rate.

---

## Key blockers summary

1. **Post-PIT sample too small for Checklist v2** — 17 snapshots, 12 HIT/MISS events. All promotion-grade testing requires Checklist v2 (FM + bootstrap + FDR + LOSO + year stability). Earliest meaningful formal testing: ~2026-07-01.

2. **event_ev_p_hit prospective sample not yet accumulated** — binder shipped and operational (Spec 077, forward-only). 0 non-null values because EV artifact coverage has not yet reached post-PIT resolved events. The calibration clock (Spec 079) has not started. Blocker is prospective accumulation, not binder infrastructure. Monthly monitoring via Spec 096.

3. **13F quarantine through ~2026-05-15** — inst_delta_regime='transition' for all 299 rows. Quarantine clears ~2026-05-20 (one-cycle buffer after refresh). Blocks Spec 072 vNext and any inst_delta-dependent alternative.

4. **EES v3 / expectation-gap formulation permanently closed** — conditional_misprice_score is pmv-derived; IC≈0 after pmv control. Requires non-pmv external inputs (IV-vs-realized, dispersion, microstructure) not available.

5. **Polymarket anecdotal coverage** — 25 events, 20/25 with no price history, 1 SMID biotech usable. Cannot extract model-vs-market alpha signal; remains below 25-event shadow threshold for biotech-relevant events.

---

## Files inspected

- `data/snapshots/` (directory listing, 163 canonical dirs)
- `artifacts/postmortem/` (36 date dirs, 158 JSON files via grep)
- `artifacts/postmortem/2026-03-02/QURE.json`
- `artifacts/postmortem/2026-05-01/ADCT.json`
- `artifacts/postmortem/2026-05-01/BCRX.json`
- `artifacts/event_ev/ev_validation_summary.json`
- `artifacts/event_ev/ev_promotion_readiness.json`
- `artifacts/event_ev/ev_shadow_memo.jsonl`
- `artifacts/event_ev/ev_validation_ledger.jsonl`
- `data/snapshots/2026-05-08/rankings.csv` (header + column analysis)
- `data/snapshots/2026-05-08/options_quality_manifest.json`
- `data/snapshots/resolutions/2026-04/` and `2026-05/` (all resolution files via grep)
- `data/snapshots/resolutions/2026-04/BIIB_2026-04-17.json`
- `data/snapshots/resolutions/2026-05/UTHR_2026-05-31.json`
- `data/snapshots/resolutions/2026-05/ARGX_2026-05-15.json`
- `data/snapshots/_forward_returns_panel.csv`
- `data/indices_prices.csv`
- `data/polymarket/alpha_event_study_2026-05-05.json`
- `data/polymarket/shadow_2026-05-04.jsonl`
- `production_data/ranker_v2_model.json`
- `artifacts/audit/spec_071_lane1_diff_2026-05-06.md`
- `artifacts/audit/spec_078_laneAB_diff_2026-05-06.md`
- `specs/changes/spec_071_catalyst_quality_gate.md`
- `specs/changes/spec_074_financial_score_logic_doc_2026_05_05.md`
- `specs/changes/spec_075_inst_delta_checkpoint_2026_05_06.md`
- `specs/changes/spec_077_event_p_hit_binder_2026_05_06.md`
- `specs/changes/spec_078_catalyst_false_catalyst_gate_2026_05_06.md`
- `specs/changes/spec_079_event_p_hit_calibration_review_2026_05_06.md`
- `specs/changes/spec_080_catalyst_timing_ranker_ablation_2026_05_06.md`
- `specs/changes/spec_081_ranker_orthogonality_design_2026_05_06.md`
- `run_screen.py` (lines 5112–5128, inst_delta_regime logic)
- `13F_COHORT_QUARANTINE_PREP_2026_05_01.md`

---

## Handoff summary

The post-PIT evidence base (17 snapshots, 12 resolved HIT/MISS, 0 bound event_ev_p_hit records) is too thin for Checklist v2 on any ranker alternative. Two immediately actionable items: (1) the Spec 077 binder is wired but not writing non-null event_ev_p_hit values — the event-EV calibration clock has not started and fixing the join failure rate is the single highest-leverage unblock; (2) the 13F refresh (~2026-05-15) must land before any inst_delta-dependent alternative can be tested. For T4 and T5: `catalyst_quality` (261/299) and `catalyst_decay_w` (299/299) are the two cleanest candidate features for a future ablation, but neither can enter formal testing until post-PIT+post-13F HIT/MISS reaches 30 (~2026-07-15). The no-ranker comparator (alternative 10) is the only alternative testable today in descriptive mode.

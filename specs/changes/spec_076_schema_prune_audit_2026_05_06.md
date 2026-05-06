# Spec 076 — Schema Prune Audit (2026-05-06)

**Status:** Audit complete. One field removed. Five false positives corrected. Morningstar mapping fixed.
**Snapshot audited:** 2026-05-06 (299 rows, 408 fields)
**Scope:** Every field in `rankings.csv` classified by producer status and actual coverage.

---

## Post-audit corrections (2026-05-06)

After implementation, pre-removal grep revealed that the original "safe-to-cut" list was **wrong for 5 of 6 fields**. See the corrected classification table and warning below.

### What was actually done

| Action | Field | Commit |
|---|---|---|
| Bug fix | Morningstar key mapping restored (`"enhancement_result"` → `"enhancements"`) | `e70ae626` |
| Removed | `catalyst_source_filed_at` — confirmed no producer, no consumer, no contract | `ff4b7c64` |

### What was NOT done (and must not be done without a new audit)

The following five fields were listed in the original safe-to-cut table below. They are **not safe to cut**:

| Field | Why NOT safe | Evidence |
|---|---|---|
| `execution_momentum` | Live producer in `run_screen.py:4418`; referenced in rollback ranker spec (`ranker_v2_pairwise.py:70`) and selector template (`selector_engine.py:126`) | Grep confirms write + reads |
| `slippage_penalty_score` | Active EES data contract field (`event_ev/data_contracts.py:453`); live producer in `event_ev/expectation_error_model.py:274,494,566` | Grep confirms EES writes to it |
| `missing_components` | 30+ consumers across tests, scripts, `run_phase2_snapshot_delta.py`, `data_integrity_audit.py`, `common/robustness.py` | Grep confirms broad read footprint |
| `source_reliability_action` | Consumed by `compute_timing_hazard.py:1266` and `event_quality_shadow_sizer.py:238` | Grep confirms live reads |
| `source_reliability_penalty` | Consumed by `event_quality_shadow_sizer.py` | Grep confirms live read |

> **WARNING — coverage is not sufficient evidence for removal.**
> 0% nonzero coverage is not sufficient evidence that a field is safe to cut.
> A field must have **no producer, no consumer, and no active or future contract role** before being classified as safe-to-cut.
> The correct pre-removal check is a full repo grep across all `.py` files — not a coverage scan of a single snapshot.

---

## Key findings

1. **`clinical_design_quality` is LIVE** — prior audit claim of "zero-fill / never populated" is FALSE.
   Coverage is 76.9% (230/299), or 99.6% within the CLINICAL family (231 rows). The 68
   non-CLINICAL rows (regulatory, timeline, other catalysts) are intentionally empty by design.
   Do not touch or deprecate this field.

2. **Morningstar `ms_*` × 6 fields were DEAD due to a code bug — now FIXED.**
   `run_screen.py:6013` was reading `results.get("enhancement_result", {})` but the dict is
   stored under `"enhancements"` (line 10802). Fixed in commit `e70ae626`. The `ms_*` fields
   are **not safe to cut** unless there is explicit evidence that the Morningstar enrichment
   pipeline has been permanently retired.

3. **OVF base fields × 8 are conditionally dead** — require artifact
   `artifacts/options_verdict/{date}_verdict.json`, which is not being produced. The `ovf11_*`
   family (12 fields, live via Options Monitor v1.1) is separate and unaffected.

4. **Tilt "applied" flags are LIVE binary signals**, not dead. Coverage of "1" is 0% for three
   of them only because no tilts fired on 2026-05-06 — the fields are 100% populated as "0".
   Reporting as 0% nonzero was a measurement artifact of the nonzero-counting method.

---

## Full classification table

Fields grouped by classification. Within each group, sorted by coverage %.

### LIVE — active, expected coverage

| Field | Coverage | Producer | Notes |
|---|---|---|---|
| (114 fields at 100%) | 100% | Various | All core scoring, ranking, decision engine fields |
| `clinical_design_quality` | 76.9% | `common/event_quality_features.py:249` | CLINICAL family only (99.6% within CLINICAL rows) — **prior audit false positive** |
| `clinical_quality_composite` | 76.9% | `common/event_quality_features.py` | Same gate as above |
| `clinical_days_precision` | 76.9% | `common/event_quality_features.py` | Same gate |
| `clinical_date_confidence` | 76.9% | `common/event_quality_features.py` | Same gate |
| `clinical_program_depth` | 76.9% | `common/event_quality_features.py` | Same gate |
| `ranker_v2_score` | 20.1% | `ranker_v2_pairwise.py` | Eligible tickers only (60/299) |
| `ranker_v2_rank` | 20.1% | `ranker_v2_pairwise.py` | Same gate |
| `ranker_active` | 20.1% | `run_screen.py` | Same gate |
| `regulatory_quality_score` | ~15–30% | `module_5_scoring_v3.py` | Regulatory family only |
| `single_asset_risk` | 2.0% | `event_quality_features.py:343` | 6 true single-program companies |
| `fundamental_red_flag` | 2.7% | `decision_engine.py:714` | 8 red-flag detections — correct |
| `fundamental_red_flag_reasons` | 2.7% | `decision_engine.py:714` | Paired with above |
| `has_adcom` | 0.3% | Lookup: `data/adcom_votes.json` | 1 ticker with ADCOM record |
| `adcom_vote_score` | 0.3% | Same | Sparse by design |
| `adcom_vote_signal` | 0.3% | Same | Sparse by design |
| `adcom_vote_recency_days` | 0.3% | Same | Sparse by design |
| `adcom_vote_basis` | 0.3% | Same | Sparse by design |

### LIVE (binary flags, all rows populated as "0" or "1")

These fields show 0% "nonzero" only because the value "0" is excluded by the nonzero counter.
Every row has a value. Do not classify these as dead.

| Field | "1" coverage | Meaning |
|---|---|---|
| `catalyst_tilt_applied` | 79.9% (239/299) | Catalyst tilt multiplier was != 1.0 |
| `cost_haircut_applied` | 0% | No cost haircuts applied on 2026-05-06 |
| `dd_rel_margin_rescued` | 0% | No drawdown rescues on 2026-05-06 |
| `catalyst_type_tilt_applied` | 0% | No catalyst-type tilt applied on 2026-05-06 |
| `mom_state_tilt_applied` | 0% | No momentum-state tilt applied on 2026-05-06 |

### ACTIVE_OR_CONTRACTED — 0% snapshot coverage but live producer or consumer

These fields were incorrectly listed as "safe-to-cut" in the original audit. Pre-removal grep
confirmed each has an active producer, consumer, or data contract. Do not remove without a
separate, complete audit.

| Field | Coverage | Why KEEP | Key evidence |
|---|---|---|---|
| `execution_momentum` | 0% | Live producer; referenced in rollback ranker spec and selector template | `run_screen.py:4418`, `ranker_v2_pairwise.py:70`, `selector_engine.py:126` |
| `slippage_penalty_score` | 0% | EES data contract field; live producer | `event_ev/data_contracts.py:453`, `event_ev/expectation_error_model.py:274,494,566` |
| `missing_components` | 0% | 30+ consumers across tests/scripts/core pipeline | `run_phase2_snapshot_delta.py`, `data_integrity_audit.py`, `common/robustness.py`, tests |
| `source_reliability_action` | 0% | Consumed by timing hazard and shadow sizer | `compute_timing_hazard.py:1266`, `event_quality_shadow_sizer.py:238` |
| `source_reliability_penalty` | 0% | Consumed by shadow sizer | `event_quality_shadow_sizer.py` |

### INACTIVE_BY_DESIGN — pairwise_minimal mode (ranker block fields)

These fields are written as empty strings in pairwise mode and would only populate if the
ranker reverts to block-score mode. They are schema placeholders for a non-current path.
Do not cut without a separate decision on ranker architecture.

| Field | Producer | Gate |
|---|---|---|
| `ranker_adjustment` | `run_screen.py:5375` | `if ranker_mode == "pairwise_minimal"` → empty |
| `ranker_options_block` | `run_screen.py:5377` | Same |
| `ranker_inst_block` | `run_screen.py:5388` | Same |
| `ranker_aact_block` | `run_screen.py:5390` | Same |

### INACTIVE_BY_DESIGN — feature not yet implemented

| Field | Coverage | Notes |
|---|---|---|
| `inst_flow_abs_positive` | 0% | Awaiting institutional flow decomposition feature |
| `inst_flow_abs_negative` | 0% | Same |
| `inst_relative_underperformance` | 0% | Same |
| `inst_relative_outperformance` | 0% | Same |

These four fields are referenced in spec planning but have no producer code that computes them.
Keep for now as placeholders; harmless. Do not cut without a separate decision.

### DEAD — broken or permanently inactive

| Field | Coverage | Root cause | Status |
|---|---|---|---|
| `ms_volatility_3yr` | 0% | ~~Code bug: wrong dict key~~ **FIXED** — `run_screen.py:6013`, commit `e70ae626` | KEEP pending pipeline status confirmation |
| `ms_volatility_5yr` | 0% | Same | Same |
| `ms_star_rating` | 0% | Same | Same |
| `ms_return_ytd` | 0% | Same | Same |
| `ms_return_annualized_3yr` | 0% | Same | Same |
| `ms_return_annualized_5yr` | 0% | Same | Same |
| `ovf_agreement_count` | 0% | No `artifacts/options_verdict/{date}_verdict.json` produced | DEFER — pending OVF pipeline decision |
| `ovf_severity_score` | 0% | Same | DEFER |
| `ovf_near_catalyst` | 0% | Same | DEFER |
| `ovf_has_event_premium` | 0% | Same | DEFER |
| `ovf_has_iv_ramp` | 0% | Same | DEFER |
| `ovf_has_quiet_before` | 0% | Same | DEFER |
| `ovf_surface_confirmed` | 0% | Same | DEFER |
| `ovf_composite` | 0% | Same | DEFER |
| `slippage_penalty_score` | 0% | ~~Gated behind disabled slippage calc~~ **RECLASSIFIED** — active EES data contract | KEEP / ACTIVE_OR_CONTRACTED |
| `execution_momentum` | 0% | ~~Superseded by momentum_score~~ **RECLASSIFIED** — live producer + rollback path | KEEP / ACTIVE_OR_CONTRACTED |

### LEGACY_COMPAT — structural placeholders, no harm

| Field | Coverage | Notes |
|---|---|---|
| `de_alpha_60d_missing_reason` | 0% | Placeholder string from `defensive_features`, sometimes empty |
| `de_beta_xbi_60d_missing_reason` | 0% | Same |
| `de_drawdown_missing_reason` | 0% | Same |
| `catalyst_source_filed_at` | — | **REMOVED** in commit `ff4b7c64` — no producer, no consumer, no contract |
| `missing_components` | 0% | **RECLASSIFIED** → ACTIVE_OR_CONTRACTED (30+ consumers) |
| `missingness_penalty` | 0% | Always 0.0 when no missing components |
| `source_reliability_action` | 0% | **RECLASSIFIED** → ACTIVE_OR_CONTRACTED (consumed by timing hazard + shadow sizer) |
| `source_reliability_penalty` | 0% | **RECLASSIFIED** → ACTIVE_OR_CONTRACTED (consumed by shadow sizer) |
| `adcom_vote_n` | 0% | Pilot feature with near-zero data availability |

---

## Final corrected status summary

| Field / Family | Corrected Status |
|---|---|
| `ms_*` × 6 | FIXED_MAPPING / KEEP — mapping bug fixed in `e70ae626`; do not cut until enrichment pipeline confirmed retired |
| `catalyst_source_filed_at` | REMOVED — confirmed dead in `ff4b7c64` |
| `execution_momentum` | KEEP / ACTIVE_OR_CONTRACTED — live producer + rollback path |
| `slippage_penalty_score` | KEEP / ACTIVE_OR_CONTRACTED — active EES data contract |
| `missing_components` | KEEP / ACTIVE_OR_CONTRACTED — 30+ consumers |
| `source_reliability_action` | KEEP / ACTIVE_OR_CONTRACTED — consumed by timing hazard + shadow sizer |
| `source_reliability_penalty` | KEEP / ACTIVE_OR_CONTRACTED — consumed by shadow sizer |
| `clinical_design_quality` | LIVE / DO_NOT_CUT — 76.9% overall, 99.6% within CLINICAL rows |
| `ovf_*` base × 8 | DEFER — pending explicit operator decision on options-verdict pipeline |
| `ovf11_*` × 12 | DO_NOT_CUT — live via Options Monitor v1.1 |
| `de_sort_contrib_*` | INACTIVE_BY_DESIGN / DO_NOT_CUT without separate architecture decision |
| Tilt flags × 5 | DO_NOT_CUT — live binary signals; 0% "nonzero" is a measurement artifact |
| Ranker block placeholders × 4 | DO_NOT_CUT without separate ranker architecture decision |
| `inst_flow_*` × 4 | DO_NOT_CUT — spec-planned future features |
| `adcom_*` × 5 | DO_NOT_CUT — sparse but live pilot data |

---

## Safe-to-cut candidates (corrected)

Only one field was confirmed safe for removal. The original list of six was wrong for five of them.

| Field | Reason | Status |
|---|---|---|
| `catalyst_source_filed_at` | No producer, no consumer, no contract. Archive artifact from prior tracking version. | **REMOVED** — commit `ff4b7c64` |
| ~~`execution_momentum`~~ | ~~Superseded by `momentum_score`~~ | **RETRACTED** — live producer + rollback path |
| ~~`slippage_penalty_score`~~ | ~~Feature disabled~~ | **RETRACTED** — active EES data contract |
| ~~`missing_components`~~ | ~~Always empty string~~ | **RETRACTED** — 30+ consumers |
| ~~`source_reliability_action`~~ | ~~Never populated~~ | **RETRACTED** — consumed by `compute_timing_hazard.py` + `event_quality_shadow_sizer.py` |
| ~~`source_reliability_penalty`~~ | ~~Never populated~~ | **RETRACTED** — consumed by `event_quality_shadow_sizer.py` |

**Decision-gate before cutting Morningstar fields:**
Mapping bug was fixed in `e70ae626`. Before any future removal, confirm the enrichment pipeline
is permanently retired. If enrichment is still active, the fix is the correct action. If
permanently retired, remove all 6 fields and the enrichment call at `run_screen.py:6012–6033`.

**Decision-gate before cutting OVF base fields:**
Determine whether the options-verdict pipeline (`options_verdict_features.py`) is intended to
produce artifacts in future. If yes, keep. If no, remove the 8 `ovf_*` base fields (distinct
from the live `ovf11_*` family).

---

## Do-not-cut fields

| Field | Reason |
|---|---|
| `clinical_design_quality` | LIVE — prior audit was wrong; 76.9% coverage, 99.6% within CLINICAL rows |
| All `ovf11_*` fields | LIVE via Options Monitor v1.1 — separate from the dead `ovf_*` base family |
| Tilt "applied" flags | LIVE binary signals — 0% "nonzero" is a measurement artifact |
| Ranker block fields (4) | Pairwise-mode placeholders — needed if ranker mode ever changes |
| `inst_flow_*` (4) | Spec-planned future features — premature to cut |
| `adcom_vote_*` (5) | Sparse but live pilot data |
| `single_asset_risk` | LIVE, rare by definition |
| `fundamental_red_flag*` | LIVE, rare by definition |
| `execution_momentum` | ACTIVE_OR_CONTRACTED — live producer + rollback path (was incorrectly listed as safe-to-cut) |
| `slippage_penalty_score` | ACTIVE_OR_CONTRACTED — EES data contract (was incorrectly listed as safe-to-cut) |
| `missing_components` | ACTIVE_OR_CONTRACTED — 30+ consumers (was incorrectly listed as safe-to-cut) |
| `source_reliability_action` | ACTIVE_OR_CONTRACTED — consumed by timing hazard + shadow sizer (was incorrectly listed) |
| `source_reliability_penalty` | ACTIVE_OR_CONTRACTED — consumed by shadow sizer (was incorrectly listed) |

---

## Prior audit false positives identified

| Claim | Status | Correction |
|---|---|---|
| "clinical_design_quality is zero-fill / never populated" | **FALSE** | 76.9% overall, 99.6% within CLINICAL family. Gating is intentional: `event_quality_features.py:364–371` returns empty for non-CLINICAL catalysts. |
| Clinical Phase A claimed ~79.6% | **SLIGHTLY HIGH** | Actual is 76.9% of total universe. If measured within CLINICAL-only rows: 99.6%. Discrepancy explained by denominator choice (total vs CLINICAL-only). |
| "execution_momentum safe to cut — superseded by momentum_score" | **FALSE** | Live producer in `run_screen.py:4418`; referenced in rollback spec and selector template. |
| "slippage_penalty_score safe to cut — feature disabled" | **FALSE** | Active EES data contract field; producer in `event_ev/expectation_error_model.py`. |
| "missing_components safe to cut — always empty string" | **FALSE** | 30+ consumers across tests, scripts, and core pipeline tools. |
| "source_reliability_action safe to cut — never populated" | **FALSE** | Consumed by `compute_timing_hazard.py:1266` and `event_quality_shadow_sizer.py:238`. |
| "source_reliability_penalty safe to cut — never populated" | **FALSE** | Consumed by `event_quality_shadow_sizer.py`. |

---

## Recommended next actions (revised)

1. **Morningstar mapping is fixed** (`e70ae626`). Verify on next production run that `ms_*`
   fields populate for tickers where Morningstar enrichment returns SUCCESS.

2. **Verify OVF pipeline status** — Is `artifacts/options_verdict/` intended to resume?
   If no, plan removal of 8 `ovf_*` base fields. No action until decision is explicit.

3. **No further safe-to-cut removals from this audit** — the only confirmed-dead field
   (`catalyst_source_filed_at`) has already been removed. The other candidates require
   new, complete audits (producer grep + consumer grep + contract check) before any
   removal is considered.

4. **No action on `clinical_design_quality`** — prior audit recommendation to cut was wrong.

5. **No action on tilt flags, ranker block fields, inst_flow_*, or adcom_*** — all correctly
   classified as LIVE or reserved.

---

## Counts summary

| Classification | Count |
|---|---|
| LIVE (active, normal coverage) | ~134 |
| LIVE (intentionally low coverage — family-gated, sparse, or rare) | 15 |
| LIVE (binary flags, 0% "nonzero" is measurement artifact) | 5 |
| ACTIVE_OR_CONTRACTED (0% coverage but live producer or consumer) | 5 |
| INACTIVE_BY_DESIGN (pairwise mode placeholders) | 4 |
| INACTIVE_BY_DESIGN (future feature, no producer yet) | 4 |
| DEAD/mapping-fixed (Morningstar — key bug fixed, keep pending pipeline decision) | 6 |
| DEAD/deferred (missing artifact — OVF base) | 8 |
| LEGACY_COMPAT (structural placeholders) | 7 |
| REMOVED (confirmed dead, no producer/consumer/contract) | 1 |
| **Total audited** | **~408** |

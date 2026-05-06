# Spec 076 — Schema Prune Audit (2026-05-06)

**Status:** Audit only. No schema changes, no field removals, no production code edits.
**Snapshot audited:** 2026-05-06 (299 rows, 408 fields)
**Scope:** Every field in `rankings.csv` classified by producer status and actual coverage.

---

## Key findings

1. **`clinical_design_quality` is LIVE** — prior audit claim of "zero-fill / never populated" is FALSE.
   Coverage is 76.9% (230/299), or 99.6% within the CLINICAL family (231 rows). The 68
   non-CLINICAL rows (regulatory, timeline, other catalysts) are intentionally empty by design.
   Do not touch or deprecate this field.

2. **Morningstar `ms_*` × 6 fields are DEAD due to a code bug**, not a data absence.
   `run_screen.py:6013` reads `results.get("enhancement_result", {})` but the dict is stored
   under `"enhancements"` (line 10802). Fix the key to restore these fields if Morningstar
   data is still desired. No action taken here.

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

### INACTIVE_BY_DESIGN — pairwise_minimal mode (ranker block fields)

These fields are written as empty strings in pairwise mode and would only populate if the
ranker reverts to block-score mode. They are schema placeholders for a non-current path.

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
Keep for now as placeholders; harmless.

### DEAD — broken or permanently inactive

| Field | Coverage | Root cause | Safe to cut? |
|---|---|---|---|
| `ms_volatility_3yr` | 0% | Code bug: `run_screen.py:6013` reads wrong dict key (`"enhancement_result"` vs `"enhancements"`) | Only after deciding whether to fix or drop Morningstar |
| `ms_volatility_5yr` | 0% | Same bug | Same |
| `ms_star_rating` | 0% | Same bug | Same |
| `ms_return_ytd` | 0% | Same bug | Same |
| `ms_return_annualized_3yr` | 0% | Same bug | Same |
| `ms_return_annualized_5yr` | 0% | Same bug | Same |
| `ovf_agreement_count` | 0% | No `artifacts/options_verdict/{date}_verdict.json` produced | Only after deciding OVF pipeline fate |
| `ovf_severity_score` | 0% | Same | Same |
| `ovf_near_catalyst` | 0% | Same | Same |
| `ovf_has_event_premium` | 0% | Same | Same |
| `ovf_has_iv_ramp` | 0% | Same | Same |
| `ovf_has_quiet_before` | 0% | Same | Same |
| `ovf_surface_confirmed` | 0% | Same | Same |
| `ovf_composite` | 0% | Same | Same |
| `execution_momentum` | 0% | Superseded by `momentum_score` (100%); no producer in run_screen.py | Yes |
| `slippage_penalty_score` | 0% | Gated behind disabled slippage calc in `defensive_overlay_adapter.py` | Yes |

**Note on Morningstar:** The bug fix is one line (`run_screen.py:6013`). Before removing these
fields, decide whether to fix the key lookup. If Morningstar data is still active, fix is
preferred over removal. If Morningstar data is no longer ingested, remove both the fields and
the `morningstar_signal_engine.py` enrichment call.

**Note on OVF:** The `ovf11_*` fields (12 fields, live via Options Monitor v1.1) are a separate
family and are LIVE. The 8 `ovf_*` base fields listed above require a different artifact
(`options_verdict/`) that is not currently being produced. Clarify whether the options-verdict
pipeline is intended to resume before cutting.

### LEGACY_COMPAT — structural placeholders, no harm

| Field | Coverage | Notes |
|---|---|---|
| `de_alpha_60d_missing_reason` | 0% | Placeholder string from `defensive_features`, sometimes empty |
| `de_beta_xbi_60d_missing_reason` | 0% | Same |
| `de_drawdown_missing_reason` | 0% | Same |
| `catalyst_source_filed_at` | 0% | Archived from prior catalyst tracking version, no longer updated |
| `missing_components` | 0% | Computed by `decision_engine.py:2655`; always empty string in practice |
| `missingness_penalty` | 0% | Always 0.0 when no missing components |
| `source_reliability_action` | 0% | Placeholder, never populated |
| `source_reliability_penalty` | 0% | Placeholder, never populated |
| `adcom_vote_n` | 0% | Pilot feature with near-zero data availability |

These fields have zero or near-zero coverage but are structurally benign. No urgency to cut.

---

## Safe-to-cut candidates

These are the only fields where removal has no production impact, no downstream risk, and no
planned revival:

| Field | Reason | Prerequisite before cutting |
|---|---|---|
| `execution_momentum` | Superseded by `momentum_score` (live, 100%); no producer | None — safe to remove immediately |
| `slippage_penalty_score` | Feature disabled; no plan to re-enable | Confirm with operator that slippage gate is permanently off |
| `catalyst_source_filed_at` | Archive artifact from prior tracking version; nothing writes to it | None |
| `missing_components` | Always empty string; structural artifact | None — removing it changes no behavior |
| `source_reliability_action` | Never populated; no producer | None |
| `source_reliability_penalty` | Never populated; no producer | None |

**Decision-gate before cutting Morningstar fields:**
Fix the dict key bug first. If Morningstar data is still ingested and the fix restores values,
keep the fields. If Morningstar data is no longer active, remove all 6 fields and the
enrichment call in `run_screen.py:6012–6033`.

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

---

## Prior audit false positives identified

| Claim | Status | Correction |
|---|---|---|
| "clinical_design_quality is zero-fill / never populated" | **FALSE** | 76.9% overall, 99.6% within CLINICAL family. Gating is intentional: `event_quality_features.py:364–371` returns empty for non-CLINICAL catalysts. |
| Clinical Phase A claimed ~79.6% | **SLIGHTLY HIGH** | Actual is 76.9% of total universe. If measured within CLINICAL-only rows: 99.6%. Discrepancy explained by denominator choice (total vs CLINICAL-only). |

---

## Recommended next actions (in priority order)

1. **Verify Morningstar data status** — Is the enrichment pipeline still active? If yes, fix
   `run_screen.py:6013` (one-line change). If no, plan removal of 6 fields + enrichment call.

2. **Verify OVF pipeline status** — Is `artifacts/options_verdict/` intended to resume?
   If no, plan removal of 8 `ovf_*` base fields.

3. **Cut the 6 safe fields** (`execution_momentum`, `slippage_penalty_score`,
   `catalyst_source_filed_at`, `missing_components`, `source_reliability_*`) only if operator
   confirms these paths are permanently closed.

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
| INACTIVE_BY_DESIGN (pairwise mode placeholders) | 4 |
| INACTIVE_BY_DESIGN (future feature, no producer yet) | 4 |
| DEAD (code bug — Morningstar) | 6 |
| DEAD (missing artifact — OVF base) | 8 |
| DEAD (superseded or disabled) | 2 |
| LEGACY_COMPAT (structural placeholders) | 9 |
| **Total audited** | **~408** |

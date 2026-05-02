# Spec 072 — Screener vNext: Manager-as-Gate, Traps-then-Catalyst-Rank (2026-05-01)

**Status:** Spec + initial diagnostic results captured 2026-05-01. **No production code changes from this document.** Diagnostic-only redesign with **frozen candidate set** awaiting 2026-05-22 verification.

**Constraints:**
- Alpha stack frozen per `policy_alpha_freeze_2026_04_04.md` — promotion requires Checklist v2 (FM + bootstrap + FDR + LOSO + year stability).
- Architecture frozen per `policy_freeze_architecture_2026_04_19.md` — current production unchanged. vNext runs as parallel diagnostic only.
- Coinvest as context layer per `policy_coinvest_context_layer_2026_04_25.md` — this spec operationalizes the "next ranker retrain" target.
- Runway severity stays as gate/sizing per validated `feedback_runway_severity_architecture.md` — never promote to ranking.

**Empirical motivation:**
- Audit on 2026-04-30 (`ranker_dominance_audit`) found block deltas: institutional **+0.20**, coinvest_score_z raw **+0.95**, inst_delta_z raw **+1.09**, catalyst block **+0.06**, market block **+0.01**, **clinical block 0.00**, survivability **-0.06**, financial_score **-20.2**.
- Production top-30 is institutional-following + risk-on, not catalyst/clinical alpha. 23/30 names use INST_BOOST mechanism. ρ(coinvest_score_z, final_score) = **+0.882** median.
- Spec 057 found **conditional clinical IC within top-coinvest = +0.103 (t=3.53)** — clinical signal exists but only conditional on coinvest. Empirical anchor for the manager-as-gate redesign.
- EES v3 closed 2026-04-30 (`ees_v3_structural_failure_2026_04_30.md`) — confirms expectation-error formulations cannot extract alpha when raw pmv is the input.

**Prerequisites status (2026-05-01):**
- ✅ **Spec 071 Lane 1 SHIPPED** (commit `e7e42b2f`, "fix(catalyst): hard-reject CT.gov catalyst credit for ineligible statuses"). False-catalyst contamination concern mitigated for D2/D3.
- 🔄 Cohort-change quarantine window per `regime_post_cohort_change_distortion_2026_04_28.md` — closes ~2026-05-15.
- 🔄 Spec 069 (Module 2 v2 schema restore) status TBD — affects 4/30 names today (IMCR/INSM/MIRM/STOK).

---

## 1. Principle (the rethink)

> **Use managers to validate science. Use traps to avoid obvious losers. Use catalyst/clinical quality to rank.**

| layer | purpose | mechanism |
|---|---|---|
| L1 — Universe | Liquid biotech eligibility | existing universe rules (unchanged) |
| **L2 — Manager Validation Gate** | "Are biotech specialists paying attention?" | **coinvest_score_z threshold gate**, NOT ranker input |
| **L3 — Trap Filter** | Remove obvious losers | hard exclusions for missing catalyst, weak runway, poor liquidity, stale thesis, dilution risk |
| **L4 — Catalyst + Clinical Ranker** | Rank surviving validated names | composite of FROZEN candidate set (§8) |
| L5 — Portfolio construction | Sizing, capacity, decay | existing infrastructure (unchanged) |

The decisive change vs. current: **coinvest is binary in vNext (gate), continuous in current (ranker)**.

---

## 2. Proposed data flow

```
Universe (297 tickers)
  │  rule: standard biotech filters (existing module_1_universe.py)
  ▼
L1 universe-eligible
  │  RULE: coinvest_score_z ≥ τ_coinvest (default 0.0; sensitivity tested {0.0, 0.25, 0.5})
  ▼
L2 manager-validated
  │  TRAPS (any one fails → exclude):
  │    a. has_catalyst_signal == "1" AND catalyst_days ≤ 180
  │    b. financing_truth_gate == "True"
  │    c. execution_bucket NOT IN {"blocked","micro_size_only"}
  │    d. coinvest_recency_state == "fresh"
  │    e. dilution_haircut < 0.40
  │    f. fundamental_red_flag != "1"
  ▼
L3 trap-survived  (~85 names/day at τ=0.0; ~48 at τ=0.5)
  │  RANK by FROZEN candidate set (§8)
  ▼
L4 ranked candidates (top-30 EW, existing sizing/capacity/decay)
```

---

## 3. Exact fields to reuse (no new producers)

### L2 gate
- `coinvest_score_z`, `coinvest_tag`, `coinvest_filing_age_days`, `coinvest_recency_state`

### L3 traps
- `has_catalyst_signal`, `catalyst_days`, `next_catalyst_date`, `is_hard_catalyst`, `catalyst_event_type`, `catalyst_family`
- `runway_buffer_months`, `runway_severity_score`, `financing_truth_gate`
- `dilution_haircut`, `dilution_risk_engine.py` outputs
- `execution_bucket`, `execution_capacity_score`, `dollar_volume`, `adv_60d`
- `fundamental_red_flag`, `coinvest_recency_state`

### L4 ranker — see frozen candidate set in §8

**No new fields. No new producers. No new caches.**

---

## 4. Exclusion rules (the trap layer, formalized)

| trap | rule | severity | source memo |
|---|---|---|---|
| missing/distant catalyst | `has_catalyst_signal != "1"` OR `catalyst_days > 180` | HARD | — |
| false catalyst | flagged by Spec 071 Lane 1 status hard-reject | HARD ✅ shipped | spec_071 (`e7e42b2f`) |
| weak runway | `financing_truth_gate != "True"` | HARD | feedback_runway_severity |
| poor liquidity | `execution_bucket ∈ {blocked, micro_size_only}` | HARD | — |
| stale thesis | `coinvest_recency_state != "fresh"` | HARD | — |
| severe dilution | `dilution_haircut >= 0.40` | HARD | feedback_runway_severity |
| governance flag | `fundamental_red_flag == "1"` | HARD | — |

---

## 5. Ranking inputs — admissibility rules

### Hard-banned (structurally redundant or proven anti-alpha)
- `coinvest_score_z` — already used as gate; double-counting.
- `inst_delta_z` — institutional-following theme already represented by gate.
- `financial_score` — anti-alpha per audit.
- `runway_severity_score` — gate/sizing only; never promote per `feedback_runway_severity_architecture`.
- `expectation_error_score` / `ees_v3_score` / `conditional_misprice_score` / `conditional_expected_move` — closed lane.
- `priced_move_pct` — implied move alone is not alpha.
- `base_rate_gap_score` — anti-predictive (negative control).

### Candidate inputs (require D7/D8/D9 pass before inclusion)
The unconditional rejection of clinical features (e.g., `clinical_score_v2_z` REJECTED Δ=-0.68pp) was on the **full population**. Within the gated universe (L3), these features may behave differently — exactly the conditional structure Spec 057 found.

All `clinical_*`, `catalyst_*`, `design_*`, `endpoint_*`, `readout_*`, `binary_quality_*`, `regulatory_quality`, `de_sort_contrib_event_ev`, `competitive_*`, `program_*`, `execution_momentum` — must pass D7 before any candidate ranker formula.

---

## 6. Orthogonality + diagnostic battery

All run **per-snapshot** (no cross-snapshot aggregates per `policy_freeze_architecture`). Reuses existing infrastructure:
- Filter module: `scripts/research/ees_validation_filters.py`
- Forward-return joiner: `scripts/research/ees_forward_returns.py`
- Validation table builder: `scripts/research/ees_validation_table.py`

### 🚨 Orthogonality constraint (non-negotiable)

The single most likely failure mode is **silent reintroduction of coinvest into the ranker** via downstream-correlated fields. Same failure mode that killed EES v3 (Spearman -0.978 with pmv).

**Three orthogonality tests (D7, D8, D9). ALL must pass before any candidate ranker advances.**

### D7 — Per-feature orthogonality vs coinvest within L3

For each candidate input `f`: `Spearman(f, coinvest_score_z)` per snapshot. Median + range across snapshots, plus τ-sensitivity at τ ∈ {0.0, 0.25, 0.5}.

**Tightened thresholds (2026-05-01 calibration based on n=85 sampling math)**:
- |median ρ| < 0.20 AND stable sign across τ → **PASS**
- 0.20 ≤ |median ρ| < 0.30 → **RESIDUALIZE** (must bin-residualize before D8)
- |median ρ| ≥ 0.30 OR sign flips across τ → **EXCLUDE**

**Prior threshold (0.30/0.50) was too permissive** — Spearman SE ≈ 0.11 at L3 sizes ~85 means |ρ|<0.30 is barely distinguishable from zero.

#### D7 execution results (2026-05-01)
- **26 candidates tested**, 16 snapshots (2026-04-15 → 2026-05-01)
- L3 sizes: τ=0.0 → median 86; τ=0.25 → median 64; τ=0.5 → median 48
- **τ-stability flips (5 features)**:
  - `clinical_quality_composite` PASS → RESIDUALIZE (sign flip +0.13 → -0.23)
  - `regulatory_quality` RESIDUALIZE → PASS
  - `program_diversification` RESIDUALIZE → **EXCLUDE**
  - `program_count` PASS → RESIDUALIZE
  - `competitive_intensity_z` RESIDUALIZE → **EXCLUDE**
- **Stable PASS at both τ=0.0 AND τ=0.5 (Tier 1 conservative)**: 11 features
- **3 NO-DATA** (constant within L3): `catalyst_strength`, `catalyst_type_mult`, `de_sort_contrib_event_ev` — features traps already consumed.

### D8 — Within-coinvest-quintile IC stability

Within L3, partition into coinvest quintiles (5 bins; deciles too small at n=85 per snapshot). For each candidate score:
- `Spearman(score, excess_return_5d)` *within each quintile*
- Mean within-quintile IC; sign consistency

**Pass**: mean within-quintile IC > +0.05 AND ≥4/5 quintiles same sign as mean AND no single quintile contributes >50% of IC mass.

### D9 — Bin-residualized IC vs coinvest (full L3 cohort)

Bin-residualize each candidate (subtract coinvest-quintile mean), then test:
- `Spearman(score_resid, excess_return_5d)`
- t-stat (NW lag-corrected per Spec 064 P1)

**Pass**: residualized IC > 0 AND raw t > +1.5 (preliminary) / NW-corrected t_adj ≥ +1.96 (promotion-grade).

#### D8/D9 execution results (2026-05-01)

Pool: 7 resolved snapshots × ~85 L3 names = **600 triples** (effective N ≈ 245 after autocorrelation).

**Tier 1 (PASS at both τ=0.0 AND τ=0.5)**:

| feature | D8 mean within-quint IC | D9 resid ρ | D9 raw t | verdict |
|---|---|---|---|---|
| `clinical_score` | +0.178 | +0.200 | +5.00 | ADVANCE |
| `clinical_score_v2` | +0.173 | +0.202 | +5.05 | ADVANCE |
| `clinical_score_v2_z` | +0.173 | +0.202 | +5.05 | ADVANCE |
| `clinical_score_z` | +0.161 | +0.174 | +4.25 | ADVANCE |
| `readout_density_90` | +0.128 | +0.128 | +3.16 | ADVANCE |
| `endpoint_strength_score` | +0.080 | +0.080 | +1.96 | ADVANCE (marginal) |
| `clinical_optionality_pct_dev` | -0.116 | -0.143 | -3.33 | D9-only |
| `clinical_rank_pct_dev` | +0.115 | +0.143 | +3.35 | D9-only |
| `execution_momentum` | +0.015 | +0.064 | +1.57 | D9-only |
| `binary_quality_score` | +0.032 | +0.023 | +0.56 | **FAIL** |
| `calendar_confidence` | -0.000 | +0.014 | +0.34 | **FAIL** |

Sign-flippers (caution): `clinical_alpha_z` (D9 t=+4.06), `design_quality_score` (+3.81), `readout_curve_score` (+3.77), `clinical_design_quality` (+2.24), `late_stage_readouts_180` (+2.22).

### Cross-feature deduplication (2026-05-01)

Pairwise Spearman within L3 across ADVANCE features identified 7 clusters at |ρ|≥0.70:

| cluster | members | underlying signal |
|---|---|---|
| 1 | clinical_score / v2 / v2_z / z + clinical_optionality / rank_pct_dev | "clinical-quality score" (one signal × 6 transforms) |
| 2 | clinical_alpha_z, clinical_design_quality | trial maturity / design |
| 3 | design_quality_score (singleton) | design quality |
| 4 | readout_curve_score, late_stage_readouts_180 | late-stage readout density |
| 5 | readout_density_90 (singleton) | recent readout density |
| 6 | endpoint_strength_score (singleton) | endpoint quality (truly orthogonal: ρ ≤ 0.31 with all) |
| 7 | execution_momentum (singleton) | failed D8 — drop |

**Cross-cluster correlations**: clusters 2/3/4/5 form a "trial-maturity" theme (internal corr 0.55–0.67) — they are NOT 4 independent signals. After dedup: **2 truly distinct signals + 1 weakly-distinct theme**.

### D1–D6 (vNext vs current production comparison)
Run after D7-D9 gate passes. Spec unchanged from prior draft:
- D1 Composition diff (Jaccard < 0.70)
- D2 Block-delta (catalyst δ ≥ +0.15, clinical non-zero)
- D3 Forward-return (vNext top-30 mean T+5 excess vs production)
- D4 Stability (day-over-day Jaccard within 10pp of production)
- D5 Trap pass-through audit
- D6 vNext self-dominance check (no single feature ρ > 0.85 with score)

### D7-D9 enforcement order
```
D7 (per-feature orthogonality)  ← DONE 2026-05-01
  ↓
Build candidate ranker on FROZEN SET (§8)
  ↓
D8 (within-quintile IC stability)  ← INITIAL DONE 2026-05-01
  ↓
D9 (bin-residualized IC)  ← INITIAL DONE; verification 2026-05-22
  ↓
ONLY THEN → D1–D6 (composition, forward-return, etc.)
  ↓
Checklist v2 (out of scope until verification + ≥30 days)
```

### Spec 064 P1 promotion thresholds (apply at 2026-05-22 verdict)
- `t_adj ≥ 1.65` at 21d horizon with NW lag `L = h−1`, `N_eff ≥ 30`
- block bootstrap 95% CI excludes zero
- sign agreement Test A vs Test C

---

## 7. Diagnostics to compare vNext vs current production (D1–D6)

Run after D7–D9 verification gate at 2026-05-22.

### D1 — Composition diff (per snapshot)
Jaccard(vNext top-30, production top-30) — pass if < 0.70 (else redesign is decorative).

### D2 — Block-delta confirmation
For vNext top-30, recompute audit block deltas — pass if catalyst δ ≥ +0.15 AND clinical signal becomes non-zero.

### D3 — Forward-return comparison (THE ALPHA QUESTION)
Mean T+5 excess: vNext top-30 vs production top-30 vs coinvest-only top-30 vs XBI baseline.

### D4 — Stability
Day-over-day Jaccard within 10pp of production.

### D5 — Trap pass-through audit
L1 → L2 → L3 attrition counts per snapshot.

### D6 — Self-dominance check
ρ(any single feature, score_vnext) should be < +0.85.

---

## 8. 🔒 FROZEN candidate set (post-D7/D8/D9 + dedup, locked 2026-05-01)

**No additions, removals, or substitutions until 2026-05-22 verification completes.**

| rank | feature | role | D7 ρ (τ=0.0/0.5) | D9 raw t | distinctness |
|---|---|---|---|---|---|
| **PRIMARY** | `clinical_score_v2_z` | headline signal — clinical-quality conditional alpha | -0.116 / -0.135 | **+5.05** | ρ ≤ 0.42 with all other reps |
| **BACKUP** | `endpoint_strength_score` | independent secondary | -0.119 / -0.134 | +1.96 (marginal) | ρ ≤ 0.31 with all — truly orthogonal |
| ~~set aside~~ | trial-maturity cluster (clinical_alpha_z, design_quality_score, readout_curve_score, readout_density_90) | NOT advanced — single theme, 4 labels (corr 0.55–0.67) | various | up to +4.06 | dropped to prevent composite-building |

### Hard freeze rules until 2026-05-22 verdict review

1. **No additional features** may be added to the candidate set, regardless of new ideas, audits, or findings. Per `[ees_v3_structural_failure_2026_04_30]`, premature feature combination is the failure mode that killed EES.
2. **No tuning** of weights, gate τ, or trap thresholds based on current data. The current configuration is the controlled-experiment baseline.
3. **No composite ranker construction.** Test PRIMARY alone first. The BACKUP exists only if PRIMARY fails verification, not as a co-feature.
4. **No production shadow ship.** Per `[policy_freeze_architecture]`, attribution-only.
5. **No widening of D7/D8/D9 thresholds** if features fail at verification. A real null is a real result (per §13 Q7).

### The candidate is FRAGILE, not a confirmed edge

Raw t=+5 in pooled L3 is **suspiciously strong** given:
- effective N ≈ 245 after autocorrelation
- 7 trading days of forward returns (vs. ≥30 required)
- partial overlap with cohort-quarantine window
- Spec 064 NW correction reduces raw t-stats by ~40% (so t_adj ≈ +3 at best)

**Most likely 2026-05-22 outcomes** (rough priors):
- still positive but smaller (t_adj ≈ 2–3): **HIGH probability**
- collapses to noise (t_adj < 1): **MEDIUM probability**
- stays at t_adj ≈ +5: **LOW probability**

The promotion path is gated behind the verification re-run, not behind today's t-stat.

---

## 9. 2026-05-22 verification protocol

Scheduled remote agent fires on **2026-05-22**. Tasks:

1. **Rebuild resolved L3 panel** with ≥30 trading days of T+5 forward returns.
2. **Compute on FROZEN candidate set only** (`clinical_score_v2_z` PRIMARY, `endpoint_strength_score` BACKUP):
   - Per-snapshot IC (not just pooled — required by `policy_freeze_architecture`)
   - NW-corrected t-stat (lag L=4, since horizon h=5)
   - Hit rate (sign agreement on T+5 excess return)
   - Decile spread (top vs bottom decile within L3)
   - Drawdown / worst-snapshot IC
3. **Re-run D7, D8, D9** with the larger panel:
   - D7 must hold orthogonality at τ=0.0 and τ=0.5
   - D8 mean within-quintile IC > +0.05, ≥4/5 same sign
   - D9 NW-corrected t_adj ≥ +1.96 for promotion-grade
4. **Validate three things hold**:
   - Signal direction unchanged (PRIMARY positive)
   - No collapse in IC magnitude (D9 t_adj ≥ +1.5 minimum)
   - No dependence on a single snapshot (>50% of mass)
5. **Output verdict to memory**:
   - **PASS** (all checks pass): supersede `screener_vnext_d8_d9_first_candidate_2026_05_01.md` with promotion-eligible memo. Begin §10 promotion path (shadow phase).
   - **FAIL** (any check fails): supersede with closure memo. Do NOT loosen thresholds.

### Out-of-bounds for the verification agent
- Do NOT add features
- Do NOT tune τ, traps, or thresholds
- Do NOT reweight PRIMARY vs BACKUP
- Do NOT run any production-affecting code paths
- Do NOT promote to selector/ranker/sizing

---

## 10. Promotion path (from 2026-05-22 verdict onward)

If verification PASSES:
1. **Shadow phase** — emit vNext top-30 alongside production top-30 in `data/snapshots/<date>/vnext_shadow.csv`. Still no production effect. Run for ≥30 additional days.
2. **Checklist v2 evaluation** — full FM + bootstrap + FDR + LOSO + year-stability per `policy_alpha_freeze_2026_04_04.md`.
3. **Promotion** — replace production ranker. Requires explicit user approval.

---

## 11. What this spec is NOT

- **Not a feature add.** Zero new fields, producers, or external data sources.
- **Not a code change to production.** Any harness work lives in `scripts/research/`. No edits to `run_screen.py`, `module_5_*`, or any production path.
- **Not a kill of current production.** Production stays live and unchanged.
- **Not promotion-grade evidence.** Today's D7/D8/D9 results are exploratory.
- **Not a re-formulation of expectation-error.** That lane stays closed per `ees_v3_structural_failure_2026_04_30`.
- **Not a ranker composite.** PRIMARY and BACKUP are alternatives, not co-features.

---

## 12. Why this design vs. alternatives

| alternative | why rejected |
|---|---|
| Strip coinvest entirely | Per `policy_coinvest_context_layer_2026_04_25.md`, do NOT strip without audited replacement. Spec 057's clinical IC fires *within top-coinvest*; removing the gate likely destroys the signal. |
| Add catalyst/clinical to existing ranker (linear) | Tested historically (clinical_score_v2_z REJECTED Δ=-0.68pp). Today's D9 result CONFIRMS this — same field works conditionally where it failed unconditionally. |
| Use ML model on top-coinvest cohort | Premature optimization. Test the simple weighted composite first; the linear vNext baseline is the null hypothesis any ML model must beat. |
| Combine multiple ADVANCE features into a composite | NO. After dedup we have 2 distinct signals + 1 set-aside theme. Combining before verification re-introduces the EES failure mode. PRIMARY first, alone. |

---

## 13. Open questions (revisit at 2026-05-22 verdict)

1. **τ_coinvest gate threshold** — currently 0.0. Tighter τ shrinks L3 (87→48) but may strengthen orthogonality. Re-evaluate based on verification.
2. **Hard catalyst window** — currently 180d. Tighter (90d) may improve precision; test in §9 verification.
3. **Survivability re-introduction** — current production anti-selects. vNext gate excludes weak survivability via `financing_truth_gate`. Test stratified.
4. **Sector crowding** — `oncology_crowding_z` FAILS τ=0.5 (excluded). Revisit if PRIMARY passes.
5. **Orthogonality threshold calibration** — |ρ|<0.20 was tightened from |ρ|<0.30 on 2026-05-01 based on n=85 SE. Spec 064 NW-correction may further inform.
6. **What if PRIMARY fails verification** — fall back to BACKUP `endpoint_strength_score`? Per §8 hard rules, run alone, not as composite. If both fail → publish "vNext architecture is structurally viable but no current feature carries sufficient post-orthogonality alpha at current N." Real result, not setback.
7. **What if ALL features fail orthogonality** — possible legitimate outcome: gated universe contains no available features both predictive AND orthogonal. Response: publish that finding, do NOT loosen thresholds. Re-engage when new orthogonal features available (e.g., realized-vs-implied-vol history per `ees_v3_structural_failure` rule).

---

## 14. Artifacts

- Filter module: `scripts/research/ees_validation_filters.py`
- Forward-return joiner: `scripts/research/ees_forward_returns.py`
- Validation table builder: `scripts/research/ees_validation_table.py`
- Forward-return panel: `data/snapshots/_forward_returns_panel.csv` (resolved through 04-23 as of 2026-05-01)
- Memory artifacts (in `~/.claude/.../memory/`):
  - `screener_vnext_d8_d9_first_candidate_2026_05_01.md` — first read (preliminary, expires 2026-05-22)
  - `spec_072_screener_vnext_2026_05_01.md` — design memo (this spec, mirrored)
  - `ees_v3_structural_failure_2026_04_30.md` — the failure mode this spec is designed to avoid
- D7/D8/D9 raw run outputs: live in conversation transcript 2026-05-01; future cleanup to persist as `data/snapshots/_d7_d8_d9_2026-05-01.csv`.

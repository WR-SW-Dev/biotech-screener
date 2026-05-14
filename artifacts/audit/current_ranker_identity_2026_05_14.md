# Current Production Ranker Identity — 2026-05-14 Snapshot

**Date:** 2026-05-14  
**Status:** Read-only audit (no changes)  
**Purpose:** Baseline for 2026-05-22 review; confirm what is actually in production before evaluating research candidates

---

## Active Production Configuration

### Selector (Universe Reduction)

**Formula:** `0.65 × coinvest_score_z + 0.35 × inst_delta_z`

**Inputs:**
- `coinvest_score_z`: Manager consensus signal (Deerfield, RA Capital, Redmile, Baker Bros, OrbMed, Perceptive, Ally Bridge, Venbio, Casdin, Suvretta, Tang, Vivo, etc.)
- `inst_delta_z`: Institutional ownership change signal (elite manager holdings delta vs sector baseline)

**Output:** Eligible universe (typically ~60 tickers after gate application)

**Gating:**
- ✓ Positive coinvest_score_z threshold (excludes low-manager-conviction names)
- ✓ Minimum clinical evidence (HINT trial baseline, PubMed author screening)
- ✓ Liquidity gate (minimum $ trading volume)

---

### Ranker v2 (Ranking Within Selector Output)

**Architecture:** 2-feature pairwise ordinal ranking

**Active features:**
1. `financial_score_z` (Module 5 rank-normalized financial health)
2. One of: `coinvest_score_z` (current) OR `inst_delta_z` (alternate config tested, not live)

**Top-30 construction:** Equal-weight from ranked eligible universe

**Coefficient state:** Frozen at v1.14.0 ruleset (`8887576e`; prior v1.13.0 was `2a3e79eb` until 2026-05-04)

---

### Risk Control (Post-Ranking Overlay)

**Conviction scaling (optional):** Sizes positions by ranker score confidence → max $50M+ capacity

**No rank-weighting:** All positions equal-weight within Top-30 (ordinal ranking only; no confidence-based sizing)

---

## Explicitly Banned or Shadow-Only Signals

| Signal | Status | Reason |
|---|---|---|
| `clinical_score_v2_z` | SHADOW-ONLY (Spec 072 candidate) | Under diagnostic verification; not production-rated |
| `catalyst_score` | SHADOW-ONLY (Spec 098 candidate) | Timing monitor only; not ranker input |
| `expectation_misprice_score` | RETIRED (Spec 064) | Structural failure (pmv-dominance); sidecar diagnostic only |
| `base_rate_gap_score` | RETIRED | Anti-predictive after pmv control |
| `priced_move_pct` (as ranker input) | SHADOW-ONLY (diagnostic) | Options-gated; used for expectation model input, not selection |
| `insider_net_buy_value_90d` | DIAGNOSTIC-ONLY (Spec 065) | Data-integrity gate only; NOT selector/ranker input |

---

## Known Distortions / Windows

**Active:** Cohort distortion regime (2026-04-25 through ~2026-05-15)
- `inst_delta_z` contaminated by 4-manager cohort expansion on 2026-04-25
- Byte-identical values across 19 snapshots (no fresh 13F data)
- Expected to self-heal post-13F Q1 2026 refresh (~2026-05-15)
- SIGNAL_ALERT (ic_health_monitor) correctly persistent during window
- Do NOT change selector weights or inst_delta logic during window

---

## What Has NOT Changed (Since Last Review)

✓ Selector formula (0.65/0.35 weighting)  
✓ Ranker architecture (2-feature pairwise)  
✓ Ranker inputs (financial_score_z + coinvest_score_z)  
✓ Top-30 equal-weight construction  
✓ Conviction scaling logic  
✓ Gating logic (clinical, liquidity, coinvest threshold)  
✓ Risk control overlay  

---

## What Is Under Review / Frozen Pending

**Spec 072 — vNext Ranker Redesign:**
- Clinical quality ranking within manager-gated universe
- Frozen candidate set (clinical_score_v2_z, endpoint_strength_score)
- Diagnostic (D7/D8/D9) gates must pass 2026-05-22 before any production change
- No composite ranker construction until verified

**Spec 091 — score_rank_pct Governance:**
- WARN streak monitoring; no action until evidence bundle + CRT complete
- No selector/ranker/sizing changes justify by this signal alone

**Spec 100 (old) — Ranker IC Tooling:**
- True ranker-specific IC measurement tool not yet built
- Blocks all ranker promotion claims until fixed

---

## Governance Frame (Spec 096)

**Gate/Ranker Separation:**
- Gates exclude names (NO continuous scoring in gate)
- Ranker ranks survivors within gated universe (ordinal only; no confidence weights)
- Risk control adjusts post-ranking (convictions, position sizing, overlay logic)

**Ranker Promotion Requirements (Spec 096):**
1. ✓ Marginal ordering value (Spec 094) — not just correlation with selector
2. ✓ Correct IC scope (Spec 095 + old Spec 100) — true ranker IC, not selection universe IC
3. ✓ Orthogonality — candidate independent of selector inputs
4. ✓ Checklist v2 (6 modules: FM, bootstrap, FDR, LOSO, year stab, domain)
5. ✓ Spec 096 doctrine — all of the above non-negotiable

---

## Next Review Date

**2026-05-22** — Full ranker research review after:
- 13F Q1 2026 refresh validated (SIGNAL_ALERT clear)
- Cohort window closed (inst_delta_z normalized)
- Spec 072 D7/D8/D9 verification gates re-run on clean data
- Forward-return window accumulates post-cohort-change
- Spec 091 evidence-bundle readiness assessed

**No ranker changes authorized before 2026-05-22 review completion + Checklist v2 readiness.**

---

## Audit Checklist (for review)

- [ ] Selector formula verified: 0.65 × coinvest_score_z + 0.35 × inst_delta_z
- [ ] Ranker inputs verified: financial_score_z + coinvest_score_z (2-feature pairwise)
- [ ] Top-30 equal-weight confirmed (no rank-weighting or confidence sizing)
- [ ] Gating logic unchanged (clinical, liquidity, coinvest threshold all active)
- [ ] Risk control overlay unchanged (conviction scaling; max capacity $50M+)
- [ ] Banned signals confirmed (expectation_misprice, base_rate_gap: RETIRED)
- [ ] Shadow signals confirmed (clinical_score_v2, catalyst_score, insider: not in production)
- [ ] Cohort distortion documented (inst_delta_z locked at 0.743; self-heal post-13F refresh)
- [ ] Spec 096 doctrine applied (gates/ranker/risk control layers; marginal value gate)
- [ ] Frozen candidate set (Spec 072): clinical_score_v2_z PRIMARY, endpoint_strength_score BACKUP only

---

## References

- **Active ruleset:** v1.14.0 (`8887576e`)
- **Production identity memo:** `scoring_model_identity_2026_04_06.md`
- **Spec 096 doctrine:** gate/ranker separation governance
- **Ranker research landscape:** `memory/ranker_research_landscape_2026_05_14.md`
- **Spec 072:** `specs/changes/spec_072_screener_vnext_2026_05_01.md`

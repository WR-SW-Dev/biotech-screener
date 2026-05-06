# Spec 086 — v1.14.0 / `8887576e` freeze-regime compliance audit (2026-05-06)

**Status:** SCOPED ONLY. Audit-only. **No rollback. No ruleset rotation. No scoring changes. No code edits.** Implementation of any remediation requires explicit user approval after the audit completes.

**Origin:** Spec 084 ruleset-ID reconciliation investigation surfaced an unanswered governance question: whether the 2026-05-04 v1.14.0 promotion (canonical hash `8887576e`) satisfied the freeze regime declared in `policy_alpha_freeze_2026_04_04.md`.

**Priority:** Higher governance significance than ID reconciliation, but lower implementation urgency than the reader bug (Spec 084 Step B).

**Classification:** **Governance / process audit, not a model change.** This ticket asks "did the right gate get applied?", not "should we keep v1.14.0?".

---

## Hard constraints

- Do NOT roll back `8887576e`.
- Do NOT rotate to a different ruleset.
- Do NOT modify `production_data/decision_rulesets/manifest.json`.
- Do NOT modify `production_data/ranker_v2_model.json`.
- Do NOT touch `common/ranker_active_contract.py`.
- Do NOT edit selector / ranker / EV / sizing code.
- Do NOT alter any cron schedule.
- Do NOT remove the v1.14.0 governance documents — they are evidence.
- The audit produces a written verdict and (if needed) a remediation note. Any remediation requires a separate approval cycle.

---

## 1. Problem statement

`policy_alpha_freeze_2026_04_04.md` declares:

> No promotions w/o Checklist v2 (FM + bootstrap + FDR + LOSO + year stab). Pairwise = ordinal only (ECE=0.19); no rank-weighting; ranker frozen at 2 features.

On 2026-05-04, ruleset rotated from `2a3e79eb` v1.13.0 → `8887576e` v1.14.0 (initially-computed phantom hash `622edb77`, corrected on 2026-05-05). The change zeroed `inst_delta_z` weight in the selector and re-weighted `coinvest_score_z` from 0.65 → 1.00. Documented in `INST_DELTA_Z_GOVERNANCE_LOG_2026_05_04.md` and `INST_DELTA_Z_SIGNAL_HEALTH_GOVERNANCE_REVIEW_2026_05_04.md`.

The governance docs cite:
- ic_health_monitor + calibration_evidence ALERT (two-frame signal-health evidence)
- Comparator probe: `coinvest_score_z` healthy over same window (mean_ic=+0.097, hit_rate=0.897, rho=-0.33 vs `inst_delta_z`)

**These are signal-health degradation evidence, not Checklist v2 (FM + bootstrap + FDR + LOSO + year stab).** Whether this satisfies the freeze gate is the question.

---

## 2. Investigation scope

### 2.1 Characterize the v1.14.0 change precisely

- Read `production_data/decision_rulesets/manifest.json` entry for `8887576e` — full diff vs v1.13.0 entry.
- Read the v1.14.0 ruleset file itself: `production_data/decision_rulesets/v1.14.0_coinvest_only_selector.json` (per `INST_DELTA_Z_GOVERNANCE_LOG_2026_05_04.md` "Changes applied" table).
- Confirm scope: selector weight change only? Or also any ranker / EV / sizing?

Manifest `notes` (already read): "Weight change within existing A4 selector+ranker architecture. No new pipeline code. inst_delta_z weight redistributed: coinvest_score_z 65%->100%, inst_delta_z 35%->0% in selector. Ranker unchanged. EW Top-30 unchanged. True PIT bundle backtest remains +2.34pp/mo, t=2.57. Actual computed hash: 8887576e (file was identical to v1.13.0 until selector_config fields added 2026-05-05)."

**Audit question:** is "weight change within existing architecture" a hygiene patch (defending the hold-discipline thesis when a signal degrades) or an alpha promotion (changing how the model selects names)? The freeze regime defines "promotion" as requiring Checklist v2. Hygiene patches that demote a degrading signal may sit in a different bucket — clarify which by:
- Reviewing `policy_alpha_freeze_2026_04_04.md` for explicit hygiene-patch carve-outs.
- Reviewing memory `feedback_pause_between_control_plane_changes.md` for guidance on signal-degradation responses.
- Reviewing prior ruleset rotations (e.g., `bebe73f8` 2026-03-09) for governance precedent.

### 2.2 Behavioral classification

For each of the following, classify the v1.14.0 change as: **alpha-promoting** / **hygiene** / **bugfix** / **governance**.

| Aspect | v1.14.0 change |
|---|---|
| Selector composition | inst_delta_z 35%→0%, coinvest 65%→100% — selector signal mix changed |
| Selector universe | unchanged (same threshold, same A4 architecture) |
| Ranker (2-feat pairwise) | unchanged |
| EV layer | unchanged |
| Sizing | unchanged (EW Top-30 unchanged) |
| Eligibility gates | unchanged |
| New pipeline code | none |

Surface-level it is a selector-weight rebalance triggered by signal degradation. But: changing the selector signal mix changes which names get selected — that **is** an alpha-affecting change in the strict sense, regardless of intent.

### 2.3 Was Checklist v2 actually performed?

Search for evidence of:
- FM (forecast metrics?) — grep `tools/`, `common/stats/`, `tests/` for `forecast_metric` or `FM_v2` or related.
- Bootstrap — grep for `bootstrap` against the v1.14.0 rotation timeframe (2026-05-04±).
- FDR (false discovery rate) — grep for `fdr` or `false_discovery`.
- LOSO (leave-one-snapshot-out) — grep for `loso` or `leave_one_snapshot`.
- Year stab (year-over-year stability) — grep for `year_stab`, `yearly_stability`.
- Checklist v2 itself — `common/stats/` per memory has 6 modules and 36 tests.

Look in:
- `artifacts/` for any 2026-05-04 ± artifacts named with these terms.
- `INST_DELTA_Z_*` documents for explicit Checklist v2 references.
- Git log between 2026-05-01 and 2026-05-05 for any commit mentioning Checklist v2 evidence.
- `agents/calibration/memory/` for promotion-recommender records.

### 2.4 Documented justification audit

Read in full:
- `INST_DELTA_Z_GOVERNANCE_LOG_2026_05_04.md`
- `INST_DELTA_Z_SIGNAL_HEALTH_GOVERNANCE_REVIEW_2026_05_04.md`
- `INST_DELTA_Z_GOVERNANCE_LOG_TEMPLATE_2026_05_04.md`
- `RULESET_CHANGELOG.md` (the v1.14.0 entry, if added)
- `CLAUDE.md` Active Ruleset section (history of edits)

For each, capture:
- What evidence was cited?
- Was Checklist v2 explicitly claimed?
- What conditions were stated for re-opening / reversal?

### 2.5 Precedent

Compare against the prior rotation `2a3e79eb` v1.13.0 (apparently active 2026-04-06 → 2026-05-04 per CLAUDE.md). If v1.13.0 satisfied Checklist v2 (or if it was promoted under a different regime — pre-freeze), use that as the reference. Same for `bebe73f8` v1.10.0 (March 2026, pre-freeze).

---

## 3. Deliverables (this ticket)

A single audit memo at `artifacts/audit/spec_086_v1_14_0_freeze_compliance_audit_2026_05_06.md` answering:

1. **What changed in the v1.14.0 ruleset rotation?** Precise diff + behavioral classification (alpha / hygiene / bugfix / governance).
2. **Was it selector / ranker / alpha behavior, hygiene/governance, or bugfix?** Single-word verdict + 2-line justification.
3. **Did docs claim Checklist v2 evidence?** Yes / No, with citations.
4. **If Checklist v2 was required, was it actually satisfied?** Evidence-based yes / no / partial.
5. **If not satisfied, what governance note / remediation is needed?** Three options:
   - **(a) None** — reclassify the change as a hygiene patch outside Checklist v2 scope, document the precedent in `policy_alpha_freeze_2026_04_04.md` so the same path can be used for future degradation responses.
   - **(b) Backfill** — perform Checklist v2 retrospectively on `8887576e` and document the result. If it passes, no further action; if it fails, escalate.
   - **(c) Rollback** — return to `2a3e79eb` until Checklist v2 can be performed prospectively.
6. **Does the current live ruleset need any operational action, or only documentation?** This drives the answer to "do we leave 8887576e live?". Recommendation should be evidence-grounded.

---

## 4. Out of scope for this ticket

- Performing Checklist v2 itself (separate ticket if option (b) is chosen).
- Rolling back (separate ticket; requires user approval and standard promotion-receipt machinery — note Spec 084 Step B identified that `scripts/promote_ruleset.py` was not used for the original 2026-05-04 promotion, so the receipt machinery may need fixing as a prerequisite to any rollback).
- Editing the freeze policy itself.
- ID reconciliation (handled by Spec 084 Step A).
- The reader bug (handled by Spec 084 Step B).

---

## 5. Risk if remediation later proceeds

- **Option (a) None / clarify policy:** Low risk. Documents the carve-out so future hygiene-patches don't trigger the same audit churn.
- **Option (b) Backfill Checklist v2:** Medium-high effort, low operational risk. Result might be uncomfortable: if v1.14.0 fails Checklist v2 on backfill, that surfaces a real governance violation needing remediation.
- **Option (c) Rollback:** Highest operational risk. Returns to `2a3e79eb` which was rotated AWAY from for documented signal-degradation reasons. Re-introduces the degradation. Requires the receipt-writer machinery (Spec 084 Step B prerequisite).

---

## 6. Acceptance for closure

The audit memo above answers the six questions in §3 with citation-backed evidence. The memo recommends one of (a) / (b) / (c) and lists the prerequisites. User accepts or revises the recommendation. **No code or ruleset change is in scope for closure** — only the audit memo + recommendation.

---

## 7. Dependencies

- Best done after Spec 084 Step B reader bug is at least understood (so any rollback recommendation accounts for the broken receipt path).
- Independent of Spec 083 (date-stamp corruption — already closed for policy_shadow_watch).
- Independent of Spec 085 (`shadow_watch` disposition).
- Independent of P1 reductions (still held).

---

_Spec only. No implementation. Audit triggered by Spec 084 finding that v1.14.0 governance docs cite signal-health evidence rather than Checklist v2 specifically._

# Spec 086 — v1.14.0 / `8887576e` freeze-regime compliance audit (2026-05-06)

**Status:** Read-only audit per Spec 086. **No rollback. No ruleset rotation. No scoring changes. No code edits.** Verdict + recommended remediation only.

**Headline:** v1.14.0 was a **defensive hygiene patch** (removal of a documented anti-predictive signal), **not an alpha promotion**. The freeze policy's "No new promotions w/o Checklist v2" rule does **not** unambiguously cover demotions/removals, and the operator process actually used (two-frame ALERT confirmation + comparator probe + Spec-style writeup + operator sign-off) IS the documented standard for signal demotion in `docs/hermes_skills/openclaw-data-pipeline-debug.md:328-348`. **However**, the change altered the freeze policy's explicitly-named B6 baseline AND bypassed `scripts/promote_ruleset.py` — so two governance questions remain. Recommend **option (a) — clarify policy + backfill missing receipt** as the lowest-risk reconciliation. **Question 4 classified NEEDS_HUMAN_REVIEW.**

---

## Q1 — What changed in the v1.14.0 ruleset rotation?

Per `INST_DELTA_Z_GOVERNANCE_LOG_2026_05_04.md:23-30` and `production_data/decision_rulesets/manifest.json:464-471`:

| File | Change |
|---|---|
| `run_screen.py:132-152` | `coinvest_score_z` selector weight 0.65 → 1.00; `inst_delta_z` 0.35 → 0.00 |
| `run_phase2_snapshot_delta.py:31` | `PHASE2_PINNED_RULESET_ID` `2a3e79eb` → `622edb77` (later corrected to `8887576e`) |
| `production_data/decision_rulesets/v1.14.0_coinvest_only_selector.json` | New ruleset file (copy of v1.13.0 + selector_config field changes) |
| `CLAUDE.md` Active Ruleset | v1.13.0 → v1.14.0 |

Manifest notes (line 471):
> "Weight change within existing A4 selector+ranker architecture. No new pipeline code. inst_delta_z weight redistributed: coinvest_score_z 65%->100%, inst_delta_z 35%->0% in selector. Ranker unchanged. EW Top-30 unchanged. True PIT bundle backtest remains +2.34pp/mo, t=2.57. Actual computed hash: 8887576e (file was identical to v1.13.0 until selector_config fields added 2026-05-05)."

**Scope summary:** selector signal-mix change only. **Ranker, EV, sizing, eligibility gates: unchanged.**

---

## Q2 — Was it selector/ranker/alpha behavior, hygiene/governance, or bugfix?

**Verdict: HYGIENE / DEFENSIVE PATCH.**

Justification (2 lines):
- The change *removes* an empirically-documented anti-predictive signal (`inst_delta_z` mean_ic = -0.097 over 36 dates AND event-IC = -0.244 over 75 postmortems — two independent methodologies, both negative; per `INST_DELTA_Z_SIGNAL_HEALTH_GOVERNANCE_REVIEW_2026_05_04.md:11-46`).
- It does NOT introduce a new signal, weight, lane, or model class. The remaining selector (`coinvest_score_z` at 100%) was already active and was independently verified healthy (`coinvest_score_z` mean_ic = +0.097, hit_rate = 0.897 over the same window per the comparator probe).

**Counter-argument considered:** the freeze policy memory file (`policy_alpha_freeze_2026_04_04.md`) explicitly names "B6 selector (coinvest 65% + inst_delta 35%)" as the frozen baseline. Changing the baseline from "B6" to "coinvest-only" arguably IS a behavior change to the production stack. But the change-direction is *removal* of a degraded component, not *promotion* of new alpha — Checklist v2 (which tests positive predictive evidence) is structurally inapplicable to a demoted signal.

---

## Q3 — Did docs claim Checklist v2 evidence?

**Verdict: NO.**

- `INST_DELTA_Z_GOVERNANCE_LOG_2026_05_04.md` rationale (line 19): cites "Two-frame ALERT confirmed (ic_health_monitor + calibration_evidence). Comparator probe showed coinvest_score_z healthy over same window..." — none of these are Checklist v2 components.
- `INST_DELTA_Z_SIGNAL_HEALTH_GOVERNANCE_REVIEW_2026_05_04.md` "FACTS" section (lines 11-65) cites: ic_dashboard JSON, calibration_evidence MD, sentinel memory, dashboard tail IC series, and the comparator probe. Zero references to Fama-Macbeth, bootstrap, FDR, LOSO, or year-stability.
- `production_data/decision_rulesets/manifest.json:471` notes cite the bundle backtest "remains +2.34pp/mo, t=2.57" — a single t-stat is not Checklist v2 (which requires Newey-West incremental t ≥ 1.96 AFTER controls, plus 4 other gates).
- No `checklist_v2_results.json` or equivalent artifact found under `artifacts/` for the 2026-05-04 timeframe.

`common/promotion_gate.py:validate_checklist_v2` exists and enforces the 5-gate battery, but it requires an input results file. No evidence such a results file was produced for v1.14.0.

---

## Q4 — If Checklist v2 was required, was it actually satisfied?

**Verdict: NEEDS_HUMAN_REVIEW.**

The freeze policy is **silent on demotions**. Specifically:

- `policy_alpha_freeze_2026_04_04.md:9` states: "Production is frozen. **No new promotions** until they pass Checklist v2." (emphasis added). The wording targets "promotions" — adding new alpha — not removals.
- `policy_alpha_freeze_2026_04_04.md:15-18` names B6 as the baseline but does not explicitly forbid changing the baseline; it forbids "new signal promotions" without Checklist v2.
- The 6-gate Checklist v2 itself (`policy_alpha_freeze_2026_04_04.md:26-33`) tests POSITIVE predictive evidence (selector Δ > 0, ranker IC > 0, NW-t ≥ 1.96, etc.) — gates that are structurally meaningless for a signal that has demonstrated NEGATIVE predictive evidence (which is exactly the case for demoting `inst_delta_z`).

**However, the freeze IS clear that any alteration to the production stack requires governance review.** The relevant standard for demotion is in `docs/hermes_skills/openclaw-data-pipeline-debug.md:328-348`:

> "**GOVERNANCE CEILING:** Do NOT recommend ruleset changes, weight adjustments, or signal demotion without a formal Spec-style writeup reviewed by the operator."

This is the **demotion-specific** governance bar. By that standard:
- ✓ Two-frame ALERT confirmation: YES (ic_health_monitor + calibration_evidence, two independent methodologies).
- ✓ Comparator probe: YES (`artifacts/ic_dashboard/2026-05-04_coinvest_probe.json` per review §6).
- ✓ Spec-style writeup: YES (`INST_DELTA_Z_SIGNAL_HEALTH_GOVERNANCE_REVIEW_2026_05_04.md`, 168 lines, formal structure).
- ✓ Operator sign-off: YES (`INST_DELTA_Z_GOVERNANCE_LOG_2026_05_04.md:45-46` — "Operator: Darren Schulz, Date filed: 2026-05-04").
- ✓ Conditions for re-opening documented: YES (governance log §"Conditions for re-opening").

**By the demotion-specific standard, the change was compliant. By the strict reading of the freeze ("any change to the frozen B6 baseline is a promotion"), it was not.** Reasonable people can disagree. Hence NEEDS_HUMAN_REVIEW for the policy interpretation.

**Two ancillary findings that ARE clear:**

1. **`scripts/promote_ruleset.py` was bypassed.** Per `CLAUDE.md:205` ("**Promote script**: `scripts/promote_ruleset.py` — blocks promotion unless battery PASS") this is the canonical path. The 2026-05-04 promotion landed via direct manifest edit (commit `980c02b55` "fix(manifest): register..."). Consequence: no promotion receipt was written to `artifacts/promotions/`, and Checklist v2 enforcement (which is built into the script) was not invoked. **This is a process violation regardless of the demotion-vs-promotion classification.** It is what produced the Spec 084 reader bug (sentinel reading a stale receipt because no current one exists).
2. **The change satisfies the demotion governance standard but lacks an explicit policy statement that demotion is exempt from Checklist v2.** This ambiguity is what makes the audit unable to give a clean YES/NO.

---

## Q5 — If not satisfied, what governance note / remediation is needed?

Three options (none implemented; no rollback recommended).

### Option (a) — POLICY CLARIFICATION + RECEIPT BACKFILL **[RECOMMENDED]**

- Add an explicit demotion carve-out to `policy_alpha_freeze_2026_04_04.md` codifying that:
  - Removing a signal that has been confirmed anti-predictive by two-frame ALERT + comparator probe + Spec-style writeup + operator sign-off does NOT require Checklist v2 (which tests positive evidence and is structurally inapplicable).
  - Demotions still require `scripts/promote_ruleset.py` invocation so a promotion receipt is written.
- Backfill a promotion receipt for `8887576e` at `artifacts/promotions/promotion_2026-05-04_8887576e.json` — synthetic if necessary, citing `INST_DELTA_Z_GOVERNANCE_LOG_2026_05_04.md` as the source of `gate` baseline metrics.
- Update `RULESET_CHANGELOG.md` to add the v1.14.0 entry (per `RULESET_CHANGELOG.md` headers, the changelog format expects per-promotion entries; a v1.14.0 entry was not added).

**Risk: low.** Documentation + one fixture file. No scoring impact. Surfaces the precedent so future demotions follow the same path explicitly.

### Option (b) — BACKFILL CHECKLIST V2

- Retrospectively run `common/promotion_gate.validate_checklist_v2` against the v1.14.0 selector configuration.
- Document the results regardless of outcome.
- If PASS: declare compliant retroactively.
- If FAIL: escalate — choose between leaving live (with a documented exception) vs rolling back.

**Risk: medium-high effort, low operational risk.** Caveat: Checklist v2 expects a candidate signal with positive evidence; running it on "the absence of a signal" is structurally awkward. The result may be inconclusive.

### Option (c) — ROLLBACK

- Revert to `2a3e79eb` v1.13.0.
- Re-introduces documented anti-predictive signal (-0.097 mean_ic, -0.244 event-IC).
- Requires functioning `scripts/promote_ruleset.py` workflow (broken per Q4 finding — would need to fix the bypass first).

**Risk: highest operational risk.** Re-introduces the degradation that motivated the original change. Not recommended.

---

## Q6 — Does the current live ruleset need any operational action, or only documentation?

**Verdict: Documentation + ONE small fixture-file backfill. No scoring/code action needed.**

- Live ruleset (`8887576e`) is **functionally correct**: it removes a documented anti-predictive signal in favor of a documented healthy signal. No production-decision integrity is at risk.
- The Spec 084 Step B reader fix (commit `e5dff322`) already addresses the visible side-effect (sentinel false-positive on `bebe73f8`) by reading the manifest as source of truth.
- The remaining gaps are governance hygiene:
  - No promotion receipt for `8887576e` → backfill (option (a)).
  - No `RULESET_CHANGELOG.md` entry for v1.14.0 → backfill (option (a)).
  - Policy is ambiguous on demotion-vs-promotion → clarify (option (a)).
- **No rollback is recommended.** The ruleset is doing what the evidence supports.

---

## Recommendation summary

1. **Adopt Option (a):** policy clarification + receipt backfill + changelog entry.
2. **Defer the demotion-vs-promotion policy interpretation to the operator** — both readings are defensible from the existing documents.
3. **Hold rollback off the table** unless the operator explicitly chooses Option (c).
4. **Do NOT auto-implement Option (a) without explicit user approval** — the receipt-backfill, even synthetic, becomes part of the audit trail.

---

## Out of scope confirmations

- No selector / ranker / EV / sizing changes proposed or implemented.
- No agent retirement.
- No edits to `production_data/decision_rulesets/manifest.json`, `production_data/ranker_v2_model.json`, or `common/ranker_active_contract.py`.
- Step A (text/SOUL cleanup), Spec 085, P1 reductions all still held.

---

## Provenance

Read for this audit:
- `policy_alpha_freeze_2026_04_04.md` (memory)
- `INST_DELTA_Z_GOVERNANCE_LOG_2026_05_04.md` (full)
- `INST_DELTA_Z_SIGNAL_HEALTH_GOVERNANCE_REVIEW_2026_05_04.md` (full)
- `INST_DELTA_Z_GOVERNANCE_LOG_TEMPLATE_2026_05_04.md` (template, n/a content)
- `production_data/decision_rulesets/manifest.json` (active entry + notes)
- `common/promotion_gate.py` (Checklist v2 enforcement code)
- `docs/hermes_skills/openclaw-data-pipeline-debug.md:315-348` (governance ceiling section)
- `CLAUDE.md:24, 205-207` (active ruleset, promote script reference)
- Git log filtered for ruleset commits 2026-04-06 → 2026-05-07
- Search for `checklist_v2*.json` / `checklist*` artifacts (none for v1.14.0)
- `production_data/decision_rulesets/v1.14.0_coinvest_only_selector.json` (confirmed present)

No file outside this memo was written or modified by this audit.

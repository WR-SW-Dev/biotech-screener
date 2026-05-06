# Shadow Signal Promotion — Evidence Integrity Policy

**Status:** ACTIVE
**Created:** 2026-05-06
**Authority:** CCFT North Star (CLAUDE.md)
**Trigger:** 2026-05-06 governance audit finding R8 (forward shadow accumulation risk)

---

## Problem This Policy Prevents

Shadow arms accumulate forward-return data from live production starting on
their shadow start date. If that accumulated performance is later cited as
in-sample evidence for promoting the signal to production, the result is:

- Data that was collected after the model was deployed is used to validate the model
- This is look-ahead contamination disguised as out-of-sample evidence
- It violates the CCFT North Star: "Backtest systems NEVER directly modify
  production screening behavior"

This is not hypothetical. The current shadow signals (insider_exec,
aact_execution, coinvest arms) have been accumulating daily since 2026-04-03.
Any promotion memo citing their forward shadow performance as validation
evidence would be unsound without this policy's attestation requirements.

---

## Required Attestation Fields

Every signal promotion memo that cites shadow performance MUST include
an explicit "Shadow Evidence Attestation" block. Without this block, the
memo is incomplete and cannot be used to trigger a governance review.

```
## Shadow Evidence Attestation

| Field | Value |
|-------|-------|
| Evidence cutoff date | YYYY-MM-DD |
| Shadow start date | YYYY-MM-DD |
| Forward-collected? | YES / NO |
| Pre-registered? | YES / NO |
| Validation role | MONITORING / VALIDATION |
| Contamination risk | NONE / LOW / HIGH |
```

**Field definitions:**

- **Evidence cutoff date** — the last date included in the performance calculation.
  Must be stated explicitly; "through today" is not acceptable.

- **Shadow start date** — the first date the signal began accumulating live data.
  If this is after the signal was developed, the performance window is forward-only
  and clean. If this is before the signal was designed (e.g. backreconstructed),
  flag as HIGH contamination risk.

- **Forward-collected?** — YES if the evidence window begins on or after shadow
  start date. NO if any pre-shadow backtest data is included. Mixed windows
  must be split and each segment assessed separately.

- **Pre-registered?** — YES if the signal and its evaluation methodology were
  documented before any shadow data was collected. NO if the evaluation criteria
  were chosen after observing the shadow results.

- **Validation role** — MONITORING means the shadow data is shown for context
  only and is not part of the statistical validation (Checklist v2 gates).
  VALIDATION means it is cited as evidence for a gate. VALIDATION requires
  explicit justification below.

- **Contamination risk** — NONE when forward-collected=YES and pre-registered=YES.
  LOW when forward-collected=YES but pre-registered=NO (criteria chosen after
  observing some results). HIGH when forward-collected=NO (backtest contamination).

---

## Disqualifying Conditions

A promotion memo is automatically disqualified from triggering a ruleset change if:

1. The attestation block is missing entirely.
2. Forward-collected=NO and contamination risk is not explicitly addressed.
3. Shadow performance is cited as a Checklist v2 gate result (FM / bootstrap /
   FDR / LOSO) — forward shadow does not substitute for these statistical tests.
4. The evidence cutoff date is within 5 trading days of the memo date
   (insufficient settlement; use a rolling IC window instead).
5. Pre-registered=NO and no explanation is given for why the evaluation
   criteria were chosen post-observation.

---

## Current Shadow Signal Status (as of 2026-05-06)

| Signal | Shadow start | Forward-collected | Pre-registered | Validation role |
|--------|-------------|-------------------|----------------|-----------------|
| coinvest_shadow_tracker (7 arms) | 2026-04-03 | YES | YES | MONITORING |
| insider_exec_buy_value_90d | 2026-04-03 | YES | YES | MONITORING |
| aact_execution_score | 2026-04-03 | YES | YES | MONITORING |

None of the above are pre-cleared for VALIDATION role. They may be cited in
promotion memos as supplementary monitoring context only. Statistical validation
(Checklist v2 Queue C) must come from the historical research panel
(`output/signals/research_panel.csv`), not from live shadow accumulation.

---

## Enforcement

This policy is enforced at the governance review step, not at the code level.
The reviewer (ops + sentinel) must confirm the attestation block is present
and complete before accepting a promotion memo for decision.

The `GOVERNANCE_LOG` entry for any ruleset change that cites shadow performance
must include the attestation block reproduced verbatim.

---

## Related Documents

- `CLAUDE.md` — CCFT North Star, trust buckets
- `specs/SPEC_086_v1.14.0_checklist_v2_validation.md` — coinvest-only validation bundle
- `output/checklist_v2_rerun/operator_memo.md` — 2026-04-04 Checklist v2 results
- `INST_DELTA_Z_GOVERNANCE_LOG_2026_05_04.md` — inst_delta_z governance log
- `GOVERNANCE.md` — general governance framework

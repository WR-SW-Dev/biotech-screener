# Agent Spec: Catalyst Resolution Tracker (CRT)

**Agent ID:** `agent_crt` / Step 24.5
**Model routing:** Haiku (monitoring class)
**Status:** PROPOSED
**Author:** Claude Chat (architecture spec) / Claude Code (implementation)
**Date:** 2026-03-31

---

## 1. Purpose

Close the prediction -> resolution -> calibration loop that currently blocks
five queued governance decisions:

| Blocked decision | What CRT unblocks |
|---|---|
| Lock `mean_rr` composite weight | Captures resolution of 4 live RR directional predictions |
| Promote PoS v2 to default | Generates out-of-sample calibration data by catalyst type x phase |
| Clinical bucket decomposition | Labels outcomes by clinical sub-bucket for IC attribution |
| Catalyst type taxonomy multipliers | Provides empirical hit-rate denominators by catalyst type |
| Postmortem agent test coverage | Feeds structured resolution records the postmortem agent consumes |

## 2. Position in pipeline

Step 24 (rankings written) -> Step 24.5 (CRT) -> Step 25 (reporting)

## 3. Resolution record schema version: 1.0.0

## 4. Outcome enum: HIT, MISS, MIXED, DELAYED, WITHDRAWN, NEEDS_REVIEW

## 5. Catalyst type enum: PDUFA_ACTION, PHASE_3_READOUT, PHASE_2_READOUT, PHASE_1_DATA, ADVISORY_COMMITTEE, NDA_BLA_FILING, REGULATORY_DESIGNATION, CORPORATE_UPDATE, EARNINGS, CONFERENCE_PRESENTATION

## 6. Source type enum: SEC_8K, PRESS_RELEASE, CTGOV_STATUS, FDA_ACTION, MANUAL

## 7. Detection window: T-7 to T+30 relative to expected catalyst_date

## 8. CCFT compliance: deterministic, PIT-safe, SHA256 hashed, atomic writes, immutable records

## 9. Implementation: 4 phases, ~12h total, TDD discipline

See full spec in Claude Chat session 2026-03-31 for detailed schema, detection logic, calibration rollup, governance triggers, and implementation plan.

---

*Template version: 1.0.0*

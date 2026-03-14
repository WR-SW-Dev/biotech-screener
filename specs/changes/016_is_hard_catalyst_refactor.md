# Spec 16: `is_hard_catalyst` Refactor

**Status**: PROPOSED
**Owner**: research / options lane
**Priority**: P1
**Why now**: current options studies are polluted by CTGov calendar milestones (`CT_PRIMARY_COMPLETION`, `CT_STUDY_COMPLETION`) that are not true binary catalysts. This distorts PoS divergence, straddle mispricing, and historical move calibration.

## Objective

Create a single, point-in-time-safe `is_hard_catalyst` classification that is computed once and reused everywhere options research depends on event outcomes.

## Hard Catalyst Definition (v1)

### Positive classes (is_hard_catalyst = 1)
- DATA_READOUT
- DATA_PRESENTATION (when tied to trial result)
- PDUFA / FDA_DECISION / ADVISORY_COMMITTEE / ADCOM
- REGULATORY_DECISION / APPROVAL_DECISION / CRL
- EMA_DECISION / MAA_DECISION

### Negative classes (is_hard_catalyst = 0)
- CT_PRIMARY_COMPLETION / CT_STUDY_COMPLETION
- Generic CTGOV_CALENDAR milestones
- RESULTS_POSTED / ENROLLMENT_COMPLETE
- Unspecific timing windows

## Implementation Plan

### Phase 1 — shared classifier: common/hard_catalyst.py
### Phase 2 — wire into dataset builders
### Phase 3 — --event-subset CLI flags
### Phase 4 — lookup table hygiene (v2_hard_catalyst schema)

## Deliverables
- common/hard_catalyst.py
- tests/test_hard_catalyst.py
- --event-subset wiring in studies
- report metadata showing event filter counts

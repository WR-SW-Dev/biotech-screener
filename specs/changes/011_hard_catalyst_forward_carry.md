# Spec 11: Hard Catalyst Source Forward-Carry

**Status**: IMPLEMENTED (2026-03-15)

## Problem

8-K sourced hard catalysts (FDA_PDUFA_DATE, DATA_READOUT) can disappear and reappear across daily snapshots because the SEC 8-K collector re-derives catalyst events fresh each run. BIIB's PDUFA appeared on 2026-03-12 and 2026-03-14 but was missing on 2026-03-13 — the 8-K wasn't in that day's fetch window.

This causes two problems:

1. **Blind spot streak undercounting**: `ts_blind_spot_consecutive_days` requires N consecutive days of a flag. If a hard catalyst source intermits, the streak resets even though the underlying event is still real.

2. **is_hard_catalyst instability**: The same ticker can be `is_hard_catalyst=True` on day N, `False` on day N+1, and `True` again on N+2. Research studies that filter on this flag will get inconsistent row counts across snapshots for the same name.

## Root Cause

The catalyst pipeline re-runs the full 8-K collector and event merger each day. If a filing falls outside the fetch window or the EDGAR search doesn't return it on a particular run, the catalyst_source field reverts to CTGOV_CALENDAR (or empty) for that snapshot.

## Fix

**Forward-carry rule**: Once a hard catalyst source appears for a (ticker, catalyst_event_type) pair, carry it forward into subsequent snapshots until the event date passes.

### Implementation

**Phase 1 — State file: `data/state/hard_catalyst_carry.json`**

```json
{
    "BIIB": {
        "catalyst_event_type": "FDA_PDUFA_DATE",
        "catalyst_source": "SEC_8K_FILING",
        "catalyst_days_at_first_seen": 22,
        "first_seen_date": "2026-03-12",
        "estimated_event_date": "2026-04-03"
    }
}
```

**Phase 2 — Carry logic in `run_screen.py`**

After the catalyst scoring pass but before the options diagnostics enrichment:

```python
def _forward_carry_hard_catalysts(csv_rows, state_path, as_of_date):
    """Forward-carry hard catalyst sources from prior runs.

    For each row where catalyst_source is empty or CTGOV_CALENDAR:
    - Check if the ticker has a prior hard catalyst entry in state
    - If the estimated_event_date is still in the future, override
      catalyst_source and catalyst_event_type with the carried values
    - If the event date has passed, remove the entry from state
    """
```

Rules:
- Only carry from `_HARD_CATALYST_SOURCES` (SEC_8K_FILING, FDA_PDUFA_DATE, DATA_READOUT, COMPANY_GUIDANCE)
- Only carry forward, never backward — if today's run has a DIFFERENT hard source, use today's
- Expire entries when `estimated_event_date < as_of_date`
- Log every carry: `[CARRY] BIIB: FDA_PDUFA_DATE from SEC_8K_FILING (first seen 2026-03-12)`

**Phase 3 — Update state after each run**

After catalyst enrichment, scan csv_rows for new hard catalyst sources not yet in state. Add them. This is the "learn" step — the state file grows as new 8-K events are detected and shrinks as events resolve.

### Where to insert in run_screen.py

After the Module 3 catalyst scoring pass (which sets catalyst_event_type and catalyst_source) but before:
- Options diagnostics enrichment
- Market-model disagreement overlay
- Term structure validation
- Review queue

This ensures all downstream consumers see the carried-forward source.

## Scope

- Only affects catalyst_source and catalyst_event_type fields
- Does NOT change catalyst_days (which is recomputed from the event date each run)
- Does NOT change composite_score or any ranking
- Does NOT affect the decision engine

## Tests

- Carry fires when source is empty but state has entry
- Carry does NOT override a different hard source from today's run
- State entry expires when event date passes
- New hard source gets added to state
- Multiple tickers carry independently

## CCFT Compliance

The state file carries `first_seen_date` for audit trail. The carry is logged explicitly so the provenance of any overridden field is traceable. The state file must never be read by the decision engine or any scoring component.

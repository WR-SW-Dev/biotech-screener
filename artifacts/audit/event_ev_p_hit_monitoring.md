# event_ev_p_hit Monitoring Log
**Spec:** spec_096  
**Gate 3 thresholds:** n≥15 bound records → first calibration look; n≥30 → formal IC test  
**Binder:** `_bind_event_ev_p_hit` in `tools/catalyst_resolution_tracker.py` (Spec 077, shipped)  
**Backfill policy:** No backfill unless exact node_id evidence in EV artifact predating event resolution

---

## Monthly Checks

| Check date | Total postmortems | Field present | Non-null | Match types | Gate 3 progress | Notes |
|------------|------------------|---------------|----------|-------------|-----------------|-------|
| 2026-05-08 | 158 | 37 | 0 | none | 0/15 (first look) | Field present in resolution_source.event_ev_p_hit for 37 records (dates 2026-04-27 to 2026-05-01). All null — EV artifact coverage not yet reaching these events. Binder architecture confirmed operational. |

---

## Status as of 2026-05-08

**Binder health:** OPERATIONAL. The binder ran on 37 postmortem records and correctly recorded `null` where no EV artifact match was found. No silent failures detected.

**Why all null:** The 37 postmortem files with the field cover events that resolved 2026-04-27 to 2026-05-01. For a non-null binding, an EV artifact must exist in `artifacts/event_ev/` with either (a) a matching `node_id` or (b) a matching (ticker, expected_date ±7d) that is unambiguous. EV artifact coverage for those specific events is not present in the current EV artifact store.

**Accumulation required:** As new events resolve and the event_ev pipeline produces artifacts for those events, forward-only bindings will populate. No action needed — monitor monthly.

---

## Gate 3 Tracker

| Milestone | Count required | Current count | Est. date |
|-----------|---------------|---------------|-----------|
| First calibration look | 15 | 0 | Unknown (EV artifact coverage dependent) |
| Formal IC test | 30 | 0 | Unknown |

---

## Next Check

Run on or before **2026-06-08**. Check:
1. Total postmortems (should be growing at ~3-4/month)
2. Field-present count (should grow as new postmortems are written by `run_postmortem.py`)
3. Non-null count (Gate 3 progress)
4. Any non-null: record match_type (exact_node vs ticker_date_7d) and p_hit distribution

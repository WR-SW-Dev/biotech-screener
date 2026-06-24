# Spec 100 Early Diagnostic — Monitor Only

**Date:** 2026-06-24  
**Status:** SPEC100_EARLY_MONITOR_ONLY  
**Governance force:** NONE  
**Label:** NOT_PRIMARY_GATE — NOT_PROMOTION_EVIDENCE

---

## Purpose

Operational verification that `tools/measure_final_score_ic_spec100.py` runs cleanly before
the July 8 primary gate. No governance conclusions are drawn from this run.

---

## Command Run

```bash
python3 tools/measure_final_score_ic_spec100.py \
  --start-date 2026-06-18 --end-date 2026-06-24 \
  --horizons 5 6 \
  --forward-date-mode nearest_later \
  --forward-tolerance-days 3 \
  --output-dir artifacts/spec100
```

---

## Tool Execution

- **Executed cleanly:** YES — no errors, no crashes
- **Eligible universe:** 60 tickers (actionable_rank <= 60) per snapshot
- **Observable pairs:** 59 tickers per horizon (1 price gap)
- **Artifacts written:** `dem_ranker_phase_2b_final_score_ic_summary.json`, `T+5.csv`, `T+6.csv`

---

## Available Horizon

Only the **2026-06-18 base date** has observable forward data as of 2026-06-24.

| Base date  | Horizon | Forward date | Status          |
|------------|---------|--------------|-----------------|
| 2026-06-18 | T+5     | 2026-06-23   | Observable      |
| 2026-06-18 | T+6     | 2026-06-24   | Observable      |
| 2026-06-22 | T+5     | —            | Forward missing |
| 2026-06-23 | T+5     | —            | Forward missing |
| 2026-06-24 | T+5     | —            | Forward missing |

Coverage gap: snapshots for 2026-06-19, 2026-06-20, 2026-06-21 are missing (weekend + gaps);
forward snapshots for 2026-06-27+ do not yet exist. This is expected — daily pipeline accumulates
over time.

---

## IC Results (Monitor Only — N=1 Observation Each)

| Horizon | base date  | obs | IC      | t-stat | vs 0.0200 threshold |
|---------|------------|-----|---------|--------|---------------------|
| T+5     | 2026-06-18 | 59  | 0.0000  | 0.00   | BELOW               |
| T+6     | 2026-06-18 | 59  | +0.0154 | 0.12   | BELOW               |

**N=1 observation is not interpretable.** A single base-date IC is noise. These numbers have
zero statistical weight and zero governance force.

The "4 dates" in the tool summary includes 3 forward-unobservable NaN rows — effective valid
observations: 1 per horizon.

---

## Governance Status

```
SPEC100_GOVERNANCE_GATE:     PENDING
PRIMARY_GATE_DATE:           2026-07-08
PRIMARY_GATE_HORIZON:        T+20 from 2026-06-18 base
PRIMARY_GATE_THRESHOLD:      final_score IC >= 0.0200
DEM_AUTHORITY:               LEVEL_0_BLOCKED (unchanged)
RANKER_IC_STATUS:            UNMEASURED (Spec 095 open)
MODEL_CHANGES_AUTHORIZED:    NO
PROMOTION_EVIDENCE:          NO
```

This run does NOT:
- Pass or fail Spec 100
- Unblock DEM
- Change ranker, selector, sizing, final_score, eligibility, or portfolio construction
- Constitute promotion evidence

---

## What Happens Next

On or after **2026-07-08**: run the primary gate using the July 8 runbook
(`docs/dem_ranker_july8_ic_remeasurement_runbook.md`):

```bash
for FLD in final_score catalyst_decay_w catalyst_score coinvest_score_z financial_score; do
  echo "=== $FLD ==="
  python3 tools/measure_final_score_ic_spec100.py \
    --score-field "$FLD" \
    --start-date 2026-06-18 --end-date 2026-07-15 \
    --horizons 20
done
```

That run produces the first authoritative T+20 IC reading from a real-time forward snapshot.
Outcome determines DEM authority per the Phase C memo decision tree.

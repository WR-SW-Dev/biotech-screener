# Outcome Data Audit — 2026-03-14

## Finding: The outcome dataset is structurally PCD-dominated

| Bucket | Count | % |
|--------|-------|---|
| Genuine binary (abs_gap >= 10%) | **0** | 0% |
| Moderate move (5-10%) | 20 | 18% |
| Calendar noise (< 5%) | 91 | 82% |

All 111 outcome rows are CT_PRIMARY_COMPLETION or CT_STUDY_COMPLETION
from CTGOV_CALENDAR (avg abs_gap = 2.5%). Zero SEC_8K_FILING, zero
FDA_PDUFA_DATE, zero DATA_READOUT events have outcomes yet.

## Root Cause

Not a join bug — temporal limitation. The snapshot archive (2026-03-12
to 2026-03-14) has 8 SEC_8K_FILING hard catalyst rows but their events
are 17-22 days in the future. Forward returns can't be computed until
the events actually happen.

The older archive snapshots (pre-options-diagnostics) don't have
options data, so they can't contribute to the enriched dataset even
if they have outcomes.

## Impact on Research Studies

| Study | Previous Result | Corrected Result |
|-------|----------------|-----------------|
| PoS divergence | IC=-0.193 alpha_candidate | insufficient_sample (8 hard rows, 0 outcomes) |
| Straddle mispricing | IC=-0.172 alpha_candidate | insufficient_sample (8 hard rows, 0 outcomes) |

Both previous "alpha_candidate" verdicts were driven by PCD calendar
noise, not genuine binary events. The signals need real readout/PDUFA
outcomes to produce meaningful verdicts.

## Fix Applied

Added `is_hard_catalyst` flag to `eval_options_alpha.py` enriched dataset
builder. Both study scripts now accept `--hard-catalysts-only` flag.

Hard catalyst sources: FDA_PDUFA_DATE, SEC_8K_FILING, DATA_READOUT,
COMPANY_GUIDANCE. Backstop: abs_gap >= 10% regardless of labeling.

## Next Steps

1. Wait for hard catalyst events to occur (BIIB PDUFA ~Apr 3, CELC/PVLA/TBPH readouts ~Apr 1)
2. Re-run both studies with `--hard-catalysts-only` once outcomes exist
3. If hard catalyst count remains < 20 after 4 weeks, expand archive depth

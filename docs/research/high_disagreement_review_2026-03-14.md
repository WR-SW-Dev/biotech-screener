# High-Disagreement Manual Review — 2026-03-14

All 16 names have **negative** pos_divergence: market pricing larger moves than model quality suggests.

## Review Table

| Ticker | Tier | CatDays | IV | PosDvg | CatMode | Archetype | Root Cause | Action |
|--------|------|---------|-----|--------|---------|-----------|------------|--------|
| SVRA | C | 442 | 23.96 | -6.97 | specific_days | drug_developer | stale_window | fix_catalyst_date |
| SABS | C | 597 | 13.10 | -4.35 | no_upcoming | drug_developer | stale_window | fix_catalyst_date |
| ANNX | C | 231 | 17.60 | -3.94 | specific_days | drug_developer | genuine_skepticism | accept_as_overlay_signal |
| CMPX | C | 262 | 11.54 | -2.87 | specific_days | drug_developer | genuine_skepticism | accept_as_overlay_signal |
| DYN | C | 108 | 5.79 | -2.34 | specific_days | drug_developer | genuine_skepticism | accept_as_overlay_signal |
| ABEO | B | 474 | 10.32 | -2.32 | specific_days | drug_developer | stale_window | fix_catalyst_date |
| AURA | B | 261 | 10.04 | -2.19 | specific_days | drug_developer | genuine_skepticism | accept_as_overlay_signal |
| FHTX | C | 444 | 2.32 | -2.15 | specific_days | drug_developer | stale_window | fix_catalyst_date |
| TRDA | C | 1083 | 1.14 | -1.96 | no_upcoming | drug_developer | stale_window | fix_catalyst_date |
| TSHA | B | 363 | 10.40 | -1.88 | specific_days | drug_developer | stale_window | fix_catalyst_date |
| HROW | C | 324 | 0.64 | -1.73 | far_window | commercial_pharma | data_artifact | investigate_further |
| APLS | C | 444 | 0.51 | -1.72 | specific_days | commercial_biotech | stale_window | fix_catalyst_date |
| ACAD | C | 292 | 0.59 | -1.70 | specific_days | commercial_biotech | data_artifact | investigate_further |
| CERS | C | 138 | 7.66 | -1.69 | specific_days | platform_devices | genuine_skepticism | accept_as_overlay_signal |
| TARS | C | 109 | 0.61 | -1.64 | far_window | commercial_biotech | data_artifact | investigate_further |
| ESPR | C | 16 | 1.28 | -1.62 | far_window | commercial_pharma | data_artifact | investigate_further |

## Root Cause Summary

| Root Cause | Count | Names |
|------------|-------|-------|
| stale_window | 7 | SVRA, SABS, ABEO, FHTX, TRDA, TSHA, APLS |
| genuine_skepticism | 5 | ANNX, CMPX, DYN, AURA, CERS |
| data_artifact | 4 | HROW, ACAD, TARS, ESPR |

## Analysis

### Stale Window (7 names — 44%)

These names have `catalyst_days > 300` (most > 400) with EXTREME IV. The model scores them low because far-out catalysts get heavy decay, but the options market sees micro-cap clinical-stage vol that has nothing to do with the distant PCD. The divergence is **mechanically inflated** by the sqrt(T) term in implied_event_move: large catalyst_days × high IV = enormous implied move → huge negative divergence.

**Key insight:** The pos_divergence signal should **pre-filter** names with `catalyst_days > 180` before computing divergence. The signal is only meaningful within the same catalyst window the decision engine operates on (0-180d). Names beyond 180d are in the `far_window` or `no_upcoming` zone where IV has no catalyst-specific interpretation.

TRDA at 1083 days is the clearest case: no upcoming catalyst, IV of 1.14 is normal, but the sheer distance creates artificial divergence.

### Genuine Skepticism (5 names — 31%)

These are the real overlay candidates:
- **ANNX/CMPX/AURA**: drug developers, 231-262 days out, EXTREME IV (10-17x), model scores near zero but IV says the market sees a big event. These are names where the market clearly expects catalyst-driven moves the model doesn't credit.
- **DYN**: 108 days, IV=5.8, SEC 8-K sourced readout. Market pricing a meaningful move in a window the model should be covering.
- **CERS**: 138 days, IV=7.7, platform device company with strong event premium (term slope -0.49).

These 5 names are where the disagreement overlay adds genuine value.

### Data Artifact (4 names — 25%)

- **HROW/ACAD/TARS**: commercial archetypes with normal/low IV (0.5-0.6) but low model scores. The divergence is driven by the model penalizing commercial names more than the market. This isn't market skepticism — it's archetype mismatch in the z-scoring.
- **ESPR**: 16 days out, `far_window` mode (shouldn't be), IV=1.28 elevated. The far_window classification on a 16-day catalyst is suspicious — this may be a catalyst_mode assignment bug.

## Recommendations

### Signal pre-filter (immediate)
Add `catalyst_days <= 180` filter before computing pos_divergence in `run_screen.py`. This eliminates the 7 stale_window artifacts and focuses the diagnostic on names where the model and market are actually looking at the same event horizon.

### Archetype-aware z-scoring (future)
Compute pos_divergence z-scores within archetype cohorts (drug_developer, commercial_biotech, commercial_pharma) rather than cross-sectionally across the full universe. This would reduce data_artifact noise from archetype score differences.

### ESPR investigation
Check why ESPR (16 catalyst_days) is in `far_window` mode — likely a catalyst_mode assignment edge case where a closer event exists but isn't surfaced as primary.

### Surviving signal
After removing stale_window and data_artifact names, **5 of 16 (31%) represent genuine market-model disagreement**. This is a reasonable hit rate for a shadow diagnostic — the signal is useful but noisy without pre-filtering.

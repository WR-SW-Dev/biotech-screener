# 002 — Catalyst Tilt L3 Sizing

**Ruleset**: `2b1c8959` (v1.13.0)
**Derived from**: `7177a4ea` (v1.11.0, active)
**Layer**: L3 (sizing only — no membership or sort order change)
**Status**: CANDIDATE

## Change

Flip `enable_catalyst_tilt: true` on the active ruleset. Keep the default
multipliers that have been present (but disabled) since the catalyst tilt
feature was first added:

| Bucket  | Multiplier | Effect |
|---------|-----------|--------|
| NEAR    | 1.10      | +10% weight for ≤120d catalyst |
| MID     | 1.05      | +5% weight for ≤180d catalyst |
| FAR     | 0.95      | -5% weight for >180d catalyst |
| MISSING | 0.90      | -10% weight for no catalyst data |

Mode: `hard` (discrete bands, no logistic decay).

## Evidence

### Analytical Sweep (2026-03-13)

34 snapshot dates (2025-06-01 to 2025-12-31), top-20 holdings, 16 grid
variants (NEAR: 1.05/1.10, MID: 1.02/1.05, FAR: 0.95/1.00, MISSING:
0.90/0.95).

**All 16 variants beat baseline at both horizons.** Grid is monotonically
ordered — more aggressive tilts produce larger deltas.

Best variant (default mults):

| Horizon | Delta vs Baseline | Win Rate | Median Delta |
|---------|-------------------|----------|--------------|
| 63d     | +0.66%            | 80% (24/30) | +0.63%    |
| 84d     | +1.16%            | 96% (24/25) | +1.13%    |

Turnover impact: 0.89% (negligible — pure weight reallocation).

### Prior Validation (2026-02-12, PARKED)

10 snapshots (2025-01 to 2025-10). Effect +0.18pp (default) to +0.37pp
(aggressive) at 60d. Parked due to small sample and inconsistency (4/10
win rate). Current sweep supersedes with 3x sample size and 80-96% win rate.

### Live Pipeline Verification (2026-03-12)

- 20/20 top-20 membership overlap (L3-only confirmed)
- `catalyst_tilt_applied=1` on all eligible names
- Total absolute weight change: 0.8pp
- All validation checks PASS

## Top-20 Bucket Distribution

Average across 34 dates:
- NEAR: 55% (11.0 names)
- MID: 16% (3.2 names)
- FAR: 19% (3.9 names)
- MISSING: 10% (2.0 names)

## Caveats

- t-stats low (0.43 / 0.38) — per-date variance high relative to mean
- Asymmetric tails: worst -1.21%, best +2.96% (favorable skew)
- Current top-20 is heavily NEAR — tilt mostly upweights; FAR/MISSING
  penalty has less opportunity to discriminate

## Promotion Path

1. Add to manifest as candidate (done)
2. Monitor live weight drift on next 3-5 production runs
3. If stable: promote via `scripts/promote_ruleset.py`
4. Track via `catalyst_tilt_applied` / `catalyst_tilt_mult` columns in rankings.csv

## Artifacts

- Sweep results: `output/research/catalyst_tilt_sweep/catalyst_tilt_sweep.json`
- Sweep script: `scripts/research/eval_catalyst_tilt_sweep.py`
- Prior validation: `artifacts/catalyst_tilt_validation_2026-02-12.md`

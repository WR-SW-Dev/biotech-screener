# Spec 21: IV Build Curves and Crush Calibration

**Status**: IMPLEMENTING
**Date**: 2026-03-15
**Ruleset impact**: NO (research-only; no ranking or decision-engine change)

## Objective

Two research scripts on top of existing historical IV feature panel:
1. Normalized IV build curves into hard catalysts (baseline + deviation)
2. Empirical post-event IV crush calibration (replace uncalibrated 0.45 assumption)

Plus a third telemetry script for daily RR/skew timeseries accumulation.

## Phases
1. eval_iv_build_curves.py — IV approach curves by broad event bucket
2. measure_iv_crush.py — empirical pre/post IV crush ratios
3. build_live_options_timeseries.py — daily RR/skew telemetry panel

## Key constraint
Reuse existing historical_iv_features.csv — do NOT create a second surface builder.

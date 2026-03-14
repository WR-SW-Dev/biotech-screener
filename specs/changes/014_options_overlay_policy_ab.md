# Spec 14: Options Construction Overlay A/B Gate

**Status**: BUILDING

## Pass/Fail Thresholds

- Cumulative hedged delta: >= +0.20pp
- Mean weekly hedged delta: >= -0.05pp
- Turnover delta: <= +0.25pp

## Verdicts

- PASS: all three bars pass
- WARN: mean + turnover pass, cumulative misses
- FAIL: mean or turnover fails
- INVALID_DATA: zero OQC across all snapshots
- INVALID_NOOP: overlay enabled but zero periods changed construction
- NEEDS_MORE_BUT_SAFE: WARN + turnover ok + gap_risk_high_delta <= 0 + binary_31_90 delta >= 0

## Arms

- A (baseline): current policy
- B (treatment): same policy + options_overlay.enabled=true

## Invariants

Same snapshots, prices, ruleset, universe, bucket targets, family targets.
Only difference: options_overlay toggle.

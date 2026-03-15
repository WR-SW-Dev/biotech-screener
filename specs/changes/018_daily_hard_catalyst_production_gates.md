# Spec 18: Daily Hard-Catalyst Production Gates

**Status**: IMPLEMENTING
**Owner**: research / shadow operations
**Priority**: P1
**Depends on**: Spec 11 (hard catalyst forward-carry), Spec 16 (`is_hard_catalyst`), Spec 17 (daily options review queue)

## Objective

Add post-screen production gates that validate the **daily hard-catalyst options lane** is:
1. generating the expected queue artifacts,
2. surfacing a minimally useful number of hard catalysts,
3. enriching those hard catalysts with live options data,
4. preserving hard-source stability via forward-carry,
5. and producing a reviewable set of names rather than a noisy or empty artifact.

These gates are for the **review/support lane**, not for the ranking model.
They should live in `tools/run_daily_production.py` and run after `run_screen.py` completes.

## Gate Set

### 1. hard_queue_artifacts
Verify queue JSON/CSV exist and parse. FAIL if missing/unreadable.

### 2. hard_catalyst_supply
- FAIL if n_hard < 3
- WARN if 3 <= n_hard < 8
- FAIL if n_hard_0_90d == 0
- WARN if 1 <= n_hard_0_90d < 4

### 3. hard_options_coverage
- opt_coverage_pct: FAIL < 40%, WARN < 60%
- actual_straddle_coverage_pct: FAIL < 20%, WARN < 50%
- reviewable_signal_pct: WARN if 0

### 4. hard_carry_state
- FAIL if state unreadable
- FAIL if unexpired ticker backslid to soft source
- WARN if state absent but hard queue non-empty

### 5. hard_queue_actionability
- PASS if n_hard_reviewable >= 3
- WARN if 1-2
- WARN if 0

## Thresholds (GateConfig)

```python
hard_queue_min_warn: int = 8
hard_queue_min_fail: int = 3
hard_queue_near_term_min_warn: int = 4
hard_queue_near_term_min_fail: int = 1
hard_options_coverage_warn_pct: float = 60.0
hard_options_coverage_fail_pct: float = 40.0
hard_actual_straddle_warn_pct: float = 50.0
hard_actual_straddle_fail_pct: float = 20.0
hard_reviewable_min_warn: int = 3
```

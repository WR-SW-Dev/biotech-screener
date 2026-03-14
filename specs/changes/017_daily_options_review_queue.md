# Spec 17: Daily Options Mispricing Review Queue

**Status**: PROPOSED
**Owner**: research / shadow operations
**Priority**: P1
**Depends on**: Spec 16 (is_hard_catalyst), live Massive chain analytics, historical move lookup

## Objective

Create a daily, non-ranking, review-only options queue that identifies mispriced biotech names via:
1. Cheap/Rich Straddle (actual vs historical move)
2. High Market-Model Disagreement
3. Term Structure Flags
4. Skew / Risk-Reversal Signal

## Queue Inclusion Logic

A row enters if it satisfies at least one trigger:
- A: cheap_vol_score >= 1.30 or <= 0.70 (hard catalyst only)
- B: market_model_disagreement == "high"
- C: ts_flag == "1"
- D: abs(opt_rr_25d) >= 0.15

## Priority Score

review_priority_score = 3*disagreement + 2*ts_flag + 2*hard_catalyst + 2*cheap_rich + 1*extreme_skew + 1*within_90d

## Output Artifacts

Per snapshot:
- options_review_queue.csv (all rows)
- options_review_queue.json (schema: options_review_queue.v1)
- options_review_queue.md (top 25 + summary)

## Implementation Plan

### Phase 1 — common/options_review_queue.py
### Phase 2 — wire into run_screen.py
### Phase 3 — coverage integration (log line + coverage_quality.json)

## Deliverables
- common/options_review_queue.py
- tests/test_options_review_queue.py
- Wiring in run_screen.py
- Log: [OPTIONS_QUEUE] queued=N hard=N cheap=N rich=N disagree=N ts=N skew=N

# Learnings Log

<!-- Self-improving agent learning entries. Format: [LRN-YYYYMMDD-XXX] -->
<!-- Entries logged during conversations; promoted to CLAUDE.md / memory when verified. -->

## [LRN-20260329-001] size_confound_in_raw_event_counts

**Logged**: 2026-03-29T19:00:00Z
**Priority**: high
**Status**: pending
**Area**: research

### Summary
Raw event counts (graveyard burden, catalyst density, neg_reg count) all correlate positively with forward returns — capturing "well-covered large company" not genuine alpha.

### Details
Both graveyard burden (IC=+0.046 at 63d) and catalyst history features (event_density IC=+0.141, neg_reg IC=+0.052) showed wrong-sign results. The same size/coverage confound appeared in PI trial count earlier. Any count-based feature needs size-orthogonal decomposition before promotion.

### Suggested Action
Residualize all count-based research features against pipeline size (n_total_trials) or market_cap_bucket before testing for signal. Do not promote raw count features.

### Metadata
- Source: research_backtest
- Related Files: scripts/research/backtest_graveyard_signal.py, scripts/research/backtest_catalyst_history_signal.py
- Tags: size_confound, research, signal_quality
- Pattern-Key: raw_count_size_confound
- Recurrence-Count: 3

## [LRN-20260329-002] portfolio_drag_is_construction_not_ranking

**Logged**: 2026-03-29T20:00:00Z
**Priority**: critical
**Status**: promoted
**Area**: portfolio

### Summary
Shadow portfolio drag comes from flat 3% weights on C-tier names and no exit rule for persistent headwind+drawdown, not from ranking model defects.

### Details
C-tier P&L/weight-day: -0.78% (2x worse than A-tier). Headwind bleed: 2.3x non-headwind. Tier-weighted policy (A=4/B=2.5/C=1/D=0) improved returns by +1.60pp over 18 days. Adding headwind+drawdown exit improved by +1.82pp. SLN and EYPT were held as C-tier headwind names at full weight — not rebalance lag, but policy design.

### Suggested Action
Run tier-weighted policy as formal shadow candidate (Spec 035). Already implemented and wired into run_screen.py. Current verdict: PROMISING (4/4 gates pass).

### Metadata
- Source: shadow_attribution_audit
- Related Files: tools/build_policy_shadow_compare.py, tools/eval_policy_candidate.py, specs/changes/035_tier_weighted_policy.md
- Tags: portfolio_construction, policy, shadow_candidate
- Skill-Path: Spec 035

## [LRN-20260329-003] open_targets_api_search_type_mismatch

**Logged**: 2026-03-29T17:00:00Z
**Priority**: medium
**Status**: resolved
**Area**: data_pipeline

### Summary
Open Targets GraphQL search endpoint returns generic SearchResult types — inline fragments like `... on Drug` or `... on Disease` are silently ignored. Must use two-step: search → get ID → fetch details by ID.

### Details
This bug caused zero results from the Open Targets enrichment tool. The fix required both a two-step query pattern AND correcting the field name `maxPhaseForIndication` → `maxClinicalStage`. After fix: 218/309 tickers enriched with 14,833 disease associations.

### Suggested Action
Always use two-step query pattern for Open Targets API. The search endpoint does not support type-specific inline fragments.

### Metadata
- Source: bug_fix
- Related Files: tools/enrich_open_targets.py, tools/enrich_indication_master.py
- Tags: api, open_targets, graphql, enrichment
- Pattern-Key: ot_search_type_mismatch

## [LRN-20260329-004] f_string_no_placeholder_flake8

**Logged**: 2026-03-29T18:00:00Z
**Priority**: low
**Status**: resolved
**Area**: code_quality

### Summary
Flake8 F541 fires on f-strings used for markdown table headers with no interpolation. Use plain strings for static table headers.

### Details
Recurred across bioshort_watch, catalyst_history_diagnostics, eval_policy_candidate, build_policy_shadow_compare. Every new markdown formatter hits this.

### Suggested Action
Use plain strings for static markdown table headers, f-strings only when interpolating values.

### Metadata
- Source: pre_commit_hook
- Tags: flake8, code_style
- Pattern-Key: f_string_no_placeholder
- Recurrence-Count: 5

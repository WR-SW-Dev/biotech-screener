# Feature Requests Log

<!-- Self-improving agent feature request entries. Format: [FEAT-YYYYMMDD-XXX] -->

## [FEAT-20260329-001] size_orthogonal_signal_decomposition

**Logged**: 2026-03-29T20:30:00Z
**Priority**: medium
**Status**: pending
**Area**: research

### Requested Capability
Residualize graveyard burden and catalyst history features against pipeline size before testing for signal.

### User Context
All raw count-based signals show positive IC (more events = higher returns), capturing company size/coverage, not genuine alpha. Need orthogonalization against n_total_trials or market_cap_bucket.

### Complexity Estimate
medium

### Suggested Implementation
Add `--residualize-against` flag to backtest scripts. Regress feature against size proxy, use residuals as the signal. Test neg_reg_residual and graveyard_burden_residual.

### Metadata
- Frequency: recurring (3 signals hit same wall)
- Related Features: backtest_graveyard_signal, backtest_catalyst_history_signal

## [FEAT-20260330-003] production_branch_for_triggers

**Logged**: 2026-03-30T13:00:00Z
**Priority**: medium
**Status**: pending
**Area**: ops

### Requested Capability
Pin remote triggers to a `production` branch or commit SHA instead of `main`, so a bad push at 1:30pm doesn't break the 1:37pm automated run.

### User Context
Standard deployment pattern. Remote triggers clone from main — if broken code is pushed just before the scheduled run, the automation fails.

### Complexity Estimate
simple

### Suggested Implementation
Create `production` branch. Update trigger sources to use it. Only merge to `production` after local testing passes.

### Metadata
- Frequency: first_time
- Related Features: remote_triggers

## [FEAT-20260329-002] dashboard_page2_research_evidence

**Logged**: 2026-03-29T21:00:00Z
**Priority**: low
**Status**: pending
**Area**: dashboard

### Requested Capability
Second dashboard page showing research/evidence: IC dashboard, calibration, graveyard/catalyst diagnostics.

### User Context
Policy Control Tower is page 1. Page 2 would make research artifacts browsable without reading raw JSON.

### Complexity Estimate
medium

### Suggested Implementation
Add `/research` route to dashboard/app.py. Load graveyard diagnostics, catalyst history diagnostics, signal backtest results. Reuse card/table patterns from page 1.

### Metadata
- Frequency: first_time
- Related Features: dashboard

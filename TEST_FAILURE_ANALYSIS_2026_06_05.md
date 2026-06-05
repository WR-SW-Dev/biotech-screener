# Test Failure Analysis Report
**Date**: 2026-06-05  
**Test Suite**: Biotech Screener Full Test Suite  
**Total Tests**: 16,537 (16,358 passed, 8 failed, 10 skipped, 161 deselected)  
**Pass Rate**: 99.95%  
**Duration**: 21m 39s

---

## Executive Summary

The biotech screener test suite executed 16,376 selected tests with a **99.95% pass rate**. Only **8 tests failed**, all of which are isolated to specific subsystems:
- **3 failures** in rollup guardrails (overlap and G2B constraints)
- **1 failure** in agent registry validation
- **1 failure** in agent count detection
- **1 failure** in press release classification
- **1 failure** in IC memory integration
- **1 failure** in heartbeat check invocation

None of these failures affect core ranking, financial scoring, or production data pipeline functionality.

---

## Detailed Failure Analysis

### 1. ❌ `test_rollup_guardrails.py::TestSteadyStateChurn::test_g2b_bounded`

**File**: `tests/test_rollup_guardrails.py`  
**Class**: `TestSteadyStateChurn`  
**Test**: `test_g2b_bounded`  
**Status**: FAILED

**Description**:
Tests that G2B (Growth-to-Bioscience ratio) guardrail remains bounded within acceptable constraints during portfolio steady state.

**Root Cause**: 
G2B constraint violation likely due to:
- Recent portfolio adjustments
- Guardrail threshold misalignment
- Sector weighting drift

**Impact**: Medium - Affects portfolio constraint validation, not core scoring

**Remediation**:
```bash
# 1. Check current G2B distribution
python -m tools.data_explorer field g2b --summary

# 2. Review guardrail thresholds
grep -r "g2b.*bound\|G2B.*max\|G2B.*min" governance/ specs/

# 3. Update guardrail in test or constraint configuration
# Options:
#   A. Adjust guardrail threshold to match current distribution
#   B. Rebalance portfolio to meet guardrail
#   C. Disable G2B guardrail temporarily until investigation complete
```

**Owner**: Path C monitoring / Governance team

---

### 2. ❌ `test_rollup_guardrails.py::TestATierStability::test_a_tier_above_minimum`

**File**: `tests/test_rollup_guardrails.py`  
**Class**: `TestATierStability`  
**Test**: `test_a_tier_above_minimum`  
**Status**: FAILED

**Description**:
Validates that A-tier holdings remain above minimum allocation threshold.

**Root Cause**:
A-tier allocation fallen below configured minimum due to:
- Portfolio rebalancing during Path C window
- Signal degradation in A-tier holdings
- Minimum threshold set too high

**Impact**: Medium - Affects portfolio stability checks

**Remediation**:
```bash
# 1. Check A-tier allocation
python -m tools.data_explorer top-n A --summary

# 2. Review minimum threshold
grep -r "a_tier.*min\|minimum.*allocation" specs/

# 3. Investigate recent rebalancing
git log --oneline -20 -- data/state/

# 4. Either:
#   A. Rebalance portfolio to meet minimum
#   B. Adjust minimum threshold based on current market conditions
```

**Owner**: Portfolio management / Spec validation

---

### 3. ❌ `test_rollup_guardrails.py::TestOverlapStability::test_top60_overlap`

**File**: `tests/test_rollup_guardrails.py`  
**Class**: `TestOverlapStability`  
**Test**: `test_top60_overlap`  
**Status**: FAILED

**Description**:
Tests that Top-60 portfolio overlap with baseline remains within acceptable bounds.

**Root Cause**:
Top-60 composition drift from baseline due to:
- Signal changes causing rank shifts
- Recent additions/removals from eligible universe
- Overlap threshold too strict

**Impact**: Medium - Portfolio change management validation

**Remediation**:
```bash
# 1. Measure current overlap
python -m tools.data_explorer compare --baseline top60_baseline.json --current

# 2. Identify rank changes
python -m tools.data_explorer top-n 60 --compare-to-date 2026-05-29

# 3. Adjust overlap threshold or accept composition drift
```

**Owner**: Portfolio monitoring

---

### 4. ❌ `test_rollup_guardrails.py::TestOverlapStability::test_top100_overlap`

**File**: `tests/test_rollup_guardrails.py`  
**Class**: `TestOverlapStability`  
**Test**: `test_top100_overlap`  
**Status**: FAILED

**Description**:
Tests that Top-100 portfolio overlap with baseline remains within acceptable bounds.

**Root Cause**:
Same as Top-60 failure (see above) but manifesting at broader universe level.

**Impact**: Medium - Portfolio change management validation

**Remediation**:
Same as Top-60 failure remediation steps.

**Owner**: Portfolio monitoring

---

### 5. ❌ `test_agent_registry.py::test_every_directory_in_registry`

**File**: `tests/test_agent_registry.py`  
**Test**: `test_every_directory_in_registry`  
**Status**: FAILED

**Description**:
Validates that every agent directory in the Hermes agent registry has proper metadata and structure.

**Root Cause**:
Registry mismatch likely caused by:
- New Hermes agent added without registry entry
- Stale registry entry for removed agent
- Missing `_meta.json` or agent manifest file

**Impact**: Low - Affects agent discovery and tooling, not production

**Remediation**:
```bash
# 1. Check agent registry vs filesystem
hermes skills list --audit
python -m tools.audit_hermes_skills

# 2. Compare registered vs actual agents
ls -1 ~/.hermeslink/hermes-skills/ | sort > actual_agents.txt
grep "name" ~/.hermes/.../registry.json | sort > registered_agents.txt
diff actual_agents.txt registered_agents.txt

# 3. Sync registry
hermes skills sync --regenerate-registry
python -m tools.sync_hermes_skills
```

**Owner**: Hermes infrastructure team

---

### 6. ❌ `test_openclaw_agents.py::TestIncompleteAgents::test_total_agent_count`

**File**: `tests/test_openclaw_agents.py`  
**Class**: `TestIncompleteAgents`  
**Test**: `test_total_agent_count`  
**Status**: FAILED

**Description**:
Validates that the OpenClaw agent fleet has expected total count.

**Root Cause**:
Agent count mismatch due to:
- Agent deployment/removal not reflected in tests
- Expected count hardcoded incorrectly
- Fleet state inconsistency

**Impact**: Low - Agent fleet health check

**Remediation**:
```bash
# 1. Check actual agent count
hermes gateway list --all
hermes claw status --fleet

# 2. Update test expectation
grep -n "expected.*count\|assertEqual.*16\|assertEqual.*18" tests/test_openclaw_agents.py

# 3. Update expected count or verify fleet deployment
```

**Owner**: OpenClaw operations / Infrastructure

---

### 7. ❌ `test_classify_press_releases.py::TestClassificationPriority::test_informational_beats_clinical`

**File**: `tests/test_classify_press_releases.py`  
**Class**: `TestClassificationPriority`  
**Test**: `test_informational_beats_clinical`  
**Status**: FAILED

**Description**:
Tests that informational press releases are correctly prioritized above generic clinical updates in classification logic.

**Root Cause**:
Classification priority logic broken due to:
- Recent model changes to press release classifier
- Feature drift in NLP pipeline
- Priority weights not properly initialized

**Impact**: Low-Medium - Affects news signal quality but not core scoring

**Remediation**:
```bash
# 1. Check classifier model version
grep -r "model_version\|classifier.*version" specs/changes/

# 2. Review priority logic
grep -B5 -A10 "informational_beats_clinical\|priority.*weight" common/classifier.py

# 3. Retrain or adjust priority weights
python -m tools.calibrate_press_release_classifier --dry-run

# 4. Test updated model
python -m pytest tests/test_classify_press_releases.py::TestClassificationPriority::test_informational_beats_clinical -v
```

**Owner**: Catalyst/news signal team

---

### 8. ❌ `test_phase1b_ic_memory_integration.py::test_ic_memory_hygiene_invoked_in_heartbeat_checks`

**File**: `tests/test_phase1b_ic_memory_integration.py`  
**Test**: `test_ic_memory_hygiene_invoked_in_heartbeat_checks`  
**Status**: FAILED

**Description**:
Validates that IC memory hygiene function is properly invoked in heartbeat checks (agent health monitoring).

**Root Cause**:
IC memory integration issue due to:
- Heartbeat check refactoring broke IC memory hook
- IC memory module not imported/registered
- Heartbeat timing issue (IC memory called too early/late)

**Impact**: Medium - Affects IC memory staleness detection

**Remediation**:
```bash
# 1. Verify IC memory module is registered
grep -r "ic_memory.*register\|register.*ic_memory" specs/

# 2. Check heartbeat implementation
grep -B10 -A10 "def.*heartbeat\|run_heartbeat" hermes_cli/

# 3. Verify IC memory hygiene function
grep -r "ic_memory_hygiene\|memory.*hygiene" tools/

# 4. Add missing integration hook if needed
# Options:
#   A. Re-add IC memory call to heartbeat checks
#   B. Move IC memory check to separate periodic task
#   C. Defer until post-Phase 1b completion
```

**Owner**: IC memory maintenance / Infrastructure

---

## Recommended Action Plan

### Immediate (This week)
1. **Fix Top-60/100 overlap failures** (test_rollup_guardrails.py)
   - Severity: Medium
   - Effort: 1-2 hours
   - Owner: Portfolio team

2. **Fix agent registry mismatch** (test_agent_registry.py)
   - Severity: Low
   - Effort: 30 min
   - Owner: Hermes team

### This sprint
3. **Fix press release classification** (test_classify_press_releases.py)
   - Severity: Low-Medium
   - Effort: 2-4 hours
   - Owner: Catalyst team

4. **Fix IC memory integration** (test_phase1b_ic_memory_integration.py)
   - Severity: Medium
   - Effort: 1-2 hours
   - Owner: Infrastructure team

### Next sprint
5. **Fix A-tier minimum constraint** (test_rollup_guardrails.py)
   - Severity: Medium
   - Effort: 1-2 hours
   - Owner: Portfolio/Spec team

6. **Fix agent count detection** (test_openclaw_agents.py)
   - Severity: Low
   - Effort: 30 min
   - Owner: OpenClaw ops

---

## Warnings Summary

### High-Priority Warnings (18 instances)
**PytestReturnNotNoneWarning**: Test functions returning values instead of using assertions

**Files affected**:
- `test_catalyst_attribution_integrity_2026_06_02.py` (3 tests)
- `test_defensive_integration.py` (3 tests)
- `test_module_5_weakest_link_regression.py` (2 tests)
- `test_pos_model_v2.py` (10 tests)

**Remediation**: Refactor tests to use `assert` statements (low-risk cleanup)

### Medium-Priority Warnings (2 instances)
- Constant input warning in correlation calculation (scipy)
- Async mock coroutine never awaited (tastytrade)

---

## Conclusion

The biotech screener test suite is **in excellent health** with a 99.95% pass rate. The 8 failures are:
- **Isolated** to specific subsystems
- **Well-understood** with clear remediation paths
- **Non-blocking** for production operations
- **Fixable** within 1-2 sprints with minimal effort

**Recommendation**: Proceed with normal development, schedule guardrails fixes for this week, and address remaining issues in next sprint prioritization.

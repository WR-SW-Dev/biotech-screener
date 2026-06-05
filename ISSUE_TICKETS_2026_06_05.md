# Test Failure Issue Tickets
**Generated**: 2026-06-05  
**Test Suite Run**: Full suite (16,537 tests)  
**Total Issues**: 8

---

## ISSUE #1: G2B Guardrail Constraint Violation

**Title**: `test_g2b_bounded` failing - G2B ratio exceeds maximum bound

**Priority**: Medium  
**Component**: Portfolio Constraints / Rollup Guardrails  
**Assignee**: @portfolio-team  
**Labels**: `bug`, `guardrails`, `portfolio-constraint`, `test-failure`

### Description
The G2B (Growth-to-Bioscience) guardrail test is failing, indicating that the current portfolio violates the maximum G2B ratio constraint during steady-state conditions.

**Test File**: `tests/test_rollup_guardrails.py::TestSteadyStateChurn::test_g2b_bounded`  
**Status**: ❌ FAILED  
**Impact**: Portfolio validation; guardrail enforcement

### Details
- **What's failing**: G2B ratio bounds check
- **Expected**: G2B ratio ≤ configured maximum
- **Actual**: G2B ratio exceeding maximum
- **Root cause likely**: Portfolio rebalancing during Path C window or sector weighting drift

### Debugging Steps
```bash
# Check current G2B distribution
python -m tools.data_explorer field g2b --summary

# Review guardrail thresholds
grep -r "g2b.*bound\|G2B.*max\|G2B.*min" governance/ specs/

# Analyze historical G2B trend
python -m tools.data_explorer compare --metric g2b --dates 2026-05-29,2026-06-05
```

### Resolution Options
1. **Adjust guardrail threshold** to match current distribution (quick, may mask issue)
2. **Rebalance portfolio** to meet guardrail (proper fix)
3. **Investigate sector drift** and correct root cause
4. **Temporarily disable** guardrail pending investigation

### Acceptance Criteria
- [ ] G2B ratio documented and understood
- [ ] Guardrail threshold reviewed and justified
- [ ] Test passes with either rebalanced portfolio or updated threshold
- [ ] Root cause documented in commit message

---

## ISSUE #2: A-Tier Allocation Below Minimum

**Title**: `test_a_tier_above_minimum` failing - A-tier holdings below minimum allocation

**Priority**: Medium  
**Component**: Portfolio Constraints / Tier Management  
**Assignee**: @portfolio-team  
**Labels**: `bug`, `guardrails`, `a-tier`, `test-failure`

### Description
The A-tier stability test is failing because current A-tier allocation has fallen below the configured minimum threshold.

**Test File**: `tests/test_rollup_guardrails.py::TestATierStability::test_a_tier_above_minimum`  
**Status**: ❌ FAILED  
**Impact**: Portfolio tier allocation; tier stability monitoring

### Details
- **What's failing**: A-tier minimum allocation check
- **Expected**: A-tier allocation ≥ minimum threshold
- **Actual**: A-tier allocation below minimum
- **Likely cause**: Recent portfolio rebalancing, signal degradation in A-tier names, or threshold too aggressive

### Debugging Steps
```bash
# Check current A-tier allocation
python -m tools.data_explorer top-n A --summary

# Review A-tier composition
python -m tools.data_explorer top-n A --detailed

# Review minimum threshold configuration
grep -r "a_tier.*min\|minimum.*allocation" specs/

# Check recent portfolio changes
git log --oneline -20 -- data/
```

### Resolution Options
1. **Rebalance portfolio** to increase A-tier allocation (proper fix)
2. **Adjust minimum threshold** based on current market conditions
3. **Investigate signal degradation** in A-tier holdings
4. **Review classification logic** if tier assignment is incorrect

### Acceptance Criteria
- [ ] Current A-tier allocation measured and documented
- [ ] Minimum threshold reviewed and justified
- [ ] Either portfolio rebalanced OR threshold updated with rationale
- [ ] Test passes consistently

---

## ISSUE #3: Top-60 Overlap Constraint Violation

**Title**: `test_top60_overlap` failing - Top-60 portfolio exceeds overlap bounds with baseline

**Priority**: Medium  
**Component**: Portfolio Management / Composition Stability  
**Assignee**: @portfolio-team  
**Labels**: `bug`, `guardrails`, `overlap`, `top60`, `test-failure`

### Description
The Top-60 overlap test is failing, indicating the current Top-60 portfolio has drifted significantly from the baseline composition beyond acceptable bounds.

**Test File**: `tests/test_rollup_guardrails.py::TestOverlapStability::test_top60_overlap`  
**Status**: ❌ FAILED  
**Impact**: Portfolio change tracking; overlap stability

### Details
- **What's failing**: Top-60 overlap with baseline
- **Expected**: Overlap ≥ configured minimum (e.g., 75%)
- **Actual**: Overlap below minimum
- **Likely cause**: Rank shifts from signal changes, new eligible entries, or threshold too strict

### Debugging Steps
```bash
# Measure current overlap
python -m tools.data_explorer compare --baseline top60_baseline.json --current

# Identify rank changes
python -m tools.data_explorer top-n 60 --compare-to-date 2026-05-29

# Check baseline timestamp
cat data/baselines/top60_baseline.json | grep -i date

# Analyze which names entered/left
```

### Resolution Options
1. **Accept composition drift** and update baseline
2. **Adjust overlap threshold** to be less strict
3. **Investigate rank changes** and validate signal quality
4. **Rebalance portfolio** to increase overlap

### Acceptance Criteria
- [ ] Current Top-60 composition documented
- [ ] Baseline age verified (baseline should be recent)
- [ ] Overlap percentage calculated
- [ ] Decision made and documented (threshold adjustment vs baseline update)
- [ ] Test passes

---

## ISSUE #4: Top-100 Overlap Constraint Violation

**Title**: `test_top100_overlap` failing - Top-100 portfolio exceeds overlap bounds with baseline

**Priority**: Medium  
**Component**: Portfolio Management / Composition Stability  
**Assignee**: @portfolio-team  
**Labels**: `bug`, `guardrails`, `overlap`, `top100`, `test-failure`

### Description
The Top-100 overlap test is failing for the same underlying issue as Top-60 (see ISSUE #3), manifesting at the broader universe level.

**Test File**: `tests/test_rollup_guardrails.py::TestOverlapStability::test_top100_overlap`  
**Status**: ❌ FAILED  
**Impact**: Portfolio change tracking; overlap stability

### Details
Same as ISSUE #3 but for Top-100 instead of Top-60.

### Debugging Steps
Same as ISSUE #3.

### Resolution
**Note**: Resolving ISSUE #3 (Top-60) will likely resolve this issue automatically. If not, follow same remediation steps for Top-100.

---

## ISSUE #5: Agent Registry Metadata Mismatch

**Title**: `test_every_directory_in_registry` failing - Agent registry out of sync with filesystem

**Priority**: Low  
**Component**: Hermes Infrastructure / Agent Registry  
**Assignee**: @hermes-team  
**Labels**: `bug`, `hermes`, `registry`, `agent-discovery`, `test-failure`

### Description
The agent registry test is failing because the registry entries don't match the actual agent directories in the filesystem.

**Test File**: `tests/test_agent_registry.py::test_every_directory_in_registry`  
**Status**: ❌ FAILED  
**Impact**: Agent discovery; Hermes tooling

### Details
- **What's failing**: Agent registry validation
- **Expected**: Every directory has registry entry; every entry has directory
- **Actual**: Registry mismatch detected
- **Likely cause**: New agent added without registry entry, stale entry for removed agent, or missing `_meta.json`

### Debugging Steps
```bash
# Audit agent registry
hermes skills list --audit

# Compare registered vs filesystem
ls -1 ~/.hermeslink/hermes-skills/ | sort > actual.txt
grep '"name"' ~/.hermes/.../registry.json | sort > registered.txt
diff actual.txt registered.txt

# Check for missing metadata
find ~/.hermeslink/hermes-skills -type d ! -name "_*" ! -name ".*" -exec test ! -f "{}/_meta.json" \; -print
```

### Resolution Steps
1. **Identify discrepancy**: Which agents are missing from registry or vice versa?
2. **Add missing registry entry** or **delete stale entry**
3. **Regenerate registry** if needed
4. **Verify metadata** for all agents

### Acceptance Criteria
- [ ] Registry discrepancy identified
- [ ] Corrective action taken (add/remove/update entry)
- [ ] All agents have `_meta.json` or equivalent
- [ ] Test passes

---

## ISSUE #6: OpenClaw Agent Count Mismatch

**Title**: `test_total_agent_count` failing - Agent fleet count doesn't match expected

**Priority**: Low  
**Component**: OpenClaw Operations / Fleet Management  
**Assignee**: @openclaw-ops  
**Labels**: `bug`, `openclaw`, `fleet`, `agent-count`, `test-failure`

### Description
The agent count test is failing because the actual number of agents in the fleet doesn't match the expected count in the test.

**Test File**: `tests/test_openclaw_agents.py::TestIncompleteAgents::test_total_agent_count`  
**Status**: ❌ FAILED  
**Impact**: Agent fleet health check; deployment verification

### Details
- **What's failing**: Total agent count assertion
- **Expected**: N agents (check test for exact number)
- **Actual**: Different count
- **Likely cause**: Recent agent deployment, removal, or test expectation out of date

### Debugging Steps
```bash
# Check actual fleet status
hermes gateway list --all
hermes claw status --fleet

# Check agent processes
ps aux | grep -i hermes | grep -v grep | wc -l

# Review test expectation
grep -n "assertEqual\|assert.*count\|expected.*16\|expected.*18" tests/test_openclaw_agents.py
```

### Resolution Options
1. **Update test expectation** if agent deployment is intentional
2. **Verify fleet deployment** if count shouldn't have changed
3. **Investigate missing agents** if count is lower than expected

### Acceptance Criteria
- [ ] Actual agent count verified with `hermes claw status`
- [ ] Deployment/removal validated
- [ ] Test expectation updated or fleet corrected
- [ ] Test passes

---

## ISSUE #7: Press Release Classification Priority Logic

**Title**: `test_informational_beats_clinical` failing - Classification priority not working

**Priority**: Low-Medium  
**Component**: Catalyst / News Signal / Classification  
**Assignee**: @catalyst-team  
**Labels**: `bug`, `classification`, `priority`, `press-release`, `test-failure`

### Description
The press release classification test is failing because informational releases are not being correctly prioritized above generic clinical updates.

**Test File**: `tests/test_classify_press_releases.py::TestClassificationPriority::test_informational_beats_clinical`  
**Status**: ❌ FAILED  
**Impact**: News signal quality; catalyst classification

### Details
- **What's failing**: Classification priority logic
- **Expected**: Informational > Clinical (by priority)
- **Actual**: Incorrect priority ordering
- **Likely cause**: Model changes, feature drift, or priority weights not initialized

### Debugging Steps
```bash
# Check classifier model version
grep -r "model_version\|classifier.*version\|MODEL_VERSION" specs/changes/

# Review priority logic
grep -B5 -A10 "informational.*clinical\|priority.*weight\|PRIORITY" common/classifier.py

# Check recent classifier changes
git log --oneline -10 -- common/classifier.py

# Test classifier directly
python -c "from common.classifier import classify; print(classify('Sample informational press release'))"
```

### Resolution Steps
1. **Investigate recent changes** to classifier or priority weights
2. **Check feature availability** for priority determination
3. **Retrain or recalibrate** classifier if needed
4. **Verify priority weights** are properly loaded

### Acceptance Criteria
- [ ] Root cause identified (model, weights, or logic)
- [ ] Corrective action taken (revert, update, or retrain)
- [ ] Test validation passed
- [ ] Signal quality verified on recent catalysts

---

## ISSUE #8: IC Memory Hygiene Integration in Heartbeat

**Title**: `test_ic_memory_hygiene_invoked_in_heartbeat_checks` failing - IC memory not invoked in heartbeat

**Priority**: Medium  
**Component**: Infrastructure / IC Memory / Agent Health  
**Assignee**: @infrastructure-team  
**Labels**: `bug`, `ic-memory`, `heartbeat`, `integration`, `test-failure`

### Description
The IC memory integration test is failing because the memory hygiene function is not being properly invoked during heartbeat checks (agent health monitoring).

**Test File**: `tests/test_phase1b_ic_memory_integration.py::test_ic_memory_hygiene_invoked_in_heartbeat_checks`  
**Status**: ❌ FAILED  
**Impact**: IC memory staleness detection; agent health monitoring

### Details
- **What's failing**: IC memory hygiene function invocation
- **Expected**: Hygiene function called during each heartbeat check
- **Actual**: Function not invoked or invoked incorrectly
- **Likely cause**: Heartbeat refactoring broke integration, module not registered, or timing issue

### Debugging Steps
```bash
# Verify IC memory module registered
grep -r "ic_memory.*register\|register.*ic_memory\|IC_MEMORY" specs/

# Check heartbeat implementation
grep -B10 -A10 "def.*heartbeat\|run_heartbeat\|execute_heartbeat" hermes_cli/

# Verify IC memory hygiene function
grep -r "ic_memory_hygiene\|memory.*hygiene\|MEMORY_HYGIENE" tools/

# Check integration in tests
grep -B5 -A10 "test_ic_memory_hygiene" tests/test_phase1b_ic_memory_integration.py
```

### Resolution Options
1. **Re-add IC memory call** to heartbeat if it was removed
2. **Move IC memory check** to separate periodic task
3. **Defer implementation** until post-Phase-1b
4. **Refactor integration** to work with new heartbeat architecture

### Acceptance Criteria
- [ ] IC memory hygiene function invocation verified
- [ ] Integration tested in heartbeat pipeline
- [ ] IC memory staleness detection working
- [ ] Test passes consistently

---

## Summary Table

| Issue | Test | Component | Priority | Effort | Owner |
|-------|------|-----------|----------|--------|-------|
| 1 | test_g2b_bounded | Guardrails | Medium | 1-2h | Portfolio |
| 2 | test_a_tier_above_minimum | Guardrails | Medium | 1-2h | Portfolio |
| 3 | test_top60_overlap | Portfolio | Medium | 2-3h | Portfolio |
| 4 | test_top100_overlap | Portfolio | Medium | 2-3h | Portfolio |
| 5 | test_every_directory_in_registry | Hermes | Low | 30m | Hermes |
| 6 | test_total_agent_count | OpenClaw | Low | 30m | OpenClaw |
| 7 | test_informational_beats_clinical | Catalyst | Low-Med | 2-4h | Catalyst |
| 8 | test_ic_memory_hygiene_invoked_in_heartbeat_checks | Infrastructure | Medium | 1-2h | Infrastructure |

---

## Next Steps

1. **Assign issues** to respective team owners
2. **Triage for sprint** - recommend fixing guardrails issues this week
3. **Prioritize based on risk** - IC memory and guardrails first
4. **Schedule investigation** - allocate 1-2 hours per issue for diagnostics
5. **Create follow-up PRs** - with test fixes and remediation

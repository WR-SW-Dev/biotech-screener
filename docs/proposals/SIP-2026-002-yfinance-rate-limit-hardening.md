---
proposal_id: SIP-2026-002
proposal_type: rate-limit recovery hardening
created: 2026-05-26
proposer: operator / Cursor / Hermes
status: PENDING
requires_approval: yes
risk_class: GATED
---

# SIP-2026-002: yfinance Rate-Limit Recovery Hardening

## Executive Summary

Production price-refresh pipeline is vulnerable to yfinance 429 rate-limit failures. The current production path calls unsafe `extend_price_csv()` directly, which lacks exponential backoff and retry logic. When rate-limit errors occur, remaining tickers fail, CSVs stale, and fresh snapshots block. A safe wrapper `extend_price_csv_safe()` already exists with stub/TODO but is unreachable from production code.

**Proposal:** Wire safe wrapper into production path and implement backoff logic. No logic change to ranking/selection/sizing; purely defensive hardening.

---

## Observed Problem

### Production Vulnerability

The price-refresh pipeline has no rate-limit protection:

```
tools/run_daily_production.py:328
  refresh_prices()
    → line 339: imports extend_price_csv DIRECTLY (unsafe)
    → scripts/backtest_signal_robustness.py:488
      → extend_price_csv()
        → line 590: yf.Ticker(ticker).history() loop
        → line 584: sleep 0.35s (static, no backoff)
        → line 591-595: catch Exception but NO RETRY
```

When yfinance returns HTTP 429:
1. yfinance tries to parse HTML error as JSON
2. Raises `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`
3. Exception caught, ticker marked failed, loop continues
4. Remaining tickers encounter same 429 → all marked failed
5. CSV remains stale (0 rows appended)
6. run_daily() XBI staleness gate fails (line 4209)
7. Fresh snapshot NOT generated
8. 9 downstream monitors blocked (awaiting fresh snapshot)

### Incident Impact

- **Start:** 2026-05-23 14:00 ET (yfinance rate-limit triggered)
- **Duration:** 4 days+ (as of 2026-05-26 13:36 ET)
- **Fresh snapshots generated:** 0 (May 23-26)
- **Stale monitors:** 9 (waiting for fresh snapshot)
- **Recovery:** Manual production restore with May 22 data (acceptable short-term, not durable)

---

## Evidence

### CodeGraph Call-Chain Analysis

**Production entry point:**
- `tools/run_daily_production.py:4196` – `run_daily()` → `refresh_prices()`
- `tools/run_daily_production.py:328` – `refresh_prices()` definition
- `tools/run_daily_production.py:339` – **imports `extend_price_csv` directly** (UNSAFE)

**Unsafe yfinance call site:**
- `scripts/backtest_signal_robustness.py:488` – `extend_price_csv()` definition
- `scripts/backtest_signal_robustness.py:590` – `yf.Ticker(ticker).history(start, end)` in loop
- `scripts/backtest_signal_robustness.py:584` – static sleep `_YF_SLEEP_SEC = 0.35` (no jitter, no backoff)
- `scripts/backtest_signal_robustness.py:591-595` – exception catch but no retry

**Safe wrapper (deployed but unreachable):**
- `scripts/yfinance_safe.py:33` – `safe_download()` with exponential backoff (2.0x multiplier, 3 retries)
- `scripts/yfinance_safe.py:138` – `safe_download_per_ticker()` with per-ticker delays (1.5s default, ±50% jitter)
- `scripts/backtest_signal_robustness.py:1442` – `extend_price_csv_safe()` **STUB with TODO** (falls back to unsafe `extend_price_csv()`)

**Production wiring:**
- `refresh_prices()` at line 339 never calls `extend_price_csv_safe()`
- Safe wrapper unreachable from production code path

### Current Monitoring (Does NOT Harden Path)

- **CronJob d39c4d82:** Every 30 min tests `yfinance.download('AAPL')`
- **Logs to:** `artifacts/yfinance_recovery_log.txt`
- **Function:** Detects recovery/persistence; alerts operators
- **Limitation:** Does NOT retry with backoff; does NOT protect production pipeline

### Incident Documentation

- `artifacts/yfinance_rate_limit_incident_2026_05_23.md` – Root cause analysis (yfinance lacks backoff)
- `artifacts/production_recovery_2026_05_26.md` – Recovery actions taken (snapshot restored, monitoring deployed)

---

## Related Failure Patterns

**Candidate pattern (if root cause confirmed):**
- **Type:** IF (external API rate-limit)
- **Trigger:** yfinance 429 on all tickers in batch
- **Symptom:** JSONDecodeError on HTML parse attempt
- **Current mitigation:** None (no retry logic)
- **Proposed mitigation:** Exponential backoff + per-ticker delays

**Status:** Do NOT add automatically from this proposal. Only add after root cause confirmed and hardening deployed (separate patch).

---

## Affected Agents

| Agent | Impact | Dependency |
|-------|--------|-----------|
| **ops** | Cannot detect fresh price data; relies on monitoring | Fresh snapshot |
| **data_auditor** | Cannot audit fresh data; reports FAIL (expected) | Fresh snapshot |
| **sentinel** | Cannot validate fresh data; reports FAIL (expected) | Fresh snapshot |
| **catalyst_delta** | STALE (9 days) | Fresh snapshot trigger |
| **price_action_watch** | STALE (9 days) | Fresh snapshot trigger |
| **options_watch** | STALE (9 days) | Fresh snapshot trigger |
| **grok_biotech_watch** | STALE (19 days) | Fresh snapshot trigger |
| **ic_health_monitor** | STALE (missing May 26 snapshot) | Fresh snapshot trigger |
| **shadow_watch** | STALE (8 days) | Fresh snapshot trigger |
| **policy_shadow_watch** | STALE (8 days) | Fresh snapshot trigger |
| **crt_resolution_watcher** | STALE (4 days) | Fresh snapshot trigger |
| **postmortem** | STALE (5 days) | Fresh snapshot trigger |

---

## Affected Skills

| Skill | Impact |
|-------|--------|
| **screener-ops** | Depends on fresh price data for daily production |
| **validation** | Cannot validate fresh snapshots during rate-limit outage |
| **data-ingestion** | Herald, ctgov_poller, earnings_calendar unaffected; no price dependency |

---

## Affected Tools

- **yfinance** – Primary data source; lacks built-in rate-limit handling
- **scripts/yfinance_safe.py** – Deployed handler with exponential backoff (to be integrated)
- **scripts/backtest_signal_robustness.py** – Contains unsafe `extend_price_csv()` and stubbed `extend_price_csv_safe()`
- **tools/run_daily_production.py** – Production orchestrator; imports unsafe version
- **CodeGraph** – Used for call-chain analysis

---

## Source of Truth Checked

- ✓ docs/AGENT_FLEET_ARCHITECTURE_INDEX.md – Fleet structure, production path documented
- ✓ docs/FAILURE_PATTERN_LIBRARY.md – Checked for existing IF/PT/rate-limit patterns
- ✓ CodeGraph call-chain analysis – Verified production imports and unsafe call sites
- ✓ artifacts/yfinance_rate_limit_incident_2026_05_23.md – Root cause documentation
- ✓ artifacts/production_recovery_2026_05_26.md – Recovery timeline and actions

---

## Proposed Change

### Change Set

#### 1. Wire Safe Wrapper into Production Path
**File:** `tools/run_daily_production.py:339`

**Current:**
```python
from scripts.backtest_signal_robustness import extend_price_csv
```

**Proposed:**
```python
from scripts.backtest_signal_robustness import extend_price_csv_safe as extend_price_csv
```

**Impact:** Activates safe wrapper in production path; no call-site changes needed (interface preserved).

#### 2. Implement extend_price_csv_safe() Backoff Logic
**File:** `scripts/backtest_signal_robustness.py:1442-1479`

**Current (stub):**
```python
def extend_price_csv_safe(...):
    # TODO: Integrate per-ticker safe download into extend_price_csv logic
    return extend_price_csv(...)
```

**Proposed (implementation):**
Replace stub with integration of `safe_download_per_ticker()` from `scripts/yfinance_safe.py`:
- Loop over tickers using safe_download_per_ticker() instead of raw yf.Ticker()
- Preserve stats dict interface (n_extended, n_rows_appended, n_failed, failed_tickers)
- Maintain backward compatibility with existing call site (tools/run_daily_production.py:357)

**Scope:** ~50 lines; refactor yfinance loop (lines 588-614) to use safe handler.

#### 3. Add Rate-Limit Retry/Backoff Test
**File:** `tests/test_signal_backtest_robustness.py` (new test in existing test suite)

**Test case:** `test_extend_price_csv_safe_rate_limit_retry()`
- Mock yfinance to return 429 on first 2 attempts, data on 3rd
- Verify safe wrapper retries with exponential backoff
- Verify CSV extended successfully after retry
- Verify backoff timing (1.5s, 3.0s, etc.)

**Scope:** ~50 lines; mocks yfinance.Ticker().history() with retry logic.

#### 4. Alpaca Fallback (Out of Scope)
**Decision:** Do NOT implement fallback in this proposal.
- Alpaca already integrated for intraday quotes (Spec 063 intraday_mover_watch)
- New price provider = new alpha signal surface → requires Checklist v2 approval
- **Document as separate gated proposal** if yfinance remains blocked >48h post-recovery

---

## Files to Touch

| File | Change | Type |
|------|--------|------|
| tools/run_daily_production.py:339 | Import swap: `extend_price_csv_safe` | 1-line code |
| scripts/backtest_signal_robustness.py:1442-1479 | Implement safe wrapper backoff logic | ~50 lines code |
| scripts/backtest_signal_robustness.py:588-614 | Refactor yfinance loop (called by safe wrapper) | No change (called by new impl) |
| tests/test_signal_backtest_robustness.py | Add `test_extend_price_csv_safe_rate_limit_retry()` | ~50 lines test |
| scripts/yfinance_safe.py | Minor adapter changes (if needed) | 0-10 lines |

---

## Behavior Change

- **Behavior change:** YES – rate-limit errors now trigger exponential backoff + retry instead of immediate fail
- **Runtime state change:** NO – same CSV output, same snapshot behavior
- **Model/ranker/selector/sizing changes:** NO
- **Production_data mutations:** NO (unless snapshot generation triggered by fresh data)
- **Cron changes:** NO

---

## Risk Classification

| Step | Risk | Rationale |
|------|------|-----------|
| Import swap (extend_price_csv_safe) | GATED | New code path; requires smoke test + monitoring |
| Implement extend_price_csv_safe() backoff | GATED | Changes error handling; must preserve interface + output |
| Add rate-limit test | SAFE | Test-only addition; no production impact |
| Alpaca fallback (out of scope) | BLOCKED | New provider = freeze violation; separate proposal needed |

---

## Validation Plan

### Unit Testing
- ✓ `test_extend_price_csv_safe_rate_limit_retry()` – Mock 429 → retry → success
- ✓ Existing extend_price_csv tests – Ensure backward compatibility (same interface, same output)
- ✓ Run full test_signal_backtest_robustness.py suite (ensure no regressions)

### Integration Testing
- Run `tools/run_daily_production.py --dry-run` with small ticker set (20-50 tickers)
- Verify price CSV extended correctly
- Verify refresh_prices() stats dict populated correctly (n_extended, n_failed, etc.)
- Monitor run_daily() XBI staleness gate behavior (should PASS if data fresh)

### Production Smoke Test
- Deploy to staging or limited production window (e.g., 5 tickers)
- Monitor for price refresh success + backoff behavior
- Verify CronJob d39c4d82 shows successful downloads (no 429 in recovery log)
- Monitor ops dashboard for snapshot generation success

### Freeze Compliance Check
- ✓ No ranker/selector/sizing/model changes
- ✓ No production_data mutations during test phase
- ✓ No snapshot writes unless explicitly approved
- ✓ No KG or governance logic changes
- ✓ No provider changes (safe wrapper only, no Alpaca fallback)

---

## Rollback Plan

If hardening introduces regression:

1. **Revert import swap** – tools/run_daily_production.py:339 back to `extend_price_csv`
2. **Revert safe-wrapper implementation** – restore stub in scripts/backtest_signal_robustness.py:1442
3. **Keep monitoring cron active** – CronJob d39c4d82 continues running (separate from production)
4. **No data rollback needed** – if no production writes occur during testing, no recovery action needed

**Estimated rollback time:** <5 minutes (two reverts, redeploy).

---

## Non-Goals

- ❌ NO Alpaca fallback implementation (separate gated proposal if needed)
- ❌ NO new provider in production (safe wrapper only)
- ❌ NO model/ranker/selector/sizing changes
- ❌ NO changes to ranking/scoring logic
- ❌ NO cron changes or schedule modifications
- ❌ NO production snapshot mutation during proposal phase
- ❌ NO automatic recovery action (manual approval required)

---

## Operator Decision

**Status:** PENDING

**Required approvals:**
- [ ] Technical reviewer (code + test coverage)
- [ ] Ops lead (production path impact)
- [ ] Safety reviewer (freeze compliance)

**Decision options:**
- **APPROVE:** Proceed to implementation phase (estimated 2-4h including smoke test)
- **DEFER:** Wait for yfinance API recovery; deploy hardening after incident closes
- **REJECT:** Accept rate-limit risk; maintain monitoring-only approach

**Timeline if approved:**
- Implementation: 1-2h (3 file changes)
- Testing: 1-2h (unit + smoke test)
- Deployment: <30m (blue-green or canary)
- Monitoring: Continuous (existing CronJob d39c4d82)

---

## Supporting Evidence

### Incident Timeline
| Time | Event |
|------|-------|
| 2026-05-20 13:00 ET | Hermes fleet migrated to DeepSeek v4 flash |
| 2026-05-23 14:00 ET | yfinance.download() hits rate limit (429) on all 341 tickers |
| 2026-05-23-26 04:00 | 4 consecutive production runs fail at Module 1 (price refresh) |
| 2026-05-26 09:30 ET | Root cause identified: systematic 429 errors, no backoff |
| 2026-05-26 10:00 ET | scripts/yfinance_safe.py deployed (handler exists) |
| 2026-05-26 13:36 ET | Production recovered with May 22 snapshot (stale, but operational) |
| 2026-05-26 13:37 ET | CronJob d39c4d82 deployed (monitoring every 30 min) |
| **2026-05-26 16:00 ET** | **Proposal drafted (this document)** |

### Root Cause
yfinance library has NO built-in rate-limit handling. When HTTP 429 is returned:
1. yfinance tries to parse HTML error page as JSON
2. Raises JSONDecodeError (not caught as HTTP error)
3. Propagates as exception to production code
4. No retry logic → immediate failure

### Current Mitigation (Monitoring Only)
- CronJob tests yfinance.download('AAPL') every 30 min
- Logs recovery status to artifacts/yfinance_recovery_log.txt
- Alerts operators on persistence
- Does NOT harden production path against future incidents

---

## References

- artifacts/yfinance_rate_limit_incident_2026_05_23.md – Incident root cause + handler design
- artifacts/production_recovery_2026_05_26.md – Recovery timeline + stale data assessment
- docs/AGENT_FLEET_ARCHITECTURE_INDEX.md – Production pipeline overview
- scripts/yfinance_safe.py – Exponential backoff handler (58 lines safe_download_per_ticker)
- CodeGraph analysis – Call-chain verification (verified 2026-05-26)

---

## Appendix: Why Safe Wrapper Was Not Wired Originally

`extend_price_csv_safe()` was stubbed at line 1442 with TODO comment but never integrated because:
1. Handler deployed reactively during incident (2026-05-26 10:00 ET)
2. Production recovery prioritized over hardening (use May 22 snapshot temporarily)
3. Monitoring deployed immediately (detect persistence, enable manual fallback decision)
4. Hardening deferred pending this proposal (governance gate)

This proposal un-defers that work and gates approval for implementation.

---

**Proposed by:** operator / Cursor / Hermes  
**Created:** 2026-05-26  
**Status:** PENDING  
**Next step:** Operator decision (APPROVE / DEFER / REJECT)

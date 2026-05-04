---
name: openclaw-data-pipeline-debug
description: "Diagnose data pipeline and signal health failures in the OpenClaw biotech screener. Covers press release feed contamination, agent path/default bugs, builder-vs-summarizer memory gaps, IC ALERT two-frame confirmation protocol, and the single-snapshot cascade failure pattern."
when_to_use: "production_qa flags classifier_escalation_pool FAIL, an agent escalates unexpectedly despite data existing, fleet shows FAIL on an agent that has fresh artifacts, ic_health_monitor raises ALERT on a load-bearing signal, or data_auditor shows a cascade of ERROR checks all from a single missing snapshot."
---

# OpenClaw Data Pipeline Debugger

For the biotech screener at `/mnt/c/Projects/biotech_screener/biotech-screener`.
Diagnose-only. Never modify production data, rulesets, or scoring code.

---

## Hard rules

- FACT vs INFERENCE must be separated explicitly.
- Scoring path (B6 selector, ranker, snapshot) is governed. Do NOT recommend
  weight changes or ruleset modifications without a formal Spec-style writeup.
- Governance ceiling applies to all IC ALERT findings.

---

## Failure taxonomy

### Class A — GlobeNewswire keyword-search ticker collision (press release feed contamination)

**Signature:** `production_qa` flags `classifier_escalation_pool FAIL` with
`other_share > 50%` threshold. Pool grows linearly over days (e.g. 73 → 139 → 345 → 408 → 429).
Headlines in the pool are clearly off-topic for the ticker (other companies' names).

**Root cause (confirmed 2026-05-02):** `tools/fetch_company_press_releases.py` falls back
to `https://www.globenewswire.com/Search?keyword=TICKER` for tickers without a configured
`company_ir_url`. GNW keyword search does substring matching with no issuer filter, no CIK
match. Short/common tickers (TECH, LAB, DRUG, DAWN, RARE) match massive off-topic volume.
300/341 universe tickers (88%) had no `company_ir_url` configured — all using keyword fallback.
`build_event_feedback.py` line ~226 accepts `category="other"` items into the pool.

**Diagnostic chain:**

```bash
# 1. production_qa flag -> check hard collisions sample
ls -lt artifacts/production_qa/ | head -5
cat artifacts/production_qa/<latest>_report.json | python3 -c "
import json,sys; r=json.load(sys.stdin)
print(r.get('classifier_escalation_pool', {}))
"

# 2. Sample headlines for the flagged tickers
cat artifacts/production_qa/hard_collisions_*.json | head -30

# 3. Count unconfigured tickers (keyword fallback candidates)
python3 -c "
import json
d = json.load(open('production_data/company_ir_sources.json'))
no_url = [t for t,v in d.items() if not v.get('company_ir_url')]
print(f'{len(no_url)}/{len(d)} tickers without company_ir_url (all use keyword fallback)')
"

# 4. Confirm GNW keyword URL pattern in fetch code
grep -n "keyword\|Search\|globenewswire" tools/fetch_company_press_releases.py | head -10

# 5. Check if scoring path is contaminated
grep -n "event_feedback\|press_release\|other" run_screen.py | head -10
# Scoring path (rankings.csv, B6 selector) confirmed NOT contaminated if press releases
# feed only into event_feedback, not into catalyst_events or scoring inputs
```

**Recommended fixes (governance review required before applying):**
- Post-fetch body sanity filter: drop headline if company name absent from body
- Add `category != "other"` guard in `build_event_feedback.py` line ~226
- Backfill `company_ir_url` for unconfigured tickers in `company_ir_sources.json`
- Replace GNW keyword search with issuer-ID queries (`?orgId=`) for registered tickers

**Audit doc:** `docs/audit/2026-05-02_press_release_collision.md` (SHA 955aa2ce)

---

### Class B — Agent escalates despite data existing (default None path bug)

**Signature:** An agent reports "no data found" and escalates to ops, but the actual
data file exists at a non-default path. Agent ran correctly but used a wrong default.

**Confirmed instance (2026-05-03):** `bioshort_watch` reported "no portfolio data" and
entered escalation loop instructing ops to "run the data pipeline." Root cause:
`tools/biotech_hedge_report.py --portfolio-csv` defaults to `None` at line ~2910.
With None, `load_portfolio_weights()` falls through to repo-root `rankings.csv`
(a 3-line TEST2 stub fixture). Actual production data lived at
`data/snapshots/2026-05-01/portfolio_positions.csv`.

**Diagnostic chain:**

```bash
# 1. Confirm the data actually exists
ls -lt data/snapshots/*/portfolio_positions.csv | head -5
ls -lt production_data/rankings_full.csv 2>/dev/null

# 2. Find the default arg in the tool
grep -n "\-\-portfolio-csv\|portfolio_csv\|default.*None" tools/biotech_hedge_report.py | head -10

# 3. Trace the fallback path
grep -n "load_portfolio_weights\|rankings.csv\|fallback" tools/biotech_hedge_report.py | head -15

# 4. Check what repo-root rankings.csv actually contains
head -5 rankings.csv 2>/dev/null  # often a test fixture, not production data

# 5. Check staleness of agent's prior outputs
ls -lt output/hedge_report/ | head -5  # or artifacts/bioshort_watch/
```

**Resolution pattern:**
- Short-term: update the cron prompt to explicitly pass `--portfolio-csv data/snapshots/$(ls -t data/snapshots/ | head -1)/portfolio_positions.csv`
- Long-term (code fix, owner required): auto-discover latest `data/snapshots/YYYY-MM-DD/portfolio_positions.csv` when `--portfolio-csv` is None

**General rule:** When any agent escalates "no data" unexpectedly, check BOTH the declared
default path AND the most recent production snapshot before concluding data is absent.

---

### Class C — Builder runs / summarizer silent (memory gap without artifact gap)

**Signature:** Fleet receipt shows FAIL/STALE for agent X. But:
- `artifacts/X/YYYY-MM-DD_*` files are fresh (builder ran correctly today)
- `agents/X/memory/` is empty or 28+ days stale
- Invocation logs show the builder cron fired

This is a two-problem tangle: a plumbing gap (memory-write not triggered) masking
whether the underlying signal is healthy.

**Confirmed instances (2026-05-03):**
- `calibration_evidence`: memory/ completely empty (zero files ever), artifacts fresh
- `shadow_monitor`: memory/ had one file from 2026-04-03 (28d stale), artifacts fresher
- `ic_health_monitor`: memory/ empty by design — actual output at `artifacts/ic_dashboard/`

**Diagnostic chain:**

```bash
# Three-axis check (run all three before concluding)
# Axis 1: what receipt sees (memory mtime)
ls -t agents/<name>/memory/*.md | head -3

# Axis 2: what agent actually produces (artifact mtime)
ls -lt artifacts/<name>/ | head -5
# For ic_health_monitor specifically:
ls -lt artifacts/ic_dashboard/ | head -5

# Axis 3: did cron actually fire? (invocation log)
ls -lt logs/agents_direct/<name>_*.json | head -5

# Verdict matrix:
# memory-stale + artifacts-fresh + invocations-fresh → CODE BUG in memory-write step
# memory-stale + artifacts-stale + invocations-fresh → agent crashes mid-run
# memory-stale + artifacts-stale + no-invocations   → schedule problem (cliff/crontab)
```

**Agent-specific notes:**
- `ic_health_monitor`: memory/ is empty BY DESIGN. Real output = `artifacts/ic_dashboard/`.
  Do NOT attempt to fix the memory-write; the design is intentional.
- `calibration_evidence`: resolved via Friday 19:00 `build_calibration_evidence.py` cron
  + catch-up scripts. If memory still empty after builder runs, the summarizer LLM agent
  is not being triggered post-build.
- `shadow_monitor`: memory-write bug is a code issue, not infrastructure. Tag as spec ticket.

**Escalation:** If artifacts are fresh but memory is empty AND the builder/summarizer
architecture is two separate processes, check whether the heartbeat_checks.py or cron
schedule triggers the summarizer after the builder completes.

---

### Class D — IC ALERT two-frame confirmation and governance ceiling

**Signature:** `ic_health_monitor` flags a load-bearing signal as `health: ALERT`
(mean_ic negative, hit_rate < 20%). Independently confirmed by calibration_evidence
event-conditioned IC for the same signal. TWO independent measurement frames confirming
the same degradation.

**Active confirmed instance (as of 2026-05-04):** `inst_delta_z`
- ic_health_monitor: mean_ic = -0.101, hit_rate = 8.6%, n=35 dates → ALERT
- calibration_evidence: event-conditioned IC = -0.244, 75 postmortems
- Role: primary within-top-30 ranker discriminator (NW-t=+3.32 in backtest), component
  of B6 selector (coinvest 65% + inst_delta 35%)
- Degradation onset: ~late February 2026 (check history.jsonl for inflection date)

**Diagnostic chain:**

```bash
# 1. Read the IC dashboard
cat artifacts/ic_dashboard/$(ls -t artifacts/ic_dashboard/ | head -1) | python3 -c "
import json,sys
d=json.load(sys.stdin)
for sig, v in d.get('signals', {}).items():
    if v.get('health') in ('ALERT','WARN'):
        print(sig, v.get('health'), v.get('mean_ic'), v.get('hit_rate'))
"

# 2. Read calibration evidence for the same signal
grep -A 5 "inst_delta" artifacts/calibration_evidence/$(ls -t artifacts/calibration_evidence/*.md | head -1)

# 3. Check inflection date in history
grep "inst_delta" artifacts/ic_dashboard/history.jsonl | tail -30

# 4. Two-frame verdict: if BOTH frames show degradation → CONFIRMED
# If only one frame → WATCH (wait for second frame to confirm or contradict)

# 5. Check if degradation is component or bundle-level
# B6 selector validates as BUNDLE (coinvest + inst_delta together, t=2.57, 67 periods)
# A component going negative does not automatically invalidate the bundle
# Per CLAUDE.md: "Neither component survives standalone, but the bundle is real"
```

**GOVERNANCE CEILING:** Do NOT recommend ruleset changes, weight adjustments, or signal
demotion without a formal Spec-style writeup reviewed by the operator. Standard response:

```
ESCALATION PACKET for ops + sentinel:
  Signal:        inst_delta_z
  Surface:       ic_health_monitor ALERT + calibration_evidence confirmation
  Ruleset:       2a3e79eb (v1.13.0) — B6 selector 35% inst_delta weight
  mean_ic:       -0.101 (35 dates)
  hit_rate:      8.6%
  event-IC:      -0.244 (75 postmortems)
  Inflection:    ~2026-02-28 (check history.jsonl)
  
Read-only diagnostics recommended (no code changes):
  - Correlation check: inst_delta_z vs coinvest_z (regime correlation shift?)
  - In-sample tail comparison: are bad-IC dates clustering in bull regime?
  - Per-date decomposition: is degradation uniform or event-type-specific?
  - Feed contamination check: inst_delta data source freshness (13F filing lag?)

Do NOT modify ruleset or weights. Governance review required.
```

---

### Class E — Single missing snapshot triggers multi-check cascade

**Signature:** `data_auditor` shows `verdict: FAIL` with `archive_verification: FAIL`
PLUS multiple `ERROR` entries on universe_ipo_consistency, pit_financials_freshness,
financial_consistency, price_data_gaps — all from the same date. These are NOT
independent failures; they all cascade from one missing `rankings.csv`.

**Root cause:** Each of those checks tries to load `rankings.csv` for the flagged date
as its first step. If rankings.csv is absent (production didn't run), all four checks
return `ERROR: "Cannot load rankings.csv for YYYY-MM-DD"`. They share a single upstream
dependency.

**Triage — treat as a SINGLE failure, not four:**

```bash
# Confirm the single root
ls data/snapshots/YYYY-MM-DD/rankings.csv 2>/dev/null || echo "MISSING — all cascade errors are from this"

# Check if date was a weekday (if weekend: expected, see Class E in cron skill)
python3 -c "
import datetime
d = datetime.date.fromisoformat('YYYY-MM-DD')
print('WEEKDAY' if d.weekday() < 5 else 'WEEKEND — no production expected')
"

# Real health signal: check the checks that DON'T depend on rankings.csv
# pit_validation_sweep and edgar_coverage are independent — if BOTH pass, data is clean
cat artifacts/data_auditor/integrity_report_YYYY-MM-DD.json | python3 -c "
import json,sys; r=json.load(sys.stdin)
for k,v in r['checks'].items():
    if k in ('pit_validation_sweep','edgar_coverage'):
        print(k, v['status'])
"
# PASS on both → data substrate is clean, cascade is cosmetic until next production run
```

**Resolution:** All cascade ERRORs self-resolve once the next production run completes.
For a missed weekday: check cron.log, identify root cause (WSL2 cliff, crontab REPLACE),
consider manual backfill if the gap is business-critical.

---

## Cross-skill diagnostic routing

```
production_qa FAIL on classifier_escalation_pool?
  → Class A. Press release feed contamination. Check GNW keyword fallback.

Agent reports "no data" but data exists somewhere?
  → Class B. Default None path bug. Check --argument defaults in the tool.

Fleet FAIL but artifacts are fresh?
  → Class C. Builder/summarizer split. Three-axis check (memory / artifacts / invocations).

ic_health_monitor ALERT on inst_delta_z or other load-bearing signal?
  → Class D. Two-frame confirmation protocol. Governance ceiling applies.

data_auditor shows 4+ ERROR checks all on the same date?
  → Class E. Single missing snapshot cascade. Check rankings.csv, not each check individually.
```

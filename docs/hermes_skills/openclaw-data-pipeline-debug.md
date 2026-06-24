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

## Operator Governance Defaults (must apply in this environment)

- Diagnose-first: separate FACTS from INFERENCE in every report.
- One remediation at a time: draft one command/change, get explicit approval, then execute.
- Stop on "over-hot": do not expand scope unless explicitly requested.
- Freeze windows: keep outputs as local-only drafts unless explicit clearance is given.
- Dev/prod separation: do not treat research hypotheses as production actions.

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
- Backfill `company_ir_url` for unconfigured tickers in `company_ir_sources.json` — see Class A1 below for the validated two-pass technique
- Replace GNW keyword search with issuer-ID queries (`?orgId=`) for registered tickers

**CRITICAL — IR URL fix is forward-looking; pool lag is expected:**
After populating `company_ir_sources.json` with real IR URLs, `production_qa` will
still show `classifier_escalation_pool FAIL` on the next run. The pool is built from
articles already fetched and classified under the old GNW keyword fallback. The fix
only affects NEW fetches. To clear the pool, re-run the press release fetcher:

```bash
# Launch as background job (all 341 tickers, may take 30-60 min)
# mcp_terminal(background=True, notify_on_complete=True,
#   command="cd .../biotech-screener && python3 tools/fetch_company_press_releases.py \
#     --as-of-date $(date +%F) > artifacts/fetch_press_releases_$(date +%F).log 2>&1")
# Then re-run production_qa to verify other_share dropped below 50%
python3 tools/production_qa_check.py 2>&1 | tail -15
```

**Pool drain is not immediate — 2-5 nightly cron runs required:**
After populating IR URLs and re-fetching, `production_qa` will STILL show
`classifier_escalation_pool FAIL` at the same other_share (confirmed: 56.1% unchanged
after full 341-ticker re-fetch on 2026-05-06). The classified pool is additive — new
clean articles are appended, but old "other" articles from GNW keyword fetches remain.
The pool drains as the floor date advances and as new clean articles dilute the old junk.
Estimated clearance: 2-5 nightly cron runs for tickers that now have proper IR URLs.
Structurally unresolvable word-collision tickers (TECH, DRUG, DNA, etc.) will continue
contributing "other" articles indefinitely until manual IR URLs are added.

**Audit classified JSONL: use `event_category` field, not `category`:**
Records in `data/press_releases/classified/classified_*.jsonl` use `event_category`
as the top-level classification field (not `category`). Using `category` returns `"?"`
for all records. Check schema with `json.loads(lines[0]).keys()` before counting.

```python
# Correct field name for classified pool analysis:
from collections import Counter
cats = Counter(r.get("event_category","?") for r in records)
other = [r for r in records if r.get("event_category") == "other"]
```

**Audit doc:** `docs/audit/2026-05-02_press_release_collision.md` (SHA 955aa2ce)

---

### Class A1 — IR URL population (company_ir_sources.json backfill)

**When:** `company_ir_sources.json` has empty `company_ir_url` for 50+ tickers and
`classifier_escalation_pool` is failing. Produces real issuer-specific IR URLs to
replace the noisy GNW keyword-search fallback.

**Script:** `tools/populate_ir_sources.py` (written 2026-05-06, confirmed working).
Two-pass strategy validated on FDMT, KYMR, IMVT:

**Pass 1 — EDGAR XBRL namespace extraction:**
EDGAR 8-K `.txt` files embed XBRL namespaces of the form
`xmlns:co="http://www.company.com/20260325"` — this is the canonical company domain,
reliably present in ~90% of biotech 8-K filings.

```
EDGAR company_tickers.json → CIK per ticker
  → data.sec.gov/submissions/CIK{padded}.json → find latest 8-K accession numbers
  → /Archives/edgar/data/{cik}/{acc_nodash}/{acc}.txt → extract XBRL xmlns domain
  → probe IR paths on that domain (IR subdomains first, then company domain paths)
  → require keyword match ("press release", "news release", "announcements") to confirm
```

Key pitfalls:
- EDGAR `website` and `investorWebsite` fields in submissions JSON are almost always empty for biotechs — don't use them.
- GNW `.com/issuer/TICKER` 404s. GNW org IDs in URL are per-release-ID, not per-company.
- GNW `/Search?keyword=TICKER` redirects (301) to `/en/search/keyword/TICKER` — use the redirect target directly.
- Probe IR subdomains (`investors.company.com`, `ir.company.com`) BEFORE company domain paths — subdomain hit rate is higher and company domain `/ir` paths often redirect to non-IR pages.
- Require a keyword match on the probed page, not just a 200 response. Short `/ir` paths redirect to science/research pages for some biotechs (confirmed: KYMR `kymeratx.com/ir` → science page; `investors.kymeratx.com/investor-relations` → correct IR page).
- CRITICAL — skip entire subdomain on first SSL/timeout error. When `investors.X.com` gets SSLError or ReadTimeout, all remaining paths on that subdomain will also fail. Naively probing all 13 paths = 75s stall per ticker (confirmed: `investors.crisprtx.com`). Group candidates by netloc and set a `skip_base` flag on first connection failure. Use timeout=5s, not 8-10s. See `references/ir_url_population.md` for implementation pattern.

**Pass 2 — GNW search → JSON-LD fallback:**
For tickers where EDGAR XBRL didn't yield a domain (e.g. no recent 8-Ks, exotic filers):

```
GET https://www.globenewswire.com/en/search/keyword/{TICKER}   (note: /Search?keyword redirects here)
  → extract /news-release/YYYY/MM/DD/{release_id}/0/en/{slug} links
  → match slug against ticker/company name
  → fetch release page → parse JSON-LD author.url → company domain
  → probe IR paths same as Pass 1
```

**IR probe path ordering (tier 1 before tier 2):**
```
Tier 1: investors.company.com, investor-relations.company.com, ir.company.com
         × each of: /investors/news-releases, /investor-relations/news-releases,
                    /investors/press-releases, ..., /ir/press-releases, /investors, /ir
Tier 2: company.com × same path list
```

**Tool selection — IMPORTANT:**
Use `tools/populate_ir_sources.py` (XBRL + GNW JSON-LD). NOT `tools/populate_ir_urls.py`.
The latter uses EDGAR `investorWebsite` field (empty for ~100% of biotechs) + HEAD slug probing
that hangs on WSL2 Cloudflare blocks. Both scripts exist; `populate_ir_urls.py` produces 0 results.

**Usage:**
```bash
# Smoke test one ticker first (confirm connectivity, ~15s)
python3 tools/populate_ir_sources.py --ticker VRTX --verbose

# Full dry run → review → then apply (300 tickers ~90-120 min)
# Launch as background terminal job (not Hermes cron — this is a one-shot network job)
# Use mcp_terminal with background=True and notify_on_complete=True
# mcp_terminal(background=True, notify_on_complete=True, timeout=600,
#   command="cd /mnt/c/.../biotech-screener && python3 tools/populate_ir_sources.py --dry-run > artifacts/ir_url_population_run_$(date +%F).log 2>&1")
# Poll while running:
#   mcp_process(action='poll', session_id=<proc_id>)
#   tail -5 artifacts/ir_url_population_run_$(date +%F).log   # see current ticker + hit count
#   grep -c "IR URL = " artifacts/ir_url_population_run_$(date +%F).log  # running hit count

# Pass 1 only (skip GNW fallback)
python3 tools/populate_ir_sources.py --pass1-only

# Apply (writes to company_ir_sources.json — operator review required first)
python3 tools/populate_ir_sources.py
```

**DO NOT use `terminal(background=True)` from mcp_execute_code** -- that route is
blocked ("User denied"). Use `mcp_terminal` directly with `background=True`.

**Heredoc pitfall:** Python heredocs (`<< 'EOF' ... EOF`) inside `terminal()` calls
from `mcp_execute_code` return empty output silently. Write complex Python audit
logic to a temp `.py` file with `mcp_write_file`, then run it with a plain
`terminal("python3 tools/myaudit.py", ...)` call. This applies to any multi-line
Python script passed via heredoc — confirmed broken in 2026-05-06 session (3 empty
results before switching to file-write approach).

Output: updates `production_data/company_ir_sources.json` in place + writes
`artifacts/ir_url_population_YYYY-MM-DD.md` with per-ticker results and method breakdown.

**Expected hit rate (confirmed from full 300-ticker run 2026-05-06):**
Pass 1 (EDGAR XBRL): 192/300 = 64%. Large-caps trend higher; small-cap/recent IPO filers
have sparser 8-K XBRL history, pulling the rate down from theoretical 75-85%.
Pass 2 (GNW JSON-LD): 87 additional = combined 279/300 (93%) newly populated.
Remaining 21 (7%) had `ir_url: None` after both passes — delisted, shell co, or
non-GNW filers. Still empty after full run: set their `company_ir_url` to `null`
explicitly so the fallback is intentional rather than accidental.

**IMPORTANT — Pass 2 junk-domain contamination:**
55 of the 87 Pass 2 hits used `gnw_jsonld_domain` method (domain root, IR probe failed).
~20 of those 55 are junk: law firm sites, market research spam, and ticker collisions
(e.g. `gildan.com` for ticker GILD). Run a cleanup filter BEFORE committing the applied
results. Reject `gnw_jsonld_domain` entries whose domain contains none of the ticker
string or company name words.

After the full 2026-05-06 run: 9 confirmed wrong-company URLs assigned (bad) + 2
borderline cases (NBP=novabridge, GHRS=domain-root-only) = 11 tickers to null out
after `--apply`. Full confirmed null list and audit script in `references/ir_url_population.md`.

**Word-collision tickers — RESOLVED 2026-06-23 (commit 35e662f8):**
Common-word tickers (TECH, DRUG, RARE, LAB, DNA, RNA, VIR, IRON, BEAM, ALT, etc.) flood
GNW keyword search and make GNW JSON-LD unreliable (GNW releases match the word, not the
company). The `gnw_jsonld_domain` fallback for these tickers almost always returns a wrong
company's domain. EDGAR XBRL works better (confirms pass 1 results for RARE, LAB, BEAM,
ALT, COLL, MRNA, EDIT, GLUE, VERA) but some (TECH→tech.com, DNA→no 8-Ks) fail at XBRL
too.

**Resolution (2026-06-23, commit 35e662f8):** 12 word-collision tickers (DRUG, DNA, RNA,
TECH, IRON, BEAM, DAWN, EDIT, FOLD, GRAL, JAZZ, MENS) had their `company_ir_url` entries
replaced from ticker-keyword searches to company-name searches. This eliminates the false
positives when GlobeNewswire serves partial HTML. The fix is in `production_data/company_ir_sources.json`
— these tickers now use company-name-based searches instead of ticker-as-keyword.

**Historical note:** Prior to 2026-06-23, the guidance was to null out wrong-company
gnw_jsonld_domain entries. Confirmed wrong assignments from 2026-05-06 run:
  TECH  → ownify.com         (not Bio-Techne)
  DRUG  → researchandmarkets.com (not Bright Minds)
  DNA   → delveinsight.com   (not Ginkgo Bioworks)
  VIR   → virtualinvestorconferences.com (not Vir Biotechnology)
  RNA   → ir.madrigalpharma.com = MDGL, not Avidity Biosciences
  DAWN  → dawnproject.com    (not Day One Biopharma)
  JAZZ  → usmint.gov         (not Jazz Pharmaceuticals)
These are now resolved via company-name searches; the nulling guidance is historical only.

**Rate limit:** 1.5s between requests. EDGAR best practice: include
`User-Agent: WakeRobinBiotechScreener research@wakerobincapital.com` header.

**Observed runtime:** ~18s/ticker (EDGAR calls + subdomain probing + rate limit).
300 tickers = 90-120 min. Launch as background job; laptop sleep will kill it.

**Verify improvement after run:**
```bash
# Check new populated count
python3 -c "
import json
data = json.load(open('production_data/company_ir_sources.json'))
sources = data['sources']
populated = sum(1 for e in sources if e.get('company_ir_url','').strip())
print(f'{populated}/{len(sources)} populated ({populated/len(sources)*100:.1f}%)')
"
# Then run production_qa to check if classifier_escalation_pool other_share drops below 50%
```

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

**CHECK RANKER BEFORE ESCALATING SELECTOR:** Before recommending selector changes,
confirm whether the flagged signal is already excluded from the ranker. In this codebase,
the selector (`A4_SELECTOR_CONFIG` in run_screen.py) and the ranker (`PRODUCTION_RANKER_V2_CONFIG`)
are separately configured. A signal can be anti-predictive in the selector while already
being a "dead feature" in the ranker. Confirmed 2026-05-04: inst_delta_z was already
excluded from the ranker (run_screen.py:157 comment "dead features: inst_delta_z, catalyst_decay_w,
binary_quality_score added noise") before we zeroed it in the selector. Checking this first
avoids redundant ranker fixes.

```bash
grep -n "inst_delta_z\|coinvest\|dead features" run_screen.py | head -20
```

**Full governance+promotion workflow:** once two-frame confirmation is established, load the `signal-shared-regime-check` skill. It has the comparator probe script (`scripts/shared_regime_check.py`), the governance memo template, and the full ruleset promotion sequence (run_screen.py patch → new ruleset JSON → PHASE2_PINNED_RULESET_ID → CLAUDE.md). Do not re-derive this workflow ad-hoc — the skill has the exact steps confirmed from the 2026-05-04 inst_delta_z case.

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

### Class F — run_agent_direct.py architectural mismatch for tool-dependent agents

**Signature:** Agent crontab entry fires (SCAN or HEARTBEAT), log shows agent "ran"
and wrote a JSON response, but no artifact was produced and the agent reports
"XAI_API_KEY not found" or "cannot check filesystem". Agent appears to run but
produces nothing.

**Root cause (confirmed 2026-05-04):** `tools/run_agent_direct.py` is a **plain
Anthropic SDK text call with no tool execution**. It sends a message and receives
text — it does NOT execute bash commands, Python scripts, or API calls that the
agent writes in its response. Agents designed to run under OpenClaw's gateway
(which provides real bash tool execution) will "hallucinate" shell commands in
their response text that never actually run.

Confirmed affected agent: `grok_biotech_watch`. Its SOUL.md was designed for
OpenClaw's bash tooling. When invoked via `run_agent_direct.py`:
- `env | grep XAI` returns nothing (no real shell)
- `XAI_API_KEY` is in `.env` and loaded into `os.environ` by main() but the
  agent's bash calls in the response text never execute
- Agent writes "HEARTBEAT: FAIL — no XAI_API_KEY" because its preflight bash
  call never ran

**Diagnostic confirmation:**

```bash
# Check agents_direct log for today's run
cat logs/agents_direct/<agent>_<date>_*.json | python3 -c "
import json,sys; d=json.load(sys.stdin)
print('status:', d.get('status'))
print('response snippet:', d.get('response','')[:500])
"
# If response contains bash-like commands as TEXT (not real output),
# and artifacts directory is empty, this is Class F.
```

**Resolution options:**

A. **Wire through OpenClaw instead** — the agent already has
   `~/.openclaw/agents/<name>/agent/` dir. Use `openclaw cron add` to schedule
   via the gateway which provides real bash execution. Requires auth-profiles.json
   with the relevant provider (e.g. xai profile for grok_biotech_watch).

B. **Write a dedicated wrapper script** — bypass the LLM agent for the deterministic
   search/fetch step. A shell/Python script calls the API directly (e.g. xAI Grok
   via curl), writes the artifact, then optionally passes results to a summarizer.
   More reliable for agents whose core work is a deterministic API call.

C. **Extend run_agent_direct.py with a tool executor** — add a tool-use loop that
   intercepts bash tool_use blocks and executes them as real subprocesses. High effort,
   changes a shared tool used by all 30 agents.

**Recommended:** Option B for API-heavy agents (grok_biotech_watch, ctgov_poller-style).
Option A for agents that need broad filesystem access.

**Detection heuristic:** If an agent's SOUL.md mentions `env | grep`, `XAI_API_KEY`,
`curl <external-api>`, or any external HTTP call, it needs real bash execution and
will silently fail under `run_agent_direct.py`.

---

### Class F — production_qa STALE false label (receipt proxy lag)

**Signature:** Fleet receipt shows production_qa as STALE or NO_ARTIFACTS for today.
But when you check `artifacts/production_qa/` directly, today's report exists and
was written in the evening.

**Root cause:** The fleet_steward receipt is generated at 17:30 ET (before the
evening run). production_qa runs at 17:35 ET. The receipt's proxy check for
production_qa fires 5 minutes before the artifact lands. The next day's receipt
clears it, but the current-day receipt always shows production_qa as STALE.

**Confirmed instance (2026-05-04):** receipt flagged production_qa STALE.
Direct check: `artifacts/production_qa/2026-05-04_report.md` written at 22:07 ET.
Actual status: YELLOW (10/11 checks pass). Only FAIL: classifier_escalation_pool
54% other_share — GlobeNewswire keyword contamination (separate tracked issue).

**Triage rule:** When production_qa appears STALE in the receipt, always check
`artifacts/production_qa/<today>_report.md` directly before treating as a failure.
If the file exists with today's date: receipt is stale, agent is healthy.

---

### Class I — Morningstar enrichment silent double-bug (run_screen.py wrong inner key)

**Signature:** `run_screen.py` runs without error and produces a rankings CSV, but all
`ms_*` fields (`ms_return_ytd`, `ms_volatility_3yr`, `ms_star_rating`) are empty strings
or null for the entire universe. The screen runs, the Morningstar engine runs, but nothing
enriches — completely silent failure at the site level.

**Root cause (confirmed 2026-05-06, commits `e70ae626` + `5c284ab7`):** Two independent
bugs in the Morningstar enrichment block of `run_screen.py`:

**Bug 1 (first):** `MorningstarSignalEngine.score_universe()` returns
`{"scores_by_ticker": {...}, ...}`. The enrichment block called `.get("scores", {})` —
wrong top-level key. The `.get()` silently returns `{}` when the key is absent; no error,
no log. Fixed commit: `e70ae626`.

**Bug 2 (second, independent):** After fixing the top-level key, the inner extraction also
used `.get("scores", {})` instead of the correct field path. Second silent empty-dict
return. Fixed commit: `5c284ab7`.

**Both bugs were silent** — no exception, no warning log, just empty enrichment fields in
the output. The pattern `result.get("scores", {})` is structurally ambiguous when the
engine return schema uses a different key name at the same level.

**Diagnostic chain:**

```bash
# 1. Confirm ms_* fields are empty in most recent snapshot
python3 -c "
import json, glob
files = sorted(glob.glob('data/snapshots/*/screen_output.json'), reverse=True)
if not files: print('no snapshots'); exit()
data = json.load(open(files[0]))
rows = data if isinstance(data, list) else data.get('tickers', [])
sample = rows[:3]
for r in sample:
    print({k: v for k, v in r.items() if k.startswith('ms_')})
"

# 2. Confirm what MorningstarSignalEngine.score_universe() actually returns
grep -n 'def score_universe\|scores_by_ticker\|return.*scores' tools/morningstar*.py | head -20

# 3. Check the enrichment site in run_screen.py
grep -n 'scores_by_ticker\|\.get.*scores\|morningstar.*enrich\|ms_return_ytd' run_screen.py | head -20
```

**Pattern to catch:** Any `.get("scores", {})` call against a dict returned by a signal
engine should be verified against the engine's actual return schema. Signal engines in
this repo commonly use `"scores_by_ticker"` (with the `_by_ticker` suffix) as the top-
level key — not bare `"scores"`. If the key name drifts between engine and consumer, the
`.get()` fallback silently swallows the data.

**Test coverage added:** `TestMorningstarEnrichmentKeyPath` (6 tests) in
`tests/test_run_screen_units.py` now covers both wrong-key variants and the correct path.

**Impact on recent screens:** Any screen run between the Morningstar engine activation
and `5c284ab7` had ms_* fields uniformly empty. Use `ls -lt data/snapshots/*/rankings.csv`
to find affected dates; the fix produces `ms_return_ytd: 297/297 non-null` on a 299-ticker
universe (2026-05-06 confirmed post-fix run).

---

### Class G — ic_health_monitor ALERT persists after signal zeroed (expected self-clearing)

**Signature:** ic_health_monitor continues to show ALERT on inst_delta_z even after
the signal has been zeroed in the selector (ruleset promotion). This looks like the
fix didn't work but it's expected behavior.

**Root cause:** The IC dashboard computes rolling IC over a historical lookback window
(60 dates). Zeroing a signal in the selector doesn't change past IC measurements.
The ALERT reflects historical data; it clears naturally as new dates accumulate in
the window with the signal no longer active in selection.

**Expected timeline:** With a 60-date lookback and ~1 date/day, the historical
negative IC window gets diluted over ~4-6 weeks. Do not re-open the governance
review based on ALERT persistence alone after a zeroing promotion.

**Triage rule:** After a signal is zeroed via ruleset promotion, suppress
ic_health_monitor ALERTs on that signal for 30 calendar days. Check the
governance log for the promotion date. If the ALERT persists beyond 30 days
after promotion with IC still negative, THEN re-open.

**Secondary signal watch — score_rank_pct WARN (confirmed 2026-05-06):**
IC dashboard may show WARN on signals beyond the primary governed signal.
Confirmed pattern (2026-05-05/06): `score_rank_pct` entered WARN status
(mean_ic = -0.0098, hit_rate 34.2% on Day 2; worsened to -0.0119/29% on Day 3)
while `inst_delta_z` was already ALERT/governed.

IC time-series evidence shows `score_rank_pct` was consistently negative from
mid-February onward, not a recent perturbation. This is structural degradation,
not Day-of-week or regime noise.

**Escalation rule for WARN signals in the IC dashboard:**
- Day 1 WARN: note as a new finding; surface to ops
- Day 2 WARN: confirm time-series shape (structural vs episodic)
- Day 3+ WARN: escalate to sentinel for review; invoke `signal-shared-regime-check`
  skill to check for shared-regime vs signal-specific failure

**GOVERNANCE CEILING:** Applies equally to WARN as to ALERT. Do NOT recommend
weight changes without a Spec/Checklist v2 writeup. Surface an escalation packet only:

```
ESCALATION PACKET for ops + sentinel:
  Signal:        score_rank_pct
  Surface:       ic_health_monitor WARN Day 3+ (2026-05-06)
  mean_ic:       -0.0119 (38 dates, worsened from -0.0098 Day 2)
  hit_rate:      29% (worsened from 34.2% Day 2)
  Onset:         mid-February 2026 (structural pattern, not episodic)
  Role:          composite rank percentile — downstream of selector/ranker
  
Read-only diagnostics recommended:
  - Time-series plot of IC (is Feb-onset consistent or sporadic?)
  - Shared-regime check vs coinvest_score_z (controlled for selection regime)
  - Check if degradation is universe-shift artifact from cohort reshuffle
Do NOT modify ruleset or weights. Governance review required.
```

**Note:** `ic_health_monitor` has NO standalone cron — built inside
`cron_daily_production.sh`. Dashboard at `artifacts/ic_dashboard/<date>_dashboard.json`.

---

### Class H — financial_records CashAndSecurities understated due to XBRL tag mismatch

**Signature:** `data_auditor` financial_consistency check shows WARN with a divergence
> 50% for a specific ticker. The `financial_records_value` matches the `Cash` field
exactly, but `pit_value` is much larger (cash + STI). CashAndSecurities in
financial_records.json equals Cash only.

**Root cause (confirmed 2026-05-05, EWTX):** `collect_financial_data.py` fetches
ShortTermInvestments via XBRL tag `ShortTermInvestments` from SEC EDGAR. Some tickers
file their STI under a different XBRL tag that the script doesn't cover. The STI fetch
returns None; CashAndSecurities is set to Cash only. Meanwhile, `pit_financials/<ticker>.json`
(which has its own EDGAR fetch path) correctly captures the STI.

Confirmed numbers for EWTX 2025-12-31 10-K (accn 0001104659-26-020112):
- financial_records: Cash=$61.1M, ShortTermInvestments=None, CashAndSecurities=$61.1M
- pit_financials: cash=$61.1M + STI=$468.9M = $530.1M correct
- divergence: 88.5%

**Diagnostic chain:**

```bash
# 1. Confirm the divergence is STI-missing (not data corruption)
python3 - << 'EOF'
import json
REPO = "/mnt/c/Projects/biotech_screener/biotech-screener"
TICKER = "EWTX"

# financial_records
fr = json.load(open(f"{REPO}/production_data/financial_records.json"))
ewtx = next((x for x in fr if x.get("ticker") == TICKER), {}) if isinstance(fr, list) else fr.get(TICKER, {})
print("financial_records:")
print(f"  Cash:               {ewtx.get('Cash')}")
print(f"  ShortTermInvestments: {ewtx.get('ShortTermInvestments')}")
print(f"  CashAndSecurities:  {ewtx.get('CashAndSecurities')}")

# pit_financials
pit = json.load(open(f"{REPO}/production_data/pit_financials/{TICKER}.json"))
cash_entries = sorted(pit["facts"].get("cash", []), key=lambda x: x["end"])
sti_entries  = sorted(pit["facts"].get("short_term_investments", []), key=lambda x: x["end"])
if cash_entries: print(f"pit_financials cash latest: {cash_entries[-1]}")
if sti_entries:  print(f"pit_financials STI latest:  {sti_entries[-1]}")
EOF

# 2. If STI is None in financial_records but present in pit_financials →
#    XBRL tag mismatch. The fix is to patch from pit_financials.

# 3. Confirm dates align (both from same period end)
```

**Surgical patch recipe (confirmed working 2026-05-05):**

```python
import json, sys
from pathlib import Path
from datetime import datetime, timezone

REPO = Path("/mnt/c/Projects/biotech_screener/biotech-screener")
TICKER = "EWTX"
APPLY = "--apply" in sys.argv

def get_latest(facts, key):
    entries = sorted(facts.get(key, []), key=lambda x: x["end"])
    return (entries[-1]["val"], entries[-1]["end"]) if entries else (None, None)

pit = json.loads((REPO / "production_data" / "pit_financials" / f"{TICKER}.json").read_text())
cash_val, cash_date = get_latest(pit["facts"], "cash")
sti_val, sti_date   = get_latest(pit["facts"], "short_term_investments")
assert cash_date == sti_date, f"Date mismatch: {cash_date} vs {sti_date}"
correct_cs = cash_val + sti_val

# Patch production_data/financial_records.json and financial_data.json
for path in [REPO / "production_data" / "financial_records.json",
             REPO / "production_data" / "financial_data.json"]:
    data = json.loads(path.read_text())
    is_list = isinstance(data, list)
    idx = next((i for i, e in enumerate(data) if e.get("ticker") == TICKER), None) if is_list else None
    entry = data[idx] if is_list else data.get(TICKER, {})
    print(f"{path.name}: CashAndSecurities {entry.get('CashAndSecurities')} → {correct_cs}")
    if APPLY:
        entry["ShortTermInvestments"] = sti_val
        entry["ShortTermInvestments_date"] = sti_date
        entry["CashAndSecurities"] = correct_cs
        entry["CashAndSecurities_date"] = cash_date
        entry["collected_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if is_list: data[idx] = entry
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print(f"  WRITTEN")

# Also patch all pit_archives (untracked) with the same script logic,
# iterating REPO.glob("data/pit_archives/*/financial_records.json")
```

Run dry-run first (no `--apply`), verify output, then add `--apply`.

**Also patch pit_archives:** The auditor reads from `data/pit_archives/<date>/financial_records.json`
first. Use the same patch logic iterating all pit_archive dates — typically 400+ files.
All are untracked, so this doesn't pollute git.

**Verify fix:**
```bash
python3 agents/data_auditor/run_audit.py --as-of-date YYYY-MM-DD --daily-only 2>&1 | tail -10
# financial_consistency should now show PASS with no divergences
```

**Root cause residual:** `collect_financial_data.py` will re-introduce the gap on next
full refresh if the XBRL tag mismatch isn't fixed. The script fetches STI via tag
`ShortTermInvestments`; the ticker may use `AvailableForSaleSecuritiesCurrent` or
another tag. The surgical patch is a hotfix; a permanent fix requires extending the
XBRL tag fallback list in collect_financial_data.py or back-filling from pit_financials
during collection.

**What NOT to do:**
- Do NOT use a manual override entry — that masks root cause and requires indefinite maintenance.
- Do NOT re-run the full `collect_financial_data.py` — it will overwrite with the same bad value.

---

## Resuming after a disconnected session

When reconnecting and the user says "pick up where we left off," use this standard recovery sequence:

1. `session_search(query='<last known topic>')` — get the most recent session summary.
   The summary contains: what was running, what background process was launched, what the log path is, and what the next steps were.
2. `mcp_process(action='list')` — check if the background job is still running.
   If it returns `{"processes": []}`, the process died with the session.
   This does NOT mean the run failed — check the log for the summary block first.
3. `tail -30 <log_path>` — check where the run ended and get the final summary block.
4. Report the completion state clearly (counts, errors, next steps) before asking the user what to do.

The session summary reliably captures background job state. Even after a full disconnect,
the log file is still on disk and the summary block at the bottom of the log is the ground truth.

Confirmed pattern (2026-05-06): background IR URL population run was killed when the session
disconnected. Recovery: session_search found the log path; mcp_process showed the process was
gone; tail -30 of the log showed the run HAD completed (summary block was present). Full
300-ticker result was readable from the log. No data was lost.

### Parallel fleet commit → orphan branch → cherry-pick recovery

When a background fleet agent (ops cron, daily run, etc.) commits to main while you are
mid-work in the same repo, git may auto-create a side branch (`save/...`) to hold your
commit rather than rejecting it. Symptoms:

- `git log --oneline -5` doesn't show your commit
- `git log --all --oneline | grep <your-commit-sha>` DOES show it
- `git branch --contains <sha>` shows something like `save/ir-sources-populate-2026-05-06`
- `git diff <sha> HEAD -- <file>` shows your changes on the `-` side (removed in HEAD)

**Recovery:**
```bash
# 1. Confirm working tree is clean first
git status -s
# 2. Cherry-pick your commit onto main
git cherry-pick <sha>
# 3. Verify it landed
git log --oneline -3
```

This is safe as long as the working tree is clean (no staged/modified tracked files).
Confirmed 2026-05-06: `b05becd2` landed on `save/ir-sources-populate-2026-05-06`;
cherry-picked as `578d32a4` onto main without conflicts.

**Prevention:** Before committing, check `git log --oneline -3` to confirm HEAD is
where you expect. If main has moved ahead, stash, pull/rebase, then commit.

---

### Stale `.git/index.lock` after session disconnect

A disconnected session that died mid-git operation (e.g. `git add`) leaves
`.git/index.lock` on disk. The next `git add` fails with:

```
fatal: Unable to create '.git/index.lock': File exists.
Another git process seems to be running in this repository
```

Fix: `rm /mnt/c/Projects/biotech_screener/biotech-screener/.git/index.lock`

Confirmed safe when no git process is actually running (session is dead).
Diagnostic tell: `ps aux | grep git` shows nothing. The lock file is a tombstone
from the killed session.

---

### IR URL population — log-replay recovery (FASTER than re-running)

`tools/populate_ir_sources.py` **writes atomically at the end of the run**. A disconnection
mid-run leaves `company_ir_sources.json` completely untouched (the backup `.bak-pre-populate-*`
file has a newer mtime than the source JSON — this is the diagnostic tell). If the dry-run
log completed (`[DRY RUN] No files written.` at the bottom), you have all 279 URLs in the log.
Re-running the full network job (~90 min) is unnecessary.

**Log-replay apply script** (parse dry-run log → write JSON directly):

```python
import json, re

LOG  = "artifacts/ir_url_population_run_2026-05-06.log"
JSON = "production_data/company_ir_sources.json"
BAD_TICKERS = {"ABCL","ARWR","BRKR","ILMN","LGND","MEDP","OABI","TEM","ZLAB","NBP","GHRS"}

with open(LOG) as f:
    lines = f.readlines()

ir_url_pat   = re.compile(r"INFO\s+(\w+): IR URL = (.+)")
gnw_dom_pat  = re.compile(r"INFO\s+(\w+): company site via GNW JSON-LD = (.+)")
dom_root_pat = re.compile(r"INFO\s+(\w+): IR probe failed, using domain root")

ir_urls, gnw_domains, failed_probes = {}, {}, set()
for line in lines:
    if m := ir_url_pat.search(line):   ir_urls[m.group(1)]    = m.group(2).strip()
    if m := gnw_dom_pat.search(line):  gnw_domains[m.group(1)] = m.group(2).strip()
    if m := dom_root_pat.search(line): failed_probes.add(m.group(1))

# domain-root entries: gnw_domains where probe failed (url = domain root itself)
domain_root = {k: gnw_domains[k] for k in failed_probes if k in gnw_domains}
all_urls = {**domain_root, **ir_urls}   # ir_urls takes precedence

with open(JSON) as f:
    data = json.load(f)

for entry in data["sources"]:
    t = entry.get("ticker","")
    if t in BAD_TICKERS:
        entry["company_ir_url"] = ""
        continue
    if entry.get("company_ir_url","").strip():
        continue   # already populated
    if t in all_urls:
        entry["company_ir_url"] = all_urls[t]
        entry["_ir_population_method"] = "edgar_xbrl_probe" if t in ir_urls else "gnw_jsonld_domain"

with open(JSON, "w") as f:
    json.dump(data, f, indent=2)

populated = sum(1 for e in data["sources"] if e.get("company_ir_url","").strip())
print(f"{populated}/{len(data['sources'])} populated")
```

**Three regex patterns required** — not one. The log has three URL-bearing line types:
- `INFO   TICKER: IR URL = <url>` — Pass 1 EDGAR + Pass 2 GNW probe hits (224 entries)
- `INFO   TICKER: company site via GNW JSON-LD = <domain>` — GNW domain capture (87 entries)
- `INFO   TICKER: IR probe failed, using domain root` — signals the preceding domain IS the URL (55 of the 87)

If you only parse `IR URL =` lines you get 224/279 (missing the 55 domain-root fallbacks).

### Class J — Drift report pipeline broken (sentinel blinded on overlap/rank-shift)

**Signature:** Sentinel reports ROLLBACK_RECOMMENDED or consecutive WARN days, but the
drift dimension (top-60 overlap, max rank shift) cannot be computed because the
drift_guardrails/ directory is missing from recent snapshots. The WARN is driven by a
single factor (e.g. headwind_weight_pct) with the drift dimension unmeasurable.

**Confirmed instance (2026-06-17):** Sentinel reported 6+ consecutive WARN days with
ROLLBACK_RECOMMENDED. Headwind_weight_pct flat at 36.63% (threshold 30%). However,
drift_guardrails/ directory was missing from snapshots for 5+ consecutive days. Sentinel
could not compute top-60 overlap or max rank shift, meaning the ROLLBACK_RECOMMENDED
was single-factor and could not be fully validated. Additionally,
`artifacts/ruleset_health_history.jsonl` had not been updated since 2026-05-06 (6+ weeks
stale), preventing longitudinal drift assessment.

**Root cause:** The drift report is generated as part of the snapshot pipeline. If the
pipeline step that produces drift_guardrails/ fails silently or is skipped (e.g. due to
missing prior-day snapshot for comparison, or a code change that broke the step), the
guardrails directory is absent. Sentinel's automated checks then fall back to the
headwind-only dimension, which can trigger WARN without the drift dimension to confirm
or contradict.

**Diagnostic recipe:**

```bash
# 1. Check if drift_guardrails/ exists in recent snapshots
for d in $(ls -t data/snapshots/ | head -5); do
  echo "=== $d ==="
  ls data/snapshots/$d/drift_guardrails/ 2>/dev/null || echo "MISSING"
done

# 2. Check ruleset_health_history freshness
tail -3 artifacts/ruleset_health_history.jsonl
# If last entry is >7 days old, longitudinal drift tracking is broken

# 3. Check if the drift report step is in the production pipeline
grep -n 'drift_guardrails\|drift_report\|overlap' tools/run_daily_production.py | head -10

# 4. Check sentinel's TOOLS.md for how it reads drift data
grep -A5 'drift\|overlap\|guardrail' agents/sentinel/TOOLS.md | head -20

# 5. Assess whether WARN is single-factor or multi-factor
# If drift_guardrails/ is missing, sentinel WARN is headwind-only → less reliable
```

**Resolution:**
1. Identify why the drift report pipeline step stopped producing output.
2. Check for code changes to the drift report step in recent commits.
3. Check if prior-day snapshot exists (drift comparison requires two consecutive days).
4. Manually trigger the drift report step if possible.
5. Until drift_guardrails/ is restored, treat sentinel WARN as single-factor and
   note in triage: "drift dimension unmeasurable, WARN is headwind-only."
6. Do NOT act on ROLLBACK_RECOMMENDED without the drift dimension confirming.

**Related: ruleset_health_history.jsonl stale**

If `artifacts/ruleset_health_history.jsonl` has not been updated for weeks, sentinel's
longitudinal drift tracking is also broken. This file is appended to by the drift report
pipeline step. If that step is broken, both drift_guardrails/ AND history.jsonl go stale
simultaneously. Check both together.

```bash
# Check both together
ls data/snapshots/$(ls -t data/snapshots/ | head -1)/drift_guardrails/ 2>/dev/null
tail -1 artifacts/ruleset_health_history.jsonl | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print('last entry:', d.get('date'))"
```

---

### Class K — LangGraph review node artifact_dir None guard (third-runtime pattern)

**Signature:** LangGraph-based review nodes crash with AttributeError or TypeError when
`artifact_dir` is None. The LangGraph runtime (third alongside Hermes and OpenClaw) has
different null-handling expectations than the other two runtimes.

**Root cause (confirmed 2026-06-22, commit `afced5d4`):** The LangGraph review node
assumed `artifact_dir` was always a valid path string. When the node was invoked in
contexts where no artifact directory was configured (e.g., diagnostic-only runs, certain
cron triggers), `artifact_dir` was None, causing the node to crash when attempting path
operations.

**Runtime boundary context:** Commit `96ffea36` (2026-06-22) established the
"Hermes/OpenClaw/LangGraph runtime boundary map" — LangGraph is now a third runtime
alongside Hermes (cron-managed agents) and OpenClaw (gateway-managed agents). Each
runtime has different null-handling, tool-execution, and artifact-path conventions:

- **Hermes**: cron-managed, tool-execution via Hermes agent loop, artifacts at
  `artifacts/<agent>/` or agent-specific paths. Null args typically default to None
  and agents handle gracefully.
- **OpenClaw**: gateway-managed, real bash tool execution, artifacts at declared paths
  in AGENTS.md. Null args cause tool-execution failures that agents can diagnose.
- **LangGraph**: graph-based workflow, node-level execution, artifacts at node-declared
  paths. Null args cause node crashes (AttributeError/TypeError) unless explicitly
  guarded. See `docs/governance/runtime_boundary_map.md` for the full matrix.

**Diagnostic chain:**

```bash
# 1. Check if the crash is in a LangGraph node (not Hermes/OpenClaw agent)
grep -r "langgraph\|StateGraph\|node.*artifact_dir" tools/ agents/ --include="*.py" | head -10

# 2. Check the node's artifact_dir parameter handling
grep -B2 -A5 "artifact_dir" tools/<langgraph_tool>.py | head -20
# If the node does path operations (e.g., artifact_dir / "file.json") without
# checking for None first, this is the Class K pattern.

# 3. Check the invocation context
# LangGraph nodes can be invoked from multiple contexts (cron, manual, diagnostic).
# Some contexts may not configure artifact_dir. Check the call site.
```

**Resolution pattern:**
- Add explicit None guard at the node entry point: `if artifact_dir is None: return {"status": "skip", "reason": "no artifact_dir configured"}`
- Or provide a default: `artifact_dir = artifact_dir or Path("artifacts/default_review")`
- The fix should match the node's contract — if the node is designed to work without
  artifacts in some contexts, return a skip status; if it always needs artifacts, raise
  a clear error.

**Detection heuristic:** If a LangGraph node crashes with AttributeError/TypeError on
path operations and the traceback points to `artifact_dir` being None, this is Class K.
Check the runtime boundary map to confirm the node is LangGraph (not Hermes/OpenClaw).

**Note:** LangGraph is a newer runtime in this ecosystem (admitted 2026-06-22 via
Package B governance review). Skills and diagnostic patterns are still being built out.
When encountering LangGraph-specific failures, check `docs/governance/runtime_boundary_map.md`
for the runtime's conventions before applying Hermes/OpenClaw diagnostic patterns.

---

### Class L — Financial calculation unit-mismatch (periodicity confusion)

**Signature:** Financial metrics (burn rate, runway, cash consumption) are silently wrong
by a factor of 3-4×. The calculation runs without error, produces plausible-looking numbers,
but the underlying periodicity assumption is wrong (quarterly divisor applied to annual data,
or annual divisor applied to quarterly data).

**Root cause (confirmed 2026-06-23, commit `c6e1700c`):** Module 2 (financial health) had
two fallback burn-rate calculation paths in NetIncome and R&D expense handling. Both paths
hard-coded `/3` (quarterly assumption) when the SEC filing data was actually annual (Dec
fiscal year-end 10-K). This overstated monthly burn 4× and understated runway 4× for tickers
reaching these last-resort fallback paths.

**Confirmed instance:** Tickers with SEC annual filings (fiscal year-end December) reaching
the NetIncome or R&D fallback paths. The fix ported `_ytd_months_from_date()` from v1 to
use the `NetIncome_date` / `R&D_date` fields (already passed through in financial_data) to
infer the correct period. Default remains 3 when date is missing (no behavior change for
existing data without date fields).

**Diagnostic chain:**

```bash
# 1. Check if financial metrics look plausible
python3 - << 'EOF'
import json, glob
files = sorted(glob.glob('data/snapshots/*/rankings.csv'), reverse=True)
if not files: exit()
import csv
with open(files[0]) as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        if i >= 5: break
        burn = row.get('monthly_burn_rate_mm')
        runway = row.get('runway_months')
        cash = row.get('cash_and_securities_mm')
        if burn and runway:
            print(f"{row.get('ticker')}: burn={burn}, runway={runway}, cash={cash}")
            # Sanity check: runway ≈ cash / burn
            try:
                expected_runway = float(cash) / float(burn) if float(burn) > 0 else None
                if expected_runway and abs(expected_runway - float(runway)) > 0.5:
                    print(f"  ⚠️  Runway mismatch: expected {expected_runway:.1f}, got {runway}")
            except:
                pass
EOF

# 2. Check the calculation code for hardcoded divisors
grep -n "/3\|/12\|_ytd_months\|period.*month" tools/financial_health.py | head -20
# Look for: hardcoded /3 or /12 without checking the actual filing period

# 3. Check if date fields are used to infer periodicity
grep -n "NetIncome_date\|R&D_date\|fiscal_year_end\|period_end" tools/financial_health.py | head -20
# If date fields exist but aren't used to determine the divisor, this is the Class L pattern

# 4. Verify the fix (post-c6e1700c)
grep -A10 "_ytd_months_from_date" tools/financial_health.py | head -15
# Should see: uses the date field to infer months, not hardcoded /3
```

**Pattern to catch:** Any financial calculation that divides by a hardcoded number (3, 4, 12)
to convert between periodicities (annual↔quarterly↔monthly) WITHOUT checking the actual
filing period or date field is suspect. SEC filings have mixed periodicity:
- 10-K (annual) → divide by 12 for monthly
- 10-Q (quarterly) → divide by 3 for monthly
- If the code doesn't distinguish, it will silently produce wrong results

**Test coverage added (commit c6e1700c):** 2 new golden cases verify the annual path
(Dec date → /12). 136/136 module_2 tests pass; 44/44 golden tests pass.

**Impact on recent screens:** Any screen run between the Module 2 activation and c6e1700c
had burn rates overstated 4× and runways understated 4× for tickers reaching the fallback
paths. Use `ls -lt data/snapshots/*/rankings.csv` to find affected dates; the fix produces
correct burn/runway for annual filers.

**General rule:** When financial metrics look implausible (runway < 6 months for a company
with $100M+ cash, or burn rate 4× higher than peers), check the periodicity assumption in
the calculation code. The bug is silent — no exception, no warning, just wrong numbers.

---

## Support files

- `scripts/patch_financial_records_sti.py` — reusable surgical patch for XBRL STI mismatch
  (Class H). Patches financial_records.json, financial_data.json, and all pit_archive dates
  from pit_financials source of truth. Run with `--apply` to write; dry-run by default.
- `references/ir_url_population.md` — detailed notes on the two-pass IR URL sourcing
  technique (EDGAR XBRL namespace + GNW JSON-LD), probe path ordering, confirmed results
  for FDMT/KYMR/IMVT, full pass 2 audit (87 entries classified), confirmed null list
  (11 tickers), pitfalls, and log-replay recovery technique for disconnected sessions.

### Class K — Shadow monitor truthy-form immutability (post-merge audit pattern)

**Signature:** A shadow monitor or append-only ledger uses `if forward_complete_20d is True`
or `if forward_complete_20d == True` to guard settled rows from mutation. Manually edited
ledger values like `1`, `"true"`, or `"True"` pass the truthiness test but fail the identity
check, allowing settled rows to be overwritten.

**Root cause (confirmed 2026-06-23, commit `376d9e9d`):** Post-merge audit of shadow monitor
(commit `60876b11`) identified that `backfill_open_rows()` and the integrity assertion only
protected rows where `forward_complete_20d is True` (Python identity), missing manually edited
ledger values like `1` or `"true"`.

**Diagnostic chain:**

```bash
# 1. Check the immutability guard pattern
grep -n "forward_complete.*is True\|forward_complete.*== True\|forward_complete" \
  scripts/research/ees_v2_phase3_shadow_monitor.py | head -20

# 2. Look for all check sites (load, backfill, compute, assertion)
grep -n "forward_complete_20d\|forward_complete_5d" \
  scripts/research/ees_v2_phase3_shadow_monitor.py

# 3. Check if a helper function exists for truthy-form acceptance
grep -n "_is_settled\|def.*settled" \
  scripts/research/ees_v2_phase3_shadow_monitor.py
```

**Resolution pattern (confirmed working 2026-06-23):**
Add a `_is_settled(v)` helper that accepts all truthy forms:
```python
def _is_settled(v):
    """Accept True, 1, 'true'/'True'/'TRUE'; reject False, 0, 'false', None, missing, '1'-as-string"""
    if v is True or v == 1:
        return True
    if isinstance(v, str) and v.lower() in ("true",):
        return True
    return False
```

Apply `_is_settled()` at ALL check sites (load_ledger, backfill_open_rows outer+inner,
computeSummary, main() integrity assertion). Tests: +17 hardening tests (54 total, was 37).

**Pattern to catch:** Any boolean identity check (`is True`, `== True`) against a field that
may be manually edited or loaded from JSON/CSV is suspect. JSON/CSV loaders may coerce `true`
to `True`, `1` to int, or leave `"true"` as string. The guard must accept all settled forms.

**Test coverage added (commit 376d9e9d):**
- `TestIsSettled`: 11 unit tests covering all accepted/rejected forms
- `TestBoolishSettledRowImmutability`: 6 integration tests confirming backfill + assertion
  honor all settled forms

**General rule:** When a ledger has an "immutable after settled" contract, the settled check
must be a truthy-form acceptance function, not a Python identity check. Post-merge audit is
the right time to catch this — the initial implementation often uses `is True` for clarity,
but real-world edits (manual CSV patches, JSON hand-edits) introduce variant forms.

---

### Class L — Financial calculation unit-mismatch (periodicity confusion)

**Signature:** Financial metrics (burn rate, runway, cash consumption) are silently wrong
by a factor of 3-4×. The calculation runs without error, produces plausible-looking numbers,
but the underlying periodicity assumption is wrong (quarterly divisor applied to annual data,
or annual divisor applied to quarterly data).

**Root cause (confirmed 2026-06-23, commit `c6e1700c`):** Module 2 (financial health) had
two fallback burn-rate calculation paths in NetIncome and R&D expense handling. Both paths
hard-coded `/3` (quarterly assumption) when the SEC filing data was actually annual (Dec
fiscal year-end 10-K). This overstated monthly burn 4× and understated runway 4× for tickers
reaching these last-resort fallback paths.

**Confirmed instance:** Tickers with SEC annual filings (fiscal year-end December) reaching
the NetIncome or R&D fallback paths. The fix ported `_ytd_months_from_date()` from v1 to
use the `NetIncome_date` / `R&D_date` fields (already passed through in financial_data) to
infer the correct period. Default remains 3 when date is missing (no behavior change for
existing data without date fields).

**Diagnostic chain:**

```bash
# 1. Check if financial metrics look plausible
python3 - << 'EOF'
import json, glob
files = sorted(glob.glob('data/snapshots/*/rankings.csv'), reverse=True)
if not files: exit()
import csv
with open(files[0]) as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        if i >= 5: break
        burn = row.get('monthly_burn_rate_mm')
        runway = row.get('runway_months')
        cash = row.get('cash_and_securities_mm')
        if burn and runway:
            print(f"{row.get('ticker')}: burn={burn}, runway={runway}, cash={cash}")
            # Sanity check: runway ≈ cash / burn
            try:
                expected_runway = float(cash) / float(burn) if float(burn) > 0 else None
                if expected_runway and abs(expected_runway - float(runway)) > 0.5:
                    print(f"  ⚠️  Runway mismatch: expected {expected_runway:.1f}, got {runway}")
            except:
                pass
EOF

# 2. Check the calculation code for hardcoded divisors
grep -n "/3\|/12\|_ytd_months\|period.*month" tools/financial_health.py | head -20
# Look for: hardcoded /3 or /12 without checking the actual filing period

# 3. Check if date fields are used to infer periodicity
grep -n "NetIncome_date\|R&D_date\|fiscal_year_end\|period_end" tools/financial_health.py | head -20
# If date fields exist but aren't used to determine the divisor, this is the Class L pattern

# 4. Verify the fix (post-c6e1700c)
grep -A10 "_ytd_months_from_date" tools/financial_health.py | head -15
# Should see: uses the date field to infer months, not hardcoded /3
```

**Pattern to catch:** Any financial calculation that divides by a hardcoded number (3, 4, 12)
to convert between periodicities (annual↔quarterly↔monthly) WITHOUT checking the actual
filing period or date field is suspect. SEC filings have mixed periodicity:
- 10-K (annual) → divide by 12 for monthly
- 10-Q (quarterly) → divide by 3 for monthly
- If the code doesn't distinguish, it will silently produce wrong results

**Test coverage added (commit c6e1700c):** 2 new golden cases verify the annual path
(Dec date → /12). 136/136 module_2 tests pass; 44/44 golden tests pass.

**Impact on recent screens:** Any screen run between the Module 2 activation and c6e1700c
had burn rates overstated 4× and runways understated 4× for tickers reaching the fallback
paths. Use `ls -lt data/snapshots/*/rankings.csv` to find affected dates; the fix produces
correct burn/runway for annual filers.

**General rule:** When financial metrics look implausible (runway < 6 months for a company
with $100M+ cash, or burn rate 4× higher than peers), check the periodicity assumption in
the calculation code. The bug is silent — no exception, no warning, just wrong numbers.

---

## Cross-skill diagnostic routing

```
production_qa FAIL on classifier_escalation_pool?
  → Class A. Press release feed contamination. Check GNW keyword fallback.
  → Class A1. If root cause is empty company_ir_url: run tools/populate_ir_sources.py
    (two-pass: EDGAR XBRL namespace → IR probe; GNW JSON-LD fallback).

Agent reports "no data" but data exists somewhere?
  → Class B. Default None path bug. Check --argument defaults in the tool.

Fleet FAIL but artifacts are fresh?
  → Class C. Builder/summarizer split. Three-axis check (memory / artifacts / invocations).

ic_health_monitor ALERT on inst_delta_z or other load-bearing signal?
  → Class D. Two-frame confirmation protocol. Governance ceiling applies.

data_auditor shows 4+ ERROR checks all on the same date?
  → Class E. Single missing snapshot cascade. Check rankings.csv, not each check individually.

data_auditor financial_consistency WARN: one ticker with 50–90% divergence?
  → Class H. XBRL tag mismatch. Check if ShortTermInvestments is None in financial_records
    but present in pit_financials. Patch from pit_financials; don't use manual override.

All ms_* fields empty across universe in rankings CSV?
  → Class I. Morningstar silent double-bug. Check .get("scores") vs .get("scores_by_ticker")
    in run_screen.py enrichment block. Both bugs are independent; fix both commits needed.

Monitoring step artifact missing (e.g. trapops_daily_summary.json not written after production)?
  → Pattern 7 (see biotech-screener-catchup-hardening). Three-part failure: (1) compute
    function doesn't write artifact — only standalone main() writes it; (2) step is inside
    promotion gate — skipped on reruns; (3) watchdog checks log mtime not artifact presence.
    Fix: pipeline step writes artifact itself (idempotent); watchdog checks artifact file.
    Root cause confirmed 2026-05-06 (ec183074). Never assume a monitoring function that
    returns a dict also writes it — check explicitly.
  → Class G extension. Score_rank_pct pattern confirmed 2026-05-06. Escalate per escalation
    packet template. Invoke signal-shared-regime-check skill for time-series diagnosis.

Sentinel ROLLBACK_RECOMMENDED but drift_guardrails/ missing from snapshots?
  → Class J. Drift report pipeline broken. WARN is single-factor (headwind-only).
    Do NOT act on ROLLBACK_RECOMMENDED without drift dimension confirming.
    Also check ruleset_health_history.jsonl freshness.

Shadow monitor / append-only ledger allows settled rows to be overwritten?
  → Class K. Truthy-form immutability. Check if settled guard uses `is True` identity
    instead of truthy-form acceptance. Post-merge audit pattern. Confirmed 2026-06-23 (376d9e9d).

Financial metrics (burn, runway) look implausible (4× off)?
  → Class L. Periodicity confusion. Check if calculation hardcodes /3 or /12 without
    checking filing period. Confirmed 2026-06-23 (c6e1700c): annual data divided by 3.
```
LangGraph node crashes with AttributeError/TypeError on path operations?
  → Class K. artifact_dir (or similar path arg) is None. LangGraph is the third
    runtime — check docs/governance/runtime_boundary_map.md before applying
    Hermes/OpenClaw diagnostic patterns.
```

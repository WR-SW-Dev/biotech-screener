     1|---
     2|name: openclaw-data-pipeline-debug
     3|description: "Diagnose data pipeline and signal health failures in the OpenClaw biotech screener. Covers press release feed contamination, agent path/default bugs, builder-vs-summarizer memory gaps, IC ALERT two-frame confirmation protocol, and the single-snapshot cascade failure pattern."
     4|when_to_use: "production_qa flags classifier_escalation_pool FAIL, an agent escalates unexpectedly despite data existing, fleet shows FAIL on an agent that has fresh artifacts, ic_health_monitor raises ALERT on a load-bearing signal, or data_auditor shows a cascade of ERROR checks all from a single missing snapshot."
     5|---
     6|
     7|# OpenClaw Data Pipeline Debugger
     8|
     9|For the biotech screener at `/mnt/c/Projects/biotech_screener/biotech-screener`.
    10|Diagnose-only. Never modify production data, rulesets, or scoring code.
    11|
    12|---
    13|
    14|## Hard rules
    15|
    16|- FACT vs INFERENCE must be separated explicitly.
    17|- Scoring path (B6 selector, ranker, snapshot) is governed. Do NOT recommend
    18|  weight changes or ruleset modifications without a formal Spec-style writeup.
    19|- Governance ceiling applies to all IC ALERT findings.
    20|
    21|---
    22|
    23|## Failure taxonomy
    24|
    25|### Class A — GlobeNewswire keyword-search ticker collision (press release feed contamination)
    26|
    27|**Signature:** `production_qa` flags `classifier_escalation_pool FAIL` with
    28|`other_share > 50%` threshold. Pool grows linearly over days (e.g. 73 → 139 → 345 → 408 → 429).
    29|Headlines in the pool are clearly off-topic for the ticker (other companies' names).
    30|
    31|**Root cause (confirmed 2026-05-02):** `tools/fetch_company_press_releases.py` falls back
    32|to `https://www.globenewswire.com/Search?keyword=TICKER` for tickers without a configured
    33|`company_ir_url`. GNW keyword search does substring matching with no issuer filter, no CIK
    34|match. Short/common tickers (TECH, LAB, DRUG, DAWN, RARE) match massive off-topic volume.
    35|300/341 universe tickers (88%) had no `company_ir_url` configured — all using keyword fallback.
    36|`build_event_feedback.py` line ~226 accepts `category="other"` items into the pool.
    37|
    38|**Diagnostic chain:**
    39|
    40|```bash
    41|# 1. production_qa flag -> check hard collisions sample
    42|ls -lt artifacts/production_qa/ | head -5
    43|cat artifacts/production_qa/<latest>_report.json | python3 -c "
    44|import json,sys; r=json.load(sys.stdin)
    45|print(r.get('classifier_escalation_pool', {}))
    46|"
    47|
    48|# 2. Sample headlines for the flagged tickers
    49|cat artifacts/production_qa/hard_collisions_*.json | head -30
    50|
    51|# 3. Count unconfigured tickers (keyword fallback candidates)
    52|python3 -c "
    53|import json
    54|d = json.load(open('production_data/company_ir_sources.json'))
    55|no_url = [t for t,v in d.items() if not v.get('company_ir_url')]
    56|print(f'{len(no_url)}/{len(d)} tickers without company_ir_url (all use keyword fallback)')
    57|"
    58|
    59|# 4. Confirm GNW keyword URL pattern in fetch code
    60|grep -n "keyword\|Search\|globenewswire" tools/fetch_company_press_releases.py | head -10
    61|
    62|# 5. Check if scoring path is contaminated
    63|grep -n "event_feedback\|press_release\|other" run_screen.py | head -10
    64|# Scoring path (rankings.csv, B6 selector) confirmed NOT contaminated if press releases
    65|# feed only into event_feedback, not into catalyst_events or scoring inputs
    66|```
    67|
    68|**Recommended fixes (governance review required before applying):**
    69|- Post-fetch body sanity filter: drop headline if company name absent from body
    70|- Add `category != "other"` guard in `build_event_feedback.py` line ~226
    71|- Backfill `company_ir_url` for unconfigured tickers in `company_ir_sources.json` — see Class A1 below for the validated two-pass technique
    72|- Replace GNW keyword search with issuer-ID queries (`?orgId=`) for registered tickers
    73|
    74|**CRITICAL — IR URL fix is forward-looking; pool lag is expected:**
    75|After populating `company_ir_sources.json` with real IR URLs, `production_qa` will
    76|still show `classifier_escalation_pool FAIL` on the next run. The pool is built from
    77|articles already fetched and classified under the old GNW keyword fallback. The fix
    78|only affects NEW fetches. To clear the pool, re-run the press release fetcher:
    79|
    80|```bash
    81|# Launch as background job (all 341 tickers, may take 30-60 min)
    82|# mcp_terminal(background=True, notify_on_complete=True,
    83|#   command="cd .../biotech-screener && python3 tools/fetch_company_press_releases.py \
    84|#     --as-of-date $(date +%F) > artifacts/fetch_press_releases_$(date +%F).log 2>&1")
    85|# Then re-run production_qa to verify other_share dropped below 50%
    86|python3 tools/production_qa_check.py 2>&1 | tail -15
    87|```
    88|
    89|**Pool drain is not immediate — 2-5 nightly cron runs required:**
    90|After populating IR URLs and re-fetching, `production_qa` will STILL show
    91|`classifier_escalation_pool FAIL` at the same other_share (confirmed: 56.1% unchanged
    92|after full 341-ticker re-fetch on 2026-05-06). The classified pool is additive — new
    93|clean articles are appended, but old "other" articles from GNW keyword fetches remain.
    94|The pool drains as the floor date advances and as new clean articles dilute the old junk.
    95|Estimated clearance: 2-5 nightly cron runs for tickers that now have proper IR URLs.
    96|Structurally unresolvable word-collision tickers (TECH, DRUG, DNA, etc.) will continue
    97|contributing "other" articles indefinitely until manual IR URLs are added.
    98|
    99|**Audit classified JSONL: use `event_category` field, not `category`:**
   100|Records in `data/press_releases/classified/classified_*.jsonl` use `event_category`
   101|as the top-level classification field (not `category`). Using `category` returns `"?"`
   102|for all records. Check schema with `json.loads(lines[0]).keys()` before counting.
   103|
   104|```python
   105|# Correct field name for classified pool analysis:
   106|from collections import Counter
   107|cats = Counter(r.get("event_category","?") for r in records)
   108|other = [r for r in records if r.get("event_category") == "other"]
   109|```
   110|
   111|**Audit doc:** `docs/audit/2026-05-02_press_release_collision.md` (SHA 955aa2ce)
   112|
   113|---
   114|
   115|### Class A1 — IR URL population (company_ir_sources.json backfill)
   116|
   117|**When:** `company_ir_sources.json` has empty `company_ir_url` for 50+ tickers and
   118|`classifier_escalation_pool` is failing. Produces real issuer-specific IR URLs to
   119|replace the noisy GNW keyword-search fallback.
   120|
   121|**Script:** `tools/populate_ir_sources.py` (written 2026-05-06, confirmed working).
   122|Two-pass strategy validated on FDMT, KYMR, IMVT:
   123|
   124|**Pass 1 — EDGAR XBRL namespace extraction:**
   125|EDGAR 8-K `.txt` files embed XBRL namespaces of the form
   126|`xmlns:co="http://www.company.com/20260325"` — this is the canonical company domain,
   127|reliably present in ~90% of biotech 8-K filings.
   128|
   129|```
   130|EDGAR company_tickers.json → CIK per ticker
   131|  → data.sec.gov/submissions/CIK{padded}.json → find latest 8-K accession numbers
   132|  → /Archives/edgar/data/{cik}/{acc_nodash}/{acc}.txt → extract XBRL xmlns domain
   133|  → probe IR paths on that domain (IR subdomains first, then company domain paths)
   134|  → require keyword match ("press release", "news release", "announcements") to confirm
   135|```
   136|
   137|Key pitfalls:
   138|- EDGAR `website` and `investorWebsite` fields in submissions JSON are almost always empty for biotechs — don't use them.
   139|- GNW `.com/issuer/TICKER` 404s. GNW org IDs in URL are per-release-ID, not per-company.
   140|- GNW `/Search?keyword=TICKER` redirects (301) to `/en/search/keyword/TICKER` — use the redirect target directly.
   141|- Probe IR subdomains (`investors.company.com`, `ir.company.com`) BEFORE company domain paths — subdomain hit rate is higher and company domain `/ir` paths often redirect to non-IR pages.
   142|- Require a keyword match on the probed page, not just a 200 response. Short `/ir` paths redirect to science/research pages for some biotechs (confirmed: KYMR `kymeratx.com/ir` → science page; `investors.kymeratx.com/investor-relations` → correct IR page).
   143|- CRITICAL — skip entire subdomain on first SSL/timeout error. When `investors.X.com` gets SSLError or ReadTimeout, all remaining paths on that subdomain will also fail. Naively probing all 13 paths = 75s stall per ticker (confirmed: `investors.crisprtx.com`). Group candidates by netloc and set a `skip_base` flag on first connection failure. Use timeout=5s, not 8-10s. See `references/ir_url_population.md` for implementation pattern.
   144|
   145|**Pass 2 — GNW search → JSON-LD fallback:**
   146|For tickers where EDGAR XBRL didn't yield a domain (e.g. no recent 8-Ks, exotic filers):
   147|
   148|```
   149|GET https://www.globenewswire.com/en/search/keyword/{TICKER}   (note: /Search?keyword redirects here)
   150|  → extract /news-release/YYYY/MM/DD/{release_id}/0/en/{slug} links
   151|  → match slug against ticker/company name
   152|  → fetch release page → parse JSON-LD author.url → company domain
   153|  → probe IR paths same as Pass 1
   154|```
   155|
   156|**IR probe path ordering (tier 1 before tier 2):**
   157|```
   158|Tier 1: investors.company.com, investor-relations.company.com, ir.company.com
   159|         × each of: /investors/news-releases, /investor-relations/news-releases,
   160|                    /investors/press-releases, ..., /ir/press-releases, /investors, /ir
   161|Tier 2: company.com × same path list
   162|```
   163|
   164|**Tool selection — IMPORTANT:**
   165|Use `tools/populate_ir_sources.py` (XBRL + GNW JSON-LD). NOT `tools/populate_ir_urls.py`.
   166|The latter uses EDGAR `investorWebsite` field (empty for ~100% of biotechs) + HEAD slug probing
   167|that hangs on WSL2 Cloudflare blocks. Both scripts exist; `populate_ir_urls.py` produces 0 results.
   168|
   169|**Usage:**
   170|```bash
   171|# Smoke test one ticker first (confirm connectivity, ~15s)
   172|python3 tools/populate_ir_sources.py --ticker VRTX --verbose
   173|
   174|# Full dry run → review → then apply (300 tickers ~90-120 min)
   175|# Launch as background terminal job (not Hermes cron — this is a one-shot network job)
   176|# Use mcp_terminal with background=True and notify_on_complete=True
   177|# mcp_terminal(background=True, notify_on_complete=True, timeout=600,
   178|#   command="cd /mnt/c/.../biotech-screener && python3 tools/populate_ir_sources.py --dry-run > artifacts/ir_url_population_run_$(date +%F).log 2>&1")
   179|# Poll while running:
   180|#   mcp_process(action='poll', session_id=<proc_id>)
   181|#   tail -5 artifacts/ir_url_population_run_$(date +%F).log   # see current ticker + hit count
   182|#   grep -c "IR URL = " artifacts/ir_url_population_run_$(date +%F).log  # running hit count
   183|
   184|# Pass 1 only (skip GNW fallback)
   185|python3 tools/populate_ir_sources.py --pass1-only
   186|
   187|# Apply (writes to company_ir_sources.json — operator review required first)
   188|python3 tools/populate_ir_sources.py
   189|```
   190|
   191|**DO NOT use `terminal(background=True)` from mcp_execute_code** -- that route is
   192|blocked ("User denied"). Use `mcp_terminal` directly with `background=True`.
   193|
   194|**Heredoc pitfall:** Python heredocs (`<< 'EOF' ... EOF`) inside `terminal()` calls
   195|from `mcp_execute_code` return empty output silently. Write complex Python audit
   196|logic to a temp `.py` file with `mcp_write_file`, then run it with a plain
   197|`terminal("python3 tools/myaudit.py", ...)` call. This applies to any multi-line
   198|Python script passed via heredoc — confirmed broken in 2026-05-06 session (3 empty
   199|results before switching to file-write approach).
   200|
   201|Output: updates `production_data/company_ir_sources.json` in place + writes
   202|`artifacts/ir_url_population_YYYY-MM-DD.md` with per-ticker results and method breakdown.
   203|
   204|**Expected hit rate (confirmed from full 300-ticker run 2026-05-06):**
   205|Pass 1 (EDGAR XBRL): 192/300 = 64%. Large-caps trend higher; small-cap/recent IPO filers
   206|have sparser 8-K XBRL history, pulling the rate down from theoretical 75-85%.
   207|Pass 2 (GNW JSON-LD): 87 additional = combined 279/300 (93%) newly populated.
   208|Remaining 21 (7%) had `ir_url: None` after both passes — delisted, shell co, or
   209|non-GNW filers. Still empty after full run: set their `company_ir_url` to `null`
   210|explicitly so the fallback is intentional rather than accidental.
   211|
   212|**IMPORTANT — Pass 2 junk-domain contamination:**
   213|55 of the 87 Pass 2 hits used `gnw_jsonld_domain` method (domain root, IR probe failed).
   214|~20 of those 55 are junk: law firm sites, market research spam, and ticker collisions
   215|(e.g. `gildan.com` for ticker GILD). Run a cleanup filter BEFORE committing the applied
   216|results. Reject `gnw_jsonld_domain` entries whose domain contains none of the ticker
   217|string or company name words.
   218|
   219|After the full 2026-05-06 run: 9 confirmed wrong-company URLs assigned (bad) + 2
   220|borderline cases (NBP=novabridge, GHRS=domain-root-only) = 11 tickers to null out
   221|after `--apply`. Full confirmed null list and audit script in `references/ir_url_population.md`.
   222|
   223|**Word-collision tickers are structurally unresolvable — null them, don't use domain root:**
   224|Common-word tickers (TECH, DRUG, RARE, LAB, DNA, RNA, VIR, IRON, BEAM, ALT, etc.) flood
   225|GNW keyword search and make GNW JSON-LD unreliable (GNW releases match the word, not the
   226|company). The `gnw_jsonld_domain` fallback for these tickers almost always returns a wrong
   227|company's domain. EDGAR XBRL works better (confirms pass 1 results for RARE, LAB, BEAM,
   228|ALT, COLL, MRNA, EDIT, GLUE, VERA) but some (TECH→tech.com, DNA→no 8-Ks) fail at XBRL
   229|too. For any gnw_jsonld_domain entry where the domain is clearly a wrong company, explicitly
   230|null it — don't leave the wrong domain in the JSON, as it will be fetched and produce more
   231|"other" articles than the GNW keyword fallback would.
   232|
   233|Confirmed wrong gnw_jsonld_domain assignments from 2026-05-06 run:
   234|  TECH  → ownify.com         (not Bio-Techne)
   235|  DRUG  → researchandmarkets.com (not Bright Minds)
   236|  DNA   → delveinsight.com   (not Ginkgo Bioworks)
   237|  VIR   → virtualinvestorconferences.com (not Vir Biotechnology)
   238|  RNA   → ir.madrigalpharma.com = MDGL, not Avidity Biosciences
   239|  DAWN  → dawnproject.com    (not Day One Biopharma)
   240|  JAZZ  → usmint.gov         (not Jazz Pharmaceuticals)
   241|
   242|**Rate limit:** 1.5s between requests. EDGAR best practice: include
   243|`User-Agent: WakeRobinBiotechScreener research@wakerobincapital.com` header.
   244|
   245|**Observed runtime:** ~18s/ticker (EDGAR calls + subdomain probing + rate limit).
   246|300 tickers = 90-120 min. Launch as background job; laptop sleep will kill it.
   247|
   248|**Verify improvement after run:**
   249|```bash
   250|# Check new populated count
   251|python3 -c "
   252|import json
   253|data = json.load(open('production_data/company_ir_sources.json'))
   254|sources = data['sources']
   255|populated = sum(1 for e in sources if e.get('company_ir_url','').strip())
   256|print(f'{populated}/{len(sources)} populated ({populated/len(sources)*100:.1f}%)')
   257|"
   258|# Then run production_qa to check if classifier_escalation_pool other_share drops below 50%
   259|```
   260|
   261|---
   262|
   263|### Class B — Agent escalates despite data existing (default None path bug)
   264|
   265|**Signature:** An agent reports "no data found" and escalates to ops, but the actual
   266|data file exists at a non-default path. Agent ran correctly but used a wrong default.
   267|
   268|**Confirmed instance (2026-05-03):** `bioshort_watch` reported "no portfolio data" and
   269|entered escalation loop instructing ops to "run the data pipeline." Root cause:
   270|`tools/biotech_hedge_report.py --portfolio-csv` defaults to `None` at line ~2910.
   271|With None, `load_portfolio_weights()` falls through to repo-root `rankings.csv`
   272|(a 3-line TEST2 stub fixture). Actual production data lived at
   273|`data/snapshots/2026-05-01/portfolio_positions.csv`.
   274|
   275|**Diagnostic chain:**
   276|
   277|```bash
   278|# 1. Confirm the data actually exists
   279|ls -lt data/snapshots/*/portfolio_positions.csv | head -5
   280|ls -lt production_data/rankings_full.csv 2>/dev/null
   281|
   282|# 2. Find the default arg in the tool
   283|grep -n "\-\-portfolio-csv\|portfolio_csv\|default.*None" tools/biotech_hedge_report.py | head -10
   284|
   285|# 3. Trace the fallback path
   286|grep -n "load_portfolio_weights\|rankings.csv\|fallback" tools/biotech_hedge_report.py | head -15
   287|
   288|# 4. Check what repo-root rankings.csv actually contains
   289|head -5 rankings.csv 2>/dev/null  # often a test fixture, not production data
   290|
   291|# 5. Check staleness of agent's prior outputs
   292|ls -lt output/hedge_report/ | head -5  # or artifacts/bioshort_watch/
   293|```
   294|
   295|**Resolution pattern:**
   296|- Short-term: update the cron prompt to explicitly pass `--portfolio-csv data/snapshots/$(ls -t data/snapshots/ | head -1)/portfolio_positions.csv`
   297|- Long-term (code fix, owner required): auto-discover latest `data/snapshots/YYYY-MM-DD/portfolio_positions.csv` when `--portfolio-csv` is None
   298|
   299|**General rule:** When any agent escalates "no data" unexpectedly, check BOTH the declared
   300|default path AND the most recent production snapshot before concluding data is absent.
   301|
   302|---
   303|
   304|### Class C — Builder runs / summarizer silent (memory gap without artifact gap)
   305|
   306|**Signature:** Fleet receipt shows FAIL/STALE for agent X. But:
   307|- `artifacts/X/YYYY-MM-DD_*` files are fresh (builder ran correctly today)
   308|- `agents/X/memory/` is empty or 28+ days stale
   309|- Invocation logs show the builder cron fired
   310|
   311|This is a two-problem tangle: a plumbing gap (memory-write not triggered) masking
   312|whether the underlying signal is healthy.
   313|
   314|**Confirmed instances (2026-05-03):**
   315|- `calibration_evidence`: memory/ completely empty (zero files ever), artifacts fresh
   316|- `shadow_monitor`: memory/ had one file from 2026-04-03 (28d stale), artifacts fresher
   317|- `ic_health_monitor`: memory/ empty by design — actual output at `artifacts/ic_dashboard/`
   318|
   319|**Diagnostic chain:**
   320|
   321|```bash
   322|# Three-axis check (run all three before concluding)
   323|# Axis 1: what receipt sees (memory mtime)
   324|ls -t agents/<name>/memory/*.md | head -3
   325|
   326|# Axis 2: what agent actually produces (artifact mtime)
   327|ls -lt artifacts/<name>/ | head -5
   328|# For ic_health_monitor specifically:
   329|ls -lt artifacts/ic_dashboard/ | head -5
   330|
   331|# Axis 3: did cron actually fire? (invocation log)
   332|ls -lt logs/agents_direct/<name>_*.json | head -5
   333|
   334|# Verdict matrix:
   335|# memory-stale + artifacts-fresh + invocations-fresh → CODE BUG in memory-write step
   336|# memory-stale + artifacts-stale + invocations-fresh → agent crashes mid-run
   337|# memory-stale + artifacts-stale + no-invocations   → schedule problem (cliff/crontab)
   338|```
   339|
   340|**Agent-specific notes:**
   341|- `ic_health_monitor`: memory/ is empty BY DESIGN. Real output = `artifacts/ic_dashboard/`.
   342|  Do NOT attempt to fix the memory-write; the design is intentional.
   343|- `calibration_evidence`: resolved via Friday 19:00 `build_calibration_evidence.py` cron
   344|  + catch-up scripts. If memory still empty after builder runs, the summarizer LLM agent
   345|  is not being triggered post-build.
   346|- `shadow_monitor`: memory-write bug is a code issue, not infrastructure. Tag as spec ticket.
   347|
   348|**Escalation:** If artifacts are fresh but memory is empty AND the builder/summarizer
   349|architecture is two separate processes, check whether the heartbeat_checks.py or cron
   350|schedule triggers the summarizer after the builder completes.
   351|
   352|---
   353|
   354|### Class D — IC ALERT two-frame confirmation and governance ceiling
   355|
   356|**Signature:** `ic_health_monitor` flags a load-bearing signal as `health: ALERT`
   357|(mean_ic negative, hit_rate < 20%). Independently confirmed by calibration_evidence
   358|event-conditioned IC for the same signal. TWO independent measurement frames confirming
   359|the same degradation.
   360|
   361|**Active confirmed instance (as of 2026-05-04):** `inst_delta_z`
   362|- ic_health_monitor: mean_ic = -0.101, hit_rate = 8.6%, n=35 dates → ALERT
   363|- calibration_evidence: event-conditioned IC = -0.244, 75 postmortems
   364|- Role: primary within-top-30 ranker discriminator (NW-t=+3.32 in backtest), component
   365|  of B6 selector (coinvest 65% + inst_delta 35%)
   366|- Degradation onset: ~late February 2026 (check history.jsonl for inflection date)
   367|
   368|**Diagnostic chain:**
   369|
   370|```bash
   371|# 1. Read the IC dashboard
   372|cat artifacts/ic_dashboard/$(ls -t artifacts/ic_dashboard/ | head -1) | python3 -c "
   373|import json,sys
   374|d=json.load(sys.stdin)
   375|for sig, v in d.get('signals', {}).items():
   376|    if v.get('health') in ('ALERT','WARN'):
   377|        print(sig, v.get('health'), v.get('mean_ic'), v.get('hit_rate'))
   378|"
   379|
   380|# 2. Read calibration evidence for the same signal
   381|grep -A 5 "inst_delta" artifacts/calibration_evidence/$(ls -t artifacts/calibration_evidence/*.md | head -1)
   382|
   383|# 3. Check inflection date in history
   384|grep "inst_delta" artifacts/ic_dashboard/history.jsonl | tail -30
   385|
   386|# 4. Two-frame verdict: if BOTH frames show degradation → CONFIRMED
   387|# If only one frame → WATCH (wait for second frame to confirm or contradict)
   388|
   389|# 5. Check if degradation is component or bundle-level
   390|# B6 selector validates as BUNDLE (coinvest + inst_delta together, t=2.57, 67 periods)
   391|# A component going negative does not automatically invalidate the bundle
   392|# Per CLAUDE.md: "Neither component survives standalone, but the bundle is real"
   393|```
   394|
   395|**CHECK RANKER BEFORE ESCALATING SELECTOR:** Before recommending selector changes,
   396|confirm whether the flagged signal is already excluded from the ranker. In this codebase,
   397|the selector (`A4_SELECTOR_CONFIG` in run_screen.py) and the ranker (`PRODUCTION_RANKER_V2_CONFIG`)
   398|are separately configured. A signal can be anti-predictive in the selector while already
   399|being a "dead feature" in the ranker. Confirmed 2026-05-04: inst_delta_z was already
   400|excluded from the ranker (run_screen.py:157 comment "dead features: inst_delta_z, catalyst_decay_w,
   401|binary_quality_score added noise") before we zeroed it in the selector. Checking this first
   402|avoids redundant ranker fixes.
   403|
   404|```bash
   405|grep -n "inst_delta_z\|coinvest\|dead features" run_screen.py | head -20
   406|```
   407|
   408|**Full governance+promotion workflow:** once two-frame confirmation is established, load the `signal-shared-regime-check` skill. It has the comparator probe script (`scripts/shared_regime_check.py`), the governance memo template, and the full ruleset promotion sequence (run_screen.py patch → new ruleset JSON → PHASE2_PINNED_RULESET_ID → CLAUDE.md). Do not re-derive this workflow ad-hoc — the skill has the exact steps confirmed from the 2026-05-04 inst_delta_z case.
   409|
   410|**GOVERNANCE CEILING:** Do NOT recommend ruleset changes, weight adjustments, or signal
   411|demotion without a formal Spec-style writeup reviewed by the operator. Standard response:
   412|
   413|```
   414|ESCALATION PACKET for ops + sentinel:
   415|  Signal:        inst_delta_z
   416|  Surface:       ic_health_monitor ALERT + calibration_evidence confirmation
   417|  Ruleset:       2a3e79eb (v1.13.0) — B6 selector 35% inst_delta weight
   418|  mean_ic:       -0.101 (35 dates)
   419|  hit_rate:      8.6%
   420|  event-IC:      -0.244 (75 postmortems)
   421|  Inflection:    ~2026-02-28 (check history.jsonl)
   422|  
   423|Read-only diagnostics recommended (no code changes):
   424|  - Correlation check: inst_delta_z vs coinvest_z (regime correlation shift?)
   425|  - In-sample tail comparison: are bad-IC dates clustering in bull regime?
   426|  - Per-date decomposition: is degradation uniform or event-type-specific?
   427|  - Feed contamination check: inst_delta data source freshness (13F filing lag?)
   428|
   429|Do NOT modify ruleset or weights. Governance review required.
   430|```
   431|
   432|---
   433|
   434|### Class E — Single missing snapshot triggers multi-check cascade
   435|
   436|**Signature:** `data_auditor` shows `verdict: FAIL` with `archive_verification: FAIL`
   437|PLUS multiple `ERROR` entries on universe_ipo_consistency, pit_financials_freshness,
   438|financial_consistency, price_data_gaps — all from the same date. These are NOT
   439|independent failures; they all cascade from one missing `rankings.csv`.
   440|
   441|**Root cause:** Each of those checks tries to load `rankings.csv` for the flagged date
   442|as its first step. If rankings.csv is absent (production didn't run), all four checks
   443|return `ERROR: "Cannot load rankings.csv for YYYY-MM-DD"`. They share a single upstream
   444|dependency.
   445|
   446|**Triage — treat as a SINGLE failure, not four:**
   447|
   448|```bash
   449|# Confirm the single root
   450|ls data/snapshots/YYYY-MM-DD/rankings.csv 2>/dev/null || echo "MISSING — all cascade errors are from this"
   451|
   452|# Check if date was a weekday (if weekend: expected, see Class E in cron skill)
   453|python3 -c "
   454|import datetime
   455|d = datetime.date.fromisoformat('YYYY-MM-DD')
   456|print('WEEKDAY' if d.weekday() < 5 else 'WEEKEND — no production expected')
   457|"
   458|
   459|# Real health signal: check the checks that DON'T depend on rankings.csv
   460|# pit_validation_sweep and edgar_coverage are independent — if BOTH pass, data is clean
   461|cat artifacts/data_auditor/integrity_report_YYYY-MM-DD.json | python3 -c "
   462|import json,sys; r=json.load(sys.stdin)
   463|for k,v in r['checks'].items():
   464|    if k in ('pit_validation_sweep','edgar_coverage'):
   465|        print(k, v['status'])
   466|"
   467|# PASS on both → data substrate is clean, cascade is cosmetic until next production run
   468|```
   469|
   470|**Resolution:** All cascade ERRORs self-resolve once the next production run completes.
   471|For a missed weekday: check cron.log, identify root cause (WSL2 cliff, crontab REPLACE),
   472|consider manual backfill if the gap is business-critical.
   473|
   474|---
   475|
   476|### Class F — run_agent_direct.py architectural mismatch for tool-dependent agents
   477|
   478|**Signature:** Agent crontab entry fires (SCAN or HEARTBEAT), log shows agent "ran"
   479|and wrote a JSON response, but no artifact was produced and the agent reports
   480|"XAI_API_KEY not found" or "cannot check filesystem". Agent appears to run but
   481|produces nothing.
   482|
   483|**Root cause (confirmed 2026-05-04):** `tools/run_agent_direct.py` is a **plain
   484|Anthropic SDK text call with no tool execution**. It sends a message and receives
   485|text — it does NOT execute bash commands, Python scripts, or API calls that the
   486|agent writes in its response. Agents designed to run under OpenClaw's gateway
   487|(which provides real bash tool execution) will "hallucinate" shell commands in
   488|their response text that never actually run.
   489|
   490|Confirmed affected agent: `grok_biotech_watch`. Its SOUL.md was designed for
   491|OpenClaw's bash tooling. When invoked via `run_agent_direct.py`:
   492|- `env | grep XAI` returns nothing (no real shell)
   493|- `XAI_API_KEY` is in `.env` and loaded into `os.environ` by main() but the
   494|  agent's bash calls in the response text never execute
   495|- Agent writes "HEARTBEAT: FAIL — no XAI_API_KEY" because its preflight bash
   496|  call never ran
   497|
   498|**Diagnostic confirmation:**
   499|
   500|```bash
   501|
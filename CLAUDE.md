# CLAUDE.md — Wake Robin Capital Management Biotech Screener

## Project Identity
This is an institutional-grade biotech investment screening system.
Outputs must be reproducible, auditable, and deterministic.
Every decision must be traceable to a data source with a timestamp.

## North Star Rule
Backtest systems NEVER directly modify production screening behavior.
They produce evidence and proposals only. Governance review required before
any backtest finding changes a production signal weight.

## CCFT Principles (Non-Negotiable)
All data fixtures must be:
- Canonical: single authoritative source per data type
- Complete: no silent nulls or missing fields without explicit flags
- Frozen: historical snapshots are immutable once written
- Timestamped: data_available_timestamp <= as_of_date always enforced

## Active Ruleset
- **ID**: `8887576e` (v1.14.0)
- **File**: `production_data/decision_rulesets/v1.14.0_coinvest_only_selector.json`
- **Key settings**: sort_anchor=selector_score, coinvest-only selector (coinvest_score_z 100%), pairwise_minimal ranker (ordinal-only), EW Top-30. inst_delta_z zeroed in selector 2026-05-04 (ALERT: mean_ic=-0.097, two-frame confirmed).
- **Prior ruleset**: `2a3e79eb` (v1.13.0) — RETIRED 2026-05-04
- **Pinned in**: `run_screen.py` AND `run_phase2_snapshot_delta.py` (must stay in sync)
- **Manifest**: 36+ entries, no dup IDs

---

## Current Operating Truths

Spec 050 (2026-04-03) replaced the old optionality-anchored selector with a two-stage
selector/ranker architecture. Checklist v2 rerun (2026-04-04) revalidated the live stack
under the Spec 055 statistical bar (FM, bootstrap, FDR, LOSO).

> **Production mental model: coinvest selects (sole institutional signal as of v1.14.0), financial penalizes
> "safe but less catalytic" names, and clinical is a weak/conditional feature under review.**
> inst_delta_z zeroed in selector 2026-05-04 (ALERT two-frame confirmed; governance log filed).

1. **B6 selector + pairwise_minimal ranker (ordinal-only) + EW Top-30 is production.** True PIT backtest: +2.34pp/mo net-of-cost, t=2.57, 69% hit rate, 67 monthly periods (Jun 2020 — Apr 2026).
2. **B6 selector validated under Checklist v2.** Bootstrap: +2.42pp/mo, 95% CI [1.25%, 3.70%], P(>0)=99.99%. LOSO: ROBUST across all dimensions. Neither component survives standalone, but the bundle is real.
3. **Selector and ranker learn different structure.** B6 selector runs coinvest_score_z at 100% weight (coinvest-only since v1.14.0; inst_delta_z zeroed 2026-05-04, ALERT: mean IC = -0.097 over 36 dates). Within top-30: inst_delta is the dominant positive discriminator (NW-t=+3.32), financial_score is a true negative penalty (NW-t=-3.41), coinvest washes out (+0.49). inst_delta_z excluded from ranker since Spec 051.
4. **Pairwise ranker is ordinal-only.** ECE=0.129 (POOR calibration). No rank-weighting, no confidence sizing. Equal-weight is the correct construction.
5. **EW Top-30 is the correct construction.** RW-EW = -0.09pp, t=-0.95. Pairwise calibration confirms.
6. **K=30 validated by sweep.** Net-of-cost peak at +2.34pp, stable K=25-35 plateau.
7. **Bear/neutral alpha engine.** Bear: +3.37pp (75% hit), neutral: +6.23pp (93% hit), bull: -0.37pp (50% hit). Worst months are all bull regime.
8. **event_type_score is the only 5/5 Checklist v2 pass.** Use as overlay/diagnostic/sizer only — does NOT improve B6 bundle.
9. **insider_exec and aact_execution downgraded.** Both 1/5 under Checklist v2. Shadow only.
10. **Forward shadow accumulating daily** (7 arms in coinvest_shadow_tracker v2, wired into run_daily.py).

---

## Trust Buckets

### Safe to use now (production-grade evidence)
- **B6 selector + pairwise_minimal ranker (ordinal-only) + EW Top-30**: true PIT validated, t=2.57, 67 periods
- **B6 bundle revalidated under Checklist v2** (2026-04-04): bootstrap CI [1.25%, 3.70%], LOSO ROBUST
- **Pairwise ordinal-only policy**: ECE=0.129, no rank-weighting or confidence sizing
- Selector engine (`selector_engine.py`), ranker engines (`ranker_engine.py`, `ranker_v2_pairwise.py`): 48+ tests
- Statistical QA package (`common/stats/`): FM, bootstrap, FDR, LOSO, calibration — 36 tests
- PIT validation audit framework, PIT financial regeneration infrastructure
- K=30 validated by sweep (stable K=25-35 plateau)
- Forward shadow tracker (7 arms, wired into daily cron)
- event_type_score as overlay/diagnostic (5/5 Checklist v2 pass, but not selector weight)

### Deprecated (do not cite)
- **All survivorship-only benchmark numbers** (+93.7pp, +110.5pp, etc.)
- **Old optionality-anchored selector** — underwater on PIT data (-25pp cumulative)
- **DEFAULT selector weights** (clinical 35%, catalyst 25%) — destructive as selector (-0.53pp)
- **clinical_score_v2_z as selector anchor** — negative delta (-0.68pp), universally destructive
- **Pre-Checklist-v2 signal card t-stats** — superseded by FM/bootstrap/FDR/LOSO findings
- **insider_exec_buy_value_90d optimistic reads** — 1/5 under Checklist v2, FRAGILE
- **aact_execution_score optimistic reads** — 1/5 under Checklist v2, bear-unstable
- Any promotion memo citing pre-Spec-050 selector performance
- "Bear IR 3.35" regime story from contaminated data
- **Any ranker IC claim based on composite_score** (Spec 095, 2026-05-13) — measured the wrong score field, misattributed

### Current evidence hierarchy
1. **Checklist v2 rerun (2026-04-04)**: B6 bundle bootstrap+LOSO validated — STRONGEST (for signals)
2. **True PIT backtest (Spec 050)**: A4+ranker +2.34pp net, t=2.57 — STRONGEST (for portfolio)
3. **Pairwise feature audit (2026-04-04)**: within-top-30 FM on ranker features — SUPPORTING
4. **Forward shadow**: accumulating daily since 2026-04-03 — MONITORING
5. **Old PIT benchmark (Spec 048)**: optionality selector underwater — SUPERSEDED by new selector

---

## Do Not Reopen Without New Evidence

These lanes have been tested and either died or were superseded. Do not spend research
hours here unless genuinely new data or a structural model change creates a reason to revisit.

| Lane | Status | Why closed |
|------|--------|------------|
| Options surface-shape as systematic ranker | DEAD | 50-month backtest IC negative at all horizons |
| Options-as-alpha (Spec 053) | CLOSED | 37 signals tested, ALL fail as selector/ranker |
| Static execution features (Spec 054) | CLOSED | PCD overdue, update recency, pipeline velocity all noise/destructive |
| Clinical composites as ranker (Spec 055) | CLOSED | Negative across ALL robustness slices, universally destructive |
| `total_volume_z` | DEAD | IC=-0.10 on PIT-native data (109 obs) |
| Always-on rank-weighting (Top-20 or Top-30) | NOT PROMOTED | RW-EW = -0.09pp; pairwise ECE=0.129 confirms ordinal-only |
| Confidence/rank-weighted sizing | NOT JUSTIFIED | Pairwise scores not calibrated (ECE=0.129) |
| `insider_exec_buy_value_90d` | SHADOW ONLY | 1/5 Checklist v2, FRAGILE robustness |
| `aact_execution_score` | SHADOW ONLY | 1/5 Checklist v2, bear-unstable (-1.86pp) |
| Top-20 / pruner promotion story | DEPRECATED | PIT-financial correction shows both underwater vs XBI |
| Historical alpha narrative (+93pp / +110pp) | DEPRECATED | Inflated by financial look-ahead contamination |
| `cal_alpha` | REMOVED in v1.12.0 | Confirmed no-op, zero deltas at all horizons |
| Clinical sort signal | OFF | Insufficient IC, destructive as selector |
| Coinvest as standalone sort signal | SUPERSEDED | Now used as B6 selector anchor; standalone only 3/5 Checklist v2 |
| Quality tiebreaks (Specs 030/031) | EXHAUSTED | All economically immaterial |
| 91-180d drawdown gate | DEAD | Counterproductive at all thresholds |
| Dynamic caps | DEAD | Identical to plain EW |
| Fixed sleeve budgets | RETIRED | Primary construction damage mechanism (+153.6pp drag) |

---

## Current Promotion Story

1. **Coinvest-only selector + pairwise_minimal ranker (ordinal-only) + EW Top-30 is production (v1.14.0).** B6 selector now coinvest_score_z 100% (inst_delta_z zeroed 2026-05-04, ALERT: mean_ic=-0.097 over 36 dates; reinstatement conditions in governance log). Original B6 bundle (coinvest 65% + inst_delta 35%) validated in true PIT backtest: +2.34pp/mo net-of-cost, t=2.57, 69% hit rate, 67 monthly periods.
2. True PIT evidence: +2.34pp/mo net, t=2.57, 69% hit, beats XBI on return and risk.
3. **B6 bundle passes Checklist v2**: bootstrap +2.42pp/mo, CI [1.25%, 3.70%], LOSO ROBUST. Bundle > parts.
4. **Pairwise ordinal-only confirmed**: ECE=0.129. Do not rank-weight or confidence-size.
5. **Within-cohort roles clear**: coinvest selects (sole institutional signal, v1.14.0), financial penalizes safe names. inst_delta_z zeroed in selector — reinstatement pending IC recovery.
6. **event_type_score**: 5/5 Checklist v2 but overlay only — does not improve B6 bundle.
7. **Forward shadow is the validation layer.** 7 arms accumulating daily. Evaluate after 30 trading days.
8. **K=30 is validated** by PIT sweep (stable K=25-35 plateau, net-of-cost peak).
9. **Regime caveat**: this is a bear/neutral alpha engine. Expect bounded underperformance in strong bull.
10. The governance hold (Spec 048) **succeeded**: it prevented the old optionality selector from being institutionalized on contaminated data, which led to finding the better B6 selector.

---

## PIT Rules

1. **Never call the historical set "true PIT"** unless archived raw inputs, archived code, AND archived derived artifacts all exist as-of each date.
2. Historical benchmark outputs must carry `pseudo_pit_version` (1=contaminated, 2=cleaned).
3. Benchmark reruns must use the PIT-aware paths: `--pit-mode survivorship` or `--pit-mode full`.
4. Long-history conclusions are **provisional** until PIT-v2 financial rerun lands.
5. The forward monitor is the only true out-of-sample evidence. Accumulate it.

---

## Canonical Benchmark Commands

```bash
# Survivorship-cleaned selection benchmark (current baseline)
python3 scripts/research/build_selection_benchmark.py --pit-mode survivorship --top-n 20 --also-top30

# Monthly IC / selection benchmark
python3 scripts/research/selection_benchmark.py --pit-mode survivorship

# Ranker evaluation (inst_delta_z within top-30)
python3 scripts/research/ranker_evaluation_harness.py --signal inst_delta_z --pit-mode survivorship

# Construction v2 benchmark (all variants)
python3 scripts/research/construction_v2_benchmark.py --pit-mode survivorship

# PIT-financials snapshot regeneration (heavy lift, ~2h)
python3 scripts/research/regenerate_pit_v2_snapshots.py

# Run benchmarks on PIT-financial-corrected snapshots
python3 scripts/research/build_selection_benchmark.py --pit-mode survivorship --top-n 20 --also-top30 --snapshot-dir data/snapshots_pit_v2
```

---

## Heavy-Lift Jobs

- **PIT financial regeneration is COMPLETE.** 76 monthly dates in `data/snapshots_pit_v2/`, 72/72 OK, 0 errors.
- **Result: historical alpha collapsed.** All pre-correction claims are deprecated.
- **Next heavy lift: forward monitor accumulation.** No compute needed — just time. Evaluate after 30+ trading days of true-PIT daily production.
- **If forward evidence is positive:** re-establish selector thesis from clean data. Do not backfill from historical.
- **If forward evidence is negative:** the selector needs structural re-examination.

---

## Architecture Freeze Status

- **v1.14.0 freeze in effect** until post-h20d checkpoint (~2026-05-26)
- No new enforcement logic or scoring changes until then
- `ranker_active_contract.py` exists on unmerged branch (`hygiene/ranker-active-contract-2026-04-30`), deferred to post-freeze
- Manual spot-checks via snapshot_integrity verifier in the interim
- Spec 100 (ranker IC tooling correction) is highest-priority code change post-freeze

## Governance Artifacts (PR #286, merged May 16, 2026)

### governance/AGENT_ROUTING_POLICY.md
Tier 0-4 routing policy classifying every part of the codebase by governance sensitivity. Defines allowed tools, review requirements, and merge rules per tier. The policy itself is Tier 4 — changes require a memo, not a direct edit. Quarterly review required.

**Tier Summary:**
- **Tier 0 (Deterministic Production Hot Path):** Scripts, cron, tests, static checks only. No LLM may supervise, decide, mutate, or deploy production state.
- **Tier 1 (Low-Governance Utility):** Codex CLI, OpenClaw low-risk agents. Documentation, CLI ergonomics, non-scoring utilities.
- **Tier 2 (Medium-Governance Engineering):** Codex first draft + Claude Code review when output feeds Tier 3 code. Non-production analytics, validation scripts, ingestion plumbing.
- **Tier 3 (High-Governance Production/Evidence):** Claude Code for implementation or mandatory review. CCFT, selector, ranker, scoring, catalyst, CRT, shadow, walk-forward harness, production hashes. Tests asserting Tier 3 behavior are themselves Tier 3.
- **Tier 4 (Governance/Research Judgment):** Claude Chat/project chat + human approval. Architecture changes, signal admission/retirement, catalyst taxonomy, ablation interpretation, this policy itself.

**Walk-Forward Harness:** Permanent Tier 3 surface. Evidence-breaking migrations are Tier 4 decisions requiring a memo with cutover date, affected outputs, disposition of pre-migration evidence, and PM sign-off.

**Production Hash Rotation Rule:** Any diff changing a production hash requires a corresponding entry in `governance/HASH_ROTATIONS.md` with old hash, new hash, effective date, affected surface, reason, downstream impact, and reviewer.

**Merge Rule:** Highest affected tier governs review requirements. Patch size is not evidence of safety.

### governance/STATUS.md
Enforcement status: AGENT_ROUTING_POLICY.md is live. Pending enforcement layers: agent_registry.yml (PR 2), AGENT_DIRECTORY_MAP.md, CI registry validation, import-graph validation. Until enforcement layers are live, routing classifications applied manually.

### governance/HASH_ROTATIONS.md
Empty rotation log (policy effective date 2026-05-16). Required fields defined. No rotations recorded.

### Compliance Memo (Content Library)
"Why the DEM 27-Agent Fleet Is Insulated from Model-Output-as-Control-Signal Failures" — Final version, repo-verified. Cites Texas A&M SUCCESS Lab taxonomy of 470 OpenClaw advisories (arXiv:2603.27517). Available in Content Library at ai-projects/.

## External AI Landscape (May 2026)

### OpenClaw Security Posture
- Texas A&M SUCCESS Lab (arXiv:2603.27517, April 2026): 470 advisories organized by 7 architectural layers and 5 attack types
- Three Moderate/High-severity advisories compose into complete unauthenticated RCE from LLM tool call to host process
- Exec allowlist bypass via line continuation, busybox multiplexing, GNU long-option abbreviation
- Malicious skill executed two-stage dropper within LLM context, bypassing exec pipeline entirely
- DEM insulation: no agent has authority to modify production weights without traversing the full multi-gate promotion path

### Hermes Agent (Competitive Frame)
- Nous Research, launched February 2026, MIT license, $70M funded ($1B valuation)
- 153K GitHub stars (May 16, 2026 — single dated data point from GitHub)
- Core differentiator: self-learning Skill Documents (Markdown files created after 5+ tool calls, 40% efficiency gains)
- Self-evolving skill loop is governance-incompatible with CCFT unless every skill mutation is versioned, reviewed, and approved
- Recommendation: Monitor, do not adopt. hermes_claw_migrate command indicates Nous targeting OpenClaw installed base.

### ODIN Engine (External Benchmark for Clinical Scoring)
- L2-regularized logistic regression, 51 engineered features, 8 signal categories
- AUC: 0.9363 on 2,210 historical FDA events (2000-2025); verified 96.2% accuracy on 53 outcomes
- ODIN feature categories not in DEM: manufacturing/CMC risk, FDA era effects, options market implied probability, sponsor historical approval rate by therapeutic area
- These are Tier 4 evaluation candidates through T5 promotion path

### BiotechEdge (External Benchmark for Institutional Signals)
- Tracks 20 specialist biotech hedge funds, $46.5B+ total assets, 1,558+ companies, 2,318+ catalysts
- Fund convergence signal (3+ independent funds buying same stock) validates DEM's coinvest_score_z methodology
- Open-source alternative: pr124/Biotech_Fund_Tracker (GitHub) parsing 38-40 specialist funds

### FDA Real-Time Clinical Trial Initiative (April 2026)
- Two RTCT proof-of-concept studies launched: AstraZeneca TRAVERSE (MCL), Amgen STREAM-SCLC
- AI-Enabled Early-Phase Trial Pilot Program RFI (comments due May 29, 2026; selections August 2026)
- Projected 20-40% trial duration reduction, $120M annual savings
- If trials become continuous rather than phase-gated, binary catalyst model evolves — affects catalyst_decay_w and catalyst_quality calibration. Monitor as Tier 4 governance question.

### AI Drug Pipeline (Q1 2026)
- 173+ AI-originated programs in clinical trials (94 Phase I, 56 Phase II, 15 Phase III) — 7x increase since 2022
- Pre-clinical compression: 4-6 years to 12-24 months. Clinical timelines unchanged.
- Insilico Medicine Rentosertib: first fully AI-designed drug with Phase IIa results (Nature Medicine, June 2025)
- Isomorphic Labs: $2.1B Series B (May 2026). Recursion: fifth Sanofi milestone ($134M cumulative)
- 2026 is definitive validation year — Phase III results determine if AI improves beyond ~90% historical failure rate

### Industry AI Adoption
- 92% of hedge funds with $1B+ AUM use AI/ML (up from 56% in 2022); 67% describe as "integral"
- AI-integrated funds outperform traditional systematic strategies by 3-4pp annually
- NBIM ($2.1T): ~50% of 680 staff code own AI tools using Claude; all employees use AI daily
- Only 21% of organizations deploying AI have formal governance frameworks — DEM's merged governance artifacts place it in the leading minority

## 13F Cycle Status (Q1 2026 — COMPLETE)

*Updated: 2026-05-16*

- **All three tracked managers filed Q1 2026 13F-HR on deadline day (May 15, 2026)**
- Accession numbers: Fairmount 0001104659-26-062419, Deep Track 0001856083-26-000003, Logos Global 0001172661-26-002196
- CIKs: Fairmount 0001802528, Deep Track 0001856083, Logos Global 0001792126
- Filing pattern: all three filed on deadline day, consistent with Q1 2025 pattern (all May 15, 2025)

**Key changes:**
- **Fairmount**: Added DAMORA THERAPEUTICS ($225.7M, 16.3% of portfolio — largest new, NOT signaled by 13D/13G). Massive APGE trim (-85.4%), COGT trim (-38.9%). Exits: KINIKSA, NUVALENT. VRDN held (3.9M shares at 3/31). Post-Q1: VRDN stake raised to 14.04% via $20M purchase May 11.
- **Deep Track**: AUM $6,124M (+9.2%). 63 positions (was 55). 16 new positions including ALMS ($149M), NUVL ($141M), GMAB ($98M), DFNT ($57M). Exits: DVAX ($242M largest). VRDN: 1.4M shares at 3/31, accumulated to 5.4M post-Q1 per 13G.
- **Logos Global**: AUM $2,003M (+21.0%). 66 positions. Massive CNTA add (+963%, now $84.4M). New: UTHR ($47M), MDGL ($44.5M), XENE ($26M). 15 exits including CDTX ($68.5M).
- **Top coinvest**: VRDN (FM 14.04% + DT 5.30%) entering Ph3 TED readout. ORKA coinvest (FM + DT). Triple overlap on CRESCENT BIOPHARMA only. DT+Logos 22 overlaps.

**13D/13G pre-signal validation**: ~60-70% of major moves captured pre-filing. Largest surprises (DAMORA for Fairmount, CNTA for Logos) were invisible until 13F-HR.

**Post-filing action sequence**: (1) Warm 13F cache, (2) Run cohort quarantine, (3) Check collapse guards (coinvest_score_z SD), (4) Refresh IC decomposition, (5) 5-day observation window.

**Next cycle**: Q2 2026 (period ending June 30, 2026). Filing deadline ~August 14, 2026. Monitor EDGAR starting ~August 11.

## Active Spec Status (071-105)

*Updated: 2026-05-16*

### Recently Resolved
| Spec | Title | Status | Commit |
|------|-------|--------|--------|
| 093 | financial_score sign direction | RESOLVED (INTENTIONAL_STRESS_UPSIDE) | 2026-05-13 audit |
| 101 | Runway Severity v1.1 Export Contract | CLOSED | eaa4ea87 + cba4ee0f |
| 087 B0 | Stale-Propagation Guard | CLOSED | 0f0c7952 |
| 087 B2 | Dashboard Freshness Envelope | CLOSED | 400a6cd9 |
| 088 B | Catalyst Delta v2 Filter Companion | SHIPPED | 5ca4b033 |

### Active / Blocked
| Spec | Title | Status | Blocker |
|------|-------|--------|---------|
| 094 | Selector-only comparator | RANKER_UNPROVEN | Rerun target 2026-05-27 |
| 095 | Evaluation scope (IC tooling gap) | CURRENT_TOOLS_CONFLATED | Blocks ranker IC claims |
| 100 | Ranker IC tooling correction | Spec written, no impl | Architecture freeze (~May 26) |
| 104 | Insider diagnostic stabilization | MEASURED | Isolation guard (R4a) |
| 105 | Expectation layer coverage verification | CODE-CLOSED | Pending live QA |
| 102 | Historical backfill for expectation research | DRAFT | — |

### Monitoring
| Spec | Purpose | Gate | Next Review |
|------|---------|------|-------------|
| 096 | Gate/ranker separation doctrine | Defines promotion paths | Ongoing |
| 097 | Event-EV prospective monitoring | Brier <= 0.08, n >= 30 | Monthly |
| 098 | Catalyst timing prospective monitor | Correlation > 0.15 | Monthly |
| 099 | Clinical orthogonality audit | Pre-promotion gate | Before clinical promotion |

## Insider Diagnostic (Spec 104)

`insider_net_buy_value_90d` is **DIAGNOSTIC ONLY**. It is tracked in `DIAGNOSTIC_FIELDS` and explicitly excluded from `ALPHA_FEATURE_REGISTRY`. It does NOT enter the scoring model, ranker, or selector.

**CRITICAL**: The expectation model has an `insider_net_buy_z` weight that activates silently if the field flows into `market_features`. Spec 104 R4a requires an explicit isolation guard.

**Blank vs. Zero semantics**: NaN/None/blank = not fetched. 0.0 = fetched, no insider buy activity. Never collapse blank and zero.

**Promotion requires ALL of**: 20+ stable snapshots, >= 60% non-null coverage, IC > 0 at p < 0.05, Checklist v2 pass, explicit written approval.

## Expectation Layer Coverage Gate (Spec 105)

Production pipeline hard-fails if market-expectation fields are missing or under-covered in `rankings.csv`. Required fields: `short_interest_pct` (0.90), `close_price` (0.99), `market_cap_mm` (0.95), `priced_move_pct` (0.80), `insider_net_buy_value_90d` (0.30, nonblocking/diagnostic). Thresholds sourced from `FEATURE_COVERAGE_REQUIREMENTS` (single source of truth).

## Hermes Knowledge Layer (Spec 089) & Town Bridge (Spec 090)

### Knowledge Layer
Repo-native "ops brain" with four layers: Capture (read-only from specs, artifacts, registry, git, cron), Normalize (structured ledgers), Reason (drift/contradiction/missed-run detection), Deliver (operator briefs). Artifacts in `artifacts/ops/knowledge_layer/`.

### Town-Hermes Bridge
Routes Hermes events to Town via structured email to `djschulz@gmail.com`. Town routine triggers on `[Hermes]` subject prefix. Town is read-only relay — NOT a scheduler, repo mutator, or spec approver. Phase A complete (dry-run mode). Phase B (live delivery) not yet started.

## Forward Shadow & IC Status

*Updated: 2026-05-16*

- **Forward shadow**: accumulating since 2026-04-03. ~30+ trading days as of mid-May. Approaching or at evaluation threshold.
- **coinvest_score_z IC** (last measured 2026-05-13): Pooled mean IC = -0.031 (14 dates, 28.6% hit rate). Pre-cohort (clean): -0.051 (11.1% hit). Post-cohort (contaminated): -0.008 (60.0% hit). Verdict: OBSERVE.
- **Ranker IC**: UNMEASURED. Existing tools conflate composite_score with final_score (Spec 095). All prior ranker IC claims are misattributed. Blocked until Spec 100.
- **inst_delta_z**: zeroed in selector since 2026-05-04. Active in ranker (NW-t = +3.32). Reinstatement requires IC recovery evidence.
- Refresh IC decomposition after Q1 2026 13F cache warm + cohort quarantine.

## What to Update After Every Session

- [ ] Current benchmark winner (Top-20 vs Top-30, any new candidate)
- [ ] Trust bucket changes (provisional -> safe, or new invalid entries)
- [ ] Dead-lane list (add any newly killed signals/lanes)
- [ ] PIT version / contamination status
- [ ] Active heavy-lift job status
- [ ] 13F cycle status (next filing deadline, post-filing action items)
- [ ] Architecture freeze status (lift date, post-freeze priorities)
- [ ] Active spec status (newly resolved, newly blocked)
- [ ] Forward shadow & IC status (trading days accumulated, next checkpoint)
- [ ] Governance artifact status (PRs merged, enforcement layers pending)
- [ ] External AI landscape updates (ODIN accuracy, Hermes releases, FDA RTCT progress)

## Decision Engine Architecture (v1.14.0)

**Core files:**
- `decision_engine.py` — L0 gates -> L2 overlays -> L4 tiers -> L3 sizing -> sort key
- `selector_engine.py` — B6 selector (5 blocks, coinvest+inst dominant)
- `ranker_v2_pairwise.py` — pairwise_minimal ranker (6 features, ordinal-only)
- `ranker_engine.py` — clinical_50 ranker (legacy/fallback, bounded +/-15%)

**Pipeline flow:**
```
Modules 1-5 -> Decision Engine (gates, tiers, sizing)
           -> Selector Engine (B6: coinvest_score_z 100%, inst_delta_z zeroed 2026-05-04)
           -> Ranker Engine (pairwise_minimal: 6 features, top-60 cohort, ordinal-only)
           -> Sort by final_score -> EW Top-30 -> rankings.csv
```

**Sort anchor:** `selector_score` (uses `final_score` = ranker_v2_score for cohort members)
All downstream consumers use `actionable_rank` (now driven by selector/ranker, not composite_rank).

**Statistical QA:** `common/stats/` (6 modules), `scripts/research/checklist_v2_rerun.py`

## Promotion Governance
- **Manifest**: `production_data/decision_rulesets/manifest.json` — all rulesets tracked with status (active/candidate/retired)
- **Promotion battery**: `scripts/research/run_promotion_battery.py` -> bucketed verdicts + weekly live-sim -> PASS/FAIL
- **Promote script**: `scripts/promote_ruleset.py` — blocks promotion unless battery PASS
- **Health monitor**: `tools/ruleset_health_monitor.py` — post-promotion drift detection
- **Rollback**: `scripts/promote_ruleset.py --rollback --reason "..."` — first-class with auto-LKG discovery
- **Governance policy**: `governance/AGENT_ROUTING_POLICY.md` — Tier 3/4 review required for all promotion-adjacent changes

## Event Ledger & Cache Warming
- **Event ledger**: `build_event_ledger()` in `event_ledger.py` — 7+ sources (CTGov, merged trials, SEC 8-K, SEC multi-form, FDA ADCOM, FDA regulatory, PDUFA manual, EMA)
- **Cache warmer**: `warm_caches.py --sources sec_8k,ctgov,sec_13f,fda_adcom,fda_regulatory,euctr,ctis,isrctn,merged_trials`
- **EU/EEA registries**: `euctr_collector.py`, `ctis_collector.py`, `isrctn_collector.py` in `wake_robin_data_pipeline/collectors/`
- **Trial merger**: `trial_registry_merger.py` — cross-registry dedup by NCT/EudraCT IDs
- Always warm 8-K cache BEFORE running screen

## Daily Production Pipeline
- **Runner**: `tools/run_daily_production.py` — 13-step orchestrator
- **Cron**: 5:30 PM ET weekdays + `@reboot` catch-up for missed runs
- **Steps**: price refresh -> cache warm (incl. FDA) -> screen (with `--inputs-manifest write`) -> audit -> gates -> manifest + promotion -> drift report -> action packet -> shadow portfolio -> trade plan -> portfolio report -> readiness scorecard -> ops digest -> PIT backfill (optional)
- **Ops digest**: `tools/build_ops_digest.py` -> `artifacts/ops_digest/YYYY-MM-DD_digest.md` — single-screen actionable summary
- **Readiness**: `tools/weekly_readiness_scorecard.py` -> READY / REVIEW / HOLD verdict
- **Health checks**: collection health (INFO/WARN/FAIL with weekend-safe price fallback), phase-2 health, exposure metrics

## OpenClaw Ops Agent
- **Workspace**: `agents/ops/` — SOUL.md (boundaries), TOOLS.md (daily working set), HEARTBEAT.md (3-check)
- **Role**: read-mostly operator — runs pipeline, reads digest, surfaces action items, refuses to modify rulesets
- **Gateway**: 127.0.0.1:18789, loopback only, auth via setup token
- **Model**: Llama 3.3 70B Instruct Turbo via Together AI (switched 2026-05-13, was OpenRouter). Inference tuning: temperature 0.2, frequency penalty 0.1, repetition penalty 1.2, API timeout 2400s.
- **Fleet**: 27 active agents per AGENT_REGISTRY.json (schema v1.0, as-of 2026-04-28). Authority levels: observe_only, observe_and_propose, write_artifacts, mutate_data, mutate_config. Only crt_resolution_watcher holds mutate_data. Three-lane routing per docs/ops/hermes_openclaw_routing_policy.md (Lane A deterministic, Lane B cheap monitoring, Lane C manual engineering). No cron job may depend on a gateway token. Terminal agents (ops_supervisor) intentionally unsupervised.

## Shadow Portfolio
- **File**: `tools/live_shadow_portfolio.py` (902 lines)
- **Policy**: `production_data/portfolio_policy.json` (v3), $500k, 55/25/10/10 bucket split
- **Family sleeves**: REGULATORY/CLINICAL split per bucket with time-ladder sub-buckets
- **Regulatory sleeve A/B**: +1.85pp 63d, +1.59pp 84d (positive but coverage-limited)

## Adding a 13F Manager
- **Use `tools/onboard_manager.py`** — never edit `production_data/manager_registry.json` directly.
- One-shot flow: registry append -> backfill across every existing PIT dir (lookback=40 ~ 10y) -> warm current as-of date -> run `tools/test_manager_integration.py` (6/6 gate).
- Example: `python tools/onboard_manager.py --cik 1802528 --name "Fairmount Funds Management" --aum-b 1.3 --style concentrated_clinical_stage --tier elite_core --notes "..."`
- For reruns or partial flows use `--skip-registry`, `--skip-backfill`, `--skip-current`, `--skip-test`.
- Underlying primitive: `tools/warm_13f_cache.py --ciks <CIK> --existing-pit-dirs --elite-only` (merges into each PIT dir's `index.json`, doesn't disturb other managers).

## Data Provenance Rules
- **Holdings truth source:** `production_data/institutional_summary.json` is canonical. It has CUSIP->ticker resolution, issuer normalization, and corporate action handling.
- **Raw EDGAR XML is debug-only.** Never build a narrative (e.g., "8 new entrants") from raw filing parses unless it matches the canonical summary. Raw issuer strings are unreliable — different filings use different names for the same entity.
- **CUSIP-first, not issuer-first.** Always reason from CUSIP -> canonical ticker, never from issuer name strings.
- **If raw count != summary count:** investigate the summary pipeline first. The summary is more likely correct.

## Before Writing Any Code
1. State which module this change belongs to
2. Identify whether this is a new signal, validation change, or infrastructure change
3. Write the failing test FIRST — show me the red test before any implementation
4. Confirm no look-ahead bias: what is the data_available_timestamp?
5. Classify the diff by governance tier (Tier 0-4 per governance/AGENT_ROUTING_POLICY.md)

## Coding Standards
- All outputs: encoding='utf-8', lineterminator='\n', quoting=csv.QUOTE_MINIMAL
- SHA256 hash every scored output for audit trail
- Identical inputs must produce byte-identical outputs — no random seeds, no datetime.now()
- Use Point-in-Time fixtures — never fetch live data in tests

## What NOT To Do
- Do not refactor and add features in the same commit
- Do not change production agent weights without an ablation test showing Sharpe delta
- Do not use PubMed h-index API, options flow, or CapIQ — see approved data sources
- Do not introduce survivorship bias — graveyard list is at data/graveyard/

## Test Requirements
Every new signal must include:
1. Unit test with known fixture input -> expected output
2. Leakage test confirming data_available_timestamp compliance
3. Ablation test stub showing Sharpe contribution >= 0.1

## Long-Call Contract Recommendations (Post-Screen)

When producing long-call candidates from the screen output, also recommend the best executable long-call contract for each surviving candidate.

**Goal:** For every name that passes the long-call filter, recommend:
1. One primary contract
2. One backup contract
3. Or explicitly mark `NO_TRADE` if no contract is liquid / priced well enough

Do NOT just say "buy calls." Pick an actual strike + expiry from the chain data available in the repo/output.

### Step 1 — Expiry selection
- Base case: choose the first liquid expiry that is AFTER the catalyst date and still leaves 14-35 calendar days of cushion after the event
- If catalyst_days is 21-45: allow tighter post-event cushion of 7-21 days
- Avoid expiries that occur BEFORE the catalyst
- Avoid very long expiries unless all nearer expiries are illiquid or the event date is uncertain
- Prefer standard monthly expiries over odd weeklies when liquidity is similar

### Step 2 — Strike selection
- Target call delta between 0.30 and 0.50
- Higher-conviction names: prefer 0.40-0.50 delta
- Lower-conviction / higher-IV names: prefer 0.30-0.40 delta
- Avoid ultra-OTM lottery strikes unless premium is tiny and liquidity is still acceptable
- Avoid deep ITM unless spread/liquidity is clearly superior and thesis is very high conviction

### Step 3 — Liquidity filter
Reject contracts if any of these are true:
- open_interest is too low
- volume is too low
- bid/ask spread is too wide
- pricing looks stale

If the repo does not have exact spread fields, use the best liquidity proxies available and state the limitation.

### Step 4 — Entry economics
For each candidate contract, compute or estimate:
- mid premium
- breakeven move to expiry
- event-date implied move
- crush-adjusted move if available
- delta
- DTE

Prefer contracts where:
- directional thesis is confirmed by RR / skew
- implied move is not already extreme
- the contract still has room to profit after likely post-event IV compression
- premium at risk is reasonable relative to conviction

### Step 5 — Rank contracts
Choose the primary contract by this priority:
1. Expiry appropriately covering the catalyst
2. Strongest liquidity
3. Delta in target band
4. Best breakeven vs thesis
5. Cleaner spread / execution quality

Choose one backup contract that is either:
- one strike lower/higher with similar expiry, or
- next best expiry with similar delta profile

### Output format for each candidate
```
ticker:
  catalyst: <event_type> in <N> days
  thesis: <1-2 lines>
  primary_contract:
    expiry:
    DTE:
    strike:
    option_type: CALL
    delta:
    premium_or_mid:
    open_interest:
    volume:
    spread_or_liquidity_proxy:
    breakeven_move_pct:
    why_this_contract:
  backup_contract:
    <same fields>
  no_trade_reason: <if applicable>
```

### Important constraints
- If exact contract-chain data is unavailable from the snapshot alone, look for the nearest chain artifact/cache already produced by the repo for that date
- If the contract recommendation depends on missing chain fields, say so explicitly and give the best constrained recommendation possible
- Do not change DEM scoring or ranking logic
- This is a post-screen execution recommendation only

## Options Expression Layer (Spec 062, 2026-04-13)
- **Status**: Shadow-only, merged to main. Zero alpha impact.
- **Module**: `event_ev/expression_layer.py` — classification -> mapping -> gates -> sizing
- **Attribution**: `event_ev/expression_attribution.py` — JSONL logging, CRT resolution, kill switches
- **Wiring**: `run_screen.py` emits `expression_overlay_summary.json` + `expression_recommendations.json` per snapshot
- **Tests**: 123 (83 expression + 40 attribution)
- **Policy**: overlay-only. Does NOT enter selector/ranker/construction. Expression layer must NEVER be imported by `selector_engine.py`, `ranker_engine.py`, or `decision_engine.py`.
- **Review horizon**: 30 days from first emission. No threshold tuning before then.

## Data Explorer Agent (2026-04-13)
- **CLI**: `python -m tools.data_explorer {summary,compare,qa,catalog,field,top-n,daily}`
- **Package**: `tools/data_explorer/` (loader, catalog, explorer, comparator, reporter, viz)
- **Tests**: 33
- **Policy**: Read-only analysis. Canonical reporting source — console agent summaries are non-authoritative unless backed by dataset evidence.
- **Output**: `reports/data_explorer/` (timestamped directories with markdown + PNG charts)

## Key File Locations
| Area | File |
|------|------|
| Main orchestrator | `run_screen.py` |
| Decision Engine | `decision_engine.py` |
| Selector Engine | `selector_engine.py` |
| Ranker Engine | `ranker_engine.py` |
| Calendar Alpha | `common/clinical_calendar_alpha.py` |
| Options Provider | `common/options_history_massive.py` |
| Daily Production | `tools/run_daily_production.py` |
| Shadow Portfolio | `tools/live_shadow_portfolio.py` |
| Trade Plan | `tools/build_trade_plan.py` |
| Portfolio Report | `tools/build_portfolio_report.py` |
| Readiness Scorecard | `tools/weekly_readiness_scorecard.py` |
| Ops Digest | `tools/build_ops_digest.py` |
| Collection Health | `tools/build_data_collection_health.py` |
| Hedge Report | `tools/biotech_hedge_report.py` |
| Promotion Battery | `scripts/research/run_promotion_battery.py` |
| Signal Evidence | `scripts/run_signal_evidence.py` |
| Ruleset Manifest | `production_data/decision_rulesets/manifest.json` |
| Cache Warmer | `warm_caches.py` |
| Event Ledger | `event_ledger.py` |
| Cron Wrapper | `tools/cron_daily_production.sh` |
| Ops Agent Workspace | `agents/ops/` |
| Expression Layer | `event_ev/expression_layer.py` |
| Expression Attribution | `event_ev/expression_attribution.py` |
| Data Explorer | `tools/data_explorer/agent.py` |
| Spec 062 | `specs/changes/spec_062_options_expression_layer.md` |
| Governance Policy | `governance/AGENT_ROUTING_POLICY.md` |
| Governance Status | `governance/STATUS.md` |
| Hash Rotations | `governance/HASH_ROTATIONS.md` |
| Routing Policy (ops) | `docs/ops/hermes_openclaw_routing_policy.md` |
| Agent Registry | `agents/AGENT_REGISTRY.json` |

## Developer Profile

This system is maintained by an institutional SFO investment professional (CFA, CAIA, 30+ years) who is Director of Investments at Wake Robin (wakerobin.co), a real estate investment and community development company in Holland, MI.

### Quantitative Biotech Investment
- **Biotech equity screening pipeline** — multi-module scoring (financial health, clinical development, catalyst/event resolution, composite), Decimal arithmetic, PIT-safe, deterministic, 13-step daily production pipeline
- **Institutional signal analysis (13F/13D/13G)** — coinvest_score_z pipeline tracking Fairmount Funds, Deep Track Capital, Logos Global Management via SEC EDGAR. PIT cache infrastructure, cohort quarantine, contamination window governance
- **Statistical signal evaluation** — Spearman IC decomposition, Checklist v2 promotion battery (FM, bootstrap, FDR, LOSO, year stability), forward shadow monitoring, evidence hierarchy, dead-lane registry
- **Catalyst & event-driven analysis** — 7+ event sources (ClinicalTrials.gov/AACT, SEC 8-K, FDA ADCOM, PDUFA, EMA), catalyst_decay_w, binary_quality_score, event_ev_p_hit, resolution tracking
- **Decision engine & portfolio construction** — two-stage selector/ranker, B6 coinvest-only selector, pairwise minimal ranker, EW Top-30. Production: +2.34pp/mo net-of-cost, t=2.57
- **Biotech earnings signal classification** — SM/ACC/MR/CON/ID weekly post-mortem system with cumulative ledger

### Family Office & Institutional Modeling
- **SFO liquidity architecture** — 7-layer deterministic modeling stack (entity, account/position, cash-flow, PE pacing, RE+OpCo, liquidity, allocation/policy). Four-line principle. Quarterly ledger spine.
- **PE pacing models** — Takahashi-Alexander, STAIRS market-coupled adapter, capital call obligation bridge, configurable reconciliation gates
- **Spending policy design** — flat-real, smoothing, Owl/Guyton-Klinger guardrails, configurable spending base denominator
- **Institutional asset allocation** — multi-asset-class rebalancing, AUM management ($14B+), sovereign wealth fund and public pension experience
- **Alternatives & derivatives** — options strategies, index futures, structured products, tail risk hedging

### Technical AI/Automation
- **AI agent fleet architecture** — 27-agent Hermes/OpenClaw fleet (per AGENT_REGISTRY.json schema v1.0, as-of 2026-04-28: 27 active, 1 suppressed, 1 retired, 1 shadow) on Llama 3.3 70B via Together AI. Per-agent SOUL.md, four-layer monitoring, Knowledge Layer (Spec 089). Governed by governance/AGENT_ROUTING_POLICY.md (Tier 0-4, merged PR #286 May 16, 2026). Authority levels: observe_only, observe_and_propose, write_artifacts, mutate_data, mutate_config. Only crt_resolution_watcher holds mutate_data. Three-lane operational routing (Lane A deterministic, Lane B cheap monitoring, Lane C manual engineering). No cron job may depend on a gateway token.
- **Production pipeline engineering** — 13-step daily biotech screener (cron 5:30 PM ET), timeout optimization, race condition resolution, sleep-cliff mitigation, determinism enforcement (byte-identical outputs)
- **Town AI platform** — 18 active routines, 19 custom skills encoding pipeline scoring rules, SFO architecture, governance. Routine design with email recipients, MCP servers, callable sub-routines
- **LLM integration** — Claude/Grok/ChatGPT for research synthesis, prompt engineering, Llama-optimized inference tuning, persona configuration
- **DevOps** — WSL2 Python, cron orchestration, Together AI gateway monitoring, token management, log aggregation

### Financial Data Engineering
- **SEC EDGAR pipeline** — PIT-safe ingestion of 13F-HR, 13D/A, 13G, Form 4, 8-K. Per-CIK PIT cache, canonical institutional summary, CUSIP-first reasoning, staleness gates, SEC_USER_AGENT compliance
- **Clinical trial data** — ClinicalTrials.gov/AACT, EU/EEA registries (EUCTR, CTIS, ISRCTN), cross-registry dedup, trial status monitoring
- **Financial data APIs** — yfinance, Alpaca, Polygon, Massive feeds, PubMed, AACT
- **Data validation** — CCFT principles (canonical, complete, frozen, timestamped), PIT audits, survivorship bias detection, snapshot collapse guards

### Research Governance & Spec Lifecycle
- **Evidence standards** — Checklist v2 (FM, bootstrap, FDR, LOSO, calibration), true PIT backtests, forward shadow monitoring
- **Spec lifecycle** — DRAFT > IN PROGRESS > HELD > RESOLVED > CLOSED, with phased acceptance criteria, blocking dependencies, closure memos. Currently managing specs 071-105.
- **Promotion governance** — promotion battery, ruleset health monitor, architecture freeze protocol, rollback capability. Governed by governance/AGENT_ROUTING_POLICY.md Tier 3/4 requirements.
- **Knowledge management** — Hermes Knowledge Layer (Spec 089), Town-Hermes Bridge (Spec 090), held-spec ledger, first-fire ledger, contradiction ledger, operator briefs

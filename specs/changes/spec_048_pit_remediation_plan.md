# PIT Remediation Plan

**Status:** PHASES 0-4 COMPLETE (survivorship layer); PIT FINANCIALS REGENERATION IN PROGRESS
**Author:** operator / Claude
**Date:** 2026-04-02 (updated 2026-04-02)
**Ruleset impact:** NO immediate scoring change; YES for historical benchmark validity and any promotion claims

## !! GOVERNANCE HOLD — do not finalize committee narrative until PIT-financials rerun lands

The survivorship-cleaned results below are **provisional**. Full PIT-financial regeneration
(76 monthly dates via `regenerate_pit_v2_snapshots.py`) is running. Impact assessment showed
**only 12/30 top-30 names overlap** between old and PIT-financial-corrected rankings on a sample
date (2024-06-28), and 67.8% of top-30 names have >25% cash delta. This is large enough to
overturn the Top-20 vs Top-30 conclusion.

**Decision tree after rerun:**
- If Top-30 still beats Top-20 → committee story gets stronger
- If Top-20 re-emerges → concentration story comes back
- If both weaken materially → selector itself needs re-baselining

## Results summary (survivorship-only pseudo-PIT v2 — PROVISIONAL)

| Metric | EW Top-20 v2 | EW Top-30 v2 | XBI |
|--------|-------------|-------------|-----|
| Cum return (full history) | +152.6% | +169.4% | +58.9% |
| Cum excess vs XBI | +93.7pp | +110.5pp | — |
| Top-30 minus Top-20 excess | — | +16.8pp | — |

**Key findings (PROVISIONAL — awaiting PIT financials rerun):**
- Top-30 beats Top-20 by +16.8pp on survivorship-cleaned full history
- Recent window (Oct 2025+) is **unaffected** by survivorship cleanup — identical to v1
- Long-history alpha is **larger** after survivorship cleanup
- Monthly IC benchmark (63d): mean excess +2.15pp/mo vs eligible, +4.27pp/mo vs XBI, hit rate 67%, IR 0.39, t-stat 3.20
- Regime: bull IR +0.79, bear IR -0.06 (bear is flat, not destructive)
- **Construction drag persists:** +158pp (top-20) / +175pp (top-30) gap vs shadow
- **PIT financials impact:** 12/30 overlap on sample date; 67.8% of top-30 have >25% cash delta — rankings are materially different

## Objective

Restore trust in historical backtests by moving the snapshot stack from **retro-regenerated pseudo-PIT with known contamination** to a cleaner **pseudo-PIT v2** baseline, then re-benchmark the small set of results that currently drive portfolio and committee decisions.

This plan is motivated by a serious survivorship finding: the PIT audit found **8,556 IPO look-ahead violations across 420 snapshots**, with **84.8% of snapshots** including tickers before they existed; the note calls out **LBRX** appearing in **335 snapshots** despite listing in September 2025. The same audit note says all historical snapshots were generated retroactively with today's code/static files, so long-history backtests are directionally informative but not true PIT. 

## Scope

This plan covers:

* historical snapshot generation
* investable-universe filtering
* PIT financials
* PIT validation / audit
* rerun order for core benchmarks
* trust buckets for current evidence

This plan does **not**:

* reopen dead signal lanes
* change live DEM scoring today
* relitigate construction, options ranker, or `total_volume_z` before the cleaned rerun

## Current state

Already built:

* **Production Data Archiver** that snapshots key inputs with SHA-256 manifests
* **EDGAR PIT financials pipeline** (`build_pit_financials.py`, `pit_financials.py`)
* **PIT validation audit**
* **snapshot overwrite protection**
* **CTGov fallback PIT safety net** in `run_screen.py` so future-dated trial updates are filtered on historical reruns.  

Known contamination / weakness:

* survivorship / investability contamination is **real and material**
* financial features are still provisional until PIT EDGAR facts replace current-state financial records
* catalyst look-ahead remains inconclusive because early files were generated retroactively
* early historical snapshots degrade some fields, so older backtests may be testing a simpler model than the current one. 

## Operating principles

1. **Do not call anything "true PIT" unless raw inputs, code, and derived artifacts are archived as-of each date.**
2. **Rebuild the minimal benchmark stack first.**
3. **Use trust buckets aggressively.**
4. **Promotion decisions pause until pseudo-PIT v2 reruns land.**

## Phases

### Phase 0 — Freeze and label

**Goal:** stop overclaiming while remediation runs.

Tasks:

* label current long-history benchmark outputs as **pseudo-PIT v1**
* add a note to committee/review materials that 2020+ results are provisional pending survivorship + PIT financials rerun
* freeze use of long-history alpha numbers for promotion claims

Exit criteria:

* all benchmark artifacts and memos clearly distinguish **pseudo-PIT v1** from future **pseudo-PIT v2**

Owner:

* **Quant PM / investor hat** for policy language
* **Python / quant engineering hat** for artifact labels and note injection 

---

### Phase 1 — Fix investability / survivorship

**Goal:** ensure a historical snapshot only contains names that could actually be owned on that date.

Tasks:

* build and persist `ipo_date` / `first_trade_date` map from price history
* optionally add `delist_date` / acquisition exit when available
* filter snapshot generation to exclude:

  * `first_trade_date > as_of_date`
  * `delist_date < as_of_date` when applicable
* add audit artifact:

  * `output/pit/survivorship_audit_YYYY-MM-DD.json`

Invariants:

* no historical snapshot may include a ticker before its first trading date
* survivorship audit must report zero pre-IPO inclusions after fix

Exit criteria:

* **0 IPO look-ahead violations** on rerun audit

Owner:

* **Python / quant engineering hat** for filter wiring
* **Data engineering hat** for date source integrity 

---

### Phase 2 — Wire PIT financials

**Goal:** replace current-state financial features in historical reruns with filing-date-gated facts.

Tasks:

* run `tools/build_pit_financials.py` across the tracked universe
* wire `pit_financials.py` into `run_screen.py` whenever `--as-of-date` is used
* ensure filed-date gating controls all historical financial fields
* produce audit artifact:

  * `output/pit/financials_pit_coverage_YYYY-MM-DD.json`

Invariants:

* historical financial rows must only use filings with `filed <= as_of_date`
* no fallback to current-state `financial_records.json` during PIT reruns once PIT facts are available

Exit criteria:

* PIT financial module is the active source for historical reruns
* coverage and fallback rates are reported explicitly

Owner:

* **Python / quant engineering hat** for wiring
* **Data engineering hat** for EDGAR/XBRL integrity  

---

### Phase 3 — Rebuild pseudo-PIT v2 snapshot set

**Goal:** regenerate the historical snapshot history on the cleaned stack.

Tasks:

* rerun historical snapshots after:

  * survivorship filter
  * PIT financial wiring
  * CTGov fallback PIT safety net
  * snapshot overwrite protection
* write outputs to a clearly labeled location or with a version marker:

  * `pseudo_pit_version = 2`
* keep v1 and v2 benchmark artifacts side-by-side for compare

Invariants:

* reruns must not overwrite prior benchmark evidence silently
* snapshot metadata must include:

  * `saved_at`
  * `as_of_date`
  * `pseudo_pit_version`
  * provenance summary

Exit criteria:

* full historical snapshot set rebuilt as **pseudo-PIT v2**

Owner:

* **Python / quant engineering hat** for rerun orchestration
* **Data engineering hat** for archive completeness

---

### Phase 4 — Rerun the benchmark stack

**Goal:** answer the only questions that matter after cleanup.

Rerun order:

1. **DEM Top-20 vs XBI**
2. **DEM Top-30 vs XBI**
3. **Top-20 vs Top-30**
4. **Top-20 vs Top-30 net of costs**
5. **By-regime slices**
6. **Only then** recheck pruner / stage-2 overlays

Reason for order:

* current model decisions are now dominated by the simpler question of whether **Top-20** is the right product of the selector, so that gets rerun first
* more complex layers only matter if the cleaned benchmark still supports the simpler story

Exit criteria:

* a refreshed benchmark pack exists for pseudo-PIT v2
* committee claims are updated only from v2 outputs

Owner:

* **Quant PM / investor hat** for benchmark rules and interpretation
* **Python / quant engineering hat** for runner execution and artifact generation 

---

### Phase 5 — Reclassify evidence by trust bucket

**Goal:** make every signal / benchmark explicitly governable.

Buckets:

#### Safe to use now

Use operationally or as engineering hygiene:

* snapshot overwrite protection
* CTGov fallback PIT safety net
* production data archiver
* PIT validation audit framework
* live risk / rebalance / execution controls
* recent operational artifacts that do not depend on long contaminated histories 

#### Provisional

Directionally useful, but not promotion-grade until pseudo-PIT v2 rerun:

* long-history **DEM Top-20 vs XBI**
* long-history **DEM Top-30 vs XBI**
* claims about "Top-20 is the sweet spot"
* construction / pruner conclusions that depend on 2020+ regenerated snapshots
* any full-history regime decomposition based on the contaminated snapshot set

#### Invalid until rerun

Do not use for decision claims:

* any benchmark that still includes pre-IPO names
* any historical financial-signal result that still uses current-state financial records
* any long-history comparison that mixes contaminated universe membership with current claims of investability
* any promotion memo that cites the contaminated 2020+ history as if it were clean PIT

Owner:

* **Quant PM / investor hat** for governance classification
* **Python / quant engineering hat** for tagging artifacts

## Rerun priority matrix

### Must rerun first

* selection-only benchmark
* Top-20 vs Top-30
* Top-20 / Top-30 vs XBI
* any long-history committee slide

### Rerun second

* pruner / stage-2 overlays
* regime-conditioned comparisons
* signal ICs that depend on cleaned membership / historical financials

### Can wait

* options lane, where the main blocker was calendar maturity and forward-return fill, not only PIT contamination
* AACT recent-lane evaluations with bounded recent windows
* purely operational dashboards / digests

## Owners by hat

**Quant PM / investor hat**

* define what claims are paused
* approve trust buckets
* define rerun benchmark set
* approve committee language after v2 rerun

**Python / quant engineering hat**

* survivorship filter
* PIT financial wiring
* snapshot regeneration
* benchmark reruns
* artifact labeling / versioning

**Data engineering hat**

* EDGAR PIT ingestion integrity
* investability date source quality
* archive completeness
* validation-audit automation

**Frontend / API hat**

* optional: show pseudo-PIT version and trust bucket on benchmark endpoints / dashboard cards 

## Artifacts

Suggested outputs:

```text
output/
  pit/
    survivorship_audit_YYYY-MM-DD.json
    financials_pit_coverage_YYYY-MM-DD.json
    pseudo_pit_compare_v1_vs_v2.json
  benchmarks/
    selection_only_top20_pseudo_pit_v2_YYYY-MM-DD.json
    selection_only_top30_pseudo_pit_v2_YYYY-MM-DD.json
    top20_vs_top30_pseudo_pit_v2_YYYY-MM-DD.json
    regime_slices_pseudo_pit_v2_YYYY-MM-DD.json
```

## Promotion / communication rule

Until pseudo-PIT v2 reruns land:

* **do not** promote model changes based on contaminated long-history alpha
* **do not** present 2020+ long-history results as clean PIT
* **do** use current results for directional architecture shaping only

After pseudo-PIT v2 reruns:

* update the model thesis only from the rerun benchmark pack
* explicitly state whether the simpler "Top-20" story survived cleanup

## Bottom line

This remediation plan is:

1. **freeze claims**
2. **fix survivorship**
3. **wire PIT financials**
4. **rebuild pseudo-PIT v2**
5. **rerun the minimal benchmark stack**
6. **reclassify every signal into safe / provisional / invalid**

That is the shortest honest path from "useful but contaminated backtests" to a benchmark set you can defend.

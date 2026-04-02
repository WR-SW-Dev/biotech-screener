# PIT Remediation Plan

**Status:** ALL PHASES COMPLETE — PIT financial correction landed, historical alpha story collapsed
**Author:** operator / Claude
**Date:** 2026-04-02 (final update 2026-04-02)
**Ruleset impact:** NO scoring change; YES — all historical benchmark claims are now deprecated

## Executive Finding

> After correcting PIT financial leakage, historical selector performance materially
> deteriorates. Top-20 and Top-30 portfolios now underperform XBI cumulatively, and
> monthly excess returns are weak and statistically insignificant. This strongly suggests
> prior alpha was inflated by financial look-ahead contamination. Forward true-PIT
> monitoring is now the only credible performance evidence.

## Results: PIT-Financial-Corrected (final)

76 monthly snapshots regenerated with EDGAR filing-date-gated financials + survivorship filter.

| Metric | Survivorship-only (deprecated) | **PIT-Financial-Corrected (final)** |
|--------|-------------------------------|-------------------------------------|
| EW Top-20 cum excess vs XBI | +93.7pp | **-28.2pp** |
| EW Top-30 cum excess vs XBI | +110.5pp | **-25.1pp** |
| Top-30 minus Top-20 | +16.8pp | +3.1pp |
| Diagnosis | CONSTRUCTION_DRAG | **SIGNAL_COLD_PLUS_DRAG** |

### Monthly IC (63d horizon)

| Metric | Survivorship-only (deprecated) | **PIT-Financial-Corrected** |
|--------|-------------------------------|---------------------------|
| Mean excess vs XBI | +4.27pp/mo | **+0.58pp/mo** |
| Hit rate vs XBI | 67% | **52%** |
| IR vs XBI | 0.39 | **0.08** |
| t-stat vs XBI | 3.20 | **0.65** |
| Mean excess vs eligible | +2.15pp/mo | **+0.11pp/mo** |

### Regime split (63d, vs XBI)

| Regime | Survivorship-only (deprecated) | **PIT-Financial-Corrected** |
|--------|-------------------------------|---------------------------|
| Bear | -0.43pp, IR -0.06 | **+0.01pp, IR 0.00** |
| Bull | +9.40pp, IR +0.79 | **+1.21pp, IR +0.15** |

### What happened

Financial look-ahead contamination in historical snapshots inflated alpha by allowing the model to
"see" future financial filings (cash balances, burn rates, runway) when scoring historical dates.
On a sample date (2024-06-28), only 12/30 top-30 names overlapped between original and
PIT-financial-corrected rankings. 67.8% of top-30 names had >25% cash delta. The correction
reshuffled rankings severely enough to eliminate the cumulative excess.

### Governance outcome

The governance hold (established earlier in this spec) **prevented a false positive from being
institutionalized**. All survivorship-only claims are now deprecated. The forward monitor under
true PIT is the only credible evidence source going forward.

## Operational status

All pre-correction benchmark claims are **DEPRECATED / CONTAMINATED**:
- Do not cite survivorship-only v2 numbers (+93.7pp, +110.5pp) for any purpose
- Do not cite the "Top-30 is the sweet spot" narrative from contaminated data
- The selector may still have real alpha — but the historical evidence no longer supports the claim
- Forward true-PIT monitoring is the only path to re-establishing confidence

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

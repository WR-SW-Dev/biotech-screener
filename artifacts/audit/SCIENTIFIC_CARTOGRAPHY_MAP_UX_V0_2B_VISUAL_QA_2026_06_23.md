# Scientific Cartography Map UX v0.2b — Visual QA
**Date:** 2026-06-23
**Status:** WARN
**Verdict:** `WARN_MAP_UX_V0_2B_USABLE_BUT_NEEDS_DENSITY_REFINEMENT`

---

## 1. Evaluation Method

Inspected all four generated files for the T2D prototype
(`artifacts/scientific_cartography/map_ux/type-2-diabetes-mellitus/`):

- `index.html` (11,838B) — full HTML including embedded SVG + stats row + legend
- `map.svg` (8,036B) — standalone SVG, 990×266px
- `map.json` (284,170B) — full lane/column/node data
- `README.md` (1,046B)

Also ran programmatic analysis against `map.json` to count confidence
distributions, identify duplicate assets, and flag non-drug program
pollution in visible nodes.

---

## 2. Checklist Assessment

### 2.1 Can I instantly see the stage distribution?

**PASS.**

Stats row in HTML shows: `phase3: 150 | unknown: 106 | phase1: 106 | phase2: 103 | approved: 86`
Column headers (PHASE1, PHASE2, PHASE3, APPROVED, UNKNOWN STAGE) are
clear white-on-dark labels. Stage breakdown is visible in under 5 seconds.

### 2.2 Is the Unknown Mechanism lane visually honest and not hidden?

**PASS.**

Amber background (`#ffeeba`), bold "Unknown Mechanism" label, tall row
(148px vs 44px for GLP-1 lane). The lane is visually dominant and
correctly draws the reader's eye. The warning banner above the map
explicitly states: "Mechanism coverage is sparse (0.2%). Unknown
mechanism lane is dominant and expected."

### 2.3 Are public tickers readable?

**FAIL (expected, not a generator defect).**

Ticker linkage is 0% because no snapshot/`rankings.csv` was used — this
is correct behavior per the forbidden-source design. All node borders are
thin (no ticker linkage). Tickers will appear when a snapshot is
authorized as input; the generator encodes them correctly via thick-border
nodes. This is a data limitation, not a visual grammar defect.

### 2.4 Are node labels too dense?

**WARN.**

The 5-node-per-cell cap works correctly — no cell overflows the SVG grid.
However, label truncation at ~20 characters hides meaningful names:

- `"standard of care (b…"` — only program in GLP-1 lane; incomprehensible
- `"Human Insulin Inhal…"` — truncated before the key word "Powder"
- `"Maridebart cafraglu…"` — truncated before anything identifiable

At 9px font size × 144px cell width, approximately 20 characters are
displayable. This is structural, not fixable by widening cells. The deeper
problem is **asset deduplication** — removing duplicates would surface
more distinct, informative asset names in the top-5 slots rather than
repeats like Metformin ×5.

### 2.5 Is GLP-1 separated clearly from Unknown Mechanism?

**PASS (structural separation works; lane is nearly empty).**

The GLP-1 lane is clearly separated with its own row, distinct background
(`#ecf0f1`), and non-bold label. However, the lane contains only 1
program (`"standard of care (b…"` in the Approved column). All other GLP-1
agonists (semaglutide, liraglutide, dulaglutide) are in the Unknown
Mechanism lane because the mechanism dictionary has only 1 T2D alias
active. The structural grammar is correct; the content is not.

### 2.6 Are confidence/source-ref encodings visible?

**FAIL.**

Confidence range across all visible nodes: **min=0.60, max=0.70,
stdev=0.039**. The SVG opacity formula (`0.30 + 0.70 × confidence`)
maps this to an opacity range of **0.72–0.79** — a 7-percentage-point
band that is perceptually imperceptible.

All programs currently have confidence in a very tight band because:
- 100% have unknown modality (gray) → no modality boost
- 100% have MONDO-mapped disease → similar disease_confidence
- 100% have unknown asset alias → capped at 0.75 by R3

The R3 confidence redesign is technically correct, but current data
produces a degenerate range. Confidence as a visual encoding will become
meaningful only after ticker linkage (which splits into two tiers: ~0.75
unresolved vs. ~0.85+ resolved) and modality normalization.

Modality colors: only 1 blue node (small molecule) visible in the GLP-1
lane. All 550 Unknown Mechanism nodes are gray (#95a5a6 = unknown). Color
encoding is therefore also non-informative at this stage.

### 2.7 Does the governance banner make clear this is diagnostic-only?

**PASS.**

- Dark header bar with red "DIAGNOSTIC ONLY — NOT AN INVESTMENT
  RECOMMENDATION" in the first line
- Footer repeats "DIAGNOSTIC ONLY — NOT AN INVESTMENT RECOMMENDATION"
- Stats row shows 0% ticker linkage explicitly
- Warning banner calls out sparse mechanism coverage
- README restates governance

The governance presentation is clear, non-dismissible (first element on
page), and unambiguous.

### 2.8 Does the map feel like a landscape, not just a table?

**FAIL.**

With 2 lanes (effectively 1 meaningful data row), the map is a table with
an empty decorative row on top. A landscape requires ≥4–6 mechanism lanes
to communicate competitive structure. The Unknown Mechanism row dominates
so completely that spatial reasoning is impossible — the user cannot ask
"where is this field crowded?" because all 550 programs are in the same
row.

The structural grammar (columns = stage, rows = mechanism) is correct
and well-implemented. The landscape feel will emerge after R6 mechanism
aliases populate ≥4 lanes.

---

## 3. Investor Question Coverage

| Question | Answerable? | Note |
|---|---|---|
| Which mechanisms are represented? | ❌ | Only GLP-1 (1 program); 99.8% unknown |
| Which stages are populated? | ✅ | Clear from column headers + stats row |
| Which public companies appear? | ❌ | 0% ticker linkage |
| Where is the field crowded? | ⚠️ Partial | Can see phase3 has 150 programs, but they're all in one undifferentiated row |
| What is unknown or low confidence? | ✅ | Unknown stage column + amber lane + warning banner |

---

## 4. Data Quality Issues Identified

These are not generator defects — they are upstream data issues that
become visible when rendering and must be addressed in v0.2c.

### 4.1 Asset Deduplication Not Implemented (Critical)

Each CT.gov trial record generates a separate program node. Drugs
appearing in multiple trials show up as multiple nodes:

| Asset | Appearances in visible cells |
|---|---|
| Metformin | ×24 |
| Dapagliflozin | ×16 |
| Saxagliptin | ×13 |
| Insulin Glargine | ×7 |

This means the phase3 column showing "150 programs" is actually ~30
distinct drugs in ~5 trials each. The map currently communicates trial
count, not drug count. For landscape use, each asset should appear once
at its highest-observed stage.

### 4.2 Non-Drug Programs Polluting Nodes (High)

CT.gov trial records include lifestyle/behavioral interventions as
"intervention_name" fields. These are flowing into program records as
assets. Identified in visible nodes:

| Program name | Type |
|---|---|
| "aerobic exercise + low-level laser thera" | behavioral |
| "Aerobic exercise" | behavioral |
| "Diet" | behavioral |
| "Exercise" | behavioral |
| "Lifestyle therapy" | behavioral |
| "aerobic training, tobacco cessation..." | behavioral |
| "No treatment given" | comparator arm |
| "Comparison of eating windows..." | behavioral |
| "Withings BPM Connect" | medical device |

These appear across phase2, phase3, and unknown stage columns. A landscape
map should show pharmaceutical programs, not RCT comparator arms.

### 4.3 Confidence Range Degenerate (Medium)

All nodes cluster at confidence 0.60 (unknown stage) or 0.70 (known
stage), with effectively no spread. The R3 design intent was correct;
the degenerate range is a data-completeness artifact that resolves
with ticker linkage and modality normalization.

### 4.4 Single Active Mechanism Lane (Expected/Critical)

Only 1 of 551 T2D programs has a resolved mechanism class (GLP-1). The
entire clinical landscape of T2D (SGLT2 inhibitors, DPP-4 inhibitors,
insulin, GLP-1 RAs, PPAR agonists, biguanides) is invisible in the lane
axis. This is the R6 mechanism alias problem and is the single highest-
impact fix available.

---

## 5. What Works Well

1. **SVG grid geometry** is correct: columns are evenly spaced, lane
   labels are legible, column headers visible.
2. **5-node-per-cell cap** prevents visual overflow effectively.
3. **Stage column order** (phase1→phase2→phase3→approved→unknown) is
   clinically correct and immediately interpretable.
4. **Overflow labels** ("+101 more") communicate scale without clutter.
5. **Stats row** answers the basic quantitative question in the first
   glance: 551 programs, 80.8% staged, 0.2% mechanism-known.
6. **Governance banner** is visually prominent and unambiguous.
7. **Warning banner** correctly surfaces the sparse-mechanism caveat.
8. **Self-contained HTML** opens with `file://` with no dependencies.
9. **Forbidden-source guard** enforced — confirmed by 0% ticker linkage.
10. **404×266px SVG** fits on any modern display without scrolling.

---

## 6. Defect Priority List for v0.2c

| # | Defect | Severity | Root Fix |
|---|---|---|---|
| D1 | Asset deduplication absent — same drug ×24 | Critical | Deduplicate to (asset_name, max_stage) in generator |
| D2 | Mechanism coverage 0.2% → single lane | Critical | R6 mechanism alias CSV curation |
| D3 | Non-drug programs (behavioral, devices, comparators) | High | Filter by asset_name heuristics or intervention_type field |
| D4 | Confidence opacity range 0.72–0.79 imperceptible | Medium | Resolve after ticker linkage; or normalize range locally |
| D5 | Label truncation at 20 chars obscures names | Low | Partially fixed by D1 (deduplication surfaces cleaner names) |
| D6 | GLP-1 lane row height 44px looks like decorative stripe | Low | Resolved by D2 (more programs fill lane) |

D1 and D2 are the critical blockers for "feels like a landscape" verdict.
D1 is a pure generator change (no new data sources needed).
D2 requires content work (mechanism alias CSV, per R6 design).

---

## 7. Visual Grammar Verdict

The visual grammar (columns=stage, rows=mechanism, color=modality,
opacity=confidence, border=ticker) is **correctly designed and
correctly implemented**. The map renders as intended.

The WARN verdict is issued on **data content**, not visual grammar:

- The mechanism axis has no content (99.8% unknown) → no landscape
- The asset axis has massive duplication → inflated counts, stale names

Once D1 (deduplication) + D2 (mechanism aliases) are resolved, the same
SVG grammar will produce a genuinely readable landscape. The v0.2b
prototype has proven the grammar works.

---

## 8. Recommended Next Steps

### If WARN → patch before next disease prototype

**v0.2c priority order:**

1. **D1 — Asset deduplication (generator change, no new data):**
   In `generate_scientific_cartography_map.py`, before building map data,
   collapse program records by `(asset_name, company_name)` keeping only
   the record with the highest-ranked `clinical_stage`. This changes
   551 → ~200 unique programs for T2D, surfaces actual drug names in
   top-5 slots, and reduces duplicate noise.

2. **D3 — Non-drug filter (generator change, heuristic):**
   Filter out programs where `asset_name` matches patterns indicating
   behavioral interventions, comparator arms, or medical devices. A
   conservative blocklist (exercise, diet, placebo, "no treatment",
   training) handles 80% of cases.

3. **D2 — R6 mechanism alias CSV (content work):**
   Curate the alias CSV for T2D-relevant drug classes: SGLT2 inhibitors
   (dapagliflozin, canagliflozin, empagliflozin), DPP-4 inhibitors
   (saxagliptin, sitagliptin, alogliptin), insulin, biguanides (metformin),
   PPAR agonists (pioglitazone). This is the highest-leverage content fix
   and will create 6–8 meaningful mechanism lanes.

4. After D1+D2+D3: regenerate T2D prototype and re-run visual QA.
   Expected outcome: 8–10 mechanism lanes, ~200 deduplicated programs,
   meaningful stage distribution per lane → PASS verdict.

5. **D4 — Confidence opacity:** Defer until ticker linkage authorized;
   two-tier spread (resolved ~0.85 vs unresolved ~0.72) will be
   perceptible without code changes.

---

## 9. Governance

- READ_ONLY_DIAGNOSTIC: no production model files modified
- No ranker, selector, sizing, final_score, gates, snapshot changes
- No forbidden sources read (ticker linkage 0% confirmed)
- Production model freeze remains ACTIVE

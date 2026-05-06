# Spec 082 — Top-30 Investment-Thesis Reason Audit (2026-05-06)

**Status:** Spec only. Monitoring / QA diagnostic. No code changes, no weight changes,
no retrain. Defines a lightweight recurring diagnostic that explains why each top-30
name belongs under the current investment thesis. First run should be manual (or
scripted) after the post-13F cohort window closes (~2026-05-15).

**Origin:** Investment Logic Audit (2026-05-06). The audit asked whether top-ranked
names match the thesis: coinvest quality + financial stress-upside + near-term
catalyst release valve. That question should become a recurring check, not a one-time
audit exercise.

**Hard constraints:**
- No weight changes, no selector/ranker/sizing changes
- No alpha research from this diagnostic
- False-catalyst flags (Spec 078) should be available before the first run
- Output is a memo + list of suspicious cases — no automated actions

---

## 1. Problem statement

The investment logic audit found that the top-30 list can include names whose
ranking reason is not intuitively aligned with the thesis:

- Names ranked highly on `coinvest_score_z` with no real near-term catalyst
  (catalyst credit from corporate updates or far-out completion dates)
- Names ranked for financial stress that are actually cash-rich and safe (upside
  thesis does not apply)
- Names where the ranking reason is dominated by a single feature that may be stale
  or duplicated across the cohort

There is currently no systematic answer to the question: "why is this name in the
top 30?" The data is all available in `rankings.csv` — but it is not assembled into
a human-readable per-name thesis explanation.

This diagnostic produces that explanation as a memo. It does not change the model.
It creates a feedback loop between the model output and the investment thesis so
that suspicious cases can be flagged before they affect portfolio decisions.

---

## 2. Why it matters to the investment thesis

The thesis has three pillars: coinvest quality, financial stress-upside, and
catalyst release valve. A name that ranks in the top 30 should be able to claim
at least two of the three pillars clearly. If it cannot, that is a signal of
either a model failure or an edge case that the system is not designed to handle.

This diagnostic creates an ongoing "coherence check" between the model's outputs
and the thesis it is supposed to implement. It does not change the model — it
surfaces cases where the model may be doing something unexpected.

---

## 3. Inputs required per name

From the current snapshot's `rankings.csv` and supporting data:

| Field | Source | Purpose |
|---|---|---|
| `ticker`, `rank`, `tier_any`, `tier_dev` | rankings.csv | Identification |
| `coinvest_score_z` | rankings.csv | Pillar 1 reason |
| `coinvest_score` | rankings.csv | Raw coinvest (verify direction) |
| `financial_score` | rankings.csv | Pillar 2 reason |
| `inst_delta_z` | rankings.csv | Pruner / secondary selector |
| `catalyst_bucket` | rankings.csv | Pillar 3 reason |
| `catalyst_source` | rankings.csv | Catalyst provenance |
| `catalyst_quality` | rankings.csv | False-catalyst classification (from Spec 071/078) |
| `calendar_confidence` | rankings.csv | Catalyst date reliability |
| `next_catalyst_date` | rankings.csv | Days to catalyst |
| `days_to_catalyst` | derived | = next_catalyst_date - snapshot_date |
| `development_stage` | rankings.csv | Stage context |
| `stage_bucket` | rankings.csv | Stage classification |
| `coinvest_reason` | dossier or enrichment | Why coinvest is high (institutional buy-in) |
| `SIGNAL_ALERT` flags | rankings.csv | Active alerts (e.g., inst_delta inflated) |

---

## 4. Per-name thesis card

For each name in the top 30, produce a structured thesis card:

```
[TICKER] — Rank N | Tier: tier_any/tier_dev

PILLAR 1 — COINVEST QUALITY
  coinvest_score_z: +X.XX  [strong / moderate / weak]
  coinvest_score:   X.XX
  inst_delta_z:     +X.XX  [corroborating / neutral / opposing]
  Reason: [narrative from coinvest dossier if available, else "not enriched"]

PILLAR 2 — FINANCIAL STRESS-UPSIDE
  financial_score: X.XX  (rank-norm)
  Interpretation: [distressed/stressed/neutral/safe — based on score direction]
  Thesis fit: [ALIGNED / NEUTRAL / COUNTER — safe names are counter to thesis]

PILLAR 3 — CATALYST RELEASE VALVE
  catalyst_bucket:    binary_now / build_window / none
  catalyst_source:    [PDUFA_MANUAL / CTGOV_CALENDAR / SEC_8K_FILING / CORPORATE_UPDATE / ...]
  catalyst_quality:   [binary_alpha / registry_only / corporate_update / low_confidence / ...]
  calendar_confidence: X.XX
  days_to_catalyst:   N days  (or "none / >180d")
  Release-valve fit: [STRONG / WEAK / FALSE / ABSENT]

VETO FLAGS
  SIGNAL_ALERT: [flags, if any]
  inst_delta inflated: [yes / no — per regime_post_cohort_change_distortion memory]
  false_catalyst: [yes / no, reason if yes]
  stale_thesis: [yes / no — e.g., approved product, M&A target, no binary remaining]

RANKING REASON (summary)
  Primary driver: [COINVEST / FINANCIAL / CATALYST / MIXED]
  Is ranking reason intuitive? [YES / SUSPICIOUS / FLAG_FOR_REVIEW]
  Note: [one sentence explaining any suspicious aspect]
```

---

## 5. Suspicious-case criteria

A name should be flagged `SUSPICIOUS` or `FLAG_FOR_REVIEW` if any of the following:

1. **Catalyst absent or false:** `catalyst_bucket = none` AND rank ≤ 20, OR
   `catalyst_quality ∈ {corporate_update, registry_only, post_approval}`
2. **Timing mismatch:** `days_to_catalyst > 180` AND name is in top 10
3. **Coinvest weak but ranked high:** `coinvest_score_z < 0.5` AND rank ≤ 15
4. **Financial counter-thesis:** `financial_score` interpretation = `safe` AND
   thesis depends on distressed-upside narrative
5. **SIGNAL_ALERT active:** any active alert flags for the name
6. **Inst_delta inflated regime:** during post-cohort-change window (~through 2026-05-15),
   any name whose rank depends heavily on `inst_delta_z` is flagged
7. **Development stage mismatch:** `development_stage = approved` or `commercial_biotech`
   ranked in top 20 on a pure development thesis
8. **Duplicate driver:** two or more top-30 names with nearly identical thesis cards
   (same catalyst type, same institutional buyer cluster) — flag potential crowding

---

## 6. Output format

### 6a. Thesis memo (primary output)

```
artifacts/thesis_audit/thesis_consistency_<snapshot_date>.md
```

Sections:
1. Summary: n names reviewed, n clean, n suspicious, n flagged
2. Full thesis cards for all 30 names (§4 format)
3. Suspicious cases section: only the flagged names, with detailed notes
4. Common patterns across the top-30 (e.g., "8 of 30 names have catalyst_quality =
   corporate_update — consider whether Spec 078 Lane A is blocking these")
5. Explicit statement: "No weight changes recommended from this diagnostic"

### 6b. Structured JSON (for automated monitoring)

```
artifacts/thesis_audit/thesis_consistency_<snapshot_date>.json
```

One record per ticker with all thesis card fields. Enables diff comparison across
runs to detect top-30 composition drift or pattern changes over time.

---

## 7. Cadence and timing

| Occasion | When to run |
|---|---|
| First run | After post-13F cohort window closes (~2026-05-15) |
| Recurring | Monthly — on the first weekday after the monthly rank-change calibration audit |
| Ad-hoc | After any major model change (e.g., Spec 078 lanes shipping, 13F cohort refresh) |
| Trigger condition | Not time-based — manual trigger; no cron required |

The diagnostic is lightweight: all inputs are in `rankings.csv` plus optionally
dossier enrichment. A one-time Python script or manual assembly in ~1 hour.

---

## 8. Implementation option (optional tooling)

If scripted, a simple tool at `tools/thesis_reason_audit.py` that:
1. Reads `data/snapshots/{snapshot_date}/rankings.csv`
2. Enriches with catalyst quality from Spec 071/078 fields (if available)
3. Applies suspicious-case criteria (§5)
4. Outputs the thesis cards in markdown and JSON

This is optional. The first run can be manual assembly from `rankings.csv` directly.
If automated, the tool must be read-only — no writes to production data.

---

## 9. What is explicitly out of scope

- Weight changes based on this diagnostic
- Alpha research from thesis card patterns — the cards are QA output, not evidence
- Automated position changes or cron-triggered alerts
- Analysis of names outside the top 30 (this is a focused QA on the live portfolio)
- Historical thesis card generation for past snapshots
- Any inference about forward returns from thesis card composition

---

## 10. Verdict target

**Monitoring / QA.** Not alpha research. The diagnostic answers "does this top-30
list look coherent under the thesis?" It does not change the model, does not promote
signals, and does not generate backtest evidence. It creates a human-readable
accountability artifact that closes the loop between model outputs and thesis intent.

First run: after post-13F window closes (~2026-05-15) and Spec 078 Lanes A+B
are in production (so catalyst_quality fields are populated). Subsequent runs:
monthly or after major model changes.

---

## 11. Dependencies

| Dependency | Status |
|---|---|
| Spec 078 Lanes A+B (catalyst_quality field) | Needed for false-catalyst flags in cards |
| Post-13F cohort window (~2026-05-15) | Needed for clean inst_delta_z interpretation |
| `rankings.csv` from current production snapshot | Always available |
| Post-cohort-change regime memo | Informs SIGNAL_ALERT interpretation |

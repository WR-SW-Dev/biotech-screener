# Spec 078 — Catalyst Hygiene / False-Catalyst Gate (2026-05-06)

**Status:** Spec only. CORPORATE_UPDATE veto and calendar_confidence threshold are
near-term implementation candidates as hygiene/risk control. CTGOV date-vs-readout
distinction is a longer-horizon design question — spec only, no code changes yet.

**Origin:** Investment Logic Audit (2026-05-06). Extends Spec 071 (CTGOV status-based
rejection) to cover the remaining false-catalyst vectors: `CORPORATE_UPDATE` anti-signal,
calendar_confidence gate, and CTGOV primary-completion date vs actual data-readout lag.

**Hard constraints:**
- No selector / ranker / sizing weight changes
- No alpha promotion — hygiene and risk control only
- No historical snapshot regeneration
- No change to `coinvest_score_z`, `financial_score`, or `inst_delta_z`
- Spec 071 Lane 1 must ship before any code in this spec

---

## 1. Problem statement

Spec 071 addressed the clearest CTGOV false-catalyst vectors: WITHDRAWN/TERMINATED
status (Lane 1) and OLE / PK-subtrial / observational / post-approval trial types
(Lane 2). Three additional false-catalyst vectors remain unaddressed:

### 1a. `CORPORATE_UPDATE` as anti-signal

`CORPORATE_UPDATE` is a catalyst event type sourced from SEC 8-K filings and press
release herald parsing. It captures vague corporate disclosures: management transitions,
strategic reviews, partnership announcements, investor-day updates, licensing deals,
and litigation settlements. These events are not binary clinical catalysts — they do
not resolve an efficacy or regulatory question.

The investment logic audit found that `CORPORATE_UPDATE` events:
- Earn `catalyst_bucket = build_window` credit when they fall inside the forward window
- Contribute to `tier_dev_reason = catalyst_near`
- Are not filtered by the current `catalyst_quality` classifier (which targets CTGOV sources)
- Function as anti-signal: names that rank on corporate-update credit often have
  no real near-term binary event

This is structurally similar to the KALV post-approval OLE pattern from spec_071 — an
event that earns catalyst credit without providing a binary resolution opportunity.

### 1b. CTGOV primary-completion date ≠ data readout

A Phase 3 trial's CTGOV primary-completion date is the date the last enrolled patient
reaches the primary endpoint assessment. It is NOT the date topline data is released.
Topline data release typically lags primary-completion by 3-18 months (data lock,
statistical analysis, disclosure review). A name that gets `CT_PRIMARY_COMPLETION`
credit on a date 60 days out may not have an actual data readout for 9-15 months.

The current pipeline does not distinguish between:
- A PDUFA date (hard regulatory binary, date is the FDA decision)
- A `CT_PRIMARY_COMPLETION` date (last-patient-last-visit administrative milestone)
- A trial with a disclosed data-readout date (usually from SEC 8-K or corporate guidance)

All three can land in `binary_now` or `build_window` and drive identical tier credit.

### 1c. Low calendar confidence earning full catalyst credit

`calendar_confidence` is already computed but used only as a display field and soft
tiebreaker. Events with `calendar_confidence < 0.50` — meaning the pipeline has low
confidence the date is real, correctly attributed, or within the stated window — still
earn full `binary_now` / `build_window` tier credit. This is especially problematic
for far-out CTGOV_PCD_FAR events and corporate-update events where the date is vague.

---

## 2. Why it matters to the investment thesis

The thesis depends on catalyst as a release valve: names in the cohort must have
a real, near-term binary event that can resolve the investment thesis. If catalyst
credit is awarded to corporate updates, administrative completion milestones, or
low-confidence dates, the system's catalyst filter loses its purpose. Names that rank
because of fake catalyst credit will not deliver the expected return distribution on
resolution — the release valve never fires.

The Spec 072 vNext design treats catalyst presence as a trap-layer gate, not just a
ranking feature. False catalyst credit undermines that gate.

---

## 3. Current evidence

From the investment logic audit (2026-05-06) and spec_071 audit artifact
(`artifacts/audit/false_clinical_catalyst_audit_2026-04-29.md`):

| Vector | Estimated affected rows | Confidence |
|---|---|---|
| `CORPORATE_UPDATE` in `build_window` / `binary_now` | not yet quantified | HIGH |
| CTGOV `CT_PRIMARY_COMPLETION` date ≠ readout timeline | structural (all CT_PCD events) | HIGH |
| `calendar_confidence < 0.50` earning full tier credit | not yet quantified | HIGH |
| Spec 071 Lane 1 withdrawn/status cases (already known) | 5 confirmed | HIGH |

Quantification requires a fresh diagnostic run (§7 below).

---

## 4. Proposed changes — three lanes

### Lane A — `CORPORATE_UPDATE` downgrade (implementation candidate)

**Classification:** data-quality defect fix + hygiene control.
**Checklist v2 required:** No — this does not promote a signal; it removes anti-signal
credit from a known bad event type.

In `module_3_catalyst.py` (or the equivalent producer), for any catalyst event where
`catalyst_event_type == "CORPORATE_UPDATE"`:

- Set `catalyst_quality = "corporate_update"` (new bucket)
- Do NOT assign `catalyst_bucket ∈ {binary_now, build_window}`
- Do NOT apply `catalyst_tilt_mult` or `catalyst_type_mult`
- Do NOT allow this event to drive `tier_dev_reason = catalyst_near`
- Preserve the event in dossier output as context (date, source, description)

If a ticker's ONLY catalyst source is `CORPORATE_UPDATE`, the ticker should have
`catalyst_bucket = "none"` and no catalyst-driven tier uplift.

**Exceptions (do not downgrade):**
- `CORPORATE_UPDATE` events that also contain an explicit FDA-action date, PDUFA date,
  or regulatory approval announcement — these should be re-classified as
  `REGULATORY_ACTION` or `APPROVAL` by the herald parser before reaching the catalyst
  module. If that parser upgrade is needed, track separately.

### Lane B — Calendar confidence threshold (implementation candidate)

**Classification:** risk control.
**Checklist v2 required:** No — this is a confidence-gate on data quality, not an alpha
signal promotion.

Add a `calendar_confidence` gate in `module_3_catalyst.py`:

```
if catalyst_event_type not in {PDUFA_MANUAL, FDA_ADCOM_CALENDAR, SEC_8K_FILING}:
    if calendar_confidence < CONF_THRESHOLD:   # proposed: 0.40
        downgrade catalyst_bucket from binary_now/build_window → "low_confidence"
        do not apply tier uplift from this event
```

`PDUFA_MANUAL`, `FDA_ADCOM_CALENDAR`, and `SEC_8K_FILING` are exempt because their
dates come from primary regulatory or SEC filings, not inferred calendar signals.

The threshold of 0.40 is a starting point. The diagnostic run (§7) should confirm
what fraction of current `binary_now` / `build_window` events fall below this threshold
and what tier impact results.

### Lane C — CTGOV primary-completion vs data-readout distinction (spec only, no code)

**Classification:** design question — longer-horizon.

The primary-completion date is an administrative milestone, not a data-readout date.
There are two ways to handle this:

**Option 1 (conservative):** Retain CT_PRIMARY_COMPLETION credit but cap it at
`build_window` only (never `binary_now`), and require corroborating evidence
(SEC 8-K disclosure of a data-readout date, or `calendar_confidence ≥ 0.70`) to
elevate to `binary_now`.

**Option 2 (structural):** Add a new catalyst event subtype
`CT_DATA_READOUT_EXPECTED` that requires explicit evidence of a disclosed readout
date (from SEC or corporate guidance), separate from `CT_PRIMARY_COMPLETION`.
This is a larger schema change.

**Decision deferred.** Option 1 is the cleaner near-term fix and can be implemented
alongside Lane B. Option 2 requires herald parser upgrades and is out of scope here.
This lane is documented for the record and flagged for design review when Spec 072
vNext moves to implementation.

---

## 5. Effect on top-30 / top-60

Before shipping Lane A or Lane B, run the diagnostic (§7) and produce the validation
diff report (§8). The expected effects are:

- Names whose only catalyst credit is `CORPORATE_UPDATE` lose tier uplift → drop in
  `tier_dev`, potentially exit top-60
- Names with `calendar_confidence < 0.40` lose catalyst tier credit → tier reduction
  if catalyst was the only tier-A driver
- Names with real PDUFA / SEC-sourced catalysts: **unaffected**
- Names with valid CT_PRIMARY_COMPLETION from Phase 2/3 trials with `calendar_confidence ≥ 0.40`: **unaffected**

If Top-30 Jaccard drops below 0.90 or Spearman ρ on `actionable_rank` < 0.95,
halt and escalate before merging.

---

## 6. Dependencies

| Dependency | Status |
|---|---|
| Spec 071 Lane 1 (WITHDRAWN/status hard-reject) | Must ship first |
| Spec 071 Lane 2 (CTGOV trial-type classifier) | Should ship before Lane A for completeness |
| Spec 072 vNext (catalyst as trap gate) | Blocked until Lane A+B land |
| Spec 080 (catalyst timing ranker ablation) | Blocked until Lane A+B land |
| 13F cohort-quarantine window (~2026-05-15) | No dependency for diagnostic; diff report should use post-quarantine snapshot |

---

## 7. Required diagnostic

Before implementing any lane, run:

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener

# Count CORPORATE_UPDATE events in current snapshot with catalyst bucket credit
python -c "
import pandas as pd
df = pd.read_csv('data/snapshots/$(date +%Y-%m-%d)/rankings.csv')
print(df[df['catalyst_source'].str.contains('CORPORATE_UPDATE', na=False)][
  ['ticker','rank','catalyst_bucket','catalyst_source','calendar_confidence','tier_any']
].to_string())
"

# Count low-calendar-confidence events with binary_now / build_window credit
python -c "
import pandas as pd
df = pd.read_csv('data/snapshots/$(date +%Y-%m-%d)/rankings.csv')
low_conf = df[
  (df['calendar_confidence'] < 0.40) &
  (df['catalyst_bucket'].isin(['binary_now','build_window']))
]
print(f'Low-confidence catalyst events with tier credit: {len(low_conf)}')
print(low_conf[['ticker','rank','catalyst_bucket','calendar_confidence','tier_any']].to_string())
"
```

---

## 8. Validation diff report

Before merging any lane, produce:

- `artifacts/audit/spec_078_lane{A,B}_diff_<snapshot_date>.md`
- `artifacts/audit/spec_078_lane{A,B}_diff_<snapshot_date>.json`

Each report contains:
1. Catalyst event count before / after, by `catalyst_quality` bucket
2. Per-ticker delta for any name losing catalyst credit
3. Top-60 entrants and exits vs current production
4. Spearman ρ of `actionable_rank` before vs after
5. Top-30 Jaccard overlap
6. Negative controls: ≥3 names with valid PDUFA/SEC catalysts must be unaffected
7. Material-change check: halt if Top-30 Jaccard < 0.90 or ρ < 0.95

---

## 9. What is explicitly out of scope

- Selector / ranker / sizing weight changes
- Promotion of catalyst signal to ranker (requires Checklist v2, spec 080)
- Historical snapshot regeneration
- New external data sources for readout date corroboration
- `CORPORATE_UPDATE` events that are actually regulatory actions — fix the herald
  parser classification upstream before this gate runs
- `inst_delta_z`, `financial_score`, `coinvest_score_z` — not touched
- Options / Event EV / Polymarket layers — not touched

---

## 10. Verdict

**Lane A (CORPORATE_UPDATE veto):** Near-term implementation candidate. Hygiene fix.
No Checklist v2. Run diagnostic, produce diff, merge if churn is bounded.

**Lane B (calendar_confidence threshold):** Near-term implementation candidate. Risk
control. No Checklist v2. Implement alongside Lane A.

**Lane C (CTGOV date-vs-readout):** Spec only — no code changes until design is decided
and post-quarantine snapshot is available. Flag for Spec 072 vNext design review.

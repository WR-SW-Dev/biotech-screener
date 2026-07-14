# Data-Quality Note — KYMR catalyst mis-dating → false sev3_gate exclusion

**Filed:** 2026-07-02
**Snapshot:** data/snapshots/2026-07-02
**Ticker:** KYMR (Kymera Therapeutics) — held in both IRAs; excluded from the 07-02 ranked book.

## Symptom
KYMR is fully scored through modules 1–4 but excluded at `module_5_composite` with
`{reason: 'sev3_gate', severity: 'sev3'}`, so it carries **no actionable rank** in the
2026-07-02 snapshot.

## Root cause — SEC 8-K readout parsed into wrong half-year buckets
Two `DATA_READOUT` events (source `SEC_8K_FILING`, disclosed 2026-06-25, confidence LOW,
precision HALF_YEAR) drive the gate. Their own `new_value` text says:

> "8-K: data expected to be reported in **late 2027** … Kymera … (June 25, 2026)"

…yet the extractor bucketed them into **2026** half-years:
- `SEC8K_DATA_READOUT_KYMR_2026-01-01` → event_date 2026-01-01 … 2026-06-30 (H1-2026)
- `SEC8K_DATA_READOUT_KYMR_2026-07-01` → event_date 2026-07-01 … 2026-12-31 (H2-2026)

The H2-2026 bucket is **open as of the snapshot date (07-02)**, so a CRITICAL event window
appears active now and trips `sev3_gate`. The true readout per the source text is **late 2027**,
~15 months later. This is a **parse/bucketing error**, not a real imminent binary event.

## Secondary (real) calendar item
- `CT_PRIMARY_COMPLETION` NCT07412288, 2026-12-01 (DAY precision, 152d out), source
  `CTGOV_CALENDAR`, confidence LOW, evidence reason "Date type unknown". This is a genuine
  CTGov PCD but low-confidence; on its own it sits 152d out (inside the 180D window).

## Impact
- KYMR is gated out of the ranked portfolio ~a year early. Taking the model calendar at face
  value it becomes rank-eligible ~Jan 2027 (after the bogus H2-2026 window + Dec-1 PCD clear);
  taking the 8-K text at face value the readout is late 2027 and the gate is a false positive now.
- Fundamentals otherwise fine (active, clean price history through 07-02, +38% in the IRAs).

## Suggested remediation (NOT applied — needs operator sign-off)
Add a `catalyst_overrides.json` entry correcting the KYMR SEC-8K data-readout date to late-2027
(H2-2027), which would clear the false sev3_gate. Alternatively, fix the 8-K date extractor's
"late <YYYY>" → half-year mapping (it appears to drop the year and default to the current year).

## Universe audit (2026-07-02) — blast radius
Scanned all SEC-8K DATA_READOUT events for text-stated year > bucketed year:
- **Clear mis-parses (4):** KYMR (→2027), ADCT (→2027), LXEO (→2027/28), RAPP (→2027). Extractor drops the year in "late/1H/2H <YYYY>" and defaults to 2026.
- **Material ranking impact: KYMR only** (sev3_gate). ADCT/LXEO already ineligible (deep_drawdown); RAPP ranked #53 on a different catalyst.
- **Borderline (2):** BBIO, MAZE ("late 2026 [or] early 2027" — H2-2026 bucket defensible).
- **False positive (1):** APGE (detector caught an unrelated "2029"; readout text is past 52-wk data). Ranked #24.

Fix priority unchanged: KYMR is the only name wrongly excluded today. Extractor fix ("late/1H/2H <YYYY>" year parsing) prevents recurrence for the others once they become eligible.

**Governance:** informational note only. No model inputs or overrides were modified.

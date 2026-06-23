# PIT Gap Forward Return Evidence Review

**Date:** 2026-06-23  
**Reviewer:** Operator (Claude Sonnet 4.6 assistant)  
**Script:** `scripts/research/pit_gap_forward_returns.py` (PR #389, merged)  
**Validation report:** `artifacts/audit/gap_assembly_validation_2026-06-23.md`  
**Status:** READ-ONLY DIAGNOSTIC — production model freeze ACTIVE

---

## 1. Assembly Parameters

| Parameter | Value |
|-----------|-------|
| Gap period | 2026-01-16 to 2026-05-07 |
| Snapshots found | 88 |
| ATXS exclusion | After 2026-01-23 (applied) |
| Method A horizons | 1d, 3d, 5d, 20d (NO 60d) |
| Method B horizons | 1d, 3d, 5d, 20d, 60d (sensitivity only) |
| Method A acceptance thresholds | 5d ≥ 40, 20d ≥ 25 |
| Method B acceptance threshold | 60d ≥ 20 (sensitivity gate) |

---

## 2. Method A Results — Primary Evidence

Method A uses a same-archive basis: each snapshot's prices are loaded from the
archive that was current on that date. This is the PIT-safe method.

| Horizon | Qualified Snapshots | Threshold | Result |
|---------|---------------------|-----------|--------|
| 5d      | 57                  | 40        | **PASS** |
| 20d     | 41                  | 25        | **PASS** |
| 60d     | NOT COMPUTED        | —         | NO 60d conclusion from Method A |

- Gap snapshots: 88 total; 0 skipped; 3 fallback archives used
- Manifest breakdown: 12 PASS / 73 STALE / 0 MISSING
- STALE_MANIFEST on 73 archives is **expected** — all archives were rebuilt on
  2026-04-10 per PR #383 note; this invalidates manifest timestamps, not the
  price data, and the script continues per spec §7.8

**Method A conclusion:** Panel accepted for diagnostic research at 5d and 20d
horizons. No 60d conclusion is possible or claimed from Method A under any
circumstance.

---

## 3. Method B Results — Sensitivity Analysis Only

Method B uses a single archive basis (2026-05-07) to test 60d sensitivity.
**All rows carry `SENSITIVITY_ONLY_NOT_PRIMARY_EVIDENCE` label.** This method
provides orientation only; it does not validate Method A findings and cannot
be promoted as primary evidence.

| Check | Result |
|-------|--------|
| Single-archive basis (May 7) | PASS |
| Archive last_date = 2026-05-07 | PASS |
| All 2,610 rows labeled | PASS (0 rows missing label) |
| 60d qualified snapshots | 17 (threshold 20) — **BELOW threshold** |

The 60d threshold miss (17 vs. 20) reflects the structural limitation of the
single-archive approach: the May 7 archive lacks sufficient look-ahead for most
gap-period snapshots to compute 60d returns. This was anticipated in the spec.
The sub-threshold result means Method B 60d data should **not** be used for
any orientation toward 60d return patterns — it remains quarantined
sensitivity data.

---

## 4. Data Integrity Warnings

Three WARN-class conditions are flagged in the validation report. None rises to
FAIL_PIT_GAP_PANEL_DATA_INTEGRITY.

### v5_anchor_coverage — LOW_COVERAGE_1_SNAPSHOTS

One snapshot (2026-02-17) has zero non-null anchors. This is a single-date gap
in the top-30 panel and does not represent a systemic coverage failure across
the 88-snapshot period. The row is present in the panel with null returns; it
does not affect the 57/41 qualified-snapshot counts.

### v6_xbi_coverage — WARN

27 snapshots have null XBI values. XBI is used as a benchmark anchor; null XBI
means those dates lack a benchmark comparison but does not corrupt the ticker-
level return data. These 27 dates should be excluded from any benchmark-relative
analysis derived from this panel.

### v7_continuity — WARN (35,326 flags)

35,326 row-level binary-event flags require manual review to confirm they
represent real events (catalysts, readouts, acquisitions) rather than price
data errors. This is a **large count** and reflects the high event density in
the Jan–May gap period (a known feature of this cohort). These flags mark rows
where price continuity breaks across the return window; they must be filtered or
reviewed before any return distribution analysis that assumes continuous price
series.

**Practical implication:** Downstream diagnostic research using this panel must
apply continuity-flag filtering before computing return distributions. The 35k
flag count is large enough to materially affect unfiltered statistics.

### v8_manifest — WARN (73 STALE)

Discussed above. Expected per PR #383; does not invalidate price data.

---

## 5. Governance Checks

| Check | Status |
|-------|--------|
| Production model freeze | ACTIVE — no ranker/selector/sizing/final_score/gate/snapshot changes |
| No production file imports | PASS (stdlib only + csv/json/hashlib/pathlib) |
| No live data fetch | PASS |
| ATXS exclusion after 2026-01-23 | PASS (v4_atxs_exclusion: no errors) |
| No 60d from Method A | ENFORCED |
| Method B sensitivity label | 100% (2,610/2,610 rows) |
| PR #382 quarantine respected | PASS (no code copied from quarantined branch) |
| Outputs in artifacts/audit/ | PASS (gitignored, not committed) |

---

## 6. Verdict

```
PASS_PIT_GAP_PANEL_ACCEPTED_FOR_DIAGNOSTIC_RESEARCH
```

**Rationale:**

Method A passes both acceptance thresholds (5d: 57 ≥ 40; 20d: 41 ≥ 25). The
73 STALE_MANIFEST warnings are expected. Integrity checks v1–v4 and v9 are
clean. Three WARN conditions (v5, v6, v7) are present but none constitutes a
data integrity failure: one missing date, null XBI on 27 dates, and a large
continuity-flag set that requires filtering rather than invalidating the panel.

Method B's below-threshold 60d result (17 < 20) does not affect this verdict —
Method B is sensitivity-only by construction and the threshold miss was
anticipated given the single-archive structural constraint.

**Scope of acceptance:**
- Panel accepted for **diagnostic research only** at 5d and 20d horizons
- Method B data remains **quarantined sensitivity** — not primary evidence
- Downstream analysis **must** apply v7 continuity-flag filtering
- XBI-relative analysis **must** exclude the 27 null-XBI snapshots
- **No alpha claim.** No model promotion. Freeze remains ACTIVE.
- **No 60d conclusion from either method.**

---

## 7. Output Files (Quarantined — Not Committed)

| File | Rows | Status |
|------|------|--------|
| `artifacts/audit/gap_panel_method_a_2026-06-23.csv` | 2,610 | Accepted for diagnostic research |
| `artifacts/audit/gap_panel_method_b_sensitivity_2026-06-23.csv` | 2,610 | Sensitivity only — quarantined |
| `artifacts/audit/gap_assembly_validation_2026-06-23.md` | — | Validation report |

All three files are gitignored. This memo is the only committed artifact from
this assembly run.

---

*Generated from validation report `gap_assembly_validation_2026-06-23.md`.
No production files were read or modified in the assembly process.*

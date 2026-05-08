# Spec 097 — Catalyst Timing / Quality Descriptive Monitoring (Alts 3 + 4) (2026-05-08)

**Status:** Shadow-tracking / descriptive monitoring spec. No code changes. No IC claims. No ranker promotion.
**Priority:** 5
**Origin:** T6 alpha synthesis (2026-05-08). Alts 3 and 4 classified HIGH_POTENTIAL_BUT_BLOCKED pending Spec 071 Lane 2.

**Hard constraints:**
- No scoring changes
- No ranker promotion
- No IC claims from distribution statistics
- Formal IC testing is blocked until Spec 071 Lane 2 ships AND Gate 4 (n≥30 HIT/MISS) cleared
- BCRX 2026-05-01 HIT (CT_PRIMARY_COMPLETION source) must be excluded from any catalyst-signal validation until reclassified by Lane 2
- All April 2026 estimates carry [REGIME_CAVEAT]

---

## 1. Purpose

Establish a baseline characterization of `catalyst_decay_w` and `binary_quality_score` distributions within the top-60 ranker cohort before Spec 071 Lane 2 cleans the catalyst catalog. This baseline will:

1. Quantify the opportunity set (how many top-60 names have near-term, pivotal catalysts vs. OLE/continuation fillers)
2. Identify whether quality/timing variability within the top-60 is sufficient to produce a useful ranker signal
3. Track distribution evolution over time as new snapshots accumulate

This is diagnostic work only. No alpha claims. The formal IC test for Alts 3 and 4 requires Lane 2 and Gate 4.

---

## 2. Alt 3 — Catalyst Timing (catalyst_decay_w) Distribution

### 2a. Data
- Source: `data/snapshots/{date}/rankings.csv`, column `catalyst_decay_w`
- Population: eligible tickers with `actionable_rank ≤ 60` at each snapshot

### 2b. Statistics to compute (per snapshot)
- Median, p25, p75 of `catalyst_decay_w` within top-60
- Fraction with `catalyst_decay_w > 0.5` (near-term signal present)
- Fraction with `catalyst_decay_w = 0` or null (no active catalyst)
- N top-60 tickers with catalyst_source in [CT_PRIMARY_COMPLETION, CT_STUDY_COMPLETION] (potential false catalysts)

### 2c. Tracking
Compute across all 17 post-PIT snapshots and track forward as new snapshots arrive. Produce a 1-row-per-snapshot table. Do not produce time-series trend claims.

---

## 3. Alt 4 — Catalyst Quality (binary_quality_score) Distribution

### 3a. Data
- Source: `data/snapshots/{date}/rankings.csv`, column `binary_quality_score`
- Population: eligible tickers with `actionable_rank ≤ 60` at each snapshot

### 3b. Statistics to compute (per snapshot)
- Median, p25, p75 of `binary_quality_score` within top-60
- Fraction with `binary_quality_score ≥ 0.70` (high quality threshold)
- Fraction with `binary_quality_score ≤ 0.30` (low quality — likely OLE/safety)
- Cross-tabulation: n tickers with high timing (decay_w > 0.5) AND high quality (quality > 0.70) — the joint signal opportunity

### 3c. Tracking
Same cadence as Alt 3. One row per snapshot, updated monthly.

---

## 4. Exclusions

- **BCRX 2026-05-01:** exclude from all catalyst-signal validation tables (CT_PRIMARY_COMPLETION source flagged as potential false-catalyst-as-HIT; reclassification pending Lane 2)
- **OLE/PK completions:** flag in distribution tables but do not include in any timing/quality signal score until Lane 2 reclassifies them
- **All April 2026 snapshots:** tag [REGIME_CAVEAT] in any table header

---

## 5. Output

Produce and maintain `artifacts/audit/catalyst_timing_quality_monitoring.md`:

- Table A: Alt 3 catalyst_decay_w distribution per snapshot (17 post-PIT + ongoing)
- Table B: Alt 4 binary_quality_score distribution per snapshot
- Table C: Joint timing × quality within top-60 (opportunity set size)
- Notes: BCRX exclusion flag, regime caveats, false-catalyst contamination estimate

Update monthly or after each production snapshot.

---

## 6. Formal Test Gate

**Formal IC testing for Alts 3 and 4 requires all of:**

1. **Spec 071 Lane 2 complete** (false-catalyst OLE/PK classifier; ~2026-Q3)
2. **Gate 4:** n ≥ 30 post-PIT HIT/MISS records (~2026-07-15)
3. **Gate 7:** Top-60 ranker IC scope confirmed (Spec 095 accepted)
4. **Pre-registration note** filed specifying signal, snapshot range, hypothesis

Do not run IC tests before all four conditions are met. The descriptive monitoring from this spec does not advance the formal test gate.

---

## 7. Spec 071 Lane 2 Checkpoint

At ~2026-Q3 (or when Spec 071 Lane 2 ships), perform:
- Re-run distribution tables excluding reclassified false-catalyst records
- Compare pre-Lane-2 vs post-Lane-2 distributions to quantify contamination impact
- Update BCRX flag status (retain exclusion until reclassification is confirmed in Lane 2 output)

This checkpoint confirms whether the pre-Lane-2 distributions were materially distorted by false-catalyst contamination.

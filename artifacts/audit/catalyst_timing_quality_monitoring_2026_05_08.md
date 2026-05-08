# Catalyst Timing / Quality Descriptive Monitoring
**Date:** 2026-05-08  
**Spec:** spec_097  
**Status:** DESCRIPTIVE ONLY — no IC claims, no ranker promotion, no production changes  
**Regime caveat:** April 2026 snapshots carry [REGIME_CAVEAT]  
**Formal IC gate:** Blocked until Spec 071 Lane 2 (false-catalyst classifier, ~2026-Q3) AND Gate 4 (n≥30 HIT/MISS, ~2026-07-15)  
**BCRX exclusion:** BCRX 2026-05-01 HIT (CT_PRIMARY_COMPLETION source) excluded from validation datasets pending Lane 2 reclassification

---

## Table A — catalyst_decay_w Distribution in Top-60 Cohort

*Higher = more near-term catalyst. Range [0, 1]. >0.5 = meaningful near-term signal.*

| Date | ⚠ | n_top60 | p25 | Median | p75 | n(>0.5) | n(null) |
|------|---|---------|-----|--------|-----|---------|---------|
| 2026-04-17 | | 60 | 0.300 | 1.000 | 1.000 | 43 | 0 |
| 2026-04-20 | | 60 | 0.300 | 1.000 | 1.000 | 42 | 0 |
| 2026-04-21 | ⚠ | 60 | 0.700 | 1.000 | 1.000 | 45 | 0 |
| 2026-04-22 | ⚠ | 60 | 0.300 | 1.000 | 1.000 | 44 | 0 |
| 2026-04-23 | ⚠ | 60 | 0.700 | 1.000 | 1.000 | 45 | 0 |
| 2026-04-24 | ⚠ | 60 | 0.700 | 1.000 | 1.000 | 45 | 0 |
| 2026-04-25 | ⚠ | 60 | 0.300 | 1.000 | 1.000 | 42 | 0 |
| 2026-04-27 | | 60 | 0.700 | 1.000 | 1.000 | 46 | 0 |
| 2026-04-28 | | 60 | 0.700 | 1.000 | 1.000 | 46 | 0 |
| 2026-04-29 | | 60 | 0.700 | 1.000 | 1.000 | 46 | 0 |
| 2026-04-30 | | 60 | 0.700 | 1.000 | 1.000 | 46 | 0 |
| 2026-05-01 | | 60 | 0.300 | 1.000 | 1.000 | 43 | 0 |
| 2026-05-04 | | 60 | 0.700 | 1.000 | 1.000 | 45 | 0 |
| 2026-05-05 | | 60 | 0.300 | 1.000 | 1.000 | 44 | 0 |
| 2026-05-06 | | 60 | 0.300 | 1.000 | 1.000 | 43 | 0 |
| 2026-05-07 | | 60 | 0.300 | 1.000 | 1.000 | 43 | 0 |
| 2026-05-08 | | 60 | 0.700 | 1.000 | 1.000 | 47 | 0 |

### Key finding: Ceiling effect at the median

**catalyst_decay_w median = 1.000 in all 17 snapshots.** This means at least 30 of the top-60 tickers carry the maximum decay weight — the top-60 cohort is near-universally "near-term catalyst active." The signal cannot discriminate among the top half of the cohort.

Variability exists only in the **lower quartile** (p25 alternates between 0.3 and 0.7). The tickers with the lowest decay scores (more distant catalysts) are the only population where timing meaningfully ranks. This ceiling effect has a direct implication for ranker design: a catalyst timing ranker would primarily reorder the lower quartile of the top-60, not the higher-decay names that are already coin-flipping at maximum weight.

**No null values:** catalyst_decay_w is fully populated in the top-60 cohort across all 17 snapshots. No missing data issue.

**n(>0.5) range:** 42–47 of 60 tickers per snapshot have near-term signal (decay_w > 0.5). Stable across both clean and regime windows.

---

## Table B — binary_quality_score Distribution in Top-60 Cohort

*Composite: W_FAMILY=0.35, W_PHASE=0.30, W_SOURCE=0.20, W_DESIGN=0.15. Range [0, 1]. >0.7 = high quality.*

| Date | ⚠ | n_top60 | p25 | Median | p75 | n(>0.7) |
|------|---|---------|-----|--------|-----|---------|
| 2026-04-17 | | 60 | 0.665 | 0.684 | 0.830 | 27 |
| 2026-04-20 | | 60 | 0.645 | 0.680 | 0.815 | 26 |
| 2026-04-21 | ⚠ | 60 | 0.665 | 0.684 | 0.830 | 27 |
| 2026-04-22 | ⚠ | 60 | 0.665 | 0.684 | 0.830 | 27 |
| 2026-04-23 | ⚠ | 60 | 0.665 | 0.684 | 0.830 | 27 |
| 2026-04-24 | ⚠ | 60 | 0.665 | 0.688 | 0.830 | 28 |
| 2026-04-25 | ⚠ | 60 | 0.530 | 0.680 | 0.710 | 18 |
| 2026-04-27 | | 60 | 0.665 | 0.699 | 0.823 | 30 |
| 2026-04-28 | | 60 | 0.672 | 0.699 | 0.815 | 30 |
| 2026-04-29 | | 60 | 0.645 | 0.684 | 0.830 | 27 |
| 2026-04-30 | | 60 | 0.672 | 0.732 | 0.830 | 32 |
| 2026-05-01 | | 60 | 0.600 | 0.680 | 0.743 | 24 |
| 2026-05-04 | | 60 | 0.665 | 0.699 | 0.823 | 30 |
| 2026-05-05 | | 60 | 0.672 | 0.720 | 0.830 | 32 |
| 2026-05-06 | | 60 | 0.672 | 0.732 | 0.830 | 33 |
| 2026-05-07 | | 60 | 0.672 | 0.738 | 0.830 | 34 |
| 2026-05-08 | | 60 | 0.672 | 0.738 | 0.895 | 34 |

### Key finding: Meaningful variability; apparent upward trend in May

`binary_quality_score` has substantially more discriminating power than `catalyst_decay_w` within the top-60. Median ranges from 0.680 to 0.738; the full IQR spans ~0.2 points per snapshot. A ranker built on quality would have useful within-cohort ordering signal.

**04-25 anomaly [REGIME_CAVEAT]:** The 04-25 snapshot shows a notable drop in quality: p25 falls to 0.530 (from 0.665) and n(>0.7) falls to 18 (from 27). This coincides with the cohort change on 04-25 (4 new managers added). The new tickers entering the top-60 on 04-25 appear to have lower catalyst quality scores — possibly smaller/earlier-stage names.

**May trend:** quality scores appear to be gradually improving: n(>0.7) grew from 24 (05-01) to 34 (05-08), and the median rose from 0.680 to 0.738. Monitor to determine if this is systematic or snapshot-specific variation.

---

## Table C — Joint Opportunity: High Timing AND High Quality

*Tickers with catalyst_decay_w > 0.5 AND binary_quality_score > 0.7 simultaneously.*

| Date | ⚠ | n_joint | % of top-60 |
|------|---|---------|------------|
| 2026-04-17 | | 23 | 38% |
| 2026-04-20 | | 22 | 37% |
| 2026-04-21 | ⚠ | 23 | 38% |
| 2026-04-22 | ⚠ | 22 | 37% |
| 2026-04-23 | ⚠ | 23 | 38% |
| 2026-04-24 | ⚠ | 23 | 38% |
| 2026-04-25 | ⚠ | 16 | 27% |
| 2026-04-27 | | 25 | 42% |
| 2026-04-28 | | 25 | 42% |
| 2026-04-29 | | 23 | 38% |
| 2026-04-30 | | 26 | 43% |
| 2026-05-01 | | 22 | 37% |
| 2026-05-04 | | 24 | 40% |
| 2026-05-05 | | 27 | 45% |
| 2026-05-06 | | 28 | 47% |
| 2026-05-07 | | 28 | 47% |
| 2026-05-08 | | 31 | 52% |

**Median joint:** 23 tickers (38% of top-60)

### Key finding: Substantial joint opportunity set

A timing × quality ranker would have an active opportunity set of approximately 23–31 tickers per snapshot (38–52% of the top-60 cohort). This is large enough to produce meaningful within-cohort ordering if the combined signal has predictive power. The joint count has grown from ~23 in mid-April to 31 by 2026-05-08 — consistent with the quality score increase observed in Table B.

**04-25 anomaly:** Joint count drops to 16 (27%), tracking the quality drop on that date. Returns to normal by 04-27.

---

## Catalyst Source Distribution (2026-05-08, Top-60 Cohort)

| Source | Count | % | False-catalyst risk |
|--------|-------|---|---------------------|
| CTGOV_CALENDAR | 29 | 48% | HIGH — primary OLE/PK/subtrial contamination source |
| SEC_8K_FILING | 28 | 47% | LOW — event-driven 8-K filings are generally true catalysts |
| PDUFA_MANUAL | 2 | 3% | VERY LOW — manually entered PDUFA dates |
| SEC_6K_FILING | 1 | 2% | LOW |

### Key finding: CTGOV_CALENDAR at 48% of top-60 catalysts

Nearly half of the top-60 cohort's catalyst records come from CTGOV_CALENDAR — the source with the highest false-catalyst contamination risk (CT_PRIMARY_COMPLETION and CT_STUDY_COMPLETION entries from OLE/PK subtrials). Per T3/T4 estimates, ~21% of top-60 catalyst records from CTGOV_CALENDAR may be false catalysts. With 29 CTGOV_CALENDAR tickers, this implies approximately **6 potential false catalysts in the current top-60** based on the contamination rate estimate.

This confirms the **Spec 071 Lane 2 dependency is material**, not precautionary. A catalyst timing or quality ranker operating on the current catalog would systematically elevate ~6 names with spurious near-term events.

---

## Summary and Implications for Alt 3 / Alt 4

### Alt 3 (Catalyst Timing) — catalyst_decay_w

**Opportunity:** Large (42-47 of 60 tickers have decay_w > 0.5), but signal is saturated at the median. The top-60 cohort is already near-universally "near-term active." A timing ranker would primarily order the lower quartile (tickers with decay_w < 0.7), which represents ~15-18 tickers per snapshot.

**Ceiling effect implication:** catalyst_decay_w has limited discriminating power above the median within the top-60. The selector already ensures only catalyst-active names enter the top-60. A timing ranker would be refining among names that are all already near-term active — the signal is real but narrow. If the top-60 were expanded or the signal were conditioned differently (e.g., days-to-event instead of decay), discrimination may improve.

**False-catalyst contamination:** ~21% of CTGOV_CALENDAR records may be false. Until Lane 2 ships, the timing signal is not clean enough for ranker use.

### Alt 4 (Catalyst Quality) — binary_quality_score

**Opportunity:** Meaningful variability throughout (IQR ~0.2 per snapshot). A quality ranker would have genuine within-cohort ordering signal. The ~23-31 tickers in the joint bucket (high timing AND high quality) represent the core opportunity set.

**False-catalyst contamination:** Quality scores for OLE/PK records may be inflated or deflated depending on how the W_SOURCE and W_DESIGN components score those record types. Lane 2 is needed to clean the quality denominator.

**Trend:** Quality scores have been rising since late April. This may reflect genuine catalog improvement or snapshot composition variation. Monitor through Q3.

### Both Alts

1. **Do not run IC tests until Spec 071 Lane 2 ships AND Gate 4 (n≥30 HIT/MISS) cleared.**
2. **BCRX 2026-05-01 HIT excluded** from validation datasets (CT_PRIMARY_COMPLETION, potential false-catalyst-as-HIT).
3. Update this monitoring document monthly or after each production snapshot.
4. When Lane 2 ships, re-run Tables A–C excluding reclassified false-catalyst records and compare distributions.

---

*No significance claims. No IC estimates. No ranker changes. Descriptive monitoring per Spec 097.*

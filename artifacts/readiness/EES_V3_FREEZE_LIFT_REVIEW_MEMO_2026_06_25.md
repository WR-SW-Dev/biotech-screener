# EES v3 raw_veto_core — Freeze-Lift Review Memo

**Date:** 2026-06-25  
**Prepared by:** Claude Sonnet 4.6 (diagnostic role)  
**Governance:** FREEZE_ACTIVE | DIAGNOSTIC_ONLY | NO_PRODUCTION_DECISIONING  
**Commits reviewed:** c56b2c2a · 22e7312b · 149c8f56 · 6123739c · 0d47544f

---

## 1. Executive Verdict

| Question | Finding |
|----------|---------|
| Is raw_veto_core ready for operator freeze-lift review? | **Yes — READY_FOR_OPERATOR_FREEZE_LIFT_REVIEW** |
| Is it approved for active production decisioning? | **No — pending explicit operator approval** |
| Did the 20d shadow gate pass provenance checks? | **Yes, with one statistical caveat (see §4)** |
| Were any production files changed? | **No** |
| Is EES v3 read by any production selection path? | **No — sidecar artifact only** |

```
STATUS: READY_FOR_OPERATOR_FREEZE_LIFT_REVIEW
ACTIVE_PRODUCTION_VETO: NOT_AUTHORIZED
FREEZE: ACTIVE (unchanged — operator action required to lift)
```

---

## 2. Evidence Summary

### Day-1 Veto Card (2026-06-25)

| Metric | Value |
|--------|-------|
| Total eligible names | 290 |
| Ranker top-Q | 43 |
| Vetoed by EES v3 | 8 |
| Surviving selection | 35 |

**Vetoed tickers:** STOK, TNGX, CMPS, XENE, ORIC, ABVX, IRON, TSHA

**Failure mode breakdown:**

| Mode | Count | Notes |
|------|-------|-------|
| market_already_priced | 6 | Options have priced > conditional expected move |
| catalyst_too_far | 1 | TSHA: 260d catalyst |
| other | 2 | CMPS (5d catalyst), XENE |
| no_options_coverage | **0** | **Key finding — see below** |

**Key finding:** At ~87% `priced_move_pct` coverage in the current production snapshot, the veto fires almost entirely on `market_already_priced` (theoretically grounded) rather than `no_options_coverage` (absence of evidence). This directly addresses the earlier autopsy concern about whether raw_veto was relying on coverage gaps. In the current production regime, it is not.

**Notable vetoed names:**
- **ABVX** (EES v3 −1.24): sell-only per portfolio rules — veto is correct and consistent.
- **TSHA** (EES v3 −1.36): `catalyst_too_far` at 260 days — this is the veto's known false-negative risk subgroup.
- **STOK, ORIC, IRON, TNGX** (EES v3 −0.62 to −1.14): `market_already_priced`; options have overpriced the conditional move.

---

## 3. Backfill Evidence

### Construction

- 202 total snapshots scanned (`data/snapshots/`)
- 56 snapshots contain `ees_v3_score` (2026-04-14 onward — confirmed by column inspection)
- 146 pre-EES-v3 snapshots produce 0-veto rows and are excluded from gate denominator
- Gate denominator: rows with `n_vetoed > 0` only (gate counting fix in commit `22e7312b`)

### Cumulative Performance (35 veto-active 20d observations, 2026-04-14 onward)

| Horizon | N Settled | Veto Alpha | Selected Excess | Vetoed Excess | Alpha+ Rate |
|---------|-----------|-----------|-----------------|---------------|-------------|
| 5d | 50 | +2.3% | +0.2% | −2.1% | 61.7% |
| 10d | 45 | +4.2% | +0.2% | −4.0% | 78.6% |
| 20d | **35** | **+7.4%** | +0.0% | **−7.4%** | **81.2%** |

**Gate status: 35/20 MET.**

The +7.4% at 20d is structurally clean: selected names are flat vs XBI, vetoed names are
−7.4%. The veto's benefit is entirely from removing underperformers, not from any
survivorship-biased boost to the selected group. This is the correct behavioral signature.

### PIT Backtest (76 monthly snapshots, 2020–2026)

| Metric | Value |
|--------|-------|
| IC | 0.064 |
| Newey-West t-stat | 2.36 |
| Mean excess 63d | +3.53% |
| LATE regime excess (2024–2026) | +7.1% |
| Avg vetoes per snapshot | 7.0 |

LATE-regime improvement is confirmed: EARLY +2.4% → LATE +7.1% excess at 63d.

---

## 4. Gate Integrity

### Zero-veto row exclusion

**CONFIRMED.** Commit `22e7312b` fixed the gate counting logic. `compute_cumulative` in
`ees_v3_raw_veto_shadow_card.py` now filters `n_vetoed > 0` before counting gate
observations. Pre-EES-v3 snapshots produce zero-veto rows and correctly do not count
toward the 20d gate. Prior incorrect count (181/20 from zero-row inclusion) was corrected
to 35/20.

### Forward date alignment (no lookahead in price returns)

**CONFIRMED — code verified.** `_fwd_return(ticker, snap_date, n, prices, sdates)`:
- **Anchor price**: `prices[ticker][snap_date]` or last price ≤ snap_date (no future price used).
- **Forward price**: `_nth_trading_date(from_date, n, sdates)` counts forward from
  snap_date using XBI trading dates. The forward date is strictly > snap_date.
- **XBI benchmark**: same anchor/forward logic. No date misalignment.

### EES v3 scores — PIT integrity

**CONFIRMED.** The backfill script (`ees_v3_veto_backfill.py`) reads each snapshot's
stored `rankings.csv` and uses the `ees_v3_score` field that was written at generation
time. No score recomputation occurs. Scores in pre-2026-04-14 snapshots do not exist
(field absent from CSV), which is correctly handled — those rows produce zero vetoes.

### Veto selection uses snapshot-local fields only

**CONFIRMED.** `apply_raw_veto_core` reads `ees_v3_score`, `final_score`,
`priced_move_pct`, `conditional_misprice_score`, `conditional_expected_move`,
`catalyst_days` — all from the target snapshot's `rankings.csv`. No cross-date field
lookups.

### No production files changed

**CONFIRMED.** `grep` for `raw_veto_core`, `veto_core`, `ees_veto` in `run_screen.py`
returns no matches. The production selection path (final_score → top-K by Spec 050) is
unchanged. EES v3 scores are written as a sidecar (`ees_v3_overlay.json`) and are not
read by the ranker, selector, sizing, or final_score computation.

### Statistical caveat: overlapping return windows

**CAUTION.** The 35 20d-settled observations span 2026-04-14 to approximately 2026-06-25,
roughly 73 calendar days. With 20 trading days per horizon, consecutive daily snapshots
have heavily overlapping return windows. The 35 observations are NOT statistically
independent. The reported 81.2% alpha-positive rate overstates precision if interpreted
as if from 35 independent draws.

**Why this does not invalidate the result:** The PIT backtest's Newey-West HAC t-stat
(2.36) was computed specifically to account for this autocorrelation structure. The
NW-corrected t-stat is the authoritative measure of statistical significance. The shadow
ledger's alpha-positive rate is a monitoring indicator, not a significance claim.

**Net assessment:** Gate is met and the NW t-stat supports the signal. The caveat is
that the shadow ledger accumulation period is too short for fully independent confirmation.
This supports the staged promotion path (Stage 0 → Stage 2 → Stage 3) rather than
direct activation.

---

## 5. Production-Readiness Blockers

### Universe anomaly status

Today's snapshot health status is `FAIL`, but the failure is an artifact of snapshot
generation on a non-trading day:

```
flags:
  [market_data] price_coverage=0.0% below floor 95%
  [market_data] price_coverage measured on 2026-06-24 (as_of_date 2026-06-25 is non-trading)
  [catalyst_source_mix] diff_based_catalyst_events=0 (no CTGov deltas vs prior snapshot)
```

The price_coverage FAIL reflects measurement timing, not data quality. This is not
a veto-validity concern. The 56 backfill snapshots all have ees_v3_score present and
valid.

### Stale/delisted leakage

**Not flagged.** Today's `data_collection_health.json` shows `stale_count: 0,
delisted_count: 0`. ABVX appears correctly in the veto list with a large negative EES v3
score (−1.24), consistent with its sell-only status. The veto correctly removes it.

### EES scores PIT-correct for backfilled snapshots

**CONFIRMED** — see §4. Backfill reads stored scores, does not recompute. Pre-EES-v3
snapshots absent the field produce zero-veto rows, excluded from gate denominator.

### Price/XBI forward return alignment

**CONFIRMED** — see §4. Anchor uses snap_date price or last-known-before. Forward uses
XBI calendar N trading days forward. No lookahead.

### Independence of 35 observations

**FLAGGED AS CAVEAT** — see §4. Overlapping windows reduce effective sample size.
NW-HAC t-stat in PIT backtest (2.36) is the correct significance measure.

### Veto harm to far-out catalyst names

**PARTIAL CONCERN.** The autopsy showed `catalyst_too_far` has 26.7% true-negative rate
and +22.7% excess return in the HL bucket — the veto's worst false-negative subgroup.
However:
- It represents only 2.8% of historical HL names (15 of 533 observations).
- In the conditional veto simulator across all 76 snapshots, protecting these names adds
  only +2.4% mean excess — the +22.7% was period-specific (most recent ~10 snapshots).
- Today's veto card has exactly 1 such case (TSHA, 260d catalyst). This is within
  expected frequency.

**Assessment:** The `catalyst_too_far` risk is real but modest at current veto frequency.
It supports watching for TSHA performance in the shadow ledger, not blocking review.

---

## 6. Recommendation

```
READY_FOR_OPERATOR_FREEZE_LIFT_REVIEW
```

**Rationale:** All five provenance checks pass. The 20d shadow gate is met (35/20) with
+7.4% cumulative alpha and 81.2% alpha-positive rate. The PIT backtest shows NW t=2.36
with late-regime improvement (LATE +7.1%). The current production-regime veto card fires
predominantly on `market_already_priced` — the theoretically grounded signal, not
coverage-gap noise. No production files were changed.

**What this recommendation does NOT authorize:**
- Activation of the EES v3 veto in production selection.
- Any change to `run_screen.py`, `final_score`, ranker, selector, or sizing.
- Cron or portfolio changes.

**Remaining open questions for operator review:**

1. **Observation independence:** The 35 shadow observations are overlapping. The operator
   should weight the NW-HAC t-stat (2.36) over the raw alpha-positive rate (81.2%) when
   assessing significance.

2. **Staged promotion path:** The analysis supports a staged activation (paper overlay →
   operator review → active veto), not a direct freeze lift to active veto. The proposed
   path is:
   - **Stage 0 (current):** Artifact-only shadow monitor.
   - **Stage 1:** Daily report says "would veto X names" — production ignores it.
   - **Stage 2:** Paper overlay: compare base ranker vs veto-survivor portfolio for N live cycles.
   - **Stage 3:** Operator-approved active veto.

3. **TSHA monitoring:** The one `catalyst_too_far` veto (TSHA, 260d) should be tracked
   as a sentinel for false-negative behavior.

4. **Coverage expansion path:** The conditional veto simulator confirmed that the correct
   long-term upgrade is expanding `priced_move_pct` coverage, not conditioning the veto
   on current evidence. The `no_options_coverage` mode will naturally disappear as
   coverage improves, at which point `raw_veto_core` becomes a de facto evidence-qualified
   veto.

**Do not output LIFT_FREEZE until the operator explicitly approves after reading this memo.**

---

## Appendix: Commit Summary

| Commit | Title | Role in Review |
|--------|-------|---------------|
| `149c8f56` | Shadow research package + promotion simulator | PIT IC baseline: NW t=2.36, LATE +7.1% |
| `6123739c` | Veto autopsy (HL bucket analysis) | True-neg rate 55.6%, LATE 60.5%; dominant mode no_options_coverage |
| `0d47544f` | Conditional veto simulator | RAW_VETO_REMAINS_BEST vs 6 conditional variants |
| `c56b2c2a` | Raw veto shadow card (Day 1) | 8 vetoed; 6x market_already_priced; failure mode distribution clean |
| `22e7312b` | Backfill + gate counting fix | 35/20 MET; gate counting corrected (n_vetoed > 0 filter) |

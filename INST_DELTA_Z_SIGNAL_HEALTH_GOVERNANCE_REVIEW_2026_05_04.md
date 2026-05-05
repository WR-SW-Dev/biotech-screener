# inst_delta_z Signal Health — Governance Review
**Date:** 2026-05-04
**Ruleset:** 2a3e79eb (v1.13.0)
**Author:** Hermes (read-only diagnostic)
**Status:** OPEN — operator disposition required

---

## 1. FACTS (cited)

**ic_health_monitor (artifacts/ic_dashboard/2026-05-04_dashboard.json)**
- Signal: `inst_delta_z`
- health: `ALERT`
- mean_ic: -0.097
- hit_rate: 0.111 (4/36 dates positive)
- n_dates: 36 (2026-02-19 to 2026-04-02)
- latest_ic: +0.030 (2026-04-02, single date)
- dashboard attention: `HIGH`

**Inflection date:** 2026-02-28 (first 5-consecutive-negative IC run onset)

**IC series tail (last 10 dates from dashboard):**
| Date | IC |
|------|------|
| 2026-03-23 | -0.141 |
| 2026-03-24 | -0.155 |
| 2026-03-25 | -0.148 |
| 2026-03-26 | -0.084 |
| 2026-03-27 | -0.097 |
| 2026-03-28 | -0.049 |
| 2026-03-30 | -0.023 |
| 2026-03-31 | -0.019 |
| 2026-04-01 | -0.009 |
| 2026-04-02 | +0.030 |

**calibration_evidence (artifacts/calibration_evidence/2026-05-03_evidence.md)**
- inst_delta_z event-conditioned IC: -0.244 (n=75 postmortems)
- spread: +0.14% (high-ranked vs low-ranked — effectively flat, no monotonic predictive gradient)

**TWO-FRAME CONFIRMATION:** dashboard rolling IC (-0.097) + postmortem event-IC (-0.244) both negative, independent methodologies.

**Comparator probe (artifacts/ic_dashboard/2026-05-04_coinvest_probe.json — generated this session)**
- Probe methodology: Spearman IC on same snapshots, same 20-day forward return window
- Fidelity check: probe reproduces inst_delta_z mean_ic = -0.084 (dashboard: -0.097; delta from lower snapshot coverage n=29 vs n=36)
- `coinvest_score_z` over identical window: mean_ic = +0.097, hit_rate = 0.897 — **HEALTHY**
- IC cross-correlation ρ(inst_delta_z, coinvest_score_z) = -0.33 (n=29)

**Sentinel (agents/sentinel/memory/2026-05-04.md)**
- Ranker health: OK as of 2026-05-04
- Consecutive WARNs: 0 (reset)
- top60_overlap: 96.72%, max_rank_shift: 0.78
- Prior WARNs (2026-04-27 to 2026-04-30) caused by catalyst_7d_count surge, not ranker IC degradation; fully resolved 2026-05-01

**Other signals (same dashboard):**
| Signal | Health | mean_ic | hit_rate |
|--------|--------|---------|----------|
| score_rank_pct | WARN | -0.004 | 0.36 |
| clinical_optionality_pct_dev | HEALTHY | +0.105 | 0.89 |
| inst_delta_z | **ALERT** | -0.097 | 0.11 |

**Ruleset role of inst_delta_z (CLAUDE.md):**
- B6 selector weight: 35% (coinvest 65% + inst_delta 35%)
- Within-top-30 ranker: dominant positive discriminator (NW-t=+3.32 in PIT backtest)
- Bundle validated: t=2.57, 67 monthly periods (Jun 2020 — Apr 2026)

---

## 2. INFERENCE (separated)

**INFERENCE:** coinvest_score_z is healthy (+0.097 IC, 89.7% hit rate) over the identical window where inst_delta_z is anti-predictive (-0.084 IC, 13.8% hit rate). The cross-correlation ρ=-0.33 means their IC time series are mildly anti-correlated — they are not co-degrading. This rules out "the entire 13F/institutional data lane is broken" as the cause. The degradation appears specific to inst_delta_z, not to the coinvest signal or the data feed as a whole.

**INFERENCE:** Inflection date 2026-02-28 coincides with the window when Q4 2025 13F filings (deadline Feb 14, 2026) would have flowed into the data. The inst_delta construct reflects institutional position changes (entries/exits) rather than holdings levels. A cohort of new Q4 13F data landing simultaneously may have introduced a mean-reversion artifact — positions that looked like "new buys" per the delta were actually Q3→Q4 rotations now reversing. This is a hypothesis, not confirmed.

**INFERENCE:** The +0.030 IC reading on 2026-04-02 (the most recent date in the window) is one data point. The IC window does not yet include April-May 2026 production snapshots (those are not forward-returnable until 20 trading days out). It cannot yet be determined whether this is the start of a reversal or noise.

**INFERENCE:** The bundle IC (B6 as a unit: 0.65*coinvest_z + 0.35*inst_delta_z) may be less impaired than the component IC suggests, because coinvest_z is strongly healthy and the component weights give coinvest the larger share. The backtest validated the bundle, not the components in isolation. However, we cannot compute the bundle-level rolling IC without a new script — it is not in the current dashboard.

**INFERENCE:** Ranker instability (3 consecutive WARNs) was catalyst_7d_count-driven, fully resolved. It is NOT evidence of ranker IC degradation independently of this signal-health finding.

---

## 3. OPTIONS

### Option A — Shadow inst_delta_z weight to zero in selector, hold ranker weight
**What:** Remove inst_delta_z from the B6 selector (set weight to 0%, give full 100% to coinvest_z). Keep within-top-30 ranker weighting unchanged. Monitor both for 30 days before deciding on ranker.
**Trade-offs:**
- ✅ Removes anti-predictive signal from selection step (highest-impact use)
- ✅ coinvest_z is proven healthy — not penalized by the bundle reduction
- ❌ Changes production ruleset — requires governance memo promotion, new ruleset ID, v1.14.0 bump
- ❌ Breaks the bundle that was validated as a unit; the backtest validates coinvest+inst_delta together
- ❌ Potentially premature — only 36 IC dates, window doesn't include April-May data
- Reversibility: moderate — requires a new ruleset file + governance sign-off to reverse

### Option B — Shadow reduce inst_delta_z (lower weight, not zero), forward shadow accumulation
**What:** Reduce inst_delta_z selector weight from 35% to ~15-20% via a shadow variant. Run the shadow alongside production for 30-60 days. Only promote if shadow outperforms.
**Trade-offs:**
- ✅ Accumulates evidence before committing; respects the forward shadow framework
- ✅ Does not change production immediately
- ❌ Requires creating a new shadow arm (coinvest_shadow_tracker v2 or new arm)
- ❌ 30-day lag before actionable evidence; degradation continues in production during that window
- Reversibility: high — shadow is not production

### Option C — Watch only, extend IC window, no action until Tuesday data lands
**What:** Take no action. Wait for Monday (05-05) production run to add 5+ new IC dates (2026-04-07 to 2026-05-01). Re-run ic_health_monitor after Tuesday. Assess whether the single +0.030 reading on 2026-04-02 is the start of a trend reversal or noise.
**Trade-offs:**
- ✅ Zero production risk; cheapest option
- ✅ IC window is currently stale — missing ~20 trading days of data
- ✅ Consistent with established 7-consecutive-WARN threshold before escalation
- ❌ If degradation is real and persistent, another 5-10 days of live exposure with an anti-predictive signal
- ❌ Does not explain the mechanism
- Reversibility: N/A — no change made

### Option D — Bundle-level IC computation before deciding
**What:** Compute rolling IC for the full B6 composite score (0.65*coinvest_z + 0.35*inst_delta_z) over the same window before choosing A/B/C. If bundle IC is also negative, escalates urgency. If bundle IC is healthy (coinvest dominance saving it), deescalates urgency.
**Trade-offs:**
- ✅ Directly answers the question "is the bundle broken or just one component?"
- ✅ Small additional script (~30 lines), read-only, no production touch
- ❌ Adds ~1 hour to the decision timeline
- Reversibility: N/A — probe only, produces an artifact

---

## 4. WHAT THIS MEMO DOES NOT ANSWER

- Whether the B6 **bundle** IC (the actual production composite) is degraded over this window (requires Option D computation)
- Whether the +0.030 IC on 2026-04-02 is a genuine reversal or an outlier (requires more forward-return-settled dates)
- The specific mechanism of degradation (13F lag hypothesis is unverified — would require examining the inst_delta_z data source timestamps by cohort date)
- Whether the inst_delta_z **ranker** role is also impaired (current analysis is selector-IC focused; ranker impact requires a separate within-top-30 analysis)
- Any forward-return data after 2026-04-02 (the 20-day window for 04-02 settles 2026-04-30; we have 05-01 data, so this could be computed now for the last few dates)

---

## 5. NEXT STEP

Operator's call. This memo is intentionally quiet about which option to take.

Cheap follow-ups in priority order (all read-only):

1. **Bundle IC probe** (Option D) — ~30 min, read-only, highest diagnostic value. Compute rolling IC for the B6 composite score directly. Script would follow the same pattern as the coinvest probe above.

2. **Wait for Tuesday production run** — free. Monday 05-04 production runs at 16:30 ET. After ic_health_monitor fires at 17:30, re-read the dashboard to see if 5 new dates (04-07 to 04-27) shift the mean_ic materially.

3. **Shadow arm setup** (if Option B chosen) — draft a new coinvest_shadow_tracker arm with inst_delta_z weight reduced. Requires operator approval before wiring into cron.

4. **Ruleset bump spec** (if Option A chosen) — draft a new `v1.14.0_b6_coinvest_only_selector.json` with inst_delta_z weight set to zero. Requires a full governance review promotion cycle per CLAUDE.md.

---

## 6. PROVENANCE

**Artifacts read (no modifications made to any of these):**
- `artifacts/ic_dashboard/2026-05-04_dashboard.json`
- `artifacts/calibration_evidence/2026-05-03_evidence.md`
- `agents/sentinel/memory/2026-05-04.md`
- `agents/sentinel/memory/2026-05-01.md`
- `data/snapshots/2026-MM-DD/rankings.csv` (29 dates, read for probe)
- `production_data/price_history.csv` (read for probe forward returns)

**Artifacts created this session (new, read-only diagnostic):**
- `artifacts/ic_dashboard/2026-05-04_coinvest_probe.json` (comparator probe output)
- `INST_DELTA_Z_SIGNAL_HEALTH_GOVERNANCE_REVIEW_2026_05_04.md` (this file)

**No production code, rulesets, snapshots, or scoring files were modified.**
**No file outside this memo and the probe artifact was created or modified by this review.**

---

_Next artifact: INST_DELTA_Z_GOVERNANCE_LOG_TEMPLATE_2026_05_04.md (disposition record — to be filed once operator selects an option)_

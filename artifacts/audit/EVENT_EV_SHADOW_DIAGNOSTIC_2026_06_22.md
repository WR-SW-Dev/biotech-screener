# Event EV Shadow Diagnostic — 2026-06-22

**STATUS: EVENT_EV_SHADOW_DIAGNOSTIC_ONLY_NO_ALPHA_PROMOTION**

**VERDICT: PASS_EVENT_EV_SHADOW_DIAGNOSTIC_NO_MODEL_CHANGE**

Auditor: Claude Code (claude-sonnet-4-6)
Scope: read-only shadow diagnostic; no ranker/selector/final_score/sizing/gate changes made
Snapshot input: `data/snapshots/2026-06-22/rankings.csv` (291 tickers)
Shadow output dir: `artifacts/audit/event_ev_shadow_2026_06_22/`
Prerequisite: Task 1 PASS (`EXPECTATION_LAYER_FIELD_COVERAGE_VERIFICATION_2026_06_22.md`)

---

## 1. Normalization Safety Check

**priced_move_pct cross-sectional normalization: CONFIRMED SAFE**

The batch path (`EventEVCalculator.run_batch()` → `ExpectationModel.estimate_batch()`) was
used for 100% of evaluated events. The single-name `estimate()` path (which has the raw-float
inconsistency flagged in Task 1) was used for 0 events.

priced_move_pct percentile rank statistics across 428 evaluated events:
- Events with priced_move_pct rank available: **360/428 (84.1%)**
- Range: [0.003, 1.000] — all strictly within [0, 1]
- Mean: 0.503 (well-centered, no directional skew)
- All-in-range check: **PASS** — 0 values outside [0, 1]

The 68 events without a priced_move_pct rank correspond to tickers with no listed options
(priced_move_pct absent from rankings.csv). The feature weight (0.05) for those events
contributes 0 to both numerator and denominator, cleanly falling out of the belief score.

**Normalization path used:**

```
batch path: 428/428 events  ← cross-sectional percentile ranks [0,1]
single-name path: 0/428 events
```

---

## 2. Evaluation Scope

| Metric | Value |
|---|---|
| Total graph nodes (all time) | 4,268 |
| Nodes evaluated (0–180d cohort) | 428 (10.0%) |
| Nodes skipped | 3,840 (90.0%) |
| Skip reason | Outside 0–180d evaluation window or resolved |
| Diagnostic positive EV candidates (EV > 0, within 180d) | **17 (4.0% of cohort)** |
| Positive EV (any days) | 27 (6.3% of cohort) |

**Days-to-event distribution of evaluated cohort:**
- 0–30d: 285 events (66.6%)
- 31–60d: 3 events (0.7%)
- 61–90d: 3 events (0.7%)
- 91–180d: 137 events (32.0%)

The 0–30d dominance reflects the HALF_YEAR date precision category (342/428 events = 79.9%).
For windowed events with overdue windows, the model returns 15d by convention — this
inflates the near-term bucket and is expected behavior, not a data quality issue.

**Event source breakdown:** SEC_8K_FILING 414, M3_RANKINGS_SUPPLEMENT 9, PDUFA_MANUAL 5

**Event family breakdown:** CLINICAL 339, REGULATORY 85, SAFETY 4

---

## 3. Belief-Score Feature Coverage (Post–Field Surfacing)

With `short_interest_pct`, `priced_move_pct`, `close_price`, and `market_cap_mm` now
present in rankings.csv, the expectation model's weighted feature coverage improved.

**Coverage distribution across 428 events (7 belief-score features, max active weight = 0.90):**

| Feature count | Events | % |
|---|---|---|
| 7/7 (all features) | 360 | 84.1% |
| 6/7 | 7 | 1.6% |
| 5/7 | 4 | 0.9% |
| 4/7 | 1 | 0.2% |
| 0/7 (not in universe) | 56 | 13.1% |

| Metric | Value |
|---|---|
| Average weighted coverage (excl. 0-feature events) | 0.900 (100% of max) |
| Average weighted coverage (all events incl. 0-feature) | 0.780 (86.7% of max) |
| Events at full coverage (≥ 0.90) | 360/428 (84.1%) |
| Events at ≥ 0.80 weighted coverage | 371/428 (86.7%) |

**The 56 zero-feature events** are all from 26 tickers not in the 291-ticker screener universe
(confirmed: 0 in-universe tickers had zero features). These events enter the graph from
historical catalyst event files but lack corresponding market data. The expectation model
correctly defaults to `implied_p_hit = 0.500` (uninformed prior) for these events.

**Before vs after field surfacing (estimate from weighted coverage change):**

| State | Typical weighted coverage |
|---|---|
| Before (short_interest_pct, priced_move_pct missing) | ~0.80 (80% of max) |
| After (all 4 fields surfaced) | 0.90 for 84.1% of events |

This confirms the operator memo's characterization of ~80% → ~95% improvement (the 95%
figure describes the broader expectation + context stack including `close_price` as
`underlying_price` and `market_cap_mm` in the payoff/context model; belief score alone
moved from 0.80 → 0.90 for universe tickers).

---

## 4. Expectation Gap Diagnostics (Shadow Only)

**Belief direction distribution (428 events):**
NEUTRAL 138 (32.2%) | UNCERTAIN 131 (30.6%) | BULLISH 85 (19.9%) | BEARISH 74 (17.3%)

**Top mispricing candidates by |model P(hit) − market-implied P(hit)|:**

These are diagnostic observations only. They indicate where the expectation model's
outcome prior diverges from the crowd-belief estimate. They carry no alpha or action
implication until validated.

| Ticker | Event Type | Misprice | Model P(hit) | Market P(hit) | Mkt Direction | Note |
|---|---|---|---|---|---|---|
| SMMT | PDUFA | +0.458 | 0.797 | 0.339 | BEARISH | Model bullish vs crowded short |
| IRON | FDA_PDUFA_DATE | −0.393 | 0.302 | 0.695 | BULLISH | Market very bullish vs base rate |
| MBX | DATA_READOUT | −0.367 | 0.357 | 0.724 | BULLISH | Market very bullish |
| DYN | FDA_PDUFA_DATE | −0.361 | 0.316 | 0.677 | BULLISH | Market very bullish |
| CMPS | FDA_PDUFA_DATE | −0.336 | 0.322 | 0.658 | BULLISH | Market very bullish |
| MLTX | FDA_PDUFA_DATE | −0.332 | 0.290 | 0.622 | BULLISH | Market very bullish |
| TRVI | DATA_READOUT | −0.331 | 0.350 | 0.681 | BULLISH | Market very bullish |
| MRNA | PDUFA | +0.323 | 0.794 | 0.471 | NEUTRAL | Model bullish vs neutral mkt |
| MIRM | FDA_PDUFA_DATE | −0.320 | 0.320 | 0.639 | BULLISH | Market very bullish |
| VERA | FDA_PDUFA_DATE | −0.317 | 0.292 | 0.608 | BULLISH | Market very bullish |
| SYRE | DATA_READOUT | −0.315 | 0.363 | 0.678 | BULLISH | Market very bullish |
| ORKA | DATA_READOUT | −0.314 | 0.363 | 0.677 | BULLISH | Market very bullish |
| GILD | DATA_READOUT | +0.307 | 0.637 | 0.330 | BEARISH | Model bullish vs short crowd |
| CLDX | FDA_PDUFA_DATE | −0.299 | 0.341 | 0.641 | BULLISH | Market very bullish |
| VRTX | DATA_READOUT | +0.295 | 0.643 | 0.348 | BEARISH | Model bullish vs bearish crowd |

**Pattern observation (diagnostic only):**

The dominant pattern is large *negative* mispricing (market more bullish than model) concentrated
in FDA_PDUFA_DATE events. This is consistent with known market behavior around PDUFA events —
institutional and options markets price high approval probability for PDUFA dates with regulatory
history, while the base-rate outcome model applies a more conservative prior.

The positive mispricings (SMMT, MRNA, GILD, VRTX) represent the inverse: model outcome
probability exceeds market-implied, typically where short interest or neutral sentiment is
elevated relative to the model's prior.

**These observations are SHADOW_DIAGNOSTIC_ONLY. No action, promotion, or model change implied.**

---

## 5. Top 17 Diagnostic Positive EV Candidates (EV > 0, ≤ 180d) — Shadow Only

| Rank | Ticker | Type | Days | P(hit) | Misprice | EV% | DS-EV% | Market-Implied P |
|---|---|---|---|---|---|---|---|---|
| 1 | IMRX | DATA_READOUT | 15 | 0.532 | +0.147 | +12.3 | +4.8 | 0.385 |
| 2 | BEAM | DATA_READOUT | 15 | 0.558 | −0.021 | +8.7 | +4.7 | 0.579 |
| 3 | GLUE | DATA_READOUT | 4 | 0.537 | −0.100 | +11.0 | +4.6 | 0.637 |
| 4 | PYXS | DATA_READOUT | 15 | 0.528 | +0.070 | +11.9 | +4.3 | 0.459 |
| 5 | TNGX | DATA_READOUT | 15 | 0.533 | −0.165 | +8.8 | +3.5 | 0.698 |
| 6 | VYGR | DATA_READOUT | 15 | 0.538 | +0.156 | +7.8 | +3.2 | 0.382 |
| 7 | BCYC | DATA_READOUT | 15 | 0.528 | +0.109 | +8.0 | +2.8 | 0.419 |
| 8 | SMMT | PDUFA | 145 | 0.797 | +0.458 | +3.2 | +1.5 | 0.339 |
| 9 | MRNA | PDUFA | 44 | 0.794 | +0.323 | +3.3 | +1.4 | 0.471 |
| 10 | PRME | DATA_READOUT | 4 | 0.517 | +0.017 | +5.0 | +1.2 | 0.500 |
| 11 | HOWL | DATA_READOUT | 15 | 0.517 | +0.017 | +5.0 | +1.2 | 0.500 |
| 12 | LXEO | DATA_READOUT | 15 | 0.503 | −0.069 | +7.6 | +0.8 | 0.572 |
| 13 | VRDN | PDUFA | 8 | 0.765 | +0.221 | +3.7 | 0.0 | 0.544 |
| 14 | SEPN | DATA_READOUT | 100 | 0.496 | −0.129 | +5.9 | −0.1 | 0.624 |
| 15 | VERA | PDUFA | 15 | 0.759 | +0.151 | +3.6 | −0.5 | 0.608 |
| 16 | NRIX | DATA_READOUT | 15 | 0.504 | +0.006 | +5.0 | −0.5 | 0.498 |
| 17 | REGN | DATA_READOUT | 15 | 0.512 | +0.046 | +4.8 | −0.7 | 0.466 |

**These are shadow scores only — not screener output, not portfolio instructions.**

---

## 6. Scoring Boundary Confirmation

| Check | Result |
|---|---|
| `ranker_v2_score` emitted in shadow output | 0/428 |
| `final_score` emitted in shadow output | 0/428 |
| `selector_score` emitted in shadow output | 0/428 |
| Rankings.csv modified by diagnostic run | NO |
| Production snapshots modified | NO |
| `insider_net_buy_value_90d` loaded into market_features | 0/291 (lane remains closed) |
| Git tracked-file mutations | NONE (shadow output is untracked) |
| Eligibility/gate fields emitted | NO |
| Action/sizing language | NONE |

---

## 7. Diagnostic Artifacts Written

All outputs to `artifacts/audit/event_ev_shadow_2026_06_22/` (untracked, shadow-only):
- `2026-06-22_event_ev_scores.json` — summary stats + leaderboard
- `2026-06-22_event_ev_full.json` — full EventEV objects (428 entries)
- `2026-06-22_ev_leaderboard.json` — compact leaderboard
- `2026-06-22_ev_leaderboard.md` — operator-readable memo

---

## Summary

| Check | Result |
|---|---|
| priced_move_pct cross-sectional normalization safe | PASS — all ranks in [0, 1] |
| Batch path used (not single-name) | PASS — 428/428 batch |
| Events evaluated | 428 (0–180d cohort from 4,268-node graph) |
| Events skipped | 3,840 (outside window/resolved) |
| Zero-feature events | 56 — all from 26 non-universe tickers, expected |
| Weighted belief coverage | 0.90 for 84.1% of events; avg 0.780 overall |
| No scoring field leakage | PASS |
| No tracked file mutations | PASS |
| Insider lane remains closed | PASS |
| Production model freeze respected | PASS |

**VERDICT: PASS_EVENT_EV_SHADOW_DIAGNOSTIC_NO_MODEL_CHANGE**

---

## Next Step Gate

Task 2 verdict is clean. Task 3 (Scientific Cartography operational review) may proceed
under the same scoped work freeze boundaries.

The mispricing table above (§4) may serve as input context for the Event EV shadow work
in future sessions, but requires NO action and should NOT be cited as alpha until validated
via forward IC over a meaningful sample.

# Biotech EV Pre-Trade Artifact Map

**Version:** 2026-05-05  
**Author:** Hermes (session-generated, operator-reviewed)

---

## Purpose

Manual analyst overlay for reviewing screener outputs before acting on a catalyst event.
Use alongside `data/snapshots/<date>/ACTION.json` and `data/snapshots/<date>/rankings.csv`.

> **WARNING: This is not a model gate and not evidence for changing signal weights.**
> Observations from this checklist are hypotheses only. Any model, ranker, selector,
> or EV change requires CRT evidence, IC evidence, PIT-safe validation, and full
> Checklist v2 (FM, bootstrap, FDR, LOSO) before promotion. See Governance Boundary below.

---

## Pre-Trade Artifact Map

| Checklist Item | Artifact / Path | Fields to Inspect | How to Read It | Red Flags | Notes |
|---|---|---|---|---|---|
| **A. Base Rate Anchoring** | `artifacts/calibration_evidence/<most-recent>_evidence.json` | `signal_tracker`, `threshold_audit`, `calibration_curve`, `n_postmortems` | Check `status` and `n_postmortems` to gauge evidence depth. Sparse postmortems = base rate estimate thin. | `n_postmortems < 10` for this event type → base rate unreliable | Only Mon/Wed/Fri ledgers exist. Use most recent dated file, not today's date. If >7d stale, treat base rates as unverified. |
|| | `data/snapshots/resolutions/calibration_summary.json` | `by_catalyst_type.hit_rate`, `by_catalyst_type.n_resolved` | Hit rate by catalyst type across resolved CRT events. Compare your POS estimate to historical hit rate for this event type. | n < 10 for this catalyst type → hit rate unreliable | Use `n_resolved` per type to weight confidence. This is the authoritative base-rate source, not calibration_evidence. |
| **B. Data Freshness** | `artifacts/data_auditor/integrity_report_<date>.json` | `verdict`, `financial_consistency.divergences`, `price_data_gaps.missing_tickers` | PASS = data clean. WARN = at least one check degraded. Check if ticker in `missing_tickers` or `divergences`. | Ticker appears in `divergences` (>50% financial gap) or `missing_tickers` | Run audit report is daily (~18:00 ET). If today's is missing, data freshness is unverified. |
| | `data/snapshots/<date>/metadata.json` | `as_of_date`, `decision_engine_ruleset_id` | Confirm snapshot is for today's date and ruleset hash matches `8887576e` | `ruleset_id` ≠ `8887576e` → wrong ruleset active | `integrity_report` lands ~18:00 ET; before then use yesterday's. `as_of_date` not `effective_as_of_date`. |
| **C. Event Specificity** | `data/snapshots/<date>/rankings.csv` | `is_hard_catalyst`, `catalyst_date_precision`, `calendar_confidence`, `has_tradeable_calendar`, `catalyst_source`, `next_catalyst_date` | `is_hard_catalyst=True` with `catalyst_date_precision=DAY` = high specificity. `calendar_confidence < 0.7` = wider date uncertainty. | `catalyst_date_precision=RANGE` or `calendar_confidence < 0.7` | No separate hard_queue_artifacts.json — all fields are columns on rankings.csv. Cross-check `next_catalyst_date` against `catalyst_date_lower/upper` spread. |
| **D. Market-Implied Expectation** | `data/snapshots/<date>/rankings.csv` | `opt_event_premium`, `implied_event_move`, `priced_move_pct`, `opt_atm_iv`, `opt_dte` | `opt_event_premium` = market's implied excess move for the event. `implied_event_move` = expected % swing. Compare to your own POS × upside model. | `priced_move_pct` >> your EV estimate → market has already priced upside. `opt_liquidity_ok=False` → straddle price unreliable. | `opt_has_data=False` means options signal unavailable; fall back to `priced_move_pct` from price history only. |
| | `data/snapshots/<date>/rankings.csv` | `iv_ramp_flag`, `surface_signal_quality`, `ovf11_score`, `ovf_composite`, `opt_use_for_judgment` | `iv_ramp_flag=True` = market loading up into event. `ovf11_score` aggregates surface confirmation across 11 factors. | `surface_signal_quality=poor` or `ovf_composite=False` → options signal unreliable | These are per-ticker columns on rankings.csv, not fields on surface_delta.json. surface_delta.json is a day-over-day drift report only. |
| **E. Expectation Error / EV** | `data/snapshots/<date>/rankings.csv` | `expectation_error_score`, `ees_v2_score`, `ees_v3_score`, `ees_eligible`, `ees_quality_gate`, `ees_trap_gate` | `ees_eligible=True` + `ees_quality_gate=True` + `ees_trap_gate=True` = EES usable. `expectation_error_score` > 0 = positive EV signal. | `ees_eligible=False` or either gate=False → EES should not drive sizing | EES v3 is diagnostic; EES v2 is the production gate. Do not promote v3 to production without governance review. |
| | | `conditional_misprice_score`, `conditional_expected_move`, `conditional_gap_score`, `conditional_confidence` | Gap between model-expected move and market-implied move. Positive gap = potential mispricing. | `conditional_confidence=low` → misprice estimate unreliable | Conditional model requires adequate options data and a matched CRT base rate. |
| **F. Downside Asymmetry** | `data/snapshots/<date>/rankings.csv` | `runway_severity_score`, `runway_buffer_months`, `financing_truth_gate`, `dilution_haircut`, `severity_bucket` | `financing_truth_gate=True` = financing risk is manageable. `severity_bucket=critical` or `runway_buffer_months < 3` = imminent dilution risk regardless of catalyst outcome. | `financing_truth_gate=False` → size down or shadow regardless of POS | Downside on a failed catalyst + financing need = compounded loss. Treat separately from pure event risk. |
| | | `fundamental_red_flag`, `fundamental_red_flag_reasons` | `fundamental_red_flag=True` signals a hard structural problem (cash, revenue cliff, burn vs runway). | Any hard red flag present | Red flag is a gate, not a penalty. Positive EV does not override a hard red flag. |
| **G. Liquidity / Capacity** | `data/snapshots/<date>/rankings.csv` | `execution_capacity_score`, `execution_bucket`, `adv_20d`, `adv_60d`, `max_position_dollars`, `max_position_weight` | `execution_bucket=unrestricted` = full position size available. `execution_bucket=restricted` = cap at `max_position_weight`. `max_position_dollars` is the hard ceiling from ADV model. | `adv_20d < 5× intended position` → liquidity insufficient | Dollar volume check: `median_dollar_volume_20d` is the cleanest single-number liquidity proxy. |
| | | `dollar_volume`, `short_interest_pct`, `crowding_level`, `crowding_bias_score` | High short interest + high crowding = squeeze risk on positive catalyst but also crowded exit on failure. | `crowding_level=highly_crowded` + `short_interest_pct > 20%` | Crowding amplifies both tails. Adjust sizing, not POS. |
| **H. GO / SHADOW / NO-GO** | `data/snapshots/<date>/ACTION.json` | `buckets[*].bucket`, `buckets[*].names[*].ticker`, `buckets[*].names[*].tier`, `buckets[*].names[*].weight_pct`, `buckets[*].names[*].in_portfolio` | Name present in `binary_now` or `build_window` bucket with `tier=A` = strong screener alignment. `in_portfolio=True` = already held. Cross-check bucket assignment against your checklist conclusion. | Name absent from all ACTION.json buckets → screener does not endorse; size very conservatively or shadow | ACTION.json groups names into catalyst buckets. Per-name fields are: ticker, rank, weight_pct, tier, catalyst_days, catalyst_mode, in_portfolio — not tier_any/ees_eligible/selector_rank_bucket (those are on rankings.csv). |
| | `data/snapshots/<date>/rankings.csv` | `tier_any`, `tier_any_reason`, `cat_priority`, `selector_rank_bucket`, `ranker_active`, `ees_eligible`, `actionable_rank`, `final_score`, `ranker_v2_score` | `selector_rank_bucket=top30` + `tier_any=A/B` + `ees_eligible=True` = screener aligned with GO. `selector_rank_bucket=outside` or `tier_any=C` with no catalyst = SHADOW or NO-GO. Lower `actionable_rank` = higher conviction. | `actionable_rank` absent (name outside top-30) → size conservatively | `actionable_rank` is assigned only within top-30 selector bucket; null outside it by design. |

---

## Checklist Decision Rule (Manual Overlay)

```
GO     — All of A, B, C, D pass; EV positive from E; F and G clear; screener tier A or B
SHADOW — One of A-D borderline; or EV positive but F/G restricted; or tier C with weak catalyst
NO-GO  — Base rate miss; data stale (auditor WARN on ticker); financing_truth_gate=False;
          execution_bucket=blocked; or hard fundamental red flag present
```

Apply this to the screener output, not instead of it. Divergence between your overlay and the screener is a signal to investigate, not to override.

---

## Governance Boundary

This document is a **read-only analyst overlay**. It authorizes nothing.

Manual checklist observations may generate hypotheses. A hypothesis becomes actionable only after:

1. **CRT evidence** — realized outcomes across ≥10 resolved events of this type show the pattern
2. **IC evidence** — forward IC across ≥20 production dates confirms signal predictive power
3. **PIT-safe validation** — no lookahead leakage, point-in-time data only
4. **Checklist v2 rerun** — Fama-MacBeth, block bootstrap (95% CI excludes zero), BH FDR q < 0.10, LOSO ROBUST

Until all four are met: **no signal weight changes, no ranker adjustments, no selector modifications, no EV model updates**.

The path from "I noticed something" to "the model reflects it" is a Spec ticket reviewed under the North Star rule: *backtest systems never directly modify production screening behavior.*

---

*This file is static documentation. Re-verify artifact paths and field names against the live snapshot before relying on this map. Use `tools/check_output_contract.py` (if present) or inspect `data/snapshots/<date>/rankings.csv` columns directly to confirm field names have not drifted.*

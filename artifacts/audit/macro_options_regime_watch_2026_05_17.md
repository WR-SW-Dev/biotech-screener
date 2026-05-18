# Macro/Options Regime Watch Note — 2026-05-17

**Source:** Yahoo Finance / Bloomberg — "Tech Bubble Fear Lures Investors" (Christian Dass, May 17, 2026)
**Classification:** Market-regime signal (monitoring only — no scoring or weight changes)
**Filed by:** Operator (D. Schulz) via Town PA
**Related specs:** Spec 105 (Expectation Layer Coverage), Spec 077 (Event EV Binder), Spec 097/098 (Prospective Monitoring)

---

## Context

Investors are increasingly paying for crash protection and convexity through
exotic options as the tech rally shows bubble-like characteristics.
Bloomberg-syndicated framing describes "two-way risk" — the market can still
squeeze higher, but downside hedging demand is rising materially. Michael
Burry's concurrent warning that "put options are expensive" confirms elevated
hedging demand. SOX intraday drop of 6.8% (May 12) illustrates the volatility
regime shift.

## Biotech Model Implications (per operator analysis)

### 1. Macro risk appetite is getting less stable

Small/mid-cap biotech is long-duration, financing-sensitive, and highly exposed
to volatility shocks. If tech volatility bleeds into broader risk assets,
biotech may see indiscriminate de-risking even when company-level catalysts are
unchanged.

### 2. Options-implied expectations become more valuable

This supports the Spec 105 direction of wiring expectation fields into
production `rankings.csv`. In a regime where options are repricing two-way risk,
`priced_move_pct` / straddle-implied move becomes more important, not less.

### 3. Do not convert this into a broad bearish overlay

The article is a caution flag, not a liquidation signal. Bubble-like markets
can keep melting up. The model should not punish all biotech exposure simply
because tech hedging demand is rising.

### 4. Practical implication — monitoring, not scoring

> "Macro/options regime watch: rising vol-of-vol, widening index straddle
> pricing, and stronger crash-hedge demand may reduce confidence in
> market-implied expectation signals and increase financing-risk sensitivity
> for low-runway names."

## Expectation Field Verification (Spec 105 — confirmed operational)

Production `rankings.csv` expectation fields verified as flowing and meeting
coverage thresholds per Spec 105 closure memo (2026-05-14):

| Field | Coverage (May 14) | Required | Status |
|---|---|---|---|
| `short_interest_pct` | 98.3% | >= 90% | PASS |
| `close_price` | 100.0% | >= 99% | PASS |
| `market_cap_mm` | 100.0% | >= 95% | PASS |
| `priced_move_pct` | 83.6% | >= 80% | PASS |

All four fields confirmed consumed by `ExpectationErrorModel` at inference
(commit `0ddbb509`, Spec 105 closure). Pipeline hard-fails at Step 5 (Gates)
if any field drops below threshold via `FEATURE_COVERAGE_REQUIREMENTS` in
`tools/production_qa_check.py`.

## Operator Decision

No selector/ranker weight changes from this article alone. Expectation fields
are verified operational in production `rankings.csv`. This regime note is
filed to the Event EV / expectation-model audit trail for future reference.

If vol-of-vol persists or index straddle pricing widens further, revisit
whether `priced_move_pct` confidence scaling or financing-risk sensitivity
adjustments are warranted for low-runway names.

## Next Steps

- Verify expectation field coverage in next weekday production snapshot (Monday May 18 or next available)
- Monitor XBI/IBB implied volatility levels for biotech-specific contagion from tech vol
- If macro regime deteriorates further, consider Spec 097/098 prospective monitoring addendum for regime-conditional confidence scaling on `priced_move_pct`
- No changes to catalyst-resolution, selector, or ranker architecture from this signal alone

---

*Filed: Sunday, May 17, 2026. Operator: D. Schulz, CFA, CAIA — Director of Investments, Wake Robin.*

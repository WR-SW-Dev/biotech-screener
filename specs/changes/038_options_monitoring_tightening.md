# Change Spec: Options Monitoring Tightening

**Status**: PROPOSED
**Author**: dschulz
**Date**: 2026-03-30
**Ruleset impact**: NO (monitoring only, no scoring changes)
**Type**: Operator workflow / alert quality

---

## Objective

Optimize options monitoring by making it narrower, more structured, and
more verdict-driven — not by making it broader.

## Principles

1. **Watchlist-scoped** — mirror the Grok watch pattern: shadow holdings,
   review queue, trade plan, near-term catalysts, max ~40 names
2. **Typed anomaly output** — every alert emits structured fields, not free text
3. **Multi-check fusion** — escalate when 2+ lenses agree, not on single alerts
4. **Cheap routing** — Haiku for routine monitoring, Sonnet for edge cases
5. **Per-family thresholds** — catalyst-centric aggressive, skew/surface stricter
6. **Verdict-first delivery** — compact summary, not transcript

## Typed Anomaly Schema

Each options alert must emit:

```json
{
  "anomaly_code": "IV_RAMP_PRE_CATALYST",
  "severity": "HIGH",
  "surface_tenor": "30d",
  "direction": "bullish",
  "confidence": 0.85,
  "near_catalyst": true,
  "requires_operator_review": true,
  "ticker": "PVLA",
  "catalyst_days": 3
}
```

## Multi-Check Fusion

Treat options monitoring as a 4-lens agreement problem:

| Lens | Source | Timing |
|------|--------|--------|
| Pre-open watch | options_watch --pre-open | Before market open |
| Post-packet watch | options_watch (default) | After daily production |
| Surface delta | surface_delta_monitor | After production |
| Price action | price_action_watch | After production |

Escalation rules:
- 2+ lenses agree → HIGH
- 1 high-priority on near-catalyst name → HIGH
- 1 medium-priority alone → MEDIUM (daily digest only)
- New/ongoing/resolved state transitions, not repeated alerts

## Per-Family Threshold Calibration

| Anomaly Family | Current | Proposed |
|----------------|---------|----------|
| Catalyst-centric (IV ramp near event) | Aggressive | Keep aggressive |
| Skew extreme | Global z-score | Stricter: require persistence (2+ days) |
| Surface move | Single threshold | Require confirmation from price action |
| Divergence (stock/IV mismatch) | Single check | Require 2-day persistence |

## Delivery Contract

Same pattern as Spec 037 cron briefs:
- One-line verdict
- 2-4 typed support fields
- Dashboard deep link
- Dedup window (4h for HIGH, 24h for MEDIUM)
- State transitions: new / ongoing / resolved

## Implementation Order

1. Typed anomaly schema for options_watch output
2. Fused verdict across the 4 lenses
3. Per-family threshold calibration
4. Haiku routing for routine runs
5. Dashboard grouping and delivery

## Non-Goals

- No new data sources
- No change to scoring or rankings
- No options signal promotion (that goes through signal evidence)
- No universe-wide monitoring (watchlist-scoped only)

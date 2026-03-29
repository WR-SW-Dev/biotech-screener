# Spec 034: Catalyst History Expansion

**Status:** IN PROGRESS — Phase A (infrastructure)
**Date:** 2026-03-29
**Lane:** New signal-source + PIT history infrastructure
**Type:** Historical event ledger + research features
**Priority:** Next highest-ROI signal-source lane after survivorship

## Objective

Build a PIT-safe catalyst history ledger that records all material catalyst
disclosures and updates over time, not just the nearest current catalyst.

## Phases

- **Phase A**: Build canonical ledger + rollup from existing caches
- **Phase B**: Historical archive reconstruction
- **Phase C**: Coverage/quality diagnostics
- **Phase D**: Research evidence (backtest)

## Key outputs

- `data/catalyst_history/catalyst_history_events.jsonl` (event ledger)
- `data/catalyst_history/catalyst_history_rollup.json` (ticker rollup)

## Event sources (v1)

- CTgov calendar readouts / milestones + trial_cd / trial_active backfills
- FDA calendar / ADCOM events
- Federal Register FDA notices (approvals, CRLs, RTFs, warning letters)
- SEC filings (8-K, 10-Q, 10-K, 6-K)

## Files

- scripts/research/build_catalyst_history_events.py
- scripts/research/build_catalyst_history_rollup.py
- tests/test_build_catalyst_history_events.py
- tests/test_catalyst_history_pit.py

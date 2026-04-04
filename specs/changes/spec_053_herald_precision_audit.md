# Change Spec 053: Herald Precision Audit

**Status**: COMPLETE
**Author**: Claude / arrenchulz
**Date**: 2026-04-04
**Ruleset impact**: NO (diagnostic + defense-in-depth, not signal/ranking change)

---

## Objective

Systematic quality audit of the Herald press release classification pipeline and Catalyst History event ledger. Identifies date-confidence errors, misclassifications, ticker contamination, staleness, and confidence inconsistency. Fixes three classifier bugs and adds three data-quality enrichments to the catalyst history builder.

## Context

Herald (Spec 044) classifies company press releases into typed events that feed the Catalyst Resolution Tracker (CRT, Spec 042). The Catalyst History builder aggregates SEC 8-K, PDUFA, ADCOM, and CTGov events into a unified ledger. Both pipelines have systematic quality issues:

1. **Noise leakage**: GlobeNewswire keyword search pulls unrelated market research articles (PHVS "Black Masterbatches" classified as NDA_BLA_FILING)
2. **Ticker collision**: `_is_ticker_collision()` exists but is ineffective (0 records flagged). 88.6% of tickers rely on GlobeNewswire keyword search.
3. **Safety negation**: "Lifts clinical hold" classified as safety/miss instead of positive regulatory event
4. **Forward dates unlabeled**: 31.3% of catalyst history events have event_date > pit_available_at (forward-looking guidance mixed with actual events)
5. **Confidence inconsistency**: SEC uses categorical (HIGH/MED/LOW), CTGov uses numeric (0.3-0.95)
6. **Ticker recycling**: ORKA has 4 events from a pre-2024 company that previously used the same ticker

## Deliverables

| # | File | Type |
|---|------|------|
| 1 | `scripts/research/herald_precision_audit.py` | **Main audit script** |
| 2 | `tests/test_herald_precision_audit.py` | Tests |
| 3 | `tools/classify_press_releases.py` | Fix 3 bugs |
| 4 | `scripts/research/build_catalyst_history_events.py` | Add 3 enrichments |
| 5 | `artifacts/herald_audit/{date}_audit.json` | Output artifact |

## Design

### Audit Script (primary deliverable)

Six audit modules producing a unified report:

**A. Date-confidence**: placeholder dates, forward dates, staleness
**B. Ticker contamination**: pre-IPO events via ipo_dates.json
**C. Confidence consistency**: mixed categorical/numeric detection
**D. Herald classification**: noise leakage, negation misclass, severity/confidence mismatch
**E. April cluster spotlight**: ORKA, ARTV, CLYM, PHVS, ABUS
**F. Summary scorecard**: counts, severity rating

### Classifier Fixes (defense-in-depth)

**Fix A**: Expand `_is_noise()` with 15+ new market research / analyst patterns
**Fix B**: Add safety negation context (hold lifted/removed/resolved)
**Fix C**: Strengthen `_is_ticker_collision()` — invert brand-name heuristic to require biotech indicators

### Catalyst History Enrichments

**Fix A**: `date_type` field — "actual" / "guidance" / "placeholder"
**Fix B**: Confidence normalization — consistent 0-1 float scale, preserve raw in `confidence_raw`
**Fix C**: IPO-date ticker recycling flag — flag but don't filter

## Invariants

1. **Read-only audit**: audit script does not modify any production data
2. **Fail-open**: missing IPO date or classified data → WARN, not error
3. **Deterministic**: same inputs → same audit output
4. **No scoring impact**: classifier fixes are noise suppression only, not signal changes
5. **Backward compatible**: `confidence_raw` preserves original value; `ticker_recycling_flag` is additive

## Validation Plan

### Tests
- [x] `test_placeholder_date_detection` — quarter-start + guidance flagged, mid-month not
- [x] `test_forward_date_detection` — event_date > pit flagged
- [x] `test_ticker_contamination` — pre-IPO flagged, post-IPO not, missing IPO warns
- [x] `test_confidence_normalization` — categorical mapped, numeric passthrough
- [x] `test_staleness_detection` — past unresolved flagged
- [x] `test_noise_leakage` — market research headlines detected
- [x] `test_negation_misclass` — "lifts clinical hold" detected

### Integration
- [x] Audit script produces valid artifact (2026-04-04_audit.json)
- [x] ORKA contamination: IPO date in ipo_dates.json is from old company (2020), needs manual correction
- [x] PHVS noise pattern caught (41 noise leakage findings total)
- [x] Existing tests pass (67/67, no regression)
- [x] Pre-commit hooks pass

## Non-Goals

- Not changing DEM scoring or production rankings
- Not changing CRT resolution logic
- Not replacing Grok classification (just fixing local keyword fallback)
- Not building a real-time monitoring dashboard (that's Phase 2 dashboard pass)

---

## Implementation Log

- **2026-04-04**: Audit script `herald_precision_audit.py` — 6 modules, 450 LOC
- **2026-04-04**: 32 tests in `test_herald_precision_audit.py`, all passing
- **2026-04-04**: Classifier fixes: expanded noise (15 patterns), safety negation, collision heuristic inverted
- **2026-04-04**: Catalyst history: date_type, confidence normalization, ticker recycling flag (schema v2)
- **2026-04-04**: First audit run: 1066 placeholders, 1331 forward dates, 62 ticker recycling, 41 noise leakage, 1 negation misclass
- **2026-04-04**: ORKA note: ipo_dates.json has old company's first_price_date (2020), needs manual update to new ORKA IPO (~2024)

---

*Template version: 1.0.0 — see specs/SYSTEM_SPEC.md for system invariants*

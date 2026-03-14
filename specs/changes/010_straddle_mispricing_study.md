# Spec 10: Straddle Mispricing Study

**Status**: SESSION 1 COMPLETE — table built, modules ready, awaiting more outcome data
**Schema**: `event_move_table.v1`

## What Exists

- `common/event_move_lookup.py` — lookup table builder + fallback hierarchy
- `common/straddle_mispricing.py` — cheap_vol_score computation with confidence gating
- `scripts/research/build_event_move_table.py` — table builder from enriched outcomes
- `data/research/event_move_table.json` — canonical lookup (111 outcomes, 2 dates, 56 tickers)
- `tests/test_event_move_lookup.py` — 24 tests covering lookup, fallback, mispricing, confidence

## Data Assessment (2026-03-14)

| Cell | n | p50 | Confidence |
|------|---|-----|------------|
| CLINICAL/phase3/oncology | 48 | 0.018 | ok |
| CLINICAL/phase3/other | 31 | 0.015 | ok |
| CLINICAL/phase2/any | 12 | 0.027 | ok |
| CLINICAL/any/any | 101 | 0.017 | ok |
| Global | 111 | 0.018 | ok |

**Key limitation:** p50 abs_gap values are 1.5-4.8% — these are calendar-inferred PCD events, not hard binary readouts. The straddle mispricing signal will be most useful once the dataset includes PDUFA/readout events with 10-50%+ abs_gap.

Zero REGULATORY outcomes currently. Table will auto-improve as snapshot outcomes accumulate.

## Next Steps (Sessions 2-4)

- Session 2: Wire cheap_vol_score into run_screen.py as diagnostic columns
- Session 3: Build eval_straddle_mispricing.py research study
- Session 4: Wire verdict into review queue action rules

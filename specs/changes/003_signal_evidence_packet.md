# Change Spec: Signal Evidence Packet Harness

**Status**: IN_PROGRESS
**Author**: arrenchulz
**Date**: 2026-03-13
**Ruleset impact**: NO (tooling only — no ranking or portfolio changes)

---

## Objective

Build a thin composition layer that consumes existing evaluation artifacts (`eval_forward_returns`, `rerank_snapshots`) to produce a single, governance-grade evidence packet for signal proposals. Eliminates manual diff workflows when comparing baseline vs candidate rankings.

## PIT / Data Constraints

- [x] No lookahead — delegates to `eval_forward_returns.evaluate()` which enforces PIT
- [x] Data source: snapshot directories (rankings.csv + metadata.json), price_history.csv
- [x] Historical availability: depends on available snapshots and price data
- [x] Known gaps: none introduced; inherits gaps from underlying evaluator

## Inputs

| Input | Source | Schema |
|-------|--------|--------|
| date_manifest | User-provided text file | One YYYY-MM-DD per line or CSV with `date` column |
| baseline snapshots | `--baseline-root` directory | Standard snapshot dirs (rankings.csv + metadata.json) |
| candidate snapshots | `--candidate-root` directory | Standard snapshot dirs (rankings.csv + metadata.json) |
| price_history.csv | `--price-csv` path | Standard price history (ticker, date, close) |
| ruleset JSON | `--rerank-spec` (optional) | DecisionRuleset JSON |

## Outputs

| Output | Destination | Schema |
|--------|-------------|--------|
| signal_evidence.json | `--out-dir` | `signal_evidence.v1` (see script docstring) |
| signal_evidence.md | `--out-dir` | Human-readable summary |

## Invariants

1. **Deterministic**: same inputs → identical JSON output (byte-level after canonical key sort)
2. **Fail-closed on missing manifest**: empty or missing manifest → hard error, no implicit date discovery
3. **Manifest-exact evaluation**: only dates listed in manifest are evaluated; no extras
4. **Symmetric evaluation**: baseline and candidate use identical eval parameters
5. **No side effects**: does not modify snapshots, rankings, or any production data

## Failure Modes

| Scenario | Expected behavior |
|----------|-------------------|
| Missing or empty date manifest | Hard error with clear message |
| Snapshot dir missing for a manifest date | Date counted as skip; if <50% coverage → NEEDS_MORE recommendation |
| Price CSV missing | Hard error (required by eval_forward_returns) |
| Candidate root == baseline root | Allowed; produces near-zero deltas (useful for smoke tests) |
| Optional rerank-spec invalid | Hard error before evaluation begins |

## Validation Plan

### Tests (write BEFORE implementation)
- [x] `test_deterministic_output` — same inputs → identical JSON packet
- [x] `test_identity_delta` — candidate == baseline → all deltas ≈ 0.0
- [x] `test_missing_snapshot_fails` — manifest date with no snapshot → fail-closed
- [x] `test_low_coverage_fails` — <50% evaluable → NEEDS_MORE + coverage warning
- [x] `test_pit_validation_propagates` — metadata mismatch → reported in pit_validation
- [x] `test_manifest_honored_exactly` — only manifest dates evaluated
- [x] `test_recommendation_thresholds` — verify PROMISING/REJECT/NEEDS_MORE logic

### Evaluation (if signal/ranking change)
- N/A — this is tooling, not a signal change

### Integration
- [ ] Full suite passes
- [ ] No pre-commit hook failures

## Expected Effect Size

Structural improvement only — reduces manual signal evaluation workflow from ~15min to a single command. No direct IC or alpha impact.

## Non-Goals

- Does NOT replace or modify the promotion battery (`run_promotion_battery.py`)
- Does NOT implement new evaluation metrics beyond what `eval_forward_returns` already computes
- Does NOT auto-promote signals; only produces evidence packets for human review
- Does NOT handle multi-signal ablation (A vs B vs C); only pairwise baseline vs candidate

---

## Implementation Log

### 2026-03-13 — Initial implementation
- Files created: `scripts/run_signal_evidence.py`, `tests/test_signal_evidence.py`, `specs/changes/003_signal_evidence_packet.md`
- Tests added: 7
- Commit: pending

---

*Template version: 1.0.0 — see specs/SYSTEM_SPEC.md for system invariants*

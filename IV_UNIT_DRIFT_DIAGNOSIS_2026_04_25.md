# `priced_move_pct` Unit Drift — Root-Cause Re-Audit (2026-04-25)

**Status:** diagnosis only. No production code changes. Designed to land after the 2026-04-27 production cycle clears.

**Bottom line:** the original audit (`audit_run_screen_2026_04_25` memory) attributed `priced_move_pct` blowups to dollar/decimal confusion in the chain straddle. Re-audit shows the **primary cause is `opt_atm_iv` unit drift in the Tastytrade producer path, propagating through the IV-implied-move fallback** in `common/straddle_mispricing.py:74`. Chain-straddle dollar/decimal confusion is at most a secondary failure mode and is not present in the 2026-04-25 snapshot.

---

## 1. Field map and unit contracts

| Field | Expected unit | Producers (production path) |
|---|---|---|
| `opt_atm_iv` | decimal-annualized vol (e.g., `0.65` = 65%) | `common/options_diagnostics.py:718` (TT IVx — **uncapped**), `common/options_diagnostics.py:931` (Polygon massive-chain — capped at 8.0) |
| `straddle_price` (column) | decimal-fraction implied move (e.g., `0.39` = 39% move) — **after run_screen.py:5605 overwrite** | `run_screen.py:5605` (only writer in the production path; sources `cvs["implied_move"]` from `compute_cheap_vol_score`) |
| `implied_event_move` | decimal-fraction implied move | `run_screen.py:5795` via `common/pos_divergence.py:145` (`iv × sqrt(t)`) |
| `priced_move_pct` | percentage points (e.g., `39.0` = 39%) | `run_screen.py:3605` Phase 2z (`straddle_price × 100`) |

`compute_atm_straddle` in `common/massive_chain_analytics.py:165-174` writes `straddle_price` as **dollars** in the chain analytics dict, but that field is read into `_chain_straddle_price` (run_screen.py:5540), not into the public `straddle_price` column. The public column is unconditionally overwritten at line 5605 with `cvs["implied_move"]` (decimal fraction). So the public `straddle_price` column unit is consistent on the production path — provided `cvs["implied_move"]` itself is sane.

`cvs["implied_move"]` in `common/straddle_mispricing.py` comes from one of two paths:

- Line 70: `implied_move = actual_straddle_price / underlying_price` (decimal fraction, correct by construction)
- Line 73-74: `implied_move = opt_atm_iv × sqrt(catalyst_days/365.0)` — **inherits whatever units `opt_atm_iv` has**

The IV-fallback path is where the drift enters.

## 2. Cross-snapshot scale (the audit count was low)

```
snapshot       n_rows  pm>200   iv>5   iv>8  iv>10  sp==iem
2026-04-20        297      39     35     18     16      173
2026-04-21        297      42     29     14     11      178
2026-04-22        297      37     21     15     10      181
2026-04-23        297      42     24     12      9      182
2026-04-24        297      45     28     15     11      182
2026-04-25        297      38     27     12     10      187
```

- `pm > 200`: 37–45 per snapshot, **stable around 12–15% of rows**, not growing.
- Original audit memory said "13/250" — that was an undercount or a different threshold. The real scale has been ~13% for at least the last 6 snapshots.
- `sp == iem` for ~60% of rows confirms most `straddle_price` values come from the same `iv × sqrt(t)` IV-fallback path as `implied_event_move` (not from a chain straddle dollar value).

## 3. Producer attribution

For 2026-04-25 (`opt_atm_iv > 5` count by `opt_diagnostic_basis`):

| Basis | All rows | iv > 5 |
|---|---:|---:|
| `tt_market_metrics` | 286 | **27** |
| `no_liquid_expiry` | 11 | 0 |

**100% of bad IVs in the production path come from the Tastytrade IVx producer.** The Polygon massive-chain producer (`options_diagnostics.py:931`) is not active on this snapshot and has its own cap (`min(front_iv, 8.0)`) anyway. The TT producer at line 718 is **completely uncapped**:

```python
"opt_atm_iv": round(atm_iv, 4) if atm_iv is not None else round(front_iv, 4),
```

## 4. `opt_iv_regime` is already a working quarantine signal — but ignored

For 2026-04-25:

| `opt_iv_regime` | `pm > 200` | `pm 1–200` | `pm < 1` / empty |
|---|---:|---:|---:|
| EXTREME (≥ 4.0) | **36** | 30 | 9 |
| ELEVATED (1.20–4.0) | 2 | 138 | 21 |
| NORMAL (< 1.20) | 0 | 44 | 6 |

`opt_iv_regime == EXTREME` predicts 36 of 38 bad rows. The flag is already computed (Polygon path: `options_diagnostics.py:916`; TT path via `compute_operator_flags`). Likewise `opt_use_for_judgment` is already set to `"NO"` when `capped_iv >= 5.0` on the Polygon path. **No production consumer reads either flag** — `common/straddle_mispricing.py:74`, `common/pos_divergence.py`, and `event_ev/ev_calculator.py:261` all consume `opt_atm_iv` directly with no quality gate.

## 5. Propagation example (TYRA, 2026-04-25)

- `opt_atm_iv = 21.4094` (TT IVx — uncapped, implausible as decimal-annualized vol)
- `catalyst_days = 129`
- `sqrt(129/365) = 0.5945`
- `implied_move = 21.4094 × 0.5945 = 12.728`
- `row["straddle_price"] = "12.7278"` (run_screen.py:5605 writes the decimal-fraction-by-contract value)
- `row["implied_event_move"] = 12.7278` (same `iv × sqrt(t)` math via `pos_divergence`)
- Phase 2z (run_screen.py:3605): `priced_move_pct = 12.7278 × 100 = 1272.78`

The Phase 2z saturation guard at `run_screen.py:3608` does fire (`_n_suspicious` warning logged) but does not quarantine the row.

## 6. Why the original audit was wrong

The audit memory said:

> *upstream `straddle_price` is sometimes dollar-denominated while `straddle_price * 100` assumes decimal-fraction*

This would be true if `row["straddle_price"]` were sourced from `_chain_straddle_price` (the dollar-denominated chain field). It is not — line 5605 unconditionally overwrites with `cvs["implied_move"]` (decimal fraction). The visible-on-CSV unit is consistent. The drift enters earlier, in `cvs["implied_move"]`, because the IV-fallback path inherits a corrupted `opt_atm_iv`.

Chain-straddle dollar/decimal confusion remains a *theoretical* failure mode (e.g., if a future code path bypasses line 5605), but it is not the cause of the 38/297 rows observed on 2026-04-25 or the 37–45/297 rows seen on each of the prior five snapshots.

## 7. Proposed quarantine rule (producer-side)

Per the design rule (validate at producer, do not clamp downstream, keep run_screen saturation guard as tripwire):

**Primary fix — Tastytrade producer (`common/options_diagnostics.py:718` block):**

- Apply a producer-side validity cap. Threshold candidate: **IV > 4.0 → write `""` (missing) and set `opt_use_for_judgment="NO"`, `opt_iv_regime="INVALID"`**. Rationale: 400% annualized vol is already extreme for biotech; 800% (Polygon's existing cap) is too generous; `iv ≥ 5.0` is the existing `opt_use_for_judgment` threshold on the Polygon path so 4.0 leaves a small safety margin.
- Do NOT silently cap (i.e., do not write `min(iv, 4.0)`); blanking the field is honest — propagates as missing through downstream, which is the intended degrade behavior.
- Tag the row in a sidecar quarantine list (`production_data/iv_quarantine_{date}.json`) so the audit trail survives.

**Secondary fix — Polygon producer (`options_diagnostics.py:931`):**

- Lower cap from 8.0 to match the new TT threshold.
- Keep the `opt_use_for_judgment` flag, but downstream must consult it (see consumer fix below).

**Consumer hardening — defensive but not the primary fix:**

- `common/straddle_mispricing.py:72-74`: skip the IV-fallback when `opt_atm_iv` exceeds a sanity threshold (e.g., 4.0). Treat as no-data, return `empty`. This is a tripwire, not the fix.
- `run_screen.py:3608` saturation guard: keep the warning. Add a hard-fail mode behind `--pit-mode=strict` (mirrors the cache-miss policy). In `degrade` mode, blank the row's `priced_move_pct` instead of writing the inflated value.

**Explicitly NOT in scope:**

- No downstream clamping of `priced_move_pct`. Saturation guard remains warning-only in degrade mode.
- No retroactive backfill of the 6 affected snapshots. Mark them as known-degraded in a snapshot-level note; do not rewrite history.

## 8. Test sketch

```python
# tests/test_iv_quarantine.py — to be written after 2026-04-27 cycle clears

def test_tt_producer_blanks_extreme_iv():
    # IV > 4.0 from TT path must blank opt_atm_iv and set opt_use_for_judgment=NO
    diag = build_tt_diag(atm_iv=10.5, ...)
    assert diag["opt_atm_iv"] == ""
    assert diag["opt_use_for_judgment"] == "NO"
    assert diag["opt_iv_regime"] == "INVALID"

def test_straddle_mispricing_skips_extreme_iv():
    # IV > 4.0 → return empty result, do not propagate
    cvs = compute_cheap_vol_score(opt_atm_iv=10.0, catalyst_days=129, ...)
    assert cvs["implied_move"] is None

def test_phase2z_blanks_in_degrade_mode():
    # Phase 2z with priced_move_pct > 500 should blank the field, not write it
    rows = [{"straddle_price": "10.0", "priced_move_pct": ""}]
    _finalize_priced_move(rows, mode="degrade")
    assert rows[0]["priced_move_pct"] in ("", None)

def test_full_snapshot_no_extreme_pm():
    # Regression: full pipeline against fixture data should produce 0 rows with pm > 200
    rows = run_pipeline_against_fixture("tests/fixtures/2026-04-25_minimal/")
    bad = [r for r in rows if float(r.get("priced_move_pct") or 0) > 200]
    assert bad == []
```

## 9. `market_data.json` freshness control — separate draft

Independent of the IV drift, the second open audit control. Status of file as of 2026-04-25:

- Top-level: list of 341 dicts. No document-level `as_of_date`/`snapshot_date`.
- Per-row: `collected_at` field present on all 341 rows; uniform value `"2026-04-22"`.
- `run_screen.py` does not read `collected_at` anywhere. Only `common/data_integration_contracts.py:251,265` declares it as a known field — schema-only, no validation.
- Today is 2026-04-25; data is 1 business day stale (Friday → Monday acceptable; Friday → Tuesday borderline; Friday → Wednesday is the current state and warrants a warning).

**Proposed control:**

1. **Producer:** `collect_market_data.py` and similar emit a top-level wrapper:
   ```json
   {"as_of_date": "2026-04-22", "rows": [...]}
   ```
   Backwards-compat: keep `collected_at` per-row. Consumers that read the list directly continue to work via a small loader shim.

2. **Consumer:** `run_screen.py` validates at load time:
   - All rows must have `collected_at`.
   - All `collected_at` values must match the document-level `as_of_date` (or be explicitly tagged as a mixed-date snapshot with provenance).
   - `as_of_date` must be ≤ run_screen's `as_of_date` and within `N` business days (proposed: `N=2` business days).
   - **Strict mode:** raise `MarketDataStaleError` on mismatch / staleness / missing date.
   - **Degrade mode:** warn, set a `coverage_degraded=True` flag on the run, propagate to snapshot metadata.

3. **Schema check:** add `as_of_date` to `common/data_integration_contracts.py` market-data contract; emit a hard error on missing top-level field once producer is updated.

## 10. Action plan (post 2026-04-27 cycle clear)

1. Land producer-side IV cap in `common/options_diagnostics.py` (TT path) + matching Polygon-path threshold.
2. Land consumer guard in `common/straddle_mispricing.py` as a tripwire.
3. Land `--pit-mode=strict` hard-fail and `--pit-mode=degrade` blank-out for Phase 2z.
4. Tests in `tests/test_iv_quarantine.py`.
5. Separately: `market_data.json` freshness control (producer wrapper + consumer validation). Spec sequencing — should be a separate cycle from the IV fix.

Both controls together fix the two open audit items without restarting the pause-between-control-plane-changes clock more than once.

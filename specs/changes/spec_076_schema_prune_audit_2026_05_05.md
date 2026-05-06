# Spec 076 — Schema Prune Audit (2026-05-05)

**Status:** Audit and categorization ticket. No field removals yet. Output is a verified field registry organized by lifecycle category. Cuts require a separate implementation ticket with blast-radius diff.

**Hold-off scope:** No schema changes, no CSV column removals, no `run_screen_columns.py` edits. This ticket resolves the contradiction in the investment logic audit memo and produces the ground truth categorization that any future pruning must reference.

---

## 1. Why this audit exists

The 2026-05-05 investment logic audit memo incorrectly stated that `clinical_design_quality` is "never populated / zero-fill." Direct measurement from the 2026-05-05 rankings snapshot showed 231/299 rows (77.3%) non-empty. The audit also identified ~30 fields as candidates for removal, but several had not been verified at the time.

This ticket documents the verified state of every alleged dead field and establishes the correct lifecycle category for each. **Do not cut any field without first confirming it appears here as DEAD.**

---

## 2. Verified field categories

All fill rates measured from `data/snapshots/2026-05-05/rankings.csv` (299 rows). Total schema: 319 columns — schema and CSV are aligned (zero mismatch).

---

### Category A — ACTIVE (do not cut)

| Field | Fill rate | Producer | Notes |
|---|---|---|---|
| `clinical_design_quality` | 231/299 (77.3%) | `common/event_quality_features.py:249` → `compute_clinical_design_quality()` | Conditional: only CLINICAL catalyst family rows get non-empty values. Non-clinical tickers correctly empty. This is by-design, not a data gap. |

**Correction to audit memo:** The claim that `clinical_design_quality` is zero-fill is wrong. The field is computed in `common/event_quality_features.py` via a weighted score (0.35 × design_quality + 0.30 × phase_score + 0.20 × endpoint_strength + 0.15 × confirmatory_proxy) and written to every CLINICAL-family row. It appears in `run_screen_columns.py` and is read by `common/ranking_utils.py:275`. Do not remove.

---

### Category B — DEAD (zero fill, producer inactive or artifact missing)

These fields can be removed in a future pruning ticket after blast-radius diff review. No field in this category should be cut without confirming: (a) no downstream consumer reads it, (b) no test references it as an expected output column, (c) no agent or cron script writes to it.

#### B1 — Options Verdict Features (OVF), 8 fields

Fill rate: 0/299 for all.

| Field |
|---|
| `ovf_agreement_count` |
| `ovf_severity_score` |
| `ovf_near_catalyst` |
| `ovf_has_event_premium` |
| `ovf_has_iv_ramp` |
| `ovf_has_quiet_before` |
| `ovf_surface_confirmed` |
| `ovf_composite` |

**Root cause:** Producer is `common/options_verdict_features.py:135-169` → `enrich_csv_rows_with_verdict()`, triggered in `run_screen.py:6035-6049`. The enrichment requires `artifacts/options_verdict/{as_of_date}_verdict.json`. This artifact is not being generated — the options verdict pipeline is inactive. Enrichment returns 0 rows; all 8 fields fall back to empty string.

**Removal prerequisite:** Confirm `artifacts/options_verdict/` is empty or stale before cutting. If the verdict pipeline is ever reactivated, these fields will self-populate.

#### B2 — Morningstar Fields, 6 fields

Fill rate: 0/299 for all.

| Field |
|---|
| `ms_volatility_3yr` |
| `ms_volatility_5yr` |
| `ms_star_rating` |
| `ms_return_ytd` |
| `ms_return_annualized_3yr` |
| `ms_return_annualized_5yr` |

**Root cause:** Producer is `morningstar_signal_engine.py:455-460`, triggered in `run_screen.py:6012-6033`. Requires `enhancement_result.morningstar_scores.scores.{ticker}`. No Morningstar feed is active; enriched count = 0.

**Removal prerequisite:** Confirm DealForma/Morningstar feed is permanently dropped (per memory: "DealForma DROPPED"). These are safe to remove.

#### B3 — Legacy Ranker Block Fields, 4 fields

Fill rate: 0/299 for all.

| Field |
|---|
| `ranker_adjustment` |
| `ranker_options_block` |
| `ranker_inst_block` |
| `ranker_aact_block` |

**Root cause:** These fields belonged to a prior ranker design with per-block scoring. The current ranker (`ranker_v2_pairwise.py`) uses only 2 features (`coinvest_score_z`, `financial_score`) with no block decomposition. These fields are not written by any active code path.

#### B4 — Penalty and Tilt Flags, 6 fields

Fill rate: 0/299 for all.

| Field |
|---|
| `cost_haircut_applied` |
| `catalyst_type_tilt_applied` |
| `mom_state_tilt_applied` |
| `slippage_penalty_score` |
| `missing_components` |
| `missingness_penalty` |

**Root cause:** Not in current scoring path. Gates or tilt mechanisms that were designed but not activated in v1.13+/v1.14.

---

### Category C — CONDITIONAL / DEAD-BY-DEFAULT

These fields are non-empty only in error or edge-case conditions. They should NOT be removed — they are diagnostic outputs that exist for a reason. They should be retained but not expected to appear in normal snapshots.

| Field | Trigger condition |
|---|---|
| `de_alpha_60d_missing_reason` | Decision engine encounters missing alpha data — error path only |

Any other field that documents a failure mode or edge-case fallback belongs in this category. Check for similar `*_reason`, `*_flag`, `*_error` fields in `run_screen_columns.py` before categorizing them as DEAD.

---

## 3. Pre-cut checklist (for future pruning ticket)

Before any field in Category B is removed from `run_screen_columns.py` and the CSV output:

- [ ] Grep all test files for the field name — remove test assertions that check for its presence
- [ ] Grep all agent files (`agents/`) for the field name — confirm no agent reads it
- [ ] Grep all tool files (`tools/`) for the field name — confirm no downstream consumer
- [ ] Grep `docs/` for the field name — update or remove documentation references
- [ ] Check `common/ranker_active_contract.py` — field should not appear in the active contract
- [ ] Confirm no cron artifact writes the field to a JSONL or JSON output file that downstream scripts parse
- [ ] Run full test suite before and after removal — zero regressions

Do not batch-remove all Category B fields in one commit. Group by subcategory (B1 OVF together, B2 MS together, etc.) so each removal is a reviewable unit.

---

## 4. clinical_design_quality — shadow monitoring status

Because the audit memo error nearly led to cutting this field, explicitly record its monitoring context here:

- **Phase A verdict (2026-05-04):** Clinical selector NO_GO; clinical ranker SHADOW only on `clinical_design_quality`. The field IS active in shadow.
- **Spec 072 vNext:** Clinical quality ranks survivors after the manager gate and trap filter. `clinical_design_quality` is a candidate input to the L4 ranker.
- **Next verdict review:** 2026-05-22. Do not touch this field before that review.

---

## 5. Verification commands

To re-verify any field's fill rate against the current snapshot:

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener

# Single field
python -c "
import pandas as pd
df = pd.read_csv('data/snapshots/2026-05-05/rankings.csv')
col = 'clinical_design_quality'
nonempty = df[col].notna() & (df[col].astype(str).str.strip() != '')
print(f'{col}: {nonempty.sum()}/{len(df)} ({nonempty.mean():.1%})')
"

# Batch check all alleged dead fields
python -c "
import pandas as pd
df = pd.read_csv('data/snapshots/2026-05-05/rankings.csv')
fields = [
    'ovf_agreement_count','ovf_severity_score','ovf_near_catalyst',
    'ovf_has_event_premium','ovf_has_iv_ramp','ovf_has_quiet_before',
    'ovf_surface_confirmed','ovf_composite',
    'ms_volatility_3yr','ms_volatility_5yr','ms_star_rating',
    'ms_return_ytd','ms_return_annualized_3yr','ms_return_annualized_5yr',
    'ranker_adjustment','ranker_options_block','ranker_inst_block','ranker_aact_block',
    'cost_haircut_applied','catalyst_type_tilt_applied','mom_state_tilt_applied',
    'slippage_penalty_score','missing_components','missingness_penalty',
]
for f in fields:
    if f not in df.columns:
        print(f'{f}: NOT IN SCHEMA')
        continue
    nonempty = df[f].notna() & (df[f].astype(str).str.strip() != '')
    print(f'{f}: {nonempty.sum()}/{len(df)}')
"
```

Re-run these commands against the snapshot on the date of any future pruning ticket to confirm fill rates have not changed before cutting.

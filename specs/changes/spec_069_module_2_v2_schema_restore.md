# Spec 069 — Module 2 v2 Schema Restore (2026-04-28)

**Status:** Spec only. **No production code changes from this document.**
**Author:** drafted 2026-04-28 in response to Spec 068 audit findings.
**Constraint:** alpha-stack frozen per `policy_alpha_freeze_2026_04_04.md`. Architecture frozen per `policy_freeze_architecture_2026_04_19.md`. **This spec is alpha-affecting.** Implementation requires Checklist v2 (FM + bootstrap + FDR + LOSO + year stability) before merge.

## 0. Why this spec exists

The Spec 068 audit (2026-04-28) traced four `likely_internal_stale` mismatches (MESO/VCEL/HALO/MLYS) to a deeper bug: **Module 2 v2 (`module_2_financial_v2.py`) does not emit `has_revenue` or `revenue_scale_bucket` fields** that Module 2 v1 (`module_2_financial.py:calculate_revenue_score`) produced. `run_screen.py:9720-9721` reads these keys with defaults:

```python
has_revenue = m2.get("has_revenue", False)
revenue_scale_bucket = m2.get("revenue_scale_bucket", "pre_revenue")
```

Result: `False` and `"pre_revenue"` for every ticker. The `commercial_biotech` promotion path in `classify_company_archetype()` (`run_screen.py:408-410`) is dead code:

```python
if archetype == "drug_developer" and has_revenue and revenue_scale_bucket in ("medium", "large"):
    archetype = "commercial_biotech"
```

The `commercial_pharma` archetype path (via `INDUSTRY_TO_ARCHETYPE` map keyed on Yahoo Finance industry) is unaffected and continues to fire correctly (36 tickers in today's snapshot).

## 1. Scope

This spec defines a single change: restore `has_revenue` and `revenue_scale_bucket` emission in Module 2 v2's per-ticker score record so the `commercial_biotech` archetype promotion fires for the 67 affected tickers in today's universe.

**Out of scope** for this spec (do not bundle):
- Adjusting Module 2 v1/v2 revenue thresholds.
- Adding new archetype categories.
- Changing the `commercial_pharma` industry map.
- Modifying the clinical activity filter logic.
- Touching `stage_bucket` derivation or any Module 5 cohort code.
- Module 4 lead-phase logic.

## 2. Blast radius (measured on 2026-04-28 snapshot)

Computed against `data/snapshots/2026-04-28/rankings.csv` (n=297) and `production_data/financial_records.json`.

### 2.1 Revenue bucket population

| Bucket | Threshold | Count |
|---|---|---|
| `pre_revenue` | < $10M | 131 |
| `small` | $10M – $100M | 50 |
| `medium` | $100M – $1B | 76 |
| `large` | ≥ $1B | 40 |

### 2.2 Archetype delta

| Archetype | Now | After restore | Δ |
|---|---|---|---|
| `drug_developer` | 230 | 163 | **−67** |
| `commercial_biotech` | 0 | 67 | **+67** |
| `commercial_pharma` | 36 | 36 | 0 |
| `platform_diagnostics` | 14 | 14 | 0 |
| `platform_devices` | 12 | 12 | 0 |
| `platform_services` | 5 | 5 | 0 |

67 tickers (29% of `drug_developer` cohort) would move to `commercial_biotech` if their `Revenue ≥ $100M`.

### 2.3 Top-30 / Top-60 selector impact

- **Top-30**: 4 tickers promote → `IMCR`, `INSM`, `MIRM`, `STOK` (selector_scores 0.87–0.92).
- **Top-60**: 11 tickers promote → `AXSM`, `IDYA`, `IMCR`, `INSM`, `JAZZ`, `KRYS`, `MIRM`, `PTCT`, `SNDX`, `STOK`, `ZYME`.

These are real composition shifts: 4 of today's top-30 names move to a different archetype cohort, with downstream effects on clinical_score_z, financial_score rank-norm cohort, and clinical activity filter exemption.

### 2.4 Cohort population changes

**clinical_score_z** is computed per-archetype-cohort in `run_screen.py:4220-4244`:

| Cohort | Now | After restore |
|---|---|---|
| `drug_developer` (`dev`) | 230 | 163 |
| `commercial_biotech` (`comm_biotech`) | 0 | 67 |
| `commercial_pharma` (`comm_pharma`) | 36 | 36 |

The `commercial_biotech` cohort is currently empty — its z-score path effectively doesn't run. After restore, it has 67 members and computes its own mean/std. The `drug_developer` cohort loses 67 names (the largest, mostly late-stage), shifting its mean and std materially. **Every remaining `drug_developer` ticker's `clinical_score_z` value will change** because the cohort statistics are different.

### 2.5 Clinical activity filter exemption

`run_screen.py:702-792` (`apply_clinical_activity_filter`) excludes tickers without sufficient clinical activity, but exempts non-`drug_developer` archetypes. After restore, **67 tickers gain exemption from the filter**. For `drug_developer`s with marginal clinical activity, this matters; for tickers with strong pipelines, it's a no-op. Need to enumerate the subset that was previously eligibility-marginal.

### 2.6 stage_bucket × market_cap_bucket cohort

`module_5_composite*.py` computes `financial_score` z-norm within (stage_bucket × market_cap_bucket) cells. Archetype itself doesn't appear in this key, but stage_bucket is derived from `lead_phase`, which for commercial_biotech tickers is typically `approved` or beyond. So while archetype changes don't directly recompute the cohort key, **the population of late-stage cells gets clarified** and the financial_score rank-norm tightens (less noise from misclassified commercial names sitting in `phase_3` cohorts).

## 3. Repair options

### Option 1 — Restore schema in Module 2 v2 (recommended)

Add `has_revenue` and `revenue_scale_bucket` keys to each ticker's score dict produced by `compute_module_2_financial` (v2). Use the same threshold logic as v1:

```python
# In module_2_financial_v2.py, alongside existing scoring:
revenue = financial_data.get("Revenue", 0) or 0
score_record["has_revenue"] = revenue >= 10e6
if revenue >= 1e9:
    score_record["revenue_scale_bucket"] = "large"
elif revenue >= 100e6:
    score_record["revenue_scale_bucket"] = "medium"
elif revenue >= 10e6:
    score_record["revenue_scale_bucket"] = "small"
else:
    score_record["revenue_scale_bucket"] = "pre_revenue"
```

**Pros**:
- Single source of truth: Module 2 owns revenue classification.
- v1/v2 schema parity restored; no caller changes needed.
- Trivial to test in isolation.

**Cons**:
- Module 2 v2 file gets one more responsibility it apparently dropped intentionally during the v1→v2 migration. Need to confirm the drop wasn't deliberate (read commit history before implementing).

### Option 2 — Compute revenue bucket locally in run_screen.py

Bypass Module 2 entirely; read `financial_records[ticker]["Revenue"]` directly inside the archetype-classification loop:

```python
fr_by_ticker = {r["ticker"]: r for r in financial_records}
# …
rev = (fr_by_ticker.get(ticker, {}).get("Revenue") or 0)
has_revenue = rev >= 10e6
revenue_scale_bucket = (
    "large" if rev >= 1e9
    else "medium" if rev >= 100e6
    else "small" if rev >= 10e6
    else "pre_revenue"
)
```

**Pros**:
- No Module 2 changes; surgical patch in `run_screen.py`.
- Works even if Module 2 fails or skips a ticker.

**Cons**:
- Two sources of truth for revenue thresholds (Module 2 v1 + run_screen.py duplicate).
- Defeats the encapsulation Module 2 was meant to provide.
- Future Module 2 v3 change to thresholds wouldn't propagate.

### Recommendation

**Option 1**, unless `git log module_2_financial_v2.py` reveals the schema drop was intentional (e.g., to remove dead fields nobody read — which would be ironic given that this *is* a real consumer). Default to Option 1 with a v2 unit test asserting the new keys appear in every score record.

## 4. Pre-implementation gates (Checklist v2 required)

This change is alpha-affecting. Before merge, the following must be produced:

1. **Forward-Modeling (FM)** of the change on the 2026-04-28 snapshot:
   - Diff in selector top-30 composition (4 known affected; map full delta in/out).
   - Diff in EW Top-30 returns under 30/70 DEM/XBI allocation, simulated forward for a horizon to be selected at planning time.
2. **Block bootstrap** of the diff with horizon-matched lag.
3. **FDR** correction across all archetype-affecting changes (none active right now, so this is a single-test correction).
4. **LOSO** (leave-one-snapshot-out) stability — re-run the diff over a rolling window to confirm direction/magnitude is stable.
5. **Year stability** — show the directional sign holds across 2024 / 2025 / 2026 retrospective snapshots (with the pseudo-PIT caveat from `Historical Backtest INVALIDATED 2026-04-17`).
6. **Cohort-change quarantine plan** per `feedback_cohort_change_quarantine`: the first snapshot after the change will have contaminated `inst_delta_z` and `rank_delta` because the archetype cohort population shifts. The plan must explicitly mark the post-change snapshot as quarantined and gate downstream consumers.
7. **Blast-radius diff per `feedback_quarantine_blast_radius_diff`**: per-ticker rows-affected, downstream-fields-degraded.

## 5. Implementation envelope (when gates clear)

- Minimal patch: ~10 lines in `module_2_financial_v2.py` (Option 1) or ~15 lines in `run_screen.py` (Option 2).
- A unit test asserting `has_revenue` and `revenue_scale_bucket` appear in every Module 2 v2 score record.
- A regression test that on the 2026-04-28 fixture, exactly 67 tickers become `commercial_biotech`.

## 6. Non-goals

- **No archetype taxonomy changes.** Same enum as today.
- **No new clinical activity filter rules.** The existing exemption path applies.
- **No `stage_bucket` re-derivation.** Same lead_phase → bucket map.
- **No Module 5 / EES / Event EV / ranker / selector logic changes.** This spec only restores the field emission; downstream code is unchanged.
- **No fix to `run_screen.py:9720-9721` defaults.** They remain as defensive fallbacks.

## 7. Open questions

These need answers before §5 is written:

1. **Was the schema drop intentional?** Run `git log -p -- module_2_financial.py module_2_financial_v2.py | grep -A5 -B2 "has_revenue\|revenue_scale_bucket"` to see when v1 emitted these and when v2 stopped. If the migration commit explicitly removed them as dead code, this spec needs to reconcile that with the now-active consumer at `run_screen.py:9720`.
2. **Are the v1 thresholds still right?** $10M / $100M / $1B were set at some point; biotech revenue distributions in 2026 may warrant re-calibration. **Out of scope for this spec** — answer is "use the v1 thresholds verbatim" — but flag as a candidate for a separate spec if Checklist v2 finds the cutoffs are introducing classification noise.
3. **Should Spec 068's `development_stage_overrides.json` be retired once Spec 069 lands?** Probably yes for the 4 current entries (HALO/VCEL would auto-promote to `commercial_biotech`, which sets `development_stage = "commercial"` via the `archetype.startswith("commercial_")` precedence at `run_screen.py:683-684`; MESO and MLYS still need overrides because their revenue is too small). Decision deferred until Spec 069 is implemented and verified.

## 8. References

- `MEMORY.md` index entries: `policy_alpha_freeze_2026_04_04.md`, `policy_freeze_architecture_2026_04_19.md`, `feedback_quarantine_blast_radius_diff.md`, `feedback_cohort_change_quarantine.md`, `spec_068_pre_implementation_2026_04_28.md`
- Spec 068: `specs/changes/spec_068_development_stage_external_cache_audit.md`
- Audit artifact that surfaced this: `artifacts/development_stage/stage_cache_audit_2026-04-28.{csv,md,json}`
- Code locations: `module_2_financial.py:559-665` (v1 `calculate_revenue_score`), `module_2_financial_v2.py:1340+` (v2 wrapper), `run_screen.py:380-412` (`classify_company_archetype`), `run_screen.py:9714-9727` (call site).

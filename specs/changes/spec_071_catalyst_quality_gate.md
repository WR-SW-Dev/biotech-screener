# Spec 071 — Catalyst Quality Gate (2026-04-29)

**Status:** Spec only. **No production code changes from this document.**
**Author:** drafted 2026-04-29 in response to the false-clinical-catalyst audit (`artifacts/audit/false_clinical_catalyst_audit_2026-04-29.md`).
**Constraint:** alpha stack frozen per `policy_alpha_freeze_2026_04_04.md`. Architecture frozen per `policy_freeze_architecture_2026_04_19.md`.
**Lane discipline:**
- **Lane 1** (status hard-reject) is a **data-quality defect fix**. Ships behind a narrow change window with a before/after diff. No Checklist v2 required.
- **Lane 2** (full classifier) is **alpha-affecting**. Requires Checklist v2 (FM + bootstrap + FDR + LOSO + year stability) before production promotion.

## 1. Background

`module_3_catalyst.py:272` (`convert_calendar_catalyst_to_v2`) and its producer `catalyst_diagnostics.py:450` (`detect_calendar_catalysts`) treat any CT.gov primary-completion / study-completion date inside a forward window as a forward-looking catalyst with `source="CTGOV_CALENDAR"`. The only exclusion at the producer level is `record.overall_status.is_terminal_negative`. Title content, study type, and several status states (WITHDRAWN, APPROVED_FOR_MARKETING, AVAILABLE) are not inspected.

CT.gov primary-completion dates are **not** automatically alpha catalysts. Registry maintenance dates, open-label extensions (OLE), PK subtrials, healthy-volunteer Phase-1 studies, withdrawn studies, expanded-access protocols, and post-approval studies can each produce false `catalyst_near` / `build_window` / Tier-A credit through this path. The KALV takeout post-mortem on 2026-04-29 surfaced the pattern: KALV's `2026-06-30 CT_PRIMARY_COMPLETION` mapped to `NCT05505916` (open-label long-term safety extension) and `NCT05511922` (PK subtrial in adolescents), despite EKTERLY having been approved and launched in July 2025. The acquisition was M&A on a launched commercial asset, not a clinical readout.

## 2. Evidence from audit (2026-04-29 snapshot)

Source: `tools/audit_false_clinical_catalyst.py`, run against `data/snapshots/2026-04-29/rankings.csv` and `production_data/trial_records.json`.

| Metric | Count |
|---|---:|
| In-window catalysts (all sources, `binary_now` + `build_window`) | 104 |
| CT.gov candidates audited (`CTGOV_CALENDAR` ∪ `CTGOV_PCD_FAR`) | 85 |
| **High-confidence FALSE** | **15 (17.6%)** |
| Ambiguous (manual review) | 1 |
| Likely valid | 69 |

**KALV seed (out of in-window threshold but inside `build_window` bucket):**
- Rank 46, Tier A/A, `build_window` 62d, `CT_PRIMARY_COMPLETION 2026-06-30`
- `NCT05505916` — open-label long-term safety extension → flagged `title:ole_or_long_term_extension`
- `NCT05511922` — PK subtrial (adolescent) → flagged `title:pk_subtrial`
- Aggregate verdict: **false**

**Primary patterns observed in the 15 false catalysts:**

1. **WITHDRAWN trials still credited** (5 cases): `JAZZ` (rank 33), `FATE` (42), `ELDN` (166), `NVAX` (172), `IBRX` (186). Pure data-quality bugs.
2. **Phase-1 healthy-volunteer / PK studies credited as catalysts on late-stage names** (6 cases): `PTGX` (109, A/A, **stage=phase_3**) → P1 healthy-subjects study; `SION` (93), `CLYM` (117), `GHRS` (121), `BEAM` (62), `BMEA` (no rank).
3. **Approved-product registry maintenance** (1 case, KALV-pattern): `KALV` (46) — OLE + PK subtrial on already-approved/launched drug.
4. **Mixed observational pile** (1 case): `DNA` (Ginkgo, no rank) — six trials matching same date, mostly OBSERVATIONAL or N/A interventional.

## 3. Scope

This spec defines **two lanes**, sequenced. Lane 1 is implementation-ready as a defect fix; Lane 2 is a separate alpha-affecting change that must follow Checklist v2 before any production promotion.

**Out of scope (do not bundle):**
- SEC-filed catalysts (`SEC_8K_FILING`, `SEC_6K_FILING`, `PDUFA_MANUAL`, `FDA_ADCOM_CALENDAR`) — these are out-of-scope for this spec; they come from primary disclosures and are not registry-derived.
- Historical regeneration of past snapshots.
- Ranker retuning.
- Any change to selector / ranker / sizing weights.
- New external feeds.
- `DATA_READOUT` events that originate from SEC filings (the audit's 39 `DATA_READOUT` rows mostly come from CT.gov; those CT.gov-origin DATA_READOUTs are in-scope, the SEC-origin ones are not).

## 4. Lane 1 — narrow status-based defect fix

**Goal:** hard-reject CT.gov catalyst credit for trials whose `status` makes the date intrinsically non-actionable. No model behavior beyond this.

### 4.1 Filter

In `catalyst_diagnostics.py:detect_calendar_catalysts`, before emitting any `CalendarCatalyst`, drop the record if `record.overall_status` ∈ {

```
WITHDRAWN
TERMINATED
APPROVED_FOR_MARKETING
NO_LONGER_AVAILABLE
TEMPORARILY_NOT_AVAILABLE
```

}.

(Today the producer only checks `is_terminal_negative`, which on inspection does not cover the regulatory-cleared statuses or `WITHDRAWN`.)

### 4.2 What this changes

- The dropped trials no longer drive:
  - `catalyst_bucket` (`binary_now` / `build_window`)
  - `catalyst_near` reason
  - `tier_any` / `tier_dev` uplift via `high_opt+catalyst_near`
  - `actionable_rank` lift from the catalyst bonus
  - `next_catalyst_date` when no other CTGOV/SEC source provides one
- The trial date may still surface in dossiers as a context field (preserve `nct_id` + `primary_completion_date`), but it is **not** assigned a `CatalystEventV2`.

### 4.3 Expected immediate removals (audit-confirmed)

- `JAZZ` (rank 33) — `NCT06217536` WITHDRAWN, `NCT05850676` OBSERVATIONAL (latter is Lane 2)
- `FATE` (rank 42) — `NCT05934097` WITHDRAWN
- `ELDN` (rank 166) — `NCT04711226` WITHDRAWN
- `NVAX` (rank 172) — `NCT06482359` WITHDRAWN
- `IBRX` (rank 186) — `NCT05007769` WITHDRAWN

KALV is **not** affected by Lane 1 (its OLE / PK trials are `ACTIVE_NOT_RECRUITING`, not WITHDRAWN). KALV is a Lane 2 case.

### 4.4 Risk profile

Defect fix. The dropped trials cannot produce binary clinical alpha by definition — a withdrawn trial will never read out, and an `APPROVED_FOR_MARKETING` study has already cleared regulatory review. Lane 1 removes obviously invalid signal without changing the model's clinical-catalyst philosophy.

## 5. Lane 2 — full catalyst-quality classifier

**Goal:** classify every CT.gov-derived candidate event by the trial's intent, and downgrade non-binary events from tier-driving catalysts to context-only.

### 5.1 New field: `catalyst_quality`

For each row that has `catalyst_source ∈ {CTGOV_CALENDAR, CTGOV_PCD_FAR}` (or `catalyst_event_type ∈ {CT_PRIMARY_COMPLETION, CT_STUDY_COMPLETION}`), emit a new field `catalyst_quality` with one of:

| Value | Meaning |
|---|---|
| `binary_alpha` | True forward-looking efficacy or readout event. |
| `registry_only` | Trial-registry artifact (OLE, extension, rollover, post-trial access). |
| `maintenance` | Long-term safety / observational / surveillance / natural-history / registry. |
| `pk_or_phase1_support` | PK subtrial, healthy-volunteer Phase-1, food-effect, DDI, bioavailability, QT. |
| `post_approval` | Post-marketing / Phase-4 / approved-product-only context. |
| `ambiguous` | Multiple same-date matches with mixed classifications, or insufficient title signal. |
| `invalid_status` | Status hard-rejected (subsumes Lane 1; if Lane 1 is shipped first, this label still emits for traceability). |

Also emit `catalyst_quality_reason` (string) — comma-joined list of the rule labels that fired (matches the audit's `verdict_reasons` format).

### 5.2 Classification rules (deterministic, ordered)

Apply in order; the first match wins.

1. **`invalid_status`** — `status` ∈ Lane 1 reject set.
2. **`registry_only`** — `study_type == "EXPANDED_ACCESS"`, OR title matches `\b(open[\s-]?label\s+extension|long[\s-]?term\s+(safety|extension)|\bOLE\b|extension\s+(study|trial)|rollover\s+study|expanded\s+access|post[\s-]?trial\s+access|compassionate\s+use|managed\s+access|early\s+access)\b` (case-insensitive).
3. **`maintenance`** — `study_type == "OBSERVATIONAL"`, OR title matches `\b(registry|natural\s+history|surveillance|real[\s-]?world|non[\s-]?interventional)\b`.
4. **`post_approval`** — title matches `\b(post[\s-]?marketing|post[\s-]?approval|phase\s*4|phase\s*IV)\b`. (Independent of whether the parent ticker has approval; the trial title is the gate.)
5. **`pk_or_phase1_support`** — title matches `\b(pharmacokinetic|\bPK\b|healthy\s+(subjects|volunteers)|bioavailability|food[\s-]?effect|drug[\s-]?drug\s+interaction|\bDDI\b|\bQT\b)\b`, OR (`phase == "PHASE1"` AND title matches `\b(healthy|food[\s-]?effect|PK)\b`).
6. **Cross-ticker post-approval downgrade** — if classification is still unset AND the parent ticker has `development_stage == "approved"` or `archetype` ∈ {`commercial_biotech`, `commercial_pharma`} AND the matched trial is `OPEN_LABEL` / extension / PK / observational by any of rules 2–5, downgrade to `post_approval`. (This is the KALV pattern made explicit.)
7. **`ambiguous`** — multiple same-date trials match the catalyst date with conflicting classifications (e.g., one `binary_alpha` and one `maintenance`), OR `phase` ∈ {`""`, `"N/A"`} AND `study_type == "INTERVENTIONAL"` and no other rule fired.
8. **`binary_alpha`** — fall-through. Trial is interventional, has a non-rejected status, and is not flagged by any downgrade rule. Phases 2 and 3 with active/not-recruiting/recruiting/completed status are the dominant population here.

The exact regex set lives in the production code; the audit tool's regex set in `tools/audit_false_clinical_catalyst.py` is the seed and must be ported, not duplicated, when Lane 2 ships.

### 5.3 Output behavior

For each CT.gov-derived event:

- **Always preserve:** `catalyst_date`, `nct_id` match list, raw trial title, raw status. These remain visible in `rankings.csv` and dossiers as context.
- **Always emit:** `catalyst_quality`, `catalyst_quality_reason`.
- **If `catalyst_quality != "binary_alpha"`:**
  - Do **not** assign `catalyst_bucket ∈ {binary_now, build_window}`. Instead set `catalyst_bucket_for_rank = "registry_only"` (new sentinel value) or `"none"` if there is no other catalyst source for this ticker.
  - Do **not** apply the catalyst tilt (`catalyst_tilt_mult`, `catalyst_type_mult`).
  - Do **not** allow this event to count toward `tier_dev_reason = high_opt+catalyst_near`.
- **If `catalyst_quality == "ambiguous"`:** treat as non-`binary_alpha` for tier-uplift purposes; surface in dossier with explicit `_review` tag for manual triage.

### 5.4 Risk profile

Alpha-affecting. Removing tier uplift on the 10 Lane-2-only false catalysts will materially shift `tier_dev` labels and likely change top-60 composition. Per `policy_alpha_freeze_2026_04_04.md`, this requires Checklist v2 — FM (full model fit), bootstrap stability, FDR-corrected p-values, LOSO out-of-fold, and year-stability — before any production promotion.

## 6. PIT / governance constraints

Both lanes:
- No historical regeneration of prior snapshots.
- No backfill of `catalyst_quality` into `data/snapshots/<past>/`.
- Run Lane 1 / Lane 2 against the current snapshot first; emit a before/after diff artifact; do not auto-overwrite production rankings.
- Lane 2 specifically: do not promote to production until the validation report (§ 8) is reviewed and signed off, and Checklist v2 results are recorded under `artifacts/checklist_v2/spec_071_lane2_*`.

## 7. Acceptance tests

New tests under `tests/test_catalyst_quality_gate.py`. All tests use real trial records from `production_data/trial_records.json` referenced by NCT id (no synthetic fixtures for the regression cases — the bug is in real data).

| Test | Expected |
|---|---|
| `test_kalv_ole_pk_downgrade` | KALV's `NCT05505916` and `NCT05511922` → `catalyst_quality ∈ {registry_only, pk_or_phase1_support}`. KALV row has no `binary_now`/`build_window` from CT.gov in the post-Lane-2 output. KALV `tier_dev_reason` no longer contains `catalyst_near`. |
| `test_jazz_withdrawn_invalid_status` | JAZZ's `NCT06217536` (WITHDRAWN P1) → `invalid_status`. JAZZ catalyst credit removed (Lane 1). |
| `test_fate_withdrawn` | FATE's `NCT05934097` (WITHDRAWN P1) → `invalid_status`. |
| `test_nvax_withdrawn` | NVAX's `NCT06482359` (WITHDRAWN P2) → `invalid_status`. |
| `test_ibrx_withdrawn` | IBRX's `NCT05007769` (WITHDRAWN P2) → `invalid_status`. |
| `test_eldn_withdrawn` | ELDN's `NCT04711226` (WITHDRAWN P2) → `invalid_status`. |
| `test_ptgx_healthy_volunteer_p1_pk` | PTGX's `NCT07153146` (P1 healthy subjects PK) → `pk_or_phase1_support`. PTGX row has no CT.gov-driven `binary_now`/`build_window` after Lane 2. |
| `test_dna_mixed_same_date_ambiguous` | DNA's six 2026-05-01 matches → aggregate `ambiguous`. No tier uplift unless an explicit `binary_alpha` match exists. |
| `test_known_valid_p3_efficacy_remains_binary_alpha` | A pinned valid case (e.g., `RVMD` `NCT06040541` P3 active) → `binary_alpha`, retains `binary_now`/`build_window` credit. |
| `test_catalyst_date_preserved_when_downgraded` | For every downgraded row above, `catalyst_date` and `nct_id` remain populated; only the bucket/tier/tilt fields change. |
| `test_lane1_subset_of_lane2` | Every row Lane 1 rejects also gets `catalyst_quality == "invalid_status"` from Lane 2. |

## 8. Validation report

Before merge of either lane, produce a read-only diff artifact at:

- `artifacts/audit/spec_071_lane{1,2}_diff_<snapshot_date>.md`
- `artifacts/audit/spec_071_lane{1,2}_diff_<snapshot_date>.json`

Each report contains:

1. **Coverage:** number of CT.gov catalysts before / after, downgrade counts by `catalyst_quality` bucket.
2. **Per-ticker delta** for the 15 + 1 audit-flagged tickers (KALV, JAZZ, FATE, NVAX, IBRX, ELDN, PTGX, SION, CLYM, GHRS, BEAM, BMEA, DNA, plus any Lane-1-only cases): old vs new `catalyst_bucket`, `tier_any`, `tier_dev`, `actionable_rank`.
3. **Top-60 entrants and exits** vs current production `rankings.csv`.
4. **Spearman ρ** of `actionable_rank` before vs after, and Top-30 / Top-60 overlap %.
5. **Negative controls:** at least three `binary_alpha` Phase-3 trials whose tier uplift must be unchanged (e.g., `RVMD`, `NRIX`, `ORIC` from the audit's "likely valid" top-20).
6. **Material-change check:** if Top-30 overlap < 90% or Spearman ρ < 0.95 on Lane 2, halt promotion and escalate.
7. **Production rankings.csv must not be overwritten** by the validation run. The artifact is for review only.

## 9. Sequencing

1. Implement **Lane 1** as a narrow defect fix. PR title: `fix(catalyst): hard-reject CT.gov catalyst credit for withdrawn / approved-for-marketing statuses (spec 071 lane 1)`. Include the Lane-1 portion of the acceptance tests. Run § 8 validation report. Merge if Top-60 churn is bounded and audit-flagged Lane-1 cases lose credit.
2. **Re-run** `tools/audit_false_clinical_catalyst.py` against the post-Lane-1 snapshot. Confirm the 5 status cases drop out of the false-catalyst list. Update Lane 2 evidence accordingly.
3. Open a separate spec-071-lane-2 PR. Run Checklist v2. Produce the § 8 report. Promote only after sign-off.

---

**Lane 1 is a data-quality defect fix. Lane 2 is an alpha-affecting catalyst-classifier change and requires promotion discipline.**

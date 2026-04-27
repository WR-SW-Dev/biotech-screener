# Spec 068 — Development Stage External Cache Audit (2026-04-27)

**Status:** Spec only. **No production code changes from this document.**
**Author:** drafted 2026-04-27 in response to a proposal to build a recurring external `development_stage` validator.
**Constraint:** alpha-stack is frozen per `policy_alpha_freeze_2026_04_04.md`. Architecture is frozen per `policy_freeze_architecture_2026_04_19.md`. Pause policy `policy_pause_until_2026_04_28_verification.md` blocks any new diagnostic or wrapper until the 2026-04-28 verification gate clears.

## 0. Why this spec exists

A proposal landed to build `tools/validate_development_stage_external.py` — a recurring external validator that re-fetches ClinicalTrials.gov, SEC EDGAR, openFDA, Orange Book, and Purple Book per snapshot to validate the `development_stage` column. The proposal is correct that stage validation is worth doing, but the framing has three problems:

1. The pause policy explicitly blocks new diagnostics until 2026-04-28.
2. The repo already pulls CT.gov, SEC, Purple Book, and Drug Approval data on cron — a fresh fetcher would duplicate pipes and double rate-limit pressure on already-strained services.
3. The hard problem is **ticker-to-program alias resolution**. A recurring validator without alias confidence will flood operators with ARGX/REGN/VRTX-style multi-program ambiguity on every run.

This spec replaces that proposal with a **one-shot cache-only audit** that quantifies the actual stage-error rate before any framework is built. The audit answers "do we need a validator?" before designing one.

## 1. Scope and gates

- **One-shot audit only.** Not recurring. Not a cron job. Not a behind-flag deployment.
- **Cache-only.** No live API calls to CT.gov, SEC, openFDA, Orange Book, Purple Book, or company sites.
- **Read-only.** No mutation of `rankings.csv`, `universe.json`, scoring, ranker, selector, eligibility, or decision logic.
- **Implementation gate:** must wait for the 2026-04-28 verification one-shot to pass (`tools/cron_one_shot_2026_04_28.sh`). No code merges from this spec until that gate is green.
- **No production code changes from this document.** Implementation requires a separate change with its own review.

## 2. Inputs (existing local caches only)

```
data/snapshots/{as_of_date}/rankings.csv          # internal_development_stage source
production_data/universe.json                     # ticker → company / aliases
production_data/drug_name_map.json                # ~300 tickers, drug → company
cache/ctgov/trial_records_{as_of_date}.json       # ~19k trials, refreshed daily by ctgov_poller
cache/sec/8k_catalysts/                           # 8K event extractions (~387 today)
production_data/pit_financials/                   # EDGAR fact stores, 339 tickers
cache/fda/                                        # adcom_calendar, fda_regulatory
production_data/pdufa_dates_extracted.json        # 29 upcoming PDUFA actions
data/press_releases/classified/                   # if present, classified IR releases
artifacts/regulatory/                             # PDUFA diff artifacts
```

If a Purple Book or Orange Book cache exists locally (per the Mon 13:00 Purple Book cron), include it. If not, the audit notes "approved evidence: cache absent" rather than triggering a fetch.

**Explicit no-go:**
- No `requests.get` to CT.gov, SEC, openFDA, Drugs@FDA, Orange Book, Purple Book, or any company site.
- No new cron job, no scheduled trigger, no MCP connector.

## 3. Outputs

```
artifacts/development_stage/stage_cache_audit_{as_of_date}.csv
artifacts/development_stage/stage_cache_audit_{as_of_date}.md
artifacts/development_stage/stage_cache_audit_{as_of_date}.json
```

Markdown is the operator-facing summary (counts by status, top-30 impacts, multi-program callouts). JSON is the machine-readable digest. CSV is the per-ticker detail.

## 4. CSV schema

```
ticker
company_name
internal_development_stage
development_stage_source
lead_program_phase_raw
archetype
tier_commercial
ctgov_max_phase
ctgov_active_trial_count
ctgov_sponsor_match_type        # exact | alias | collaborator | normalized | fuzzy | none
ctgov_alias_confidence          # HIGH | MED | LOW | NONE
sec_detected_stage              # from 8K text scan + pit_financials disclosures
fda_or_purplebook_approved_evidence   # bool + source list
external_consensus_stage
validation_status
confidence                      # HIGH | MED | LOW
likely_action                   # validated | manual_review | alias_audit | no_action
notes
```

The `notes` column carries free-text caveats: e.g. "lead asset partnered with X — sponsor on CT.gov is partner CIK", "platform diagnostics — CT.gov not applicable".

## 5. Stage inference policy

Conservative hierarchy. External evidence layers each contribute one stage signal; the audit emits the **lowest confident stage** that is consistent with all available evidence.

```
commercial
  internal archetype/tier_commercial == commercial
  AND (FDA approval evidence + ownership/marketer match in SEC text)
  OR  pit_financials shows material product revenue line

approved
  FDA approval exists but commercial ownership/marketer is unclear

nda_bla
  SEC 8K or pit_financials disclosure shows NDA/BLA submitted/accepted/under review/PDUFA assigned

phase_3
  active or recent (≤24 months) interventional CT.gov record with PHASE3 status
  OR SEC text contains "Phase 3" / "pivotal" with HIGH-confidence sponsor match

phase_2_3
  CT.gov shows both PHASE2 and PHASE3 active
  OR SEC text says "Phase 2/3"

phase_2 / phase_1_2 / phase_1
  same logic, descending phase

preclinical
  ONLY from SEC text or company-disclosed pipeline. CT.gov registration generally requires human studies.

unknown
  no reliable external evidence and ambiguous internal signal
```

**Phase 4 does not imply commercial.** Phase 4 confirms post-marketing clinical activity but commercial status requires FDA approval AND ownership/marketer/revenue evidence. This is the most common false-positive pattern in naive validators and the audit must guard against it.

## 6. Alias and confidence policy

Ticker-to-sponsor mapping is the hardest part. The audit follows three confidence tiers:

- **HIGH** — exact company-name match against CT.gov sponsor or known subsidiary in `universe.json`/`drug_name_map.json` aliases.
- **MED** — normalized company-name match (lowercase, whitespace-collapse, "Inc"/"Corp"/"Therapeutics" suffix-stripped) AND no other ticker in the universe matches the same normalized form.
- **LOW** — fuzzy match (token-set ratio ≥ threshold, e.g. 85) OR collaborator-only match.

**Hard rule:** a LOW-confidence sponsor match cannot escalate `validation_status` past `validated` or `no_external_evidence`. It cannot mark a ticker as `likely_internal_stale`. LOW evidence appears in the CSV but does not drive the operator-facing action column.

Multi-program companies (≥2 active programs at distinct stages with HIGH-confidence sponsor match) are summarized as `ambiguous_multi_program` and reported separately, not as failures.

## 7. Validation status enum

```
validated                       — internal stage matches external consensus
likely_internal_stale           — external HIGH-confidence shows a later stage
external_lower_than_internal    — external evidence is earlier; may be incomplete
ambiguous_multi_program         — multiple HIGH-confidence stages active
sponsor_alias_uncertain         — only LOW/MED alias matches available
platform_not_ctgov_applicable   — archetype is platform/diagnostics; CT.gov absence expected
no_external_evidence            — no usable evidence; keep internal stage, flag for manual review
```

The audit does **not** auto-correct. Every status is informational; only the markdown summary calls out names operators should review.

## 8. Primary questions the audit must answer

1. How many tickers have `internal_stage != external_consensus_stage`?
2. Of those, how many are HIGH-confidence mismatches?
3. How many are `ambiguous_multi_program` false positives masquerading as mismatches?
4. How many of the affected names appear in today's top-30 or top-60 by selector_score?
5. Does any mismatch change `financial_score` cohort assignment (recall: rank-normed within stage×size)?
6. Are mismatches concentrated in platform/commercial archetypes (CT.gov gap is structural) or in drug developers (CT.gov should cover them)?
7. Is recurring validation warranted, or are manual fixes to `universe.json` cheaper?

## 9. Decision rule after audit

- **≤5 HIGH-confidence material mismatches AND no top-30 impact:** fix manually in `universe.json` / source data. No validator framework. Close the lane.
- **Repeated systematic mismatch pattern across snapshots** (e.g. consistent late-stage promotions missed): scope a recurring cache-based validator in a separate spec. The validator must reuse existing caches — no new fetchers.
- **Alias ambiguity dominates the error surface:** build a ticker-sponsor alias map (separate spec) before any validator. Without alias confidence the validator is structurally noisy.

The audit must explicitly recommend one of these three branches, not punt. A "needs more data" recommendation is a failure of the audit and means the inputs were insufficient.

## 10. Non-goals

- **No auto-correction.** No mutation of `development_stage`, `lead_program_phase_raw`, `archetype`, or `tier_commercial` in any output the production pipeline reads.
- **No mutation of `rankings.csv`.**
- **No mutation of `universe.json`.** Manual fixes to `universe.json` after the audit are a human action, not the audit's output.
- **No scoring, ranker, selector, eligibility, or decision changes.** Even if the audit finds errors, code that consumes `development_stage` is unchanged.
- **No recurring cron.** This spec is a one-shot.
- **No external API fetches.** Cache-only.
- **No alpha lane.** Per `policy_alpha_freeze_2026_04_04.md`, even a behind-flag deployment that adds a new column to `rankings.csv` would require Checklist v2. This audit emits to `artifacts/development_stage/` only.

## 11. Pre-implementation gates

Before any code is written from this spec:

1. **2026-04-28 verification gate** must pass. Confirmed via `logs/one_shot.log` entry from `tools/cron_one_shot_2026_04_28.sh`.
2. **Pause policy lifted** — once verification passes, the pause policy is intended to release. Confirm explicitly with the user before merging audit code.
3. **Alias map sanity check** — before running the audit, manually spot-check 10 random ticker → sponsor mappings against `universe.json` and `drug_name_map.json`. If alias quality is materially worse than expected, the audit's `sponsor_alias_uncertain` bucket will dominate and the audit's signal will be noise. In that case, build the alias map first.

## 12. Implementation envelope (when gates clear)

- Single Python file: `tools/audit_development_stage_external.py`. Estimated ~150-300 lines.
- Reads: the inputs in §2.
- Writes: the outputs in §3, atomically (write to `.tmp`, rename).
- Runtime budget: ≤60s on the full universe. If it can't fit in 60s using cache-only inputs, the design is wrong.
- No dependencies beyond what's already in `requirements.txt`.
- One-shot CLI: `python tools/audit_development_stage_external.py --as-of-date YYYY-MM-DD`. Idempotent.

A test under `tests/test_audit_development_stage.py` covering:
- Phase-3 ticker validated by CT.gov HIGH-confidence sponsor match
- Commercial ticker validated by FDA/Orange/Purple Book evidence + revenue line
- Preclinical-only-from-SEC-text ticker (no CT.gov record)
- Multi-program ticker emits `ambiguous_multi_program`, not `likely_internal_stale`
- Platform/diagnostics ticker emits `platform_not_ctgov_applicable`, not `no_external_evidence`
- LOW-confidence alias cannot escalate past `validated`

## 13. Open questions

These need explicit answers before §12 is written:

- **What does `development_stage` actually drive downstream?** If it's only cohort assignment for `financial_score`, the blast radius is narrow and a manual fix in `universe.json` is likely sufficient. If it gates eligibility or appears in operator-facing dashboards, the picture changes. Confirm with a quick `grep -rn "development_stage" common/ tools/ scripts/ event_ev/` before audit design.
- **What's the policy on stale stages found?** Auto-flag in `production_qa_check.py` (already running daily)? Manual quarterly review? Owner-assigned per name? This choice changes whether the audit's output is monitor-only or actionable.
- **Purple Book / Orange Book cache freshness.** Purple Book refreshes weekly (Mon 13:00); Orange Book is not currently on cron. If Orange Book data is stale or missing, the audit notes "approved evidence: small-molecule confirmation unavailable" rather than fetching.

## 14. References

- `MEMORY.md` index entries: `policy_pause_until_2026_04_28_verification.md`, `policy_alpha_freeze_2026_04_04.md`, `policy_freeze_architecture_2026_04_19.md`, `feedback_quarantine_blast_radius_diff.md`
- Existing data plumbing: `tools/run_daily_production.py` (snapshot writer), `agents/ctgov_poller/`, `tools/fetch_company_press_releases.py`, `tools/cron_data_extras.sh`
- Adjacent specs: `spec_065_form4_stable_snapshot_gate.md` (data-integrity gate pattern), `spec_066_v2_cohort_hysteresis.md` (alpha-affecting change requires Checklist v2 — note that this spec is *not* alpha-affecting and therefore does not need Checklist v2)

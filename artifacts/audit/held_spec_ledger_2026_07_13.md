# Held-Spec Ledger — 2026-07-13

Generated: 2026-07-13T12:50:00Z (cron, hermes-held-spec-ledger)
Prior ledger: artifacts/audit/held_spec_ledger_2026_07_09.md
Evidence window checked: 2026-07-09 → 2026-07-13 (commits, gate_verdict_ledger, scorecards, EES v3 status, spec files)

## Overall readiness snapshot (as of latest gate print, 2026-07-10)
- Weekly scorecard verdict (2026-07-10): **HOLD** — blocking check `bucket_drift_vs_policy` FAIL (31.67pp; 91-180d bucket Δ31.7pp vs policy). Same fail mode as 07-09 (28.33pp) — degrading, not improving.
- phase2_health: WARN (overbought_rsi_exposure) — unchanged since 07-09.
- Gate verdict ledger (2026-07-10): 33 PASS / 5 WARN (pnl_attribution, portfolio_weights, ruleset_health, source_freshness, regulatory_calendar) / 0 FAIL. overall_status=WARN.
- No scorecard artifact found for 2026-07-11, 07-12, or 07-13 — **scorecard production gap of 3 days**, confirmed by `find` returning zero results. Flag: NEEDS_OPERATOR_DECISION whether this is scheduler failure or scorecard job disabled; not yet diagnosed this run.
- forward_eval_ic_baseline.json content returned by tool is a **stale Path C window (2026-05-27–2026-06-03)** with only 1 observation, `path_c_status: ACTIVE`, `ic_observability_at_close: IC_UNOBSERVABLE_EXPECTED`. This does NOT reflect the 07-09/07-10 gate ledger's `forward_eval: PASS` — the two sources disagree on freshness. Treat forward_eval IC state as **UNVERIFIED/STALE** pending a current print; do not assume PASS = healthy IC without an up-to-date observation.

---

## 1. ACTIONABLE BLOCKERS

| Item | Trigger | Status | Action required |
|---|---|---|---|
| H20D 55-manager cohort re-evaluation gate | Was due 2026-07-01; now **12 days overdue** as of 2026-07-13 | NOT CLEARED. No `H20D_JACCARD_FINAL_*.md` or newer verdict memo found since 2026-07-04. Last real Jaccard = 0.463 (floor 0.40 — not breached; target 0.70 — not met). | Local operator must run `tools/check_13f_cohort_quarantine.py --pre-date <last pre-Q1 snapshot> --post-date <first post-Q1 snapshot>`. No evidence this has been executed in the 07-09→07-13 window. |
| Scorecard production gap | Missing 2026-07-11 / 07-12 / 07-13 scorecards | UNCONFIRMED CAUSE | Determine scheduler vs. agent failure before assuming HOLD verdict still applies unchanged. Do NOT assume 07-10 HOLD carries forward silently — re-run scorecard ASAP. |
| bucket_drift_vs_policy FAIL trend | 28.33pp (07-09) → 31.67pp (07-10), worsening | ACTIVE FAIL, blocking trade | Portfolio/policy review of 91-180d bucket allocation vs. target (55% target, 23.3–26.7% actual). |
| EES v3 raw_veto_core shadow — 20d gate MET | Gate met 2026-06-25; still FREEZE_ACTIVE as of 2026-07-12 | NEEDS_OPERATOR_DECISION | Freeze-lift review memo exists (2026-06-25). Production promotion explicitly `NOT_AUTHORIZED — pending... operator approval`. No promotion decision found in commits 07-09→07-12. This is now ~18 days sitting at MET-but-unpromoted; recommend explicit operator ruling (approve/hold/reject). |

---

## 2. HELD BRANCHES

### Spec 087 B1b — first-fire validation
- Status: **CLOSED** (per prior ledger — formal closure memo `spec_087_b1b_formal_closure_2026_05_14.md` exists). No new evidence this window changes this.
- Last evidence: `artifacts/audit/spec_087_b1b_formal_closure_2026_05_14.md` (2026-05-14)
- Blocker: none
- Next allowed action: none (closed)
- Not allowed: reopening without new operator directive
- Runtime risk: NONE
- Alert condition: n/a

### Spec 087 B2 — dashboard freshness envelope
- Status: HELD (per prior ledger; blocked on B1b, which is now closed) → **NEEDS_OPERATOR_DECISION** on whether B1b closure unblocks B2 formally
- Last evidence: `specs/changes/spec_087_b2_dashboard_freshness_envelope.md` (unchanged this window)
- Blocker: No commit/audit memo found in 07-09→07-13 window confirming B2 activation despite B1b closure
- Next allowed action: operator review to confirm B1b→B2 unblock and authorize spec transition to ACTIVE
- Not allowed: silent promotion to ACTIVE without a fresh audit memo
- Runtime risk: LOW
- Alert condition: any commit modifying dashboard freshness logic without a corresponding spec-status update

### Spec 087C — bioshort alpha research
- Status: HELD (needs ≥4 fresh weekly reports per standing description)
- Last evidence: `spec_087c_phase_b_disposition_2026_05_14.md` (2026-05-14) — no newer evidence found
- Blocker: weekly report accumulation; no new reports found this window
- Next allowed action: continue accumulation; re-check report count next cycle
- Not allowed: production activation
- Runtime risk: NONE
- Alert condition: 4th fresh weekly report landing — triggers re-evaluation

### bioshort_watch LLM reactivation
- Status: HELD — **suppressed since 2026-05-06**, per AGENT_REGISTRY.json (confirmed current this run: status=`suppressed`, `merged_into: build_bioshort_watch`, sunset_review_date 2026-09-30)
- Last evidence: AGENT_REGISTRY.json (as_of 2026-06-26, re-verified 2026-07-13)
- Blocker: reactivation requires operator decision + separate spec (explicitly stated in registry notes)
- Next allowed action: none — no next action defined; awaiting sunset review 2026-09-30
- Not allowed: any autonomous reactivation
- Runtime risk: NONE
- Alert condition: sunset review date approaching (still >2.5 months out)

### Spec 088 Phase B — catalyst_delta filtered artifacts
- Status: HELD — blocked on Spec 087 close
- Last evidence: `specs/changes/spec_088_phase_a_catalyst_delta_filter_design_2026_05_07.md`; catalyst_delta agent notes confirm "Artifact-level filtering deferred to a separate explicit change" (AGENT_REGISTRY.json, unchanged this window)
- Blocker: Spec 087 (bioshort producer restoration / B1b/B2 chain) full closure — B1b is closed but B2 status is itself NEEDS_OPERATOR_DECISION (see above), so 088 remains blocked transitively
- Next allowed action: none until 087 chain fully resolved
- Not allowed: any artifact-level filtering change to catalyst_delta production tool
- Runtime risk: LOW
- Alert condition: any commit touching `tools/build_catalyst_delta.py` filtering logic

### watchlist_current.json disposition
- Status: **NEEDS_OPERATOR_DECISION** (unchanged) — confirmed again this run: file does not exist anywhere in repo (`find . -iname "watchlist_current.json"` → 0 matches)
- Last evidence: negative search result, 2026-07-13
- Blocker: unclear whether this is a removed/renamed artifact or a broken reference in older docs/specs
- Next allowed action: operator to confirm whether references to this file are stale and should be scrubbed from docs, or whether the file needs to be regenerated
- Not allowed: fabricating or regenerating the file without operator direction
- Runtime risk: LOW
- Alert condition: any code path that reads this path at runtime and fails silently

### score_rank_pct SPEC_REQUIRED
- Status: HELD — Day 3+ streak per standing description; **UNKNOWN/UNVERIFIED** IC status persists
- Last evidence: last known good IC print +0.0432 HEALTHY dated 2026-06-24 (per prior ledger); no newer verified print found. The `forward_eval_ic_baseline.json` artifact returned this run is a stale Path C window (2026-05-27–2026-06-03), NOT a current score_rank_pct observation.
- Blocker: CRT + IC + PIT + Checklist v2 all required before any weight change; none evidenced this window
- Next allowed action: operator/agent to produce a fresh, dated IC print against current ruleset (`8887576e`) before any further disposition
- Not allowed: any scoring/ranking/weight change without full CRT+IC+PIT+Checklist v2 evidence chain
- Runtime risk: MEDIUM (stale IC visibility across an active production ruleset)
- Alert condition: any commit touching `score_rank_pct` logic without the full evidence chain attached

### EES v3 veto_monitor (raw_veto_core) — production promotion decision
- Status: HELD (shadow) — gate MET 2026-06-25, still FREEZE_ACTIVE/DIAGNOSTIC_ONLY as of 2026-07-12
- Last evidence: `artifacts/readiness/EES_V3_RAW_VETO_SHADOW_STATUS_2026_07_12.md` — 20d obs 45/20 (MET), cumulative 20d alpha+ rate 85.7%, mean veto alpha +8.2% (20d)
- Blocker: explicit operator approval for production promotion; none found in commits or memos this window
- Next allowed action: operator reviews freeze-lift review memo (2026-06-25) + current shadow status and issues explicit promote/hold/reject ruling
- Not allowed: any change to `mutation_authority` or enabling production decisioning without operator sign-off
- Runtime risk: LOW (diagnostic-only, no portfolio action per governance block)
- Alert condition: any commit that flips `production_decisioning` to true or removes FREEZE_ACTIVE without an operator-attributed commit message

### Spec 113 — construction signal PIT snapshots
- Status: HELD — **DRAFT**, unchanged
- Last evidence: `specs/changes/spec_113_construction_signal_pit_snapshots_2026_07_05.md` — re-confirmed this run, still reads "Status: DRAFT — SPEC / MEMO ONLY... Requires explicit operator approval to move DRAFT -> IN PROGRESS."
- Blocker: operator approval to move to IN PROGRESS
- Next allowed action: none until approval
- Not allowed: any implementation commits against this spec
- Runtime risk: NONE
- Alert condition: any commit referencing spec_113 implementation without a preceding approval record

### Q1 2026 13F cohort — quarantine (decision_grade=false)
- Status: HELD — ratified observation-only (PR #429/#462), quarantine not lifted
- Last evidence: no new artifacts found (`find` for Q1 2026 13F artifacts newer than 07-09 ledger → empty)
- Blocker: same as H20D gate above — deferred quarantine script never run against post-promotion snapshot
- Next allowed action: tied to H20D actionable blocker above
- Not allowed: treating Q1 13F as decision-grade for alpha/ranker/selector consumption
- Runtime risk: MEDIUM (now 12 days overdue on the gate that would resolve this)
- Alert condition: any commit consuming Q1 13F signal outside observation/attribution scope

---

## 3. RECENTLY CLOSED (since 2026-07-09 ledger)

| Item | Closure evidence | Date |
|---|---|---|
| forward_eval gate WARN→PASS (gate_verdict_ledger) | commit `892b2672` "fix(forward_eval): scope IC to tradeable set + de-overlap window (#487)" | 2026-07-08, reflected in 07-09/07-10 gate prints |
| mypy CI job | commit `b12addd0` "fix(mypy): green the type-check CI job (63→0 errors) — #485 (#488)" | 2026-07-09 |
| Cron checkout-drift guard | commit `b79d1940` "fix(cron): warn when production checkout drifts behind origin/main" | 2026-07-08 |
| Forward-validation feed hardening (PR #489) | commits `d18a53d7`, `c1b84136`, `faa354f0`, `e30fc5b4`, `5f7d9f2c`, `3ee7f7dc` | 2026-07-09 to 2026-07-12 |
| Price-feed silent-failure repair | commit `2b8fb350` "fix(prices): repair silent price-feed failure + add hard-gate append canary" | 2026-07-09 |

None of these closures touch scoring/ranking/selector logic per commit messages reviewed; all are infrastructure/monitoring/CI fixes.

---

## 4. UNCOMMITTED WORKING TREE

| Path | Type | Disposition |
|---|---|---|
| `.learnings/corrections.md` | Modified | Routine learnings log — low risk, awaiting normal commit cadence |
| `artifacts/audit/cross_signal_forward_shadow/buckets.jsonl` | Modified | Shadow artifact, no production impact — flag only |
| `artifacts/audit/inst_delta_forward_shadow/checkpoints.jsonl` | Modified | Shadow artifact — flag only |
| `artifacts/forward_validation/fills.jsonl` | Modified | Active forward-validation data, consistent with PR #489 work in progress |
| `artifacts/governance/hermes_skill_sync/latest_heartbeat.json` | Modified | Routine heartbeat |
| `artifacts/universe_hygiene/xbi_ibb_universe_audit_2026_06_28/*` (5 files, MM = staged+unstaged) | Modified (both staged/unstaged) | **NEEDS_OPERATOR_DECISION** — partial staging on a universe-audit artifact set; recommend explicit review before commit to avoid partial/inconsistent audit state |
| `data/expression_decision_log.jsonl` | Modified | Routine decision log |
| `data/snapshots/resolutions/calibration_summary.json` | Modified | Routine calibration update |
| `production_data/market_data.json`, `options_snapshot_latest.json`, `short_interest.json`, `trial_records.json` | Modified | Routine daily production data refresh |
| `production_data/universe.json` | Modified (MM) | Tied to universe hygiene audit above — same NEEDS_OPERATOR_DECISION flag |
| `tools/check_13f_cohort_quarantine.py` | Modified | **FLAG — HIGH ATTENTION.** This is the exact script required to clear the overdue H20D gate. An uncommitted modification to this script should be reviewed and disclosed before any operator runs it for the pending H20D re-evaluation, to ensure the gate clearing test uses reviewed/committed logic, not an unreviewed working-tree diff. |
| `WEEKLY_SIGNAL_REGIME_SWEEP_2026_07_09.md` | Untracked (new) | Report artifact — pending commit |
| `artifacts/audit/held_spec_ledger_2026_07_09.md` | Untracked (new) | Prior ledger, apparently never committed — recommend committing alongside this one |
| `artifacts/data_quality_audit_2026-07-02.md`, `artifacts/data_quality_note_KYMR_catalyst_misdate_2026-07-02.md` | Untracked | Data quality notes, pending commit |
| `artifacts/governance/hermes_skill_sync/hermes_skill_sync_2026_0{6_26,6_28,6_29,7_05,7_12}.md` | Untracked | Routine skill-sync reports, pending commit |
| `artifacts/governance/selfimprove_audit_2026-06-24.md` | Untracked | Pending commit |
| `production_data/options_snapshot_2026-07-0{1,2,3,6,7,8,9},2026-07-10.json` | Untracked | Daily options snapshots, pending commit (8 days of uncommitted daily data) |

---

## 5. RECOMMENDED NEXT OPERATOR DECISIONS (rank-ordered, max 5)

1. **Run the deferred H20D quarantine script** (`tools/check_13f_cohort_quarantine.py`) against pre/post Q1-promotion snapshots — now 12 days overdue. Review the uncommitted diff to that script FIRST before running it, since the working tree shows it modified.
2. **Diagnose the 3-day scorecard production gap** (07-11/07-12/07-13 missing) — confirm scheduler vs. agent failure before assuming the 07-10 HOLD verdict still holds unchanged.
3. **Rule on EES v3 raw_veto_core production promotion** — 20d gate has been MET since 2026-06-25 (18 days); an explicit approve/hold/reject decision is overdue even though no floor breach exists.
4. **Resolve `bucket_drift_vs_policy` FAIL trend** (28.33pp → 31.67pp, 91-180d bucket) — this is the sole blocking scorecard fail and is worsening.
5. **Clarify `watchlist_current.json` disposition** and confirm whether Spec 087 B2 is now unblocked by B1b's formal closure (currently marked NEEDS_OPERATOR_DECISION in this ledger).

---

*Ledger produced by read-only tooling (run_readonly_diagnostics, gate_verdicts, forward_eval_ic_ledger) plus terminal git/file inspection. No production files were modified. No scoring, ranking, or selector logic was inspected for change — only status/read.*

# Held-Spec Ledger — 2026-07-28

Generated: 2026-07-28T13:11:00Z (cron, hermes-held-spec-ledger)
Prior ledger: artifacts/audit/held_spec_ledger_2026_07_13.md
Evidence window checked: 2026-07-13 → 2026-07-28 (gate_verdict_ledger, scorecards, EES v3 status, git log, AGENT_REGISTRY.json, WEEKLY_SIGNAL_REGIME_SWEEP reports)

## Overall readiness snapshot (as of latest gate print, 2026-07-27)
- Weekly scorecard verdict (2026-07-27): **HOLD** — blocking check `bucket_drift_vs_policy` FAIL (31.67pp; 91-180d bucket Δ31.7pp vs 55% policy target, actual 23.3%). Same magnitude as the 07-10 print in the prior ledger — **not resolved, not worsening, plateaued at the fail level for ~2.5 weeks.**
- phase2_health: WARN (`catalyst_7d_count_high`) — different WARN driver than 07-13's `overbought_rsi_exposure`; treat as a new/rotated warning, not confirmation of the old one clearing.
- Gate verdict ledger (2026-07-27): 36 PASS / 3 WARN (portfolio_weights, regulatory_calendar, ruleset_health) / 0 FAIL. overall_status=WARN. This is an *improvement* over 07-13 (which had a FAIL day on 07-13 itself: hard_options_coverage FAIL, n_fail=1) — gate has been FAIL-free every day 07-17 through 07-27.
- score_rank_pct: **RESOLVED TO HEALTHY, verified fresh.** WEEKLY_SIGNAL_REGIME_SWEEP_2026_07_28.md (untracked, this run) confirms mean_ic=+0.0775, hit rate 84.6%, 39 dates, dashboard health=HEALTHY as of 2026-07-24 dashboard snapshot. This clears the "IC status UNKNOWN/UNVERIFIED" flag standing since the 07-09/07-13 ledgers. **CRT+IC+PIT+Checklist v2 requirement for any weight change is unaffected — still required, no weight change evidenced.**
- forward_eval_ic_baseline.json: still returns the same **stale Path C window (2026-05-27–2026-06-03)** content as prior ledgers, single observation, `path_c_status: ACTIVE`, `IC_UNOBSERVABLE_EXPECTED`. No update in 15 days. Continue treating this specific artifact as stale; gate ledger's `forward_eval: PASS` is the more current signal.
- EES v3 raw_veto_core shadow: **20d gate remains MET** (met 2026-06-25), status **unchanged at FREEZE_ACTIVE/DIAGNOSTIC_ONLY** as of the latest status memo (2026-07-23, no newer EES_V3_RAW_VETO_SHADOW_STATUS_*.md found — 5 days without a fresh status print, vs. near-daily cadence 07-01 through 07-23). Cumulative 20d alpha+ rate now 88.5% (up from 85.7% on 07-12), mean 20d veto alpha +7.9%. **Now ~33 days sitting MET-but-unpromoted** with no operator ruling found in commits or memos.
- git log 07-13→07-28: two governance-relevant commits found — `246349bd9` (h20d gate cleared) and `f9b5ad76b` (stale ledger-entry cleanup). Both detailed below; both are the two items the 07-13 ledger flagged as top-priority overdue blockers.

---

## 1. ACTIONABLE BLOCKERS

| Item | Trigger | Status | Action required |
|---|---|---|---|
| EES v3 raw_veto_core production promotion | Gate MET since 2026-06-25 (33 days); shadow status stale since 2026-07-23 (5 days no refresh) | NEEDS_OPERATOR_DECISION — unchanged from 07-13, now longer overdue | Operator must issue explicit promote/hold/reject ruling. Also confirm why EES_V3_RAW_VETO_SHADOW_STATUS has not printed since 07-23 (cadence break vs. near-daily prior pattern) — scheduler vs. agent issue, not yet diagnosed. |
| bucket_drift_vs_policy FAIL | Plateaued at ~31.7pp (91-180d bucket) since 07-10, still FAIL on 07-27 | ACTIVE FAIL, blocking trade (verdict=HOLD) | Portfolio/policy review of 91-180d bucket allocation vs. 55% target (actual 23.3%). No remediation evidenced in this window. |
| Spec 087 B2 dashboard freshness envelope disposition | B1b closed since 2026-05-14; B2 status left as NEEDS_OPERATOR_DECISION in prior ledger | **STILL UNRESOLVED** — no commit or audit memo found 07-13→07-28 confirming B1b→B2 unblock | Operator to confirm formally whether B2 is now ACTIVE, and if so, authorize the spec-status transition in writing. |

---

## 2. HELD BRANCHES

### Spec 087 B1b — first-fire validation
- Status: **CLOSED** (unchanged; formal closure memo `spec_087_b1b_formal_closure_2026_05_14.md`)
- Last evidence: `artifacts/audit/spec_087_b1b_formal_closure_2026_05_14.md` (2026-05-14)
- Blocker: none
- Next allowed action: none (closed)
- Not allowed: reopening without new operator directive
- Runtime risk: NONE
- Alert condition: n/a

### Spec 087 B2 — dashboard freshness envelope
- Status: **NEEDS_OPERATOR_DECISION** (unchanged from 07-13 — no new evidence closes this)
- Last evidence: `specs/changes/spec_087_b2_dashboard_freshness_envelope.md` (unchanged); no commit found in 07-13→07-28 window referencing B2 activation
- Blocker: no explicit operator ruling confirming B1b closure unblocks B2
- Next allowed action: operator review to confirm unblock and authorize spec transition to ACTIVE
- Not allowed: silent promotion to ACTIVE without a fresh audit memo
- Runtime risk: LOW
- Alert condition: any commit modifying dashboard freshness logic without a corresponding spec-status update

### Spec 087C — bioshort alpha research
- Status: HELD (needs ≥4 fresh weekly reports per standing description)
- Last evidence: `spec_087c_phase_b_disposition_2026_05_14.md` (2026-05-14) — no newer evidence found
- Blocker: weekly report accumulation; no new closure evidence found this window
- Next allowed action: continue accumulation; re-check report count next cycle
- Not allowed: production activation
- Runtime risk: NONE
- Alert condition: 4th fresh weekly report landing — triggers re-evaluation

### bioshort_watch LLM reactivation
- Status: **CLOSED / SUPERSEDED** — no longer a standing HELD item. AGENT_REGISTRY.json confirms `bioshort_watch` status=`active`, reactivated 2026-07-18 by explicit operator decision (separate written spec waived by operator), migrated to real Hermes cron job (ID `9b7546acf514`, Sat 18:13 ET). Commit `f9b5ad76b` (2026-07-18) formally cleared the stale ledger entry that had incorrectly shown this as still HELD_SUPPRESSED two months after resolution.
- Last evidence: `f9b5ad76b` (2026-07-18) + AGENT_REGISTRY.json (re-verified 2026-07-28)
- Blocker: none — resolved
- Next allowed action: monitor cadence (registry notes cadence "irregular, gaps up to ~24 days" — informational, not a gate)
- Not allowed: n/a
- Runtime risk: LOW (observe_only, read-only agent; no producer-script execution or write authority per registry)
- Alert condition: sunset review date 2026-09-30 approaching, or cron gap exceeding ~24 days

### Spec 088 Phase B — catalyst_delta filtered artifacts
- Status: HELD — blocked on Spec 087 close (transitively, via unresolved B2 status above)
- Last evidence: `specs/changes/spec_088_phase_a_catalyst_delta_filter_design_2026_05_07.md`; AGENT_REGISTRY.json catalyst_delta notes unchanged
- Blocker: Spec 087 B2 remains NEEDS_OPERATOR_DECISION (see Actionable Blockers), so 088 stays blocked
- Next allowed action: none until 087 chain fully resolved
- Not allowed: any artifact-level filtering change to catalyst_delta production tool
- Runtime risk: LOW
- Alert condition: any commit touching `tools/build_catalyst_delta.py` filtering logic

### watchlist_current.json disposition
- Status: **NEEDS_OPERATOR_DECISION** (unchanged) — reconfirmed this run: file does not exist anywhere in repo (0 matches on both filename and content search)
- Last evidence: negative search result, 2026-07-28
- Blocker: unclear whether removed/renamed artifact or a broken reference in older docs/specs
- Next allowed action: operator to confirm whether references are stale (scrub from docs) or the file needs regeneration
- Not allowed: fabricating or regenerating the file without operator direction
- Runtime risk: LOW
- Alert condition: any code path reading this path at runtime and failing silently

### score_rank_pct SPEC_REQUIRED
- Status: HELD (governance gate itself does not expire) — but underlying IC health is now **verified fresh and HEALTHY**, resolving the "UNKNOWN/UNVERIFIED" flag from 07-09/07-13
- Last evidence: `WEEKLY_SIGNAL_REGIME_SWEEP_2026_07_28.md` (untracked, this run) — mean_ic +0.0775, hit rate 84.6%, 39 dates, dashboard source `artifacts/ic_dashboard/2026-07-24_dashboard.json`. Latest single-date IC (-0.0014, 2026-06-25) is a mild negative print inside an otherwise strongly positive rolling window — flagged for awareness only, not a WARN/ALERT trigger per the sweep skill's own aggregation rule.
- Blocker: CRT + IC + PIT + Checklist v2 all still required before any weight change; none evidenced this window
- Next allowed action: no action required at this IC health level; continue nightly monitoring cadence
- Not allowed: any scoring/ranking/weight change without full CRT+IC+PIT+Checklist v2 evidence chain
- Runtime risk: LOW (down from MEDIUM in 07-13 ledger — IC visibility gap closed)
- Alert condition: any commit touching `score_rank_pct` logic without the full evidence chain attached; OR latest single-date IC persisting negative/at-or-below 0.0 threshold into next week's sweep (per sweep skill's own flagged risk)

### EES v3 veto_monitor (raw_veto_core) — production promotion decision
- Status: HELD (shadow) — gate MET 2026-06-25, still FREEZE_ACTIVE/DIAGNOSTIC_ONLY as of the latest status memo (2026-07-23)
- Last evidence: `artifacts/readiness/EES_V3_RAW_VETO_SHADOW_STATUS_2026_07_23.md` — 20d obs 55/20 (MET), cumulative 20d alpha+ rate 88.5%, mean 20d veto alpha +7.9%. **No status print found for 07-24 through 07-28** — a cadence break worth flagging (see Actionable Blockers).
- Blocker: explicit operator approval for production promotion; none found in commits or memos 07-13→07-28
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

### Q1 2026 13F cohort — quarantine
- Status: **CLOSED — decision-grade, quarantine lifted.** Commit `246349bd9` (2026-07-17, operator-approved: "Approved-by: Darren Schulz, operator sign-off, 2026-07-17") ran `tools/check_13f_cohort_quarantine.py` against the correct Q4→Q1 boundary (pre=2026-05-15, post=2026-05-18): Top-30 Jaccard **0.935** (≥0.70 threshold), coverage delta -1.01pp (<10pp trigger), manager delta 0. Supersedes the stale 0.463 wrong-cohort figure that drove the 07-13 ledger's overdue-blocker entry.
- Last evidence: `artifacts/readiness/H20D_JACCARD_FINAL_2026_07_17.md`; commit `246349bd9`
- Blocker: none — resolved
- Next allowed action: Q1 2026 13F may be consumed as decision-grade for alpha/ranker/selector purposes going forward
- Not allowed: n/a (caveat carried forward: this is a first-pass Q4-vs-Q1 comparison across a cohort-size change, not yet the fully like-for-like test — that arrives with Q2 2026, ~2026-08-14. Treat as closed-with-caveat, not permanently settled.)
- Runtime risk: NONE (resolved)
- Alert condition: Q2 2026 like-for-like re-test due ~2026-08-14 — track for next ledger cycle

---

## 3. RECENTLY CLOSED (since 2026-07-13 ledger)

| Item | Closure evidence | Date |
|---|---|---|
| H20D 55-manager cohort re-evaluation gate (Q1 2026 13F quarantine) | commit `246349bd9`, `H20D_JACCARD_FINAL_2026_07_17.md`, Jaccard 0.935, operator sign-off | 2026-07-17 |
| Stale "spec_087_b1b AWAITING_FIRST_FIRE" + "bioshort_watch_llm HELD_SUPPRESSED" ledger-seed entries | commit `f9b5ad76b` — cleared entries frozen since authoring; underlying conditions had resolved months earlier (first-fire 2026-05-08; bioshort_watch reactivated 2026-07-18) | 2026-07-18 |
| score_rank_pct IC visibility gap (UNKNOWN/UNVERIFIED since 07-09) | `WEEKLY_SIGNAL_REGIME_SWEEP_2026_07_28.md` — fresh HEALTHY print, mean_ic +0.0775 | 2026-07-28 |
| gate_verdict_ledger hard_options_coverage FAIL (07-13 print) | Resolved by 07-17 print onward (PASS every day since); no dedicated commit identified, treat as data-refresh recovery not a code fix | 2026-07-17 |

None of these closures touch scoring/ranking/selector logic per commit messages reviewed; the h20d clearance authorizes *consumption* of an existing signal cohort as decision-grade but does not itself change weights, ranking, or selection logic.

---

## 4. UNCOMMITTED WORKING TREE

| Path | Type | Disposition |
|---|---|---|
| `artifacts/forward_validation/fills.jsonl` | Modified | Routine forward-validation data append — low risk, normal cadence |
| `production_data/market_data.json` | Modified | Routine daily production data refresh |
| `WEEKLY_SIGNAL_REGIME_SWEEP_2026_07_28.md` | Untracked (new) | This week's signal sweep report (source for score_rank_pct HEALTHY finding above) — pending commit |
| `production_data/options_snapshot_2026-07-27.json` | Untracked (new) | Daily options snapshot — pending commit, routine |

Working tree is materially cleaner than the 07-13 snapshot (which had ~20 modified/untracked paths including an uncommitted diff to `tools/check_13f_cohort_quarantine.py`). That script diff is no longer showing as modified — consistent with it having been used (and presumably committed) for the 07-17 h20d gate run in commit `246349bd9`. No NEEDS_OPERATOR_DECISION items in this window's working tree.

---

## 5. RECOMMENDED NEXT OPERATOR DECISIONS (rank-ordered, max 5)

1. **Rule on EES v3 raw_veto_core production promotion.** Gate has been MET for 33 days (since 2026-06-25); cumulative shadow performance continues to strengthen (88.5% alpha+ rate, +7.9% mean 20d veto alpha). Also diagnose why the shadow-status memo cadence broke after 2026-07-23 (5 days with no fresh print vs. near-daily prior pattern).
2. **Resolve `bucket_drift_vs_policy` FAIL** (91-180d bucket, ~31.7pp deviation vs. 55% target) — sole blocking scorecard fail, plateaued (not improving) since 07-10, now ~18 days at FAIL/HOLD.
3. **Confirm Spec 087 B2 (dashboard freshness envelope) disposition in writing.** This has sat at NEEDS_OPERATOR_DECISION since at least the 07-13 ledger with no new evidence closing it either way; it is also the transitive blocker holding Spec 088 Phase B.
4. **Clarify `watchlist_current.json` disposition** — confirmed still nonexistent in repo; determine whether stale doc references should be scrubbed or the artifact regenerated.
5. **Diagnose the new phase2_health WARN driver** (`catalyst_7d_count_high`, first seen this window) — confirm whether this is a benign catalyst-calendar clustering effect or requires portfolio-level attention, distinct from the now-cleared `overbought_rsi_exposure` WARN.

---

*Ledger produced by read-only tooling (run_readonly_diagnostics, gate_verdicts, forward_eval_ic_ledger, scientific_cartography_status) plus terminal git/file inspection. No production files were modified. No scoring, ranking, or selector logic was inspected for change — only status/read.*

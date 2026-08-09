# Held-Spec Ledger — 2026-08-03

Generated: 2026-08-03T00:00:00Z (cron, hermes-held-spec-ledger)
Prior ledger: artifacts/audit/held_spec_ledger_2026_07_28.md
Evidence window checked: 2026-07-28 → 2026-08-03 (gate_verdict_ledger, phase2_health, scorecards, EES v3 status memos, git log, AGENT_REGISTRY.json, spec_114/spec_115 change files, hermes_skill_sync memo)

## Overall readiness snapshot (as of latest prints)
- Weekly scorecard verdict (2026-07-31): **HOLD** — blocking check `bucket_drift_vs_policy` FAIL, now **35.0pp** (91-180d bucket Δ vs 55% policy target, actual 20.0%). Prior ledger reported 31.7pp on 07-27 — **this has WORSENED, not plateaued.** Also new `pre_trade_gate` WARN (`alpha_health`), not present in 07-28 ledger's scorecard view.
- Gate verdict ledger (2026-07-24→07-31, 6 records): n_fail=0 throughout, overall_status=WARN every day. Chronic WARNs: `portfolio_weights`, `ruleset_health`, `regulatory_calendar` (intermittent). New: `phase2_health` WARN appears as an explicit gate on 07-29; `drift_monitoring` flipped to WARN on 07-31 (first appearance in this window) dropping n_pass 36→35.
- phase2_health (2026-07-31): WARN, `catalyst_7d_count_high` — same driver as 07-28 ledger, unresolved, now 6+ days standing.
- forward_eval_ic_baseline.json: **unchanged** — still the stale Path C window (2026-05-27–2026-06-03), single observation, `IC_UNOBSERVABLE_EXPECTED`. Now >2 months stale on this specific artifact; gate ledger's `forward_eval: PASS` remains the more current signal per prior ledger's convention.
- EES v3 raw_veto_core shadow: cadence break from 07-28 ledger (5-day gap ending 07-23) has **resolved** — fresh status memos now exist through 2026-08-01 (covering 07-28, 07-29, 07-30, 08-01). 20d gate still **MET** (met 2026-06-25, now 39 days). Cumulative 20d observations grew 62 (from n=62 same as last print but composition differs) with alpha+ rate **83.1%** and mean 20d veto alpha **+7.0%** as of 08-01 memo — both figures are *lower* than the 07-28 ledger's cited 88.5%/+7.9%; flagging the divergence for awareness, not yet diagnosed as regression vs. rolling-window effect.
- **NEW: Spec 115** (protect mandate evidence from git-state interference) — authored and Phase 1 + Phase 2(visibility-half) implemented and merged: commit `dd13e097` (2026-07-29, PR #540). Root cause: 2 of 10 trading days (07-15→07-28) lost mandate-eligible forward-validation windows to git mechanics, not model/data defects. Phase 2 full remediation (2a relocate ledger / 2b commit-after-capture) and Phase 3 (advisory lock) remain **undecided by operator**.
- **Spec 114** (CT.gov date-precision provenance) shadow/non-routing half landed: commits `5d475997` (07-29, provenance capture, non-routing) and `577d1549` (07-30, plumb precision to CalendarCatalyst, explicitly does not change routing). The **routing/freeze-lift-requiring** half of Spec 114 remains **DRAFT**, still blocked on an explicit operator freeze lift that would reset the out-of-sample clock (currently n=4 mandate-eligible windows against a 52-window gate — see Spec 115 context).
- Q1 2026 13F cohort quarantine: closed-with-caveat per 07-28 ledger; **Q2 2026 like-for-like re-test due ~2026-08-14 — now inside a 2-week actionable window.**
- New artifact observed: `hermes_skill_sync_2026_08_02.md` — Status OK, 0 critical drift, 0 warnings, 2 info items (mirror content mismatch + orphaned mirror doc). Informational only, no gate implication.

---

## 1. ACTIONABLE BLOCKERS

| Item | Trigger | Status | Action required |
|---|---|---|---|
| EES v3 raw_veto_core production promotion | Gate MET since 2026-06-25 (39 days); no operator ruling found in commits/memos through 2026-08-01 | NEEDS_OPERATOR_DECISION — longer overdue than 07-28 ledger | Operator must issue explicit promote/hold/reject ruling. Note the 20d alpha+ rate / mean-alpha figures moved down (88.5%→83.1%, +7.9%→+7.0% pp) since 07-28 print — should be reviewed alongside the promotion decision, not treated as noise without check. |
| bucket_drift_vs_policy FAIL — WORSENING | 31.7pp (07-27) → 35.0pp (07-31), 91-180d bucket actual 20.0% vs 55% target | ACTIVE FAIL, blocking trade (scorecard verdict=HOLD) | Portfolio/policy review of 91-180d bucket allocation. Trend direction changed from "plateaued" to "worsening" — escalate priority above 07-28 ledger's ranking. |
| Spec 114 freeze-lift decision | Shadow/non-routing halves already merged (07-29, 07-30); routing half blocked | NEEDS_OPERATOR_DECISION (unchanged in substance, but implementation now partially landed) | Operator to rule explicitly on freeze lift for the routing-affecting half. Reminder: lift resets the OOS clock — cost stated explicitly in the spec. |
| Spec 115 Phase 2 full remediation (2a vs 2b) + Phase 3 | Phase 1 + partial Phase 2 (visibility-only) landed 2026-07-29 | NEEDS_OPERATOR_DECISION | Operator to choose 2a (relocate evidence ledger out of git) vs 2b (commit-after-capture in cron path, adjacent to INC-2026-06-20 concerns). Phase 3 (advisory lock) sequenced last, after 1+2 observed working — do not start early. |
| Q2 2026 13F like-for-like re-test | Due ~2026-08-14 (11 days out) | Scheduled, not yet due | No action yet; flagging for next ledger cycle's tracking, and to confirm the test actually runs on schedule. |
| Spec 087 B2 dashboard freshness envelope disposition | B1b closed since 2026-05-14; unresolved since ≥07-13 ledger | STILL UNRESOLVED — no new evidence 07-28→08-03 | Operator to confirm formally whether B2 is ACTIVE; transitively blocks Spec 088. |

---

## 2. HELD BRANCHES

### Spec 087 B1b — first-fire validation
- Status: **CLOSED** (unchanged)
- Last evidence: `artifacts/audit/spec_087_b1b_formal_closure_2026_05_14.md`
- Blocker: none
- Next allowed action: none
- Not allowed: reopening without new operator directive
- Runtime risk: NONE
- Alert condition: n/a

### Spec 087 B2 — dashboard freshness envelope
- Status: **NEEDS_OPERATOR_DECISION** (unchanged, now stale ≥3 weeks)
- Last evidence: `specs/changes/spec_087_b2_dashboard_freshness_envelope_draft.md`; no commit found 07-28→08-03 referencing activation
- Blocker: no explicit operator ruling that B1b closure unblocks B2
- Next allowed action: operator review + written authorization to transition to ACTIVE
- Not allowed: silent promotion to ACTIVE
- Runtime risk: LOW
- Alert condition: any commit touching dashboard freshness logic without a spec-status update

### Spec 087C — bioshort alpha research
- Status: HELD (needs ≥4 fresh weekly reports)
- Last evidence: `spec_087c_phase_b_disposition_2026_05_14.md` — no newer evidence
- Blocker: weekly report accumulation
- Next allowed action: continue accumulation; re-check next cycle
- Not allowed: production activation
- Runtime risk: NONE
- Alert condition: 4th fresh weekly report landing

### bioshort_watch LLM reactivation
- Status: **CLOSED / SUPERSEDED** (unchanged) — AGENT_REGISTRY.json confirms `status: active`, reactivated 2026-07-18, cron ID `9b7546acf514`, cadence "irregular, gaps up to ~24 days" (informational). `sunset_review_date: 2026-09-30` unchanged.
- Last evidence: AGENT_REGISTRY.json (re-verified 2026-08-03)
- Blocker: none
- Next allowed action: monitor cadence
- Not allowed: n/a
- Runtime risk: LOW
- Alert condition: sunset review 2026-09-30 approaching, or cron gap >~24 days

### Spec 088 Phase B — catalyst_delta filtered artifacts
- Status: HELD — blocked on Spec 087 B2 close (unchanged)
- Last evidence: `specs/changes/spec_088_phase_a_catalyst_delta_filter_design_2026_05_07.md`; no new commits touching `tools/build_catalyst_delta.py` filtering logic found 07-28→08-03
- Blocker: Spec 087 B2 still NEEDS_OPERATOR_DECISION
- Next allowed action: none until 087 chain resolved
- Not allowed: any artifact-level filtering change to production catalyst_delta tool
- Runtime risk: LOW
- Alert condition: any commit touching `tools/build_catalyst_delta.py` filtering logic

### watchlist_current.json disposition
- Status: **NEEDS_OPERATOR_DECISION** (unchanged) — reconfirmed: file absent from repo, no new commits reference it
- Last evidence: negative search result, 2026-08-03
- Blocker: unclear whether removed/renamed artifact or stale doc reference
- Next allowed action: operator to confirm scrub-vs-regenerate
- Not allowed: fabricating or regenerating without operator direction
- Runtime risk: LOW
- Alert condition: any code path reading this path at runtime and failing silently

### score_rank_pct SPEC_REQUIRED
- Status: HELD (gate does not expire); IC health previously verified HEALTHY (07-28 ledger) — **not re-verified this window**, no new WEEKLY_SIGNAL_REGIME_SWEEP report found dated after 07-28 in repo listing
- Last evidence: `WEEKLY_SIGNAL_REGIME_SWEEP_2026_07_28.md` (now committed, per absence from working-tree diff)
- Blocker: CRT + IC + PIT + Checklist v2 all still required before any weight change; none evidenced
- Next allowed action: obtain a fresher sweep report before asserting current IC health; do not assume 07-28's HEALTHY finding still holds without a new print
- Not allowed: any scoring/ranking/weight change without full evidence chain
- Runtime risk: LOW-MEDIUM (ticking back up slightly — IC print now 6 days old vs. same-day freshness previously)
- Alert condition: any commit touching `score_rank_pct` logic without full evidence chain; OR next sweep print showing degraded IC

### EES v3 veto_monitor (raw_veto_core) — production promotion decision
- Status: HELD (shadow) — gate MET 2026-06-25, still FREEZE_ACTIVE/DIAGNOSTIC_ONLY as of 2026-08-01 memo
- Last evidence: `artifacts/readiness/EES_V3_RAW_VETO_SHADOW_STATUS_2026_08_01.md` — 20d gate MET (62/20), cumulative 20d alpha+ rate 83.1%, mean 20d veto alpha +7.0%
- Blocker: explicit operator approval for production promotion; none found in commits/memos through 08-03
- Next allowed action: operator reviews freeze-lift review memo (2026-06-25) + current shadow status; issues explicit promote/hold/reject ruling
- Not allowed: any change to `mutation_authority` or enabling production decisioning without sign-off
- Runtime risk: LOW (diagnostic-only, no portfolio action per governance block)
- Alert condition: any commit flipping `production_decisioning` to true or removing FREEZE_ACTIVE without an operator-attributed commit message

### Spec 113 — construction signal PIT snapshots
- Status: HELD — **DRAFT**, unchanged
- Last evidence: `specs/changes/spec_113_construction_signal_pit_snapshots_2026_07_05.md`; no new commits
- Blocker: operator approval to move to IN PROGRESS
- Next allowed action: none until approval
- Not allowed: any implementation commits against this spec
- Runtime risk: NONE
- Alert condition: any commit referencing spec_113 implementation without a preceding approval record

### Spec 114 — CT.gov date-precision provenance (NEW this cycle, tracked from prior ledger's DRAFT note)
- Status: **HELD — freeze-lift-requiring half is NEEDS_OPERATOR_DECISION; shadow/non-routing half is CLOSED (merged)**
- Last evidence: commits `5d475997` (2026-07-29, provenance capture, non-routing) and `577d1549` (2026-07-30, plumb precision to CalendarCatalyst, "deliberately does NOT change routing"); spec file `specs/changes/spec_114_catalyst_date_precision_provenance_2026_07_28.md` still reads DRAFT for the routing-affecting portion
- Blocker: operator freeze lift for the routing half — this resets the OOS clock (n=4 mandate-eligible windows / 52-window gate)
- Next allowed action: operator decision on whether the cost (OOS reset) justifies fixing the routing defect now vs. deferring
- Not allowed: any change to `catalyst_decay_w`/`catalyst_tilt_mult`/`target_weight_pct` routing logic without the freeze lift
- Runtime risk: LOW (non-routing capture is inert to production scoring; routing half not yet touched)
- Alert condition: any commit modifying routing/precision-to-tilt logic without an operator-attributed freeze-lift commit message

### Spec 115 — protect mandate evidence from git-state interference (NEW this cycle)
- Status: **HELD — Phase 1 + Phase 2(visibility) CLOSED (merged); Phase 2(full) + Phase 3 NEEDS_OPERATOR_DECISION**
- Last evidence: commit `dd13e097` (2026-07-29, PR #540); spec file `specs/changes/spec_115_production_run_git_lock_2026_07_29.md` implementation log still describes the merged work as "(uncommitted)" — **spec doc is stale relative to the actual commit; flagging the doc/commit mismatch, not treating the commit as unverified.**
- Blocker: operator choice between 2a (relocate evidence ledger outside git) and 2b (commit-after-capture in cron path); Phase 3 explicitly sequenced after 1+2 are observed working
- Next allowed action: operator decision on 2a vs 2b; do not start Phase 3 early
- Not allowed: any cron job push capability (hard invariant, unchanged); any relocation of the evidence ledger without operator sign-off
- Runtime risk: MEDIUM (mitigated from HIGH pre-fix — Mode A now diagnosable, Mode B now visible-but-not-yet-prevented; unbounded exposure window for Mode B remains open until 2a/2b lands)
- Alert condition: any further mandate-eligible window loss to git mechanics (would indicate Phase 1/2 partial fix insufficient); any uncommitted-capture WARN at next run start naming new dates

### Q1 2026 13F cohort — quarantine
- Status: **CLOSED — decision-grade** (unchanged); Q2 2026 like-for-like retest due ~2026-08-14 is the next checkpoint (see Actionable Blockers)
- Last evidence: `artifacts/readiness/H20D_JACCARD_FINAL_2026_07_17.md`; commit `246349bd9`
- Blocker: none currently — future retest scheduled
- Next allowed action: Q1 2026 13F consumable as decision-grade until Q2 retest supersedes
- Not allowed: n/a
- Runtime risk: NONE
- Alert condition: Q2 2026 retest date (~2026-08-14) arriving without a scheduled run

### Spec 089 — Hermes Knowledge Layer (NEW this cycle)
- Status: **ACTIVE** — Phase 1 implemented per commit `1188443f5` ("feat(ops): Spec 089 Phase 1 — Hermes Knowledge Layer spec + ledger generator")
- Last evidence: `specs/changes/spec_089_hermes_knowledge_layer.md`; commit `1188443f5`
- Blocker: none identified this window
- Next allowed action: continue phased implementation per spec; confirm Phase 2 scope with operator before starting if not already specified in the spec doc
- Not allowed: scope expansion beyond documented phases without spec update
- Runtime risk: LOW (ops tooling, not scoring/ranking surface)
- Alert condition: any commit under this spec touching ranking/scoring/selector logic (would be out of stated scope)

---

## 3. RECENTLY CLOSED (since 2026-07-28 ledger)

| Item | Closure evidence | Date |
|---|---|---|
| Spec 115 Phase 1 (Mode A early-bind/diagnose) + Phase 2 visibility-half (Mode B WARN) | commit `dd13e097`, PR #540 | 2026-07-29 |
| Spec 114 shadow/provenance capture (non-routing) | commit `5d475997` | 2026-07-29 |
| Spec 114 precision plumbed to CalendarCatalyst (non-routing) | commit `577d1549` | 2026-07-30 |
| Spec 089 Phase 1 (Hermes Knowledge Layer) | commit `1188443f5` | date not independently confirmed this window — flagged `[?]` |
| EES v3 shadow-status cadence gap (5-day break ending 07-23) | fresh memos resumed 07-28→08-01 | 2026-07-28 onward |

None of these closures touch scoring/ranking/selector logic per commit messages reviewed — all explicitly stated as non-routing, orchestration, or observability-only. Spec 089 is ops tooling.

---

## 4. UNCOMMITTED WORKING TREE

| Path | Type | Disposition |
|---|---|---|
| `artifacts/governance/hermes_skill_sync/latest_heartbeat.json` | Modified | Routine heartbeat update — low risk |
| `artifacts/universe_hygiene/xbi_ibb_universe_audit_2026_06_28/*` (6 files: audit md, CSVs, summary json) | Modified | **Flag for operator attention** — this is a dated (2026-06-28) universe-hygiene audit snapshot with files being modified in place ~5 weeks later; not a routine daily-append pattern like prior ledgers' items. Unclear whether this is an in-place regeneration or an accidental re-touch. No commit or audit memo found explaining the change. |
| `production_data/universe.json` | Modified | Possibly related to the above universe-hygiene audit activity — **flag jointly with the item above**; universe changes are a scoring-surface-adjacent artifact and warrant confirmation this is not an uncommunicated universe change. |
| `artifacts/governance/hermes_skill_sync/hermes_skill_sync_2026_08_02.md` | Untracked (new) | Routine skill-sync audit report, Status OK, 0 critical drift — low risk, pending commit |
| `"data/snapshots - Shortcut.lnk"` | Untracked (new) | **Anomalous** — a Windows shortcut (.lnk) file inside a tracked data directory path. Not a data artifact; almost certainly an accidental drag/drop or desktop-integration artifact. Recommend operator delete rather than commit; do not commit as-is. |

**Escalation note:** the `universe.json` + universe-hygiene-audit modification cluster is the one item in this window that differs materially from "routine daily refresh" — flagging as NEEDS_OPERATOR_DECISION rather than asserting it is benign, since no commit message or memo explains it and universe composition is scoring-adjacent.

---

## 5. RECOMMENDED NEXT OPERATOR DECISIONS (rank-ordered, max 5)

1. **Rule on EES v3 raw_veto_core production promotion.** Gate MET for 39 days; cumulative alpha+ rate/mean-alpha have both ticked down since the 07-28 print (88.5%→83.1%, +7.9pp→+7.0pp) — review this trend alongside the promotion decision rather than treating flat.
2. **Resolve `bucket_drift_vs_policy` FAIL — now worsening (31.7pp→35.0pp), not plateaued.** Escalated priority vs. 07-28 ledger given the trend reversal.
3. **Explain and confirm the `production_data/universe.json` + universe-hygiene-audit (2026-06-28 dated files) uncommitted modification.** No commit or memo found explaining a change to files 5 weeks after their nominal date; universe composition is scoring-adjacent — confirm before it ages further uncommitted.
4. **Rule on Spec 114 freeze lift and Spec 115 Phase 2 (2a vs 2b).** Both are now partially implemented (non-routing/visibility halves merged) with the harder decisions (routing freeze lift; evidence-ledger relocation) still open — sequencing risk if left much longer given the OOS-clock cost tied to Spec 114.
5. **Confirm Spec 087 B2 dashboard freshness envelope disposition in writing.** Unresolved since ≥07-13 ledger (now ≥3 weeks), transitively blocking Spec 088.

---

*Ledger produced by read-only tooling (run_readonly_diagnostics, gate_verdicts, phase2_health, forward_eval_ic_ledger) plus terminal git/file inspection. No production files were modified. No scoring, ranking, or selector logic was inspected for change — only status/read. Ledger and its published copies are the only files written by this run.*

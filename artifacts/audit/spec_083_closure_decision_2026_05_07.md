# Spec 083 Closure Decision Memo (2026-05-07)

**Status:** CLOSURE DECISION ONLY. Memo first; spec-file status flip is deferred to a follow-on edit if and when this decision is approved. No code changes in this memo. No cron edits. No agent runs.

**Subject:** `Spec 083 — P0: Agent date-stamp corruption (policy_shadow_watch, bioshort_watch)`, file `specs/changes/spec_083_p0_agent_date_stamp_corruption_2026_05_06.md`.

**Recommended ruling:** **CLOSE as SUPERSEDED / MITIGATED.** Mode-A and Mode-B failures originally listed under Spec 083 are no longer reachable in the current control plane. The two affected agents have been brought to a coherent end-state by separate, already-landed work — not by completing the Spec 083 §6 acceptance criteria as written. Closing as MITIGATED preserves the audit trail; not as `[resolved]`, because the spec's own §6.4 condition was bypassed rather than satisfied.

---

## 1. What Spec 083 originally asked for

Spec 083 (`specs/changes/spec_083_p0_agent_date_stamp_corruption_2026_05_06.md`, §6) defined acceptance for closure as four items:

| §6 item | Intent |
|---|---|
| §6.1 | After fix lands and one full weekday cron cycle, `policy_shadow_watch` writes `artifacts/policy_shadow/tier_weighted/YYYY-MM-DD_comparison.md` with today's date in both filename and inner content. |
| §6.2 | `history.jsonl` last 3 entries all date to today's run. |
| §6.3 | Heartbeat STALE alert clears within one cycle. |
| §6.4 | `bioshort_watch` Mode A fixed (correct filename); Mode B remains until `output/hedge_report/` upstream is restored — this ticket does not block on that. |

The spec was scoped READ-ONLY in its own §3 ("smallest diff that fixes the date-stamp bug without changing schedule/scope"). Implementation was intended to follow the scoped investigation under explicit operator approval.

---

## 2. What actually landed (timeline)

### 2a. policy_shadow_watch path (Mode A, the artifact-stamp bug)

| SHA | Subject | Mapping to Spec 083 |
|---|---|---|
| `f2fad8c1` | `docs(audit): P0 #1 phase 1 root-cause memo for date-stamp corruption` | Phase-1 deliverable — separates artifact-stamp bug from stale-upstream bug |
| `2fd2e7d9` | `fix(registry): align policy_shadow_watch.artifact_paths to canonical output` | Registry hygiene; not in §3 deliverables but relieves consumer confusion |
| `264c0e00` | `fix(catchup): P0 #1 fix B — align policy_shadow_watch with deterministic builder` | Replaces LLM agent invocation with `run_tool policy_shadow 1805 → build_policy_shadow_compare.py`. Catchup uses today's-comparison-file existence as idempotency check. |
| `9c90ed46` | `fix(policy_shadow): P0 #1 fix C — defensive --as-of-date guard` | Refuses `--as-of-date` older than latest `history.jsonl` entry unless `--allow-backfill`; surfaces unidentified-caller pattern that contaminated history.jsonl on 2026-05-06. |
| `7c6b4dd5` | `fix: make policy shadow history append idempotent` | Same-date append now logged-and-skipped, preventing duplicate rows when manual fire + 18:05 cron coincide. |
| `3d8271c3` | `fix(run_screen): surface policy_shadow_compare skip at warning level` | Visibility hardening. |
| `70049dd0` | `ops(heartbeat): fix review_queue_steward + policy_shadow_watch receipt noise` | Heartbeat STALE-alert noise resolution. |
| `eda9fc8c` | `docs(ops): finalize shadow_watch as suppressed placeholder` | Per Spec 085 Path C; not Spec 083 directly but closes the agent boundary. |

**Verification (read-only, 2026-05-07):**

```
artifacts/policy_shadow/tier_weighted/
  2026-05-05_comparison.md   (mtime 2026-05-05 20:45)
  2026-05-05_comparison.json (mtime 2026-05-05 20:45)
  2026-05-06_comparison.md   (mtime 2026-05-06 17:28)
  2026-05-06_comparison.json (mtime 2026-05-06 17:28)
```

`history.jsonl` last 5 rows are stamped 2026-04-30, 2026-05-01, 2026-05-04, 2026-05-05, 2026-05-06 — each row's `"date"` field matches the run date. Mode-A artifact-stamp corruption is no longer occurring on this path.

| §6 item | policy_shadow_watch verdict |
|---|---|
| §6.1 (filename + inner stamp = today) | **MET** for 2026-05-05 and 2026-05-06 cycles. Tonight's 18:05 fire (2026-05-07) is the next confirming sample. |
| §6.2 (history.jsonl last 3 entries dated to today's runs) | **MET** — last 5 entries are independently date-stamped. |
| §6.3 (heartbeat STALE clears) | **MET** via `70049dd0`. |

### 2b. bioshort_watch path (Mode A artifact-stamp + Mode B stale upstream)

| SHA | Subject | Mapping |
|---|---|---|
| `b73c223c` | `ops(agents): suppress bioshort_watch stale upstream` | Suppresses the LLM consumer that read 41-day-stale `hedge_report` (last write 2026-03-26). Producer `tools/biotech_hedge_report.py` preserved. |
| `ff03788e` | `ops(bioshort): guard stale upstream watch generation` | Stale-upstream guard in `run_screen.py`. |
| `30d73a14` | `docs(bioshort): record hedge-governance phase A memo` | Spec 087 Phase A governance decision. |
| `7165cfc2` | `docs(bioshort): record B1 producer-restoration amendments` | Spec 087 B1 amendments. |
| `b576a46d` | `docs(bioshort): record B0.1 production-verification finding` | Spec 087 B0.1 finding. |
| `ae702bf2` | `feat(bioshort): Spec 087 B1a — resolve_portfolio_csv, drop rankings.csv fallback` | Producer rebuild. |
| `07259611` | `docs(bioshort): Spec 087 B1b env-readiness finding — prerequisites cleared` | Producer prerequisites cleared. |

**State (2026-05-07):**

- Consumer: `bioshort_watch` LLM agent — **SUPPRESSED**, governed in held-spec ledger §2 row "bioshort_watch LLM reactivation: HELD/SUPPRESSED."
- Producer: `tools/biotech_hedge_report.py` — **REBUILT** under Spec 087 B0/B1; first-fire scheduled 2026-05-08 18:00 ET.
- Stale-upstream guard: present in `run_screen.py` (`ff03788e`).

| §6 item | bioshort_watch verdict |
|---|---|
| §6.4 (Mode A fixed; Mode B punted) | **NOT MET as written.** Mode A was not directly patched in `bioshort_watch`. Instead the consumer was suppressed (eliminating the consumer-side artifact-stamp pathway), and Mode B (upstream restoration) was promoted from a "punted P2" into a first-class spec branch (Spec 087 B0/B1/B1b). |

The §6.4 condition is no longer satisfiable in the current control plane: there is no live `bioshort_watch` consumer to apply Mode-A correction to. The Mode-A failure mode is unreachable.

### 2c. Spec 085 disposition (related)

Spec 085 (`shadow_watch` disposition) closed 2026-05-06 as SUPPRESSED PLACEHOLDER under Path C. This does not directly satisfy any Spec 083 §6 row, but it closes a related agent-boundary question and prevents future date-stamp issues from reappearing under a half-merged successor.

---

## 3. Why "SUPERSEDED / MITIGATED," not "[resolved]" or "still open"

### 3a. Why not `[resolved]`

Spec 083 §6 acceptance is not literally satisfied:

- §6.1–§6.3 (policy_shadow_watch): met by direct fixes — but those fixes (`264c0e00`, `9c90ed46`, `7c6b4dd5`, `70049dd0`) did **more** than the smallest-diff scope in §3 of Spec 083. They were a coordinated catchup-replacement + idempotency + as-of guard, several of which are not enumerated in Spec 083 §3.
- §6.4 (bioshort_watch): bypassed entirely. The consumer was suppressed and the producer rebuilt under a different spec.

A pure `[resolved]` label would over-claim that the original ticket's specific steps completed. They didn't — different work superseded them.

### 3b. Why not "still open"

Both failure modes have been neutralized:

- Mode-A artifact-stamp bug is structurally prevented on `policy_shadow_watch` (deterministic builder, idempotent append, as-of guard).
- Mode-A on `bioshort_watch` is unreachable (consumer suppressed).
- Mode-B stale-upstream is moved into Spec 087 with its own first-fire gate on 2026-05-08 18:00 ET.

There is no actionable item left under Spec 083's specific scope. Keeping it open would create ledger noise and ambiguous ownership against Spec 087.

### 3c. Why "SUPERSEDED / MITIGATED" is the correct ruling

The label captures the asymmetry: the failure modes are mitigated, but the route was not the route the spec specified. The original spec is preserved as the audit trail of the failure analysis; the closure memo points forward to the actual control-plane state.

This mirrors the Spec 086 pattern — the older `specs/SPEC_086_v1.14.0_checklist_v2_validation.md` was retained with a SUPERSEDED banner once the operator ruling reframed it as a demotion-hygiene patch. Same governance shape: keep evidence, redirect authority.

---

## 4. Decision

Recommended ruling, pending operator approval:

```
Spec 083 status: SUPERSEDED / MITIGATED (2026-05-07)
- Mode-A on policy_shadow_watch:  fixed-by-different-route (264c0e00 + 9c90ed46 + 7c6b4dd5 + 70049dd0)
- Mode-A on bioshort_watch:       unreachable (consumer suppressed b73c223c)
- Mode-B upstream restoration:    moved to Spec 087 B0/B1, awaiting first-fire 2026-05-08 18:00 ET
- §6.1–§6.3 acceptance:           met
- §6.4 acceptance:                bypassed; replaced by Spec 087 B-track
```

**Operator decision required:** approve the SUPERSEDED / MITIGATED label, OR direct one of the alternatives in §5 below, OR keep the spec open pending a literal §6.4 fix (not recommended).

---

## 5. Alternatives considered and rejected

| Alternative | Why rejected |
|---|---|
| Mark `[resolved]` | Overstates what happened. §6.4 was bypassed, not satisfied. |
| Keep open | Nothing actionable remains under the spec's scope. Spec 087 owns the upstream-producer track. |
| Reopen and rewrite §6 to match what landed | Possible but unnecessary. The history is clearer with a SUPERSEDED memo than with retroactive spec edits. |
| Close as `[duplicate of Spec 087]` | Misleading. Spec 087 covers the producer / upstream side only; the policy_shadow_watch fix path is its own work that does not belong under Spec 087. |

---

## 6. Out of scope for this memo

- Editing the body of `specs/changes/spec_083_p0_agent_date_stamp_corruption_2026_05_06.md`.
- Adding a SUPERSEDED banner to that file.
- Any code change.
- Any cron change.
- Any change to `bioshort_watch` SUPPRESSED state.
- Any change to `shadow_watch` SUPPRESSED PLACEHOLDER state (governed by Spec 085).
- Anything touching Spec 087 B1b first-fire path.
- Anything touching `manual_overrides.json`, `calibration_summary.json`, or per-ticker resolution files.

If the recommendation is approved, the follow-on action is a single docs commit that:
1. Adds a SUPERSEDED / MITIGATED status header to the top of `specs/changes/spec_083_p0_agent_date_stamp_corruption_2026_05_06.md` pointing at this memo.
2. Updates the held-spec-ledger row for Spec 083 (if any reappears under monitoring) to `RESOLVED — see artifacts/audit/spec_083_closure_decision_2026_05_07.md`.

That follow-on commit is **not** included here.

---

## 7. Acceptance for this memo

This memo closes when **one** of the following:

1. Operator approves the SUPERSEDED / MITIGATED ruling. Follow-on docs commit lands per §6.
2. Operator directs a different ruling. Memo updated or replaced accordingly.
3. Operator directs that Spec 083 stay open pending a literal §6.4 fix on `bioshort_watch`. In that case, `bioshort_watch` would need un-suppression, which conflicts with the held-spec-ledger §2 governance. This path is flagged as inconsistent and would require its own resolution before reopening Spec 083.

---

## 8. Dependencies

| Dependency | State |
|---|---|
| Spec 085 closure (shadow_watch SUPPRESSED PLACEHOLDER) | CLOSED 2026-05-06 |
| Spec 087 B1b producer first-fire | Awaiting 2026-05-08 18:00 ET |
| `bioshort_watch` LLM consumer suppression | Active per held-spec ledger §2 |
| `policy_shadow_watch` deterministic builder cron | Live, daily 18:05 ET |
| Today's 2026-05-07 18:05 fire of policy_shadow_watch | Pending — confirming sample for §6.1 still-met |

---

_Closure memo only. No code or spec-file edits in this memo. Authored 2026-05-07 in response to operator request to make a written closure decision before flipping spec status. Recommendation: SUPERSEDED / MITIGATED._

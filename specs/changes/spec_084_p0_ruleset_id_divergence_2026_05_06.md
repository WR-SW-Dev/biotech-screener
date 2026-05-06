# Spec 084 — P0: Ruleset-ID divergence (model-control-plane reconciliation) (2026-05-06)

**Status:** SCOPED ONLY. No code changes. No ruleset edits. No agent changes. Investigation + reconciliation plan only. Implementation requires explicit user approval AND identification of the canonical source.

**Origin:** Investment Logic Audit (`artifacts/audit/agent_fleet_investment_logic_audit_2026_05_06.md`), Section A risk #1, Section E row 3, Section I P0 #2.

**Priority:** P0 #2 (after date-stamp corruption, before `shadow_watch` disposition).

**Classification:** **MODEL-CONTROL-PLANE issue, NOT an agent-fleet issue.** Agents (`sentinel`, `ops`, `production_qa`, `catalyst_delta`) are correctly flagging the divergence. The fix lives in the ruleset registry / manifest, not in agent code.

---

## Hard constraints

- Do NOT change any ruleset file.
- Do NOT promote, demote, or re-version a ruleset.
- Do NOT touch `production_data/decision_ruleset.json` or `production_data/ranker_v2_model.json`.
- Do NOT modify `common/ranker_active_contract.py`.
- Do NOT alter selector / ranker / EV scoring or any production cron.
- Do NOT update memory file `scoring_model_identity_2026_04_06.md` until the canonical ID is confirmed by the user.
- This is a read / inventory / reconciliation-plan ticket. The actual reconciliation is a separate decision under the existing freeze regime (`policy_alpha_freeze_2026_04_04.md` + `policy_freeze_architecture_2026_04_19.md`).

---

## 1. Problem statement

Three different ruleset IDs are presently observable in the system, each from a different source of truth:

| ID | Source | Note |
|---|---|---|
| `2a3e79eb` v1.13.0 | Memory of record (`scoring_model_identity_2026_04_06.md`) | "Ruleset frozen 2026-04-06; A4 selector + 2-feat ranker; live ruleset" |
| `8887576e` v1.4.0 | Snapshot 2026-05-05 rankings.csv `ruleset_id` column (per audit memo evidence) | Audit also notes `agents/catalyst_delta/SOUL.md:36` references `8887576e v1.14.0` |
| `bebe73f8` v1.10.0 | `agents/sentinel/memory/2026-05-05.md:5` | Sentinel's view of the live ruleset |

Additionally:
- `logs/blast_radius.log` reports 297/297 tickers changed on 2026-05-05 — consistent with a ruleset version-bump or ID rotation.
- The freeze regime (post 2026-04-04) explicitly forbids un-Checklist-v2 promotions; if a ruleset rotation happened, it must be evidenced.

This is not a single bug. It is at minimum two distinct possibilities (or a combination):

- **Hypothesis H1: Stale memory.** The live ruleset rotated from `2a3e79eb` to a newer ID, and the memory file is out of date. The 100% blast on 2026-05-05 is consistent with a rotation event.
- **Hypothesis H2: Inconsistent producers.** Different code paths read/write a `ruleset_id` field from different sources (file, hash-on-the-fly, hardcoded constant). The IDs are all "live" but for different artifacts.
- **Hypothesis H3: Phantom ID.** One of the IDs is computed via a hash that was changed, producing a new value without a real change to the ruleset. (Audit-only-detectable.)

These are mutually compatible — investigation must enumerate, not pick.

---

## 2. Investigation scope (read-only inventory)

### 2.1 Source-of-each-ID map

For each of the three IDs, find:

- **Where it is written** (which file/function emits it; the CONSTANT or HASH-OF-WHAT).
- **Where it is read** (every consumer that uses the field for routing, logging, gating, attribution).
- **When it was last updated** (`git log -p` for the producing code path; commit + author + message).

Concrete starting points (do NOT modify any of these — read only):

- `production_data/decision_ruleset.json` — top-level `ruleset_id` field if present.
- `production_data/ranker_v2_model.json` — `model_id` / `ruleset_id` if present.
- `common/ranker_active_contract.py` — any constant or hash function that produces an ID.
- `module_5_composite_v3.py`, `module_5_scoring_v3.py`, `decision_engine.py`, `decision_engine_codes.py` — any place that stamps a ruleset ID into output rows.
- `run_screen.py` — search for `ruleset_id` writes into `rankings.csv`.
- `agents/sentinel/` — how sentinel discovers the ID it reports.
- `agents/catalyst_delta/SOUL.md` — confirm `8887576e v1.14.0` reference; trace the code path that updated SOUL.md.
- `tools/build_rank_change_monitor.py` and any blast-radius computation — what ID does it stamp.

### 2.2 Canonicality determination

After the source map, classify each ID as one of:

- **CANONICAL** — produced by the authoritative ruleset registry; gates production scoring.
- **DERIVED** — re-computed from canonical inputs (e.g., a hash of merged config); no independent authority but SHOULD agree with canonical.
- **ARTIFACT-LOCAL** — stamped at write-time of a particular artifact, may legitimately diverge.
- **STALE** — refers to a previous ruleset that is no longer live.

Only ONE ID can be CANONICAL. The reconciliation plan flows from that determination.

### 2.3 Blast-radius cross-check

Confirm the 100% blast on 2026-05-05:

- Read `logs/blast_radius.log` for the lines producing "Tickers with any field change: 297/297".
- Cross-reference with `data/snapshots/2026-05-05/rank_changes.csv` (or whichever artifact `tools/build_rank_change_monitor.py` writes).
- Confirm: was this a ruleset rotation event (every ticker's score changed) or a snapshot-base change (different feature inputs across the board)?
- Distinguishable by: ruleset rotation moves ranks but rarely scores by identical deltas; feature-input change moves scores in patterns by feature dependency.

### 2.4 Freeze-regime compliance audit

Per `policy_alpha_freeze_2026_04_04.md`: any ruleset promotion requires Checklist v2.

- Look for any commit between 2026-04-06 (memory of record) and 2026-05-06 (today) that touched ruleset definitions or promotion logic.
- For each, classify: silent rotation? authorized? sidecar / shadow? unrelated rename?

---

## 3. Deliverables (this ticket)

A reconciliation memo at `artifacts/audit/p0_ruleset_id_reconciliation_2026_05_06.md` containing:

1. **Source-of-each-ID map** — table covering all 3 IDs:
   - file:line where written
   - input from which the ID is derived (constant? hash of what?)
   - file:line where read by each consumer
2. **Canonical classification** — which of the 3 IDs IS the canonical one (or none, with explanation).
3. **Reconciliation plan** — minimal change to bring all three views into agreement, broken into separable steps:
   - Step A: update memory file `scoring_model_identity_2026_04_06.md` if the live ID has rotated (memory-only edit, no code change).
   - Step B: align reader code if any consumer reads from a non-canonical source (code change — gated on user approval).
   - Step C: align stamp-at-write code for any ARTIFACT-LOCAL stamps that should mirror the canonical (code change — gated on user approval).
4. **Decision matrix** — for each of H1/H2/H3, which Step set applies.
5. **What NOT to do** — explicit list of changes that look like reconciliation but would be ruleset promotions in disguise (and therefore freeze-regime violations).
6. **Audit trail capture** — which `git log` commits / artifact mtimes establish the timeline of any rotation. Capture before any reconciliation lands.
7. **Test/smoke** — for each proposed code change, the smallest verification that the change is purely cosmetic (same scoring outputs, just consistent ID stamping).

---

## 4. Out of scope for this ticket

- Promoting any ruleset.
- Reverting any ruleset.
- Making `sentinel`, `ops`, or other agents stop flagging the divergence (they SHOULD flag it until reconciled).
- Modifying `agents/catalyst_delta/SOUL.md` (its reference to `8887576e v1.14.0` is part of the evidence).
- Any selector / ranker / EV change.

---

## 5. Risk if implementation later proceeds

- **Low risk** for memory-only updates (Step A).
- **Medium risk** for reader/writer code changes (Steps B/C) — must verify the changes are stamping-only and produce byte-identical scoring outputs (check `rankings.csv` row hashes pre/post on a held snapshot). A regression here would be an undetected ruleset change masquerading as cleanup.
- **High risk** if any "reconciliation" inadvertently rotates the canonical — would violate the freeze regime. The decision matrix in §3 deliverable item 4 must explicitly flag any change that touches canonical inputs.

---

## 6. Acceptance for closure (when reconciliation later lands)

1. All three observable IDs (`sentinel` memory, snapshot column, agent SOUL files) report the same canonical ID.
2. Memory file `scoring_model_identity_2026_04_06.md` accurately reflects the live ID.
3. `tools/build_rank_change_monitor.py` and similar do not produce 100% blast unless the canonical ID actually changed.
4. No selector/ranker/EV output changed (verified by snapshot row-hash comparison).
5. `sentinel`, `ops_supervisor`, `production_qa` no longer flag a divergence.

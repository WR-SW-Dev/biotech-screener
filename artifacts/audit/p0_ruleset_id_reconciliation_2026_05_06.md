# P0 #2 — Ruleset-ID Reconciliation Memo (2026-05-06)

**Status:** Read-only investigation per Spec 084. **No ruleset, code, or memory changes implemented.** Implementation requires explicit user approval AND confirmation of the canonical ID by the user.

**Headline:** The "three-ID divergence" flagged by the audit is **largely already resolved at the canonical layer**. The live production ruleset is `8887576e` v1.14.0 (in manifest, scripts, snapshot). The other IDs are stale references in documentation/agent-SOUL/memory layers, with one phantom (`622edb77`) and one historical (`bebe73f8`). Reconciliation is overwhelmingly text/memory edits, not code or scoring changes. **One real reader-side concern remains: sentinel's 2026-05-05 memory file references `bebe73f8` — a 7+ week stale ID — suggesting `tools/ruleset_health_monitor.py` is reading from a stale source.**

---

## 1. Source-of-each-ID map

Investigation found a **fourth** ID (`622edb77`) not in the original spec — a phantom hash from the v1.14.0 promotion. All four IDs documented:

| ID | Version | Status | Where it appears (live, not archived) | Notes |
|---|---|---|---|---|
| `8887576e` | v1.14.0 | **CANONICAL — ACTIVE** | `production_data/decision_rulesets/manifest.json:464` (status="active"); `run_phase2_snapshot_delta.py:31` (`PHASE2_PINNED_RULESET_ID`); `run_screen_columns.py:444`; `data/snapshots/2026-05-06/rankings.csv` `decision_engine_ruleset_id` column; `agents/catalyst_delta/SOUL.md:36`, `agents/sentinel/SOUL.md:35`, `agents/shadow_monitor/SOUL.md:34`; `docs/research_training/biotech_ev_pretrade_artifact_map.md:27`; today's audit memo §1 risk #1 | The actual computed file hash (corrected from the phantom — see `622edb77`). Promoted 2026-05-04, hash-corrected 2026-05-05. |
| `2a3e79eb` | v1.13.0 | **RETIRED 2026-05-04** (per `manifest.json` status="retired" + `CLAUDE.md:24`) | 10 agent SOUL files (bioshort_watch, biotech_news_digest, calibration, company_news_ingest, fleet_steward, grok_biotech_watch, herald, earnings_calendar_sync, ops, options_watch, policy_shadow_watch, postmortem); `model_documentation.md` (4 lines: `:3, :112, :1338, :1718`); root MEMORY.md index ("Ruleset `2a3e79eb` (v1.13.0)"); 5 root governance MDs (INST_DELTA_Z_*, GROK_BIOTECH_WATCH_*, POLICY_SHADOW_*, repo_structure_inventory_*) | Was canonical 2026-04-06 → 2026-05-04. Now stale text in many places; not consumed by any live code path. |
| `622edb77` | v1.14.0 | **PHANTOM** — corrected to `8887576e` by commit `bd91b523d` (2026-05-05 11:36 ET) | 1 file: `INST_DELTA_Z_GOVERNANCE_LOG_2026_05_04.md` (3 lines: `:3, :28, :29`) | Was the initial computed hash of v1.14.0. After file edits on 2026-05-05 added `selector_config` fields (per manifest notes), the recomputed hash became `8887576e`. The 622edb77 reference in INST_DELTA_Z_GOVERNANCE_LOG was never updated post-correction. |
| `bebe73f8` | v1.10.0 | **HISTORICAL** (active 2026-03-09 → ~2026-04-06; retired pre-freeze) | `RULESET_CHANGELOG.md:41,63,65`; `production_data/decision_rulesets/manifest.json:289` (archived); test fixtures (`tests/test_acceptance_replay_ruleset.py:280,386`, `tests/test_pre_trade_ruleset_gate.py` ×9) — these are LEGITIMATE fixture references; **`agents/sentinel/memory/2026-05-05.md:5` ("Active ruleset: bebe73f8 (v1.10.0, promoted 2026-03-09)") — STALE** | Test fixtures using `bebe73f8` are valid (test data, not live state). The sentinel memory reference is the only LIVE-system anomaly: indicates `tools/ruleset_health_monitor.py` returned a stale baseline at 2026-05-05 17:15 run time. |

---

## 2. Canonical classification

**`8887576e` v1.14.0 is canonical.** Evidence:

- `production_data/decision_rulesets/manifest.json` shows `status: "active"` for `8887576e`; `2a3e79eb` and prior IDs are `status: "retired"`.
- All live execution code paths pin to `8887576e`:
  - `run_phase2_snapshot_delta.py:31` `PHASE2_PINNED_RULESET_ID = "8887576e"`
  - `run_screen_columns.py:444` same constant.
- Today's snapshot (`data/snapshots/2026-05-06/rankings.csv` `decision_engine_ruleset_id` column) stamps `8887576e` for every ticker.

The other IDs:

- `2a3e79eb` is **STALE** — referenced in many text/SOUL/memory locations but not consumed by any live code reader. Cosmetic divergence.
- `622edb77` is **PHANTOM** — does not exist as a live ruleset hash anywhere; existed only briefly between commits `26dd60744` (Mon May 4 22:35) and `bd91b523d` (Tue May 5 11:36).
- `bebe73f8` is **HISTORICAL** — legitimately appears in changelog and test fixtures; the only anomaly is its appearance in `agents/sentinel/memory/2026-05-05.md` as the supposed "active" ruleset on a date when `8887576e` was already canonical.

---

## 3. Audit trail — the rotation timeline

Captured here so any reconciliation can verify it has not been overwritten by later edits.

| Timestamp (ET) | Commit | Subject |
|---|---|---|
| 2026-05-04 22:35 | `26dd60744` | feat(ruleset): v1.14.0 coinvest-only selector — inst_delta_z zeroed (2026-05-04) |
| 2026-05-04 23:15 | `28b86b22a` | docs(governance): update CLAUDE.md for v1.14.0 ruleset promotion |
| 2026-05-05 08:02 | `c34e600d3` | fix(ruleset): promote PHASE2 pin to v1.14.0/622edb77 in run_screen_columns.py |
| 2026-05-05 10:54 | `980c02b55` | fix(manifest): register 622edb77 (v1.14.0) and retire 2a3e79eb (v1.13.0) |
| 2026-05-05 11:36 | `bd91b523d` | **fix(ruleset): correct v1.14.0 hash to 8887576e (was phantom 622edb77)** |

Also relevant:

- `INST_DELTA_Z_SIGNAL_HEALTH_GOVERNANCE_REVIEW_2026_05_04.md` and `INST_DELTA_Z_GOVERNANCE_LOG_2026_05_04.md` — formal governance documentation of the 2026-05-04 rotation. These document Option A (zero `inst_delta_z` selector weight, set `coinvest_score_z` to 1.00) with rationale tied to two-frame ALERT (ic_health_monitor + calibration_evidence).

The rotation was made under formal governance. **Whether it satisfied Checklist v2 specifically (FM + bootstrap + FDR + LOSO + year stab per `policy_alpha_freeze_2026_04_04.md`) is unclear from these files alone.** The governance logs cite IC degradation evidence and a coinvest comparator probe — that's signal-health evidence, not Checklist v2. Flagging this as a freeze-regime question for human review (see §5).

---

## 4. 100% blast cross-check (2026-05-05)

The audit's 100% blast finding (`logs/blast_radius.log`: "Tickers with any field change: 297/297" on 2026-05-05) is **expected and explained** — not an anomaly.

The v1.14.0 promotion zeroed `inst_delta_z` weight in the selector and re-weighted `coinvest_score_z` from 0.65 → 1.00. Every ticker's selector score depends on these weights, so every score recomputed → every rank could change → 100% blast is consistent with rotation event semantics.

Distinguishability against feature-input changes: rotation moves ranks but typically NOT all scores by identical deltas; per-ticker delta should track the ticker's prior `inst_delta_z` magnitude (those with high |inst_delta_z| move most). A spot-check of `data/snapshots/2026-05-05/` rank changes against ticker `inst_delta_z` magnitudes would confirm; deferred (read-only scope).

**Verdict:** rotation event, not silent data drift. No additional concern from the blast itself.

---

## 5. Decision matrix — H1 / H2 / H3

| Hypothesis | Verdict | Where it applies | What follows |
|---|---|---|---|
| **H1: stale memory** | **TRUE** for 2a3e79eb references | MEMORY.md index line, `model_documentation.md`, project-root governance MDs, 10 agent SOULs | Step A applies (§6) |
| **H2: inconsistent producers / stamp-at-write divergence** | **PARTIALLY TRUE** | The CANONICAL stampers (manifest, run_phase2_*.py, run_screen_columns.py, rankings.csv producer) are aligned at 8887576e. **But** `tools/ruleset_health_monitor.py` (called by sentinel) is producing a `bebe73f8` baseline reference — that's a stale READER, not a stamper | Step C applies (§6) for the sentinel reader path; nothing else |
| **H3: phantom hash** | **TRUE** but **already resolved at the canonical layer** by commit `bd91b523d` | The phantom `622edb77` only persists in INST_DELTA_Z_GOVERNANCE_LOG_2026_05_04.md (3 lines) | Step A applies for that one file (text correction) |

There is also a fourth implicit hypothesis the spec did not anticipate: **H4 — agent SOULs not synced after rotation.** Out of 28 active agents, only 3 SOULs (`catalyst_delta`, `sentinel`, `shadow_monitor`) reference the new `8887576e`; 11 still reference the retired `2a3e79eb`. This is symptomatic of an ad-hoc per-agent SOUL update process rather than a centralized re-templating; the system functions correctly because SOULs are LLM-context text, not runtime config — but it's a real consistency liability.

---

## 6. Reconciliation plan (NOT IMPLEMENTED — pending approval)

Three layers of edits, separable and rollback-safe. Each must be approved independently.

### Step A — Memory / documentation text updates (low risk, no code, no scoring)

Pure cosmetic synchronization. Risk: **none to scoring**, low to documentation fidelity (could miss a file).

**A.1** Auto-memory: update MEMORY.md index entry under "Production Model Identity (2026-04-06) [FROZEN]" to read `Ruleset 8887576e (v1.14.0)` (was `2a3e79eb (v1.13.0)`). Optionally append a one-liner noting the 2026-05-04 promotion zeroed inst_delta_z in selector. The model-identity file `scoring_model_identity_2026_04_06.md` itself does not state a specific ID — its description ("inst_delta_z prunes") is now inaccurate post-rotation; either retag the file with a `supersedes` note OR add a sibling memory entry for the v1.14.0 update.

**A.2** Project-root `model_documentation.md` lines `:3, :112, :1338, :1718` — update `2a3e79eb` → `8887576e`, `v1.13.0` → `v1.14.0`. Note per memory `feedback_model_doc_location.md` the canonical doc location is `docs/MODEL_DOCUMENTATION.md`, not the root file — verify which one is canonical before editing.

**A.3** 11 agent SOUL files: change `ID: 2a3e79eb (v1.13.0)` → `ID: 8887576e (v1.14.0)`. Files: `bioshort_watch`, `biotech_news_digest`, `calibration`, `company_news_ingest` (deprecated — skip if retiring per agent-fleet audit P3), `fleet_steward`, `grok_biotech_watch`, `herald`, `earnings_calendar_sync`, `ops`, `options_watch`, `policy_shadow_watch`, `postmortem`.

**A.4** `INST_DELTA_Z_GOVERNANCE_LOG_2026_05_04.md` lines `:3, :28, :29` — append a correction note that `622edb77` was the initial-commit phantom hash, corrected to `8887576e` on 2026-05-05 (cite commit `bd91b523d`). Do NOT delete the phantom references — they are part of the audit trail.

**A.5** Project-root governance MDs (5 files): GROK_BIOTECH_WATCH_CRON_MISCONFIG_2026_05_03.md, INST_DELTA_Z_SIGNAL_HEALTH_GOVERNANCE_REVIEW_2026_05_04.md, INST_DELTA_Z_GOVERNANCE_LOG_TEMPLATE_2026_05_04.md, POLICY_SHADOW_COMPARE_FRESHNESS_AUDIT_2026_05_03.md, POLICY_SHADOW_AND_REVIEW_QUEUE_REGISTRY_MISMATCH_2026_05_03.md, repo_structure_inventory_2026_04_26.md — these are dated point-in-time docs. Standard practice would NOT retroactively edit them; instead append a top-of-file note: "Ruleset rotated to 8887576e (v1.14.0) on 2026-05-04; references below are point-in-time."

### Step B — Reader code alignment (medium risk; only one location)

**B.1** None at the canonical layer — the live readers (`run_phase2_snapshot_delta.py`, `run_screen_columns.py`, manifest, rankings producer) all read/stamp `8887576e` correctly.

**B.2** `tools/ruleset_health_monitor.py` — **sentinel's tool produced a stale `bebe73f8` baseline in its 2026-05-05 17:15 run.** Investigation needed to find the source: does the tool read from a hardcoded constant, an old receipt path, the manifest, or some cached file? The 2026-05-05 run's `bebe73f8` appears to come from the `gate` structure (per `tools/ruleset_health_monitor.py:155-165`), which extracts baseline from a "promotion receipt." If the tool is reading the wrong receipt (e.g., the bebe73f8 promotion receipt from March 9, never replaced), this is a real reader bug that misled sentinel.

**Risk:** any change here must verify it does not break sentinel's drift detection. Snapshot row-hash comparison pre/post would confirm cosmetic-only.

### Step C — Stamp-at-write code (low risk)

**C.1** None needed — every snapshot already stamps `decision_engine_ruleset_id=8887576e`. No ARTIFACT-LOCAL diverging stamper found.

---

## 7. What NOT to do

- **DO NOT** edit `production_data/decision_rulesets/manifest.json` — it is correct (`8887576e` active, others retired).
- **DO NOT** modify `production_data/ranker_v2_model.json` (correctly reflects deployed_live_pilot variant; ranker unchanged across the v1.13.0→v1.14.0 selector-only rotation).
- **DO NOT** touch `common/ranker_active_contract.py`.
- **DO NOT** "promote" or "rotate" any ruleset under the guise of reconciliation — this entire memo is a SYNC of stale text to canonical, not a model change.
- **DO NOT** retroactively edit dated governance MDs (Step A.5 caveat); append-with-note instead.
- **DO NOT** auto-update the sentinel agent's memory file — investigate the `tools/ruleset_health_monitor.py` source-of-baseline first (Step B.2). Editing the memory without fixing the producer just hides the bug.
- **DO NOT** delete the `622edb77` phantom references from the May 4 governance log — they document that a phantom existed, which is information that may be needed for future audits.
- **DO NOT** assume the v1.14.0 promotion satisfied Checklist v2. The freeze regime requires it (per `policy_alpha_freeze_2026_04_04.md`). The 2026-05-04 governance docs document IC-degradation evidence (ic_health_monitor + calibration_evidence) and a coinvest comparator probe — which is **not** Checklist v2 (FM + bootstrap + FDR + LOSO + year stab). **This is a freeze-regime compliance question that needs human review, separate from this reconciliation.**

---

## 8. Tests / smoke for any reconciliation code change

If Step B.2 (`tools/ruleset_health_monitor.py`) lands later:

- **Cosmetic-only verification:** run `tools/ruleset_health_monitor.py` against the live manifest; confirm reported "Active ruleset" is `8887576e`, not `bebe73f8`.
- **Snapshot row-hash invariance:** rerun `tools/build_rank_change_monitor.py` against `data/snapshots/2026-05-06/`; row hashes should be byte-identical pre/post the change.
- **Sentinel re-invoke:** trigger `agents/sentinel` HEARTBEAT and confirm new `agents/sentinel/memory/<today>.md` reports `8887576e`.
- **Drift detection still works:** introduce a temp manifest with a fake new ID; confirm `ruleset_health_monitor.py` flags drift correctly.

If Step A.x lands (text only): no smoke needed beyond `git diff` review and `grep -rn '2a3e79eb'` to confirm no live code paths were touched.

---

## 9. Recommendation summary (ranked, none implemented)

1. **Investigate first, edit second.** Step B.2 (sentinel's stale baseline reader) is the most consequential finding — it indicates a runtime READER is producing stale data, not just stale text. Identify the source-of-baseline before any text edits.
2. **Step A.1 (memory of record)** is the highest-value text edit — keeps future-Claude oriented to the canonical ID.
3. **Step A.3 (agent SOULs)** is high-touch but low-risk; can be done as one batch commit.
4. **Step A.4 (phantom 622edb77 correction note)** is one-file, fast.
5. **Step A.2 + A.5** depend on confirming the canonical doc location for `model_documentation.md` and the convention for retroactive edits to dated MDs.
6. **Separate concern:** verify whether the 2026-05-04 v1.14.0 promotion satisfied Checklist v2. If not, this is a freeze-regime violation that supersedes the reconciliation question. **NEEDS_HUMAN_REVIEW.**

---

## 10. Out-of-scope confirmations

- **No selector / ranker / EV / sizing changes.** None of the proposed edits touch scoring code, weights, manifest, ranker model, or any production cron.
- **No agent retirement.** Spec 084 does not propose deleting `company_news_ingest` (handled in Spec 085 / agent fleet audit P3).
- **No bioshort upstream investigation.** That belongs to the date-stamp P2 ticket (referenced by Spec 083 §6).
- **No P1 reductions.** Held per user direction.

---

_Generated by Spec 084 read-only investigation. Implementation gated on user approval AND user confirmation of the canonical ID._

# Hermes Skill Harvest Log

Auto-maintained by the daily skill harvester cron job (Hermes).
Each entry records git activity reviewed, sessions searched, and skill patches applied.

---

## 2026-06-16 (Hermes registry + Cloud staleness refresh)

### Agent profiles / skills / memory follow-up
- **screener-ops:** registry profile line updated to 31 directories = 29 active + 2 deprecated; mirror synced.
- **memory layer:** HOT/WARM learnings updated for CodeGraph v0.9.9 and registry bidirectional invariant.
- **memory-steward:** deployment/profile guidance reconciled across `docs/hermes_skills/memory-steward.md` and `.hermes/skills/devops/memory-steward.SKILL.md`.
- Ran `python3 tools/audit_learnings.py` — no stale hints or compaction issues.

### Hermes sync/audit
- Ran `python3 tools/sync_hermes_skills.py --register-meta` and `python3 tools/sync_hermes_skills.py` — 32 registered Hermes docs, 19 cursor mirrors unchanged/skipped except `screener-ops` after CodeGraph pin refresh.
- Ran `python3 tools/audit_hermes_skills.py` — all Hermes `.md` files registered, source_authority complete, no mirror drift.

### Registry and runtime authority
- **agent_roster.md / agent-registry-reference.md:** registry-aligned counts now show 31 directories = 29 active + 2 deprecated (`bioshort_watch`, `shadow_watch`).
- **openclaw-session-routing-debug.md:** retired gateway-zombie guidance now handles retained `status=deprecated` directories.
- **HERMES_OPERATIONAL_PROFILE.md:** distinguishes repo audit counts (32 skill docs, 29 active agents + 2 deprecated workspaces) from conceptual operator-host layers.
- **screener-ops:** CodeGraph pin refreshed to v0.9.9 to match `.cursor/environment.json` and `docs/CODEGRAPH_RUNBOOK.md`.

### Governance
- Docs/metadata/heartbeat plumbing only. No selector, ranker, sizing, final score, decision engine, KG, cron, or runtime scoring changes.

---

## 2026-06-07 (Hermes taxonomy + learning loop refresh)

### Hermes-native docs
- **hermes_tools_map.md**: baseline `ec4b2726`; `audit_learnings`, skills telemetry + learning loop v2; 32-skill audit expectation; WSL sequence updated
- **hermeslink-state-capture.md**: fleet count fixed (29 active); skills learning tools; PR #322 merged state
- **agent_roster.md**: date refresh; registry count aligned
- **operator_host_skills.md**: 32/32 audit; skills learning telemetry index

### Skill mirror
- **screener-ops**: baseline `ec4b2726`; checklist 32/32

### Governance
- Docs/tooling only. No ranker, selector, sizing, or scoring changes.

---

## 2026-06-07 (repo scale + skills refresh)

### Skill sources refreshed
- **screener-ops**: Repo scale orientation table (~4k engines / ~176k production / ~750k total); baseline `main` @ `31a74d42`; `audit_learnings.py` in WSL gate Phase 1 + sync workflow
- **selector-ranker**: Codebase context — compact high-leverage engines; governance tier unchanged
- **codegraph**: baseline `31a74d42`, index file count note
- **self-improving**: Distill step → memory bootstrap block
- Ran `sync_hermes_skills.py` — updated mirrors

### Governance
- Skills/docs only. No ranker, selector, sizing, or scoring changes.

---

## 2026-06-01 (HOT memory optimization)

### Memory layer
- **`memory.md`**: bootstrap-first table (recursion, CodeGraph, host, governance); deduped ops; Pattern-Key tags
- **`archive/README.md`**: COLD tier demotion policy
- **LRN-20260329-001**: Status → promoted (raw_count_size_confound already in HOT)
- **`audit_learnings.py`**: bootstrap line count, HOT Pattern-Keys, LRN/HOT mismatch, compaction hints
- **README.md** + **self-improving** Rule 6: memory optimization principles

### Governance
- Memory/docs/tooling only.

---

## 2026-06-01 (knowledge recursion stack)

### Knowledge layer
- **`.learnings/README.md`**: agent knowledge stack map, load order, promotion rules
- **`.learnings/domains/agent_ops.md`**: WARM Hermes/Cursor/Cloud authority patterns
- **`tools/audit_learnings.py`**: read-only tier audit, Pattern-Key promotion candidates, stale hints
- **`tests/test_audit_learnings.py`**: parser + report smoke
- Updated `memory.md`, `LEARNINGS.md` (LRN-20260601-001..003), `projects/biotech_screener.md`
- **self-improving** skill/REFERENCE: `audit_learnings.py` in session-end workflow

### Governance
- Knowledge/docs/tooling only. No ranker, selector, sizing, or scoring changes.

---

## 2026-06-01 (recursive self-improvement loop)

### Skill sources refreshed
- **self-improving** (`skills/self-improving/SKILL.md`): biotech-screener recursive loop (Observe→Log→Distill→Promote→Skill-patch→Sync→Verify); Rule 10 governance; session-end trigger
- **self-improving-reference** (`skills/self-improving/REFERENCE.md`): LRN/harvest templates, session-end audit, skill-patch checklist
- **screener_ops**, **codegraph**, **openclaw-agent-optimize**: cross-links to recursion loop
- **operator_host_skills.md**: index row for self-improving + REFERENCE mirror
- **sync_hermes_skills.py**: register `self-improving-reference.md` in REFERENCE_MAP
- `.learnings/projects/biotech_screener.md`: skill recursion meta + codegraph 0.9.7 note
- Ran `sync_hermes_skills.py` — updated mirrors

### Governance
- Skills/docs only. No ranker, selector, sizing, or scoring changes.

---

## 2026-06-01 (WSL acceptance gate + CodeGraph bounds)

### Skill sources refreshed
- **screener-ops** (`skills/screener_ops/SKILL.md`): full operator WSL acceptance gate (Phases 0–4); gateway model check; Spec 087 B1b cron/artifact criteria; first-fire seed note; printable checklist; baseline `main` @ `0bac216a` (#332–#334)
- **codegraph** (`skills/codegraph/SKILL.md`): surface split table; four-step operating rule; practical CLI examples; baseline `0bac216a`
- **operator_host_skills.md**: WSL acceptance gate index row
- Ran `sync_hermes_skills.py` — updated `screener-ops.md`, `codegraph.md`

### Governance
- Skills/docs only. No ranker, selector, sizing, or scoring changes.

---

## 2026-05-31 (Cursor skills knowledge)

### Skill sources refreshed
- **screener-ops** (`skills/screener_ops/SKILL.md`): Hermes model routing table (MCP / Lane A / gateway / SOUL / `run_agent_direct.py`); plumbing baseline `main` @ `8dbd1b9c` (#326–#331); Cursor sync workflow table
- **codegraph** (`skills/codegraph/SKILL.md`): baseline `8dbd1b9c`; pointer to `hermes_tools_map.md`
- **operator_host_skills.md**: Cursor skills knowledge index (sync, audit, model doc links)
- Ran `sync_hermes_skills.py` — updated `screener-ops.md`, `codegraph.md`

### Governance
- Skills/docs only. No ranker, selector, sizing, or scoring changes.

---

## 2026-05-30

### Sync (Cursor Cloud agent)
- Ran `python3 tools/audit_hermes_skills.py` — 31/31 Hermes docs registered in `_meta.json`
- Ran `python3 tools/sync_hermes_skills.py --register-meta` — 19 cursor mirrors unchanged; `memory-steward` skipped (Hermes-authoritative)
- **screener-ops**: Town-Hermes bridge status refreshed (Phase B wiring complete 2026-05-27; live delivery pending)
- **town-operator-bridge**: Phase B call-site table updated (4 DONE, 2 TODO)
- **operational-state.md**: Hermes Skills Hub sync state block updated

### Governance
- Tooling/docs only. No ranker, selector, sizing, or scoring changes.

---

## 2026-05-31 (Hermeslink)

### hermeslink-state-capture skill refresh
- Updated `docs/hermes_skills/hermeslink-state-capture.md` for 2026-05-31: host authority table, Phase B Town egress, full run cycle, 34-agent fleet, separation from `build_knowledge_graph.py`
- Ran `build_hermes_knowledge_layer.py` on Cloud (UNKNOWN_CLOUD_ENV; 0 hard contradictions)

---

## 2026-05-31 (Hermes update)

### Code fixes (PR #322)
- Fixed `build_hermes_knowledge_layer.py` repo `sys.path` for `town_bridge_events` import
- Fixed MCP `knowledge_read(contradiction_ledger)` to prefer `latest.md`
- MCP regression test + harvest log

---

## 2026-05-30 (OpenClaw doc refresh)

### OpenClaw / Hermes taxonomy
- **hermes_tools_map.md:** §5 OpenClaw gateway (Lanes A/B/C, `run_openclaw.sh`, debug skills, post-#326 cleanup)
- **openclaw-session-routing-debug.md:** 29-agent fleet; Class G updated for repo-removed agents
- **openclaw-agent-scope-audit.md:** `policy_shadow_watch` marked resolved → `shadow_monitor`
- **hermeslink-state-capture.md:** agent counts 29 active (registry-aligned)
- **agent_roster.md:** debug skills line 29-agent; tools map cross-link

### Agent & bridge gaps addressed (earlier same day)
- **agent_roster.md:** Split repo fleet (29 agents after #326, `AGENT_REGISTRY.json`) vs Hermes scheduler jobs
- **Town-Hermes Phase B:** `common/town_bridge_events.py`; `cron_missed` from `ops_supervisor` + `cron_watchdog`; `contradiction_detected` from knowledge layer + `hermes-contradiction-detector`
- **Registry:** Added `hermes-contradiction-detector` (31 active agents)
- **Tests:** `tests/test_town_bridge_events.py`
- **Docs:** `town-operator-bridge.md` operator live-email checklist; `hermes-context.mdc` fleet count

### Governance
- Plumbing/ops only. No ranker, selector, sizing, or scoring changes.

---

## 2026-05-06

### Git activity (past 24h)
- **biotech-screener**: 30 commits reviewed
  - `8aa6d5f0` docs(specs): add investment logic audit follow-up backlog (specs 078-082)
  - `67efd1b2` Add hermes-operator Claude Code subagent for job/scheduler management
  - `ee1c9970` chore: disk cleanup batch 1+2A — remove stale artifacts, orphaned worktree, safe cache
  - `fee9b10e` Backup Hermes memory-steward skill to repo (.hermes/skills/)
  - `5c284ab7` fix: correct Morningstar scores_by_ticker inner key (second ms_* bug)
  - `dd002964` Add memory-steward Claude Code subagent for audit-gated cleanup
  - `ff4b7c64` chore: remove catalyst_source_filed_at dead schema field
  - `e70ae626` fix: restore Morningstar enrichment field mapping
  - `feba3a64` docs(audit): spec_076 schema prune audit — audit only, no removals
  - `7f02f79e` docs: spec_074 financial_score evidence memo + spec_075 inst_delta checkpoint
  - `df5a59f0` feat(ev): bind event_ev_p_hit into resolution records (shadow-only)
  - `d97a5cc7` ops(heartbeat): fix production_qa false-alarm STALE at 17:30 ET
  - `70049dd0` ops(heartbeat): fix review_queue_steward + policy_shadow_watch receipt noise
  - `9f3b91ea` ops(agents): fix memory-write for catalyst_delta, event_analyst, shadow_monitor
  - `7ac2ceee` ops(sentinel): re-anchor to v1.14.0 (8887576e)
  - (+ 15 more: populate_ir_sources, price data audit, financial data fixes, EV docs, etc.)
- **asset-allocation**: 1 commit
  - `5977b19` docs(tracking): MODE A sync 2026-05-05 — 386 tests, 1 ruff error, governance flag on 3 fix() commits

### Sessions reviewed: 8
- `20260506_081523_d685ae` — IR URL population scoping (Option 3 EDGAR-sourced recommended)
- `20260506_071508_448d23` — Fleet triage + policy_shadow backfill + grok email credential incident
- `20260505_214736_9bfa43` — Mode B audit: score_rank_pct WARN Day 2, sentinel misanchored
- `20260505_131955_90c115` — Class C + G confirmed for openclaw-cron-scheduler-debug
- `cron_4f360d005436_20260505_180021` — Fleet triage: memory-write watchdog run, v1.14.0 stability spike diagnosed
- `20260504_143458_159c55` — Fleet triage: 2026-05-02 production miss root-caused (crontab REPLACE)
- `cron_4f360d005436_20260503_024000` — Fleet triage: WSL2 sleep + 8 OAuth expired profiles
- `20260503_110735_3d31d4` — inst_delta_z governance memo, coinvest shared-regime check

### Skill patches
- **openclaw-data-pipeline-debug**: Class I added — Morningstar silent double-bug (`run_screen.py` wrong inner key `.get("scores")` vs `.get("scores_by_ticker")`). Confirmed 2026-05-06 commits `e70ae626` + `5c284ab7`. Both bugs independent + both silent.
- **openclaw-data-pipeline-debug**: Class G extended — score_rank_pct WARN Day 3+ escalation protocol added. Confirmed structural degradation from mid-February; escalation packet template with GOVERNANCE CEILING rule added. ic_health_monitor cron dependency noted (no standalone cron).
- **openclaw-data-pipeline-debug**: Routing table updated with Class I + WARN signal escalation path.
- **memory-steward**: Orphaned `.claude/worktrees/` added to known bloat patterns. Confirmed 235 MB reclaimed 2026-05-06 (`ee1c9970`). Audit step 7 updated with worktree orphan detection commands.
- **openclaw-agent-scope-audit**: Class G added — dead schema field / spec-076 pruning pattern. `catalyst_source_filed_at` as confirmed instance (commit `ff4b7c64`). Includes diagnostic recipe + safe-to-cut classification rules.

### New skills created: none

### Files synced to docs/hermes_skills/
- openclaw-data-pipeline-debug.md (patched)
- memory-steward.md (patched)
- openclaw-agent-scope-audit.md (patched)
- references/ir_url_population.md (from ~/.hermes/skills/devops/openclaw-data-pipeline-debug/references/)

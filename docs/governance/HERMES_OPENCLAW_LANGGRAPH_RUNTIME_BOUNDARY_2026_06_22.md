# Runtime Boundary Map — Hermes / OpenClaw / LangGraph / Semgrep / OS cron

**Date:** 2026-06-22
**Author:** Claude Code (containment-first Hermes upgrade, Package B)
**Purpose:** Document *who can do what* across every live and legacy execution surface, so new tools (Package C `biotech-mcp`, Package D/E external MCPs) are added against a known boundary — not a guess. Companion to `docs/incidents/INC_2026_06_20_AUTOPUSH_CLOSEOUT_2026_06_22.md` (Package A).
**Evidence basis:** direct inspection of `~/.hermes/cron/jobs.json` (23 jobs), `~/.openclaw/` (configs, exec-approvals, runs), `crontab -l` (49 jobs), `~/.hermes/config.yaml`, `hermes security`, repo git state. Audit date HEAD `2d3f54ea`.

---

## 1. Capability matrix

| Capability | **Hermes** (gateway :8642) | **OpenClaw** (gateway :19001) | **LangGraph LG3** | **OS cron** | **Semgrep** |
|---|---|---|---|---|---|
| **Write files** | ✅ `file` toolset on ~20 jobs → repo workdir, `logs/`, `artifacts/`, `docs/hermes_skills/` | ⚠️ latent (sandbox file access) but **not firing** | ✅ artifacts only (`artifacts/scientific_cartography/`) | ✅ `logs/`, `artifacts/`, snapshots | ❌ analysis only |
| **Schedule work** | ✅ **owns the live scheduler** (`~/.hermes/cron/jobs.json`, 22 enabled jobs) | ❌ **dormant** — no live `jobs.json` (only `.migrated`/`.bak`), no run since 06-17 | ▫️ scheduled *by* OS cron, owns nothing | ✅ 49 recurring jobs | ❌ |
| **Run shell** | ✅ `terminal` toolset on ~20 jobs | ⚠️ gated — exec-approval allowlist = **read-only binaries only** (`python3/ls/cat/head/tail/grep/find/wc`) | ▫️ runs as a python script, not an agent | ✅ (it *is* shell) | ❌ |
| **Touch git** | ⚠️ **YES in practice** (see §3) — most jobs read git; harvester pushed 3× (now paused) | ⚠️ capability in `github` skill (6 sandboxes) but **triple-gated** (no schedule + no runs + `git`/`gh` not allowlisted) | ❌ forbidden (no automation, no production hook) | ❌ no job touches git (verified) | ❌ |
| **Call network** | ✅ web/MCP capable; `api-429-watcher` hits external APIs | ⚠️ web/browser skills present but dormant | ❌ | ⚠️ data-refresh jobs hit yfinance/SEC/news APIs | ❌ |
| **Own memory** | ✅ Hermes memory + `memory-steward-weekly-audit` (read-only) | ⚠️ legacy `~/.openclaw/memory` (mid-migration to Hermes) | ❌ | ❌ | ❌ |
| **Own skills** | ✅ `~/.hermes/skills/` + `skill_manage` (harvester patches/syncs to `docs/hermes_skills/`) | ⚠️ legacy `~/.openclaw/workspace/skills/` + sandbox skills | ❌ | ❌ | ❌ |
| **Status** | 🟢 **current orchestrator** | 🔴 **legacy — fence or retire** | 🟢 live governed subsystem | 🟢 production scheduler | 🟡 emerging guardrail |

Legend: ✅ yes / ⚠️ conditional or latent / ▫️ N/A or indirect / ❌ no.

---

## 2. The eight boundary questions (direct answers)

- **Who can write?** Hermes (broadly, via `file` toolset), OS cron (pipeline outputs), LangGraph (diagnostic artifacts only). OpenClaw *could* but is dormant.
- **Who can schedule?** Only two live schedulers: **Hermes** (`~/.hermes/cron/jobs.json`) and **OS cron** (`crontab`). OpenClaw's scheduler is dormant. LangGraph does not schedule itself — OS cron invokes it.
- **Who can run shell?** Hermes cron agents (`terminal` toolset, ~20 jobs) and OS cron. OpenClaw is gated to read-only binaries.
- **Who can touch git / push to `main`?** **In practice: only the Hermes harvester did — and it is now paused.** No other live job pushes. OpenClaw's `github` skill is a latent, triple-gated capability. OS cron, LangGraph, Semgrep cannot. **There is currently no enabled, scheduled job that pushes to `main`.**
- **Who can call network?** Hermes (web/MCP/APIs), OS cron data-refresh jobs (yfinance/SEC/news), OpenClaw (latent/dormant).
- **Who owns memory?** Hermes (authoritative going forward); OpenClaw memory is legacy and mid-migration; `memory-steward-weekly-audit` audits read-only.
- **Who owns skills?** Hermes (`~/.hermes/skills/`, synced to `docs/hermes_skills/`). OpenClaw skills are legacy.
- **Who is deprecated?** **OpenClaw** — it is the legacy executor; its scheduler is dormant and migration to Hermes is incomplete. It still runs as a gateway (:19001) but fires no scheduled work.

---

## 3. The git-push control gap (most important finding)

Hermes `approvals` config (`~/.hermes/config.yaml`):
```
approvals:
  mode: manual          # interactive sessions prompt for approval
  cron_mode: deny        # cron context cannot obtain interactive approval
  subagent_auto_approve: false
  destructive_slash_confirm: false
command_allowlist:
- script execution via -e/-c flag
- shell command via -c/-lc flag     # ← shell exec is ALLOWLISTED
```

**The gap:** `mode: manual` + `cron_mode: deny` reads as "cron jobs cannot run approval-gated commands." **But the `command_allowlist` pre-approves shell-via-`-c`**, so a cron agent's `git push` executes *without* hitting the approval gate. The empirical proof: `weekly-skill-harvester` completed **3 autonomous pushes** (`repeat.completed: 3`, `last_status: ok`). 

➡️ **Do not treat `cron_mode: deny` as the control.** Any of the ~20 `terminal`-enabled Hermes cron jobs can push if re-prompted to, because the shell allowlist bypasses approval. The only durable backstops are: (a) pausing/scoping individual jobs, and (b) a **`pre-push` hook on `main`** (Package work-plan step 3, not yet installed). Branch protection — the real fix — is impossible on the free GitHub plan.

---

## 4. Per-runtime detail

### Hermes — current orchestrator (🟢)
- **Gateway:** `:8642`, pid 401495, `{"status":"ok"}`. Version **v0.15.1** (1 commit behind).
- **Scheduler:** 23 jobs; 22 enabled, **1 paused** (`weekly-skill-harvester`, per Package A). All workdir = the repo. Jobs are diagnostic/governance monitors (ledgers, watchers, briefings, audits) — see `hermes cron list`.
- **Confirmed read-only jobs:** `hermes-run-ledger-supervisor` ("Do not run hermes cron, openclaw commands, or git. Read-only report only"), `memory-steward-weekly-audit`, `pr-review-daily` ("Do not merge, close, or comment. Report only"), `alpha-verdict-ledger`, `inst-delta-z-recovery-watcher`.
- **Security:** `hermes security` reports **48 known vulns / 102 components**, incl. **HIGH `hermes-agent==0.15.1` DNS-rebinding in WebSocket endpoints (GHSA-4pqm-j46f-795x, fixed in 0.16.0)**, plus HIGH cryptography/PyJWT/starlette/urllib3. The gateway binds `0.0.0.0:8642` (LAN-exposed) — DNS-rebinding risk is live. **Recommend `hermes update` to ≥0.16.0** as part of the security posture (Package E-adjacent).

### OpenClaw — legacy, recommend retire/fence (🔴)
- **Gateway:** `:19001`, node pid 7171, active SQLite WAL. Up, but **scheduler dormant** (no live `jobs.json`; runs all `.migrated`, newest 06-17 08:05).
- **Push capability:** `github` skill (`git push`, `gh pr create`, `gh pr merge --squash`) present in 6 agent sandboxes (`ops/sentinel/qa/shadow_watch/bioshort_watch/calibration`). **Triple-gated:** (1) no live schedule fires them, (2) no run since 06-17, (3) `git`/`gh` absent from exec-approval allowlist (read-only binaries only).
- **Decision (recommended):** **Retire** the executor role (migration to Hermes is the stated medium-term direction) or, short-term, **fence** it: keep `git`/`gh` off the allowlist, do not restore a write-capable `jobs.json`, strip push verbs from the `github` SKILL.md of agents that don't need them. Do **not** add new Hermes profiles until OpenClaw's role is resolved.

### LangGraph LG3 — live governed subsystem (🟢)
- **Invocation:** OS cron `5 8 * * *` → `tools/run_scientific_cartography_scheduled_review.py --auto-run-latest`. Mode: `READ_ONLY_DIAGNOSTIC`, `NON_BLOCKING`, `MODE_B_CRON_COMPATIBLE`.
- **Forbidden list (holds):** no cron-as-automation escalation, no dashboard, no production hook, no agent summarization; `automation_approval` immutably `False`. Review-workflow-approval-only — never automation. Append-only JSONL artifacts.
- **Status:** observation window live to **~2026-07-03**; no LG4/LG5 until checkpoint. No write-to-`main` path.

### OS cron — production scheduler (🟢)
- 49 jobs: data refresh, snapshot/production pipeline, news digests, bellringer, watchdogs, diagnostics, Hermes knowledge layer (`build_hermes_knowledge_layer.py`), `hermes-held-spec-ledger`, LG3. **None touch git** (verified by full enumeration). Writes to `logs/`, `artifacts/`, `data/snapshots/`.

### Semgrep — emerging guardrail (🟡)
- ERROR-blocking **local pre-commit** + WARN on-demand; CI workflow `semgrep-governance-audit.yml` exists but **CI is dead** (Actions budget exhausted) → local-only enforcement. This is the closest existing analog to the Package D/E MCP-intake security gate.

---

## 5. Decisions this map forces (before Package C)

1. **OpenClaw: retire or fence?** — recommend *fence now, plan retire*. Blocks new Hermes profiles until resolved.
2. **Install `pre-push` guard on `main`** — the only durable backstop given the §3 shell-allowlist gap and absent branch protection. (Work-plan step 3.)
3. **`hermes update` to ≥0.16.0** — closes the HIGH DNS-rebinding vuln on the LAN-exposed gateway. Stage behind a smoke test (do not auto-update mid-containment).
4. **Future autopush audits must check both agent schedulers** (`~/.hermes/cron/jobs.json` *and* `~/.openclaw/cron/`), not just `crontab -l`. (Lesson from Package A.)

---

## 6. Disposition
- Package B: **complete.** Boundary documented and fact-checked.
- Next (work-plan order): **(3) install the `pre-push` guard**, then **(C) build the read-only `biotech-mcp`**.
- Tracked at `docs/governance/`; durable mirror in `~/governance_package_2026_06_21/`. Not pushed.

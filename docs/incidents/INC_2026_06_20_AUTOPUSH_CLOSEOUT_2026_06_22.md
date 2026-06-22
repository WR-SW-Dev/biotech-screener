# INC-2026-06-20-AUTOPUSH — Closeout / Vector Audit

**Date:** 2026-06-22
**Auditor:** Claude Code (containment-first Hermes upgrade, Package A)
**Repo HEAD at audit:** `afced5d4` (branch `langgraph-review-artifact-dir-none-guard-2026-06-22`)
**Scope:** Prove or disprove an *active* automated write-to-`main` path before any new tool/integration is added. This is the mandatory gate (Package A) preceding runtime-boundary mapping (B), `biotech-mcp` (C), and external MCP intake (D/E).

---

## VERDICT

```
AUTOPUSH_VECTOR_FOUND_AND_PAUSED
Package A gate: SATISFIED ONLY FOR PROCEEDING TO PACKAGE B
```

**An active autonomous push-to-`main` vector was found and has been paused.** The Hermes cron job `weekly-skill-harvester` (`~/.hermes/cron/jobs.json`, id `a15dbdcb6f41`) was `enabled: true`, scheduled `0 20 * * 1`, `next_run_at 2026-06-22T20:00:00-04:00`, with `terminal` in its toolset and the repo as workdir. Its prompt **Step 8 executes `git checkout main && git pull --ff-only && git add docs/hermes_skills/ && git commit && git push`** under the explicit instruction *"Work autonomously — no approval needed."* — the same mechanism as INC-2026-06-20-AUTOPUSH. It had run 3× (last 06-17, ok).

**Action taken (2026-06-22 13:14 EDT, operator-authorized):** `hermes cron pause weekly-skill-harvester`. Job now `enabled: false`, `state: paused` — confirmed in the live `jobs.json`. The other 22 Hermes jobs remain enabled and unaffected. The pause is fully reversible (`hermes cron resume weekly-skill-harvester`). It will **not** fire at 20:00.

**Gate status:** Package A is satisfied **only in the narrow sense of unblocking Package B**. It is *not* hard-closed — the job config still contains the push step, and the structural root cause (no branch protection, no CI) is unchanged. A pre-push defense-in-depth guard (Step 3 of the work plan) is required before the gate is durably closed.

> ⚠️ **Correction:** an earlier draft of this artifact recorded `NO_ACTIVE_AUTOPUSH_VECTOR_FOUND`. That was wrong — it was based on the OS crontab and the (genuinely dormant) OpenClaw scheduler, and missed the **Hermes** scheduler, which is live and ticking (`.tick.lock` 13:08, `agent.log` updated 13:00). The corrected verdict above stands.

Scope note: the harvester is **constrained to stage only `docs/hermes_skills/`** and is instructed never to touch production code/rulesets/crontab/.env. The risk is therefore narrower than the original incident (which committed code), but it is still an **unattended, no-approval `git push` to `main` on an unprotected branch with no CI** — exactly the control gap Package A exists to close.

---

## Acceptance criteria results

| Check | Required result | Finding | Status |
|---|---|---|---|
| Visible crons (OS) | No job capable of `git push` / branch / PR / skill auto-harvest push | 49 active OS cron jobs enumerated; **0** contain `git`/`push`/`harvest`/`branch`/`pr`/`gh`. All are read/build/diagnostic jobs writing to `logs/` and `artifacts/`. | ✅ PASS |
| Hidden schedulers | Check systemd timers, shell profiles, hooks, workflows, **Hermes scheduler** | User/system systemd timers all OS-default. Shell profiles clean. **BUT the Hermes cron scheduler (`~/.hermes/cron/jobs.json`, 23 enabled jobs) is LIVE and contains `weekly-skill-harvester`, which `git push`es to `main` autonomously.** | ❌ **FAIL — active push vector** |
| Repo hooks | No post-commit/post-merge/post-checkout auto-push | `post-checkout`, `post-commit`, `post-merge`, `pre-push` are stock **git-lfs** hooks; `pre-commit` is the standard pre-commit-framework runner (hosts the Semgrep ERROR block). **None push.** No pre-push guard exists to block the harvester. | ⚠️ PASS (hooks clean) / no guard |
| Hermes/OpenClaw jobs | No automatic write-to-main path | **OpenClaw** native scheduler is dormant (no live `jobs.json`, no run since 06-17; exec-approval allowlist = read-only binaries only, `git`/`gh` NOT allowlisted). **Hermes** scheduler is LIVE and runs `weekly-skill-harvester` (Mon 20:00, next fire 2026-06-22 20:00) which executes `git push` to `main` with "no approval needed." | ❌ **FAIL — Hermes harvester is an active write-to-main path** |
| LangGraph LG3 | Confirm forbidden list, observation window, no production-write escalation | LG3 cron present (`5 8 * * *`, reinstalled 06-22), `--auto-run-latest`, READ_ONLY_DIAGNOSTIC / NON_BLOCKING. Forbidden list (no cron-as-automation, no production hook, no agent summarization, `automation_approval` immutably False) holds. Observation window live to ~2026-07-03. No write-to-main path. | ✅ PASS |
| Repo history | Cleanup/classification of anything created in/near incident window | All incident-window commits classified below; integrated into `main` via operator PR-merge recovery (#354–#369). `herald_cache` (626 files / 59 MB) purged from git on 06-21 (`797f742d`). **No orphan or unexplained commits.** History *rewrite* (runbook §6) NOT performed — operator chose recover-and-merge over purge; the autopush-burst commits now live legitimately in `main` history. | ✅ PASS (classified; no rewrite) |

---

## The "weekly-skill-harvester" — CONFIRMED LIVE (memory was correct)

Memory flagged a re-armed `weekly-skill-harvester` auto-push-to-main vector. **This is confirmed accurate.** (An earlier pass of this audit incorrectly dismissed it after searching only the OS crontab and the repo — it lives in the *Hermes* scheduler, not the OS crontab.)

- **Live job:** `~/.hermes/cron/jobs.json` → `weekly-skill-harvester` (id `a15dbdcb6f41`), `enabled: true`, schedule `0 20 * * 1` (Mon 20:00), `next_run_at 2026-06-22T20:00:00-04:00`, `repeat.completed: 3`, `last_run_at 2026-06-17 ok`. Toolsets: `terminal, file, session_search, skills`. Workdir: the repo.
- **Push step (verbatim, Step 8):** `git checkout main && git pull --ff-only` → `git add docs/hermes_skills/` → `git commit -m "docs(skills): daily skill harvest …"` → `git push`. Header: *"auto-commit to the repo. Work autonomously — no approval needed."*
- **Self-imposed constraints in the prompt:** stage only `docs/hermes_skills/`; never modify production code/rulesets/crontab/configs/.env; never patch pinned skills; always commit on `main`. These reduce blast radius but are *prompt-level promises*, not enforced controls — an LLM agent can deviate, and there is no pre-push hook or branch protection to backstop it.
- Repo docs (`harvest_log.md`, `self-improving.md`) and the out-of-repo staging (`~/hermes_selfimprove_staging/`, no push code, manually gated) are *separate* from this — they are the skill-content side, not the scheduler.

**The mismatch the directive asked about ("in memory but not visible in crontab") is itself the finding:** the vector is invisible to `crontab -l` because it runs inside the **Hermes gateway's own scheduler**, which is a distinct surface from OS cron. Any future autopush audit must check `~/.hermes/cron/jobs.json` (and `~/.openclaw/cron/`), not just `crontab -l`.

---

## Incident-window commit classification (2026-06-19 → 2026-06-22)

**The autopush burst (root cause), 2026-06-20 20:26–22:57, author Darren Schulz:**
- `81c0c01d` feat: **MCP server + agent-driven cron jobs** ← the named vector
- `dd633986` feat: add MCP server, fix frontend backtest loading, fix cron scripts
- `39e502d0` feat: add pipeline scripts for cron automation
- `d64d8fb2` feat: interactive cell atlas web layer + pipeline scripts
- `12cd5b57` feat: score optimization — IC 0.0000 → 0.0623
- `90671163` feat: webhook receiver + event checker for FDA/CT.gov alerts
- `07ac134f` feat: multi-agent ensemble + webhook receiver + ensemble report
- `2f7ee14b` / `fdefcea9` WIP+index stash on `main` of LG4A static dashboard (uncommitted work captured)

**Recovery / cleanup, 2026-06-21:**
- `797f742d` security: remove 626 herald_cache files from git (59 MB)
- `d9531c7b` fix: restore deleted files from c16b6a3b + clean pycache
- `121b499c`, `b99403a1`, `171b4c6a`, `b7072266` recovery of audit docs / cartography / agent-workflow hardening / ensemble report

**Operator-merged hardening & hygiene, 2026-06-21 → 06-22 (Warrenpoobear):** PRs #354–#369 (Semgrep phase-0, phase2 runner fix, snapshot deadlock fix, rankings/IC/ranker contract tests, universe hygiene → 358 tickers, market-data backfill, snapshot `--as-of` fix). ⚠️ **No CI ran** on any of these — GitHub Actions budget exhausted (free plan).

**Current top of tree, 2026-06-22 (Darren Schulz):** `0573101e` Semgrep governance guardrails, `afced5d4` LangGraph None-guard.

> The two artifacts that *enabled* the incident — the webhook receiver and the agent-driven cron jobs — are both **currently inert**: no webhook listener is bound (only `:8642` Hermes and `:19001` OpenClaw are listening), and the OpenClaw native scheduler is dormant (no live `jobs.json`, no runs since 06-17).

---

## Active vector — required action (the open item)

**Primary (fires tonight):** disarm `weekly-skill-harvester` before 2026-06-22 20:00 EDT. Cleanest reversible method (does not race the live gateway that owns `jobs.json`):

```
hermes cron pause weekly-skill-harvester     # reversible; CLI verb confirmed present
```

Alternatives, in order of preference:
1. **Pause the job** (above) — surgical, reversible, leaves the other 22 Hermes jobs running.
2. **Strip Step 8 / the `terminal` toolset** from the job so it harvests and writes locally but cannot push — preserves the skill-harvest function, removes only the push.
3. **Install a `pre-push` hook** on `main` that blocks non-interactive pushes — defense-in-depth backstop, does not depend on the job config.

> ⚠️ **Conflict to resolve with operator:** the containment-lift decision (`~/governance_package_2026_06_21/CONTAINMENT_LIFTED_2026_06_22.md`, mirrored in memory) records that the operator **explicitly accepted the push risk and declined push-neutralization** on 2026-06-22. The current Package A directive requires "no job capable of `git push`." These conflict. This audit does **not** unilaterally pause the job; it surfaces the finding and the time-criticality for an explicit operator call.

### Standing controls (latent, lower priority)
- Keep `git`/`gh` **off** the OpenClaw exec-approval allowlist (current state — preserve).
- Do **not** restore a live OpenClaw `jobs.json` for the write-capable `github`-skill agents while `main` is unprotected.
- Branch protection on `main` is **impossible on the free plan** — structural root cause; the controls above are the compensating layer.

---

## Disposition

- **Package A gate: SATISFIED for proceeding to Package B.** The active vector is paused; no scheduled job will push to `main`. Not hard-closed (see gate status above).
- Operator decision (2026-06-22, this session): **pause now** — supersedes the prior "accept the risk" stance recorded in the containment-lift note for this job specifically.
- Remaining work, in order: (2) commit this artifact, (3) build the Hermes/OpenClaw/LangGraph runtime-boundary map [Package B], (4) install a `pre-push` guard against non-interactive pushes [defense-in-depth, durably closes the gate], (5) begin the read-only `biotech-mcp` [Package C].
- This artifact was committed manually on branch `langgraph-review-artifact-dir-none-guard-2026-06-22`; **not pushed** (no remote write performed during containment work).

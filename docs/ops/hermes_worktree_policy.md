# Hermes Worktree Policy

Governs when and how agents may use git worktrees.

---

## Policy

### Default: no worktrees for autonomous agents

Hermes cron jobs and subagents running without an operator at the terminal
must **not** create git worktrees. Worktree creation involves branching and
writing to the filesystem in ways that can bypass the pre-push guard and
produce hard-to-revert state.

### Interactive sessions only

Worktree creation is permitted only when:
1. An operator is actively present in the session (not a cron or background job)
2. The operator explicitly approves the worktree creation step
3. The worktree targets a non-production branch

### Cleanup requirement

Any worktree created during an interactive session must be cleaned up before the
session ends. Stale worktrees on `main` or frozen branches are a governance
violation.

---

## Allowed worktree operations

| Operation | Allowed | Condition |
|---|---|---|
| `git worktree add` | Operator-gated | Interactive only; operator-approved |
| `git worktree remove` | Allowed | Clean up stale worktrees |
| `git worktree list` | Allowed | Read-only inspection |
| `git worktree prune` | Allowed | Cleanup stale references |

---

## Branch targeting rules

If a worktree is created:
- **Allowed branches:** `feature/*`, `tooling/*`, `fix/*`, `chore/*`
- **Forbidden branches:** `main`, `master`, any branch named in a containment memo
- The worktree branch must diverge from a recent non-frozen commit

---

## Rationale

INC-2026-06-20-AUTOPUSH originated from an autonomous agent that pushed
directly to `main`. Worktrees on `main` or shared branches increase the
surface area for similar incidents. The pre-push hook blocks non-interactive
pushes but cannot prevent worktree-based writes that bypass push entirely.

---

## References

- Pre-push hook: `.git/hooks/pre-push`
- Containment governance: `~/governance_package_2026_06_21/`
- Permission tiers: `docs/ops/hermes_permission_tiers.md`

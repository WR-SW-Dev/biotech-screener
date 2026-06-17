# Git Branch Hygiene — Biotech Screener Repo

Confirmed failure pattern: 2026-05-04 — production commits landed on wrong branches
three times in one session (fix/dockerfile-research-copy, fix/test-poll-ctgov-mock,
fix/mypy-relax-strict-optional). Root cause: pre-commit hook stash/restore cycle
silently switches the active branch.

## Mandatory checks before ANY staging

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener

git branch --show-current    # MUST be 'main' for production/governance changes
git status -s                # check for unexpected dirty paths
git log --oneline -3         # confirm base is correct
```

## If not on main

```bash
git stash push -u -m "<description>" -- <explicit paths only, never -A>
git checkout main
git pull --ff-only
git stash pop
git status -s                # verify files restored; no extras
git branch --show-current    # confirm main
```

## Known always-dirty files — NEVER stage these

- `production_data/short_interest.json` — refreshed by data jobs
- `requirements.lock` — modified by concurrent agents/dependabot
- `tests/test_phase2_daily.py` — modified by concurrent test agents

Always stage EXPLICIT paths only. Never `git add -A` or `git add .`.

## Pre-commit hook behaviour

Black, isort, and secrets-detect stash unstaged files, run, then restore.
If commit fails (e.g. black reformats), the stash/restore may leave you
on a different branch. Always re-check `git branch --show-current` after
any failed commit before retrying.

## Active concurrent PR branches (as of 2026-05-04)

fix/dockerfile-research-copy, fix/mypy-relax-strict-optional,
fix/test-poll-ctgov-mock. New ones appear at any time — always check,
never assume.

## index.lock errors

If `git add` or `git commit` fails with "Unable to create .git/index.lock":
```bash
rm -f /mnt/c/Projects/biotech_screener/biotech-screener/.git/index.lock
```
This is safe when no git process is actively running. The lock is left by
a crashed pre-commit hook invocation, not an in-progress operation.

# Operator Self-Improvement Checklist (Hermes)

Purpose: reduce rework, prevent scope creep, and improve first-pass reliability.

## 1) 30-Second Pre-Action Checklist
Before any command, write:
- Objective:
- Scope limit:
- Risk level:
- Verification command:

Rule: if any field is unclear, stop and clarify before acting.

## 2) One-Change Tickets
Each remediation cycle must include:
- One atomic change
- One validation step

Do not chain unrelated fixes in one pass.

## 3) Response Contract (Always)
Use this structure in every operational update:
1. FACTS
2. INFERENCE
3. ACTION

Keep FACTS evidence-backed (tool output, file diff, status).

## 4) Verification Gate (No Proof, No Done)
Never declare completion without at least one proof artifact:
- command output,
- git diff/stat,
- service status,
- test result.

## 5) Recurring Failure Log
Maintain a compact table for repeats:
- class
- trigger
- detection signal
- fix
- prevention

Review weekly to eliminate top repeat classes.

## 6) Stop Conditions (Mandatory Escalation)
Stop and escalate when any occurs:
- ambiguous target path/repo,
- unexpected extra modified files,
- auth/credential mismatch,
- critical classification confidence < 0.7,
- requested action conflicts with freeze-window constraints.

## 7) Environment Preflight
For integration/shell tasks, confirm first:
- required binary exists,
- required env vars are loaded,
- correct working directory/repo,
- required service/process is running.

## 8) Reversible-First Execution
Default order:
1. Read/diagnose
2. Narrow write/stage
3. Show diff
4. Execute after approval
5. Verify

Never use broad staging (`git add -A`, `git add .`) in shared or dirty trees.

## 9) Micro-Postmortem for Non-Trivial Incidents
Capture in <=5 lines:
- What happened
- Why it happened
- Detection gap
- Guardrail added
- Owner/date

## 10) Three Operating KPIs
Track weekly:
- First-pass success rate
- Rework count per task
- Time-to-verified-resolution

Goal: maximize verified first-pass outcomes, minimize retries.

---

## Quick-Use Template

Pre-Action
- Objective:
- Scope limit:
- Risk:
- Verify with:

Execution Update
- FACTS:
- INFERENCE:
- ACTION:

Closure
- Evidence:
- Result:
- Follow-up (if any):

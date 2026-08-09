# Daily Skill Harvest Proposal — 2026-08-04

Status: DRAFT — proposal only. No git operations were run as part of this file.
Skill patches described below have already been applied directly (per harvester
Step 4 authorization); this file documents them for operator review, not for
approval-to-apply.

## Summary

7-day git + session harvest across `biotech-screener` and `asset-allocation`.
2 skills patched with confirmed-instance findings; 0 new skills created (no
finding cluster reached the 3+ threshold). 1 EES v3 governance discrepancy
flagged for operator attention (see below) — this is a decision item, not a
skill-harvest action.

## Skill patches applied

| Skill | Category | Addition | Evidence |
|---|---|---|---|
| `openclaw-data-pipeline-debug` | devops | Class Q — EV calibration look-ahead leakage (future-dated HITs) | commit `32a1b19a`, PR #542 (fixes #541) |
| `openclaw-data-pipeline-debug` | devops | Class R — monitoring prior-snapshot resolved from staging parent instead of `_prior_dir` | commit `d090713a`, PR #546 |
| `openclaw-cron-scheduler-debug` | devops | Class N — mandate evidence lost to git-state interference during production cron (Spec 115 P1+P2a) | commit `dd13e097`, PR #540 |

All three are backed by a merged commit hash + PR number; none were fabricated
or inferred from partial evidence.

## No-new-skill items

- `aa-model-tracker`, `openclaw-agent-scope-audit`, `openclaw-session-routing-debug`:
  no citable instance in this window (asset-allocation repo had exactly 1
  housekeeping commit — a green MODE A sync, no findings).
- EES v3 shadow monitor `run_findings.jsonl` (2026-07-20 → 2026-08-03, 10 runs):
  zero anomalies (`SCRIPT_ERROR`/`ZERO_VETOES`/`ALPHA_NEGATIVE`/`ALPHA_SPIKE`/
  `GATE_NEWLY_MET`) — nothing actionable for the shadow-monitor skill itself.

## Flagged for operator decision (not a skill-harvest action)

**EES v3 `raw_veto_core` promotion decision remains open and unadvanced.**
The 20-day observation gate has read `met: true` continuously since at least
2026-07-20 (obs 52, climbing to 62 by 2026-08-03) — i.e. well past the
"est. clear 2026-08-30" date quoted in the 2026-06-30 IC-council session
transcript. That transcript's "0/20 windows completed" framing predates the
gate being met; it is not itself wrong, just stale. No commit, memo, or
governance session in the reviewed window advanced the promotion ruling.
Recommend an explicit operator decision (promote / hold / reject) rather than
letting gate-met status age further without action — cf. Class G in
`ees-v3-veto-monitor` ("gate met → next step: operator writes memo; governance
review required before any production integration").

## Command to implement (if operator wants to proceed)

No production changes are proposed by this harvest cycle. If the operator
wants to act on the EES v3 flag above, the next concrete step is:

```
# Operator-authored governance memo only — no code/ruleset change implied.
# Suggested framing: cite gate-met date (2026-06-25), 62-observation IC/hit-rate
# from run_findings.jsonl, and the declining veto_alpha_20d trend (8.22 → 6.95)
# alongside the LATE-period backtest IC caveat from the 2026-06-30 session.
```

This proposal file makes no git commits, pushes, or branch changes.

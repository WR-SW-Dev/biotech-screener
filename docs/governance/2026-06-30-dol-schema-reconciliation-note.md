# DOL Schema Reconciliation Note — 2026-06-30

**Class:** governance documentation / no model change / no production wiring.

## Summary

The repo-authoritative Decision Outcome Ledger schema is the JSONL schema in `skills/biotech-ic-council/references/decision-outcome-ledger.md` and the live ledger at `artifacts/ic_council/decision_outcome_ledger.jsonl`.

`ICD-20260629-001` is now operator-confirmed. The evaluation window is authoritative for scoring, but the outcome remains pending until the forward-shadow window resolves.

## Confirmed Row

- `decision_id`: `ICD-20260629-001`
- `forward_shadow_mandate_id`: `SM-20260629-001`
- `evaluation_window_type`: `MODEL_EVALUATION`
- `evaluation_window_start`: `2026-06-29`
- `evaluation_window_due`: `2026-09-30`
- `operator_confirmed`: `true`
- `outcome_status`: `pending`

Backfilled Jan-Jun 2026 bootstrap results remain baseline context only. They do not resolve the forward mandate.

## Remaining Reconciliation

Town-side routines should read and report against the committed schema field names:

| Concept | Use committed field |
|---|---|
| Window class | `evaluation_window_type` |
| Window confirmation | `operator_confirmed` plus `set_by` |
| Advocate assignee | `edge_advocate_seat` and `edge_advocate_assigned` |
| Advocate stance | `edge_advocate_position` |
| Shadow mandate reference | `forward_shadow_mandate_id` and `forward_shadow_metric` |
| Shadow result | `forward_shadow_result` |
| Advocate resolution | `advocate_call_resolved_correct` |

The stale routine guard that says to skip if the ledger file does not exist should be removed or rewritten. The ledger exists and is live.

## Non-Goals

This note does not change scoring, ranker, selector, sizing, gates, event-EV math, cron, production wiring, or any Town routine prompt directly. It records the repo-side source of truth for the next routine-prompt update.

# LangGraph Runway Spike — Frozen Note

**Status:** FROZEN  
**Date:** 2026-05-05  
**Author:** Hermes (session-captured)

## Location

```
~/dev/langgraph-spike/
  runway_dossier.py   — typed state, conditional human-review gate, checkpoint/resume
  README.md           — what was proven, what was not
```

## Production impact

None. Dev-only install. No screener files touched. No production dependencies added.

## What was proven

- Typed state flows through a multi-node LangGraph graph
- Tool-routing node as placeholder for future fetcher dispatch
- `interrupt_before` human-review gate on high/critical severity
- `graph.update_state()` + re-invoke resumes after operator approval
- Conditional edges bypass the gate for low/medium severity
- Graceful error path on unknown ticker

## What was NOT proven

- That LangGraph should replace any screener component
- That tool stubs are production-ready
- That human-in-the-loop UX is solved for cron/headless contexts

## Runway data-source policy (decided 2026-05-05)

```
runway_input =
  cached_fundamentals           (primary — fast, deterministic, PIT-friendly)
  + SEC/EDGAR                   (validation/backfill — stale, missing, or high-severity cases)
  + manual_override             (explicit exception layer — ATM, PIPE, post-quarter refi; must be logged)
```

**Rule:** agent writes the dossier. Numeric runway inputs must come from deterministic,
inspectable fields. The agent does not derive runway from prose.

## Next action

None until the data-source question is concretely answered:
SEC/EDGAR direct vs cached fundamentals provider vs hybrid fetch layer.
Do not expand LangGraph plumbing before that decision is made.

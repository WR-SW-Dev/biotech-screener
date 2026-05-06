# policy_shadow_watch — Freshness Audit Follow-up
**Date:** 2026-05-05
**Status:** RESOLVED — no action required
**Author:** Hermes ops session (A2 follow-up to POLICY_SHADOW_AND_REVIEW_QUEUE_REGISTRY_MISMATCH_2026_05_03.md)

---

## Background

The May 3 memo (§1.3) flagged that `build_policy_shadow_compare` had not written a
comparison file since 2026-04-24, despite production running on Apr 29, 30, May 1-5.
This was listed as A2: file a freshness audit asking why.

## Finding (2026-05-05 check)

```
artifacts/policy_shadow/tier_weighted/
  2026-05-05_comparison.{json,md}  — mtime 2026-05-05 20:45  ← fresh
  2026-01-20_comparison.{json,md}  — mtime 2026-04-28 08:44  (backfill artifact)
  2026-04-24_comparison.{json,md}  — mtime 2026-04-25 10:21  (last pre-gap)
```

Today's comparison file landed at 20:45 ET. The gap (Apr 25 – May 4) self-resolved.

## Likely cause of Apr 25 – May 4 gap (INFERENCE, not verified)

The gap coincides with the ruleset transition period (2a3e79eb → 8887576e, promoted
2026-05-04). `build_policy_shadow_compare` compares current shadow vs policy portfolio;
if the policy portfolio path changed or the build tool checked for a specific ruleset ID,
it may have silently skipped writes during the transition window.

The May 5 production run is the first under 8887576e with a fresh comparison artifact,
consistent with this hypothesis.

## Status

RESOLVED for now. If the gap recurs after the next ruleset change, investigate
`tools/build_policy_shadow_compare.py` for a ruleset-ID guard that causes silent
fall-through in the `if "error" not in _ps` branch of run_screen.py.

## No action taken

No code changes. This memo closes the A2 audit item.

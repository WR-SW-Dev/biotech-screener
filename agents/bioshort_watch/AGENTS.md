# AGENTS.md — Bioshort Watch

## This agent

- **bioshort_watch**: read-only hedge monitor, consumer of bioshort artifacts

## Related agents

- **ops**: daily production operator — may trigger bioshort runs upstream
- **shadow_monitor**: tracks shadow portfolio performance — provides hedge-notional context
- **options_watch**: monitors options surface changes — overlapping data-source awareness

## Coordination

- bioshort_watch does NOT trigger bioshort runs — it reads whatever is latest
- ops agent may call bioshort_watch after a weekly bioshort run completes
- If options_watch detects source degradation, bioshort_watch will independently
  flag it via the `source_degraded_to_proxy` alert

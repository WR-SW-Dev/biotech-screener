# Hermes Knowledge Layer — Scheduled Refresh

**Spec:** Spec 089 (Phase 2A)
**Date wired:** 2026-05-19
**Branch:** hermes-knowledge-layer-cron-2026-05-19

## Cron Entry (OS crontab)

```cron
45 17 * * 1-5 cd /mnt/c/Projects/biotech_screener/biotech-screener && /usr/bin/python3 tools/build_hermes_knowledge_layer.py >> logs/knowledge_layer.log 2>&1
```

**Schedule:** 17:45 ET weekdays (post-production)
**Log:** `logs/knowledge_layer.log`
**Builder:** `tools/build_hermes_knowledge_layer.py` — deterministic, zero API/env dependencies

## Output Artifacts

| Artifact | Path | Format |
| -------- | ---- | ------ |
| Latest state | `artifacts/ops/knowledge_layer/latest_state.json` | JSON |
| Latest state (human) | `artifacts/ops/knowledge_layer/latest_state.md` | Markdown |
| Held spec ledger | `artifacts/ops/held_spec_ledger/latest.json` | JSON |
| First-fire ledger | `artifacts/ops/first_fire_ledger/latest.json` | JSON |
| Contradiction ledger | `artifacts/ops/contradiction_ledger/latest.md` | Markdown |

All output paths are gitignored (`artifacts/*` in `.gitignore`).

## First-Fire Validation Checklist

After the cron fires for the first time:

- [ ] Cron runs — check `crontab -l | grep build_hermes_knowledge_layer`
- [ ] Outputs written — `ls -la artifacts/ops/knowledge_layer/latest_state.json`
- [ ] Outputs parseable — `python3 -c "import json; json.load(open('artifacts/ops/knowledge_layer/latest_state.json'))"`
- [ ] Contradiction count reported — `grep contradictions: logs/knowledge_layer.log`
- [ ] Failure exits nonzero or logs clearly — `tail -20 logs/knowledge_layer.log` on failure
- [ ] Output path stays gitignored — `git check-ignore artifacts/ops/knowledge_layer/latest_state.json`

## Scope Boundary

This cron job refreshes the deterministic ledgers only. It does NOT:
- Trigger any LLM-driven analysis or alerts
- Touch selector, ranker, scoring, or production snapshots
- Run Hermes job prompts or town integration
- Modify any governance state (spec status, blocker flags, policy values)

Full Spec 089 Phase 2 (LLM-driven alerting, town delivery, contradiction-triggered escalation) remains deferred until the raw ledger has proven clean operation over multiple daily cycles.

# OpenClaw agent runtime + monitoring review patterns

Captured from the 2026-05-08 all-agent code review/fix pass in the biotech screener repo.
Use when reviewing OpenClaw agents, cron-launched LLM agents, heartbeat checks, post-snapshot supervisors, and ops_supervisor anomaly classification.

## 1. Direct LLM launcher must fail closed at process level

Risk pattern:
- A launcher returns an in-memory `{status: "error"}` dict but `main()` only prints the error and exits 0.
- Cron/watchdogs then treat API/auth/model failure as a successful run.

Check:
- Find exception/error paths in the launcher.
- Verify `main()` returns nonzero for failed agent runs.
- Verify `if __name__ == "__main__": raise SystemExit(main())` or equivalent.

Regression test shape:
- Monkeypatch `run_agent()` to return `{status: "error"}`.
- Call `main()` with test argv.
- Assert return code is nonzero and the error log is still written.

## 2. Direct-agent log names need collision resistance

Risk pattern:
- Log file name uses only agent + timestamp to seconds, e.g. `agent_YYYYmmdd_HHMMSS.json`.
- Manual reruns or watchdog retries within the same second overwrite evidence.

Expected pattern:
- Include microseconds and/or a short UUID suffix, e.g. `agent_YYYYmmdd_HHMMSS_micro_uuid.json`.

Regression test shape:
- Monkeypatch agent run to succeed instantly.
- Call `main()` twice in same test.
- Assert two distinct log files exist.

## 3. Terminal unsupervised agents are not coverage gaps

Risk pattern:
- Registry has a deliberate terminal/final-layer agent (`ops_supervisor`) marked `active` but `supervised_by_orchestrator=false`.
- Heartbeat code counts every active unsupervised agent as `missing_count`, forcing RED.

Expected pattern:
- Maintain an explicit allowlist for terminal unsupervised agents.
- Emit `SKIP`/`terminal unsupervised` for those agents.
- Keep non-terminal active unsupervised agents as coverage gaps.

Regression test shape:
- Temp registry with `qa` active supervised and `ops_supervisor` active unsupervised.
- Assert `missing_count == 0` and verdict GREEN.
- Separate test: arbitrary active unsupervised agent still increments `missing_count`.

## 4. Filename date parsing should find embedded ISO dates

Risk pattern:
- Freshness check parses `latest_name[:10]` as ISO date.
- Files named with prefixes like `releases_YYYY-MM-DD.jsonl` become `releases_2`, raise `ValueError`, and stale-source checks silently skip.

Expected pattern:
- Extract the first embedded `YYYY-MM-DD` with regex before parsing.

Regression test shape:
- Create `releases_2026-05-01.jsonl` and run check for `2026-05-08`.
- Assert `STALE_SOURCE` appears with age 7d.

## 5. CSV fallback checks must use the real header

Risk pattern:
- Code slices `lines[-6:]` and treats `recent[0]` as the header.
- In files with >5 data rows, `recent[0]` is a data row, so column lookup fails silently.

Expected pattern:
- Use `lines[0]` as the header and then inspect `lines[-N:]` data rows.

Regression test shape:
- Create CSV with header plus several positive rows and five negative rows.
- Assert fallback detects drawdown/loss streak.

## 6. Done predicates must include all terminal artifacts

Risk pattern:
- Post-snapshot task `done` predicate checks only an early/mid-pipeline artifact.
- If a later stage fails, rerun skips and never retries the failed stage.

Confirmed pattern:
- Herald `_herald_done()` checked only `deduped_YYYY-MM-DD.jsonl`, while classification output was required later.

Expected pattern:
- Done predicate requires all required terminal artifacts, e.g. deduped + classified files.
- Task implementation should resume from completed mid-stage artifact rather than rerunning everything unnecessarily.

Regression test shape:
- Create deduped file only; assert `_herald_done()` is false.
- Add classified file; assert `_herald_done()` is true.

## 7. Anomaly carry-forward identity must include issue text/code

Risk pattern:
- Ops supervisor classifies a prior match using only `(agent, raw_status)`.
- A new issue from the same agent with same status becomes `carried` and severity is downgraded.

Expected pattern:
- Match prior anomalies by `(agent, raw_status, raw_text)` or a structured stable issue code.
- Preserve raw_text (or issue code) when loading prior supervisor JSON.

Regression test shape:
- Prior anomaly: same agent/status, different raw_text.
- Current unknown anomaly should classify as `new`/ORANGE, not `carried`/YELLOW.

## 8. Test classifications need a terminal-agent bucket

Risk pattern:
- Workspace-accounting tests classify agents only as compliant/partial/incomplete/retired.
- `ops_supervisor` intentionally lacks HEARTBEAT.md because it is watched by `agent_supervisor_sentinel.py`, so forcing it into partial/incomplete produces false failures.

Expected pattern:
- Add `TERMINAL_AGENTS = ["ops_supervisor"]` or equivalent and include it in total workspace accounting only.

## Minimal validation set used in the session

```bash
python3 -m pytest \
  tests/test_run_agent_direct.py \
  tests/test_agent_heartbeat_checks.py \
  tests/test_post_snapshot_supervisor.py \
  tests/test_ops_supervisor.py \
  tests/test_openclaw_agents.py \
  -q --override-ini='addopts=' -p no:xdist
```

For the ruleset JSONL idempotency fix from the same session:

```bash
python3 -m pytest tests/test_ruleset_health_monitor.py -q --override-ini='addopts=' -p no:xdist
```

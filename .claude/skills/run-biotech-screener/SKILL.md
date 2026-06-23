---
name: run-biotech-screener
description: Run, validate, and inspect the Wake Robin biotech screener pipeline. Use when asked to run the screener, check the snapshot, validate inputs, see current rankings, check gate status, or re-run the screen for a date.
---

# run-biotech-screener

A CLI pipeline (Python 3.12, no venv needed — deps are system-wide). The primary entry point for production is `run_phase2_daily.py`; the smoke script at `.claude/skills/run-biotech-screener/smoke.sh` is the agent path for health checks and ranking inspection.

All paths below are relative to the repo root: `/mnt/c/Projects/biotech_screener/biotech-screener/`.

---

## Run (agent path) — smoke script

Validates inputs, reads the run_manifest gates, and prints top-10 rankings. No side effects.

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
bash .claude/skills/run-biotech-screener/smoke.sh [YYYY-MM-DD]
# DATE defaults to today
```

Output sections:
1. **Input validation** — confirms `production_data/` has all 4 required files
2. **Gate summary** — `overall_status`, PASS/WARN/FAIL counts, WARN/FAIL details from `run_manifest.json`
3. **Top-10 rankings** — sorted by `actionable_rank`, with selector score, final score, stage, and catalyst window flag

---

## Re-run the screen for a date

The standard production run (wraps `run_screen.py` with `--decision-mode phase2 --strict`):

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
python3 run_phase2_daily.py --as-of-date 2026-06-23
```

Defaults: `--data-dir production_data/`, `--snapshot-dir data/snapshots/`. Will refuse to overwrite an existing snapshot without `--force-overwrite`.

Full daily orchestrator (cache warm → phase2 → rollup):

```bash
python3 run_daily.py --as-of-date 2026-06-23
```

Dry-run input validation only:

```bash
python3 run_screen.py --as-of-date 2026-06-23 --data-dir production_data --dry-run
```

---

## Output locations

| Artifact | Path |
|---|---|
| Rankings | `data/snapshots/DATE/rankings.csv` |
| Full scored output | `data/snapshots/DATE/screen_output.json` |
| Gate status | `data/snapshots/DATE/run_manifest.json` |
| Decision portfolio | `data/snapshots/DATE/decision_portfolio.csv` |
| Options review queue | `data/snapshots/DATE/options_review_queue.csv` |

---

## Prerequisites

No venv — Python 3.12 system install with `yaml`, `pandas`, `numpy`, `scipy` available. No additional `apt-get` needed.

---

## Gotchas

- **`--data-dir ./data` silently fails.** Required input files live in `production_data/`, not `data/`. The dry-run reports all 4 as MISSING if you pass `./data`. Always use `production_data` (or rely on `run_phase2_daily.py`'s default).
- **`WARN overall_status` is normal.** The screener runs exit code 1 on WARN. Active WARNs as of 2026-06-23: `pnl_attribution` (0% coverage), `forward_eval` (mean IC slightly negative on 10-date window), `portfolio_weights` (sizing disabled), `phase2_health`. These are known and tracked; a WARN run is still usable.
- **Anti-clobber guard.** `run_screen.py` refuses to write to an existing snapshot dir unless `--force-overwrite` is passed. `run_phase2_daily.py` handles this correctly; if calling `run_screen.py` directly, pass `--force-overwrite` to re-run a date.
- **Freeze is in effect.** As of 2026-06-20, ranker/selector/sizing/final_score are frozen. `run_phase2_daily.py` can be used for read-only inspection; do not modify production model files.

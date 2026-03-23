# TOOLS.md — QA Agent

## Contract tests (fast, primary check)

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
python3 -m pytest tests/test_decision_engine_contract.py -x -q
```

## Full test suite

```bash
python3 -m pytest tests/ -x -q
```

## Specific test files by area

| Area | Command |
|------|---------|
| Decision engine | `pytest tests/test_decision_engine_contract.py -x` |
| Module 5 scoring | `pytest tests/test_composite_v3.py tests/test_module_5_v3_regression.py -x` |
| Shadow portfolio | `pytest tests/test_live_shadow_portfolio.py -x` |
| Trade plan | `pytest tests/test_trade_plan.py -x` |
| Collection health | `pytest tests/test_data_collection_health.py -x` |
| Hedge report | `pytest tests/test_biotech_hedge_report.py -x` |

## Dry-run screen (no data fetch, checks plumbing)

```bash
python3 run_screen.py --as-of-date 2026-03-23 --data-dir production_data --dry-run
```

## Flake8 on core files

```bash
python3 -m flake8 run_screen.py decision_engine.py tools/run_daily_production.py --select=F401,F841,E999
```

## Failure classification

| Class | Symptom | Typical root cause |
|-------|---------|-------------------|
| schema_regression | Missing/renamed field in output | Code changed a column name |
| ranking_invariant | Rank sum != expected, duplicates | Sorting logic or tie-breaking |
| catalyst_regression | catalyst_mode mismatch, missing family | Event ledger or L0 gate |
| artifact_missing | File not found after run | Step skipped or path changed |
| date_mismatch | metadata.as_of_date != arg | Date propagation bug |
| pipeline_crash | Exit code != 0 before promotion | Exception in run_screen or gates |

## Key artifacts to check after a run

| File | What to verify |
|------|---------------|
| `data/snapshots/YYYY-MM-DD/rankings.csv` | Exists, has rows, headers match schema |
| `data/snapshots/YYYY-MM-DD/metadata.json` | `as_of_date` matches, `decision_engine_version` present |
| `data/snapshots/YYYY-MM-DD/phase2_health.json` | Status is OK or WARN (not missing) |
| `logs/daily_production_YYYY-MM-DD.log` | No traceback, exit code 0 or 2 |

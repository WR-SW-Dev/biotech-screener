# TOOLS.md — Calibration Agent

## Sweep (full)

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
python3 run_decision_ruleset_sweep.py \
    --archive-dir data/archives \
    --holdout-split 2025-01-01 \
    --top-k-holdout 10 \
    --output-dir output/calibration
```

## Sweep (dry-run)

```bash
python3 run_decision_ruleset_sweep.py --dry-run
```

## Signal evidence (compare baseline vs candidate)

```bash
python3 scripts/run_signal_evidence.py \
    --baseline-ruleset 9f1f4587 \
    --candidate-ruleset <candidate_id> \
    --manifest manifests/pit_panel_eval_dates.txt
```

## Rerank snapshots

```bash
python3 scripts/research/rerank_snapshots.py \
    --ruleset <candidate_file> \
    --snapshot-dir data/snapshots
```

## Promotion battery (read-only — do NOT promote)

```bash
python3 scripts/research/run_promotion_battery.py \
    --candidate <candidate_file> \
    --dry-run
```

## Key outputs to read

| Artifact | Path |
|----------|------|
| Sweep summary | `output/calibration/ruleset_sweep_summary.csv` |
| Sweep details | `output/calibration/ruleset_sweep_details.json` |
| Candidate ruleset | `output/calibration/candidate_*.json` |
| Calibration note | `output/calibration/calibration_note.md` |
| Signal evidence | `output/signal_evidence/<name>/` |
| Promotion battery | output from `run_promotion_battery.py --dry-run` |

## Key inputs

| Resource | Path |
|----------|------|
| Archives | `data/archives/` (33 .tar.gz, 2024-01 to 2026-02) |
| Active ruleset | `production_data/decision_rulesets/v1.11.0_*.json` |
| Manifest | `production_data/decision_rulesets/manifest.json` |
| Eval date manifests | `manifests/` |

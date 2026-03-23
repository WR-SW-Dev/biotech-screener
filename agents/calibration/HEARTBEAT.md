# HEARTBEAT.md — Calibration Agent

On heartbeat, do not rerun full calibration by default.

## Checklist

1. Check whether a new candidate ruleset file appeared in:
   `production_data/decision_rulesets/`
2. Check whether a recent sweep output exists in:
   `output/` or the configured calibration output directory
3. If a new candidate exists and no summary note exists for today:
   - report CALIBRATION_REVIEW_NEEDED
4. Otherwise reply `HEARTBEAT_OK`

## Only surface issues

Surface only:
- new candidate awaiting review
- missing sweep outputs for a requested evaluation
- holdout result present but no memo written

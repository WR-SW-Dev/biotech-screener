# HEARTBEAT.md — Bioshort Watch

## Cadence

- **Weekly**: after bioshort runs (typically weekend or Monday)
- **Ad hoc**: after major biotech selloff, data-source change, or manual hedge report rerun

## Heartbeat check

1. Run `python tools/build_bioshort_watch.py`
2. Read `artifacts/bioshort_watch/{date}_watch.md`
3. If alert_level is HIGH or MEDIUM, surface to operator
4. If alert_level is LOW or NONE, log and move on

## Health indicators

- Latest hedge report is <8 days old
- Verdict JSON exists and is parseable
- At least 2 hedge reports exist for comparison
- Options data source is not degraded to realized-vol proxy

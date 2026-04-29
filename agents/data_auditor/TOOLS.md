# TOOLS.md — Data Auditor Commands

## Daily audit run

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
python3 agents/data_auditor/run_audit.py --as-of-date YYYY-MM-DD
```

## Daily checks only

```bash
python3 agents/data_auditor/run_audit.py --daily-only --as-of-date YYYY-MM-DD
```

## Weekly checks only

```bash
python3 agents/data_auditor/run_audit.py --weekly-only --as-of-date YYYY-MM-DD
```

## Check and read latest report

```bash
# View JSON report
cat artifacts/data_auditor/integrity_report_YYYY-MM-DD.json | head -100

# Pretty-print
python3 -m json.tool artifacts/data_auditor/integrity_report_YYYY-MM-DD.json | less
```

## Exit codes

- `0` = PASS — all checks passed
- `1` = FAIL — one or more checks failed
- `2` = WARN — no failures, but warnings present

## Reading the report

Output artifact: `artifacts/data_auditor/integrity_report_YYYY-MM-DD.json`

Key fields:
- `verdict`: Overall status (PASS / WARN / FAIL)
- `checks`: Dictionary of 5-7 check results
  - Each check has `status` and `detail`
  - Some checks include violation lists (divergences, stale_tickers, missing_tickers)
- `summary`: Human-readable one-line summary

## Cron schedule

```
18:00 ET  weekdays  → Run daily checks
06:00 ET  Saturdays → Run weekly checks (if scheduled)
```

## Red lines

- Never edit the audit script or check logic
- Never modify data files based on divergences (report only)
- Never delete or skip checks

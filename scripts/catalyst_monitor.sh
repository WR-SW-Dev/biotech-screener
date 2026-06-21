#!/usr/bin/env bash
# Hourly catalyst monitor — alerts on upcoming trial readouts (next 90 days)
# Called by cron job 'Biotech Catalyst Monitor' every hour
# Stays SILENT when no catalysts — only delivers when there's something to report
cd /c/Projects/biotech_screener/biotech-screener
/c/Users/DarrenSchulz/AppData/Local/Programs/Python/Python311/python.exe scripts/pipeline.py catalyst

#!/usr/bin/env bash
# Daily universe refresh — runs screener for today's date
# Called by cron job 'Biotech Daily Refresh' at 6 AM
cd /c/Projects/biotech_screener/biotech-screener
/c/Users/DarrenSchulz/AppData/Local/Programs/Python/Python311/python.exe scripts/pipeline.py refresh

#!/usr/bin/env bash
# Daily universe refresh — runs screener for today's date
# Called by cron job 'Biotech Daily Refresh' at 6 AM
python scripts/pipeline.py refresh

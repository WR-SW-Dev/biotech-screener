#!/usr/bin/env bash
# Hourly catalyst monitor — alerts on upcoming trial readouts (next 90 days)
# Silent when no catalysts. Uses system Python (not Hermes venv).
/c/Users/DarrenSchulz/AppData/Local/Programs/Python/Python311/python.exe scripts/pipeline.py catalyst

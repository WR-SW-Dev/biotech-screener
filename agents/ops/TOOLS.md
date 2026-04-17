# TOOLS.md — Ops Agent Commands

## Daily production run

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
source .env 2>/dev/null
python3 tools/run_daily_production.py --as-of-date YYYY-MM-DD
```

## Ops digest (standalone, if pipeline already ran)

```bash
python3 tools/build_ops_digest.py --as-of-date YYYY-MM-DD --stdout
```

## Portfolio metrics refresh

```bash
python3 tools/build_portfolio_report.py
```

## Readiness scorecard (standalone)

```bash
python3 tools/weekly_readiness_scorecard.py --as-of-date YYYY-MM-DD
```

## Daily working set

Read this first:
- `artifacts/ops_digest/YYYY-MM-DD_digest.md`
  - One-screen summary of NEW issues, RESOLVED issues, and items needing review

If the digest flags something, drill into only these inputs:

1. `data/snapshots/YYYY-MM-DD/phase2_health.json`
   - Core pipeline health, gate outcomes, turnover, catalyst coverage

2. `data/snapshots/YYYY-MM-DD/data_collection_health.json`
   - Source freshness, ingestion status, collection PASS/WARN/FAIL

3. `data/snapshots/YYYY-MM-DD/coverage_quality.json`
   - Coverage percentages for catalyst / sponsor / optionality / regulatory inputs

4. `data/snapshots/YYYY-MM-DD/eligibility_summary.json`
   - Eligible vs ineligible counts and tier distribution

5. `data/snapshots/YYYY-MM-DD/phase2_run_delta_details.json`
   - What changed vs prior run: entrants, exits, turnover, tier drift

5a. `data/snapshots/YYYY-MM-DD/drift_report.md` (schema v1.2.0+)
   - Day-over-day stability diagnostics:
     * top-20 / top-60 overlap (market + plumbing)
     * action transition matrix (prior tier_dev → current tier_dev)
     * mean |selector_score delta| and p95 (score-level drift)
     * feature coverage deltas — top 5 drops flagged (plumbing red flag)
     * near-miss fragility at K=20 and K=30 cutoffs
   - **Plumbing-vs-regime heuristic**: if top-20 overlap < 70% AND a feature's
     coverage dropped ≥10pp, suspect plumbing before attributing to the market.
     ops digest surfaces this as `stability_diagnostics.plumbing_suspect=true`.

6. `artifacts/live_shadow/portfolio_metrics.json`
   - Shadow portfolio return, excess vs XBI, Sharpe, drawdown

7. `artifacts/readiness/scorecard_YYYY-MM-DD.json`
   - Final readiness verdict: READY / REVIEW / HOLD

## Rule of use

Do not fan out into the full artifact set by default.
Start with the digest.
Open only the specific input file that explains the flagged issue.

## Environment

- WSL2 Ubuntu, Python 3.12
- Node 22 via nvm (for OpenClaw)
- Cron: 5:30 PM ET weekdays + @reboot catch-up
- Windows Task Scheduler: belt-and-suspenders backup

# CLAUDE.md — Wake Robin Capital Management Biotech Screener

## Project Identity
This is an institutional-grade biotech investment screening system.
Outputs must be reproducible, auditable, and deterministic.
Every decision must be traceable to a data source with a timestamp.

## North Star Rule
Backtest systems NEVER directly modify production screening behavior.
They produce evidence and proposals only. Governance review required before
any backtest finding changes a production signal weight.

## CCFT Principles (Non-Negotiable)
All data fixtures must be:
- Canonical: single authoritative source per data type
- Complete: no silent nulls or missing fields without explicit flags
- Frozen: historical snapshots are immutable once written
- Timestamped: data_available_timestamp <= as_of_date always enforced

## Active Ruleset

Current: `8887576e` (v1.14.0). Pinned in `run_screen.py` and `run_phase2_snapshot_delta.py` (must stay in sync).
**See `.claude/rules/operational-state.md` for full ruleset details, settings, and manifest.**

---

## Architecture Freeze Status

**Scoped production model freeze in effect (as of 2026-06-20).** Ranker, selector, sizing, final_score, portfolio, and snapshot files are frozen. Safe lanes: expectation verification, Event EV shadow, Sci-Cart diagnostics, observability, Hermes read-only. Lift requires explicit operator clearance.
See `.claude/rules/operational-state.md` for freeze scope and post-freeze priorities.

---

## Subagent Delegation

When a major biotech model change, validation finding, backtest correction, governance status change, or alpha/investability conclusion occurs, use the `model-doc-and-skill-sync` subagent to update `docs/MODEL_DOCUMENTATION.md` and synchronize any affected biotech skills. Documentation remains the source of truth; skill updates are downstream instruction hygiene only. No model, ranker, selector, sizing, production, or trading behavior may change through this agent.

When universe coverage, stale tickers, XBI/IBB constituents, missing biotech names, delisted names, ticker mapping, or ETF coverage drift are discussed, use the `universe-hygiene-auditor` subagent. The agent may write audit artifacts and proposals only; it must not directly mutate the production universe without separate operator approval.

---

## PIT Rules

1. **Never call the historical set "true PIT"** unless archived raw inputs, archived code, AND archived derived artifacts all exist as-of each date.
2. Historical benchmark outputs must carry `pseudo_pit_version` (1=contaminated, 2=cleaned).
3. Benchmark reruns must use the PIT-aware paths: `--pit-mode survivorship` or `--pit-mode full`.
4. Long-history conclusions are **provisional** until PIT-v2 financial rerun lands.
5. The forward monitor is the only true out-of-sample evidence. Accumulate it.

---

## Before Writing Any Code
1. State which module this change belongs to
2. Identify whether this is a new signal, validation change, or infrastructure change
3. Write the failing test FIRST — show me the red test before any implementation
4. Confirm no look-ahead bias: what is the data_available_timestamp?
5. Classify the diff by governance tier (Tier 0-4 per governance/AGENT_ROUTING_POLICY.md)

## Coding Standards
- All outputs: encoding='utf-8', lineterminator='\n', quoting=csv.QUOTE_MINIMAL
- SHA256 hash every scored output for audit trail
- Identical inputs must produce byte-identical outputs — no random seeds, no datetime.now()
- Use Point-in-Time fixtures — never fetch live data in tests

## What NOT To Do
- Do not refactor and add features in the same commit
- Do not change production agent weights without an ablation test showing Sharpe delta
- Do not use PubMed h-index API, options flow, or CapIQ — see approved data sources
- Do not introduce survivorship bias — graveyard list is at data/graveyard/

## Test Requirements
Every new signal must include:
1. Unit test with known fixture input -> expected output
2. Leakage test confirming data_available_timestamp compliance (see Trust Buckets in `.claude/rules/research-backtest.md` for signal safety assessment)
3. Ablation test stub showing Sharpe contribution >= 0.1

---

## Scoped Rules Reference

**See these files for detailed operational and governance context:**

- **`.claude/rules/operational-state.md`** — Active ruleset, 13F cycle, freeze dates, spec status, forward shadow IC. Updated weekly.
- **`.claude/rules/research-backtest.md`** — Evidence hierarchy, dead lanes, benchmark commands, promotion story. Load during research sessions.
- **`.claude/rules/production-pipeline.md`** — Decision engine architecture, pipeline flow, cron behavior, cache warming. Path-scoped to pipeline files.
- **`.claude/rules/governance.md`** — Tier definitions, promotion path, 13F onboarding, insider diagnostic, expectation layer, expression policy.
- **`.claude/rules/external-intel.md`** — OpenClaw status, Hermes competitive frame, industry AI adoption, developer profile.

---

## Key File Locations

| Area | File |
|------|------|
| Main orchestrator | `run_screen.py` |
| Decision Engine | `decision_engine.py` |
| Selector Engine | `selector_engine.py` |
| Ranker Engine | `ranker_engine.py` |
| Daily Production | `tools/run_daily_production.py` |
| Shadow Portfolio | `tools/live_shadow_portfolio.py` |
| Promotion Battery | `scripts/research/run_promotion_battery.py` |
| Ruleset Manifest | `production_data/decision_rulesets/manifest.json` |
| Governance Policy | `governance/AGENT_ROUTING_POLICY.md` |
| Agent Registry | `agents/AGENT_REGISTRY.json` |
| **Live Portfolio Rules** | `production_data/AGENTIC_ACCOUNT_RULES.md` |
| **Phase 2 Entry Prices** | `production_data/phase2_entry_prices.json` |

## Live Portfolio (Agentic Account 802349084)

A live Robinhood account (802349084) tracks the model top-30 in real money. Operational rules at `production_data/AGENTIC_ACCOUNT_RULES.md`. Key rules: weekly Monday equal-weight rebalance, hard exit if drawdown vs XBI ≤ −2pp, IRAs managed independently. Claude Code skills for execution: `biotech-rebalance`, `biotech-portfolio-status`, `biotech-governance-check`, etc. (see `~/.claude/skills/biotech-*/`). Entry prices for P&L tracking in `production_data/phase2_entry_prices.json` — do NOT use screener snapshot reference prices as entry prices.

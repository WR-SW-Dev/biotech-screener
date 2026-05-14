# Bioshort upstream P2 — producer identification (2026-05-06)

Read-only investigation per operator direction. No code, cron, or artifact changes; finding memo only.

## Summary

The `output/hedge_report/` upstream is **unscheduled and orphaned**. Last write was **2026-03-26** (41 days stale as of today). `bioshort_watch` (LLM agent) continues to read it weekly via Friday cron and faithfully propagates the stale `as_of_date=2026-03-26` into its `_watch.md` title — which is the body-staleness pattern flagged in the agent fleet audit memo and re-confirmed in Spec 083 §2.5.

Stop rule **not triggered**: the producer reads `rankings.csv` read-only (for fallback portfolio weights and catalyst/phase joins) but does **not** modify scoring, ranker, EV, sizing, eligibility, or `catalyst_delta_score`. No live scoring or daily-production path depends on the producer.

## 1. Producer

| Field | Value |
|---|---|
| Producer | `tools/biotech_hedge_report.py` |
| Writes (CLI) | `output/hedge_report/hedge_report_{as_of_date}.{json,md}` and `output/hedge_report/archive/hedge_report_{as_of_date}.json` |
| Producer-side scoring touch | NONE (writes only hedge artifacts) |
| Reads | `rankings.csv` (read-only, fallback portfolio weights line 255–319 + catalyst/phase join line 432–447) |
| Other inputs | portfolio CSV (CLI arg), price history, possibly options data |

## 2. Schedule

| Source | Result |
|---|---|
| `crontab -l \| grep -i 'hedge\|biotech_hedge_report'` | **No cron entry produces hedge_report.** The only hedge-related cron is `10 18 * * 5 ... run_agent_direct.py --agent bioshort_watch --message "HEARTBEAT"` (consumer, not producer). |
| `tools/cron_*.sh` callers | None invoke `biotech_hedge_report.py`. |
| `run_daily_production.py` | Does not invoke `biotech_hedge_report.py`. |
| Last actual write | `output/hedge_report/hedge_report_2026-03-26.{json,md}` mtime 2026-03-26 17:55. |

**Conclusion: the producer is run manually (or was, in March). Nothing schedules it.**

## 3. Consumers

| Consumer | Path | What it does |
|---|---|---|
| `tools/build_bioshort_watch.py` | `output/hedge_report/hedge_report_*.json` (line 50–51) | Sorts by date desc; loads latest + prior; produces `artifacts/bioshort_watch/{date}_watch.{json,md}` (date stamp follows upstream `as_of_date` when no CLI override — Spec 083 §2.5) |
| `bioshort_watch` LLM agent (via Friday 18:10 cron) | Invokes `build_bioshort_watch.py` and / or reads `output/hedge_report/` directly per its `SOUL.md` boundaries (`Read: output/hedge_report/, artifacts/bioshort_watch/, ...`) | Surfaces verdict / structure changes for human review |
| `dashboard/app.py:706,724` | `output/hedge_report/hedge_report_*.json` | Dashboard display |
| Consumers — production scoring path? | NONE | Confirmed by grep against `run_screen.py`, `module_3*.py`, `module_5*.py`, `ranker_*.py`, `selector_engine.py`, `decision_engine.py`, `event_ev/` — empty. Note: `common/ranker_active_contract.py` is on unmerged hygiene branch (not in production). |

## 4. Is `output/hedge_report/` current or stale?

**Stale by 41 days.**

```
output/hedge_report/
├── BIOSHORT_VERDICT.{json,md}                    Mar 26 17:55  (verdict snapshot, frozen)
├── archive/                                      Mar 26 17:55
├── hedge_report_2026-03-17.{json,md}             Mar 18 09:11 / Mar 18 09:11
├── hedge_report_2026-03-18.{json,md}             Mar 18 14:07 / Mar 18 14:07
└── hedge_report_2026-03-26.{json,md}             Mar 26 17:55 / Mar 26 17:55
```

Today (2026-05-06): no fresh hedge_report. Three reports total in the directory (2026-03-17, 2026-03-18, 2026-03-26).

## 5. Is `bioshort_watch` reading or just referencing?

**Reading.** Confirmed:

- `agents/bioshort_watch/SOUL.md` declares `Read: output/hedge_report/` in its boundaries.
- `tools/build_bioshort_watch.py:50–51` actively globs `hedge_report_*.json` in `output/hedge_report/` and feeds the result through to the artifact builder.
- `artifacts/bioshort_watch/2026-05-06_watch.md` first line: `# Bioshort Watch — 2026-03-26` — the body title carries the upstream `as_of_date` (Mar 26) even though the filename is today (2026-05-06). This is **not** a date-stamp bug per Spec 083 §2.5; it is faithful propagation of stale upstream data through `build_bioshort_watch.py`'s default `date_str = as_of_date or current_date` (line 400) where `current_date = current.get("as_of_date", "unknown")` (line 321) reads the upstream's `as_of_date` field — which is 2026-03-26.

So the consumer is healthy in the sense of not corrupting; it's just reading stale source data faithfully.

## 6. Recommended disposition

**Three options, ranked by risk:**

### (a) Document as orphaned [RECOMMENDED — lowest risk]

- Annotate `agents/bioshort_watch/SOUL.md` (or this memo's referent in the agent fleet audit) noting that the upstream producer is unscheduled and the agent is intentionally reading stale data until a producer-restoration decision is made.
- Optionally: change `bioshort_watch` cron from weekly Friday → monthly first-Friday (or pause entirely) to avoid weekly LLM cost on unchanging data. (This is a P1-style cadence change; would require its own ticket per operator's "do not bundle" rule.)
- Hedge governance question (whether hedge reports should be produced at all) escalates to a separate decision.

### (b) Restore producer wiring

- Add a cron entry invoking `biotech_hedge_report.py` weekly (Friday morning, before bioshort_watch reads it).
- Requires: identifying the correct CLI arguments (portfolio CSV path, options data path, etc.); confirming the input data sources are still being maintained; deciding on output retention policy.
- Risk: medium. Not a code-change risk, but a "are we sure we want fresh hedge reports?" decision.

### (c) Retire bioshort_watch

- If hedge governance is no longer desired, retire `bioshort_watch` (Spec 085-style SUPPRESSED PLACEHOLDER or full retire).
- This kills the only LLM consumer of `output/hedge_report/`. Dashboard consumer would still display whatever's in the directory.
- Requires operator decision on hedge governance scope.

## 7. Why not edit anything in this pass

Per operator scope: "no edits unless the finding is purely documentation and obviously safe." The disposition decision (which of (a)/(b)/(c)) is a real product question, not a documentation correction. Surfacing the finding lets the operator decide.

The agent fleet audit memo (`artifacts/audit/agent_fleet_investment_logic_audit_2026_05_06.md`) already documents bioshort upstream staleness as P2 (Section E row 9, Section F item 3, Section I P3 #1); this memo refines that finding with the producer ID, schedule (none), and consumer wiring.

## 8. Out-of-scope confirmations

- No selector / ranker / EV / sizing / eligibility / scoring change in producer.
- `catalyst_delta_score` not touched by the producer.
- No production-decision integrity is at risk from continued staleness — only the bioshort_watch agent's narrative carries the staleness, and it's a research-shadow agent (per registry).

---

_Generated by bioshort upstream P2 read-only investigation per operator direction (2026-05-06). No edits made beyond this memo._

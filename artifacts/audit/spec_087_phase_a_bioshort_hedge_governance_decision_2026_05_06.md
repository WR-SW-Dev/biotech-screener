# Spec 087 Phase A — Bioshort Hedge-Report Producer Restoration / Hedge-Governance Decision Memo

**Date**: 2026-05-06
**Phase**: A — read-only investigation, no code/cron/artifact changes
**Predecessor**: `artifacts/audit/bioshort_upstream_p2_finding_2026_05_06.md` (producer ID + suppression rationale)
**Scope guard**: no scoring / ranker / EV / sizing / Module 3 / Module 5 / `catalyst_delta_score` change; no cron wiring; no `bioshort_watch` LLM reactivation; no producer execution.

---

## 1. Recommendation

**Disposition B — restore deterministic producer only, no LLM consumer.**

Add a weekly cron invoking `tools/biotech_hedge_report.py` with an explicit `--portfolio-csv` pointing at the latest snapshot. Keep the `bioshort_watch` LLM agent suppressed. Re-evaluate B → C (LLM consumer reactivation) after 2–4 weeks of fresh weekly reports.

Rationale below; operator-decision points called out at end.

---

## 2. Producer input contract — known

`tools/biotech_hedge_report.py` (2,983 lines; entry `main()` at line 2897).

| Argument | Default | Required for sensible run? | Status today |
|---|---|---|---|
| `--as-of-date` | `date.today().isoformat()` | no — defaults work | OK |
| `--portfolio-csv` | `None` | **YES** — `None` falls through to `rankings.csv` which is a 3-line stub; was the failure mode in the 2026-05-03 cron-misescalation incident | **MUST be supplied** |
| `--price-csv` | `production_data/price_history.csv` | no — defaults work | `25.4 MB`, mtime 2026-05-06 13:32 → **FRESH** |
| `--hedge-notional` | `$1,000,000` | no | OK |
| `--output-dir` | `output/hedge_report/` | no | OK |
| `--snap-dir` | `data/snapshots/{as_of_date}` | no | OK |
| `--options-source` | `auto` (Tasty → Massive → realized-vol fallback) | no | see §3 |
| `--backtest-mode` | `auto` (historical if S3 creds, else BS) | no | OK |

Required CLI invocation (from a clean state, today):

```bash
python tools/biotech_hedge_report.py \
  --as-of-date 2026-05-06 \
  --portfolio-csv data/snapshots/2026-05-06/portfolio_positions.csv
```

The portfolio CSV uses `target_weight_pct` (verified column at `data/snapshots/2026-05-06/portfolio_positions.csv` row 1), which `load_portfolio_weights` accepts at `tools/biotech_hedge_report.py:290–298`.

---

## 3. Input freshness — all green except options source

| Input | Path | Last write | Verdict |
|---|---|---|---|
| Price history | `production_data/price_history.csv` | 2026-05-06 13:32 | FRESH |
| Portfolio positions (today) | `data/snapshots/2026-05-06/portfolio_positions.csv` | 2026-05-06 09:47 | FRESH (3 consecutive days verified: -04, -05, -06) |
| Portfolio positions (canonical) | `production_data/portfolio_positions.csv` | does not exist | not used; CLI doc lists this only as an example path |
| Snapshot dir | `data/snapshots/2026-05-06/` | present | OK |
| Options — Massive | `MASSIVE_API_KEY` | SET in `.env` | available |
| Options — Tasty | not visible in `.env` | absent | unavailable |
| Options — realized-vol | always-on | n/a | available |

**`--options-source auto` would select Massive today.** The 2026-03-26 report fell back to `realized_vol_proxy` (`source_selection_reason: "auto: no options API credentials; using realized vol proxy"`); whatever caused that fallback then is worth a one-line check in Phase B before the first restored cron run, but it does not block the disposition decision.

---

## 4. Consumers — what `output/hedge_report/` actually feeds

Confirmed via `grep` against `run_screen.py`, `module_3*.py`, `module_5*.py`, `ranker_*.py`, `selector_engine.py`, `decision_engine.py`, `event_ev/`, `common/ranker_active_contract.py`, plus direct file reads:

| Consumer | Site | What it reads | Status |
|---|---|---|---|
| `tools/build_bioshort_watch.py` | invoked by `run_screen.py:12407–12422` **every production run** | latest two `hedge_report_*.json` by glob | active, daily |
| `bioshort_watch` LLM agent | `crontab -l` weekly Friday `10 18 * * 5` | `output/hedge_report/`, `artifacts/bioshort_watch/` | **SUPPRESSED 2026-05-06** (commented out; manual invocation preserved) |
| Dashboard | `dashboard/app.py:693–735` four endpoints | `BIOSHORT_VERDICT.json`, latest `hedge_report_*.json`, `artifacts/bioshort_watch/`, archive list | active; currently serves 41-day-stale data |
| Production scoring path | none | none | **NONE — confirmed empty** |

### 4.1 Newly-surfaced finding (worth flagging in this memo)

The deterministic watch builder is **still running daily inside `run_screen.py`** even though the LLM consumer is suppressed. Evidence:

- `artifacts/bioshort_watch/2026-05-04_watch.md`, `2026-05-05_watch.md`, `2026-05-06_watch.md` all exist with mtimes matching that day's snapshot run.
- `diff 2026-05-06_watch.md 2026-05-05_watch.md` → only difference is the `Generated:` timestamp line. Body content is byte-identical and reads:

  ```
  # Bioshort Watch — 2026-03-26
  **Alert level: MEDIUM** | Prior: 2026-03-18
  ## Alerts
  - CARRY MOVED: 153.0 → 8.0 bps
  - GREEKS SHIFTED: position delta or theta moved materially
  - SOURCE DEGRADED: using realized_vol (proxy/realized vol)
  ```

This is the body-staleness propagation pattern flagged in Spec 083 §2.5 — fresh-dated filenames carrying upstream `as_of_date` (2026-03-26) in the body title. The deterministic builder is faithful to its inputs; the inputs are stale.

**Implication for disposition:** Option A (keep suppressed permanently) leaves this misleading daily artifact stream in place indefinitely. Option B closes it cleanly because fresh weekly hedge reports will produce non-degenerate week-over-week diffs instead of identical stale propagation.

---

## 5. Hedge-governance purpose — what is the report supposed to govern?

Reconciling Spec 029, `agents/bioshort_watch/SOUL.md`, and `hedge_report_2026-03-26.md`:

| Question | Answer from existing artifacts |
|---|---|
| Who is the audience? | "**This report is for IC discussion, not execution**" (`hedge_report_2026-03-26.md` line 142) |
| What does it recommend? | Optimal XBI/IBB ETF put/collar/spread structure to hedge a $1M-notional EW-top-N biotech long book |
| Does any live book trade off it? | No live execution path. No reference in `decision_engine.py`, `selector_engine.py`, or any sizing module. |
| Does it affect ranking/EV/sizing? | No — Spec 029 explicitly: "Read-only extension. Does not change DEM, ranking, execution, or production screen." |
| What would consume the verdict in production? | Today: dashboard display, IC narrative, and an LLM watcher (suppressed). Nothing else. |

**Hedge-governance purpose, restated:** weekly IC-ready evidence that *if* the operator wished to hedge biotech systematic risk, here is the cheapest currently-available structure on XBI/IBB, with backtest, Greeks, regime profile, and confidence drivers. It is governance evidence, not an execution signal.

This is a real but **bounded** purpose. It justifies a deterministic producer; it does not by itself justify an LLM-watcher cost.

---

## 6. Disposition options — full evaluation

| Option | What changes | Risk | Cost | What it leaves broken |
|---|---|---|---|---|
| **A. Keep suppressed / document orphaned permanently** | nothing | lowest | $0 | dashboard serves stale; daily watch artifacts still produced with stale body; latent confusion |
| **B. Restore producer only, no LLM consumer (RECOMMENDED)** | add weekly cron for `biotech_hedge_report.py`; LLM agent stays suppressed | low — producer touches no scoring | one cron line + `--portfolio-csv` arg auto-discovery | nothing structural; LLM watcher reactivation is a future B → C question |
| **C. Restore producer + monthly/weekly bioshort_watch** | adds B + uncomments LLM cron | low-medium — premium LLM cost; surfaces verdicts for human review | LLM call/wk + monitoring of escalation behavior | nothing, but premature absent observation period |
| **D. Retire bioshort + hedge-report surface entirely** | removes producer, builder, agent, dashboard endpoints, `output/hedge_report/`, `artifacts/bioshort_watch/`, `run_screen.py` invocation | medium — destructive | meaningful refactor | hedge-governance evidence permanently gone; future restore would be from-scratch |

### 6.1 Why B over A

A leaves the dashboard and the daily deterministic watch artifacts both serving stale data. The 2026-05-03 cron-misescalation incident already showed how stale upstream + an LLM watcher = false escalation. A is "safe" only on a fail-closed reading; it is genuinely *unsafe* for downstream consumers (dashboard, manual `run_agent_direct.py` invocations) that don't know they're consuming 41-day-old data.

### 6.2 Why B over C

C re-introduces the LLM cost and the escalation surface area before any operator has confirmed the watcher's behavior is wanted. The `2026-05-03_cron_misescalation_issue.md` memo documents the watcher mis-escalating against stale upstream — that confidence has not been rebuilt. Reactivate the producer, observe a few cycles of fresh reports through the dashboard and the deterministic watch artifacts, *then* decide on C.

### 6.3 Why B over D

D is the largest blast-radius option and forecloses the hedge-governance lane. There is no positive evidence for D — only a passive "no one is using it." Closing surfaces should require active evidence that the surface is harmful, not that it is unused.

---

## 7. Required for B → executable spec (Phase B inputs, NOT Phase A scope)

The Phase A memo stops here. Phase B (separate spec/PR) would need to define:

1. **CLI default repair.** Per `2026-05-03_cron_misescalation_issue.md` §B Option A, change `--portfolio-csv` default from `None` to auto-discover the latest `data/snapshots/[0-9]*-*/portfolio_positions.csv`. This removes the implicit coupling between cron-prompt knowledge and tool defaults.
2. **Cadence.** Recommend weekly Thursday or Friday morning (before any LLM-watch reactivation could read it). One run per week is sufficient — IC discussion cadence, not market-data cadence.
3. **Output retention.** Existing artifacts in `output/hedge_report/` and `output/hedge_report/archive/` are preserved (per audit-trail principle). Decide whether to add a retention sweep (e.g., archive > N weeks).
4. **Dashboard staleness banner.** Phase B should add a "last-fresh" indicator to the four dashboard endpoints so consumers see report age explicitly.
5. **Pre-flight options-source check.** Confirm `MASSIVE_API_KEY` works against the live endpoint; if not, document the realized-vol-proxy fallback as expected, not a regression.
6. **Rollback path.** Producer is a single CLI; rollback = comment out the cron line. No state migration. `output/hedge_report/` is append-only by `as_of_date`.
7. **Acceptance gate (per Spec 087 acceptance criteria):**
   - explicit hedge-governance purpose → §5 above
   - known input contract → §2 above
   - known cadence → weekly (Phase B confirms)
   - no scoring dependency → §4 confirmed empty
   - rollback path → §7 item 6 above

---

## 8. Out-of-scope confirmations (re-stated for the record)

- No selector / ranker / EV / sizing / eligibility / scoring change anywhere in this disposition.
- `catalyst_delta_score` not touched.
- No production-decision integrity is at risk from continued staleness — only IC narrative and dashboard display.
- `agents/AGENT_REGISTRY.json` and `agents/ops_supervisor/supervisor.py` `SUPPRESSED_AGENTS` already reflect the suppression cleanly; B does not require flipping `bioshort_watch` registry status.
- Last hedge report 2026-03-26; 41 days stale; producer `tools/biotech_hedge_report.py` (114 KB, 2,983 lines, mtime 2026-04-09) is preserved unchanged.

---

## 9. Operator decision points

The memo has answered Phase A's required questions:

| Spec 087 acceptance question | Answer |
|---|---|
| What inputs does `tools/biotech_hedge_report.py` need? | `--portfolio-csv` (essential), price history (default OK), snapshot dir (default OK), options creds (Massive present, Tasty absent) |
| Do those inputs exist and are fresh? | YES — all green except Tasty (unavailable; auto fallback to Massive) |
| What is the hedge report supposed to govern? | IC-discussion evidence on optimal hedge structure for the long biotech book — not execution |
| Who/what consumes it? | `build_bioshort_watch.py` (active daily via `run_screen.py`), dashboard (4 endpoints), `bioshort_watch` LLM agent (suppressed). No scoring path. |
| Recommended disposition? | **B — restore deterministic producer only, no LLM consumer** |

**Operator action requested**: confirm B (restore producer-only) or pick A / C / D. If B is confirmed, I will draft the Phase B spec defining CLI default repair, cadence, dashboard staleness banner, and rollback path — no execution until that spec is reviewed.

---

_Generated 2026-05-06 as Spec 087 Phase A read-only investigation. No code, cron, or artifact changes made beyond writing this memo._

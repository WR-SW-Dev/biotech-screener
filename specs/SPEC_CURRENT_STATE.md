# Biotech Screener — Current Repo Spec

**Date:** 2026-04-09
**Status:** Living document — reflects implemented state, not aspirational design

---

## 1. Product definition

This repo is a **point-in-time-safe biotech investment screening and monitoring system**. Its production core is a deterministic daily screening pipeline over a biotech universe, with externalized rulesets, health gates, snapshot promotion, and a large set of read-only research and operator artifacts. The original architecture is a screening stack with Modules 1-5, a post-processing decision engine, and a hydration/data layer.

The current repo has evolved beyond the older "screen only" framing. It now includes an implemented **Event EV** sidecar, timing-hazard infrastructure, event-quality review tooling, production monitors, and many post-promotion artifacts, while still keeping those newer subsystems **diagnostic / non-binding** rather than live ranker inputs.

## 2. Primary objective

The primary production objective is to generate a **daily biotech snapshot** that ranks and sizes names in a point-in-time-safe way, then promote that snapshot only if hard production gates pass. The system must be deterministic, auditable, and governed by frozen rulesets rather than ad hoc tuning in code.

A secondary objective is to run **research overlays** around catalysts, timing, options, event quality, and Event EV, but those overlays are not allowed to silently mutate selector, ranker, or construction behavior unless explicitly promoted through a separate governance path.

## 3. Core problem the repo solves

This is **not** a generic multi-asset alpha lab. The repo's current design center is:
**rank biotech names and biotech catalysts in a PIT-safe daily process, while accumulating evidence for future event-driven overlays.** The live system still centers on the screening/decision engine, and the newer Event EV stack exists for operator visibility and future validation, not for immediate portfolio control.

## 4. System boundary

The system has two layers:

**Production core**

* Universe filtering
* Survivability / financial health
* Catalyst detection
* Clinical development scoring
* Composite ranking / decision engine
* Health gates
* Atomic snapshot promotion

**Research and operator sidecars**

* Event EV scoring
* Timing hazard
* Event quality shadow / review queues
* Options overlays and diagnostics
* Factor drift, production monitor, risk monitor
* Dashboard APIs over read-only artifacts

## 5. Inputs and data sources

The repo's production inputs include PIT caches, CTGov trials, SEC 13F, price history, market data, regulatory calendars, and other sidecars needed by the screen and health checks. Daily production also validates `market_data.json`, CTGov cache availability, SEC 13F cache health, PIT price cache health, and other supporting inputs before or after the screen run.

For Event EV specifically, the daily scorer consumes:

* PDUFA dates
* Catalyst events
* Event ledger
* CRT resolutions
* Rankings snapshot
* Options forward log
* CRT calibration inputs

## 6. Production workflow

The canonical daily workflow is:

1. Refresh price history.
2. Warm caches.
3. Run `run_screen.py` in phase-2 decision mode into staging.
4. Run integrity audit.
5. Evaluate hard and advisory gates.
6. Write `run_manifest.json`.
7. Promote snapshot atomically only on PASS or WARN.
8. Generate a long tail of non-blocking artifacts and monitors.

The repo treats `tools/run_daily_production.py` as the single orchestration entrypoint for this cycle, with manifesting, gate evaluation, idempotent reruns, and atomic promotion semantics.

## 7. Production outputs

The main production artifact is a daily snapshot under `data/snapshots/{date}/`, anchored by `rankings.csv`, metadata, health artifacts, and manifest data. The repo defines canonical output column sets for:

* Validation snapshot
* Decision portfolio
* Portfolio positions

`rankings.csv` is the central contract. It carries decision-engine outputs, diagnostic fields, options fields, selector/ranker columns, and Event EV expectation-model pass-through fields including `short_interest_pct`, `close_price`, `market_cap_mm`, and `priced_move_pct`.

## 8. Ranking and decision-engine contract

The repo uses an externalized **decision ruleset** model. Rulesets live in JSON, are versioned/frozen, and are governed separately from code. The decision engine remains a post-processing layer controlling sort anchors, signal weights, eligibility gates, tiers, and sizing bands. Production runs enforce a ruleset-governance gate before expensive work begins.

The ranking contract includes:

* Legacy composite fields
* Decision-engine contributions
* Selector/ranker blocks
* Regime labels
* Options diagnostics
* Options quality fields
* Market-model disagreement diagnostics
* Event EV expectation pass-through columns

## 9. Event EV subsystem

The Event EV engine is a first-class implemented sidecar. Its formal architecture is six layers:

1. Catalyst graph
2. Timing hazard
3. Outcome model
4. Expectation / crowd-belief model
5. Payoff engine
6. Portfolio translation

Wrapped by `EventEVCalculator`. Core data contracts in `event_ev/data_contracts.py` include `CatalystNode`, `TimingEstimate`, `OutcomeProbabilities`, `CrowdBelief`, `ScenarioPayoffs`, `PositionRecommendation`, and `EventEV`.

The daily scoring implementation (`tools/build_event_ev_scores.py`) writes:

* `{date}_event_ev_scores.json`
* `{date}_event_ev_full.json`
* `{date}_ev_leaderboard.json`
* `{date}_ev_leaderboard.md`

## 10. Event EV policy status

Event EV is **implemented but diagnostic only**. EV scores do not feed selector, ranker, construction, or sizing in production. The daily production runner calls Event EV as a non-blocking step late in the artifact pipeline, after snapshot promotion logic.

## 11. Expectation-model status

The current repo includes pass-through fields in `rankings.csv` for the Event EV expectation model: `short_interest_pct`, `close_price`, `market_cap_mm`, and `priced_move_pct`. Feature coverage is ~95%+, with `insider_net_buy_value_90d` as the major remaining gap. The expectation layer remains diagnostic and does not constitute new alpha.

## 12. Timing hazard subsystem

Timing hazard is implemented as a production-side diagnostic overlay and review infrastructure, but not promoted as a decision input. The repo contains timing-hazard artifacts, calibration ledgers, dashboard endpoints, and research scripts for review, retraining, and OOS validation. Production behavior is unchanged; the subsystem is **research only / dashboard only**.

## 13. Event quality subsystem

The repo includes event-quality infrastructure: confusion dashboards, outlier review queues, operator-priority queues, and unified review packets. These outputs are wired into the daily production artifact chain and dashboard. The loop is advisory rather than ranker-authoritative.

## 14. Monitoring and gate model

The production runner uses a large gate set covering data freshness, market-data schema and coverage, screen success, audit, drift monitoring, CTGov PIT date health, SEC 13F cache health, institutional coverage, forward evaluation, ruleset governance, regulatory calendar health, options coverage, hard-catalyst queue health, and more. Snapshots are blocked on FAIL, promoted on PASS or WARN, and all verdicts are written into a manifest and gate ledger.

The gate system is a core part of the product spec. The "daily answer" is not just a ranking file, but a **governed, provenance-stamped snapshot** with explicit operational health attached.

## 15. Dashboard and API contract

The dashboard is read-only and serves operator-facing artifacts without mutating positions or production state. It exposes APIs for rankings, positions, policy comparisons, timing hazard, event quality, risk monitor, options overlays, and Event EV. Event EV endpoints:

* `/api/event_ev/leaderboard/{date}`
* `/api/event_ev/detail/{ticker}/{date}`
* `/api/event_ev/history`

The operator consumes research overlays through **artifact-driven, read-only APIs**, not by injecting them into selection logic.

## 16. Invariants

* **PIT safety**: no feature may leak information after `as_of_date`; catalyst visibility is anchored by disclosure timing; outcome evaluation must only use prior-resolved data.
* **Determinism**: same inputs and same snapshot date must produce the same outputs.
* **Externalized governance**: ranker and decision behavior must be controlled by frozen rulesets and promotion logic, not ad hoc code edits.
* **Non-binding diagnostics**: Event EV, timing hazard, and similar sidecars may produce artifacts and APIs, but must not affect selector/ranker/construction unless a separate promotion spec says so.
* **Atomic promotion**: snapshot replacement must preserve idempotency and avoid silent overwrite corruption.

## 17. Current maturity assessment

**A production-grade biotech screener with a frozen decision-engine core and a rapidly growing event-driven research superstructure.**

What is mature:

* Daily snapshot orchestration
* PIT discipline
* Gating and manifesting
* Ruleset governance
* Operator dashboard
* Broad artifact pipeline

What is implemented but still research-grade:

* Event EV as daily scored leaderboard
* Timing hazard as warning / calibration system
* Event-quality shadow sizing / review queues
* Several options-derived overlays

## 18. One-sentence repo spec

> `biotech-screener` is a point-in-time-safe daily biotech screening and snapshot-promotion system with an externalized decision-engine core and a non-binding event-driven research layer (Event EV, timing hazard, event quality, and options overlays) exposed through artifacts and read-only APIs.

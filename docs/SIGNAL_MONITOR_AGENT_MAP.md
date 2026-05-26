# Signal Monitor Agent Map

**Purpose:** Read-only reference documentation of signal-monitor agents, their schedules, authority levels, and production boundaries.

**Status:** 8 signal-monitor agents, all active, Lane B (LLM-on-anomaly), read-only, healthy and operational.

---

## 1. Status Summary

| Dimension | State |
|-----------|-------|
| Active agents | 8 (biotech_news_digest, catalyst_delta, price_action_watch, options_watch, review_queue_steward, ic_health_monitor, intraday_mover_watch, grok_biotech_watch) |
| Authority level | `observe_only` (all) |
| LLM policy | Lane B / LLM-on-anomaly (all) |
| Production impact | None (informational only) |
| Health | Operational |
| Registry status | Active, supervised by orchestrator |

---

## 2. Agent Matrix

### biotech_news_digest
- **Role:** Digest and distribute biotech news to followed tickers; classify by regulatory/clinical/corporate/financing/other
- **Cadence:** 3x daily (08:00, 15:00, 18:00 ET on M-F)
- **Authority:** `observe_only`
- **What it detects:** Press releases, wire service alerts, regulatory filings, clinical announcements
- **Output surface:** `artifacts/news_digest/*.{html,txt,json}`; email delivery via SMTP
- **Production impact:** None (digest only; no scoring, ranking, or portfolio impact)

### catalyst_delta
- **Role:** Monitor and quantify delta in catalyst timing, urgency, or material risk between consecutive snapshots
- **Cadence:** Daily 18:20 ET (M-F, after production)
- **Authority:** `observe_only`
- **What it detects:** Catalyst shifts (new clinical events, regulatory changes, financing news, competitive dynamics)
- **Output surface:** `artifacts/signal_monitors/catalyst_delta_{date}.json`
- **Production impact:** None (decision-support context only)

### price_action_watch
- **Role:** Monitor price moves, volatility, breadth; correlate with known catalysts and sentiment
- **Cadence:** Daily 18:30 ET (M-F, post-production)
- **Authority:** `observe_only`
- **What it detects:** Unusual price action, correlation breaks, volatility spikes, liquidity gaps
- **Output surface:** `artifacts/signal_monitors/price_action_{date}.json`
- **Production impact:** None (analytics context only)

### options_watch
- **Role:** Monitor implied volatility, skew, flow; detect hedging or speculation signals
- **Cadence:** Daily 18:40 ET (M-F, post-production)
- **Authority:** `observe_only`
- **What it detects:** IV term structure changes, skew shifts, unusual open interest, option flows
- **Output surface:** `artifacts/signal_monitors/options_{date}.json`
- **Production impact:** None (market microstructure context only)

### review_queue_steward
- **Role:** Maintain and prioritize portfolio review queue based on recent signals, catalyst timelines, and risk thresholds
- **Cadence:** Daily 18:50 ET (M-F, post-production)
- **Authority:** `observe_only`
- **What it detects:** Positions due for rebalance review, catalyst-driven decision points, risk-adjusted priority changes
- **Output surface:** `artifacts/review_queue/review_queue_{date}.json`; `review_queue_memo_{date}.md`
- **Production impact:** None (human review list only; no auto-execution)

### ic_health_monitor
- **Role:** Continuous monitoring of IC (Information Coefficient) on key signals; flag regime shifts or degradation
- **Cadence:** Continuous; daily summary post-production
- **Authority:** `observe_only`
- **What it detects:** IC drift, correlation breaks, signal strength changes, forecast degradation
- **Output surface:** `artifacts/signal_monitors/ic_health_{date}.json`; heartbeat status log
- **Production impact:** None (diagnostic monitoring; no model retraining or promotion)

### intraday_mover_watch
- **Role:** Monitor intraday price moves during market hours; alert on unusual movers relative to baseline volatility
- **Cadence:** Continuous (9:30 AM - 4:00 PM ET); periodic artifact writes during market
- **Authority:** `observe_only`
- **What it detects:** Pre-market gaps, unusual intraday moves (>3σ), catalyst-driven spikes, breadth shifts
- **Output surface:** `artifacts/intraday_movers/{date}_movers.json`; digest email (morning pre-market, midday, end-of-day)
- **Production impact:** None (tactical awareness only; no portfolio changes)
| Spec source | Spec 063 (Intraday Mover Watch) — live since 2026-04-17 |

### grok_biotech_watch
- **Role:** Continuous monitoring of biotech news, clinical trial milestones, regulatory events, M&A rumors via semantic search
- **Cadence:** Continuous; real-time artifact updates
- **Authority:** `observe_only`
- **What it detects:** Clinical data readouts, FDA meetings, trial enrollment updates, competitive moves, financing events
- **Output surface:** `artifacts/grok_watch/*.json`; optional enrichment to news digest
- **Production impact:** None (contextual intelligence only)

---

## 3. Execution Schedule

All times in ET (Eastern Time), M-F unless noted.

| Time | Agent | Action |
|------|-------|--------|
| 08:00 | biotech_news_digest | Morning digest (overnight → 08:00) |
| 09:30 - 16:00 | intraday_mover_watch | Continuous market-hours monitoring |
| 15:00 | biotech_news_digest | Midday digest (08:00 → 15:00) |
| 18:00 | biotech_news_digest | Evening digest (15:00 → 18:00) |
| 18:20 | catalyst_delta | Daily snapshot comparison |
| 18:30 | price_action_watch | Daily price/volatility summary |
| 18:40 | options_watch | Daily IV/flow summary |
| 18:50 | review_queue_steward | Review queue prioritization |
| continuous | ic_health_monitor | Signal coefficient drift |
| continuous | grok_biotech_watch | Semantic event detection |

---

## 4. Lane B / LLM-on-Anomaly Policy

**Deterministic pre-filter → LLM escalation:**

1. Each signal monitor runs a deterministic anomaly pre-filter (statistical thresholds, rule-based gates, outlier detection).
2. If no anomaly is detected, the monitor produces a **routine artifact** with no LLM involvement.
3. If an anomaly is detected (unusual price move, IC drift, catalyst spike, flow signal), the monitor invokes the LLM for:
   - Contextual interpretation (why might this have happened?)
   - Risk flagging (is this actionable?)
   - Decision-support narrative

**Cost optimization:** Routine days may produce **zero LLM calls** across all signal monitors. LLM invocation is anomaly-triggered, not cadence-driven.

**Example:** `price_action_watch` on a quiet market day:
- Deterministic filter: no >3σ moves → routine artifact written
- LLM: not invoked
- Artifact: `price_action_2026-05-26.json` (low-signal summary, no narrative)

**Example:** `ic_health_monitor` on a regime-shift day:
- Deterministic filter: signal IC drops >0.05 → anomaly
- LLM: invoked for interpretation
- Artifact: `ic_health_2026-05-26.json` + memory note on regime change

---

## 5. Production Boundaries

### Signal monitors **CANNOT**:
- Modify rankings or selector results
- Change sizing, position weights, or allocation fractions
- Execute trades or rebalances (automatic or triggered)
- Alter scoring model inputs, coefficients, or thresholds
- Auto-trigger portfolio changes or liquidations
- Modify production data (universe, short interest, coinvest scores, etc.)

### Signal monitors **CAN**:
- Flag anomalies and risks for human review
- Provide decision context and narrative
- Alert on threshold breaches (price, IV, flow, IC drift)
- Inform portfolio management and position-level decisions
- Suggest areas worth investigating
- Log historical observations for post-mortem analysis
- Write read-only artifacts to decision-support surfaces

---

## 6. Recent Activity Reference

**2026-05-25 Observations:**

| Agent | Observation |
|-------|-------------|
| biotech_news_digest | 10 items in morning digest; regulatory category dominant |
| intraday_mover_watch | 0 significant intraday movers detected (quiet market) |
| catalyst_delta | No material catalyst changes vs 2026-05-24 |
| price_action_watch | Normal volatility; no >2σ moves |
| options_watch | IV stable; no term structure shifts |
| ic_health_monitor | Signal IC normal; no regime alerts |
| review_queue_steward | 3 positions flagged for routine rebalance review |
| grok_biotech_watch | 2 PDUFA date updates; 1 clinical trial enrollment milestone |

All monitors operational, no anomalies, no escalations.

---

## 7. Relationship to Town/OpenClaw Flow Contract

See reference documents:
- `docs/TOWN_OPENCLAW_AGENT_FLOW_CONTRACT.md` — agent communication, authority, decision gates
- `docs/FAILURE_PATTERN_LIBRARY.md` — common agent failure modes and recovery patterns
- `docs/templates/SELF_IMPROVEMENT_PROPOSAL.md` — proposal workflow for agent/skill changes

**Change governance:** Any proposed signal-monitor change (new signal, modified anomaly threshold, additional LLM context) **must go through the Town/OpenClaw proposal-only workflow first**:

1. Submit `SelfImprovementProposal` via `/town-brief` command
2. Town agent routes to OpenClaw for preflight review
3. Preflight validates:
   - Does it stay within observe-only boundary?
   - Does it avoid production model/scoring/ranking changes?
   - Does it maintain Lane B LLM-on-anomaly cost policy?
   - Does it maintain read-only output surfaces?
4. If SAFE: proposal approved for implementation (separate ticket)
5. If BLOCKED: feedback provided; revise or defer

---

## 8. Non-Goals

This document is reference-only. It does **not** authorize or describe:

- Live monitor changes, enhancements, or feature additions
- Cron entry modifications or schedule shifts
- Changes to model, ranker, selector, sizing, or KG
- Automatic portfolio actions or trading logic
- OpenClaw wrapper edits or capability expansion
- Authority escalation from `observe_only` to `write_artifacts` or higher
- New LLM-invoked analysis beyond anomaly detection

Any of the above require a separate spec with full design, test plan, and operator approval.

---

## 9. Appendix: Authority & Governance Levels

All signal monitors are `observe_only`:

- **observe_only:** read fleet state, read production data, read market data, write artifacts to `artifacts/` only, no model/ranking/sizing changes, no production data mutations
- **observe_and_propose:** observe_only + propose changes via Town/OpenClaw workflow
- **write_artifacts:** (reserved for future ops tools)
- **mutate_data:** (reserved for data-pipeline agents only; e.g., universe maintenance)
- **mutate_config:** (operator-only; no agent has this authority)

Signal monitors are all `observe_only`, intentionally constrained.

---

**Document version:** 2026-05-26  
**Last verified:** 2026-05-26 (signal-monitor inspection clean)  
**Next review:** Upon any signal-monitor proposal or capability request

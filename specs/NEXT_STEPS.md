# Next Steps — Model Improvement Roadmap

**As of**: 2026-03-11
**Current system**: v1.11.0, decision engine v1.3.0, live shadow portfolio, trade decision engine with binding caps

---

## Priority 1: Regime Awareness Overlay (fastest alpha / drawdown win)

The model is regime-blind. A simple overlay improves hedged P&L and reduces tail pain without new data sources.

**What to do (minimal, testable):**

- Define a regime state using only what we already compute:
  - XBI trend / drawdown / vol proxy (XBI series already available)
  - Trailing 4w hedged excess from `live_shadow/performance.csv`
- Add a policy-only adjustment (no ranking changes):
  - If trailing 4w hedged excess < -X OR XBI drawdown worse than Y: reduce gross / tighten caps / shift bucket targets
  - If trend is strong: allow full bucket targets

**Why now**: shows up in weekly compounded results quickly, and it's reversible.

---

## Priority 2: Catalyst Date Slip Tracking (biggest signal quality lever)

Wrong dates poison bucket assignment, gap-risk rails, regulatory ladder, and calendar alpha.

**What to do:**

- Track expected vs realized for regulatory events (PDUFA/AdCom):
  - `expected_date` at time of disclosure (`as_of_disclosed_at`)
  - Realized: did it occur / shift / get delayed?
- Emit a weekly "calendar accuracy" table:
  - # events due in next 45d
  - # slipped, median slip days
  - Biggest offenders (tickers, event_type)

**Then use it to:**

- Downweight "noisy" sources (ANALYST_ESTIMATE already proven harmful)
- Tighten quality selection thresholds based on observed slip

Pure "reduce noise" — compounds into better bucket behavior.

---

## Priority 3: Conviction-Weighted Sizing (only after proving top-of-book is better)

**Pre-requisite check:**

- In weekly live-sim, does the top quintile of ranks within each bucket beat the lower quintiles meaningfully and consistently?

**If yes:**

- Add a convex sizing curve inside each bucket (e.g., softmax or rank^p)
- Keep hard caps + trade_decision rails

**If no:**

- Don't concentrate; it will just increase variance.

---

## Backlog: New Data Source Candidates

These are lower priority until regime overlay + calendar slip loop are in and measured:

- **Insider transaction timing**: potentially useful, but data quality + PIT correctness is hard; can become a timesink
- **Options IV/skew**: needs robust options history coverage and careful PIT
- **FDA advisory committee voting patterns**: interesting but complex and slow to build
- **Patent expiry proximity**: more relevant to large-cap pharma than catalyst sleeves

---

## Signal Research Status (archived, do not revisit)

- **Coinvest**: v1.9.0 REJECTED (look-ahead bias + PIT-correct signal hurts IC)
- **Alpha cohort tiebreak**: ARCHIVED (hurts IC at all weights)
- **Clinical sort**: OFF in v1.8.2 (displacement effect)

Active signals:
- **Calendar alpha v2**: w=0.3 (active)
- **Institutional delta**: sort OFF, weight=0.3 (active)

---

## Infrastructure Already in Place

- Weekly IC packet with model vs realized + attribution + gates
- Trade decision engine (TRADE / TRADE_WITH_CAPS / NO_TRADE) with binding caps
- Forward-eval gate (rolling Spearman IC, WARN-only)
- Ruleset health monitor (drift vs promotion baseline)
- Acceptance replay (PIT-safe A/B of candidate vs active ruleset)
- PnL attribution + internal consistency scorecard

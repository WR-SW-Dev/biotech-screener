# Spec 098 — Catalyst Timing Shadow Monitor

**Status**: SPEC ONLY (shadow monitoring, no promotion)  
**Date**: 2026-05-13  
**Priority**: 6 (deferred pending catalyst hygiene stability)  
**Investment**: ~4–5 hours (signal extraction + postmortem join + dashboard)

---

## Problem Statement

Catalyst timing (days to catalyst, catalyst decay, catalyst quality buckets) is a **promising ranking candidate**, but it carries execution risk:

1. Catalyst hygiene fixes (Spec 071/078) are recent (2026-05-06); need stability proof
2. Timing is highly correlated with event EV, creating orthogonality risk vs coinvest
3. No prospective evidence yet; backfill cannot create valid labels

Spec 098 establishes shadow monitoring to track catalyst timing signal without promoting it. Promotion eligible only after:
- Catalyst hygiene stable (no false-catalyst rate spikes, ≥2 weeks post-fix)
- ≥30 post-PIT postmortems with forward returns available
- Orthogonality vs coinvest confirmed (via Spec 098 section 4 pre-check)

---

## Investment Logic

- Catalyst timing is thesis-aligned (timing matters in biotech)
- Requires prospective evidence to be valid
- Shadow monitoring validates stability without production risk
- Output: ready for promotion decision once catalyst hygiene stabilizes + orthogonality pre-check passes

---

## Exact Evidence Needed

### 1. Catalyst Timing Signal Definition

Document:
- `catalyst_days`: days from as_of_date to nearest expected catalyst event
- `catalyst_decay_w`: weight decay / relevance as catalyst date recedes
- `binary_quality_score`: 1 if near-term (≤30d) catalyst is high-quality, 0 otherwise
- `catalyst_quality_buckets`: near / mid / far / missing (from phase2_health.json)

### 2. Shadow Extraction

For each post-PIT snapshot (2026-04-19+):
- Extract catalyst_days, catalyst_decay_w, binary_quality from rankings.csv or snapshot metadata
- Join to postmortem observations by (ticker, as_of_date)
- Compute correlation with forward_5d, forward_20d, max_drawdown_20d

### 3. Stability Validation

Post-catalyst-hygiene-fix (2026-05-06+), confirm:
- False catalyst count (BPIQ/IR validation failures) remains low (<5% of portfolio)
- Catalyst date precision (days to catalyst) is accurate (spot-check vs IR/Bellringer data)
- No sudden catalyst date changes (sudden resets would indicate data freshness issues)

### 4. Orthogonality Pre-Check

Compute correlation of catalyst_days with:
- coinvest_score_z
- event_ev_p_hit (if available)
- clinical_design_quality (shadow signal)

If corr(catalyst_days, coinvest_score_z) > 0.6, flag orthogonality risk.

### 5. Postmortem Join

Join shadow catalyst metrics to postmortem observations:
- Compute hit rate (% forward_5d >= 0) stratified by catalyst_quality_bucket
- Compute median forward_5d return by catalyst_days bucket (<7d, 7-15d, 15-30d, >30d)
- Document sample size per bucket (must be ≥5 for meaningful stats)

---

## Data Constraints

- PIT-safe snapshots only (2026-04-20+)
- Post-catalyst-hygiene-fix dates only (2026-05-06+, Spec 071/078 closed)
- Use existing postmortem observations; no new data collection
- No backfill of historical catalyst dates (use as-of snapshot only)

---

## Out-of-Scope

- ❌ Promote catalyst timing to ranker
- ❌ Retrain selector or ranker
- ❌ Change catalyst date collection logic
- ❌ Backfill historical catalyst timing

---

## Tests / Analysis Commands

```bash
# Extract catalyst timing from recent snapshot
python3 << 'EOF'
import pandas as pd

snap = pd.read_csv('data/snapshots/2026-05-13/rankings.csv')
catalyst_cols = [c for c in snap.columns if 'catalyst' in c.lower()]
print("Catalyst columns:", catalyst_cols)
print("\nSample (first 5 rows):")
print(snap[['ticker'] + catalyst_cols].head())

# Check false catalyst rate
if 'catalyst_false_flag' in snap.columns:
    false_rate = snap['catalyst_false_flag'].sum() / len(snap)
    print(f"\nFalse catalyst rate: {false_rate*100:.1f}%")
EOF

# Join catalyst data to postmortem
python3 << 'EOF'
import pandas as pd

snap = pd.read_csv('data/snapshots/2026-05-13/rankings.csv')
pm = pd.read_csv('artifacts/postmortem/postmortem_observations.csv')

# Merge on ticker (assume each postmortem has unique snapshot date)
merged = pm.merge(
    snap[['ticker', 'catalyst_days', 'catalyst_decay_w']],
    on='ticker',
    how='left'
)
print(f"Merged rows: {len(merged)}")
print(f"Catalyst data coverage: {merged['catalyst_days'].notna().sum() / len(merged) * 100:.1f}%")

# Correlation with forward returns
if 'forward_5d' in merged.columns:
    corr = merged[['catalyst_days', 'forward_5d']].corr()
    print(f"\nCorr(catalyst_days, forward_5d): {corr.iloc[0, 1]:.3f}")
EOF

# Check catalyst date stability (sample 10 tickers, watch for date changes)
python3 << 'EOF'
import pandas as pd
from pathlib import Path

snapshots = sorted(Path('data/snapshots').glob('2026-05-*'))[-5:]
sample_tickers = ['RVMD', 'AXSM', 'FATE', 'REPL', 'XENE']

for ticker in sample_tickers:
    dates = []
    for snap in snapshots:
        csv = snap / 'rankings.csv'
        if csv.exists():
            df = pd.read_csv(csv)
            row = df[df['ticker'] == ticker]
            if not row.empty and 'catalyst_days' in row.columns:
                dates.append(f"{snap.name}: {row['catalyst_days'].values[0]}")
    if dates:
        print(f"{ticker}: {', '.join(dates)}")
EOF
```

---

## Pass/Fail Criteria

**PASS:**
- ✅ Catalyst timing signals extracted (catalyst_days, catalyst_decay_w, binary_quality)
- ✅ Stability validated (false catalyst rate <5%, catalyst dates consistent)
- ✅ Orthogonality pre-check done (correlation with coinvest_score_z documented)
- ✅ Postmortem joins computed (hit rates by catalyst_quality_bucket)
- ✅ Sample size per bucket documented (at least 3 buckets with ≥5 samples)

**FAIL:**
- ❌ Catalyst data inconsistent or missing
- ❌ False catalyst rate high (>10%); catalyst hygiene not stable
- ❌ Catalyst dates change unexpectedly between snapshots (data freshness issue)
- ❌ Orthogonality risk (corr > 0.6 with coinvest_score_z)

---

## Promotion Blockers (Must Clear Before Spec 099)

1. ✅ Catalyst hygiene stable (Spec 071/078 closed 2026-05-06; need ≥2 weeks stability = ~2026-05-20)
2. ✅ ≥30 post-PIT postmortems with forward returns (~2026-07-01)
3. ✅ Orthogonality vs coinvest confirmed (corr < 0.4)
4. ✅ Orthogonality vs event_ev confirmed (if event_ev_p_hit available)

---

## Expected Timeline

- **2026-05-13**: Establish baseline shadow metrics
- **2026-05-20**: Validate catalyst hygiene stability (2 weeks post-fix)
- **2026-06-13**: Re-check stability + accumulate postmortems
- **~2026-07**: Sufficient postmortems for Spec 099 (orthogonality audit)
- **~2026-08**: Ready for promotion if orthogonality and returns evidence both positive

---

## Rollback / No-Op Statement

Shadow monitoring only. No production changes. If catalyst dates become unstable or orthogonality fails, continue monitoring but defer promotion indefinitely. No-op outcome: catalyst timing joins the list of shadow-only signals until evidence threshold is reached.

---

## Related Specs

- **Depends on:** Specs 071/078 (catalyst hygiene must be fixed and stable)
- **Unblocks:** Spec 099 (orthogonality audit, after stability + postmortem threshold)

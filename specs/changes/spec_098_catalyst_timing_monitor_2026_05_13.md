# Spec 098 — Catalyst Timing Prospective Monitor

**Status**: SPEC ONLY (governance shadow-monitoring, no code changes)  
**Date**: 2026-05-13  
**Priority**: 2 (validation of catalyst timing signal for possible ranker weighting)  
**Investment**: ~2–3 hours (aggregation dashboard, forward-test harness, verdict gate)

---

## Problem Statement

Post-Spec 071/078 catalyst hygiene fixes (committed 2026-04-06 and 2026-05-06), the catalyst signal has been cleaned to exclude stale/duplicate/misdated events. However, **ranker catalyst weighting requires return validation**:

- **Current state**: Catalyst events are collected and deduplicated; top-30 portfolio is partially shadowed for catalyst timing value
- **Unknown**: Whether near-term catalysts (within N days of portfolio selection) correlate with positive forward returns
- **Risk**: Catalyst as ranker weight may introduce alpha leakage (e.g., correlation with institutional conviction, clinical probability, or pure noise)
- **Hypothesis**: Portfolios with more catalyst-dense exposure outperform non-catalyst-driven selections by forward T+5/T+20 metrics

**Consequence**: Cannot yet rank-weight by catalyst timing or score. Can shadow-monitor and accumulate forward-return evidence.

---

## Investment Logic

- Catalyst timing is intuitive (near-term binary events drive volatility / convexity)
- Post-hygiene-fix, tool output is reliable (Spec 071/078 audit confirmed deduplication correctness)
- Forward-return validation is fast-path: catalyst outcomes resolve alongside forward returns (T+5, T+20)
- High-priority for portfolio signal diversification: if catalyst timing matters, unlocks non-clinical alpha path

---

## Exact Evidence & Analysis Needed

### 1. Define Catalyst Timing Metrics

For each post-PIT snapshot:

**Portfolio-level catalyst intensity**:
- `catalyst_days_to_nearest`: Days from snapshot_date to nearest upcoming catalyst event (min across top-30 portfolio)
- `catalyst_days_to_median`: Median days-to-catalyst across top-30 names
- `catalyst_hit_rate_30d`: Fraction of top-30 with ≥1 catalyst event within next 30 days
- `catalyst_hit_rate_60d`: Fraction of top-30 with ≥1 catalyst event within next 60 days

**Catalyst tiers** (to test if magnitude matters):
- Tier A: PDUFA/BLA/Marketing-Approval (binary, high-information)
- Tier B: Phase trial results (clinical outcomes)
- Tier C: Management/financing events (lower-information proxy)

**Test hypothesis**: Top-30 with higher catalyst_hit_rate_30d correlates with better T+5/T+20 forward returns

### 2. Forward-Return Aggregation

**Input**: Postmortem records with:
- portfolio_exposure (top-30 on snapshot_date)
- forward_5d_return, forward_20d_return, forward_5d_hit (outcome-binarized at 0% threshold)
- catalyst events linked via Spec 071/078 deduplicated data

**Aggregation**:
- Group postmortems by snapshot_date (each snapshot = one "experiment")
- Compute per-snapshot:
  - mean catalyst_days_to_nearest across top-30
  - mean catalyst_hit_rate_30d across top-30
  - mean forward_5d_return across top-30 (portfolio return)
  - mean forward_20d_return across top-30
  - hit_rate (pct with forward_5d_return > 0)

**Time-series**: Per-snapshot correlation matrix
- correlation(catalyst_hit_rate_30d, forward_5d_return)
- correlation(catalyst_days_to_nearest, forward_5d_return) — expect negative (sooner = better?)
- correlation(catalyst_hit_rate_60d, forward_20d_return)

### 3. Stratification Tests

**By catalyst tier**:
- Subset top-30 to Tier-A-only, Tier-B-only, Tier-C-only
- Compute forward returns for each subset
- Test: do Tier-A catalysts outperform Tier-B/C?

**By days-to-event**:
- Bucket catalysts into [0–7], [7–14], [14–30], [30–60], [60+] days
- Per-bucket: mean forward returns
- Test: is there a convexity peak (e.g., 7–14 days sweet spot)?

**Portfolio composition**:
- Compare: top-30 selected by selector-only (no catalyst weighting) vs top-30 selected by ranker (implicit catalyst-aware via financial_score / coinvest interaction)
- Test: does ranker portfolio have higher catalyst density? If so, does that explain return difference (Spec 094)?

### 4. Data Sources

**Catalyst events**: `common/catalyst_tier_definitions.py`, `data/snapshots/{snapshot_date}/catalyst_events.json` (post-Spec 071/078)

**Postmortem outcomes**: `data/postmortems/{snapshot_date}/postmortem_*.json` (forward_5d_return, forward_20d_return, resolved_outcome)

**Portfolio membership**: `data/snapshots/{snapshot_date}/rankings.csv` (actionable_rank, top-30 definition)

**Baseline comparison**: Selector-only top-30 computed from `selector_score` column (no ranker adjustment)

---

## Validation Checklist

Before promotion decision (post-accumulation, ~2026-06-15):

- ✅ Forward-return correlation computed for ≥20 post-PIT snapshots
- ✅ Time-series correlation: catalyst_hit_rate_30d vs forward_5d_return (computed; direction & magnitude noted)
- ✅ Stratification tests: Tier A vs Tier B/C returns (computed; ANOVA p-value <0.05 preferred)
- ✅ Catalyst days-to-event: bucket-wise forward return analysis (convexity check)
- ✅ Portfolio composition: ranker catalyst density > selector-only? (expected: yes, per stress-upside design)
- ✅ Return attribution: ranker outperformance vs selector-only explainable by catalyst loading? (test via partial regression)
- ✅ Spec 071/078 hygiene confirmed: no stale/duplicate events in sample postmortems (spot-check 20 records)

---

## Tests / Analysis Commands

```bash
# 1. Audit Spec 071/078 hygiene (spot-check deduplication)
python3 << 'EOF'
import json
import glob

postmortems = glob.glob("data/postmortems/**/postmortem_*.json", recursive=True)[:20]
for p in postmortems:
    pm = json.load(open(p))
    ticker = pm.get("ticker")
    events = pm.get("catalyst_events", [])
    if len(events) > 0:
        print(f"{ticker}: {len(events)} events")
        for e in events[:3]:
            print(f"  {e.get('catalyst_type')} @ {e.get('expected_date')}")
EOF

# 2. Compute portfolio-level catalyst metrics
python3 << 'EOF'
import json
import pandas as pd
from datetime import datetime
import glob

results = []
for snapshot_dir in sorted(glob.glob("data/snapshots/2026-*/"))[:30]:  # Last 30 snapshots
    snap_date = snapshot_dir.split("/")[-2]
    
    try:
        # Load rankings (top-30 definition)
        rankings = pd.read_csv(f"{snapshot_dir}/rankings.csv")
        top30 = rankings[rankings['actionable_rank'] <= 30]
        
        # Load catalyst events
        catalysts_file = f"{snapshot_dir}/catalyst_events.json"
        if os.path.exists(catalysts_file):
            catalysts = json.load(open(catalysts_file))
            
            # Compute metrics
            days_to_events = []
            for ticker in top30['ticker']:
                if ticker in catalysts:
                    ticker_events = catalysts[ticker]
                    dates = [datetime.fromisoformat(e.get('expected_date')).date() 
                             for e in ticker_events if e.get('expected_date')]
                    snapshot_date = datetime.fromisoformat(snap_date).date()
                    future_dates = [d for d in dates if d > snapshot_date]
                    if future_dates:
                        days = min([(d - snapshot_date).days for d in future_dates])
                        days_to_events.append(days)
            
            hit_rate_30d = sum(1 for d in days_to_events if d <= 30) / len(top30) if days_to_events else 0
            median_days = sorted(days_to_events)[len(days_to_events)//2] if days_to_events else None
            
            results.append({
                'snapshot_date': snap_date,
                'catalyst_hit_rate_30d': hit_rate_30d,
                'catalyst_median_days': median_days,
                'top30_size': len(top30),
            })
    except Exception as e:
        print(f"Skipped {snap_date}: {e}")

df = pd.DataFrame(results)
print(df.describe())
EOF

# 3. Compute forward-return correlations
python3 << 'EOF'
import json
import pandas as pd
import numpy as np
from scipy.stats import spearmanr
import glob

# Aggregate postmortems by snapshot_date
snapshots = {}
for pm_file in glob.glob("data/postmortems/**/postmortem_*.json", recursive=True):
    pm = json.load(open(pm_file))
    snap_date = pm.get('snapshot_date')
    if snap_date not in snapshots:
        snapshots[snap_date] = []
    snapshots[snap_date].append(pm)

# Compute per-snapshot correlations
corrs = []
for snap_date in sorted(snapshots.keys()):
    records = snapshots[snap_date]
    if len(records) < 5:  # Skip small snapshots
        continue
    
    catalyst_intensity = [len(r.get('catalyst_events', [])) for r in records]
    forward_5d = [r.get('forward_5d_return', np.nan) for r in records]
    
    # Filter out NaNs
    valid = [(c, f) for c, f in zip(catalyst_intensity, forward_5d) if not np.isnan(f)]
    if len(valid) >= 3:
        cats, fwds = zip(*valid)
        rho, pval = spearmanr(cats, fwds)
        corrs.append({
            'snapshot_date': snap_date,
            'correlation': rho,
            'p_value': pval,
            'n': len(valid),
        })

df = pd.DataFrame(corrs)
print(f"Mean correlation (catalyst count vs forward 5d): {df['correlation'].mean():.3f}")
print(f"Significant (p<0.05): {(df['p_value'] < 0.05).sum()} / {len(df)}")
print(df[['snapshot_date', 'correlation', 'p_value', 'n']].tail(10))
EOF

# 4. Tier-wise return comparison
python3 << 'EOF'
import json
import pandas as pd
import numpy as np
import glob

tier_returns = {'A': [], 'B': [], 'C': []}
for pm_file in glob.glob("data/postmortems/**/postmortem_*.json", recursive=True):
    pm = json.load(open(pm_file))
    fwd_5d = pm.get('forward_5d_return')
    if fwd_5d is None or np.isnan(fwd_5d):
        continue
    
    events = pm.get('catalyst_events', [])
    for event in events:
        tier = event.get('catalyst_tier', 'C')  # Default to C
        if tier in tier_returns:
            tier_returns[tier].append(fwd_5d)

print("Tier A (PDUFA/BLA/Approval):")
print(f"  n={len(tier_returns['A'])}, median={np.median(tier_returns['A']):.2%}, mean={np.mean(tier_returns['A']):.2%}")
print("Tier B (Phase results):")
print(f"  n={len(tier_returns['B'])}, median={np.median(tier_returns['B']):.2%}, mean={np.mean(tier_returns['B']):.2%}")
print("Tier C (Management/Financing):")
print(f"  n={len(tier_returns['C'])}, median={np.median(tier_returns['C']):.2%}, mean={np.mean(tier_returns['C']):.2%}")
EOF
```

---

## Pass/Fail Criteria

**PASS** (catalyst timing emerges as ranker signal):
- ✅ Correlation(catalyst_hit_rate_30d, forward_5d_return) > 0.15 across ≥20 snapshots (positive trend)
- ✅ Tier-A vs Tier-C forward returns show >2pp median difference (ANOVA p < 0.05)
- ✅ Days-to-catalyst: clear convexity (e.g., 7–14d bucket outperforms 30–60d)
- ✅ Ranker portfolio has higher catalyst_hit_rate_30d than selector-only (confirms stress-upside operational logic)
- ✅ Post-hoc return attribution: catalyst loading explains ≥30% of ranker vs selector-only return differential

**MONITOR** (inconclusive, continue shadowing):
- ⚠️ Correlation weak (|0.05| < rho < |0.15|)
- ⚠️ Tier differences small (<1pp median difference)
- ⚠️ No clear days-to-catalyst convexity pattern
- ⚠️ Catalyst metrics explain <30% of ranker outperformance

**FAIL** (catalyst timing does not emerge as signal):
- ❌ Negative correlation(catalyst_hit_rate_30d, forward_5d_return) < -0.10 (catalyst overweight hurts)
- ❌ Tier-A < Tier-C forward returns (reverse ordering)
- ❌ Ranker catalyst_hit_rate_30d < selector-only (catalyst loading is accidental, not intentional)
- ❌ >30% of catalyst events found to be stale/duplicate (Spec 071/078 hygiene failure)

---

## Expected Outcome

After Spec 098 implementation:

1. **Daily catalyst-timing metrics**: Auto-computed per snapshot (catalyst density, days-to-nearest)
2. **Shadow-return aggregation**: Postmortems linked to catalyst intensity; correlation time-series computed weekly
3. **Promotion clarity**: If correlation > 0.15 + Tier-A outperforms + ranker catalyst load is intentional, catalyst timing becomes ranker-weighting candidate (contingent on Spec 099 orthogonality)
4. **No-promotion path**: If correlation < 0.05 or negative, catalyst signal remains monitor-only (no ranker weighting); may indicate leakage to institutional/clinical signal

---

## Data Constraints

- Catalyst deduplication: Spec 071/078 fixes presumed correct (no backfill; forward-only)
- Limited postmortem coverage: ~0.5–0.8 postmortems/day; slow accumulation of forward-return evidence
- T+5/T+20 outcome delay: Events from 2026-04-20+ will have resolved returns by 2026-05-25 / 2026-06-09
- Catalyst-outcome linkage: Must join postmortem + catalyst_events on ticker + date windows; spot-check for false positives

---

## Out-of-Scope

- ❌ Retrain or change catalyst event collection (Spec 071/078 done; deduplication logic frozen)
- ❌ Promote catalyst to selector (catalyst is ranker-only candidate, not selector feature)
- ❌ Rank-weight by catalyst type hierarchy until Tier-wise returns are validated
- ❌ Change financial_score or coinvest_score (they implicitly correlate with catalyst intensity; isolate catalyst signal via stratification, not model changes)
- ❌ Backtest pre-Spec-071/078 catalyst claims (hygiene fixes invalidate historical claims; forward-only)

---

## Timeline

- **2026-05-13**: Spec created
- **2026-05-27**: Collect ≥20 post-PIT snapshots; compute preliminary correlation + tier-wise returns
- **2026-06-03**: Audit postmortem coverage (expect ≥30 outcomes with catalyst events)
- **2026-06-15**: Verdict decision gate (if all correlation + tier conditions pass, promote to Checklist v2 review)
- **2026-07-01**: Final calibration (if decision deferred, re-check with expanded sample)

---

## Rollback / No-Op Statement

Spec is pure monitoring infrastructure (no scoring changes, no model updates). If deferred, manual tracking remains: weekly aggregation of postmortems + catalyst_events + forward returns. If catalyst signal is weak, mark as "requires investigation" and keep ranker formula unchanged.

---

## Related Specs

- **Depends on**: Spec 071 (catalyst event deduplication audit), Spec 078 (catalyst hygiene implementation)
- **Blocks**: Ranker catalyst-weighting (any ranking adjustments conditional on signal validation)
- **Related to**: Spec 099 (clinical orthogonality; must ensure catalyst is independent of clinical/coinvest loading)

---

## Priority Note

**MEDIUM**: Catalyst timing is intuitive and post-hygiene data is clean. Validation timeline is predictable (~4 weeks to verdict). If signal is strong, unlocks diverse ranker alpha path (non-clinical, non-institutional). Monitor weekly for correlation trends; promote to Checklist v2 review if > 0.15 correlation + Tier-A outperformance confirmed.

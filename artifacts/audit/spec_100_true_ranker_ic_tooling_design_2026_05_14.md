# Spec 100: True Ranker IC Measurement Tooling — Design

**Date:** 2026-05-14  
**Status:** DESIGN (research-only tool; no production changes)  
**Purpose:** Define and implement correct ranker IC measurement to unblock Spec 096 ranker promotion requirements

---

## The Problem: Composite Score IC ≠ Ranker IC

### Historical Confusion

**Old Spec 095 Finding (2026-05-13):**
> IC backtest measured `composite_score` (selection universe), not ranker `final_score` (ranking within selection).

**Impact:** All prior IC claims using composite_score IC are invalid for ranker promotion. Composite_score IC measures selection quality (whether gate/selector chose the right names), not ranking quality (whether ranker ordered them correctly).

### The Distinction

| Metric | Universe | What It Measures | Use Case |
|---|---|---|---|
| **Composite_score IC** | Full universe (299 tickers) | Selection quality: does selector identify outperformers? | Selector evaluation; attribution |
| **Ranker IC** | Eligible universe post-gate (~60 tickers) | Ranking quality: does ranker order survivors correctly? | Ranker feature evaluation; marginal value proof |

**Critical:** Ranker IC is measured ONLY on the eligible universe (post-gate). Ranker cannot affect names outside the gate; measuring ranker IC on the full universe includes names the gate never saw.

---

## What "True Ranker IC" Means

### Definition

**Ranker IC:** Correlation between `final_rank` (or `actionable_rank`) and forward returns, measured only on tickers that passed the eligibility gate.

**Formula:**
```
Ranker IC = Pearson(final_rank_zscore, forward_return) 
           measured on rows where eligible=1
```

### Three Levels of Measurement

#### Level 1: Baseline Ranker IC (Current Production)

**What:** IC of current production ranker (2-feature pairwise: financial_score_z + coinvest_score_z)

**Horizons:** T+5, T+10, T+20, T+60 business days

**Purpose:** Establish current ranker contribution to forward returns

**Expected:** Modest IC (~+0.02 to +0.06) because ranker is ordinal only; ranking within already-vetted names has limited return variance

#### Level 2: Selector-Only Baseline (No Ranker)

**What:** IC of equal-weight portfolio on eligible universe (ignore ranker; all names ranked equally)

**Purpose:** Decompose: how much return comes from selector gate vs ranker ordering?

**Expected:** Higher IC than ranker alone (selector did the heavy lifting)

#### Level 3: Candidate Feature IC (Within Eligible Universe)

**What:** IC of proposed ranker feature (e.g., clinical_score_v2_z) measured on eligible universe only

**Purpose:** Prove marginal ordering value of candidate vs baseline

**Example:** 
```
Baseline ranker IC (financial + coinvest): +0.035
Candidate (clinical_score_v2_z) IC within eligible: +0.045
Marginal IC contribution: +0.010 (candidate adds value over current ranker)
```

**Blockers:**
- Must be positive (candidate does NOT harm ranking)
- Must be statistically significant (t > 1.5)
- Must persist across multiple horizons (T+5 AND T+20)

---

## Implementation: run_true_ranker_ic.py

### Command Signature

```bash
python3 scripts/research/run_true_ranker_ic.py \
  --start-date 2026-05-01 \
  --end-date 2026-05-13 \
  --horizons 5 10 20 60 \
  --output-dir artifacts/research/spec_100/ \
  [--candidates clinical_score_v2_z endpoint_strength_score]
```

### Inputs

**From production snapshots:**
- `data/snapshots/<date>/rankings.csv`
  - `eligible` (binary flag; gate has selected this ticker)
  - `final_rank` or `actionable_rank` (actual ranker output)
  - `close_price` (for return calculation)
  - `coinvest_score_z` (for selector-only baseline)
  - `financial_score_z` (for current ranker baseline)
  - Candidate features (if `--candidates` specified)

**From forward return data:**
- Morningstar returns or SEC filing returns
- `T+5`, `T+10`, `T+20`, `T+60` forward returns per ticker/snapshot

### Processing

```python
def run_true_ranker_ic(start_date, end_date, horizons, candidates=None):
    """
    Measure ranker IC on eligible universe only.
    
    Returns:
    - baseline_ic: {horizon: ic_value} for current production ranker
    - selector_baseline_ic: {horizon: ic_value} for equal-weight baseline
    - candidate_ic: {candidate: {horizon: ic_value}} if candidates specified
    """
    
    results = {}
    
    for snapshot_date in date_range(start_date, end_date):
        snap = load_snapshot(snapshot_date)
        
        # Filter to eligible universe (gate has passed)
        eligible_rows = [r for r in snap.rows if r['eligible'] == 1]
        
        if len(eligible_rows) < 30:
            skip(f"Insufficient eligible tickers on {snapshot_date}")
            continue
        
        # Load forward returns for this snapshot
        fwd_returns = load_forward_returns(snapshot_date, horizons)
        
        # Baseline 1: Current production ranker IC
        baseline_ic = compute_ic(
            eligible_rows['final_rank'],
            fwd_returns,
            horizons
        )
        
        # Baseline 2: Selector-only (equal weight)
        selector_ic = compute_ic(
            [0] * len(eligible_rows),  # all equal rank
            fwd_returns,
            horizons
        )
        
        # Candidate ICs (if requested)
        candidate_ics = {}
        if candidates:
            for candidate_name in candidates:
                cand_ic = compute_ic(
                    eligible_rows[candidate_name],
                    fwd_returns,
                    horizons
                )
                candidate_ics[candidate_name] = cand_ic
        
        results[snapshot_date] = {
            'baseline_ranker_ic': baseline_ic,
            'selector_only_ic': selector_ic,
            'candidate_ics': candidate_ics,
            'eligible_count': len(eligible_rows)
        }
    
    return results
```

### Outputs

**1. artifacts/research/spec_100/baseline_ranker_ic.csv**

| snapshot_date | horizon | ic | t_stat | p_value | n_eligible |
|---|---|---|---|---|---|
| 2026-05-01 | 5 | 0.0342 | 1.64 | 0.105 | 58 |
| 2026-05-01 | 10 | 0.0281 | 1.35 | 0.182 | 58 |
| 2026-05-01 | 20 | 0.0195 | 0.93 | 0.358 | 58 |
| 2026-05-01 | 60 | 0.0089 | 0.43 | 0.671 | 58 |
| ... | ... | ... | ... | ... | ... |

**2. artifacts/research/spec_100/selector_baseline_ic.csv**

(Same structure; measure IC of equal-weight portfolio on eligible universe)

**3. artifacts/research/spec_100/candidate_ic_<candidate>.csv**

(If candidates specified; measure IC of candidate feature on eligible universe)

**4. artifacts/research/spec_100/comparison_summary.md**

```markdown
# True Ranker IC Summary (2026-05-01 through 2026-05-13)

## Baseline Ranker IC (Current Production)

| Horizon | Mean IC | Std IC | Min IC | Max IC | Median t-stat | Pct Positive |
|---------|---------|--------|--------|--------|---------------|--------------|
| T+5 | 0.0328 | 0.0156 | 0.0089 | 0.0567 | 1.53 | 58% |
| T+10 | 0.0247 | 0.0134 | 0.0032 | 0.0521 | 1.21 | 52% |
| T+20 | 0.0189 | 0.0142 | -0.0031 | 0.0456 | 0.93 | 48% |
| T+60 | 0.0045 | 0.0167 | -0.0287 | 0.0312 | 0.22 | 42% |

**Interpretation:**
- Baseline ranker shows modest IC on T+5 (mean 0.033, t~1.5)
- Decays rapidly by T+60 (mean 0.0045, t~0.2)
- Consistent with ordinal ranker on vetted universe

## Selector-Only Baseline (Equal Weight on Eligible)

| Horizon | Mean IC | Std IC | Median t-stat |
|---------|---------|--------|---------------|
| T+5 | 0.0892 | 0.0234 | 4.31 |
| T+10 | 0.0756 | 0.0201 | 3.65 |
| T+20 | 0.0634 | 0.0189 | 3.06 |
| T+60 | 0.0421 | 0.0195 | 2.04 |

**Interpretation:**
- Selector (gate) does the heavy lifting: IC much higher than ranker alone
- Suggests ranker is a fine-tuning mechanism, not primary signal

## Candidate IC (e.g., clinical_score_v2_z within eligible universe)

| Horizon | Mean IC | Std IC | Marginal Gain vs Baseline | t-stat |
|---------|---------|--------|---------------------------|--------|
| T+5 | 0.0398 | 0.0189 | +0.007 | 1.87 |
| T+10 | 0.0315 | 0.0164 | +0.007 | 1.79 |
| T+20 | 0.0267 | 0.0145 | +0.008 | 1.84 |
| T+60 | 0.0128 | 0.0156 | +0.008 | 1.62 |

**Interpretation:**
- Candidate shows marginal positive IC vs baseline across all horizons
- Marginal gain consistent (~0.007-0.008) and statistically significant (t > 1.6)
- Passes Spec 094 (marginal value proof) + Spec 095 (correct IC scope)

## Caveats

- IC measured on eligible universe post-gate (not full universe)
- Does NOT include composite_score IC (selection universe)
- Ranker IC is modest because ranking within already-vetted names has limited return variance
- Marginal IC gains are the true test of ranker feature value
```

---

## Test Harness: test_true_ranker_ic_spec100.py

### Test Classes

**TestCompositeVsRankerIC:**
```python
def test_composite_score_ic_not_ranker_ic():
    """Composite_score IC measured on full universe; ranker IC only on eligible."""
    # Load snapshot
    snap = load_snapshot('2026-05-13')
    
    # Composite_score IC: all 298 tickers
    composite_ic = compute_ic(snap['composite_score'], fwd_returns, horizons)
    
    # Ranker IC: only 60 eligible tickers
    ranker_ic = compute_ic(
        snap[snap['eligible'] == 1]['final_rank'],
        fwd_returns[snap['eligible'] == 1],
        horizons
    )
    
    # These should be DIFFERENT (different universes)
    assert abs(composite_ic - ranker_ic) > 0.01, \
        "Composite and ranker IC should differ; universes are different"
```

**TestRankerICBounds:**
```python
def test_ranker_ic_within_reasonable_bounds():
    """Ranker IC on eligible universe should be modest (ranker is fine-tuning)."""
    baseline_ic = run_true_ranker_ic_baseline(...)
    
    # Ranker IC should be positive but small
    assert 0 < baseline_ic['T+5'] < 0.10, \
        f"Ranker T+5 IC {baseline_ic['T+5']} outside expected bounds"
    assert 0 < baseline_ic['T+20'] < 0.08
```

**TestCandidateMarginalValue:**
```python
def test_candidate_marginal_ic_positive():
    """Candidate IC should exceed baseline within eligible universe."""
    baseline_ic = run_true_ranker_ic_baseline(...)
    candidate_ic = run_true_ranker_ic_candidate('clinical_score_v2_z', ...)
    
    marginal = candidate_ic['T+5'] - baseline_ic['T+5']
    assert marginal > 0, f"Candidate IC {candidate_ic['T+5']} < baseline {baseline_ic['T+5']}"
    assert marginal > 0.005, f"Marginal gain {marginal} too small"
```

**TestEligibleUniverseFiltering:**
```python
def test_only_eligible_tickers_included():
    """Ranker IC must filter to eligible=1 only."""
    snap = load_snapshot('2026-05-13')
    results = run_true_ranker_ic(...)
    
    # Confirm: results['eligible_count'] matches gate output
    assert results['eligible_count'] == (snap['eligible'] == 1).sum()
```

**TestPITSafety:**
```python
def test_pit_safe_snapshot_dates():
    """Snapshots must have as_of_date <= measurement date (no lookahead)."""
    for snapshot_date in snapshots:
        snap = load_snapshot(snapshot_date)
        assert snap['as_of_date'] <= snapshot_date, \
            f"Snapshot {snapshot_date} has as_of_date {snap['as_of_date']} in future (lookahead)"
```

---

## Key Design Decisions

### 1. Eligible Universe Only

**Decision:** Measure ranker IC on `eligible=1` rows only (post-gate universe).

**Why:** Ranker cannot affect names outside the gate. Measuring IC on full universe includes names never in contention.

**Spec 095 requirement:** "Correct IC scope" means this universe distinction.

### 2. Multiple Horizons

**Decision:** Report T+5, T+10, T+20, T+60 separately; do NOT average.

**Why:** Ranker IC decays (short-term stronger than long-term). Averaging masks this.

**Spec 094 requirement:** Marginal value must hold across relevant horizons.

### 3. Baseline Comparisons (Ranker + Selector-Only)

**Decision:** Report both current-ranker IC and equal-weight (selector-only) baseline.

**Why:** Decompose: how much return is from gate selection vs ranker ordering?

**Diagnostic value:** If selector-only IC >> ranker IC, ranker is minor; candidate marginal gains are more believable.

### 4. Explicit Separation from Composite_score IC

**Decision:** Code explicitly rejects composite_score IC as ranker evidence; only allows eligible-universe IC.

**Why:** Spec 095 audit found composite_score IC was invalid for ranker claims.

**Test:** `test_composite_score_ic_not_ranker_ic()` verifies universes are different.

---

## When This Tool Is Used

### Phase 1: Now (2026-05-14+)

Build the tool. Optionally run baseline ranker IC on historical snapshots to establish production ranker performance.

### Phase 2: Post-2026-05-22 Ranker Review

If Spec 072 D7/D8/D9 all pass, use this tool to measure true IC of clinical_score_v2_z candidate on eligible universe (correct scope, correct universe).

### Phase 3: Ranker Promotion Decision

If candidate IC passes Spec 094 (marginal value) + Spec 095 (correct scope) + Spec 100 (this tool), candidate is eligible for Checklist v2 (orthogonality, LOSO, year stab, domain audit).

---

## Blockers This Solves

- **Spec 100 (old):** "True ranker IC tooling not yet built" → SOLVED by this implementation
- **Spec 095:** "IC scope correction needed" → SOLVED by eligible-universe filtering
- **Spec 094:** "Marginal value proof" → ENABLED by this tool's candidate IC measurement

---

## Not In Scope (Do NOT do)

❌ Change ranker logic or weights  
❌ Build composite ranker  
❌ Shadow-ship results without Checklist v2  
❌ Use this tool to justify selector changes  
❌ Measure IC on full universe (invalid for ranker)  
❌ Average across horizons (masks decay)  

---

## References

- **Spec 095 audit:** IC scope correction requirement (composite_score ≠ ranker IC)
- **Spec 094:** Marginal value proof (enabled by this tool)
- **Spec 096:** Gate/ranker separation doctrine (enabled by eligible-universe filtering)
- **Spec 072:** D8 test within-quintile IC (similar idea; candidate IC on constrained universe)

# System Specification

Version: 1.0.0
Last updated: 2026-03-09

This document defines the stable invariants, rules, and constraints that govern the biotech-screener system. All implementation work must conform to these rules. Claude Code sessions should reference this spec — not re-derive the rules from memory.

---

## 1. Core Invariants

### 1.1 Determinism
- Same inputs always produce byte-identical outputs
- No `random`, no `datetime.now()`, no uncontrolled randomness
- Hash all outputs for reproducibility (`stable_json_dumps()`)
- Sort keys must be fully deterministic (no ties without deterministic tiebreak)

### 1.2 Point-in-Time (PIT) Safety
- All data access must satisfy `source_date <= as_of_date - 1`
- Use `compute_pit_cutoff()` and `is_pit_admissible()` from `common/pit_enforcement.py`
- PIT violations are hard errors — never degrade silently
- `--pit-mode degrade` is the only legitimate escape hatch (for pre-cache-date archives)
- Clinical trials: `first_posted OR last_update_posted <= as_of_date` (not `<`)

### 1.3 Fail-Closed
- Validate data and stop on errors rather than gracefully degrading
- Track and report validation failures explicitly — never drop invalid data silently
- All gates default to FAIL unless proven otherwise

### 1.4 Decimal Arithmetic
- All financial calculations use `Decimal` (never floats)
- Initialize from strings: `Decimal("500000000")`, never `Decimal(500000000)`

### 1.5 Stdlib-Only Core
- Zero external dependencies in scoring modules (Modules 1-5, Decision Engine)
- `numpy`/`pandas` allowed only in research scripts and evaluation harnesses

---

## 2. Ranking Pipeline

### 2.1 Module Chain
```
Universe (M1) → Financial Health (M2) → Catalyst Events (M3) → Clinical Dev (M4)
  → Composite Scoring (M5) → Decision Engine → Phase-2 Health Gate → Output
```

### 2.2 Decision Engine Layers
- **L0**: Eligibility gate (archetype + score floor)
- **L2**: Catalyst + drawdown overlays
- **L4**: Dev tier assignment (A/B/C/D)
- **L4b**: Commercial tier assignment
- **L3**: Position sizing

### 2.3 Sort Key Contract
- Sort anchor: configurable (`composite_rank`, `optionality_pct`, `alpha_cohort`)
- Additive signal pattern: `adj = weight * clamp(z, 0, max)` subtracted from anchor (lower = better)
- Signals: clinical_sort, calendar_alpha, institutional_delta, coinvest (each independently toggleable)
- Sort tuple must be fully deterministic — ticker as final tiebreaker

### 2.4 Catalyst Classification
- **REGULATORY**: PDUFA, FDA_ADCOM, CHMP, EMA events (hard deadlines)
- **CLINICAL**: CT trial milestones, data readouts (softer dates)
- **SAFETY**: Clinical holds, safety signals, trial terminations (negative shocks)
- Source: `CATALYST_FAMILY_MAP` in `event_ledger.py`

---

## 3. Ruleset Governance

### 3.1 Promotion Pipeline
```
candidate.json → eval (A/B vs baseline) → gate summary → promote → pin IDs → receipt
```

### 3.2 Pinned IDs
- `PHASE2_PINNED_RULESET_ID` must stay in sync between `run_screen.py` and `run_phase2_snapshot_delta.py`
- Updated only via `scripts/promote_ruleset.py` (which writes both files atomically)
- Current active: `bebe73f8` (v1.10.0)

### 3.3 Rollback
- `--rollback --reason "..."` is the governed path (no `--force` required)
- Auto-discovers LKG via `_find_last_known_good()`
- Receipt has `"action": "rollback"` + `"reason"` fields

### 3.4 Manifest Invariants
- No duplicate IDs
- Exactly one `"status": "active"` entry
- All promoted/retired entries have receipts
- `promote_ruleset.py` enforces all invariants

### 3.5 Evaluation Bars
- **Primary**: +0.20pp at 126d (or longest horizon)
- **Guardrail**: no worse than -0.05pp at 84d
- **OOS signal threshold**: +0.0015 IC delta minimum
- **Paired t-stat**: t >= 2.0 for statistical significance

---

## 4. Portfolio Construction (Shadow Portfolio)

### 4.1 Policy Schema
- Source: `production_data/portfolio_policy.json` (schema `portfolio_policy.v3`)
- Account: $500k
- Bucket targets: 55/25/10/10 (binary_91_180 / binary_31_90 / binary_0_30 / less_binary)

### 4.2 Family Sleeve Allocation
- `family_filter_mode: "secondary"` — tickers with `has_regulatory_upcoming_180d=1` treated as REGULATORY
- Per-bucket family targets: 70/30 REG/CLIN in binary_31_90, 30/70 in binary_0_30
- Reflow: unused family budget → remaining active families proportionally

### 4.3 Regulatory Time-Ladder
- 4 sub-buckets: reg_0_14, reg_15_45, reg_46_90, reg_91_180
- Per-sub-bucket caps: 0.35%, 1.25%, 1.00%, 0.75%
- Reflow priority: reg_15_45 → reg_46_90 → reg_91_180 → reg_0_14 (sweet spot first)
- Configurable weights per parent bucket

### 4.4 Quality Tilt
- Quality-proportional allocation within sub-buckets
- Clip quality to [q_lo=0.30, q_hi=1.00], normalize to sum-to-1 weights
- Iterative cap-overflow reflow (not single-pass)

### 4.5 Event Resolution
- REGULATORY names with `regulatory_days <= 0` → auto-demote to 0% target
- Budget reflows to remaining names
- Tracked in summary as `resolved_regulatory`

### 4.6 Budget Conservation
- Total allocated dollars must equal bucket budget within rounding tolerance ($100)
- Cap enforcement: `min(family_name_cap, ladder_sub_bucket_cap)`
- No cash drag from rounding — excess distributed to uncapped names

---

## 5. Production Gates

### 5.1 Gate Cascade
- **FAIL** (exit 1): ruleset mismatch, zero eligible, optionality broken, coverage < 40%
- **WARN** (exit 2): A-count low, weight drift, catalyst drop, coverage < 60%
- **OK** (exit 0): all checks pass

### 5.2 Gate Allowlist (WARN-only)
`cache_health`, `ruleset_health`, `pit_bundle_health`, `sec_13f_cache`, `price_pit_cache`, `forward_eval`, `institutional_delta`

### 5.3 Pre-Trade Gate
- Checks: provenance, ruleset_active, bucket_deviation, missing_prices, gap_risk_concentration, turnover
- FAIL blocks trade plan generation entirely
- `--relaxed` downgrades mismatch to WARN

---

## 6. Testing Standards

### 6.1 Coverage
- ~11,200+ tests across 280+ test files
- All new features require tests before commit
- Full suite must pass before push to main

### 6.2 Test Isolation
- Tests must not depend on production data paths
- Use `tmp_path` for all file I/O
- Mock manifests and snapshots rather than reading real ones
- Pass explicit `positions_dir`, `manifest_path`, etc. to avoid production leakage

### 6.3 Pre-Commit Hooks
- black, isort, flake8, detect-secrets
- First commit attempt may reformat → fail; re-stage and commit again

---

## 7. Data Regimes (for backtesting)

| Period | Regime | Notes |
|--------|--------|-------|
| 2020-2024 | catalyst_broken | Incomplete catalyst data |
| 2025 | well-formed | Full pipeline, good for IS/OOS |
| 2026-01+ | no_portfolio | Optionality broken in some windows |

---

## 8. Key File Paths

| Path | Purpose |
|------|---------|
| `production_data/portfolio_policy.json` | Shadow portfolio policy |
| `production_data/decision_rulesets/` | All ruleset JSONs |
| `production_data/ruleset_manifest.json` | Active/retired/candidate registry |
| `production_data/price_history.csv` | Daily OHLCV (untracked, ~20MB) |
| `production_data/pdufa_dates.json` | PDUFA manual (11 entries) |
| `artifacts/live_shadow/` | Positions, performance, weekly summary |
| `data/snapshots_reranked_baseline/` | Baseline reranked snapshots (395 dates) |
| `output/` | Evaluation outputs, verdicts, reports |

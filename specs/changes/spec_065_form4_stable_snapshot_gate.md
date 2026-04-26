# Spec 065 — Form 4 Stable-Snapshot Gate (2026-04-26)

**Status:** Spec only. No production code changes from this document.
**Author:** drafted 2026-04-26 in advance of the 2026-05-01 flip-to-required eligibility.
**Supersedes:** none. Refines the rule mentioned in `project_insider_form4_pass_b_landed_2026_04_24.md` ("≥30% coverage for 5 consecutive production snapshots") with hard, machine-checkable criteria.

## 0. Why this spec exists

`insider_net_buy_value_90d` was wired into `rankings.csv` on 2026-04-24 (Pass B) as a **diagnostic pass-through**. Today's working memory says flip-to-required is eligible on 2026-05-01 after "5 stable snapshots." That phrase is undefined. This spec defines it, and the rule must exist *before* 2026-05-01 — not be invented when the decision is in front of us.

Ground state as of today (2026-04-26):

- Producer: `tools/fetch_form4_insider.py` (incremental mode since 2026-04-24).
- Enrichment: `common/insider_enrichment.py` injects `insider_net_buy_value_90d` at rankings-assembly time.
- Raw store: `data/form4/raw/{TICKER}.json` — **342 tickers** with raw files.
- Event panel: `data/form4/form4_panel.csv` — 27,766 rows event-keyed (do NOT naively merge on `(ticker, as_of_date)`).
- Production QA: `tools/production_qa_check.py:117` — `("insider_net_buy_value_90d", 0.30, False)` — currently `tracked_nonblocking` at 30 % coverage threshold.
- Snapshot field-present rate (column populated, `""` or `0.0` or non-zero):
  - 2026-04-22: 0 % (pre-Pass-B)
  - 2026-04-23: 0 %
  - 2026-04-24: 0 % (Pass B landed late in the day; not yet in snapshot)
  - 2026-04-25: 100 % (first snapshot containing the column)
- Blank-vs-zero semantics: `""` = no raw file for ticker; `"0.0"` = raw file exists, no P/A/S/D in 90 d window. **These are not equivalent.**

## 1. Definition of a stable snapshot

A snapshot of date `D` counts as **stable** for the Form 4 gate iff **all eight** of the following are true:

| # | Criterion | Source |
|---|-----------|--------|
| 1 | Form 4 producer (`tools/fetch_form4_insider.py`) ran to completion for date `D` with non-zero exit | `data/form4/fetch_state.json` last_run record |
| 2 | No producer-side schema change (no new keys added to `data/form4/raw/{TICKER}.json` payloads, no removed keys) versus the prior stable snapshot | hash of producer schema fingerprint |
| 3 | Coverage drift within thresholds (see §2) versus the prior stable snapshot — **per-ticker presence rate** of `insider_net_buy_value_90d != ""` in `rankings.csv` | snapshot rankings.csv field-present count |
| 4 | Blank-vs-zero distinction preserved: `""` count and `"0.0"` count are both ≥ 1; neither is `0` (collapse detection) | snapshot rankings.csv distribution |
| 5 | Signed net-buy / net-sell delta reconciliation: for every ticker in both `D` and `D-1` snapshot, signed dollar delta of `insider_net_buy_value_90d` is finite and matches reconstruction from `data/form4/form4_panel.csv` within tolerance (see §2) | reconciliation script |
| 6 | Ticker identity / CUSIP mapping anomalies below threshold — count of tickers in raw store but not in universe, or in universe but with no `data/form4/raw/{T}.json` despite Pass B being enabled | `data/form4/raw/` listing vs `production_data/universe.json` |
| 7 | No stale-source warning in producer log for date `D` (no "skipped — last fetch < 24h" pattern that masks data drift) | producer log scan |
| 8 | Snapshot's `rankings.csv` carries `insider_net_buy_value_90d` column at the expected position (currently index ~156 in `SNAPSHOT_COLUMNS`) and no row's value is a non-numeric, non-empty token (e.g., `"None"`, `"NaN"`, `"NULL"`) | snapshot column-presence + token check |

Any single failure marks the snapshot **not stable**. Stable snapshots reset the consecutive count to zero on the first failure; the count resumes from the next clean snapshot. **No partial credit.**

## 2. Proposed thresholds

| Threshold | Value | Reasoning |
|-----------|------:|-----------|
| Coverage drift — warning | ±5 percentage points field-present rate vs prior stable snapshot | normal day-to-day Form 4 churn (filings opening/closing the 90 d window) is well within this band |
| Coverage drift — hard fail | ±15 percentage points | beyond this is a producer regression or universe-mapping drop, not normal churn |
| Minimum field-present rate | ≥ 30 % of universe rows | matches existing `production_qa_check.py:117` threshold; aligns with Pass B coverage targets |
| Maximum unresolved mapping failures | ≤ 5 tickers in universe but missing from `data/form4/raw/` (after producer should have created the file) | producer is expected to write a file even when the issuer has zero recent filings (empty array) |
| Maximum missing-vs-zero collapse count | 0 | this is the silent-corruption mode; any collapse fails the snapshot. Detection: zero `""` count or zero `"0.0"` count when both are expected |
| Reconciliation tolerance for signed dollar deltas | ≤ \$1,000 absolute OR ≤ 0.5 % relative, whichever is larger, per ticker | covers floating-point rounding without masking real arithmetic errors |
| Minimum consecutive stable snapshots | **5** | matches the rule already in the working memory; no shorter window has enough days to detect weekday/weekend cadence-dependent regressions |

The "5" is the figure from the existing memory. This spec does not change it.

## 3. Flip decision rule

Evaluated on or after 2026-05-01:

1. **All 5 most recent consecutive snapshots stable** → flip eligible. Action: change `tools/production_qa_check.py:117` tuple from `("insider_net_buy_value_90d", 0.30, False)` to `("insider_net_buy_value_90d", 0.30, True)`. The threshold (`0.30`) does **not** change. Only the `required` flag flips.
2. **Any data-integrity criterion (§1) failed in the last 5 snapshots** → flip slips. The earliest possible re-evaluation is the day after the next 5-stable streak completes. Slippage is automatic; no override.
3. **Coverage clean but alpha evidence not proven** → field stays as `required-for-coverage` (production QA blocks if missing) but **not promoted to selector / ranker / sizing**. Alpha promotion requires Checklist v2 (FM + bootstrap + FDR + LOSO + year stability) and a separate spec. This spec does not promote alpha.

The flip is purely a **data-integrity gate**: it converts the production QA check from advisory to blocking. It does not add the field to scoring, does not change ranker, and does not change selector.

## 4. Explicit non-goals

This spec is intentionally narrow. It does NOT:

- Add `insider_net_buy_value_90d` to scoring, ranker, selector, or portfolio construction.
- Re-add the field to `common/feature_registry.py` (the lane stays closed per 2026-04-05 decision).
- Touch the IV quarantine hotfix branch (`hotfix/iv-quarantine-2026-04-25`).
- Wire 30 d / 60 d variants, cluster / exec / unique-buyer flags, or `insider_net_buy_shares_*`.
- Change `_INSIDER_REQUIRED_COVERAGE` or any other threshold beyond what `production_qa_check.py` already uses.
- Promote insider buying / selling as alpha. Selling is too noisy (taxes, 10b5-1, option exercises); buying needs incremental-predictive-value validation.

## 5. Evaluation checklist for 2026-05-01

Run on 2026-05-01 (or earliest day on which the 5 most recent snapshots could all qualify):

```bash
# Step 1 — confirm the 5 most recent production snapshots
cd /mnt/c/Projects/biotech_screener/biotech-screener
ls -1 data/snapshots/2026-04-2[5-9]/rankings.csv data/snapshots/2026-04-30/rankings.csv \
       data/snapshots/2026-05-01/rankings.csv 2>/dev/null | tail -5

# Step 2 — per-snapshot stability evaluation. To be implemented as
# tools/check_form4_stable_snapshot.py (DO NOT WRITE THIS UNTIL THE
# IV QUARANTINE BRANCH HAS MERGED). For now, manual evaluation:
#   a) field-present rate per snapshot (must be >= 30%, drift within +/-5pp warning, +/-15pp hard fail)
#   b) blank ("") count and zero ("0.0") count both > 0 in each snapshot
#   c) signed net-buy delta reconciliation across consecutive snapshot pairs
#   d) producer schema fingerprint unchanged
#   e) no stale-source warnings in producer log
#   f) no extra/missing universe<->raw-file mappings beyond 5 tickers
#   g) `insider_net_buy_value_90d` column present and tokens valid
#
# Manual quick-look for (a) and (b):
python3 -c "
import csv, glob, sys
snaps = sorted(glob.glob('data/snapshots/2026-04-2[5-9]/rankings.csv') +
               glob.glob('data/snapshots/2026-04-30/rankings.csv') +
               glob.glob('data/snapshots/2026-05-01/rankings.csv'))[-5:]
print(f'{\"snapshot\":<14} {\"n_rows\":>6} {\"present%\":>9} {\"blank\":>6} {\"zero\":>6} {\"nonzero\":>8}')
for s in snaps:
    rows = list(csv.DictReader(open(s)))
    blank = sum(1 for r in rows if r.get('insider_net_buy_value_90d') in ('', None))
    zero = sum(1 for r in rows if r.get('insider_net_buy_value_90d') == '0.0')
    nz = len(rows) - blank - zero
    pct = 100 * (len(rows) - blank) / max(len(rows), 1)
    date = s.split('/')[-2]
    print(f'{date:<14} {len(rows):>6} {pct:>8.1f}% {blank:>6} {zero:>6} {nz:>8}')
"

# Step 3 — only if all five snapshots pass criteria #1..#8: edit
# tools/production_qa_check.py:117 to flip the third tuple element
# from False -> True. Add a one-line comment with the spec_065 reference
# and the date the gate cleared. Run the production QA suite to confirm
# the new required check passes against today's snapshot.

# Step 4 — if any criterion fails on any of the 5 snapshots: do nothing.
# The flip slips. Document the failure in a short note appended to this
# spec, and re-evaluate on the day after the next 5-stable streak completes.
```

The decision is binary. The work is the verification, not the flip.

## 6. Open question deferred to Spec 066+ (not this one)

Promotion path beyond required-for-coverage is out of scope. If incremental-predictive-value validation eventually justifies adding `insider_net_buy_value_90d` to scoring/ranker/selector, that is a separate alpha-promotion spec gated by Checklist v2. Form 4 selling is even further out of scope (noise floor is too high without sub-feature segmentation).

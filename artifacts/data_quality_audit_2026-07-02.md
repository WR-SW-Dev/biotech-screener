# Data-Quality Audit — all tickers (2026-07-02 snapshot)

Scope: 302 screened / 324 active-universe tickers. Read-only; no inputs modified.

## Scorecard
| Dimension | Result |
|---|---|
| Price freshness | ✅ 0 missing, 1 stale >2d (CNTA) |
| Coverage_status (universe) | ✅ all covered |
| Eligibility | ✅ normal — 229 eligible / 73 out (70 deep_drawdown, 5 fundamental_red_flag) |
| Catalyst date mis-parse | ⚠️ 18 flagged (17 SEC-8K/6K → fixed by PR #455; 1 CTGOV benign) |
| sev3_gate exclusions | ✅ 12 (11 legit imminent-critical; 1 = KYMR false, fixed) |
| **defensive_features / de_vol_60d** | 🔴 **52 active tickers missing enrichment** — top finding |

## Finding 1 (🔴 actionable) — incomplete defensive_features enrichment
`de_vol_60d` (and beta_xbi_60d / drawdown / rsi_14d) are read from each universe
record's embedded `defensive_features` block (`decision_engine.py:15`,
`run_screen.py:5132`). **52 of 324 active tickers have no `defensive_features`
block** (272 do), so `de_vol_60d` is missing for 44 of the 302 screened names —
despite ample price history (TEVA 11,184 bars, CAPR 4,877, ABBV 3,395, DNTH/VKTX/
VRDN 1,633 each). Not a history problem — an **enrichment coverage gap**.

Impact: exposure_missingness / risk-sizing blind spot for these names if they
enter the book. The `coverage_status` map does NOT track defensive_features, so
this gap is invisible to the existing coverage gate (it passed).

Sample missing: ABBV, ABEO, ABOS, ACRV, AKBA, AKTX, ALDX, ALGS, ARTV, ASMB, BLTE,
BMEA, CAPR, CELC, CERS, CLYM, CMPX, CNTX, CPRX, DMRA, DNTH, DRUG, ELDN, IKT, IMNM,
IMTX, JBIO, LBRX, MDXG, MLTX, NKTX, PRLD, PRQR, PVLA, RNAC, SABS, SERA, SLS, TARA,
TCRX, TENX, TEVA, TRAX, VKTX, VRDN, VSTM (+ short-history KARD, legit).

Remediation: re-run the defensive-features enrichment over the full active
universe (compute vol_60d/beta_xbi_60d/drawdown/rsi_14d from price_history for the
52 uncovered tickers and write to universe.json), and add defensive_features to
`coverage_status` so the gap is gated going forward. NOT applied — needs sign-off.

## Finding 2 (✅ mostly fixed) — catalyst readout date mis-parse
18 tickers had text-year > bucketed-year in a catalyst event. 17 are SEC-8K/6K
sourced and addressed by the year-parse fix (PR #455) — they self-correct on the
next EDGAR re-parse (2026-07-03). 1 (GILD) is CTGOV-sourced and a detector
false-positive / benign (mega-cap, not a screener target). Material ranking
impact was KYMR only (already fixed).

## Finding 3 (informational) — imprecise CRITICAL events
46 tickers carry CRITICAL-severity catalyst events at HALF_YEAR/YEAR precision.
This is the sev3_gate risk surface; only 12 actually gated (11 legit). Inherent to
low-precision guidance language, not a bug — monitor.

**Governance:** informational audit. No model inputs, universe, or overrides modified.

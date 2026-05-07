# inst_delta Attribution — Top-30 (2026-04-28)

**Read-only attribution. Architecture-freeze authorized lane.** No production state modified.

**Question.** How much of today's top-30 is driven by the contaminated `inst_delta_z` component, given the Saturday 2026-04-25 cohort rebuild added 4 new 13F managers and inst_delta_z has been byte-identical 04-25 → 04-28?

**Method.** Counterfactual = actual today's `selector_score` − 0.35 × (`inst_delta_z_today` − `inst_delta_z_pre`), where pre = 2026-04-24 (last pre-rebuild snapshot). This preserves the actual selector_score residual structure (no reconstruction error). A ticker is "artifact entrant" if it's in today's top-30 by `actionable_rank` but its counterfactual selector_score puts it outside the top-30 by selector_score.

Sanity: `0.65 × coinvest_score_z + 0.35 × inst_delta_z` reconstructs `selector_score` with corr 0.925 / mean|err| 0.62 — so B6 is a reasonable but approximate decomposition; the refined method above avoids that error.

---

## Headline

| Bucket | Count | Tickers |
|---|---:|---|
| Stable in both top-30 | **17** | ANNX, BCRX, CELC, EWTX, KYMR, NBIX, ORIC, PHVS, PRAX, RCUS, RVMD, SLDB, SLN, STOK, TNGX, TSHA, XENE |
| **Artifact entrants** (in today's 30, OUT of counterfactual 30) | **13** | ABVX, ALKS, AXSM, BLTE, COGT, DNTH, INSM, KRYS, MIRM, NRIX, ORKA, SRRK, ZYME |
| Artifact exits (in counterfactual 30, NOT in today's 30) | **13** | BBOT, CGEM, CTNM, GH, IDYA, IRON, JBIO, KALV, NAMS, NGNE, OCUL, PTCT, TECX |

**~43% of today's top-30 is plausibly artifact-driven by the cohort rebuild.**

Counterfactual top-30 cutoff selector_score: **0.800**.

---

## True cohort-change movers (|Δinst_delta_z| > 0.30)

These tickers' `inst_delta_z` actually moved because of the new managers. Larger |Δ| → more directly affected.

| Rank | Ticker | Δinst_z | Δsel | Stable? |
|---:|---|---:|---:|---|
| 6 | NRIX | +0.747 | +0.262 | **ARTIFACT** |
| 1 | COGT | +0.576 | +0.202 | **ARTIFACT** |
| 26 | ZYME | +0.477 | +0.167 | **ARTIFACT** |
| 13 | PHVS | +0.464 | +0.162 | stable |
| 23 | MIRM | +0.451 | +0.158 | **ARTIFACT** |
| 15 | ORKA | +0.451 | +0.158 | **ARTIFACT** |
| 16 | ABVX | +0.451 | +0.158 | **ARTIFACT** |
| 28 | BCRX | +0.345 | +0.121 | stable |

The **6 artifact movers** (NRIX, COGT, ZYME, MIRM, ORKA, ABVX) are the cleanest cases — large positive Δinst_z from the new managers' holdings appearing as "new institutional buys", and that move is enough to push them into the top-30.

PHVS and BCRX moved by similar amounts but stay in the counterfactual top-30 because their underlying selector_score is high enough on coinvest alone.

---

## Reverse direction — tickers whose inst_delta DROPPED in the rebuild

A few names had inst_delta_z fall (negative Δ) when the new managers' baseline was added — meaning their counterfactual scores would be HIGHER:

| Rank | Ticker | Δinst_z | Δsel | Note |
|---:|---|---:|---:|---|
| 5 | ANNX | −0.247 | −0.086 | Higher in counterfactual → "underrated" today |
| 8 | ORIC | −0.247 | −0.086 | Higher in counterfactual |
| 10 | KYMR | −0.207 | −0.073 | Higher in counterfactual |
| 17 | SLN | −0.181 | −0.063 | Higher in counterfactual |
| 7 | STOK | −0.168 | −0.059 | Higher in counterfactual |

These are stable in both top-30 sets — the rebuild didn't push them out, but it understated their relative position.

---

## Quasi-clean tickers (|Δinst_delta_z| < 0.10)

For these, the rebuild barely moved inst_delta_z; their high inst_delta share is pre-existing institutional signal, not artifact:

EWTX (Δ +0.010), RCUS (+0.049), SLDB (+0.063), TSHA (+0.076), SRRK/KRYS/BLTE (+0.089).

Note that **SRRK, KRYS, BLTE are flagged ARTIFACT despite tiny Δinst_z** — this is because their counterfactual selector_score sits on the wrong side of the 0.800 cutoff by margin smaller than other tickers' shifts. They're marginal-cutoff artifacts, not contamination artifacts.

---

## Recommended interpretation

Treat the **6 highest-confidence artifact entrants** as cohort-rebuild driven, not fresh signal:

> **NRIX, COGT, ZYME, MIRM, ORKA, ABVX**

Their top-30 inclusion this week reflects new manager holdings appearing as "fresh buys", not actual institutional flow. Mentally downgrade. Don't drive trades off these 6 names alone.

Treat the rest of the artifact-entrant set (ALKS, AXSM, BLTE, DNTH, INSM, KRYS, SRRK) as **marginal** — small |Δinst_z| but counterfactual-cutoff sensitive. These are noise from the reranking, not contamination.

Stable 17 are unaffected by the cohort change and should be interpreted as usual.

---

## Self-heal

This regime resolves at the next 13F refresh (~2026-05-15, Q1 2026 filings). Re-run this attribution against a post-refresh snapshot to confirm contamination has cleared.

Companion: `regime_post_cohort_change_distortion_2026_04_28.md` (memory).
JSON: `artifacts/audit/inst_delta_attribution_2026-04-28.json`.

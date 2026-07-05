# Biotech Model Acquisitions — Logged YTD 2026

*As of 2026-07-05. Scope: acquisitions of names relevant to the biotech screener/coinvest model (registry-manager holdings, coinvest watchlist, and/or personal holdings) that were announced or closed in 2026 YTD. Terms verified against primary sources (issuer press releases + SEC filings). Cross-referenced to `production_data/corporate_actions.json`.*

## Logged names (6)

| Ticker | Target | Acquirer | Consideration | ~Deal value | Announced | Closed / status | Model relevance |
|---|---|---|---|---|---|---|---|
| **ACLX** | Arcellx | Gilead | $115.00 cash + $5.00 CVR (anito-cel WW sales > $6.0B by 2029-12-31) | ~$7.8B | 2026-02-22 (merger agmt) | **Closed 2026-04-28** | Registry holder: Paradigm |
| **APLS** | Apellis | Biogen | $41.00 cash + $4.00 CVR | ~$5.6B | 2026-03-31 | **Closed ~2026-05-14** | Registry holder: Deep Track (Tier 1) |
| **KALV** | KalVista | Chiesi | ~$27.00 cash/share | ~$1.9B | 2026-04-29 | **Closed ~2026-06-11** | Universe name (rare / HAE); not flagged to a Tier-1 holder |
| **CNTA** | Centessa | Eli Lilly | $38.00 cash + up to $9.00 CVR | ≤ $7.8B | 2026-03 | **Closed 2026-06-24** (delisted; px frozen to 06-29) | Registry holders: Logos (Tier 1) / Farallon; coinvest watchlist (removed 06-24, 17→16) |
| **NUVL** | Nuvalent | GSK | $124.00 cash/share | ~$10.6B | tender commenced 2026-06-24 | **PENDING** — tender expires 11:59pm ET 2026-07-14 | Registry holders: Deerfield (#1 position) + Paradigm |
| **APGE** | Apogee | AbbVie | $135.11 cash/share (~49% premium) | ~$10.9B | 2026-06-22 | **PENDING** — expected close Q3 2026 | Registry holders: Fairmount (Tier 1) / RTW / Affinity; held in Robinhood |

**Closed YTD:** ACLX, APLS, KALV, CNTA (4). **Pending:** NUVL, APGE (2).
**Personal-holding overlap:** APGE only (the single Robinhood position taken out YTD). ORKA is held but was **not** acquired (M&A speculation only) — excluded.

## Data-quality actions taken (staged in the companion PR)

1. **ACLX — PIT correction.** Registry had `effective_date 2025-12-15` @ `114.50` with no CVR. Primary sources (Gilead completion press release + SEC 8-K, acc `0001104659-26-049874`) confirm the deal **closed 2026-04-28** at **$115.00 + $5.00 CVR** (~$7.8B). Corrected — same class of PIT error as the CNTA fix (would otherwise mark ACLX dead ~4.5 months early, corrupting any Dec 2025–Apr 2026 backtest/PIT context). ACLX is correctly a 2026 YTD deal.
2. **NUVL — added.** Was entirely absent from `corporate_actions.json`. Added as `pending_acquisition` (GSK, $124.00, tender commenced 2026-06-24, expires 2026-07-14). Verified vs GSK tender-offer PR + SEC Schedule TO / SC 14D-9.

## Open data-quality flags (not changed — flagged for review)

- **APLS** and **KALV** carry `deal_price: null` in the registry. Suggested backfill (pending your confirmation): APLS $41.00 + $4.00 CVR; KALV ~$27.00. Left unchanged here to avoid writing unverified figures into production data.
- **CNTA / APGE** entries are accurate — no change.

## Sources
- Gilead / Arcellx: Gilead completion PR (2026-04-28) + SEC 8-K acc `0001104659-26-049874`.
- GSK / Nuvalent: GSK tender-offer commencement PR (2026-06-24) + SEC Schedule TO / SC 14D-9 (expiration 2026-07-14).
- CNTA, APGE, APLS, KALV: `production_data/corporate_actions.json` + Biotech M&A YTD Master List (Town doc `nx769bbmevpht8t6axkxbjhem189v0xj`).

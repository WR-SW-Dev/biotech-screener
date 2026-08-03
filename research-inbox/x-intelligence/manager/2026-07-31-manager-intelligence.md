---
type: x-intelligence
subtype: manager-intelligence
captured_at: 2026-07-31T16:00:00-04:00
week_of: 2026-07-31
pattern: convergence | pre_13f | position_claim | divergence
sources: SEC EDGAR (13D/A, 13G, Form 4), BioHedge Weekly (RxDataLab Jul 19-26), StockTitan, web-fallback (X dark — monthly quota exhausted; resets Aug 1)
tickers: ORKA, ARTV, CBIO, RVMD, ANRO, REPL, SRRK
mapped_managers: Fairmount Funds (elite_core), RA Capital (elite_core), EcoR1 Capital (elite_core), Deep Track Capital (elite_core), RTW Investments (elite_core), Logos Capital (elite_core), Orbimed (elite_core), Perceptive Advisors (elite_core)
manager_tier: elite_core
source_class: primary_source_found (filing-confirmed) | informed interpretation (Q2 pre-13F watch)
confidence: high (ARTV, CBIO — filing-confirmed) | med (ORKA, RVMD) | low (SRRK)
confirming_monitor: SEC Filing Monitor — Q2 13F window (deadline Aug 14)
lead_time_estimate: 0h for filing-confirmed items; 2-3 weeks for Q2 13F pre-signal items
ladder_stage: mixed — see per-item below
status: partially_verified
---

## X Gap Note

X monthly read quota was exhausted as of approximately July 24. This run executed on web-fallback only (SEC EDGAR aggregators, BioHedge Weekly, company PRs, holdings-channel data). Fresh social signals from the journalist/KOL roster are unavailable until the August 1 quota reset. All patterns below are sourced from filings and secondary aggregators citing filings. First-hand X reads resume next run.

---

## Verification Updates (2026-08-03 — Primary-Source Verification Queue)

### ANRO — EcoR1 Capital 5.8% 13G — PROMOTED to independent_confirmation/Confirmed
SEC EDGAR accession 0000935836-26-000361 (filed 2026-07-20, event date 2026-07-13): EcoR1 Capital LLC + Oleg Nodelman, 2,232,000 shares = 5.8% ANRO. Independent confirmation: StockTitan (Jul 20) independently reported. ladder_stage: independent_confirmation. terminal_state: Confirmed. Accession now in dedup record.

### REPL — EcoR1 Capital Q1 position — PROMOTED to independent_confirmation/Confirmed
SEC EDGAR accession 0000935836-26-000270 (EcoR1 13F-HR, filed 2026-05-15, as of 2026-03-31): 1,000,000 shares REPL = $7.65M (0.32% EcoR1 portfolio, #21 position). Multiple independent aggregators confirm: WallStRank, PortfolioSavvy, MarketBeat (all citing EDGAR directly). Return to name (EcoR1 previously held REPL Q2 2024 through Q2 2025, exited Q3 2025, re-entered Q1 2026). EcoR1 owns 1.21% of REPL outstanding. ladder_stage: independent_confirmation. terminal_state: Confirmed.

### ORKA — Thesis/Pre-13F Watch — PROMOTED to primary_source_found (event component only)
EVERLAST-A Ph2a primary endpoint primary source: Oruka 8-K (SEC, filed Apr 27): https://www.sec.gov/Archives/edgar/data/907654/000121390026047743/ea0287782-8k_oruka.htm + GlobeNewswire (Apr 27). PASI 100 at Week 16: 63.5% (40/63 patients). The Jul 30 stock move (+11.1%) and BTIG PT raise to $151 were reactions to the Apr 27 data readout, not a new data announcement. BTIG PT raise is an INTERPRETATION component only — not a source event. Investment interpretation (FM sizing post-Ph2a) remains x_post / judgment. ladder_stage: primary_source_found for the event component. terminal_state: Open (Q2 13F Aug 14 is the confirming monitor for FM's post-Ph2a action).

---

## Convergence

### ORKA — Three Elite-Core Managers + Ph2a Hit — Fairmount / Deep Track / RTW (all elite_core)

Three registry managers held ORKA entering the week: Fairmount Funds (~19.5% per Jul 2 13D/A after the Jul 1 preferred conversion of ~$300M), Deep Track Capital (Q3 2025 13F: +38.4% to 2,654,781 shares), and RTW Investments (Q4 2025 13F: +5.8% to 2,058,148 shares). On July 30, ORKA reported BTIG raised PT 94% to $151 referencing EVERLAST-A Ph2a data (original readout: Apr 27, 2026); stock +11.1%.

**POSITION CLAIM** — Fairmount: 19.5% beneficial ownership confirmed Jul 2 13D/A (Amend 7). Deep Track + RTW: Q3/Q4 2025 13F vintage — stale, Q2 2026 13F (Aug 14) required. Confidence: high (FM, filing-confirmed); med (DT, RTW — stale vintage).

**PRE-13F WATCH** — Fairmount's behavior post-Ph2a and post-preferred-conversion is the signal to watch. Whether FM adds, holds, or continues trimming from ~19.5% is unknown pre-13F. RUMOR / informed interpretation. Confirming monitor: Q2 13F (~Aug 14) + any Form 4 between now and Aug 14.

Independent sources: SEC EDGAR (13D/A, Form 144); BTIG research (Jul 30); Oruka 8-K (Apr 27 — primary event source).
Confidence: med. Estimated impact: high.

---

### RVMD — NDA Acceptance + Multi-Source Accumulation Signal — Logos Capital (elite_core), Orbimed (elite_core)

RVMD NDA for daraxonrasib accepted July 22 (Breakthrough Therapy, Priority Review, FDA Commissioner's Priority Voucher pilot). PDUFA estimated Jan-Feb 2027. Four independent sources confirmed NDA acceptance (Revolution Medicines IR, GlobeNewswire, RTTNews, BioSpace).

**POSITION CLAIM** — Logos Capital #1 position ~$194.5M (Q1 2026 13F). Orbimed +100.8% Q1 to 52,000 shares ($5.1M). BlackRock 13G July 29: 12,201,395 shares = 5.7% (passive, non-registry). Janus Henderson Q1: sold 2.54M shares (-20.6%). All Q1 vintage — Q2 13F Aug 14 is the definitive read for post-NDA positioning. Confidence: high for Q1 figures; med for current state.

**INVESTMENT INTERPRETATION** — Whether Logos adds post-NDA at current levels is pre-13F watch. RUMOR / informed interpretation. Confirming monitor: Q2 13F (~Aug 14).

Confidence: med. Estimated impact: high.

---

## Divergence

### SRRK — Analyst Consensus Bullish vs. Options Skew Bearish — No Registry Manager Identified

SRRK PDUFA Sep 30. EMA CHMP delayed (Catalent Indiana). Street uniformly bullish (Wedbush, HC Wainwright, Barclays). Options flow: 9 PUTs vs. 1 CALL (TrendSpider Jul 30). Stock -10.64% over 30 days. No registry manager identified in 57. Third consecutive carry — dropping from tracking unless Catalent resolution or registry filing surfaces.

Confidence: low.

---

## Manager-Position Claims

### ARTV — RA Capital 37.9% — filing-confirmed (ladder: primary_source_found, terminal: Open)
RA Capital 18,415,956 sh = 37.9% ARTV per 13D/A ~Jul 24-26. 6th consecutive open-market buy Jul 24: 41,319 sh @ $9.99. BioHedge Weekly independently confirms. Dedup accession not yet confirmed. Q2 13F Aug 14 for persistence. Confidence: high. Lead: 0h.

### CBIO — Fairmount 16.5% — filing-confirmed (ladder: primary_source_found, terminal: Open)
Fairmount Healthcare Fund II LP 6,593,385 sh = 16.50% CBIO per 13D/A Jul 20. Purchased 853,450 sh + 525,897 warrants @ $14.50 Jul 16. CBIO NOT on event_alert_watchlist.json — manual watchlist-addition review recommended. Q2 13F Aug 14. Confidence: high. Lead: 0h.

### ANRO — EcoR1 Capital 5.8% 13G — CONFIRMED (ladder: independent_confirmation, terminal: Confirmed)
SEC EDGAR accession 0000935836-26-000361 (filed 2026-07-20): EcoR1 Capital + Nodelman, 2,232,000 sh = 5.8% ANRO. Independently confirmed. See Verification Updates above.

### REPL — EcoR1 Capital Q1 position — CONFIRMED (ladder: independent_confirmation, terminal: Confirmed)
SEC EDGAR accession 0000935836-26-000270 (filed 2026-05-15, as of 2026-03-31): 1,000,000 sh REPL = $7.65M. Independently confirmed. See Verification Updates above.

---

## Verification Steps

1. ARTV 13D/A — Confirm RA Capital accession (~Jul 24) in SEC Filing Monitor dedup ledger. PENDING.
2. ANRO 13G — CONFIRMED (0000935836-26-000361 filed 2026-07-20). Add to dedup ledger.
3. REPL Q1 13F — CONFIRMED (0000935836-26-000270 filed 2026-05-15). Add to dedup ledger.
4. SRRK Catalent — Monitor for Scholar Rock 8-K, FDA letter, or EMA opinion update. Dropping from active tracking if no update next run.
5. Q2 13F window — Tier 1 manager filings (Fairmount, Deep Track, Logos) are highest-priority. Deadline Aug 14. Escalate to WARNING if no Tier 1 filings by Aug 7.
6. CBIO watchlist — Manual review of Crescent Biopharma thesis pending.

---

## Self-Check

- Sources: Content Library biotech captures (7 items), Decision Impact Ledger (48 rows), prior run memories, BioHedge Weekly (Jul 19-26), web-fallback searches (4 queries), registry doc, coinvest watchlist (38 tickers).
- X gap: Quota exhausted ~Jul 24. Web-fallback only. Resets Aug 1.
- Items worked: 4 position claims decomposed and verified (ANRO/REPL confirmed; ORKA event sourced; REPL PDUFA monitored).
- Ladder promotions: ANRO x_post→IC, REPL x_post→IC, ORKA thesis x_post→primary_source_found.
- Terminal states set: ANRO Confirmed, REPL Confirmed.
- Governance: No position asserted as fact. All interpretation components remain Open/judgment. No schema changes.

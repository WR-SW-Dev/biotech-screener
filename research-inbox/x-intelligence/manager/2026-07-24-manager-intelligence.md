---
type: x-intelligence
subtype: manager-intelligence
captured_at: 2026-07-24T16:00:00-04:00
week_of: 2026-07-18
pattern: convergence | pre_13f | position_claim | divergence
sources: SEC EDGAR filings (13D/A, 13G, Form 4) | Endpoints News | Seeking Alpha | Motley Fool | MarketBeat | StockTitan | BioTech Distilled | web search aggregation
tickers: CELC, SRRK, RVMD, CBIO, ARTV, ORKA, ERAS, TARS, GPCR
mapped_managers: Baker Bros (elite_core) | Fairmount Funds (elite_core) | RA Capital (elite_core) | Druckenmiller/Duquesne (n/a) | Jennison (n/a) | Deep Track (elite_core) | Logos (elite_core)
manager_tier: elite_core (Baker Bros, Fairmount, RA Capital, Deep Track, Logos) | n/a (Duquesne, Jennison)
source_class: position_claim (SEC filing — confirmed) | informed interpretation (journalist/analyst commentary)
confidence: varies per item — see sections below
confirming_monitor: SEC Filing Monitor | PDUFA/Catalyst Tracker
lead_time_estimate: 0–48h (filing-anchored items); no X read this week (monthly cap reached)
ladder_stage: independent_confirmation
status: independently_confirmed
verification_run: 2026-07-27 (Primary-Source Verification Queue — promoted)
---

# Manager-Intelligence Digest — week of 2026-07-18

> **DATA QUALITY NOTE:** X monthly read limit reached before any searches executed this run. All manager-lens signals this week are sourced from: (a) content library captures from the Biotech Event Alerts pipeline (Jul 20–23), (b) the Decision Impact Ledger (existing rows), (c) SEC EDGAR filing disclosures surfaced via web search, and (d) journalist/analyst secondary coverage. No first-hand X post reads this cycle. Lead-time advantage vs. X-sourced signals is absent for items that are already EDGAR-confirmed. Flag this gap to the Monday operational-health review.

---

## Verification Summary (2026-07-27 — Primary-Source Verification Queue)

| Item | Primary Source | Accession / URL | Second Independent Source | Stage | Terminal State |
|---|---|---|---|---|---|
| CELC Baker Bros 9.99% | SEC EDGAR 13G (Jul 16) | 0001104659-26-084329 | Biotech Distilled (independent calc) | independent_confirmation | Confirmed |
| CBIO Fairmount 16.50% | SEC EDGAR 13D/A (Jul 20) | 0001104659-26-085114 | Biotech Distilled (independent calc) | independent_confirmation | Confirmed |
| ARTV RA Capital 37.9% | SEC EDGAR 13D/A (Jul 23) | 0001346824-26-000203 | StockTitan (independently indexed) | independent_confirmation | Confirmed |
| RVMD NDA acceptance | RVMD IR press release (Jul 22) | https://ir.revmed.com/... | RTTNews, BioSpace (independent) | independent_confirmation | Confirmed |
| CELC launch delay event | Celcuity 8-K (Jul 14) | https://www.sec.gov/.../form8-k.htm | Endpoints News, MedCity News (independent) | independent_confirmation | Confirmed |

**Concentration claims still unverified:** Logos ERAS ~9% AUM — position confirmed by filing; concentration requires reconstructing position value + portfolio denominator + filing date. Still `Partially confirmed` pending Q2 13F.

---

## Convergence

### CELC — Baker Bros distribution + launch-delay thesis — Baker Bros (elite_core)

**Pattern:** Two independent sources this week converged on CELC: (1) an EDGAR-confirmed SEC Form 4 disclosure (filed Jul 16) showing Baker Bros sold 3.1M shares at $102.50 on July 14, dropping from a former 10%+ owner to a 9.99% passive holder; and (2) Endpoints News / multiple outlets independently confirming the gedatolisib (REVTORPYK) commercial launch is delayed to late Q3 2026 — later than Wall Street consensus.

**Independent sources:**
- Baker Bros 13G (Jul 16): 4,877,963 shares = 9.99% CELC (passive); Form 4 (Jul 14): sold 3,100,000 shares at $102.50 (combined Baker entities ~$317.75M proceeds). [SEC EDGAR 0001104659-26-084329, StockTitan]
- Biotech Distilled independently confirmed position arithmetic: "They defended the position without defending the percentage."
- Endpoints News (Jul 17), MedCity News (Jul 15), BioWorld (Jul 15): four+ independent outlets confirm late-Q3 launch delay.
- Content library capture 2026-07-20-CELC-post-approval-launch-delay: ladder_stage = independent_confirmation; terminal_state = Confirmed (event); overhang = Open/judgment.

**Verification (2026-07-27):** SEC EDGAR 13G 0001104659-26-084329 confirmed. Biotech Distilled independently confirmed position arithmetic. Two independent sources. **→ independent_confirmation. terminal_state: Confirmed** (position + event). Overhang interpretation remains Open/judgment.

**Classification:** convergence | position_claim (Baker Bros CELC at 9.99% — filing-confirmed)
**Mapped manager:** Baker Bros (elite_core)
**Confirming monitor:** SEC Filing Monitor (13G + Form 4 confirmed); next read = Q2 13F (~Aug 14) for persistence
**Confidence:** HIGH (position/event) / LOW (overhang interpretation — judgment only)
**Source / Evidence / Interpretation legs:** High / High / Low

---

### SRRK — Catalent Indiana manufacturing risk / CHMP delay — multiple institutional holders accumulating

**Pattern:** Three independent content library captures (Jul 20–22) plus web-search corroboration all converge on the same thesis: the Catalent Indiana FDA inspection is the single gating variable for both the EMA CHMP opinion and adds tail risk to the US PDUFA (Sep 30, 2026). Jennison Associates grew its SRRK position +19.5% in Q1 13F (3,340,492 shares = 2.80% = ~$164M).

**Independent sources:**
- Content library: 2026-07-20-SRRK-chmp-timing, 2026-07-21-SRRK-apitegromab-CHMP-delay, 2026-07-22-SRRK-apitegromab-ema-delay — three independently verified captures (all at independent_confirmation/Confirmed).
- Jennison Associates Q1 13F (+545,304 shares, +19.5% — MarketBeat Jul 19).
- D.A. Davidson new position Q1 13F (24,832 shares — MarketBeat Jul 23).

**Read:** No registry-tier elite_core manager disclosed in these captures. Jennison is not in the 57-manager registry. The manufacturing-risk thesis is confirmed; accumulation by non-registry holders provides base support but is not a specialist-fund convergence signal. Key question: what do Tier 1 registry managers (Deep Track, Logos, Fairmount) hold in SRRK? Q2 13F (Aug 14) is the first read.

**Classification:** convergence (event + non-registry institutional buying) | source event (CHMP delay confirmed)
**Mapped manager:** n/a (no registry manager identified this week)
**Confirming monitor:** PDUFA/Catalyst Tracker (Sep 30 PDUFA); SEC Filing Monitor (Q2 13F Aug 14)
**Confidence:** MED (source event confirmed; registry manager positioning unknown)
**Source / Evidence / Interpretation legs:** High / High / Medium

---

## Divergence

### RVMD — Druckenmiller bought Q1; Decheng Capital sold 53.2% Q1; multiple opposing Q1 13F flows

**Pattern:** The RVMD daraxonrasib NDA acceptance (Jul 22) coincides with divergent Q1 2026 13F disclosures published this week.

**Buyers (Q1 13F, disclosed this week):**
- Duquesne Family Office (Stanley Druckenmiller): bought 316,000 shares (~$30.6M at filing, ~$56.6M appreciated) — ~1–2% portfolio position. [Motley Fool Jul 17, confirmed multiple outlets]
- Swiss National Bank: +54.0%, now 425,431 shares (~$41.4M).
- PSquared Asset Management: new 138,290 shares (~$13.4M = 4.7% of PSquared portfolio).
- Sumitomo Mitsui Trust: +4,828.6% (near-new position, 270,972 shares).
- SEB Asset Management: new 69,630 shares (~$6.8M).

**Sellers (Q1 13F, disclosed this week):**
- Decheng Capital LLC: -53.2%, now 93,500 shares (~$9.1M).
- Bessemer Group: -59.2%, now 48,062 shares (~$4.7M).
- CalPERS: -3.1%, now 281,960 shares.
- WCM Investment Management: -10.4%, now 104,989 shares (~$9.7M).

**Read:** Q1 13F data reflects positioning as of Mar 31, 2026 — before the RASolute 302 Phase 3 ASCO plenary and NDA acceptance (Jul 22). Druckenmiller's buy is the most institutionally significant signal: a concentrated macro investor taking 1–2% pre-NDA is an informed directional call. None are in the 57-manager elite biotech registry. Key question: what do Deep Track, Logos, Perceptive, Cormorant hold? Registry Q2 13F (Aug 14) is the definitive read.

**Verification (2026-07-27):** NDA acceptance confirmed independently (see RVMD alert verification above). Q1 13F divergence sourced via MarketBeat/Motley Fool (secondary syndication from 13F aggregator) — not independently primary. Druckenmiller Duquesne buy confirmed via multiple outlets but all from same 13F aggregation feed. Stage for NDA event component: independent_confirmation/Confirmed. Stage for Q1 flow interpretation: primary_source_found (syndicated secondary only) — not elevated.

**Classification:** divergence (simultaneous institutional buying and selling in Q1)
**Mapped manager:** n/a — none above are in the 57-manager registry
**Confirming monitor:** SEC Filing Monitor — Q2 13F (Aug 14); PDUFA date (est. Jan–Feb 2027)
**Confidence:** MED — Q1 13F data confirmed; Q2 positioning and registry manager overlap unknown
**Source / Evidence / Interpretation legs:** High / High / Low

---

### ERAS — Logos thesis status divergence — Logos Capital (elite_core)

**Pattern:** Existing divergence from prior week (Decision Impact Ledger row 2026-07-19): @adamfeuerstein skeptical ("KRAS hopium/momentum") vs. clinical community positive on AURORAS-1 + Phase 3 pathway. No new independent sources surfaced this week. Per dedup rule: not re-elevating.

Class action lead plaintiff deadline Aug 10. Q2 13F (Aug 14) is the definitive read on whether Logos reduced post-AURORAS-1 and post-capital-raise.

**Classification:** divergence (carried from prior week — no material change)
**Mapped manager:** Logos Capital (elite_core)
**Action:** Monitor — do not re-log this week.

---

## Pre-13F watch (RUMOR — unverified)

### Deep Track — TARS / GPCR / VRDN — Q2 13F pending — RUMOR

- **Prior record (Q1 vintage):** Deep Track TARS ~$252M, GPCR ~$206M, VRDN ~5.4M shares.
- **Trigger events this week:** TARS Q2 earnings miss + iRenix $75M acquisition (Jul 20); GPCR GLP-1 competitive pressure (Q2 earnings Aug 5); VRDN commercial launch monitoring.
- **Chatter this week:** None surfaced (X cap reached). All prior positions are Q1 vintage — RUMOR until Q2 13F filed.
- **Confidence:** LOW — position claims are Q1 confirmed; Q2 behavior unknown.
- **Confirming monitor:** SEC Filing Monitor — Q2 13F (~Aug 14). Escalate if Deep Track reduced any position >25%.

### Logos Capital — ERAS / GPCR — Q2 13F pending — RUMOR

- **Prior record (Q1 vintage):** Logos ERAS ~$180M (~9% AUM — concentration figure partially confirmed only); GPCR ~$24M.
- **Trigger event:** ERAS class action lead plaintiff deadline Aug 10 — any Logos reduction in Q2 13F would be temporally coincident with the litigation window.
- **Confidence:** LOW — concentration figure unverified; Q2 behavior unknown.
- **Confirming monitor:** SEC Filing Monitor — Q2 13F (~Aug 14).

---

## Manager-position claims (filing-confirmed status as of 2026-07-27)

### CELC — Baker Bros 9.99% (SEC EDGAR 13G 0001104659-26-084329, Jul 16 — CONFIRMED)
- Baker Bros holds 4,877,963 shares + 62,171 warrants = 9.99% CELC after Jul 14 block sale of 3.1M shares at $102.50.
- **Stage: independent_confirmation. terminal_state: Confirmed.**
- Verify: Q2 13F (Aug 14) confirms whether position persisted through Jun 30 or was further reduced.

### CBIO — Fairmount 16.50% (SEC EDGAR 13D/A 0001104659-26-085114, Jul 20 — CONFIRMED)
- Fairmount Healthcare Fund II LP holds 6,593,385 beneficial shares = 16.50% CBIO as of Jul 16. ~$12.38M deployment. Kiselak + Harwin named. Biotech Distilled independently confirmed.
- CBIO NOT on event_alert_watchlist.json — flag for watchlist-addition analysis.
- **Stage: independent_confirmation. terminal_state: Confirmed** (ownership; concentration in %AUM unassessed — Fairmount AUM not publicly disclosed).
- Verify: Q2 13F (Aug 14) will confirm full position and persistence.

### ARTV — RA Capital 37.9% (SEC EDGAR 13D/A 0001346824-26-000203, Jul 23 — CONFIRMED)
- RA Capital Management (Kolchinsky + Shah) holds 18,415,956 shares = 37.9% beneficial ownership ARTV. StockTitan independently indexed. Additional Form 4 (Jul 24): 264,586 sh purchased Jul 21–23 at $9.55–9.96 (continued accumulation).
- **Stage: independent_confirmation. terminal_state: Confirmed.**
- Verify: Q2 13F (Aug 14) will show full portfolio context.

---

## Weakly sourced / widely repeated

### RVMD Q1 13F secondary syndication
Multiple MarketBeat/Holdings Channel articles on RVMD Q1 flows (Swiss National Bank, SEB, Walleye, PSquared, Inceptionr, Decheng). All syndicated from the same 13F aggregation feed — not independent analysis. Druckenmiller/Duquesne (Motley Fool Jul 17) is more signal-relevant but still Q1 data.

### SRRK non-registry institutional flows
Jennison +19.5% is real data from a non-registry manager. D.A. Davidson and Candriam = noise-level. Orbis Allan Gray referenced as boosting stake ~1,034.5% in SRRK (embedded in secondary article) — potentially material but single-source; verify EDGAR directly before elevating.

---

## Verification steps (remaining — post 2026-07-27)

1. **Baker Bros CELC Q2 13F** — confirm Aug 14 whether 9.99% position persists or further reduced.
2. **Deep Track TARS / GPCR / VRDN Q2 13F** — first read when filed; escalate if any position reduced >25%.
3. **Logos ERAS Q2 13F** — first read when filed; class action deadline Aug 10 is a pre-13F gating event.
4. **CBIO watchlist review** — Fairmount's 16.5% position not in current watchlist; flag for potential addition.
5. **ARTV RA Capital 13D/A** — accession 0001346824-26-000203 confirmed; add to dedup ledger on next SEC Filing Monitor run.
6. **Orbis Allan Gray SRRK** — verify EDGAR directly; single-source, not elevated.
7. **RVMD registry manager positions** — run EDGAR for Deep Track (CIK 1694055), Logos (CIK 1792126), Perceptive (CIK 1356093), Cormorant (CIK 1753926) RVMD Q1 holdings.
8. **X gap** — monthly read limit reached; next run benefits from August 1 reset.

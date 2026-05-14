# Spec 087 B2 — Dashboard Freshness Envelope (Design)

**Status**: PHASE B2 DESIGN (ready for implementation planning)
**Author**: Claude (based on Phase A decision 2026-05-06)
**Created**: 2026-05-14
**Unlocked by**: Spec 087 B1b formal closure (2026-05-14)

---

## Objective

Add explicit freshness indicators and safeguards to the dashboard's bioshort-hedge reporting endpoints. Ensure consumers understand the age of hedge reports and the conditions under which data is stale.

**Scope guard**: Dashboard display only. No scoring, selector, ranker, EV, or sizing changes. No LLM reactivation. No producer CLI changes beyond bug fixes.

---

## Background

Phase A (2026-05-06) established:
- Bioshort hedge report is governance evidence, not execution signal
- Dashboard currently serves 41-day-stale data (last report: 2026-03-26)
- Phase B1b restored weekly producer (first-fire: 2026-05-08) ✅
- Phase B2 adds freshness transparency to dashboard consumers

---

## Phase B2 Scope — 7 items

### 1. Dashboard Staleness Banner (REQUIRED)

**Item**: Add "last-fresh" timestamp indicator to four dashboard endpoints

**Current state**:
- `dashboard/app.py:693–735` serves `BIOSHORT_VERDICT.json`, latest `hedge_report_*.json`, archive list
- No age/staleness indicator exposed
- Consumer (IC, dashboard UI) cannot distinguish fresh reports from stale

**Required change**:
- Read `BIOSHORT_VERDICT.json` `as_of_date` field
- Compute age: `today - as_of_date`
- Emit staleness indicator in response (if age > 7 days: `STALE_WARNING`; if age > 14 days: `STALE_ERROR`)
- Include indicator in four endpoint responses (not just the verdict file)

**Implementation notes**:
- No dashboard UI design required (Phase B2 is spec-only); UI can show banner visually or as metadata
- Threshold recommendation: WARN at 7 days (mid-cycle), ERROR at 14 days (two-week stale)
- Fallback: if `as_of_date` missing or unparseable, emit `FRESHNESS_UNKNOWN`

### 2. Pre-Flight Options-Source Validation (REQUIRED)

**Item**: Verify Massive credentials work before producer first-fire

**Current state**:
- Producer uses `--options-source auto`: tries Tasty → Massive → realized-vol fallback
- 2026-03-26 report fell back to realized-vol (stale; reason lost in log)
- B1b first-fire (2026-05-08) confirmed "Options source: massive" ✅
- **Nothing to do going forward** (first-fire validated)

**Required change**:
- Document in Phase B2 acceptance gate: Massive endpoint was live as of 2026-05-08
- Add pre-flight check to cron wrapper (optional; low-priority) to log options-source choice
- Acceptance: if next 2–3 reports show "massive" source, close this item

**Implementation notes**:
- This is a one-time pre-flight check for Phase B2; not a standing gate
- Closure condition: 2–3 consecutive fresh reports with `source_selection_reason: "auto: massive selected"`

### 3. CLI Default Repair (REQUIRED)

**Item**: Change `--portfolio-csv` default from `None` to auto-discover latest portfolio

**Current state**:
- `tools/biotech_hedge_report.py --portfolio-csv None` falls through to `rankings.csv` (3-line stub; broken)
- Cron must explicitly pass `--portfolio-csv data/snapshots/{TODAY}/portfolio_positions.csv`
- Known issue: 2026-05-03 cron misesvation (missing `--portfolio-csv` arg → stale rankings.csv read)

**Required change**:
- Modify `tools/biotech_hedge_report.py:290–310` (argument parsing + defaults)
- Auto-discover `--portfolio-csv` default: glob `data/snapshots/[0-9]*/portfolio_positions.csv`, sort by date, use latest
- Document fallback: if glob returns no matches, error with clear message (do not silently use rankings.csv)
- Cron line can now omit `--portfolio-csv` arg (still explicit is safer; decision deferred to Phase B3)

**Implementation notes**:
- Use `sorted(Path(...).glob(...))[-1]` pattern
- Add unit test: test_portfolio_csv_auto_discovery() covering (a) multiple snapshots, (b) no snapshots (error)
- Acceptance: existing explicit cron line still works; new cron without arg also works

### 4. Cadence Specification (REQUIRED)

**Item**: Formalize weekly producer schedule

**Current state**:
- B1a set cron `0 18 * * 5` (Friday 18:00 ET)
- B1b first-fire validated (2026-05-08, Friday 18:00)
- Phase A §7.2 recommends weekly Friday OR Thursday morning

**Required specification**:
- Recommend: **Friday 18:00 ET** (align with existing cron; IC discussion ready for Monday morning)
- Alternative considered: Thursday 08:00 (pre-market); rejected as overconstrained
- Cadence: exactly 1 run per week (not variable, not intraday)
- Rationale: IC-discussion pace (weekly); hedge-structure refresh pace (weekly); asset-allocation vote cadence (Monday)

**Implementation notes**:
- Document in crontab comments: `# Bioshort hedge report — weekly governance evidence (Friday 18:00 ET)`
- Include expected output in cron wrapper logs: `tools/biotech_hedge_report.py >> logs/biotech_hedge_report.log 2>&1`
- Acceptance: cron fires once per calendar week, Friday window 18:00–18:15 ET

### 5. Output Retention Policy (OPTIONAL)

**Item**: Define archival/cleanup strategy for hedge reports

**Current state**:
- `output/hedge_report/` and `output/hedge_report/archive/` append-only (no cleanup)
- 2026-03-26 through 2026-05-08: 6 reports (12 MB total, negligible)
- No retention sweep defined

**Recommended policy**:
- Keep last 12 months of reports in `output/hedge_report/`
- Move reports > 12 months old to `output/hedge_report/archive/`
- Sweep cadence: monthly (first Monday of month) via a one-shot cron job
- Acceptance: not a blocking criterion for Phase B2; can defer to Phase B3

**Implementation notes**:
- Optional; low priority (disk usage negligible at current cadence)
- If deferred: document explicitly "no sweep defined; append-only archival accepted"

### 6. Rollback Path (REQUIRED)

**Item**: Document how to roll back Phase B2 changes

**Rollback steps**:
1. **Dashboard staleness banner**: remove from four endpoints; revert to serving raw `as_of_date` without interpretation
2. **CLI default repair**: revert `--portfolio-csv` default to `None` (and restore explicit cron arg)
3. **Cadence/pre-flight**: these are documentation only; rollback = update crontab comments
4. **Retention policy**: revert to append-only (remove sweep job)

**Production risk**: LOW (all changes are dashboard display or CLI defaults; no scoring/ranker/EV impact)

**Acceptance**: confirm rollback path is reversible in <5 minutes

---

## Acceptance Criteria (Phase B2)

| Criterion | Status | Evidence |
|-----------|--------|----------|
| **1. Hedge governance purpose clarified** | ✅ SATISFIED | Phase A §5: "IC-discussion evidence on optimal hedge structure" |
| **2. Input contract known** | ✅ SATISFIED | Phase A §2: `--portfolio-csv` essential; price history / snapshot dir / options creds verified |
| **3. Inputs exist and fresh** | ✅ SATISFIED | Phase A §3: all green as of 2026-05-06 |
| **4. First-fire validated** | ✅ SATISFIED | B1b closure: hedge_report_2026-05-08 confirmed; live Massive endpoint verified |
| **5. Dashboard staleness banner designed** | ⏳ PENDING | This spec §1 |
| **6. Options-source validation confirmed** | ⏳ PENDING | This spec §2; acceptance = 2–3 reports with "massive" source |
| **7. CLI default repair scoped** | ⏳ PENDING | This spec §3; acceptance = auto-discovery works; explicit cron line still works |
| **8. Cadence formalized** | ⏳ PENDING | This spec §4; acceptance = Friday 18:00 ET documented in crontab |
| **9. Rollback path confirmed** | ⏳ PENDING | This spec §6; acceptance = reversible in <5 minutes |
| **10. No scoring/ranker/EV impact** | ✅ SATISFIED | Phase A §8; confirmed via grep |
| **11. Retention policy (optional) decision made** | ⏳ PENDING (OPTIONAL) | This spec §5; recommend deferring to Phase B3 |

---

## Out-of-Scope (Phase B2)

- **LLM consumer reactivation** — Spec 087C, separate decision
- **Bioshort alpha research** — Spec 087C, blocked on ≥4 fresh reports
- **Scoring/ranker/EV integration** — Never; governance evidence only
- **Dashboard UI redesign** — Phase B2 adds metadata; UI rendering deferred
- **Historical backfill** — Spec 092, separate track

---

## Related Specifications

- **Spec 087 Phase A** (2026-05-06) — Hedge-governance decision, disposition B
- **Spec 087 B1a** (shipped 2026-05-07) — CLI default repair + portfolio CSV fix
- **Spec 087 B1b** (shipped 2026-05-14) — First-fire validation + env setup
- **Spec 087 B2** (this spec, design-only) — Dashboard freshness + CLI defaults
- **Spec 087C** (held) — Bioshort alpha research (requires ≥4 fresh reports)
- **Spec 029** — Hedge-report governance framework (original)

---

## Implementation Plan (Phase B2 → Phase B3)

Phase B2 is a **design specification only**. Implementation will be a separate PR with:

1. Dashboard staleness banner code + tests
2. CLI default repair in `tools/biotech_hedge_report.py`
3. Cron wrapper updates (logging, pre-flight check)
4. Updated crontab comments
5. Integration test: mock fresh reports, verify dashboard response includes staleness indicator

---

## Governance

- **Phase B2 decision**: Dashboard freshness envelope necessary before LLM reactivation (Spec 087C)
- **Phase B2 + C dependency**: both ship before bioshort alpha research (Spec 087C)
- **Promotion path**: NONE. This is infrastructure/governance change, not alpha. No Checklist v2 required.
- **Authority level**: write_artifacts (dashboard), observe_and_propose (governance)

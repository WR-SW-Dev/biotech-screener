# Grok Biotech News Feed — Quality Audit (2026-04-26)

**AUDIT ARTIFACT ONLY** — no code changes, no file moves, no scoring/ranker changes, no `production_data` mutation. Cleanup/quarantine window still active until 2026-04-27 organic snapshot.

**Scope**: Grok biotech news feed treated as an unverified operator/context layer. Audit asks whether it can be **sharpened** (cleaner, less noisy, better triage flags) — not whether it can become alpha.

---

## Verdict (one line)

**broken-and-dormant** — the feed has no live producer (last run 2026-03-31, `XAI_API_KEY` missing since at least 2026-04-20), and the wiring between producer and consumer is broken on two axes (directory name + filename). Sharpening is premature; plumbing must be repaired first.

---

## Reality Check — what exists vs. what doesn't

```
artifacts/grok_watch/                        EXISTS, single stale day
  2026-03-31_alerts.json   (Mar 30 16:52)    131 alerts
  2026-03-31_alerts.md     (Mar 30 16:52)
  dedup_state.json         (Mar 30 16:52)
artifacts/grok_biotech_watch/                MISSING (consumer reads here)
artifacts/herald/                            MISSING (phantom — confirms 2026-04-20 finding)
```

Code surfaces present:
- `specs/changes/044_grok_news_feed_pipeline.md` ✓
- `specs/changes/036_grok_biotech_watch.md` ✓ (older spec)
- `common/news_feed_schema.py` ✓ (Apr 20)
- `common/news_feed_features.py` ✓ (Mar 31)
- `tests/test_news_feed.py` ✓ (Apr 20)
- `tools/build_grok_biotech_watch.py` ✓ (Apr 9, 27 KB) — the live producer
- `tools/build_intraday_mover_watch.py` ✓ — the consumer

---

## 13-Check Matrix

| # | Check | Answer | Evidence | Severity |
|--:|-------|--------|----------|---------:|
| 1 | Grok treated as SUPPORTING / unverified only? | **No** | `grok_watch/2026-03-31_alerts.json` records carry `official_confirmation: True` and `source_type: "official_company"` directly in Grok output. | material |
| 2 | Can Grok-only path become OFFICIAL? | **Yes — already does** | Same evidence as #1. Spec 063 rule "Grok-only evidence must never be labeled OFFICIAL" is violated by producer schema. | material |
| 3 | Stale/follow-on stories overcounted? | **Yes** | 131/131 sampled alerts in `2026-03-31_alerts.json` have `date` fields from 2023/2024 inside a file dated 2026-03-31 — these aren't follow-ons, they are retrospective hallucinations emitted at HIGH severity. No `new_or_stale` field is written. | material |
| 4 | Ticker aliases causing false matches? | **Cannot assess** | Producer ad-hoc schema has no `aliases_matched` field; collision-flag plumbing exists in `news_feed_schema.py:151` (`ticker_collision_flag`) but is unused by producer. | minor |
| 5 | Financing/M&A/sell-side/legal/safety/competitor classified cleanly? | **No** | Producer emits a single `topic` string and `catalyst_keyword_hit`. No `event_category` enum (the well-designed `EventCategory` in `news_feed_schema.py:15-25` is unused). | material |
| 6 | Informational-only updates excluded from material counts? | **No** | Producer writes neither `informational_only` nor `informational_reason`. All alerts go straight into severity counts at `build_grok_biotech_watch.py:686-688`. | material |
| 7 | Exogenous events excluded from calibration-like use? | **N/A in producer; correct in schema** | `news_feed_schema.py:118` defines `exogenous_to_primary_catalyst`; `is_clean_for_calibration()` (line 154) gates on it. Producer writes nothing here, so the gate cannot fire. | material |
| 8 | `event_outcome_guess` and `price_direction_guess` separated? | **In schema, yes; in producer, missing** | `OutcomeGuess` and `PriceGuess` enums (`news_feed_schema.py:47-60`) are correctly distinct. Producer emits neither. | material |
| 9 | `source_count` / `primary_source_kind` meaningful? | **No** | Producer writes a single `source` string ("alkermes.com", "businesswire.com"). No `source_count`, no `primary_source_kind`, no `source_urls`. Sample includes literal template padding ("ALMS Biotech Press Release"). | material |
| 10 | Dedupe keys stable across runs? | **Unverified — only one run on disk** | Producer uses a `topic_hash` (e.g. `"8741c5f58e0d36e4"`), not the schema's documented `dedupe_key = SHA256(ticker\|category\|subtype\|date\|primary_url)`. `dedup_state.json` exists but only one production day. | minor |
| 11 | Missing Herald → `UNKNOWN_SOURCE_STATE`? | **Yes — handled correctly** | `build_intraday_mover_watch.py:674-685` maps missing herald to the `UNKNOWN_SOURCE_STATE` review reason; the consumer does not silently trust Grok. | info (good) |
| 12 | `review_reason_codes` populated? | **No** | Producer writes none. The well-designed `ReviewReason` enum (`news_feed_schema.py:74-81`) is dead. | material |
| 13 | Tests cover semantic feed quality, not just schema? | **Schema-only** | `tests/test_news_feed.py` exercises Pydantic models that the producer does not use. No test asserts that `build_grok_biotech_watch.py` output conforms to the schema. | minor |

---

## Reconciliation Table — Grok vs Herald

**SKIPPED.** No Herald artifacts exist (`artifacts/herald/` missing) and the most recent Grok artifact is one stale day from 2026-03-31. There are no aligned trading days to reconcile.

---

## Top 10 Concrete Feed-Quality Issues (ranked by severity)

1. **Producer writes `official_confirmation` directly on Grok output.** `grok_watch/2026-03-31_alerts.json` records carry this flag from the Grok response. Spec 063 explicitly forbids it. *(Path: `tools/build_grok_biotech_watch.py` and the recorded artifact.)*
2. **Producer does not use `common/news_feed_schema.py`.** The Spec 044 schema defines the entire safety surface — `informational_only`, `exogenous_to_primary_catalyst`, `new_or_stale`, `event_outcome_guess`, `price_direction_guess`, `review_reason_codes`, `is_clean_for_calibration()`, `is_official_source()`. The schema is imported only by `tests/test_news_feed.py`. The producer emits an ad-hoc dict.
3. **Path drift (two axes) breaks producer→consumer wiring.** Producer writes `artifacts/grok_watch/{date}_alerts.json` (`build_grok_biotech_watch.py:11, 704`). Consumer reads `artifacts/grok_biotech_watch/{date}_watch.json` (`build_intraday_mover_watch.py:268, 334`). Different directory **and** different filename. Even with a live producer, the consumer would never see its output.
4. **Hallucinated dates emitted at HIGH severity.** Sample alert in `2026-03-31_alerts.json` describes ALKS 3831 Phase 3 success with `date: 2023-10-15` and `severity: HIGH`. ALKS 3831 was withdrawn after CRL in real life. The Grok response is fabricating events and the producer has no temporal sanity gate.
5. **No materiality gate.** Severity is a free-form `"HIGH"/"MEDIUM"/"LOW"` string written from the Grok response. The schema's `Materiality` enum + `informational_only` exclusion logic is unused.
6. **No ticker-collision check.** `news_feed_schema.py:151` defines `ticker_collision_flag` and `collision_severity`; the producer does not consult `tools/classify_press_releases.py` collision logic.
7. **No `event_category` taxonomy.** `EventCategory` enum is unused; producer emits a free-text `topic` like `"Phase 3 readout"` or `"FDA approval"`.
8. **`dedupe_key` divergence.** Schema specifies `SHA256(ticker|category|subtype|date|primary_url)`. Producer writes a 16-char `topic_hash` — collision risk on similar topics across tickers, no URL anchor.
9. **`XAI_API_KEY: MISSING` since at least 2026-04-20.** The agent runs are heartbeat-only — no new artifacts since 2026-03-31. The dashboard, if any, has been silently empty for ~26 days.
10. **No producer→schema validation in tests.** `tests/test_news_feed.py` validates schema models in isolation; no test loads a real producer artifact and validates conformance. CI would not catch the schema drift documented in #2.

---

## False-Positive / False-Negative Examples (from the only live artifact)

**False positive (hallucination, HIGH severity)** — `artifacts/grok_watch/2026-03-31_alerts.json`:
> ALKS, "Alkermes Announces Topline Results from Phase 3 Study of ALKS 3831 for Schizophrenia", `date: 2023-10-15`, `severity: HIGH`, `official_confirmation: True`, `source: alkermes.com`. ALKS 3831 received a CRL in real life; the trial described did not produce this outcome.

**False positive (wire-service rumor flagged HIGH)** — same file:
> ALKS, "Alkermes Receives FDA Approval for ALKS 4230 in Combination Therapy", `date: 2023-09-20`, `severity: HIGH`, `source_type: wire_service`. ALKS 4230 (nemvaleukin) is a Phase 2 oncology asset — there is no such approval.

**False negative**: not assessable — the only artifact is hallucinated, so we cannot test recall against ground truth.

---

## Proposed Minimal Patch List (do not implement without approval)

| # | Bucket | File | Change | Why minimal |
|--:|--------|------|--------|-------------|
| P1 | source hierarchy | `tools/build_grok_biotech_watch.py` | Strip/override `official_confirmation` and `source_type:"official_company"` from Grok responses; force `primary_source_kind` to `NEWS` or `OTHER` for Grok-only items. | One-line policy clamp; preserves Spec 063 invariant. |
| P2 | schema validation | `tools/build_grok_biotech_watch.py` | Replace ad-hoc dict with `NewsEvent` from `common/news_feed_schema.py`; persist `NewsFeedBatch.model_dump()`. | Schema already exists. |
| P3 | dedupe/staleness | `tools/build_grok_biotech_watch.py` | Reject any record where `date < as_of_date - 14d` or where `date` parses to a year outside `[as_of_year-1, as_of_year]`. | Catches the 2023/2024 hallucination class. |
| P4 | path drift | producer + consumer | Pick one: either move producer output to `artifacts/grok_biotech_watch/{date}_watch.json`, or change consumer paths in `build_intraday_mover_watch.py:268, 334`. | One-line fix on either side; pick consumer rename to avoid disturbing dedupe-state file. |
| P5 | review_reason_codes | producer | Populate `review_reason_codes` (LOW_CONFIDENCE, INFORMATIONAL_AMBIGUOUS, POSSIBLE_EXOGENOUS, TICKER_ALIAS_CONFLICT) using simple keyword + confidence rules. | Triage signal for operators, no scoring impact. |
| P6 | prompt tightening | producer | Add prompt clauses: "Do not include events older than 14 days from the run timestamp." "Do not assert official confirmation unless the source is the company IR page, SEC, FDA, or exchange." | Pure prompt, zero code surface. |
| P7 | operator display | producer markdown formatter | Add a "REVIEW" banner block; suppress `official_confirmation: true` from Grok-only items in the digest. | Surface change only. |

**Out of scope (do not patch)**: any DEM/CRT/Event-EV integration, any ranker change, any `production_data` mutation.

---

## Tests to Add Before Any Patch

1. **`test_producer_emits_schema_conformant_records`** — load a real artifact (or a fixture mimicking one), `NewsFeedBatch.model_validate(...)` must pass.
2. **`test_grok_only_records_are_not_official`** — `NewsEvent.is_official_source()` returns `False` for any record whose `primary_source_kind` originates from a Grok-only path.
3. **`test_stale_dates_are_rejected`** — fixture with `date` 60 days before `as_of_date` is dropped or marked `STALE` + `needs_review=True`.
4. **`test_path_drift_regression`** — assert producer output filename pattern matches the consumer's lookup pattern in `build_intraday_mover_watch.py`.
5. **`test_dedupe_key_stability`** — same `(ticker, category, subtype, date, primary_url)` produces the same `dedupe_key` across two runs.
6. **`test_missing_herald_yields_unknown_source_state`** — the existing handling at `build_intraday_mover_watch.py:674-685` is correct; lock it in with a regression test.

---

## Final Recommendation

**Defer.** The feed is not a sharpening problem — it is a plumbing-and-fidelity problem.

- The schema is good (`common/news_feed_schema.py` is well-designed, Spec 063-aligned, and ready to use).
- The producer ignores it. Until P2 + P4 are merged (schema adoption + path fix), there is no quality surface to "sharpen."
- The current artifact is one stale day of hallucinations; sharpening prompts before fixing the schema-emitter and path-drift bugs would be polishing a disconnected pipe.

**Suggested sequence** (post-2026-04-27, after cleanup window closes):
1. Decision: keep Grok feed alive, or retire. If retired, follow Spec 063 path-drift fix as a deletion.
2. If kept: P4 (path drift) → P2 (schema adoption) → P1 (no-OFFICIAL clamp) → P6 (prompt tightening) → P3 (date sanity) → P5 (review codes) → P7 (operator display). Each gated by the tests above.
3. Restore `XAI_API_KEY` and re-run the producer **only after** P1+P3 clamp hallucinations.

Until then: the dashboard should display "news feed offline" rather than show stale hallucinations.

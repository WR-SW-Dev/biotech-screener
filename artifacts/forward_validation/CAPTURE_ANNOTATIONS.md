# Capture annotations — SM-20260629-001

Out-of-band notes on individual forward-validation captures.

`captures.jsonl` is append-only evidence of record and is **never edited retroactively**
(CCFT: frozen once written). Where a capture needs a caveat, it is recorded here against
its date rather than by mutating the record. An annotation is commentary — it does not
change `eligible_for_mandate` or `quality_status`, and any consumer that filters on those
fields will still see whatever the pipeline wrote.

---

## 2026-08-06 — captured mid-session, after seven failed production runs

**The record says:** `capture_mode=LIVE`, `eligible_for_mandate=true`, `quality_status=PASS`,
`captured_at_utc=2026-08-06T19:11:34Z` (15:11 ET), `effective_price_date=2026-08-06`,
`xbi_price_at_capture=154.59`, `n_universe=299`.

**What is unusual.** Daily production failed seven consecutive times on this date before
succeeding — twice from an unlisted `split_adj_freshness` gate (#549) and five times from
219 spurious CRITICAL audit violations caused by a blank `eligible` cell (#555). Both were
fixed the same day (PR #23). The successful run started 14:45 ET and promoted at 14:52, so
the capture landed at 15:11 ET, roughly 49 minutes before the close.

`xbi_price_at_capture=154.59` is therefore an **intraday quote, not a settled close**.

**What is *not* unusual, and why this is a caveat rather than a disqualification.**
Mid-session same-day captures already have precedent in this ledger and have been accepted:

| date | captured (ET) | effective_price_date | verdict |
|------|---------------|----------------------|---------|
| 2026-07-30 | 01:29 | 2026-07-29 (prior-day) | eligible / PASS |
| 2026-07-31 | 10:49 | 2026-07-31 (**same-day**) | eligible / PASS |
| 2026-08-03 | 09:14 | 2026-07-31 (prior-day) | eligible / PASS |
| 2026-08-04 | 09:26 | 2026-08-03 (prior-day) | eligible / PASS |
| 2026-08-05 | 09:50 | 2026-08-05 (same-day) | **ineligible / DEGRADED** |
| 2026-08-06 | 15:11 | 2026-08-06 (**same-day**) | eligible / PASS |

2026-07-31 is the direct precedent: same-day, mid-session, accepted. So the price basis
here is not novel. What is novel is only *how late* in the session it was taken — 15:11 ET
is the latest capture point in the recent set.

**How to use it.** Treat 2026-08-06 as usable evidence. The caveat is narrow: do not treat
its entry price as equivalent to a settled close when computing anything timing-sensitive,
and be aware that the recent window mixes three different bases (prior-day close, early
mid-session, late mid-session). If an analysis is sensitive to entry timing, exclude it or
stratify — do not silently pool it with the 09:xx prior-day captures.

**Not asserted.** No claim is made that this capture is biased in either direction. The
basket and XBI are priced at the same instant, so the excess figure is internally
consistent; the concern is comparability across captures, not internal validity.

**Related:** PR #23 (both production fixes), commit `f8a18a7d` (08-03/04/05 captures).
#555 still writes a blank `eligible` rather than `eligible=0`; deferred as an eligibility
change under the NO_MODEL_CHANGE window.

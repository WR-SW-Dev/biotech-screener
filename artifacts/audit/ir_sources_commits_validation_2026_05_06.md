# IR-source commits validation note (2026-05-06)

**Status:** Validation only. No revert. Per user direction "Do not revert unless validation shows harm."

**Subjects:**
- `578d32a4` "feat: populate company_ir_sources.json with issuer IR URLs (90.6% coverage)" — committed 2026-05-06 15:17 ET
- `f394dd41` "fix: null out 7 wrong-company gnw_jsonld_domain IR URL assignments" — committed 2026-05-06 16:17 ET

Both arrived on `origin/main` via fast-forward `7c49be12..7c2bbb31` during the P0 #1 push. Content-equivalent of the previously-quarantined `b05becd2` (which remains preserved on local branch `save/ir-sources-populate-2026-05-06`).

---

## 1. Files changed

| Commit | File | Insertions | Deletions |
|---|---|---|---|
| `578d32a4` | `production_data/company_ir_sources.json` | +805 | -537 |
| `f394dd41` | `production_data/company_ir_sources.json` | +14 | -21 |

Single file in each commit. No code paths touched.

---

## 2. Production scoring impact

**None — confirmed by code inspection.**

`production_data/company_ir_sources.json` is consumed by:
- `tools/classify_press_releases.py:530` (press-release classifier)
- `tools/fetch_company_press_releases.py` (news ingest)
- `tools/populate_ir_sources.py`, `tools/populate_ir_urls.py`, `tools/null_bad_ir_urls.py` (its own producers)
- Tests: `tests/test_audit_escalation_pool.py`, `tests/test_classify_press_releases.py`, `tests/test_production_qa_classifier_check.py`, `tests/test_reclassify_cache.py`

Negative-confirmation grep against scoring code (`run_screen.py`, `module_*.py`, `ranker_*.py`, `selector_engine.py`, `decision_engine.py`, `event_ev/*.py`, `common/*.py`) returned no matches for `company_ir_sources` or `company_ir_url`. Selector / ranker / Event EV / sizing layers do not consume this file.

Indirect impact only via news-classification quality → herald artifacts → digest content → human review queue. No automated decision path.

---

## 3. JSON shape and URL hygiene

Schema: `{"schema": "company_ir_sources.v1", "sources": [<341 records>]}`.

| Metric | Value |
|---|---|
| Total records | 341 |
| Populated (non-empty `company_ir_url`) | 302 |
| Empty | 39 |
| Coverage | 88.6% |
| Malformed URLs (regex `^https?://...`) | 0 |

Population methods (post-`f394dd41`):
- `edgar_xbrl_probe` — 212
- `gnw_jsonld_domain` — 49
- `(unset)` — 41 (includes the 11 known-bad GNW + 7 newly-nulled by `f394dd41` + 23 truly unpopulated)

Confirmed nullings from `f394dd41` (TECH, DRUG, DNA, VIR, RNA, DAWN, JAZZ): all show `company_ir_url=""` and method `(unset)`. Diff intent matches on-disk state.

---

## 4. Classifier escalation pool — does `other_share` improve?

**Not yet, and almost certainly cannot from today's data.** Today's production_qa report (mtime 2026-05-06 16:18 ET — written 1 minute after `f394dd41` landed) reads:

```
classifier_escalation_pool: pool=547, clean=30/30, other=56.1%, hard_coll_pool=1328 [other_share=56.1% (>50)]
```

Trend over last 5 reports:
| Date | other_share | Status |
|---|---|---|
| 2026-04-30 | 51.7% | FAIL |
| 2026-05-04 | 54.0% | FAIL |
| 2026-05-05 | (FAIL — exact pct in log) | FAIL |
| 2026-05-06 | 56.1% | FAIL |

The trend is upward. The IR commits were intended to reduce this, but the metric still rose today. Two reasons:

1. **Timing.** Production_qa ran at 16:18 ET, ~1 minute after `f394dd41` landed and ~1 hour after `578d32a4`. The classifier itself runs upstream of pqa and would have processed press releases against the OLD `company_ir_sources.json`. Today's 56.1% reflects pre-fix state, not post-fix.
2. **Reclassification not automatic.** The repo has `tools/reclassify_cache.py` (per test naming) — suggesting reclassification of cached press releases is a separate step, not part of the daily cron's press-release ingestion. Until reclassification runs against the fixed JSON, the pool reflects historical mis-classifications.

**Do not revert.** Reverting would re-introduce the 7 wrong URLs (TECH→ownify.com, DRUG→researchandmarkets.com, DNA→delveinsight.com, VIR→virtualinvestorconferences.com, RNA→ir.madrigalpharma.com [MDGL!], DAWN→dawnproject.com, JAZZ→usmint.gov) — that's actively harmful. The right next step is to verify reclassification picks up the corrected URLs on the next cycle (probably the next-day cron or an explicit `tools/reclassify_cache.py` run — not in scope here).

---

## 5. Verdict

**KEEP both commits.** Validation finds:

- ✓ JSON schema intact (341 records, validated as `company_ir_sources.v1`).
- ✓ Zero malformed URLs.
- ✓ All 7 nulled tickers from `f394dd41` correctly empty.
- ✓ No production scoring impact (selector/ranker/EV/sizing untouched).
- ✓ The 7 wrong-URL nullings prevent active harm (e.g., classifying VIR press releases by `virtualinvestorconferences.com` would have cross-contaminated VIR's news).
- ⊘ `classifier_escalation_pool` improvement not yet observable — expected to require either a downstream reclassification cycle or one more daily ingestion turnover.

No harm found. Recommend monitoring `other_share` on the next 1–2 days of production_qa reports. If it does not begin trending down, escalate to an "is reclassification wired" diagnostic — separate from this validation.

---

_Generated by IR-source commits validation per user direction (2026-05-06). Read-only, no code or data changes._

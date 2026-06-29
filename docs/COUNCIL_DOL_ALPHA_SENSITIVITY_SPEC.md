# IC Council Alpha-Sensitivity Revision — Decision Outcome Ledger + Edge Advocate

**Status:** DRAFT — awaiting operator approval
**Date:** 2026-06-29
**Classification:** `COUNCIL_GOVERNANCE_SPEC_REVISION / DECISION_LEDGER_CALIBRATION / NO_MODEL_CHANGE / NO_RANKER_CHANGE / NO_SELECTOR_CHANGE / NO_SIZING_CHANGE / NO_TRADING_CHANGE`

---

## 0. Why this exists

The biotech IC council is structurally anti-false-positive. All five seats exist to reject a bad merge. None exists to catch a false negative — a real edge discarded because it is noisy, concentrated, or inconvenient.

The DEM finding is the canonical example: +7.9 pp/mo 2025+ excess that is rally-concentrated. Five skeptic seats correctly refuse to promote it to production. But without an advocate mechanism, no seat is required to ask: "should this be shadow-tracked as a valid rally-participation engine, sized accordingly, rather than simply parked?"

A second structural gap: the recursive loop currently learns from review debates (process LRN entries) but not from whether past council calls were right about the market. A promotion gate that cannot tell you whether its holds and rejects made or lost money is itself an unvalidated model — the exact thing it forbids in others.

This spec closes both gaps with the minimum viable changes:

1. **Edge advocate (rotating role)** — assigned per-review on alpha/model/backtest-claim reviews; argues the strongest good-faith case the signal is real; forces false-negative challenge and forward-shadow mandate when evidence is promising but insufficient.

2. **Decision Outcome Ledger (DOL)** — append-only artifact recording every IC recommendation and its later-resolved outcome; makes the loop learn from money, not just process.

---

## 1. Hard constraints

Do not change:

- model logic, ranker, selector, final_score, sizing, trading behavior
- production defaults, cron, live action card behavior
- investability gate thresholds
- stress-wrapper trading behavior

No new autonomous workflow. No new resolution cron. No live Top-30 narrative review. No production hooks.

This spec updates only:

- council governance documentation
- council skill/spec text (`skills/biotech-ic-council/SKILL.md`)
- DOL schema/protocol (`skills/biotech-ic-council/references/decision-outcome-ledger.md`)
- initialized empty ledger (`artifacts/ic_council/decision_outcome_ledger.jsonl`)
- Town mirror (`docs/hermes_skills/biotech-ic-council.md`)

---

## 2. Edge advocate (rotating role)

### 2.1 What it is

A per-review role, not a permanent sixth seat. Activated only on reviews where the triage gate returns YES on `alpha/model` or `backtest claim`.

Assignment is deterministic rotation through seats 1→2→3→4→5→1, or chair assignment when one seat is already the natural counterpart to the skeptic. Record the assigned seat number in the DOL row.

### 2.2 Why rotation, not a fixed seat

A fixed advocate becomes ceremonial — the council learns to discount a voice that always argues bull. Rotation means any seat may hold the role, the assignment is auditable, and no seat can coast on its permanent stance.

### 2.3 Authority

The advocate may:

- argue the strongest good-faith case the signal is real
- identify the conditioning under which a concentrated or noisy edge is usable (regime, horizon, sizing posture, risk wrapper)
- flag when the council is about to reject something valid-but-inconvenient
- require a forward-shadow mandate when evidence is promising but insufficient
- recommend: `FORWARD_SHADOW_MANDATE`, `CONDITIONAL_EDGE_TRACKING`, `REGIME_CONDITIONED_TRACKING`, `RISK_WRAPPER_TRACKING`, `REJECT_BUT_LOG_FALSE_NEGATIVE_RISK`

The advocate may not:

- approve production changes
- override gates
- change ranker, selector, or sizing
- recommend trading

### 2.4 Required questions

The advocate must address all of these before the cross-examination round:

1. What is the strongest case this signal is real?
2. What condition would make the edge usable (regime, horizon, sizing posture, risk wrapper)?
3. Is the council confusing conditional/noisy alpha with no alpha?
4. What forward-shadow test would prove or disprove the edge within the evaluation window?
5. What would we regret discarding if this later proves correct?
6. Is the evidence still insufficient — and if so, what is the minimum viable test before the next review?

### 2.5 DEM worked example

Alpha skeptic (correct): "+7.9 pp/mo 2025+ is rally-concentrated, top-5 months = 100% of alpha — not production-ready."

Edge advocate (required counter): "Agreed it is not cross-sectional alpha, but it is a coherent rally-participation engine. The correct disposition is not REJECT but FORWARD_SHADOW_MANDATE: track frozen Top-30 bootstrap percentile vs random baskets across 20 completed weekly windows. If percentile stays >75 net-of-costs, that is investable as regime-conditioned convexity, not core holding."

The reframing — valid edge, wrong-if-discarded, right-if-conditioned — is what five skeptic seats cannot produce on their own.

---

## 3. Decision Outcome Ledger (DOL)

The DOL is the council's own forward-validation record. Full schema, evaluation window taxonomy, resolution authority rules, and calibration metrics are in:

`skills/biotech-ic-council/references/decision-outcome-ledger.md`

Key design decisions summarized here:

### 3.1 Evaluation window taxonomy

Every row must be classified as one of four window types, to prevent `unobservable` from catching too many rows:

| Type | When to use | Due date |
|------|------------|---------|
| `EVENT_ANCHORED` | Natural resolution event exists (catalyst, FDA date, filing) | Event date + observation buffer |
| `MODEL_EVALUATION` | Requires accumulating forward windows or checkpoint | Date when required windows complete |
| `OPEN_ENDED` | No natural window; requires manual scoping | Next manual review checkpoint |
| `OPERATIONAL` | CI, pipeline, schema, or production run completion | Next verification cycle |

### 3.2 Resolution authority

Town may generate proposed outcome stamps. Existing trackers (PDUFA/Catalyst, Earnings Post-Mortem) provide evidence. Human/operator must commit resolved outcome fields to the repo. Town mirror rows are not authoritative unless committed.

No new resolution cron. Reuse existing trackers.

### 3.3 Outcome field rules (summary)

- `call_correct = mixed` → `outcome_notes` + `resolved_components` + `unresolved_components` required
- `call_correct = unobservable` → `unobservable_reason` + `next_review_due` required
- `call_correct = true | false` → `outcome_evidence_refs` required
- Window extension → `extension_reason` + `prior_due_date` + `new_due_date` + `operator_confirmed = true` required

### 3.4 Calibration metrics

Compute at each monthly Self-Learning Loop Review:

- `flip_rate` — council sometimes declines/qualifies (proves it is load-bearing)
- `hold_precision` / `reject_precision` — council's caution was right (proves it is calibrated)
- `false_negative_catch_rate` — of advocate-flagged risks, % that later showed positive shadow evidence
- `unobservable_rate` — flag if >30% of closed rows
- `ledger_readability` — schema completeness rate

The `false_negative_catch_rate` is operationalized as:

> Of rows where `edge_advocate_false_negative_risk_flag = true`, what percentage later showed `forward_shadow_result` indicating positive evidence within the evaluation window?

Not defined as a counterfactual. Defined as: did the shadow test we ran confirm the advocate's claim?

---

## 4. Recommendation taxonomy

The full recommendation set for Step 8 of the council review:

| Recommendation | Meaning |
|---------------|---------|
| `APPROVE` | Evidence sufficient, blast radius controlled |
| `RESEARCH_ONLY` | Useful diagnostic, not production-approved |
| `PLUMBING_ONLY` | Coverage/observability improvement, no alpha claim |
| `HOLD` | Promising but missing required proof |
| `REJECT` | Harmful, misleading, leaky, or outside mandate |
| `NO_CONSENSUS` | Irreducible disagreement; escalate to operator |
| `FORWARD_SHADOW_MANDATE` | Evidence promising but insufficient; measurable forward test required; no production change |
| `CONDITIONAL_EDGE_TRACKING` | Signal real only under specific conditions; track with explicit condition labels and forward validation |

`FORWARD_SHADOW_MANDATE` and `CONDITIONAL_EDGE_TRACKING` do not change production behavior. They create a structured observation record only.

---

## 5. Forward-shadow mandate structure

When the recommendation is `FORWARD_SHADOW_MANDATE` or `CONDITIONAL_EDGE_TRACKING`, the council must emit a structured shadow mandate alongside the DOL row. Required fields:

```
shadow_mandate_id:         SM-YYYYMMDD-NNN (assigned at review time)
signal_or_claim:           one-line statement of what is being tracked
why_not_approved:          specific reason production promotion was not granted
why_not_rejected:          specific reason outright rejection was not appropriate
hypothesis:                falsifiable claim that the shadow test will test
primary_metric:            the one number that determines success or failure
secondary_metrics:         supporting metrics
comparison_group:          what the signal is measured against
evaluation_window_type:    (must match DOL row)
evaluation_window_due:     date by which the test should conclude
success_threshold:         explicit condition for graduation to further review
failure_threshold:         explicit condition for closing as not useful
data_required:             what needs to be observable/logged
artifact_location:         where results are stored
operator_owner:            who is responsible for the resolution pass
```

The DEM worked example (from the design discussion):

```
shadow_mandate_id:         SM-20260629-001
signal_or_claim:           DEM YTD Top-30 excess appears selection-driven vs random biotech baskets
why_not_approved:          YTD/in-sample/gross-of-costs; forward windows not yet mature
why_not_rejected:          Bootstrap control places model ~99th percentile vs random baskets
hypothesis:                Frozen Top-30 will continue to outperform random same-universe baskets
                           on forward captures net of costs
primary_metric:            forward bootstrap percentile
secondary_metrics:         net weekly excess vs XBI, hit rate by regime
comparison_group:          random same-universe baskets (matched size)
evaluation_window_type:    MODEL_EVALUATION
evaluation_window_due:     20 completed weekly captures
success_threshold:         percentile >75 and positive net excess across 20 completed windows
failure_threshold:         percentile ≤50 or negative net excess after sufficient windows
data_required:             weekly Top-30 forward captures in artifacts/rank_depth_shadow/
artifact_location:         artifacts/dem_shadow/dem_bootstrap_shadow.csv
operator_owner:            human operator
```

---

## 6. Deliverables

| # | Deliverable | Path | Class |
|---|-------------|------|-------|
| D1 | DOL schema + protocol doc | `skills/biotech-ic-council/references/decision-outcome-ledger.md` | doc-only |
| D2 | SKILL.md patch — edge advocate, recommendation taxonomy, DOL reference | `skills/biotech-ic-council/SKILL.md` | skill patch (process) |
| D3 | Empty ledger initialized | `artifacts/ic_council/decision_outcome_ledger.jsonl` | artifact (empty) |
| D4 | Overarching spec | `docs/COUNCIL_DOL_ALPHA_SENSITIVITY_SPEC.md` | doc-only |
| D5 | Town mirror refreshed | `docs/hermes_skills/biotech-ic-council.md` | mirror refresh |
| D6 | Resolution-stamp note in PDUFA + Earnings trackers | Town routine prompts | Town-side, observe-only |
| D7 | DOL calibration metrics in Loop Review | Town routine prompt | Town-side, observe-only |

D1–D5 are repo writes and included in this commit. D6–D7 are Town-side and applied separately after operator approval.

---

## 7. Deferred (not in this spec)

These are proposals only. They depend on the DOL existing and being calibrated first:

- **Forward-shadow mandate as automatic council output** — requires DOL to resolve rows before we know if mandates are useful
- **Standing live Top-30 review** — pointing an un-calibrated council at live positions produces narrative, not decisions; revisit after ≥3 months of resolved DOL rows
- **Automatic tier promotion** — out of scope
- **Automatic manager reweighting** — out of scope
- **Automatic EES veto or stress-wrapper substitution** — out of scope
- **LangGraph implementation** — out of scope

---

## 8. Sequencing

1. Operator reviews and approves this spec (this doc).
2. D1–D5 are committed in this PR (docs/schema/mirror only).
3. Apply D6–D7 Town-side immediately (observe-only, no CI dependency).
4. First efficacy read at the next monthly Self-Learning Loop Review.
5. Full calibration read at ~2–3 months.
6. Revisit deferred items only after the DOL shows the council is calibrated.

---

## 9. Governance conclusion

This revision makes the council more alpha-sensitive by forcing promising conditional edges into measurable forward-shadow validation. It does not approve, promote, trade, re-rank, resize, or change production behavior. The council still recommends; the operator still decides; nothing here touches final_score, ranker, selector, sizing, cron, or live execution.

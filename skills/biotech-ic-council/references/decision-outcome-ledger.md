# Decision Outcome Ledger — Schema and Protocol

Use this reference when writing DOL rows after a council review, setting evaluation windows, performing resolution passes, or computing calibration metrics.

The ledger records every IC Council recommendation and its later-resolved outcome. It is the council's own forward-validation record — the same discipline the council demands of any alpha claim, applied to the council itself.

**Location:** `artifacts/ic_council/decision_outcome_ledger.jsonl`
**Format:** append-only JSONL; one object per council recommendation
**Authority:** repo-committed rows are authoritative. Town-generated stamps are proposals only until committed.

---

## Row schema

```jsonc
{
  // --- set at review time ---
  "decision_id": "ICD-YYYYMMDD-NNN",
  "review_date": "YYYY-MM-DD",
  "trigger": "pr | proposal | live_review | postmortem",
  "subject": "<one line — what was reviewed>",
  "classification": ["alpha/model", "..."],
  "blast_radius": "<from Restatement gate>",
  "recommendation": "<see Recommendation values>",

  // --- edge advocate fields (set at review time) ---
  "edge_advocate_assigned": false,
  "edge_advocate_seat": null,
  "edge_advocate_position": "support | partial | oppose | not_applicable",
  "edge_advocate_false_negative_risk_flag": false,
  "skeptical_majority_position": "<one line>",
  "forward_shadow_mandate_created": false,
  "forward_shadow_mandate_id": null,
  "forward_shadow_metric": null,

  // --- narrative fields (set at review time) ---
  "dissent_summary": "<one line — strongest credible counter>",
  "alpha_thesis": "<one line>",
  "risk_thesis": "<one line>",

  // --- evaluation window (council proposes; operator confirms) ---
  "evaluation_window_type": "EVENT_ANCHORED | MODEL_EVALUATION | OPEN_ENDED | OPERATIONAL",
  "evaluation_window_start": "YYYY-MM-DD",
  "evaluation_window_due": "YYYY-MM-DD",
  "evaluation_window_basis": "<description — what determines the window>",
  "set_by": "council",
  "operator_confirmed": false,

  // --- filled only by resolution pass, never at review time ---
  "outcome_status": "pending",
  "call_correct": null,
  "outcome_notes": null,
  "resolved_components": null,
  "unresolved_components": null,
  "unobservable_reason": null,
  "next_review_due": null,
  "outcome_evidence_refs": null,
  "extension_reason": null,
  "prior_due_date": null,
  "new_due_date": null,
  "forward_shadow_result": null,
  "advocate_call_resolved_correct": null,
  "resolved_date": null
}
```

**PIT discipline:** All outcome fields must be `null` at review time. They are written only by the resolution pass after `evaluation_window_due`. A non-null outcome field on a `pending` row is a leakage bug.

---

## Recommendation values

```
APPROVE
RESEARCH_ONLY
PLUMBING_ONLY
HOLD
REJECT
NO_CONSENSUS
FORWARD_SHADOW_MANDATE
CONDITIONAL_EDGE_TRACKING
```

---

## Evaluation window taxonomy

Every row must classify its evaluation window. Use the most specific type that applies.

### EVENT_ANCHORED

A natural resolution event exists: clinical data readout, FDA action date, filing deadline, financing close, M&A close, corporate action, or known forward price observation window.

- `evaluation_window_due` = natural event date + appropriate observation buffer (typically 5–20 trading days)
- Reuse the PDUFA/Catalyst Resolution Tracker as resolution evidence where available.

### MODEL_EVALUATION

Resolution depends on accumulating model evidence over predefined windows: 20/40/52 weekly forward windows, quarterly IC checkpoint, bootstrap percentile, net-of-cost validation, regime-stratified forward return.

- `evaluation_window_due` = date by which the required number of windows will have accumulated, or the explicit quarterly checkpoint date
- `evaluation_window_basis` must state the required window count or checkpoint criteria (e.g., "20 completed weekly captures with forward return observable")

### OPEN_ENDED

No natural resolution window exists yet. Manual scoping is required before the row can be scored.

- `evaluation_window_due` = next manual review checkpoint date, not a final scoring date
- Overuse of OPEN_ENDED is a red flag; most reviews have a scorable window
- The monthly Self-Learning Loop Review should convert OPEN_ENDED rows to a typed window or mark them permanently unobservable

### OPERATIONAL

Resolution depends on CI health, artifact generation, data pipeline run status, coverage verification, schema validation, or production run completion.

- `evaluation_window_due` = next CI/prod/artifact verification cycle or explicit run date
- `evaluation_window_basis` should name the artifact or check (e.g., "`artifacts/ic_council/decision_outcome_ledger.jsonl` populated after first CI-green run")

---

## Evaluation window governance

The council proposes the window. The operator confirms or edits it. The repo-committed row is authoritative.

```
Rule: operator_confirmed must be set to true before the row is treated as authoritative.
Rule: A row with operator_confirmed = false is a draft.
Rule: Do not score a row against a window the operator has not confirmed.
```

If the operator has not responded within the natural review cycle, the council may note `operator_confirmed = false` and flag it in the monthly Loop Review.

---

## Outcome field rules

### `call_correct` allowed values

```
true
false
mixed
unobservable
pending
```

### Constraints

```
if call_correct = mixed:
  outcome_notes required (non-null, substantive)
  resolved_components required (list of what resolved)
  unresolved_components required (list of what remains open)

if call_correct = unobservable:
  unobservable_reason required (why the window cannot be scored)
  next_review_due required unless permanently unobservable
  (permanently unobservable must be stated in outcome_notes)

if call_correct = true or false:
  outcome_evidence_refs required (pointer to artifact, log, snapshot, or tracker entry)

if evaluation_window_extension needed:
  extension_reason required
  prior_due_date required
  new_due_date required
  operator_confirmed must be set to true on the extension
```

Do not commit a bare `mixed` without `resolved_components` and `unresolved_components`. Do not commit a bare `unobservable` without `unobservable_reason`.

---

## Resolution authority

Town-side tools (PDUFA tracker, Earnings Post-Mortem tracker, monthly Loop Review) may generate proposed outcome stamps. These proposals are not authoritative until committed to the repo.

```
Rule: Town generates proposed stamps → operator reviews → human commits to repo.
Rule: Town mirror rows are not authoritative unless mirrored via reviewed commit or PR.
Rule: Resolution pass is read-only until operator commits the outcome update.
Rule: Do not create a new resolution cron. Reuse existing trackers as evidence sources.
```

Resolution sources in priority order:
1. PDUFA/Catalyst Resolution Tracker (for EVENT_ANCHORED rows tied to clinical/regulatory events)
2. Biotech Earnings Post-Mortem Tracker (for event-anchored earnings windows)
3. Forward shadow artifact at `forward_shadow_mandate_id` location (for FORWARD_SHADOW_MANDATE rows)
4. Monthly Self-Learning Loop Review (for MODEL_EVALUATION and OPEN_ENDED rows)
5. Manual operator stamp (for any row the above cannot resolve)

---

## Edge advocate tracking fields

These fields capture the advocate's call and its later resolution. They are the basis for the false-negative catch-rate metric.

```
edge_advocate_assigned:         was the role assigned for this review?
edge_advocate_seat:             which seat held the role (1–5)?
edge_advocate_position:         support | partial | oppose | not_applicable
edge_advocate_false_negative_risk_flag: did the advocate flag this as a false-negative risk?
skeptical_majority_position:    one-line summary of the majority position the advocate challenged
forward_shadow_mandate_created: was a shadow mandate emitted as a result?
forward_shadow_mandate_id:      ID or path of the shadow mandate artifact
forward_shadow_metric:          the primary metric the shadow mandate tracks
forward_shadow_result:          outcome of the shadow test (filled at resolution time)
advocate_call_resolved_correct: did the advocate's position later prove correct? (true/false/mixed/unobservable)
```

---

## Calibration metrics

Compute these at each monthly Self-Learning Loop Review from resolved rows.

| Metric | Definition |
|--------|-----------|
| `flip_rate` | % of full-council decisions later resolved as wrong or materially qualified |
| `hold_precision` | % of HOLD decisions that avoided bad production changes or generated useful forward evidence |
| `reject_precision` | % of REJECT decisions that stayed correctly rejected after evaluation |
| `advocate_resolution_rate` | % of edge-advocate support/partial calls that resolved correct, mixed-positive, or useful |
| `false_negative_catch_rate` | % of advocate-flagged false-negative-risk rows where forward-shadow evidence was later positive |
| `unobservable_rate` | % of rows that cannot be scored (flag if >30% of closed rows) |
| `mixed_rate` | % of rows marked mixed (high rates suggest outcome definitions need tightening) |
| `ledger_readability` | schema completeness rate: % of resolved rows with all required fields populated |

### False-negative catch rate — operational definition

Do not define as a counterfactual. Measure as:

> Of rows where `edge_advocate_false_negative_risk_flag = true`, what percentage later showed `forward_shadow_result` indicating positive evidence within the evaluation window?

If advocate calls often produce positive shadow evidence → the council was previously at risk of discarding real conditional alpha.

If advocate calls never resolve correct after ≥10 resolved rows → the role may be ceremonial or overfitting-prone; flag for demotion review in the Loop Review.

---

## Success criteria (evaluate at 2–3 months)

```
flip_rate > 0 or meaningful qualifications in resolved rows
unobservable_rate not excessive (< 30% of closed rows)
mixed rows have non-null resolved_components and unresolved_components
at least one advocate call resolves as useful or correct
no new unauthorized cron or autonomous process spawned
council calibration is measurable from repo artifacts
```

## Failure criteria (flag for redesign)

```
advocate role never changes council framing
no FORWARD_SHADOW_MANDATE rows created in first 3 months
all rows remain pending or unobservable after 6 months
ledger becomes unreadable (missing required fields on resolved rows)
process creates filing overhead with no improved alpha learning
```

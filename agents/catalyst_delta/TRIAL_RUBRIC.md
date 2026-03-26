# Catalyst Delta — 5-Day Trial Rubric

## Purpose

Objective go/no-go criteria for promoting `catalyst_delta` from manual to cron.
Run manually each trading day for 5 consecutive days. Score each run against
the rubric below. Promote to cron only if all criteria pass on >=4 of 5 days.

## Daily acceptance criteria

| # | Criterion | Threshold | How to measure |
|---|-----------|-----------|----------------|
| 1 | **Output length** | <=10 surfaced items | Count items in `{date}_delta.json` that passed the noise filter |
| 2 | **Relevance rate** | >=80% judged "useful" | Manual review: would you have wanted to know this before the next batch run? |
| 3 | **No duplicate churn** | 0 items resurfaced without material change | Compare today's delta codes+tickers against yesterday's. Same ticker+code on consecutive days without date/source/status change = duplicate |
| 4 | **Noise filter effective** | <=2 items that are clearly irrelevant | Items where the name is not A/B tier, not <=30d catalyst, not in shadow, and the change is cosmetic |
| 5 | **Stable output format** | JSON parses cleanly, all required fields present | `python3 -c "import json; d=json.load(open('artifacts/catalyst_delta/{date}_delta.json')); assert 'changes' in d"` |

## Per-day scoring

After each manual run, record in `agents/catalyst_delta/memory/{date}.md`:

```
## Trial Day N — {date}
- Items surfaced: X
- Relevant: Y/X (Z%)
- Duplicates: N
- Irrelevant noise: N
- Format OK: yes/no
- PASS / FAIL
```

## Go/no-go decision

| Result | Action |
|--------|--------|
| 4-5 days PASS | Promote to cron (daily, after production packet) |
| 3 days PASS | Extend trial 3 more days, investigate failure days |
| <=2 days PASS | Redesign noise filter before retrying |

## What "material change" means

A change is material if any of these are true:
- Event date moved by >=3 days
- Source family changed (hard <-> soft)
- Event type changed (e.g., CT_PRIMARY_COMPLETION -> DATA_READOUT)
- Trial status changed (e.g., recruiting -> completed)
- New event appeared that didn't exist in prior snapshot
- Event disappeared (source retracted or superseded)

A change is NOT material if:
- Only the `collected_at` timestamp changed
- Source metadata changed but date/type/family stayed the same
- A soft event shifted by 1-2 days (CTGov PCD wobble)

## After promotion

Once on cron, review weekly:
- Is daily output still <=10 items?
- Are new failure modes emerging?
- Should the noise filter thresholds be tightened?

Adjust thresholds in AGENTS.md if needed. Do not change the rubric
retroactively — create a v2 rubric instead.

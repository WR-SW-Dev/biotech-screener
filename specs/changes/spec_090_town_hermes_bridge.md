# Spec 090 — Town-Hermes Bridge

**Status:** PHASE A IN PROGRESS
**Author:** Hermes ops session 2026-05-07
**First commit:** TBD

---

## Objective

Route Hermes Knowledge Layer outputs (Spec 089) into Town as operator-facing
tasks, briefs, and alerts — without giving Town production mutation authority.

```
Hermes  = source of truth / scheduler / repo-state brain
Town    = operator-facing assistant / inbox / task surface
Telegram = hard interrupt channel
Git/repo artifacts = permanent audit trail
```

---

## Architecture

Hermes generates deterministic artifacts. Town receives webhooks, creates tasks,
and surfaces summaries to the operator. Town does NOT control Hermes.

### Data flow

```
Hermes job completes
  → write ledger artifact (repo)
  → send_operator_event(channel="town", ...)
      → POST JSON to TOWN_WEBHOOK_URL
          → Town routine creates/updates task
          → Town DMs operator in Slack/email
```

### What Town is NOT

- NOT a scheduler
- NOT a cron controller
- NOT a repo mutator
- NOT a spec approver
- NOT allowed to reactivate bioshort_watch LLM
- NOT allowed to infer approval from a chat message
- NOT the authoritative source for any production state

---

## Integration path: email trigger (not webhook)

Town does not currently expose a native inbound webhook endpoint.
The production-ready path today is email:

  Hermes sends structured email to TOWN_EMAIL (djschulz@gmail.com)
  Town routine triggers on email arrival, filters on subject prefix [Hermes]
  Town creates task / DMs operator

Subject format:
  [Hermes] {SEVERITY} | {event_type} | {title}

Body: plain-text summary + JSON payload block (parseable by Town routine).

Future: if Town adds native webhook support, operator_delivery.py can add
a _send_town_webhook() path alongside _send_town_email() with no callers
needing to change.

## Webhook payload schema (email body JSON block)

All Hermes → Town events use this envelope:

```json
{
  "data": {
    "source": "hermes",
    "event_type": "<event_type>",
    "severity": "INFO | WARN | FAIL",
    "title": "<human-readable title>",
    "artifact": "<relative repo path to ledger>",
    "summary": "<1-3 sentence plain-text summary>",
    "next_operator_action": "<specific next step, or 'none'>"
  }
}
```

### Event types

| event_type | severity | trigger |
|------------|----------|---------|
| held_spec_ledger | INFO | hermes-held-spec-ledger completes |
| first_fire_pass | INFO | first-fire validator returns PASS |
| first_fire_fail | FAIL | first-fire validator returns FAIL |
| snapshot_missing | FAIL | production snapshot absent after run |
| ruleset_mismatch | FAIL | CLAUDE.md ruleset vs code mismatch |
| stale_artifact | WARN | required artifact past staleness threshold |
| cron_missed | FAIL | cron job did not fire (WSL sleep or other) |
| contradiction_detected | WARN | hard contradiction in contradiction_ledger |

---

## Environment variables

```
TOWN_EMAIL                 — destination address (default: djschulz@gmail.com)
OPERATOR_DELIVERY_DRY_RUN  — "1" to log without sending (Phase A default)
```

SMTP vars are shared with alert_email.py (already set in repo .env):
SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD

Never commit live values. TOWN_EMAIL default is safe to leave in .env.example.

---

## common/operator_delivery.py

Generic multi-channel delivery helper. Town-specific logic lives here only —
callers import send_operator_event() without knowing the channel.

```python
send_operator_event(
    channel="town" | "telegram" | "slack",
    severity="INFO" | "WARN" | "FAIL",
    event_type="first_fire_pass" | "held_spec_ledger" | ...,
    title="...",
    summary="...",
    artifact="artifacts/ops/held_spec_ledger/latest.md",
    next_operator_action="...",
    dry_run=True,   # Phase A default; Phase B sets via env
)
```

Behaviour:
- dry_run=True (or OPERATOR_DELIVERY_DRY_RUN=1): logs payload, skips HTTP
- Missing credentials: logs warning, returns False, never raises
- HTTP errors: logs warning, returns False, never raises
- Uses common/alert_dedupe.py for deduplication (same pattern as alerts.py)

---

## Phase plan

### Phase A — document + dry-run helper (this spec, current)

Deliverables:
- specs/changes/spec_090_town_hermes_bridge.md  ← this file
- common/operator_delivery.py (dry_run=True default)
- .env.example updated with Town vars
- tests/test_operator_delivery.py

No live secrets.
No cron changes.
No Town account required yet.

Acceptance:
- dry-run mode logs correct payload for held_spec_ledger event
- tests pass
- flake8/black/isort clean

### Phase B — wire held-spec ledger

Wire one Hermes job: hermes-held-spec-ledger → Town webhook.

Steps:
1. Set TOWN_WEBHOOK_URL + TOWN_WEBHOOK_SECRET in repo .env
2. Set OPERATOR_DELIVERY_DRY_RUN=0
3. Verify Town receives payload and creates task
4. Approval-required / read-only mode confirmed

No production failures routed yet (keep blast radius minimal for first wire).

### Phase C — hard failure routing

Add routing for:
- first_fire_fail (first-fire validation FAIL)
- snapshot_missing
- ruleset_mismatch
- cron_missed (WSL sleep detection)
- contradiction_detected (HARD_CONTRADICTION)

Each routes: Telegram (immediate) + Town (task/context/follow-up).

---

## First use case (Phase B)

```
hermes-held-spec-ledger completes
  → send_operator_event(
        channel="town",
        event_type="held_spec_ledger",
        severity="INFO",
        title="Held-spec ledger updated",
        artifact="artifacts/ops/held_spec_ledger/latest.md",
        next_operator_action="Review held specs; bioshort first-fire due Fri 18:00 ET",
    )
  → Town creates task: "Review held specs / first-fire validations"
```

Low risk. No production failures in scope yet.

---

## Guardrails (always active)

Hermes → Town delivery MAY:
- POST read-only summaries and ledger artifact paths
- create/update Town tasks
- send Slack/email DMs via Town

Hermes → Town delivery MAY NOT:
- grant Town write access to repo
- let Town trigger cron jobs
- let Town modify .env or config
- let Town approve spec changes
- infer operator approval from Town chat response
- bypass alert deduplication

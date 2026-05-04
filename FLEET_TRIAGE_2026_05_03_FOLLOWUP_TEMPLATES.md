# 2026-05-03 Fleet-Triage Follow-Up Decisions — TEMPLATES

**Status:** Templates only. No production change. Each section is a
disposition awaiting operator pick. Once operator chooses, the chosen
template's preview-then-apply block is drafted as a separate step.

This document collects the deferred decisions from today's three memos:
- `GROK_BIOTECH_WATCH_CRON_MISCONFIG_2026_05_03.md` (cron fix landed)
- `POLICY_SHADOW_AND_REVIEW_QUEUE_REGISTRY_MISMATCH_2026_05_03.md` (memo only)
- `agents/bioshort_watch/memory/2026-05-03_cron_misescalation_issue.md`
  (cron-prompt fix landed)

Templates below are filled-in WHERE-AVAILABLE and gap-marked WHERE-OPERATOR-DECIDES.

---

## TEMPLATE 1 — Email-credential disposition for grok_biotech_watch

Memo §5.3 (`GROK_BIOTECH_WATCH_CRON_MISCONFIG_2026_05_03.md`).

The 2026-05-01 invocation log surfaced W2: "No email credentials found
(SENDGRID_API_KEY / SMTP_PASSWORD / EMAIL_API_KEY all absent). Alerts
will write to artifacts/grok_watch/ but will NOT be delivered to
dschulz@wakerobin.co."

### Option E1: Provision SENDGRID_API_KEY (or SMTP_PASSWORD) in `.env`

Operator action: add credential to `<repo>/.env`. No code change required —
the agent reads env vars at invocation time.

```bash
# Append to .env (NOT committed; .env is gitignored):
echo 'SENDGRID_API_KEY=<KEY>' >> .env
# OR
echo 'SMTP_PASSWORD=<PASSWORD>' >> .env
```

Verification: re-run `python3 tools/run_agent_direct.py --agent grok_biotech_watch --message "HEARTBEAT"`
and confirm W2 alert is no longer surfaced.

✅ Cleanest restoration of the deliverability contract.
❌ Requires operator to provision and store the credential.

### Option E2: Accept disk-only delivery, document the gap

Operator action: NONE. HIGH alerts will write to `artifacts/grok_watch/`
where the operator can grep / monitor manually.

Document at agent's AGENTS.md or a posted note that delivery is
disk-only.

✅ Zero credential management.
❌ HIGH alerts may be missed if not actively checked.
❌ Defeats part of the agent's design intent.

### Option E3: Disable the email-attempt step entirely

Operator action: edit `agents/grok_biotech_watch/SOUL.md` and TOOLS.md
to remove email-delivery as a step. Agent runs scan + writes artifacts only.

✅ Cleanest contract — no implicit email obligation.
❌ Loses optionality if creds become available later.

**Operator pick:** _________________

---

## TEMPLATE 2 — Retention policy for `artifacts/grok_watch/`

Memo §5.4 (`GROK_BIOTECH_WATCH_CRON_MISCONFIG_2026_05_03.md`).

With Option A landed, three artifacts/day land in `artifacts/grok_watch/`
on weekdays. Each `<date>_alerts.json` was 126KB on 2026-03-30; growth ~2MB/day.

### Option R1: No retention; let it grow

✅ Zero ops.
❌ Repo size grows ~500MB/year if checked in.
❌ Hurts grep/find operations over time.

### Option R2: Add to `.gitignore`, no rotation

✅ Repo size protected.
❌ Local disk still fills.

### Option R3: Time-based rotation (90d window)

Add a cron job that prunes files older than 90 days from
`artifacts/grok_watch/` (excluding `dedup_state.json`):

```bash
# Crontab template:
0 4 * * 0 find /mnt/c/Projects/biotech_screener/biotech-screener/artifacts/grok_watch -maxdepth 1 -type f -name "*_alerts.*" -mtime +90 -delete
```

✅ Bounded disk + repo size.
❌ Loses historical alerts for >90d analysis.
❌ Adds another cron entry that the WSL2-sleep cliff can miss.

### Option R4: Archive-then-delete (S3 / cold storage)

Move >30d files to S3, keep 30d on disk. Requires AWS creds.

✅ Long-term audit retention without local cost.
❌ More moving parts; one more cred path to maintain.

**Operator pick:** _________________

---

## TEMPLATE 3 — policy_shadow_watch registry alignment

Memo §3 (`POLICY_SHADOW_AND_REVIEW_QUEUE_REGISTRY_MISMATCH_2026_05_03.md`).

### Option A1 — Align registry to TOOLS.md

Edit `agents/AGENT_REGISTRY.json`:

```json
"policy_shadow_watch": {
  ...
  "artifact_paths": [
    "artifacts/policy_shadow/tier_weighted/"
  ],
  ...
}
```

After A1 lands, next fleet receipt will likely STILL flag
policy_shadow_watch as STALE because the canonical artifact path is
`artifacts/policy_shadow/tier_weighted/` and last write is 2026-04-28.
That will be a real freshness issue at fact 1.3, NOT a registry artifact.

**Preview-then-apply block (drafted, not executed):**

```bash
# Step 1: Backup
BAK="$HOME/agent_registry.bak.$(date +%Y%m%d_%H%M%S).json"
cp agents/AGENT_REGISTRY.json "$BAK"
echo "Backed up to $BAK"

# Step 2: PREVIEW
python3 -c "
import json
d = json.load(open('agents/AGENT_REGISTRY.json'))
d['agents']['policy_shadow_watch']['artifact_paths'] = ['artifacts/policy_shadow/tier_weighted/']
new = json.dumps(d, indent=2)
" > /tmp/registry_new.json
diff agents/AGENT_REGISTRY.json /tmp/registry_new.json

# Step 3: STOP — operator reviews
# Expected: 4 hunks, only the policy_shadow_watch.artifact_paths array changes.

# Step 4: APPLY (after approval)
mv /tmp/registry_new.json agents/AGENT_REGISTRY.json

# Step 5: VERIFY
python3 -c "
import json
d = json.load(open('agents/AGENT_REGISTRY.json'))
print(d['agents']['policy_shadow_watch']['artifact_paths'])
"
# Expected output: ['artifacts/policy_shadow/tier_weighted/']

# Rollback: cp $BAK agents/AGENT_REGISTRY.json
```

**Operator pick:** _________________ (A1 / A2 / A3 / defer)

---

## TEMPLATE 4 — review_queue_steward registry approach

Memo §3 (`POLICY_SHADOW_AND_REVIEW_QUEUE_REGISTRY_MISMATCH_2026_05_03.md`).

This is a deeper change than Template 3 — Options B1 and B2 require
schema or code edits in `tools/agent_heartbeat_checks.py`, not just
registry JSON. Templating the recommended path (B1) and noting the
trade-offs.

### Option B1 — Custom check function reading invocation logs

Two coupled changes:

**B1a. Registry edit:**
```json
"review_queue_steward": {
  ...
  "artifact_paths": [],
  ...
}
```

**B1b. New specialised check at `tools/agent_heartbeat_checks.py`:**

```python
def check_review_queue_steward(dt: date) -> CheckResult:
    """Read invocation logs as the freshness signal for chat-mode agents."""
    log_dir = REPO_ROOT / "logs" / "agents_direct"
    pattern = f"review_queue_steward_*.json"
    candidates = sorted(log_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return CheckResult("review_queue_steward", "STALE", "no invocation logs",
                          ["NO_INVOCATIONS"])
    newest = candidates[0]
    age_days = (datetime.now().timestamp() - newest.stat().st_mtime) / 86400
    if age_days > 2:  # daily_after_production threshold
        return CheckResult("review_queue_steward", "STALE",
                          f"newest_invocation={newest.stem.split('_')[-2]} ({age_days:.1f}d)",
                          [f"STALE_INVOCATION: {age_days:.1f}d"])
    # Verify status=success in the log
    try:
        d = json.load(open(newest))
        status = d.get("status", "unknown")
        if status != "success":
            return CheckResult("review_queue_steward", "WARN",
                              f"newest invocation status={status}", [])
    except Exception as e:
        return CheckResult("review_queue_steward", "WARN", f"log unparseable: {e}", [])
    return CheckResult("review_queue_steward", "OK",
                      f"newest invocation {age_days:.1f}d, status=success")
```

Wire it into the registry-driven dispatch alongside `check_ic_health`,
`check_data_auditor`, etc.

✅ Receipt becomes correct; agent's actual liveness signal (invocation
   log) is now what the receipt reads.
✅ Pattern matches existing custom checks (no new schema field needed).
❌ Requires editing `tools/agent_heartbeat_checks.py` — touching the
   check tool itself, which is sensitive.

**Operator pick for review_queue_steward:** _________________ (B1 / B2 / B3 / defer)

---

## TEMPLATE 5 — Skill update for `openclaw-fleet-triage`

Memo §5.5 (both memos).

The skill's "Known recurring conditions" section memorialised three of
today's four findings as "chronic stale/dead". All three turned out to be
diagnosable, distinct mechanisms.

**Required edit:**
- Skill is currently PINNED. Cannot be modified via `skill_manage` until
  the operator runs `hermes curator unpin openclaw-fleet-triage`.
- Once unpinned, the patch (already drafted at session memory) replaces
  the four-agent "chronic dead" line with three separate findings:
  - production_qa: still chronic, no diagnosis attempted
  - grok_biotech_watch: cron-prompt fix landed
  - policy_shadow_watch / review_queue_steward: registry-vs-reality drift,
    memo at repo root, operator decision pending

**Operator pick:** unpin and apply, OR leave pinned and accept skill staleness.

---

## TEMPLATE 6 — Audit `STALENESS_DAYS_BY_CADENCE`

Memo §5.6 (memo #2).

`tools/agent_heartbeat_checks.py:608` reads `STALENESS_DAYS_BY_CADENCE[cadence]`.
Today's RED-on-Saturday triage shows the threshold doesn't account for
Mon-Fri-only production cadence.

Suggested check (read-only):
```bash
grep -A 20 "STALENESS_DAYS_BY_CADENCE" tools/agent_heartbeat_checks.py
```

Possible fix: add weekend-aware logic for `daily_after_production` and
`daily_premarket` cadences (skip Sat/Sun in the threshold calculation).

This is a code change to a sensitive tool. Operator decides whether
worth the touch given that today's RED was misleading and tomorrow's
post-production receipt will likely be fine.

**Operator pick:** _________________ (audit / defer)

---

## TEMPLATE 7 — Sweep `AGENT_REGISTRY.json` for path mismatches

Memo §5.7 (memo #2).

Two of today's findings (policy_shadow_watch, review_queue_steward) are
registry-vs-reality drift. The 26 other entries in
`agents/AGENT_REGISTRY.json` may have similar drift unsurfaced because
they don't appear in fleet receipts (different reason, different proxy).

Suggested audit (read-only, ~5 min):

```bash
python3 -c "
import json, pathlib
d = json.load(open('agents/AGENT_REGISTRY.json'))
ROOT = pathlib.Path('.')
for name, entry in d['agents'].items():
    paths = entry.get('artifact_paths', [])
    if not paths:
        continue
    found = []
    for p in paths:
        full = ROOT / p
        if full.is_file() or (full.is_dir() and any(full.iterdir())):
            found.append(p)
    if not found and entry.get('status') == 'active':
        print(f'{name}: ALL declared artifact_paths empty/missing — {paths}')
"
```

Output: list of agents whose registry-declared paths are all empty.
Cross-reference with receipt findings to triage.

**Operator pick:** _________________ (run audit / defer)

---

## TEMPLATE 8 — Model routing for external-content watcher agents

Surfaced by `openclaw status --deep` security audit (2026-05-03 ~17:00 ET):

> WARN — Some configured models are below recommended tiers
> Smaller/older models are generally more susceptible to prompt injection
> and tool misuse. Detected: `claude-haiku-4-5-20251001` on multiple agents.

The agents currently on Haiku that consume **untrusted external content**:

| Agent              | External-content surface                                |
| ------------------ | ------------------------------------------------------- |
| bioshort_watch     | reads `output/hedge_report/*.json` (third-party feed)   |
| grok_biotech_watch | xAI Grok web search results (free-form internet text)  |
| shadow_watch       | various external feeds (verify before routing change)   |

This is a **standing posture decision**, not an active fault. No
incident; routing was chosen for cost. Today's bioshort cron-prompt
fix tightened the read-only scope, which mitigates blast radius
regardless of model tier.

### Option M1 — Route external-content agents to Sonnet

Edit per-agent OpenClaw config to override model:

```bash
# Per-agent model override — exact CLI shape depends on OpenClaw version:
openclaw agents update bioshort_watch     --model anthropic/claude-sonnet-4-6
openclaw agents update grok_biotech_watch --model anthropic/claude-sonnet-4-6
# shadow_watch — verify content surface first, then optionally:
openclaw agents update shadow_watch       --model anthropic/claude-sonnet-4-6
```

✅ Better prompt-injection resistance per security audit recommendation.
✅ Targeted: only the three external-content readers, not the whole fleet.
✅ Reversible per-agent.
❌ ~3-5x token cost for those agents (Sonnet vs Haiku pricing).
   Annual cost depends on invocation frequency × token usage; with
   bioshort_watch at 1/week (cron 13 18 * * 6) and grok_biotech_watch at
   3/weekday (post-grok-fix), the absolute spend is small but non-zero.
❌ Verify CLI shape (`openclaw agents update --model` may not be the exact
   command name — check `openclaw agents --help` before applying).

### Option M2 — Route only the highest-risk agent (grok_biotech_watch)

Same as M1 but only for `grok_biotech_watch`. Rationale: Grok web-search
results are the most adversarial input surface (arbitrary internet text,
no operator pre-screening); hedge-report JSON is a generated artifact
inside the screener; shadow_watch's external surface is unclear without
investigation.

✅ Smallest cost increase.
✅ Concentrates the risk-mitigation on the highest-leverage target.
❌ Leaves bioshort_watch and shadow_watch on Haiku.
❌ Doesn't address the security audit warn fully.

### Option M3 — No change; document acceptance

Add a note to `agents/AGENT_REGISTRY.json` (or a separate posture doc)
recording that Haiku routing on external-content readers is a known
trade-off, intentional, and revisited if a real incident surfaces.

✅ Zero cost change.
✅ Captures the operator's already-implicit decision explicitly.
❌ The security audit warn keeps appearing in every `openclaw status --deep`
   run; nothing makes it stop.

### (Operator considerations — not a recommendation)

This is genuinely "no urgent action required" per the 2026-05-03 audit.
Today's bioshort cron-prompt tightening already mitigated one of the two
attack surfaces (the agent now refuses to escalate beyond reading
artifacts). M2 is the reasonable middle ground if cost is tight; M1 is
the cleanest closure of the security-audit warn; M3 is the do-nothing
that's still defensible.

**Operator pick:** _________________ (M1 / M2 / M3 / defer)

---

## Deferred state

All eight decisions are open. None block production today. None are
urgent — fleet receipt will continue to surface the same findings until
operator picks.

Suggested order if operator does want to chain:
1. Template 3 (policy_shadow_watch A1) — cheapest first move
2. Template 4 (review_queue_steward B1 vs B3) — depends on #1 outcome
3. Template 1 (email creds)
4. Template 5 (skill unpin + patch) — closes the loop
5. Template 6 + 7 (audits) — separate pass

Or none. The memos are durable; this template doc is the gathering place.

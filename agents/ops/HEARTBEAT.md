# HEARTBEAT.md — Ops Agent

On heartbeat, run this checklist. If everything is CLEAR, reply HEARTBEAT_OK.

## Checklist

1. Check if today's snapshot exists: `ls data/snapshots/$(date +%Y-%m-%d)/`
   - If missing and it's a weekday after 5:30 PM ET → flag as MISSED RUN
2. Read today's ops digest: `cat artifacts/ops_digest/$(date +%Y-%m-%d)_digest.md`
   - If attention != CLEAR → summarize action items
   - If the digest has a "Stability Plumbing" section with "PLUMBING SUSPECT" →
     flag as PLUMBING_INVESTIGATION and name the feature(s) that dropped coverage.
     Do NOT attribute to market regime until plumbing is ruled out.
3. Check gateway health: `openclaw gateway status`
   - If not running → flag

Only report issues. HEARTBEAT_OK means all three checks passed.

# OpenClaw announce/webchat jobs — fleet state 2026-05-05

Confirmed instance of Class G (webchat channel unresolvable in isolated cron).
All 7 affected jobs patched with --best-effort-deliver on 2026-05-05.

## Affected jobs (UUIDs)

| Name                     | Job ID                               | Agent      | After fix delivery                              |
|--------------------------|--------------------------------------|------------|-------------------------------------------------|
| ops-daily                | 69e97f03-b9c9-4bea-9526-51a14b4d99a5 | ops        | announce/webchat/bestEffort:true                |
| sentinel-daily           | d851bfab-bb7e-4acf-93fa-64d6c4556931 | sentinel   | announce/webchat/bestEffort:true                |
| daily-production-brief   | 9e195263-8dfc-4314-bea6-78c0bc27186a | ops        | announce/webchat/bestEffort:true                |
| ops-digest-summary       | b30f1359-8afe-4e59-9bb8-32de258faf96 | ops        | announce/webchat/bestEffort:true                |
| dashboard-validation-ping| 84aa25ca-4726-4392-9b62-7822da60ba57 | sentinel   | announce/webchat/bestEffort:true                |
| calibration-weekly       | aa7fd482-b2f3-4ad1-9363-2ac570e1fb33 | calibration| announce/webchat/bestEffort:true                |
| weekly-policy-review     | cd6dd704-86b6-4459-85d3-995b01600ed6 | shadow_watch| announce/webchat/bestEffort:true               |

## Healthy jobs (no delivery issues)

| Name                 | Job ID                               | delivery.mode |
|----------------------|--------------------------------------|---------------|
| qa-daily             | cf7189f3-782a-4620-8db9-02dcb0744faa | none          |
| weekly-bioshort-brief| 2887b975-4833-4907-a570-739410e01036 | none          |

## Auth-sync stall context (same incident)

- Hermes scheduler stalled: 39h gap (2026-05-03T22:02 → 2026-05-05T13:18)
- All 31 agents were EXPIRED+DRIFT at time of discovery
- Manual run of ~/.local/bin/openclaw-auth-sync: updated=31 noop=0 error=0
- Cron 4cfe9fb5d466 kicked manually; next_run reset to 13:27 ET

## How to check if Class G is recurring

If future runs show consecutive errors creeping back up on these jobs,
check whether bestEffort:true is still set:

```bash
openclaw cron list --json | python3 -c "
import json,sys
for j in json.load(sys.stdin):
    d = j.get('delivery',{})
    if d.get('mode')=='announce':
        be = d.get('bestEffort', False)
        print(f\"{j['name']:35s} bestEffort={be}\")
"
```

Expected: all announce jobs show bestEffort=True.

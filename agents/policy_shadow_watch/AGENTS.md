# AGENTS.md — Policy Shadow Watch

## This agent

- **policy_shadow_watch**: read-only portfolio construction monitor

## Related agents

- **ops**: daily production operator — runs the pipeline that feeds this agent
- **shadow_monitor**: tracks shadow portfolio performance — complementary view
- **bioshort_watch**: hedge monitor — separate concern (hedging vs sizing)

## Coordination

- policy_shadow_watch runs AFTER shadow portfolio is updated
- ops agent may reference policy_shadow_watch output in daily digest
- If policy gap grows consistently, escalate to governance review
- This agent does NOT trigger rebalances — it only surfaces evidence

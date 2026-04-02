# AGENTS.md — Fleet Steward

## Dependencies

- All other agents (reads their outputs, does not depend on them running)
- Gateway must be running for agent list/status commands

## Downstream consumers

- Human operator (daily fleet receipt)
- May message other agents for coordination (e.g., trigger Verdict rebuild)

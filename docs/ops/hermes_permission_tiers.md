# Hermes Permission Tiers

Maps `authority_level` in `AGENT_REGISTRY.json` to a numeric tier with explicit
allowed/forbidden path sets.  
**Enforced by:** `tools/hermes_path_guard.py` (`--check <path>`)

---

## Tier table

| Tier | authority_level | Readable shorthand |
|---|---|---|
| 0 | `observe_only` | Read + own artifacts |
| 1 | `observe_and_propose` | + Spec proposals |
| 2 | `write_artifacts` | + Shared artifacts |
| 3 | `mutate_data` | + Data mutations |
| 4 | `mutate_config` | + Config/cron mutations |

---

## Tier 0 — `observe_only`

**Allowed writes:**
- `artifacts/<agent_id>/` (own artifact dir)
- `logs/<agent_id>*.log`
- `agents/<agent_id>/memory/` (own memory)

**Forbidden writes (hard block):**
- `ranker/`, `selector/`, `portfolio/`, `sizing/`
- `data/snapshots*/`, `data/aact/`, `data/sec/`
- `specs/`, `CLAUDE.md`, `.github/workflows/`
- Any path matching `production_data/**`
- Any path matching `artifacts/generated/**`
- Any path outside own `artifact_paths`

---

## Tier 1 — `observe_and_propose`

**Adds to Tier 0:**
- `artifacts/ops/held_spec_ledger/` (pending spec proposals)
- `artifacts/pending_*/`

**Forbidden:** everything forbidden at Tier 0

---

## Tier 2 — `write_artifacts`

**Adds to Tier 1:**
- Any path under `artifacts/` except `artifacts/generated/`
- `docs/hermes_skills/` (mirror regeneration, capped at 3 files/run)

**Forbidden:** everything frozen (ranker/selector/portfolio/snapshots/config)

---

## Tier 3 — `mutate_data`

**Adds to Tier 2:**
- `data/aact/`
- `data/sec/`
- `data/universe/`
- `output/catalyst_ev/`

**Forbidden:** `data/snapshots*/`, `ranker/`, `selector/`, `portfolio/`

---

## Tier 4 — `mutate_config`

**Adds to Tier 3:**
- `specs/`
- `.github/workflows/`
- `cron/` config files
- `CLAUDE.md` (operator-gated; not for autonomous agents)

**Reserved for:** operator-initiated, human-in-the-loop only.  
No Hermes job should run at Tier 4 without explicit operator approval.

---

## Production freeze override

During an active production model freeze (see `CLAUDE.md` freeze status), Tier 3+ writes to any frozen component require operator clearance even if the agent's `authority_level` permits them.  

Frozen components as of 2026-06-26:
- `ranker/`, `selector/`, `sizing/`, `final_score/`
- `portfolio/`, `portfolio_positions/`, `decision_portfolio/`
- `data/snapshots*/`

---

## Enforcement

`tools/hermes_path_guard.py` implements the tier rules:

```bash
# Check whether a write to a path is allowed for a given tier
python3 tools/hermes_path_guard.py --check artifacts/my_agent/output.json --tier 0

# Check using authority_level name
python3 tools/hermes_path_guard.py --check ranker/weights.json --authority observe_only

# Self-test (all tier rules)
python3 tools/hermes_path_guard.py --self-test
```

Exit codes: 0 = allowed, 1 = blocked, 2 = error/invalid

---

## Rationale

Numeric tiers allow `hermes_path_guard.py` to implement `tier >= N` checks without
hard-coding authority_level strings throughout the codebase. The `authority_level`
enum in `AGENT_REGISTRY.json` is the operator-facing name; the tier is the
machine-enforceable integer.

---

## References

- Registry schema: `docs/ops/hermes_agent_registry.md`
- Path guard implementation: `tools/hermes_path_guard.py`
- Freeze policy: `CLAUDE.md` → Architecture Freeze Status

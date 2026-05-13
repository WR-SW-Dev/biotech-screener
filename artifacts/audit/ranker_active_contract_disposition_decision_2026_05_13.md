# ranker_active_contract.py — Disposition Decision

**Operator Decision**: ACCEPT MANUAL ENFORCEMENT (do not merge branch at this time)

**Evidence**: `common/ranker_active_contract.py` exists on branch `hygiene/ranker-active-contract-2026-04-30` (commit `e7c0ee47`, 21 drift tests). However, production code on main does not import or call it. Five audit documents currently assert enforcement that is not active.

**Rationale**: Architecture is frozen (2026-04-19 policy). Merging new enforcement logic carries unquantified risk during a period when the model and ranker are under observation (h20d checkpoint 2026-05-26). Manual/observational enforcement is sufficient until post-checkpoint stability is confirmed.

**Action Items**:
1. ✓ Document this decision (this memo)
2. Update `artifacts/audit/ranking_alternatives_research_2026_05_08.md` section 2 to reflect manual enforcement
3. Update project memory entry `biotech_ranker_active_contract_2026_04_30.md` to clarify: branch exists but unapplied; no runtime enforcement active
4. Do NOT merge branch until after h20d checkpoint (2026-05-26) and post-checkpoint review (2026-05-26+)

**Risk Acceptance**: MEDIUM risk acknowledged (no automatic enforcement of ranker input drift). Mitigation: manual spot-checks via `tools/verify_snapshot_integrity.py` before production release.

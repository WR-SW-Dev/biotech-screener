# Spec 089 Phase 1.5A — Ranker Governance Knowledge Graph Pilot — Schema Design

**Date**: 2026-05-14  
**Purpose**: Lock schema before Phase 1.5A implementation to prevent scope creep into universal ontology.  
**Non-Scope**: No graph DB, no cron, no production changes, no biotech/science/company/trial semantics.

---

## 1. Objective

Encode ranker governance dependencies, constraints, and contradictions into a queryable knowledge graph for the ranker-governance domain only. Validate the graph approach on the highest-risk, highest-value domain before expanding to full repo ops.

The graph answers:
- What blocks a production ranker change?
- What contradictions exist in ranker governance state?
- Which specs are operationally complete vs. code-closed vs. pending?
- What is the next allowed operator action?

---

## 2. Non-Scope

**Explicitly out of Phase 1.5A:**
- Graph database (JSONL only)
- Cron automation
- Production model/ranker/selector changes
- Biotech domain entities (companies, trials, mechanisms, therapies, stages)
- Science domain semantics (clinical, biomarker, endpoint)
- Universal repo ops ontology (ranker governance pilot only)
- LLM-based reasoning (rule-based only)

**What to avoid during implementation:**
- Do not model company/ticker relationships
- Do not model trial/indication relationships
- Do not model user roles or org structure
- Do not model financial/clinical scores as first-class entities (they are properties of snapshots)
- Do not add nodes for abstract concepts (e.g., "Alpha Block", "Clinical Reasoning") unless directly tied to a spec/policy/code artifact

---

## 3. Node Schema

Eleven node types. All nodes require:
```json
{
  "id": "unique_identifier",
  "type": "NodeType",
  "title": "Human-readable title",
  "status": "ACTIVE | PENDING | CLOSED | CONFLICT",
  "source_path": "path/to/authoritative/source/or/artifact",
  "evidence": "path/to/proof/or/memo/or/commit",
  "updated_at": "YYYY-MM-DDTHH:MM:SSZ"
}
```

### Node types:

#### Spec
Represents a specification document (Spec 072, Spec 100, etc.)  
Required fields: `spec_number`, `phase` (A/B/C/D/scaffold), `title`, `objective`  
Example:
```json
{
  "id": "spec_100",
  "type": "Spec",
  "spec_number": 100,
  "phase": "scaffold",
  "title": "True Ranker IC Tooling",
  "objective": "Forward-return wiring and correct IC computation",
  "status": "PENDING",
  "source_path": "specs/changes/spec_100_*.md",
  "evidence": "specs/changes/spec_100_governance_follow_up_2026_05_13.md",
  "updated_at": "2026-05-14T00:00:00Z"
}
```

#### Policy
Represents a governance constraint (ranker freeze, alpha stack freeze, etc.)  
Required fields: `policy_id`, `enforced_since`, `enforces_constraint`  
Example:
```json
{
  "id": "policy_alpha_freeze",
  "type": "Policy",
  "policy_id": "alpha_freeze_2026_04_04",
  "enforced_since": "2026-04-04",
  "enforces_constraint": "No promotions without Checklist v2",
  "status": "ACTIVE",
  "source_path": "specs/changes/policy_alpha_freeze_2026_04_04.md",
  "evidence": "specs/changes/policy_alpha_freeze_2026_04_04.md",
  "updated_at": "2026-04-04T00:00:00Z"
}
```

#### Commit
Represents a git commit with ranker-governance relevance  
Required fields: `commit_hash`, `commit_msg`, `authored_date`  
Example:
```json
{
  "id": "commit_18cd13b1",
  "type": "Commit",
  "commit_hash": "18cd13b1",
  "commit_msg": "Spec 102: historical backfill script",
  "authored_date": "2026-05-14T10:30:00Z",
  "status": "ACTIVE",
  "source_path": "git log",
  "evidence": "git show 18cd13b1",
  "updated_at": "2026-05-14T00:00:00Z"
}
```

#### Artifact
Represents a versioned output (closure memo, audit report, snapshot)  
Required fields: `artifact_name`, `artifact_type` (MEMO/REPORT/SNAPSHOT/CONFIG), `materialized_date`  
Example:
```json
{
  "id": "artifact_spec_100_closure_memo",
  "type": "Artifact",
  "artifact_name": "Spec 100 True Ranker IC Closure Memo",
  "artifact_type": "MEMO",
  "materialized_date": null,
  "status": "PENDING",
  "source_path": "artifacts/audit/spec_100_*.md",
  "evidence": "specs/changes/spec_100_governance_follow_up_2026_05_13.md",
  "updated_at": "2026-05-14T00:00:00Z"
}
```

#### CodeFile
Represents a source file with ranker-governance relevance  
Required fields: `file_path`, `file_type` (SCRIPT/MODULE/CONFIG), `last_modified`  
Example:
```json
{
  "id": "code_run_true_ranker_ic",
  "type": "CodeFile",
  "file_path": "scripts/research/run_true_ranker_ic.py",
  "file_type": "SCRIPT",
  "last_modified": "2026-05-14T10:30:00Z",
  "status": "ACTIVE",
  "source_path": "scripts/research/run_true_ranker_ic.py",
  "evidence": "git log --follow scripts/research/run_true_ranker_ic.py",
  "updated_at": "2026-05-14T00:00:00Z"
}
```

#### Signal
Represents a model signal or feature (inst_delta_z, coinvest_score_z, clinical_score, etc.)  
Required fields: `signal_name`, `signal_status` (ACTIVE/SHADOW/MONITORING/CLOSED), `in_production`  
Example:
```json
{
  "id": "signal_inst_delta_forward_shadow",
  "type": "Signal",
  "signal_name": "inst_delta_forward_shadow",
  "signal_status": "MONITORING_ONLY",
  "in_production": false,
  "status": "ACTIVE",
  "source_path": "artifacts/ops/inst_delta_forward_shadow_T0_2026_04_28.md",
  "evidence": "regime_post_cohort_change_distortion_2026_04_28.md",
  "updated_at": "2026-05-14T00:00:00Z"
}
```

#### ModelComponent
Represents a production model component (ranker, selector, gate, module)  
Required fields: `component_name`, `component_type` (RANKER/SELECTOR/GATE/MODULE), `frozen` (bool)  
Example:
```json
{
  "id": "model_ranker_v2",
  "type": "ModelComponent",
  "component_name": "Ranker v2",
  "component_type": "RANKER",
  "frozen": true,
  "status": "ACTIVE",
  "source_path": "common/ranker_v2_model.json",
  "evidence": "scoring_model_identity_2026_04_06.md",
  "updated_at": "2026-04-06T00:00:00Z"
}
```

#### Blocker
Represents an explicit operational blocker or hold  
Required fields: `blocker_type` (EVIDENCE/IMPLEMENTATION/SCOPE/VALIDATION), `blocks_what`  
Example:
```json
{
  "id": "blocker_spec_100_forward_return_wiring",
  "type": "Blocker",
  "blocker_type": "IMPLEMENTATION",
  "blocks_what": "Spec 100 operational completion",
  "description": "load_forward_returns() is stubbed, must be wired to actual forward-return computation",
  "status": "ACTIVE",
  "source_path": "scripts/research/run_true_ranker_ic.py",
  "evidence": "specs/changes/spec_100_governance_follow_up_2026_05_13.md",
  "updated_at": "2026-05-14T00:00:00Z"
}
```

#### ValidationGate
Represents a formal validation check or approval gate  
Required fields: `gate_name`, `gate_type` (SNAPSHOT/ARTIFACT/CODE/REVIEW)  
Example:
```json
{
  "id": "gate_2026_05_22_ranker_review",
  "type": "ValidationGate",
  "gate_name": "2026-05-22 Ranker Review",
  "gate_type": "REVIEW",
  "scheduled_date": "2026-05-22T17:00:00Z",
  "status": "PENDING",
  "source_path": "specs/changes/spec_072_screener_vnext_2026_05_01.md",
  "evidence": "ranker_research_landscape_2026_05_14.md",
  "updated_at": "2026-05-14T00:00:00Z"
}
```

#### Snapshot
Represents a daily production data snapshot  
Required fields: `snapshot_date` (YYYY-MM-DD), `snapshot_path`  
Example:
```json
{
  "id": "snapshot_2026_05_15",
  "type": "Snapshot",
  "snapshot_date": "2026-05-15",
  "snapshot_path": "data/snapshots/2026-05-15",
  "status": "PENDING",
  "source_path": "data/snapshots/",
  "evidence": "specs_104_105_closure_sequence_2026_05_15.md",
  "updated_at": "2026-05-14T00:00:00Z"
}
```

#### Review
Represents a formal review or audit with conclusions  
Required fields: `review_type`, `review_date`, `conclusion`  
Example:
```json
{
  "id": "review_spec_094_marginal_value",
  "type": "Review",
  "review_type": "EVIDENCE_SUFFICIENCY",
  "review_date": "2026-05-14",
  "conclusion": "PENDING_MORE_EVIDENCE",
  "status": "ACTIVE",
  "source_path": "specs/changes/ranking_methodology_spec_backlog_2026_05_13.md",
  "evidence": "specs/changes/ranking_methodology_spec_backlog_2026_05_13.md",
  "updated_at": "2026-05-14T00:00:00Z"
}
```

#### Action
Represents a discrete operator action or decision checkpoint  
Required fields: `action_type`, `action_name`, `required_by` (optional date)  
Example:
```json
{
  "id": "action_spec_100_implement_forward_returns",
  "type": "Action",
  "action_type": "IMPLEMENTATION",
  "action_name": "Wire load_forward_returns() to actual computation",
  "required_by": "2026-05-22",
  "status": "PENDING",
  "source_path": "specs/changes/spec_100_governance_follow_up_2026_05_13.md",
  "evidence": "specs/changes/spec_100_governance_follow_up_2026_05_13.md",
  "updated_at": "2026-05-14T00:00:00Z"
}
```

---

## 4. Edge Schema

Fifteen edge types. All edges require:
```json
{
  "src": "source_node_id",
  "edge": "EdgeType",
  "dst": "destination_node_id",
  "evidence": "path/to/proof/commit/memo",
  "confidence": "HIGH | MEDIUM | LOW",
  "created_at": "YYYY-MM-DDTHH:MM:SSZ"
}
```

### Edge types:

| Edge | Semantics | Example |
|------|-----------|---------|
| IMPLEMENTS | Spec/Action is implemented by Code/Commit | `spec_100 IMPLEMENTS code_run_true_ranker_ic` |
| DOCUMENTS | Spec/Policy is documented in Artifact/CodeFile | `spec_100 DOCUMENTS artifact_spec_100_closure_memo` |
| BLOCKS | Blocker/Policy/Gate prevents Action/Spec completion | `blocker_spec_100_forward_return BLOCKS action_spec_100_implement` |
| DEPENDS_ON | Spec/Action depends on another Spec/Gate/Artifact | `spec_100 DEPENDS_ON snapshot_2026_05_15` |
| GOVERNS | Policy constrains allowed changes to ModelComponent/Spec | `policy_alpha_freeze GOVERNS model_ranker_v2` |
| REQUIRES | Spec/Gate requires another Spec/Artifact/Gate to complete first | `spec_096 REQUIRES spec_094` |
| VALIDATES | Gate/Review proves or disproves a claim | `gate_2026_05_22_ranker_review VALIDATES spec_094` |
| PENDING_ON | Spec/Action is waiting on Artifact/Gate/Snapshot | `spec_072 PENDING_ON gate_2026_05_22_ranker_review` |
| CLOSED_BY | Commit/Artifact closes/resolves a Spec/Blocker | `commit_18cd13b1 CLOSED_BY spec_102` |
| TOUCHES | Commit/CodeFile modifies relevant code for a Spec | `commit_18cd13b1 TOUCHES code_run_true_ranker_ic` |
| READS | Signal/Code reads/uses data from another Signal/CodeFile/Artifact | `signal_inst_delta_forward_shadow READS artifact_13f_cohort_distortion` |
| WRITES | CodeFile/Commit produces data for Signal/Artifact/Snapshot | `code_run_true_ranker_ic WRITES artifact_spec_100_results` |
| PROHIBITS | Policy forbids an Action/Change | `policy_alpha_freeze PROHIBITS action_promote_new_ranker_feature` |
| CONTRADICTS | Artifact/CodeFile contradicts a claim in Spec/Artifact | `code_run_true_ranker_ic CONTRADICTS "Spec 100 complete"` |

---

## 5. Seed Graph Assertions

Hardcoded initial state (extracted from current memos, specs, and git):

```
# Governance structure
spec_096 GOVERNS production_ranker_change
spec_096 REQUIRES spec_094
spec_096 REQUIRES spec_095
spec_096 REQUIRES spec_100
policy_alpha_freeze GOVERNS model_ranker_v2
policy_alpha_freeze GOVERNS model_selector_a4
policy_alpha_freeze REQUIRES review_spec_094_marginal_value
policy_alpha_freeze REQUIRES review_spec_095_ic_scope

# Spec 100 blockages
spec_100 DEPENDS_ON action_forward_return_wiring
spec_100 DEPENDS_ON action_ic_computation_correct
action_forward_return_wiring BLOCKS spec_100
code_run_true_ranker_ic TOUCHES spec_100
code_run_true_ranker_ic CONTRADICTS "Spec 100 complete"

# Spec 072 blockers
spec_072 PENDING_ON gate_2026_05_22_ranker_review
spec_072 REQUIRES snapshot_2026_05_15
spec_072 DEPENDS_ON validation_cohort_distortion_cleared

# Spec 091 requirements
spec_091 REQUIRES artifact_crt

# Checklist v2 blocker
policy_checklist_v2 BLOCKS production_ranker_promotion
policy_checklist_v2 REQUIRES review_promotion_readiness

# 2026-05-15 snapshot dependencies
snapshot_2026_05_15 REQUIRED_BY spec_072
snapshot_2026_05_15 REQUIRED_BY spec_104
snapshot_2026_05_15 REQUIRED_BY spec_105
snapshot_2026_05_15 REQUIRED_BY validation_cohort_distortion_cleared
```

---

## 6. Query Contract

The extractor and query layer must support exactly these five queries:

### Query 1: `--what-blocks production-ranker-change`
Returns all nodes and paths that prevent a production ranker change.  
**Expected result**: Spec 096 doctrine, Specs 094/095/100, Checklist v2, Spec 072 2026-05-22 review, cohort distortion clearance.

### Query 2: `--spec-status spec_100`
Returns status of a spec, its dependencies, blockers, and closure evidence.  
**Expected result**: Spec 100 PENDING; depends on forward-return wiring; blocked by stub contradiction; closure memo not materialized.

### Query 3: `--contradictions`
Returns all CONTRADICTS edges and their evidence.  
**Expected result**: Spec 100 code contradicts "Spec 100 complete" (load_forward_returns stubbed); other contradictions if any.

### Query 4: `--next-actions`
Returns operator actions not yet completed, sorted by required_by date.  
**Expected result**: Action list with deadlines; prioritize 2026-05-15 snapshot closures, then 2026-05-22 review prep.

### Query 5: `--what-touches run_screen.py`
Returns all commits, specs, and changes touching a file.  
**Expected result**: List of commits/specs that modified run_screen.py.

---

## 7. Contradiction Rules

Implement exactly five contradiction detection rules:

### Rule 1: Status Contradiction
**Trigger**: Node has `status: "CLOSED"` or `status: "COMPLETE"` but has outgoing PENDING_ON or DEPENDS_ON edges.  
**Logic**:
```
IF node.status IN ["CLOSED", "COMPLETE"]
AND node has outgoing edge of type PENDING_ON or DEPENDS_ON
THEN flag CONTRADICTION(status_contradiction, node.id, blocking_node)
```
**Example**: Spec 100 marked "complete" but `spec_100 DEPENDS_ON forward_return_wiring`.

### Rule 2: Stub Contradiction
**Trigger**: CodeFile with `status: "ACTIVE"` contains placeholder/stub markers AND Spec says "COMPLETE".  
**Logic**:
```
IF CodeFile linked to Spec via IMPLEMENTS edge
AND CodeFile.content contains pattern (return None | return {} | raise NotImplemented | TODO | STUB | placeholder)
AND Spec.status == "COMPLETE"
THEN flag CONTRADICTION(stub_contradiction, spec_id, code_file_id)
```
**Example**: `load_forward_returns()` returns empty dict, but Spec 100 claims complete.

### Rule 3: Scope Contradiction
**Trigger**: Commit with type "ranker" or "selector" or "model_component" BUT Policy blocks such changes.  
**Logic**:
```
IF Commit.files_touched MATCH regex (.*ranker.*|.*selector.*|.*model_component.*)
AND Policy == policy_alpha_freeze AND Policy.status == ACTIVE
AND Policy.enforced_since < Commit.authored_date
THEN flag CONTRADICTION(scope_contradiction, commit.id, policy.id)
```
**Example**: Commit to `ranker/` during active alpha freeze.

### Rule 4: Artifact Contradiction
**Trigger**: Artifact marked "PENDING" but no file exists at `source_path`.  
**Logic**:
```
IF Artifact.status == "PENDING"
AND file_exists(Artifact.source_path) == False
AND file_exists(Artifact.evidence) == False
THEN flag CONTRADICTION(artifact_contradiction, artifact.id, "missing_file")
```
**Example**: Closure memo declared but not committed.

### Rule 5: Promotion Contradiction
**Trigger**: Signal marked `signal_status: "SHADOW_ONLY"` or `"MONITORING_ONLY"` but appears in production ModelComponent inputs.  
**Logic**:
```
IF Signal.signal_status IN ["SHADOW_ONLY", "MONITORING_ONLY"]
AND Signal has outgoing edge READS to ModelComponent
AND ModelComponent.frozen == True
THEN flag CONTRADICTION(promotion_contradiction, signal.id, component.id)
```
**Example**: `inst_delta_forward_shadow` marked monitoring-only but wired into production ranker.

---

## 8. Acceptance Criteria

The schema design is complete when:

1. **Spec 100 stub issue is flagged automatically**: Graph correctly identifies that `load_forward_returns()` is stubbed, IC outputs are placeholder zeros, and therefore Spec 100 cannot be marked complete despite having a scaffold.

2. **Production ranker change is correctly blocked**: Query `--what-blocks production-ranker-change` returns exactly: Spec 096 doctrine + Specs 094/095/100 + Checklist v2 + Spec 072 2026-05-22 review + cohort distortion clearance.

3. **No biotech-domain claims in graph**: Graph contains zero nodes of type Company, Trial, Indication, Clinical, Mechanism, Patient, Outcome, etc. (ranker governance only).

4. **All five queries are implementable**: Each query can be answered via graph traversal without external file reads.

5. **Contradiction rules are unambiguous**: Each rule is testable without human interpretation.

6. **Schema prevents scope creep**: All 11 node types and 15 edge types are necessary for ranker governance. No additional types are justified by the pilot scope.

---

**Status**: APPROVED FOR IMPLEMENTATION AFTER 2026-05-15 CLOSURES.

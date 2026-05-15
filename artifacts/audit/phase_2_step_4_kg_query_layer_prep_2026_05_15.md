# Phase 2 Step 4 — Ranker Governance KG Query Layer — Prep & Roadmap (2026-05-15)

**Purpose**: Prepare implementation plan for knowledge graph query layer (Phase 2 Step 4).

**Status**: Specification & design only (do NOT implement until 13F cohort clears ~May 23–26).

**Schema Reference**: `spec_089_phase_1_5a_kg_schema_design_2026_05_14.md` (locked, 11 node types, 15 edge types, 5 contradiction rules).

---

## Overview

Phase 2 Step 4 builds the **query layer** that answers five governance questions:

1. `--what-blocks production-ranker-change` → Returns all blockers
2. `--spec-status SPEC_ID` → Returns spec dependencies, blockers, closure evidence
3. `--contradictions` → Returns all contradictions with evidence
4. `--next-actions` → Returns pending actions sorted by deadline
5. `--what-touches FILE_PATH` → Returns commits/specs touching a file

**Non-Goals**: No graph database, no cron automation, no production changes, no LLM reasoning.

---

## Implementation Roadmap

### Phase 2 Step 4a — Data Structure & Loader (May 23–24)

**Goal**: Build KG loader that parses nodes/edges and validates schema.

**File**: `tools/kg_loader.py`

```python
class KnowledgeGraphNode:
    """Represents a single node in the governance KG."""
    id: str
    node_type: str  # Spec, Policy, Commit, Artifact, CodeFile, Signal, etc.
    title: str
    status: str  # ACTIVE, PENDING, CLOSED, CONFLICT
    source_path: str
    evidence: str
    updated_at: str
    extra_fields: dict  # Type-specific (spec_number, policy_id, etc.)

class KnowledgeGraphEdge:
    """Represents a directed edge between nodes."""
    src: str
    edge_type: str  # IMPLEMENTS, DOCUMENTS, BLOCKS, DEPENDS_ON, etc.
    dst: str
    evidence: str
    confidence: str  # HIGH, MEDIUM, LOW
    created_at: str

class KnowledgeGraph:
    """In-memory KG for governance queries."""
    nodes: dict[str, KnowledgeGraphNode]
    edges: list[KnowledgeGraphEdge]
    
    def __init__(self):
        """Load seed graph from artifacts/audit/kg_seed.jsonl"""
        
    def add_node(self, node: KnowledgeGraphNode) -> None
    def add_edge(self, edge: KnowledgeGraphEdge) -> None
    def validate_schema(self) -> list[str]  # Returns validation errors
```

**Seed Graph**: `artifacts/audit/kg_seed.jsonl`
- One JSON object per line (node or edge)
- Hand-crafted from current spec/policy/memo state
- Example:
  ```json
  {"id": "spec_100", "type": "Spec", "spec_number": 100, "phase": "scaffold", "title": "True Ranker IC Tooling", "status": "PENDING", "source_path": "specs/changes/spec_100_*.md", "evidence": "specs/changes/spec_100_governance_follow_up_2026_05_13.md", "updated_at": "2026-05-14T00:00:00Z"}
  {"src": "spec_100", "edge": "DEPENDS_ON", "dst": "action_forward_return_wiring", "evidence": "specs/changes/spec_100_governance_follow_up_2026_05_13.md", "confidence": "HIGH", "created_at": "2026-05-14T00:00:00Z"}
  ```

**Tests**:
- Load seed graph, verify 11 node types present
- Validate all edges reference existing nodes
- Check no duplicate node IDs
- Verify all required fields present

**Output**: Working KnowledgeGraph class, testable in isolation.

---

### Phase 2 Step 4b — Query Implementations (May 24–25)

**Goal**: Implement five query functions.

**File**: `tools/kg_queries.py`

```python
class KGQueries:
    def __init__(self, kg: KnowledgeGraph):
        self.kg = kg
    
    def what_blocks_production_ranker_change(self) -> dict:
        """Query 1: What blocks a production ranker change?
        
        Returns:
        {
            "blockers": [list of blocker node IDs],
            "paths": [list of dependency chains from blocker to ranker],
            "evidence": [commitment/memo/spec paths]
        }
        """
        # Traverse all edges to spec_096 and policy_alpha_freeze
        # Follow GOVERNS/BLOCKS/REQUIRES edges
        # Return reachable nodes and dependency chains
        
    def spec_status(self, spec_id: str) -> dict:
        """Query 2: Status of a spec, dependencies, blockers, closure evidence."""
        # Return spec node + all incoming/outgoing edges + closure artifact
        
    def contradictions(self) -> list[dict]:
        """Query 3: All contradictions with evidence."""
        # Apply 5 contradiction detection rules
        # Return list of {rule, nodes, evidence}
        
    def next_actions(self) -> list[dict]:
        """Query 4: Pending actions sorted by deadline."""
        # Find all Action nodes with status=PENDING
        # Sort by required_by date
        # Return list of {action, deadline, dependencies}
        
    def what_touches_file(self, file_path: str) -> list[dict]:
        """Query 5: Commits/specs touching a file."""
        # Search git log + CodeFile nodes for file_path
        # Return list of {commit, spec, date, files_touched}
```

**Implementation Notes**:
- Query 1–4: Pure graph traversal (no external file reads)
- Query 5: Graph traversal + git log (one-time read)
- All return JSON-serializable dicts

**Tests**:
- Query 1: Verify Spec 096, Specs 094/095/100, Checklist v2, Spec 072 gate, cohort clearance all returned
- Query 2: Verify Spec 100 shows PENDING, depends on forward-return wiring, blocked by stub
- Query 3: Verify Spec 100 stub contradiction flagged
- Query 4: Verify action list sorted by date, deadlines correct
- Query 5: Verify commits to run_screen.py returned with dates

---

### Phase 2 Step 4c — Contradiction Detection Rules (May 25–26)

**Goal**: Implement 5 contradiction detection rules (from schema design).

**File**: `tools/kg_contradictions.py`

```python
class KGContradictions:
    def __init__(self, kg: KnowledgeGraph):
        self.kg = kg
    
    def detect_all(self) -> list[dict]:
        """Run all 5 rules; return list of contradictions."""
        return (
            self.rule_1_status_contradiction()
            + self.rule_2_stub_contradiction()
            + self.rule_3_scope_contradiction()
            + self.rule_4_artifact_contradiction()
            + self.rule_5_promotion_contradiction()
        )
    
    def rule_1_status_contradiction(self) -> list[dict]:
        """Status Contradiction: Node CLOSED/COMPLETE but has PENDING_ON/DEPENDS_ON edges."""
        # For each node with status CLOSED or COMPLETE:
        #   If has outgoing PENDING_ON or DEPENDS_ON: flag
        
    def rule_2_stub_contradiction(self) -> list[dict]:
        """Stub Contradiction: CodeFile has stub/placeholder AND Spec claims COMPLETE."""
        # For each CodeFile->Spec IMPLEMENTS edge:
        #   Check source_path for stub patterns (return None, TODO, STUB, etc.)
        #   If Spec.status == COMPLETE: flag
        
    def rule_3_scope_contradiction(self) -> list[dict]:
        """Scope Contradiction: Commit touches ranker/selector BUT Policy freezes them."""
        # For each Commit node:
        #   If commit_msg or evidence mentions ranker/selector changes
        #   AND policy_alpha_freeze active and enforced_since < commit date: flag
        
    def rule_4_artifact_contradiction(self) -> list[dict]:
        """Artifact Contradiction: Artifact PENDING but file doesn't exist."""
        # For each Artifact with status PENDING:
        #   If source_path and evidence both don't exist: flag
        
    def rule_5_promotion_contradiction(self) -> list[dict]:
        """Promotion Contradiction: Signal SHADOW_ONLY but in production ModelComponent."""
        # For each Signal with signal_status SHADOW_ONLY or MONITORING_ONLY:
        #   If has READS edge to ModelComponent.frozen=True: flag
```

**Implementation Notes**:
- Rules 1, 4: Pure graph inspection
- Rule 2: Graph + file system (check source_path exists)
- Rule 3: Graph + git log (check commit metadata)
- Rule 5: Graph + production config (check ModelComponent inputs)

**Tests**:
- Seed graph with Spec 100 stub contradiction, verify rule 2 flags it
- Seed graph with Policy freeze + Commit during freeze, verify rule 3 flags it
- Verify no false positives (e.g., non-stub code files pass rule 2)

---

### Phase 2 Step 4d — CLI Tool & API (May 26–27)

**Goal**: Build CLI tool and HTTP API for queries.

**File**: `tools/kg_query_cli.py`

```bash
# CLI usage:
python3 tools/kg_query_cli.py --what-blocks production-ranker-change
python3 tools/kg_query_cli.py --spec-status spec_100
python3 tools/kg_query_cli.py --contradictions
python3 tools/kg_query_cli.py --next-actions
python3 tools/kg_query_cli.py --what-touches run_screen.py
python3 tools/kg_query_cli.py --all  # Run all queries, output summary
```

**Output Format**:
```
=== What Blocks Production Ranker Change ===
Status: 5 blockers identified (1 high-risk, 2 medium-risk, 2 low-risk)

Blockers:
1. [HIGH] Spec 096 Doctrine (Ranker Governance Framework)
   - Blocks: production-ranker-change
   - Requires: Specs 094, 095, 100
   - Evidence: specs/changes/spec_096_doctrine.md

2. [HIGH] Spec 100 True Ranker IC Tooling
   - Status: PENDING (stub contradiction)
   - Blocks: Spec 096 completion
   - Evidence: code_run_true_ranker_ic.py (load_forward_returns stubbed)
   
... (3 more blockers) ...

Next Action: [1] Resolve Spec 100 stub (wire load_forward_returns); [2] Prepare for 2026-05-22 review

Contradictions: 1 detected
- Spec 100 code contradicts "complete" claim (load_forward_returns stubbed)
```

**Tests**:
- CLI runs without errors
- JSON output is valid
- All queries produce expected structure
- Summary shows correct counts and priorities

---

### Phase 2 Step 4e — Validation Tests (May 27–28)

**Goal**: Write comprehensive test suite.

**File**: `tests/test_kg_queries.py`

```python
class TestKGQueries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Load seed graph once."""
        cls.kg = KnowledgeGraph()
        cls.kg.load_seed('artifacts/audit/kg_seed.jsonl')
        cls.queries = KGQueries(cls.kg)
    
    def test_what_blocks_production_ranker_change(self):
        """Verify expected blockers returned."""
        result = self.queries.what_blocks_production_ranker_change()
        self.assertIn("spec_096", result["blockers"])
        self.assertIn("spec_100", result["blockers"])
        # ... (verify all 5 expected blockers)
    
    def test_spec_100_status(self):
        """Verify Spec 100 status, dependencies, contradiction."""
        result = self.queries.spec_status("spec_100")
        self.assertEqual(result["status"], "PENDING")
        self.assertIn("action_forward_return_wiring", result["depends_on"])
        # ... (verify contradiction detected)
    
    def test_contradictions_detected(self):
        """Verify all 5 contradiction rules work."""
        contradictions = KGContradictions(self.kg).detect_all()
        # Should include Spec 100 stub contradiction
        self.assertTrue(any(c["rule"] == "stub_contradiction" for c in contradictions))
    
    def test_next_actions_sorted(self):
        """Verify actions returned in deadline order."""
        result = self.queries.next_actions()
        dates = [a["required_by"] for a in result if a.get("required_by")]
        self.assertEqual(dates, sorted(dates))
    
    # ... (more tests for Query 5, CLI, edge cases, error handling)
```

**Acceptance Criteria**:
- 30+ test cases covering all queries, rules, edge cases
- 100% pass rate before shipping
- Contradiction detection matches schema design (Spec 100 stub correctly identified)

---

## Seed Graph Content

**Manually authored** from current spec/memo state:

### Nodes (estimated ~80)
- Specs: 072, 091, 094, 095, 096, 100, 102, 104, 105
- Policies: alpha_freeze, checklist_v2, demotion_path
- Model Components: ranker_v2, selector_a4, gate_clinical
- Signals: inst_delta_forward_shadow, coinvest_score_z, clinical_score_v2_z
- Actions: forward_return_wiring, ic_computation_correct, promote_ranker_feature
- Gates: 2026-05-22 ranker review, cohort distortion clearance
- Artifacts: spec_100 closure memo, spec_100 governance follow-up
- Commits: key commits to ranker code, spec closures
- Code Files: run_screen.py, ranker_v2_model.json, common/ranker_active_contract.py
- Reviews: Spec 094 marginal value, Spec 095 IC scope, promotion readiness
- Snapshots: 2026-05-15 (with closure status)

### Edges (estimated ~120)
- GOVERNS: policies → model components
- BLOCKS: blockers/policies → specs/actions
- DEPENDS_ON: specs → actions/gates/snapshots
- IMPLEMENTS: specs → code files
- REQUIRES: specs → other specs/reviews
- TOUCHES: commits → code files
- CONTRADICTS: code → spec claims
- ... (15 edge types total)

**Authoring Process** (post-May-23 cohort clearance):
1. Extract current spec/policy/memo state from memory + artifacts
2. Extract recent commits from git log
3. Manually wire governance constraints (what blocks ranker changes?)
4. Add known contradictions (Spec 100 stub, etc.)
5. Validate all edges reference existing nodes
6. Test all 5 queries produce expected output

---

## Timeline

| Date | Phase | Task | Output |
|------|-------|------|--------|
| 2026-05-19 (Mon) | 3 | Verify watchdog, lock Phase 2 Step 3b preflight spec | Test plan validated |
| ~2026-05-23 (Fri) | 4a | 13F cohort clears (expected) | Begin KG preparation |
| 2026-05-23–24 (Fri–Sat) | 4a | Build KG loader, seed graph | tools/kg_loader.py, kg_seed.jsonl |
| 2026-05-24–25 (Sat–Sun) | 4b | Implement 5 query functions | tools/kg_queries.py (100 lines/query) |
| 2026-05-25–26 (Sun–Mon) | 4c | Implement contradiction detection | tools/kg_contradictions.py (5 rules) |
| 2026-05-26–27 (Mon–Tue) | 4d | Build CLI tool + API | tools/kg_query_cli.py |
| 2026-05-27–28 (Tue–Wed) | 4e | Write & run validation tests | tests/test_kg_queries.py (30+ tests) |
| 2026-05-28 (Wed) | 4 | Phase 2 Step 4 COMPLETE | All 5 queries working, 0 contradictions undetected |

**Do NOT wire into governance enforcement yet** (that's Phase 2 Step 5, late phase).
Document intent, provide the tool, let operator review.

---

## Notes

- **Schema locked** (May 14): 11 node types, 15 edge types, 5 rules finalized
- **Cohort clearance prerequisite**: Need stable current state before finalizing seed graph
- **No external dependencies**: Pure Python, no graph DB, no LLM reasoning
- **Query contract fixed**: Five queries, deterministic output, no ambiguity
- **Contradiction detection deterministic**: Five rules, testable without human interpretation

---

**Status**: Roadmap and prep complete. Ready for implementation post-May-23 cohort clearance.

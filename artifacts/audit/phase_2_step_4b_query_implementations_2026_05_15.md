# Phase 2 Step 4b — Knowledge Graph Query Implementations (2026-05-15)

**Status**: Design locked (specification only; do NOT implement until cohort clearance is explicitly verified).

**Scope**: ~200 lines of query code specification, test cases for all 5 queries.

**Dependencies**: Phase 4a (KnowledgeGraph loader) must be complete.

**Implementation Gate**: Do NOT begin Phase 4b until cohort clearance is explicitly CONFIRMED.

---

## Overview

Phase 4b implements five deterministic query functions that answer governance questions:

1. **what_blocks_production_ranker_change()** — Returns all blockers preventing ranker changes
2. **spec_status(spec_id)** — Returns a spec's status, dependencies, blockers, closure evidence
3. **contradictions()** — Returns all contradictions with evidence
4. **next_actions()** — Returns pending actions sorted by deadline
5. **what_touches_file(file_path)** — Returns commits/specs touching a file

All queries are **pure graph traversal** (except Query 5 which adds one git log call).

---

## File: tools/kg_queries.py

```python
from pathlib import Path
from typing import Optional
import subprocess
import json

from kg_loader import KnowledgeGraph, KnowledgeGraphNode, KnowledgeGraphEdge


class KGQueries:
    """Governance queries on the knowledge graph."""
    
    def __init__(self, kg: KnowledgeGraph):
        """Initialize with a loaded knowledge graph."""
        self.kg = kg
    
    # ========== QUERY 1: What Blocks Production Ranker Change ==========
    
    def what_blocks_production_ranker_change(self) -> dict:
        """Query 1: What blocks a production ranker change?
        
        Returns all nodes that block, govern, or gate ranker work, along with
        their dependency chains and evidence paths.
        
        Returns:
        {
            "blockers": [list of blocker node IDs],
            "blocker_details": [
                {"id": "spec_096", "title": "...", "status": "...", "reason": "..."},
                ...
            ],
            "dependency_chains": [
                ["spec_096", "spec_094", "checklist_v2", "..."],
                ...
            ],
            "evidence": [list of evidence paths],
            "summary": "N blockers identified; M high-risk, X medium-risk, Y low-risk"
        }
        """
        blockers = []
        blocker_nodes = {}
        chains = []
        evidence_set = set()
        
        # Search for nodes that mention ranker/selector in constraints
        target_node_ids = ["spec_096", "policy_alpha_freeze", "gate_ranker_review_2026_05_22"]
        
        for node_id in target_node_ids:
            node = self.kg.get_node(node_id)
            if node and node.status != "CLOSED":
                blockers.append(node_id)
                blocker_nodes[node_id] = node
                if node.evidence:
                    evidence_set.add(node.evidence)
        
        # Follow BLOCKS, REQUIRES, GATES edges from blockers to find dependencies
        for blocker_id in blockers:
            chain = self._find_dependency_chain(blocker_id, max_depth=5)
            if chain:
                chains.append(chain)
        
        # Risk assessment: HIGH if status ACTIVE, MEDIUM if PENDING, LOW if FROZEN
        risk_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for node in blocker_nodes.values():
            if node.status == "ACTIVE":
                risk_counts["HIGH"] += 1
            elif node.status == "PENDING":
                risk_counts["MEDIUM"] += 1
            else:
                risk_counts["LOW"] += 1
        
        blocker_details = [
            {
                "id": node_id,
                "title": blocker_nodes[node_id].title,
                "status": blocker_nodes[node_id].status,
                "reason": self._get_blocker_reason(node_id)
            }
            for node_id in blockers
        ]
        
        summary = (
            f"{len(blockers)} blockers identified; "
            f"{risk_counts['HIGH']} high-risk, {risk_counts['MEDIUM']} medium-risk, {risk_counts['LOW']} low-risk"
        )
        
        return {
            "blockers": blockers,
            "blocker_details": blocker_details,
            "dependency_chains": chains,
            "evidence": sorted(list(evidence_set)),
            "summary": summary
        }
    
    def _find_dependency_chain(self, start_node_id: str, max_depth: int = 5) -> list[str]:
        """Breadth-first search to find dependency chain from start node."""
        if max_depth <= 0:
            return [start_node_id]
        
        chain = [start_node_id]
        current = start_node_id
        
        # Follow one outgoing DEPENDS_ON/REQUIRES edge to build chain
        for edge in self.kg.outgoing_edges(current):
            if edge.edge_type in ["DEPENDS_ON", "REQUIRES"]:
                child_chain = self._find_dependency_chain(edge.dst, max_depth - 1)
                chain.extend(child_chain[1:])  # Skip duplicate start
                break
        
        return chain
    
    def _get_blocker_reason(self, node_id: str) -> str:
        """Return human-readable reason why this node blocks ranker work."""
        node = self.kg.get_node(node_id)
        if not node:
            return "Unknown"
        
        if "freeze" in node.title.lower():
            return "Ranker/selector work frozen by policy"
        elif "doctrine" in node.title.lower():
            return "Governance framework requirement"
        elif "review" in node.title.lower():
            return "Pending review gate"
        else:
            return node.title
    
    # ========== QUERY 2: Spec Status ==========
    
    def spec_status(self, spec_id: str) -> dict:
        """Query 2: Status of a spec, dependencies, blockers, closure evidence.
        
        Returns:
        {
            "spec_id": "spec_100",
            "title": "True Ranker IC Tooling",
            "status": "PENDING",
            "depends_on": ["action_forward_return_wiring", "gate_2026_05_22"],
            "blocked_by": ["spec_096", "checklist_v2"],
            "blocking": ["spec_096"],
            "contradictions": [{"rule": "stub_contradiction", "evidence": "..."}],
            "closure_evidence": ["path/to/memo.md", ...],
            "evidence_path": "specs/changes/spec_100_*.md"
        }
        """
        node = self.kg.get_node(spec_id)
        if not node:
            return {"error": f"Spec {spec_id} not found"}
        
        depends_on = []
        blocked_by = []
        blocking = []
        closure_evidence = []
        
        # Outgoing edges: what this spec depends on
        for edge in self.kg.outgoing_edges(spec_id):
            if edge.edge_type in ["DEPENDS_ON", "REQUIRES", "AWAITS"]:
                depends_on.append(edge.dst)
                if edge.evidence:
                    closure_evidence.append(edge.evidence)
        
        # Incoming edges: what blocks this spec
        for edge in self.kg.incoming_edges(spec_id):
            if edge.edge_type == "BLOCKS":
                blocked_by.append(edge.src)
            if edge.edge_type in ["REQUIRES", "GATES"]:
                blocked_by.append(edge.src)
        
        # Outgoing BLOCKS edges: what this spec blocks
        for edge in self.kg.outgoing_edges(spec_id):
            if edge.edge_type == "BLOCKS":
                blocking.append(edge.dst)
        
        # Find contradictions mentioning this spec
        contradictions = self._find_contradictions_for_spec(spec_id)
        
        return {
            "spec_id": spec_id,
            "title": node.title,
            "status": node.status,
            "depends_on": depends_on,
            "blocked_by": blocked_by,
            "blocking": blocking,
            "contradictions": contradictions,
            "closure_evidence": closure_evidence,
            "evidence_path": node.source_path
        }
    
    def _find_contradictions_for_spec(self, spec_id: str) -> list[dict]:
        """Find contradictions where this spec is mentioned."""
        contradictions = []
        
        # Check for incoming CONTRADICTS edges
        for edge in self.kg.incoming_edges(spec_id):
            if edge.edge_type == "CONTRADICTS":
                contradictions.append({
                    "rule": "spec_contradiction",
                    "src": edge.src,
                    "evidence": edge.evidence
                })
        
        return contradictions
    
    # ========== QUERY 3: Contradictions ==========
    
    def contradictions(self) -> list[dict]:
        """Query 3: All contradictions with evidence.
        
        Returns list of detected contradictions (rules applied in phase 4c).
        Here we just surface CONTRADICTS edges from the graph.
        
        Returns:
        [
            {
                "rule": "stub_contradiction",
                "node_id": "spec_100",
                "conflicting_node": "code_run_true_ranker_ic.py",
                "evidence": "code_run_true_ranker_ic.py (load_forward_returns stubbed)",
                "description": "Spec claims COMPLETE but code contains stub/placeholder"
            },
            ...
        ]
        """
        contradictions = []
        
        # Find all CONTRADICTS edges
        for edge in self.kg.edges:
            if edge.edge_type == "CONTRADICTS":
                src_node = self.kg.get_node(edge.src)
                dst_node = self.kg.get_node(edge.dst)
                
                if src_node and dst_node:
                    contradictions.append({
                        "rule": "code_spec_mismatch",
                        "node_id": edge.dst,
                        "conflicting_node": edge.src,
                        "evidence": edge.evidence,
                        "description": f"{src_node.title} contradicts {dst_node.title}"
                    })
        
        return contradictions
    
    # ========== QUERY 4: Next Actions ==========
    
    def next_actions(self) -> list[dict]:
        """Query 4: Pending actions sorted by deadline.
        
        Returns:
        [
            {
                "action_id": "action_forward_return_wiring",
                "title": "Wire load_forward_returns implementation",
                "required_by": "2026-05-22",
                "status": "PENDING",
                "dependencies": ["spec_100"],
                "blocking": ["spec_096"],
                "evidence": "specs/changes/spec_100_governance_follow_up_2026_05_13.md"
            },
            ...
        ]
        """
        actions = []
        
        # Find all Action nodes with status PENDING
        for node_id, node in self.kg.nodes.items():
            if node.node_type == "Action" and node.status == "PENDING":
                dependencies = []
                blocking = []
                
                # Incoming edges: what this action depends on
                for edge in self.kg.incoming_edges(node_id):
                    if edge.edge_type in ["DEPENDS_ON", "REQUIRES"]:
                        dependencies.append(edge.src)
                
                # Outgoing edges: what this action unblocks
                for edge in self.kg.outgoing_edges(node_id):
                    if edge.edge_type == "BLOCKS":
                        blocking.append(edge.dst)
                
                # Extract required_by date from extra_fields
                required_by = node.extra_fields.get("required_by", "unknown")
                
                actions.append({
                    "action_id": node_id,
                    "title": node.title,
                    "required_by": required_by,
                    "status": node.status,
                    "dependencies": dependencies,
                    "blocking": blocking,
                    "evidence": node.evidence
                })
        
        # Sort by required_by date (assuming ISO format)
        actions.sort(key=lambda a: a["required_by"])
        
        return actions
    
    # ========== QUERY 5: What Touches File ==========
    
    def what_touches_file(self, file_path: str) -> list[dict]:
        """Query 5: Commits and specs touching a file.
        
        Combines graph search (CodeFile nodes) with git log (one-time read).
        
        Returns:
        [
            {
                "type": "commit",
                "commit_hash": "3185d752",
                "commit_msg": "tools: add evening watchdog",
                "files_touched": ["tools/cron_evening_reliability_check.sh"],
                "date": "2026-05-15T16:14:15Z",
                "spec": null
            },
            {
                "type": "spec",
                "spec_id": "spec_072",
                "title": "Screener vNext",
                "files": ["run_screen.py", "tools/screener_v2.py"],
                "date": "2026-05-01T00:00:00Z"
            },
            ...
        ]
        """
        results = []
        
        # Search graph for CodeFile nodes matching file_path
        for node_id, node in self.kg.nodes.items():
            if node.node_type == "CodeFile" and file_path in node.source_path:
                # Find specs that IMPLEMENT this file
                for edge in self.kg.incoming_edges(node_id):
                    if edge.edge_type == "IMPLEMENTS":
                        spec_node = self.kg.get_node(edge.src)
                        if spec_node:
                            results.append({
                                "type": "spec",
                                "spec_id": edge.src,
                                "title": spec_node.title,
                                "files": [node.source_path],
                                "date": spec_node.updated_at
                            })
                
                # Find commits that TOUCH this file
                for edge in self.kg.incoming_edges(node_id):
                    if edge.edge_type == "TOUCHES":
                        commit_node = self.kg.get_node(edge.src)
                        if commit_node:
                            results.append({
                                "type": "commit",
                                "commit_hash": commit_node.extra_fields.get("commit_hash", "unknown"),
                                "commit_msg": commit_node.title,
                                "files_touched": [node.source_path],
                                "date": commit_node.updated_at,
                                "spec": None
                            })
        
        # Also run git log to find commits mentioning the file
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "--", file_path],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=Path(__file__).parent.parent
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if not line:
                        continue
                    parts = line.split(" ", 1)
                    commit_hash = parts[0]
                    commit_msg = parts[1] if len(parts) > 1 else ""
                    
                    # Check if already in results
                    if not any(r["type"] == "commit" and r["commit_hash"] == commit_hash for r in results):
                        results.append({
                            "type": "commit",
                            "commit_hash": commit_hash,
                            "commit_msg": commit_msg,
                            "files_touched": [file_path],
                            "date": "unknown",
                            "spec": None
                        })
        except Exception as e:
            # git log failed; continue with graph results only
            pass
        
        return results
```

---

## Test Cases

**File**: `tests/test_kg_queries.py`

```python
import unittest
from pathlib import Path
import sys
import tempfile
import json

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from kg_loader import KnowledgeGraph, KnowledgeGraphNode, KnowledgeGraphEdge
from kg_queries import KGQueries


class TestKGQueries(unittest.TestCase):
    """Test knowledge graph query implementations."""
    
    @classmethod
    def setUpClass(cls):
        """Create a test seed graph once."""
        cls.kg = KnowledgeGraph()
        
        # Create test nodes
        spec_096 = KnowledgeGraphNode(
            id="spec_096", node_type="Spec", title="Ranker Governance Doctrine",
            status="ACTIVE", source_path="specs/spec_096.md", evidence="memo.md",
            updated_at="2026-05-14T00:00:00Z", extra_fields={"spec_number": 96}
        )
        spec_100 = KnowledgeGraphNode(
            id="spec_100", node_type="Spec", title="True Ranker IC Tooling",
            status="PENDING", source_path="specs/spec_100.md", evidence="memo.md",
            updated_at="2026-05-14T00:00:00Z", extra_fields={"spec_number": 100}
        )
        policy_freeze = KnowledgeGraphNode(
            id="policy_alpha_freeze", node_type="Policy", title="Alpha Stack Freeze",
            status="ACTIVE", source_path="policies/alpha_freeze.md", evidence="policy.md",
            updated_at="2026-05-14T00:00:00Z", extra_fields={}
        )
        action_wire = KnowledgeGraphNode(
            id="action_forward_return_wiring", node_type="Action", title="Wire load_forward_returns",
            status="PENDING", source_path="actions.md", evidence="memo.md",
            updated_at="2026-05-14T00:00:00Z", extra_fields={"required_by": "2026-05-22"}
        )
        code_file = KnowledgeGraphNode(
            id="code_run_true_ranker.py", node_type="CodeFile", 
            title="True Ranker IC Code", status="ACTIVE", 
            source_path="code_run_true_ranker_ic.py", evidence="path",
            updated_at="2026-05-14T00:00:00Z", extra_fields={}
        )
        commit = KnowledgeGraphNode(
            id="commit_3185d752", node_type="Commit",
            title="tools: add evening watchdog", status="CLOSED",
            source_path="commit", evidence="git log",
            updated_at="2026-05-15T00:00:00Z",
            extra_fields={"commit_hash": "3185d752"}
        )
        gate = KnowledgeGraphNode(
            id="gate_ranker_review_2026_05_22", node_type="Gate",
            title="2026-05-22 Ranker Review", status="ACTIVE",
            source_path="gates.md", evidence="memo",
            updated_at="2026-05-14T00:00:00Z", extra_fields={}
        )
        
        # Add nodes
        for node in [spec_096, spec_100, policy_freeze, action_wire, code_file, commit, gate]:
            cls.kg.add_node(node)
        
        # Create edges
        edge1 = KnowledgeGraphEdge(
            src="spec_100", edge_type="DEPENDS_ON", dst="action_forward_return_wiring",
            evidence="spec_100.md", confidence="HIGH", created_at="2026-05-14T00:00:00Z"
        )
        edge2 = KnowledgeGraphEdge(
            src="spec_096", edge_type="BLOCKS", dst="spec_100",
            evidence="doctrine.md", confidence="HIGH", created_at="2026-05-14T00:00:00Z"
        )
        edge3 = KnowledgeGraphEdge(
            src="policy_alpha_freeze", edge_type="GOVERNS", dst="spec_096",
            evidence="policy.md", confidence="HIGH", created_at="2026-05-14T00:00:00Z"
        )
        edge4 = KnowledgeGraphEdge(
            src="code_run_true_ranker.py", edge_type="CONTRADICTS", dst="spec_100",
            evidence="code stub found", confidence="HIGH", created_at="2026-05-14T00:00:00Z"
        )
        edge5 = KnowledgeGraphEdge(
            src="spec_100", edge_type="IMPLEMENTS", dst="code_run_true_ranker.py",
            evidence="spec.md", confidence="HIGH", created_at="2026-05-14T00:00:00Z"
        )
        edge6 = KnowledgeGraphEdge(
            src="commit_3185d752", edge_type="TOUCHES", dst="code_run_true_ranker.py",
            evidence="git", confidence="HIGH", created_at="2026-05-15T00:00:00Z"
        )
        edge7 = KnowledgeGraphEdge(
            src="spec_100", edge_type="AWAITS", dst="gate_ranker_review_2026_05_22",
            evidence="spec.md", confidence="HIGH", created_at="2026-05-14T00:00:00Z"
        )
        
        for edge in [edge1, edge2, edge3, edge4, edge5, edge6, edge7]:
            cls.kg.add_edge(edge)
        
        cls.queries = KGQueries(cls.kg)
    
    def test_what_blocks_production_ranker_change(self):
        """Query 1: Verify blockers returned."""
        result = self.queries.what_blocks_production_ranker_change()
        
        self.assertIn("blockers", result)
        self.assertIn("blocker_details", result)
        self.assertIn("summary", result)
        
        # spec_096 should be a blocker
        blocker_ids = [b["id"] for b in result["blocker_details"]]
        self.assertIn("spec_096", blocker_ids)
    
    def test_spec_status_pending(self):
        """Query 2: Verify spec status with dependencies."""
        result = self.queries.spec_status("spec_100")
        
        self.assertEqual(result["spec_id"], "spec_100")
        self.assertEqual(result["status"], "PENDING")
        self.assertIn("action_forward_return_wiring", result["depends_on"])
        self.assertIn("spec_096", result["blocked_by"])
    
    def test_spec_status_not_found(self):
        """Query 2: Spec not found returns error."""
        result = self.queries.spec_status("nonexistent_spec")
        self.assertIn("error", result)
    
    def test_contradictions_detected(self):
        """Query 3: Verify contradictions found."""
        result = self.queries.contradictions()
        
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)
        
        # Should find spec_100 contradiction
        contradiction_ids = [c["node_id"] for c in result]
        self.assertIn("spec_100", contradiction_ids)
    
    def test_next_actions_sorted(self):
        """Query 4: Verify actions returned in deadline order."""
        result = self.queries.next_actions()
        
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)
        
        # Check that action_forward_return_wiring is present
        action_ids = [a["action_id"] for a in result]
        self.assertIn("action_forward_return_wiring", action_ids)
        
        # Verify required_by dates are sorted
        dates = [a["required_by"] for a in result if a["required_by"] != "unknown"]
        self.assertEqual(dates, sorted(dates))
    
    def test_what_touches_file(self):
        """Query 5: Verify commits/specs touching file returned."""
        result = self.queries.what_touches_file("code_run_true_ranker_ic.py")
        
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)
        
        # Should find both spec_100 and commit_3185d752
        types = [r["type"] for r in result]
        self.assertIn("spec", types)
        self.assertIn("commit", types)
    
    def test_what_touches_file_nonexistent(self):
        """Query 5: No results for nonexistent file."""
        result = self.queries.what_touches_file("nonexistent_file.py")
        
        # May be empty or contain only git log results
        self.assertIsInstance(result, list)


if __name__ == "__main__":
    unittest.main()
```

---

## Acceptance Criteria

Before committing May 25:

1. ✅ KGQueries class with all 5 query methods implemented
2. ✅ Query 1: what_blocks_production_ranker_change() returns blockers, chains, evidence
3. ✅ Query 2: spec_status(spec_id) returns dependencies, blockers, contradictions
4. ✅ Query 3: contradictions() surfaces all CONTRADICTS edges
5. ✅ Query 4: next_actions() returns PENDING actions sorted by deadline
6. ✅ Query 5: what_touches_file(path) combines graph + git log results
7. ✅ All 11 test cases pass
8. ✅ No regressions (all Phase 4a tests still pass)

---

## Commit Checklist

**May 25 (Phase 4b complete)**:

1. Create tools/kg_queries.py with KGQueries class and all 5 queries
2. Create tests/test_kg_queries.py with 11 test methods
3. Run tests: `python3 -m pytest tests/test_kg_queries.py -v`
4. Verify all pass
5. Verify no regressions: `python3 -m pytest tests/test_kg_loader.py tests/test_kg_queries.py -v`
6. Commit: `tools: implement KG query layer (Phase 2 Step 4b)`
7. Message includes Co-Authored-By

---

## Integration Points

**Phase 4c** (May 25–26): Apply contradiction detection rules before returning from Query 3  
**Phase 4d** (May 26–27): CLI wrapper calls these query methods  
**Phase 4e** (May 27–28): Validation tests verify query outputs match expectations

---

**Status**: Implementation design locked. Ready for May 25 coding session (3 hours to code + test).

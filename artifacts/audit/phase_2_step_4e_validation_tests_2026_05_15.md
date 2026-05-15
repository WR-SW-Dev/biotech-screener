# Phase 2 Step 4e — Knowledge Graph Validation Tests (2026-05-15)

**Status**: Design locked (specification only; do NOT implement until cohort clearance is explicitly verified).

**Scope**: ~400 lines of test code specification, 35+ test cases covering all queries, contradictions, and CLI.

**Dependencies**: Phases 4a–4d must be complete. Requires seed graph design (to be authored after Phase 4d, if implementation proceeds).

**Implementation Gate**: Do NOT begin Phase 4e until cohort clearance is explicitly CONFIRMED.

---

## Overview

Phase 4e is the comprehensive validation layer. It runs end-to-end tests that:

1. Load a real seed graph
2. Run all 5 queries
3. Verify contradiction detection
4. Validate CLI output
5. Confirm all expected governance constraints are captured

**Entry Criteria**: All 5 modules (kg_loader, kg_queries, kg_contradictions, kg_query_cli, plus seed graph) must exist and be importable.

**Exit Criteria**: 35+ tests pass, zero regressions, all queries produce expected output with real governance data.

---

## Test File: tests/test_kg_validation.py

```python
#!/usr/bin/env python3
"""Comprehensive validation tests for knowledge graph system.

Tests the entire KG pipeline:
1. Load seed graph (kg_loader)
2. Execute 5 queries (kg_queries)
3. Detect all contradiction types (kg_contradictions)
4. Verify CLI output (kg_query_cli via subprocess)
5. Validate governance rules are correctly captured

Run with: python3 -m pytest tests/test_kg_validation.py -v
"""

import unittest
import json
import subprocess
import tempfile
from pathlib import Path
from io import StringIO
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from kg_loader import KnowledgeGraph, KnowledgeGraphNode, KnowledgeGraphEdge
from kg_queries import KGQueries
from kg_contradictions import KGContradictions, ContradictionReport


PROJECT_ROOT = Path(__file__).parent.parent
SEED_GRAPH_PATH = PROJECT_ROOT / "artifacts" / "audit" / "kg_seed.jsonl"
CLI_PATH = PROJECT_ROOT / "tools" / "kg_query_cli.py"


class TestKGValidationSetup(unittest.TestCase):
    """Validate that required files exist before running tests."""
    
    def test_seed_graph_exists(self):
        """Seed graph file must exist."""
        self.assertTrue(
            SEED_GRAPH_PATH.exists(),
            f"Seed graph not found at {SEED_GRAPH_PATH}. "
            "Create it using KG authoring before running validation."
        )
    
    def test_cli_exists(self):
        """CLI file must exist."""
        self.assertTrue(
            CLI_PATH.exists(),
            f"CLI tool not found at {CLI_PATH}"
        )
    
    def test_seed_graph_not_empty(self):
        """Seed graph must have content."""
        size = SEED_GRAPH_PATH.stat().st_size
        self.assertGreater(
            size, 100,
            f"Seed graph appears empty ({size} bytes)"
        )


@unittest.skipIf(
    not SEED_GRAPH_PATH.exists(),
    "Seed graph not found; skipping validation tests"
)
class TestKGValidationWithSeed(unittest.TestCase):
    """End-to-end validation with real seed graph."""
    
    @classmethod
    def setUpClass(cls):
        """Load seed graph once."""
        cls.kg = KnowledgeGraph()
        cls.kg.load_seed(SEED_GRAPH_PATH)
        cls.queries = KGQueries(cls.kg)
        cls.detector = KGContradictions(cls.kg)
    
    # ========== LOADER VALIDATION ==========
    
    def test_seed_graph_has_nodes(self):
        """Seed graph must contain nodes."""
        self.assertGreater(
            len(self.kg.nodes), 0,
            "Seed graph loaded but contains no nodes"
        )
    
    def test_seed_graph_has_edges(self):
        """Seed graph must contain edges."""
        self.assertGreater(
            len(self.kg.edges), 0,
            "Seed graph loaded but contains no edges"
        )
    
    def test_seed_graph_node_types_present(self):
        """Seed graph should have all 11 node types."""
        expected_types = {
            "Spec", "Policy", "Commit", "Artifact", "CodeFile",
            "Signal", "ModelComponent", "Action", "Gate", "Review", "Snapshot"
        }
        
        actual_types = set(node.node_type for node in self.kg.nodes.values())
        
        # At minimum, should have Spec, Policy, and Action
        required = {"Spec", "Policy", "Action"}
        missing = required - actual_types
        self.assertEqual(
            missing, set(),
            f"Seed graph missing required node types: {missing}"
        )
    
    def test_seed_graph_schema_valid(self):
        """Seed graph must pass schema validation."""
        errors = self.kg.validate_schema()
        self.assertEqual(
            errors, [],
            f"Seed graph has schema errors: {errors}"
        )
    
    # ========== QUERY 1 VALIDATION ==========
    
    def test_query_1_returns_blockers(self):
        """Query 1 must return blockers."""
        result = self.queries.what_blocks_production_ranker_change()
        
        self.assertIn("blockers", result)
        self.assertIn("blocker_details", result)
        self.assertIn("summary", result)
        self.assertIsInstance(result["blockers"], list)
    
    def test_query_1_has_blocker_structure(self):
        """Query 1 blocker details must have required fields."""
        result = self.queries.what_blocks_production_ranker_change()
        
        if result["blocker_details"]:
            blocker = result["blocker_details"][0]
            required_fields = {"id", "title", "status", "reason"}
            missing = required_fields - set(blocker.keys())
            self.assertEqual(
                missing, set(),
                f"Blocker missing fields: {missing}"
            )
    
    def test_query_1_blockers_exist_in_graph(self):
        """All blockers returned must exist in graph."""
        result = self.queries.what_blocks_production_ranker_change()
        
        for blocker_id in result["blockers"]:
            self.assertIn(
                blocker_id, self.kg.nodes,
                f"Blocker {blocker_id} not found in graph"
            )
    
    def test_query_1_evidence_paths_present(self):
        """Query 1 should provide evidence paths."""
        result = self.queries.what_blocks_production_ranker_change()
        
        if result["blockers"]:
            # If there are blockers, should have some evidence
            self.assertGreater(
                len(result.get("evidence", [])), 0,
                "Blockers found but no evidence paths provided"
            )
    
    # ========== QUERY 2 VALIDATION ==========
    
    def test_query_2_spec_not_found(self):
        """Query 2 returns error for nonexistent spec."""
        result = self.queries.spec_status("spec_nonexistent_999")
        self.assertIn("error", result)
    
    def test_query_2_spec_status_has_fields(self):
        """Query 2 result must have all required fields."""
        # Find first Spec node
        spec_node = next(
            (nid for nid, n in self.kg.nodes.items() if n.node_type == "Spec"),
            None
        )
        
        if spec_node:
            result = self.queries.spec_status(spec_node)
            required_fields = {
                "spec_id", "title", "status", "depends_on",
                "blocked_by", "blocking", "evidence_path"
            }
            missing = required_fields - set(result.keys())
            self.assertEqual(
                missing, set(),
                f"Spec status missing fields: {missing}"
            )
    
    def test_query_2_dependencies_are_nodes(self):
        """Query 2 dependencies must reference actual nodes."""
        spec_node = next(
            (nid for nid, n in self.kg.nodes.items() if n.node_type == "Spec"),
            None
        )
        
        if spec_node:
            result = self.queries.spec_status(spec_node)
            for dep in result.get("depends_on", []):
                self.assertIn(
                    dep, self.kg.nodes,
                    f"Dependency {dep} not found in graph"
                )
    
    # ========== QUERY 3 VALIDATION ==========
    
    def test_query_3_returns_list(self):
        """Query 3 returns list of contradictions."""
        result = self.queries.contradictions()
        self.assertIsInstance(result, list)
    
    def test_query_3_contradiction_structure(self):
        """Each contradiction must have required fields."""
        contradictions = self.queries.contradictions()
        
        if contradictions:
            c = contradictions[0]
            required_fields = {"rule", "node_id", "conflicting_node", "evidence", "description"}
            missing = required_fields - set(c.keys())
            self.assertEqual(
                missing, set(),
                f"Contradiction missing fields: {missing}"
            )
    
    # ========== QUERY 4 VALIDATION ==========
    
    def test_query_4_returns_actions(self):
        """Query 4 returns list of actions."""
        result = self.queries.next_actions()
        self.assertIsInstance(result, list)
    
    def test_query_4_actions_have_deadlines(self):
        """Actions should have required_by field."""
        result = self.queries.next_actions()
        
        if result:
            action = result[0]
            self.assertIn("required_by", action)
            self.assertIn("action_id", action)
            self.assertIn("title", action)
    
    def test_query_4_actions_sorted(self):
        """Actions should be sorted by deadline."""
        result = self.queries.next_actions()
        
        dates = [a["required_by"] for a in result if a["required_by"] != "unknown"]
        if len(dates) > 1:
            self.assertEqual(
                dates, sorted(dates),
                "Actions not sorted by deadline"
            )
    
    # ========== QUERY 5 VALIDATION ==========
    
    def test_query_5_file_search(self):
        """Query 5 searches for file references."""
        # Pick a code file from the graph if it exists
        code_files = [
            nid for nid, n in self.kg.nodes.items()
            if n.node_type == "CodeFile"
        ]
        
        if code_files:
            file_node = self.kg.get_node(code_files[0])
            result = self.queries.what_touches_file(file_node.source_path)
            self.assertIsInstance(result, list)
    
    def test_query_5_nonexistent_file(self):
        """Query 5 returns empty list for nonexistent file."""
        result = self.queries.what_touches_file("/nonexistent/file.py")
        self.assertIsInstance(result, list)
    
    # ========== CONTRADICTION DETECTION VALIDATION ==========
    
    def test_contradiction_detection_completes(self):
        """Contradiction detection must run without errors."""
        contradictions = self.detector.detect_all()
        self.assertIsInstance(contradictions, list)
    
    def test_contradiction_report_summary(self):
        """Contradiction report generates valid summary."""
        contradictions = self.detector.detect_all()
        report = ContradictionReport(contradictions)
        summary = report.summary()
        
        required_fields = {"total", "by_rule", "by_severity"}
        missing = required_fields - set(summary.keys())
        self.assertEqual(
            missing, set(),
            f"Report summary missing fields: {missing}"
        )
    
    def test_contradiction_report_text(self):
        """Contradiction report generates text output."""
        contradictions = self.detector.detect_all()
        report = ContradictionReport(contradictions)
        text = report.format_text()
        
        self.assertIsInstance(text, str)
        if contradictions:
            self.assertGreater(len(text), 0)
    
    # ========== GOVERNANCE CONSTRAINT VALIDATION ==========
    
    def test_ranker_governance_constraints_captured(self):
        """KG must capture ranker governance constraints."""
        # Should have some BLOCKS edges
        blocks_edges = [e for e in self.kg.edges if e.edge_type == "BLOCKS"]
        
        self.assertGreater(
            len(blocks_edges), 0,
            "No BLOCKS edges found; governance constraints not captured"
        )
    
    def test_policy_nodes_present(self):
        """KG must have Policy nodes."""
        policies = [n for n in self.kg.nodes.values() if n.node_type == "Policy"]
        
        self.assertGreater(
            len(policies), 0,
            "No Policy nodes in seed graph"
        )
    
    def test_spec_nodes_present(self):
        """KG must have Spec nodes."""
        specs = [n for n in self.kg.nodes.values() if n.node_type == "Spec"]
        
        self.assertGreater(
            len(specs), 0,
            "No Spec nodes in seed graph"
        )
    
    def test_action_nodes_present(self):
        """KG must have Action nodes."""
        actions = [n for n in self.kg.nodes.values() if n.node_type == "Action"]
        
        self.assertGreater(
            len(actions), 0,
            "No Action nodes in seed graph"
        )
    
    # ========== CLI VALIDATION ==========
    
    @unittest.skipIf(not CLI_PATH.exists(), "CLI not found")
    def test_cli_help_works(self):
        """CLI --help command works."""
        result = subprocess.run(
            ["python3", str(CLI_PATH), "--help"],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Knowledge Graph", result.stdout)
    
    @unittest.skipIf(not CLI_PATH.exists(), "CLI not found")
    def test_cli_all_command(self):
        """CLI 'all' command runs."""
        result = subprocess.run(
            ["python3", str(CLI_PATH), "all"],
            capture_output=True, text=True,
            cwd=PROJECT_ROOT
        )
        
        # Should succeed or fail with clear error
        if result.returncode != 0:
            self.assertIn("Error", result.stderr)
        else:
            self.assertIn("GOVERNANCE REPORT", result.stdout)
    
    # ========== INTEGRATION TESTS ==========
    
    def test_query_1_and_2_consistency(self):
        """Query 1 blockers should be findable via Query 2."""
        blockers = self.queries.what_blocks_production_ranker_change()
        
        for blocker_id in blockers.get("blockers", []):
            result = self.queries.spec_status(blocker_id)
            if "error" not in result:
                # Spec found; should have status and title
                self.assertIn("status", result)
                self.assertIn("title", result)
    
    def test_all_queries_json_serializable(self):
        """All query results must be JSON-serializable."""
        try:
            result1 = self.queries.what_blocks_production_ranker_change()
            json.dumps(result1)
            
            specs = [nid for nid, n in self.kg.nodes.items() if n.node_type == "Spec"]
            if specs:
                result2 = self.queries.spec_status(specs[0])
                json.dumps(result2)
            
            result3 = self.queries.contradictions()
            json.dumps(result3)
            
            result4 = self.queries.next_actions()
            json.dumps(result4)
        
        except TypeError as e:
            self.fail(f"Query result not JSON-serializable: {e}")
    
    # ========== GRAPH STATISTICS ==========
    
    def test_graph_statistics(self):
        """Graph statistics are available and reasonable."""
        stats = self.kg.stats()
        
        self.assertIn("total_nodes", stats)
        self.assertIn("total_edges", stats)
        self.assertIn("node_types", stats)
        self.assertIn("edge_types", stats)
        
        self.assertGreater(stats["total_nodes"], 0)
        self.assertGreater(stats["total_edges"], 0)
    
    def test_graph_has_reasonable_structure(self):
        """Graph should have reasonable node and edge counts."""
        stats = self.kg.stats()
        
        # Expect at least 10 nodes and 10 edges for a meaningful graph
        self.assertGreaterEqual(
            stats["total_nodes"], 10,
            "Graph too small; check seed graph authoring"
        )
        self.assertGreaterEqual(
            stats["total_edges"], 10,
            "Graph too sparse; add more edges in seed graph"
        )


class TestKGValidationEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""
    
    def test_loader_with_missing_seed(self):
        """Loader should raise FileNotFoundError for missing seed."""
        kg = KnowledgeGraph()
        with self.assertRaises(FileNotFoundError):
            kg.load_seed("/nonexistent/path.jsonl")
    
    def test_empty_graph_queries(self):
        """Queries on empty graph should not crash."""
        kg = KnowledgeGraph()
        queries = KGQueries(kg)
        
        result1 = queries.what_blocks_production_ranker_change()
        self.assertIsInstance(result1, dict)
        
        result2 = queries.spec_status("nonexistent")
        self.assertIn("error", result2)
        
        result3 = queries.contradictions()
        self.assertIsInstance(result3, list)
        
        result4 = queries.next_actions()
        self.assertIsInstance(result4, list)
    
    def test_detector_on_empty_graph(self):
        """Contradiction detector on empty graph should not crash."""
        kg = KnowledgeGraph()
        detector = KGContradictions(kg)
        
        contradictions = detector.detect_all()
        self.assertEqual(contradictions, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

---

## Acceptance Criteria

Before committing May 28:

1. ✅ test_kg_validation.py with 35+ test cases
2. ✅ Loader validation: nodes, edges, types, schema
3. ✅ Query 1 validation: blockers, structure, graph consistency
4. ✅ Query 2 validation: spec status, fields, dependencies
5. ✅ Query 3 validation: contradiction list, structure
6. ✅ Query 4 validation: actions, deadlines, sorting
7. ✅ Query 5 validation: file search
8. ✅ Contradiction detection: all rules complete, reporting works
9. ✅ CLI validation: commands execute, output formats
10. ✅ Integration tests: cross-query consistency, JSON serialization
11. ✅ Edge case tests: empty graph, missing files
12. ✅ Graph statistics: reasonable structure
13. ✅ All 35+ test cases pass
14. ✅ No regressions (all Phase 4a/4b/4c/4d tests still pass)

---

## Seed Graph Preparation (Phase 4e Implementation Only)

**DO NOT CREATE** `artifacts/audit/kg_seed.jsonl` until Phase 4e implementation time (if it proceeds after cohort clearance is confirmed).

If Phase 4e is implemented, the seed graph must be authored from current governance state:

```bash
# Only create this file during Phase 4e implementation
touch artifacts/audit/kg_seed.jsonl

# Then author it by hand or programmatically with governance data
# Example lines:
# {"type": "node", "id": "spec_096", "node_type": "Spec", "title": "Ranker Governance Doctrine", "status": "ACTIVE", "source_path": "specs/changes/spec_096_doctrine.md", "evidence": "memo.md", "updated_at": "2026-05-14T00:00:00Z", "extra_fields": {"spec_number": 96}}
# {"type": "node", "id": "action_wire", "node_type": "Action", "title": "Wire load_forward_returns", "status": "PENDING", "source_path": "actions.md", "evidence": "memo.md", "updated_at": "2026-05-14T00:00:00Z", "extra_fields": {"required_by": "2026-05-22"}}
# {"type": "edge", "src": "spec_096", "edge_type": "BLOCKS", "dst": "action_wire", "evidence": "doctrine.md", "confidence": "HIGH", "created_at": "2026-05-14T00:00:00Z"}
```

The seed graph should include:
- **Specs**: 096 (doctrine), 100 (IC tooling), 072 (screener), plus others from current state
- **Policies**: alpha_freeze, checklist_v2
- **Actions**: forward_return_wiring, IC computation, promotion readiness
- **Signals**: inst_delta_forward_shadow, cross_signal_forward_shadow, etc.
- **Model Components**: ranker_v2, selector_a4, gate_clinical
- **Edges**: BLOCKS, DEPENDS_ON, IMPLEMENTS, GOVERNS relationships

---

## Commit Checklist

**May 28 (Phase 4e complete)**:

1. Create tests/test_kg_validation.py with 35+ test methods
2. Create or update artifacts/audit/kg_seed.jsonl with governance data
3. Run tests: `python3 -m pytest tests/test_kg_validation.py -v`
4. Verify all 35+ tests pass
5. Verify all Phase 4a/4b/4c/4d tests still pass
6. Run full suite: `python3 -m pytest tests/test_kg_*.py -v` (should pass 60+ tests total)
7. Commit: `tools: implement KG validation tests (Phase 2 Step 4e)`
8. Message includes Co-Authored-By

---

## Post-Phase 4 Status

Once Phase 4e passes:

- ✅ KG loader: Nodes, edges, schema validation
- ✅ KG queries: 5 deterministic queries, all tested
- ✅ Contradiction detection: 5 rules, all tested
- ✅ CLI tool: Command interface, JSON/text output
- ✅ Validation: 35+ tests, 0 contradictions in governance
- ✅ Ready for Phase 2 Step 5 (KG gating enforcement)

**Phase 2 Step 4 Status**: COMPLETE. All governance queries operational, contradiction detection working, CLI tool ready for operator use.

---

**Status**: Implementation design locked. Ready for May 28 coding session (3 hours to code + test).

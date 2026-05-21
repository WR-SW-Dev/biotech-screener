"""
Phase 2 Step 4e: Knowledge Graph Integration Tests

Contract validation across all components:
- KnowledgeGraph loader (4a)
- Query patterns (4b)
- Contradiction detection (4c)

Tests verify end-to-end governance scenarios and component interactions.
"""

import json
import tempfile
import unittest
from pathlib import Path

from tools.kg_contradictions import ContradictionSeverity, run_contradiction_detection
from tools.kg_loader import KnowledgeGraph, KnowledgeGraphEdge, KnowledgeGraphNode
from tools.kg_queries import (
    WhatBlocksRanker,
    WhatContradicts,
    WhatEvidence,
    WhatPromotes,
)


class TestLoaderQueryContract(unittest.TestCase):
    """Test contract between loader (4a) and queries (4b)."""

    def setUp(self):
        """Build a realistic governance graph."""
        self.graph = KnowledgeGraph()

        # Define nodes
        nodes = [
            ("policy_freeze", "Policy", "Alpha Freeze", "ACTIVE", "policies/freeze.md"),
            ("spec_089", "Spec", "KG Pilot", "PENDING", "specs/spec_089.md"),
            ("spec_100", "Spec", "IC Tooling", "PENDING", "specs/spec_100.md"),
            ("gate_ic_coverage", "Gate", "IC Coverage ≥100%", "PENDING", "gates/ic.py"),
            ("review_governance", "Review", "Governance Review", "PENDING", "reviews/gov.md"),
            ("module_ranker", "ModelComponent", "Ranker v2", "ACTIVE", "ranker.py"),
            ("action_promote_spec_089", "Action", "Promote Spec 089", "PENDING", "actions/promote_089.md"),
        ]

        for node_id, node_type, title, status, source_path in nodes:
            self.graph.add_node(
                KnowledgeGraphNode(
                    id=node_id,
                    node_type=node_type,
                    title=title,
                    status=status,
                    source_path=source_path,
                    evidence="",
                    updated_at="2026-05-20T00:00:00Z",
                    extra_fields={},
                )
            )

        # Define edges (governance relationships)
        edges = [
            ("policy_freeze", "BLOCKS", "module_ranker"),
            ("spec_089", "DEPENDS_ON", "policy_freeze"),
            ("spec_100", "DOCUMENTS", "action_promote_spec_089"),
            ("gate_ic_coverage", "GATES", "spec_100"),
            ("review_governance", "REQUIRES", "spec_089"),
        ]

        for src, edge_type, dst in edges:
            self.graph.add_edge(
                KnowledgeGraphEdge(
                    src=src,
                    edge_type=edge_type,
                    dst=dst,
                    evidence="",
                    confidence="HIGH",
                    created_at="2026-05-20T00:00:00Z",
                )
            )

    def test_loader_output_feeds_queries(self):
        """Contract: Loader graph is valid input to all query patterns."""
        # All queries should execute without error on loaded graph
        result_blocks = WhatBlocksRanker.query(self.graph, "module_ranker")
        result_contradicts = WhatContradicts.query(self.graph, "spec_089")
        result_evidence = WhatEvidence.query(self.graph, "action_promote_spec_089")
        result_promotes = WhatPromotes.query(self.graph, "spec_089")

        self.assertIn("blockers", result_blocks)
        self.assertIn("contradictions", result_contradicts)
        self.assertIn("evidence_chain", result_evidence)
        self.assertIn("promotion_gates", result_promotes)

    def test_what_blocks_ranker_finds_policy_freeze(self):
        """Query 1: WhatBlocksRanker correctly identifies policy blocking ranker."""
        result = WhatBlocksRanker.query(self.graph, "module_ranker")
        self.assertFalse(result["can_change_ranker"])
        self.assertGreater(len(result["blockers"]), 0)
        self.assertEqual(result["blockers"][0]["blocker_id"], "policy_freeze")

    def test_what_contradicts_empty_for_valid_spec(self):
        """Query 2: WhatContradicts returns empty when no contradictions."""
        result = WhatContradicts.query(self.graph, "spec_089")
        self.assertFalse(result["has_conflicts"])
        self.assertEqual(result["contradiction_count"], 0)

    def test_what_evidence_traces_full_chain(self):
        """Query 3: WhatEvidence returns complete evidence chain."""
        result = WhatEvidence.query(self.graph, "action_promote_spec_089")
        self.assertGreater(result["chain_length"], 0)
        # Should include spec_100 as evidence source
        node_ids = [e["node_id"] for e in result["evidence_chain"]]
        self.assertIn("spec_100", node_ids)

    def test_what_promotes_identifies_gates(self):
        """Query 4: WhatPromotes identifies blocking gates for spec."""
        result = WhatPromotes.query(self.graph, "spec_089")
        # spec_089 requires review_governance gate
        gate_ids = [g["gate_id"] for g in result["promotion_gates"]]
        self.assertIn("review_governance", gate_ids)


class TestContradictionDetectorContract(unittest.TestCase):
    """Test contract between queries (4b) and detector (4c)."""

    def test_detector_accepts_valid_graph(self):
        """Contract: Detector accepts loader output."""
        graph = KnowledgeGraph()
        graph.add_node(
            KnowledgeGraphNode(
                id="spec_valid",
                node_type="Spec",
                title="Valid Spec",
                status="ACTIVE",
                source_path="specs/valid.md",
                evidence="",
                updated_at="2026-05-20T00:00:00Z",
                extra_fields={},
            )
        )

        result = run_contradiction_detection(graph)
        self.assertIn("health", result)
        self.assertEqual(result["health"], "CLEAR")

    def test_detector_finds_hard_contradictions(self):
        """Contract: Detector identifies C1 violations from graph."""
        graph = KnowledgeGraph()

        # Create a contradiction: FROZEN spec requiring ACTIVE spec
        graph.add_node(
            KnowledgeGraphNode(
                id="spec_frozen",
                node_type="Spec",
                title="Frozen",
                status="FROZEN",
                source_path="specs/frozen.md",
                evidence="",
                updated_at="2026-05-20T00:00:00Z",
                extra_fields={},
            )
        )

        graph.add_node(
            KnowledgeGraphNode(
                id="spec_active",
                node_type="Spec",
                title="Active",
                status="ACTIVE",
                source_path="specs/active.md",
                evidence="",
                updated_at="2026-05-20T00:00:00Z",
                extra_fields={},
            )
        )

        graph.add_edge(
            KnowledgeGraphEdge(
                src="spec_frozen",
                edge_type="REQUIRES",
                dst="spec_active",
                evidence="",
                confidence="HIGH",
                created_at="2026-05-20T00:00:00Z",
            )
        )

        result = run_contradiction_detection(graph)
        self.assertGreater(result["critical"], 0)
        self.assertNotEqual(result["health"], "CLEAR")


class TestLoaderSeedFormat(unittest.TestCase):
    """Test loader seed file format and parsing."""

    def test_load_seed_from_jsonl(self):
        """Loader contract: Accept JSONL seed format."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            # Write seed nodes
            f.write(
                json.dumps(
                    {
                        "type": "node",
                        "id": "spec_test",
                        "node_type": "Spec",
                        "title": "Test Spec",
                        "status": "ACTIVE",
                        "source_path": "specs/test.md",
                        "evidence": "",
                        "updated_at": "2026-05-20T00:00:00Z",
                        "extra_fields": {},
                    }
                )
                + "\n"
            )

            f.write(
                json.dumps(
                    {
                        "type": "node",
                        "id": "gate_test",
                        "node_type": "Gate",
                        "title": "Test Gate",
                        "status": "PENDING",
                        "source_path": "gates/test.py",
                        "evidence": "",
                        "updated_at": "2026-05-20T00:00:00Z",
                        "extra_fields": {},
                    }
                )
                + "\n"
            )

            # Write seed edge
            f.write(
                json.dumps(
                    {
                        "type": "edge",
                        "src": "gate_test",
                        "edge_type": "GATES",
                        "dst": "spec_test",
                        "evidence": "",
                        "confidence": "HIGH",
                        "created_at": "2026-05-20T00:00:00Z",
                    }
                )
                + "\n"
            )

            temp_path = f.name

        try:
            graph = KnowledgeGraph()
            graph.load_seed(temp_path)

            self.assertEqual(len(graph.nodes), 2)
            self.assertEqual(len(graph.edges), 1)
            self.assertIn("spec_test", graph.nodes)
            self.assertIn("gate_test", graph.nodes)
        finally:
            Path(temp_path).unlink()

    def test_load_seed_with_comments(self):
        """Loader: Skip comments and empty lines in seed."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("# Comment line\n")
            f.write("\n")  # Empty line
            f.write(
                json.dumps(
                    {
                        "type": "node",
                        "id": "spec_with_comments",
                        "node_type": "Spec",
                        "title": "Spec",
                        "status": "ACTIVE",
                        "source_path": "specs/test.md",
                        "evidence": "",
                        "updated_at": "2026-05-20T00:00:00Z",
                        "extra_fields": {},
                    }
                )
                + "\n"
            )

            temp_path = f.name

        try:
            graph = KnowledgeGraph()
            graph.load_seed(temp_path)
            self.assertEqual(len(graph.nodes), 1)
        finally:
            Path(temp_path).unlink()


class TestEndToEndGovernanceScenario(unittest.TestCase):
    """Test realistic governance scenario: Spec 089 KG pilot promotion path."""

    def test_spec_089_promotion_scenario(self):
        """Scenario: Trace Spec 089 promotion requirements and blockers."""
        graph = KnowledgeGraph()

        # Build realistic governance state for Spec 089
        nodes_data = [
            ("spec_089", "Spec", "KG Pilot Phase 1", "PENDING", "specs/spec_089.md"),
            ("spec_100", "Spec", "IC Tooling", "PENDING", "specs/spec_100.md"),
            ("policy_freeze", "Policy", "Alpha Freeze", "ACTIVE", "policies/freeze.md"),
            ("gate_kg_tests", "Gate", "KG Tests ≥60", "PENDING", "gates/kg_tests.py"),
            ("gate_contradictions", "Gate", "No Contradictions", "PENDING", "gates/no_contradictions.py"),
            ("review_kg_spec", "Review", "KG Spec Review", "PENDING", "reviews/kg.md"),
            ("action_promote_089", "Action", "Promote Spec 089", "PENDING", "actions/promote.md"),
        ]

        for node_id, node_type, title, status, source_path in nodes_data:
            graph.add_node(
                KnowledgeGraphNode(
                    id=node_id,
                    node_type=node_type,
                    title=title,
                    status=status,
                    source_path=source_path,
                    evidence="",
                    updated_at="2026-05-20T00:00:00Z",
                    extra_fields={},
                )
            )

        # Promotion gates (with documentation to avoid C4 soft contradictions)
        edges_data = [
            ("gate_kg_tests", "GATES", "spec_089"),
            ("gate_contradictions", "GATES", "spec_089"),
            ("review_kg_spec", "REQUIRES", "spec_089"),
            ("policy_freeze", "BLOCKS", "spec_089"),  # Alpha freeze blocks all promotions
            ("spec_089", "DOCUMENTS", "action_promote_089"),
            # Document the pending specs/gates to satisfy C4 requirement
            ("spec_089", "DEPENDS_ON", "spec_100"),
            ("action_promote_089", "DEPENDS_ON", "spec_089"),
            ("gate_kg_tests", "DOCUMENTS", "spec_089"),
            ("gate_contradictions", "DOCUMENTS", "spec_089"),
            ("review_kg_spec", "DOCUMENTS", "spec_089"),
            ("spec_100", "DEPENDS_ON", "spec_089"),
        ]

        for src, edge_type, dst in edges_data:
            graph.add_edge(
                KnowledgeGraphEdge(
                    src=src,
                    edge_type=edge_type,
                    dst=dst,
                    evidence="",
                    confidence="HIGH",
                    created_at="2026-05-20T00:00:00Z",
                )
            )

        # Test: What blocks Spec 089 promotion?
        blocks_result = WhatBlocksRanker.query(graph, "spec_089")
        self.assertFalse(blocks_result["can_change_ranker"])  # Alpha freeze blocks

        # Test: What gates must pass?
        promotes_result = WhatPromotes.query(graph, "spec_089")
        gate_names = [g["gate_id"] for g in promotes_result["promotion_gates"]]
        self.assertIn("gate_kg_tests", gate_names)
        self.assertIn("gate_contradictions", gate_names)

        # Test: Graph is contradiction-free
        contradictions_result = run_contradiction_detection(graph)
        # Should be CLEAR: all PENDING nodes have DOCUMENTS or DEPENDS_ON edges
        self.assertEqual(contradictions_result["health"], "CLEAR")


class TestErrorHandlingIntegration(unittest.TestCase):
    """Test error handling across components."""

    def test_invalid_node_type_rejected(self):
        """Contract: Invalid node_type is rejected at creation."""
        with self.assertRaises(ValueError):
            KnowledgeGraphNode(
                id="bad_node",
                node_type="InvalidType",
                title="Bad",
                status="ACTIVE",
                source_path="bad.md",
                evidence="",
                updated_at="2026-05-20T00:00:00Z",
                extra_fields={},
            )

    def test_invalid_edge_type_rejected(self):
        """Contract: Invalid edge_type is rejected at creation."""
        with self.assertRaises(ValueError):
            KnowledgeGraphEdge(
                src="a",
                edge_type="InvalidEdgeType",
                dst="b",
                evidence="",
                confidence="HIGH",
                created_at="2026-05-20T00:00:00Z",
            )

    def test_duplicate_node_rejected(self):
        """Contract: Duplicate node IDs are rejected."""
        graph = KnowledgeGraph()
        node = KnowledgeGraphNode(
            id="dup",
            node_type="Spec",
            title="First",
            status="ACTIVE",
            source_path="first.md",
            evidence="",
            updated_at="2026-05-20T00:00:00Z",
            extra_fields={},
        )
        graph.add_node(node)

        with self.assertRaises(ValueError) as context:
            graph.add_node(
                KnowledgeGraphNode(
                    id="dup",
                    node_type="Spec",
                    title="Second",
                    status="ACTIVE",
                    source_path="second.md",
                    evidence="",
                    updated_at="2026-05-20T00:00:00Z",
                    extra_fields={},
                )
            )

        self.assertIn("Duplicate node ID", str(context.exception))


if __name__ == "__main__":
    unittest.main()

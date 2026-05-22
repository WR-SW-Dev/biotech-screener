"""
Phase 2 Step 4b: Knowledge Graph Query Tests

8 test cases for the four query patterns:
1. What_Blocks_Ranker
2. What_Contradicts
3. What_Evidence
4. What_Promotes
"""

import unittest

from tools.kg_loader import KnowledgeGraph, KnowledgeGraphEdge, KnowledgeGraphNode
from tools.kg_queries import WhatBlocksRanker, WhatContradicts, WhatEvidence, WhatPromotes, run_all_queries


class TestWhatBlocksRanker(unittest.TestCase):
    """Test blockers for ranker module."""

    def setUp(self):
        """Create test graph with ranker blocker scenario."""
        self.graph = KnowledgeGraph()

        # Create nodes
        self.graph.add_node(
            KnowledgeGraphNode(
                id="module_ranker",
                node_type="ModelComponent",
                title="Ranker v2 (2-feature)",
                status="ACTIVE",
                source_path="ranker.py",
                evidence="",
                updated_at="2026-05-20T00:00:00Z",
                extra_fields={},
            )
        )

        self.graph.add_node(
            KnowledgeGraphNode(
                id="policy_alpha_freeze",
                node_type="Policy",
                title="Alpha Stack Frozen",
                status="ACTIVE",
                source_path="policies/alpha_freeze.md",
                evidence="policy_alpha_freeze_2026_04_04.md",
                updated_at="2026-04-04T00:00:00Z",
                extra_fields={},
            )
        )

        # Create BLOCKS edge
        self.graph.add_edge(
            KnowledgeGraphEdge(
                src="policy_alpha_freeze",
                edge_type="BLOCKS",
                dst="module_ranker",
                evidence="Promotion requires Checklist v2",
                confidence="HIGH",
                created_at="2026-04-04T00:00:00Z",
            )
        )

    def test_blockers_found(self):
        """What_Blocks_Ranker finds blocking policies."""
        result = WhatBlocksRanker.query(self.graph, "module_ranker")
        self.assertEqual(result["blocker_count"], 1)
        self.assertFalse(result["can_change_ranker"])
        self.assertEqual(result["blockers"][0]["blocker_id"], "policy_alpha_freeze")

    def test_no_blockers(self):
        """What_Blocks_Ranker returns empty when no blockers."""
        result = WhatBlocksRanker.query(self.graph, "nonexistent_node")
        self.assertEqual(result["blocker_count"], 0)
        self.assertTrue(result["can_change_ranker"])


class TestWhatContradicts(unittest.TestCase):
    """Test contradictions between specs."""

    def setUp(self):
        """Create test graph with contradiction."""
        self.graph = KnowledgeGraph()

        # Create specs
        self.graph.add_node(
            KnowledgeGraphNode(
                id="spec_057",
                node_type="Spec",
                title="Clinical Quality Score",
                status="ACTIVE",
                source_path="specs/changes/spec_057.md",
                evidence="",
                updated_at="2026-04-13T00:00:00Z",
                extra_fields={"spec_number": 57},
            )
        )

        self.graph.add_node(
            KnowledgeGraphNode(
                id="spec_069",
                node_type="Spec",
                title="Module 2 v2 Schema Restore",
                status="PENDING",
                source_path="specs/changes/spec_069.md",
                evidence="",
                updated_at="2026-04-28T00:00:00Z",
                extra_fields={"spec_number": 69},
            )
        )

        # Create CONTRADICTS edge
        self.graph.add_edge(
            KnowledgeGraphEdge(
                src="spec_057",
                edge_type="CONTRADICTS",
                dst="spec_069",
                evidence="Clinical scoring conflicts with module 2 schema",
                confidence="MEDIUM",
                created_at="2026-04-28T00:00:00Z",
            )
        )

    def test_contradictions_found(self):
        """What_Contradicts finds conflicting specs."""
        result = WhatContradicts.query(self.graph, "spec_057")
        self.assertEqual(result["contradiction_count"], 1)
        self.assertTrue(result["has_conflicts"])

    def test_both_directions(self):
        """What_Contradicts finds both incoming and outgoing contradictions."""
        result = WhatContradicts.query(self.graph, "spec_069")
        self.assertEqual(result["contradiction_count"], 1)  # incoming contradiction


class TestWhatEvidence(unittest.TestCase):
    """Test evidence chain for decisions."""

    def setUp(self):
        """Create test graph with evidence chain."""
        self.graph = KnowledgeGraph()

        # Create decision node
        self.graph.add_node(
            KnowledgeGraphNode(
                id="decision_promote_spec_057",
                node_type="Action",
                title="Promote Spec 057 Clinical Score",
                status="PENDING",
                source_path="decisions/promote_spec_057.md",
                evidence="",
                updated_at="2026-05-01T00:00:00Z",
                extra_fields={},
            )
        )

        # Create supporting spec
        self.graph.add_node(
            KnowledgeGraphNode(
                id="spec_057",
                node_type="Spec",
                title="Clinical Quality Score",
                status="CLOSED",
                source_path="specs/changes/spec_057.md",
                evidence="clinical_quality_score_2026_04_13.md",
                updated_at="2026-04-13T00:00:00Z",
                extra_fields={"spec_number": 57},
            )
        )

        # Create evidence link
        self.graph.add_edge(
            KnowledgeGraphEdge(
                src="spec_057",
                edge_type="DOCUMENTS",
                dst="decision_promote_spec_057",
                evidence="Spec 057 provides evidence for promotion",
                confidence="HIGH",
                created_at="2026-05-01T00:00:00Z",
            )
        )

    def test_evidence_chain(self):
        """What_Evidence traces evidence back to sources."""
        result = WhatEvidence.query(self.graph, "decision_promote_spec_057")
        self.assertGreater(result["chain_length"], 0)
        self.assertIn("specs/changes/spec_057.md", result["sources"])

    def test_chain_includes_target(self):
        """What_Evidence includes the target node."""
        result = WhatEvidence.query(self.graph, "decision_promote_spec_057")
        target_ids = [e["node_id"] for e in result["evidence_chain"]]
        self.assertIn("decision_promote_spec_057", target_ids)


class TestWhatPromotes(unittest.TestCase):
    """Test promotion path for specs."""

    def setUp(self):
        """Create test graph with promotion gates."""
        self.graph = KnowledgeGraph()

        # Create spec
        self.graph.add_node(
            KnowledgeGraphNode(
                id="spec_100",
                node_type="Spec",
                title="IC Tooling Correction",
                status="PENDING",
                source_path="specs/changes/spec_100.md",
                evidence="",
                updated_at="2026-05-13T00:00:00Z",
                extra_fields={"spec_number": 100},
            )
        )

        # Create promotion gates
        self.graph.add_node(
            KnowledgeGraphNode(
                id="gate_ic_coverage",
                node_type="Gate",
                title="IC Coverage 100%",
                status="PENDING",
                source_path="gates/ic_coverage.py",
                evidence="",
                updated_at="2026-05-13T00:00:00Z",
                extra_fields={},
            )
        )

        self.graph.add_node(
            KnowledgeGraphNode(
                id="review_ic_governance",
                node_type="Review",
                title="IC Governance Review",
                status="PENDING",
                source_path="reviews/ic_governance.md",
                evidence="",
                updated_at="2026-05-13T00:00:00Z",
                extra_fields={},
            )
        )

        # Create promotion edges
        self.graph.add_edge(
            KnowledgeGraphEdge(
                src="gate_ic_coverage",
                edge_type="GATES",
                dst="spec_100",
                evidence="IC coverage required before promotion",
                confidence="HIGH",
                created_at="2026-05-13T00:00:00Z",
            )
        )

        self.graph.add_edge(
            KnowledgeGraphEdge(
                src="review_ic_governance",
                edge_type="REQUIRES",
                dst="spec_100",
                evidence="Governance review required",
                confidence="HIGH",
                created_at="2026-05-13T00:00:00Z",
            )
        )

    def test_promotion_gates_identified(self):
        """What_Promotes identifies blocking gates."""
        result = WhatPromotes.query(self.graph, "spec_100")
        self.assertGreater(result["gates_remaining"], 0)
        self.assertFalse(result["ready_for_promotion"])

    def test_promotion_path_structure(self):
        """What_Promotes returns structured path."""
        result = WhatPromotes.query(self.graph, "spec_100")
        for gate in result["promotion_gates"]:
            self.assertIn("gate_id", gate)
            self.assertIn("gate_type", gate)
            self.assertIn("status", gate)


class TestRunAllQueries(unittest.TestCase):
    """Test batch query execution."""

    def setUp(self):
        """Create minimal test graph."""
        self.graph = KnowledgeGraph()
        self.graph.add_node(
            KnowledgeGraphNode(
                id="module_ranker",
                node_type="ModelComponent",
                title="Ranker",
                status="ACTIVE",
                source_path="ranker.py",
                evidence="",
                updated_at="2026-05-20T00:00:00Z",
                extra_fields={},
            )
        )

    def test_run_all_queries_returns_dict(self):
        """run_all_queries returns structured result."""
        result = run_all_queries(self.graph, target_nodes=["module_ranker"])
        self.assertIn("query_set", result)
        self.assertEqual(result["query_set"], "Phase_2_Step_4b")
        self.assertIn("queries", result)

    def test_query_set_structure(self):
        """Query set has expected structure."""
        result = run_all_queries(self.graph, target_nodes=["module_ranker"])
        self.assertIn("module_ranker", result["queries"])
        queries_for_node = result["queries"]["module_ranker"]
        self.assertIn("what_blocks_ranker", queries_for_node)
        self.assertIn("what_contradicts", queries_for_node)
        self.assertIn("what_evidence", queries_for_node)
        self.assertIn("what_promotes", queries_for_node)


if __name__ == "__main__":
    unittest.main()

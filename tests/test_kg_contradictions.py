"""
Phase 2 Step 4c: Contradiction Detection Tests

7 test cases for C0–C5 contradiction detection.
"""

import unittest

from tools.kg_contradictions import ContradictionDetector, ContradictionSeverity, run_contradiction_detection
from tools.kg_loader import KnowledgeGraph, KnowledgeGraphEdge, KnowledgeGraphNode


class TestStructuralContradictions(unittest.TestCase):
    """Test C0: Structural contradictions.

    Note: KnowledgeGraph.add_edge() enforces referential integrity by design.
    C0 detector code is "defense-in-depth" for edge cases. Tests focus on
    verifying the loader guard prevents dangling edges from being created.
    """

    def test_loader_rejects_dangling_source_node(self):
        """C0 Guard: KnowledgeGraph.add_edge() rejects dangling source."""
        graph = KnowledgeGraph()
        graph.add_node(
            KnowledgeGraphNode(
                id="target",
                node_type="Spec",
                title="Target Spec",
                status="ACTIVE",
                source_path="specs/target.md",
                evidence="",
                updated_at="2026-05-20T00:00:00Z",
                extra_fields={},
            )
        )

        # Attempt to add edge with missing source node
        with self.assertRaises(ValueError) as context:
            graph.add_edge(
                KnowledgeGraphEdge(
                    src="missing_source",
                    edge_type="BLOCKS",
                    dst="target",
                    evidence="",
                    confidence="HIGH",
                    created_at="2026-05-20T00:00:00Z",
                )
            )

        self.assertIn("source node not found", str(context.exception))

    def test_loader_rejects_dangling_target_node(self):
        """C0 Guard: KnowledgeGraph.add_edge() rejects dangling target."""
        graph = KnowledgeGraph()
        graph.add_node(
            KnowledgeGraphNode(
                id="source",
                node_type="Spec",
                title="Source Spec",
                status="ACTIVE",
                source_path="specs/source.md",
                evidence="",
                updated_at="2026-05-20T00:00:00Z",
                extra_fields={},
            )
        )

        # Attempt to add edge with missing target node
        with self.assertRaises(ValueError) as context:
            graph.add_edge(
                KnowledgeGraphEdge(
                    src="source",
                    edge_type="BLOCKS",
                    dst="missing_target",
                    evidence="",
                    confidence="HIGH",
                    created_at="2026-05-20T00:00:00Z",
                )
            )

        self.assertIn("destination node not found", str(context.exception))

    def test_valid_graph_no_structural_issues(self):
        """C0 Detector: Valid graph passes structural validation."""
        graph = KnowledgeGraph()
        graph.add_node(
            KnowledgeGraphNode(
                id="source",
                node_type="Spec",
                title="Source Spec",
                status="ACTIVE",
                source_path="specs/source.md",
                evidence="",
                updated_at="2026-05-20T00:00:00Z",
                extra_fields={},
            )
        )

        graph.add_node(
            KnowledgeGraphNode(
                id="target",
                node_type="Spec",
                title="Target Spec",
                status="ACTIVE",
                source_path="specs/target.md",
                evidence="",
                updated_at="2026-05-20T00:00:00Z",
                extra_fields={},
            )
        )

        # Add valid edge
        graph.add_edge(
            KnowledgeGraphEdge(
                src="source",
                edge_type="BLOCKS",
                dst="target",
                evidence="",
                confidence="HIGH",
                created_at="2026-05-20T00:00:00Z",
            )
        )

        detector = ContradictionDetector(graph)
        detector.detect_structural()
        self.assertEqual(len(detector.contradictions), 0)


class TestHardContradictions(unittest.TestCase):
    """Test C1: Hard contradictions."""

    def test_blocks_and_implements(self):
        """C1: Detect node with both BLOCKS and IMPLEMENTS edges."""
        graph = KnowledgeGraph()
        graph.add_node(
            KnowledgeGraphNode(
                id="policy_freeze",
                node_type="Policy",
                title="Freeze Policy",
                status="ACTIVE",
                source_path="policies/freeze.md",
                evidence="",
                updated_at="2026-05-20T00:00:00Z",
                extra_fields={},
            )
        )

        graph.add_node(
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

        # Add both BLOCKS and IMPLEMENTS to same target
        graph.add_edge(
            KnowledgeGraphEdge(
                src="policy_freeze",
                edge_type="BLOCKS",
                dst="module_ranker",
                evidence="",
                confidence="HIGH",
                created_at="2026-05-20T00:00:00Z",
            )
        )

        graph.add_edge(
            KnowledgeGraphEdge(
                src="policy_freeze",
                edge_type="IMPLEMENTS",
                dst="module_ranker",
                evidence="",
                confidence="HIGH",
                created_at="2026-05-20T00:00:00Z",
            )
        )

        detector = ContradictionDetector(graph)
        detector.detect_hard()
        self.assertGreater(len(detector.contradictions), 0)
        self.assertEqual(detector.contradictions[0].severity, ContradictionSeverity.C1_HARD)

    def test_frozen_promotes_active(self):
        """C1: Detect frozen node that promotes/requires active node."""
        graph = KnowledgeGraph()
        graph.add_node(
            KnowledgeGraphNode(
                id="spec_frozen",
                node_type="Spec",
                title="Frozen Spec",
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
                title="Active Spec",
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

        detector = ContradictionDetector(graph)
        detector.detect_hard()
        self.assertGreater(len(detector.contradictions), 0)


class TestSemanticContradictions(unittest.TestCase):
    """Test C2: Semantic contradictions."""

    def test_conflicting_edge_types(self):
        """C2: Detect conflicting edge types on same pair."""
        graph = KnowledgeGraph()
        graph.add_node(
            KnowledgeGraphNode(
                id="spec_a",
                node_type="Spec",
                title="Spec A",
                status="ACTIVE",
                source_path="specs/a.md",
                evidence="",
                updated_at="2026-05-20T00:00:00Z",
                extra_fields={},
            )
        )

        graph.add_node(
            KnowledgeGraphNode(
                id="spec_b",
                node_type="Spec",
                title="Spec B",
                status="ACTIVE",
                source_path="specs/b.md",
                evidence="",
                updated_at="2026-05-20T00:00:00Z",
                extra_fields={},
            )
        )

        # Add conflicting edge types
        graph.add_edge(
            KnowledgeGraphEdge(
                src="spec_a",
                edge_type="BLOCKS",
                dst="spec_b",
                evidence="",
                confidence="HIGH",
                created_at="2026-05-20T00:00:00Z",
            )
        )

        graph.add_edge(
            KnowledgeGraphEdge(
                src="spec_a",
                edge_type="DEPENDS_ON",
                dst="spec_b",
                evidence="",
                confidence="HIGH",
                created_at="2026-05-20T00:00:00Z",
            )
        )

        detector = ContradictionDetector(graph)
        detector.detect_semantic()
        self.assertGreater(len(detector.contradictions), 0)
        self.assertEqual(detector.contradictions[0].severity, ContradictionSeverity.C2_SEMANTIC)


class TestTemporalContradictions(unittest.TestCase):
    """Test C3: Temporal contradictions."""

    def test_newer_blocks_older(self):
        """C3: Detect newer node blocking older node."""
        graph = KnowledgeGraph()
        graph.add_node(
            KnowledgeGraphNode(
                id="spec_old",
                node_type="Spec",
                title="Old Spec",
                status="ACTIVE",
                source_path="specs/old.md",
                evidence="",
                updated_at="2026-04-01T00:00:00Z",
                extra_fields={},
            )
        )

        graph.add_node(
            KnowledgeGraphNode(
                id="spec_new",
                node_type="Spec",
                title="New Spec",
                status="ACTIVE",
                source_path="specs/new.md",
                evidence="",
                updated_at="2026-05-20T00:00:00Z",
                extra_fields={},
            )
        )

        # Newer blocks older (violation)
        graph.add_edge(
            KnowledgeGraphEdge(
                src="spec_new",
                edge_type="BLOCKS",
                dst="spec_old",
                evidence="",
                confidence="HIGH",
                created_at="2026-05-20T00:00:00Z",
            )
        )

        detector = ContradictionDetector(graph)
        detector.detect_temporal()
        self.assertGreater(len(detector.contradictions), 0)
        self.assertEqual(detector.contradictions[0].severity, ContradictionSeverity.C3_TEMPORAL)


class TestSoftContradictions(unittest.TestCase):
    """Test C4: Soft contradictions (policy violations)."""

    def test_undocumented_pending(self):
        """C4: Detect PENDING node with no documentation."""
        graph = KnowledgeGraph()
        graph.add_node(
            KnowledgeGraphNode(
                id="spec_undocumented",
                node_type="Spec",
                title="Undocumented Spec",
                status="PENDING",
                source_path="specs/undoc.md",
                evidence="",
                updated_at="2026-05-20T00:00:00Z",
                extra_fields={},
            )
        )

        detector = ContradictionDetector(graph)
        detector.detect_soft()
        self.assertGreater(len(detector.contradictions), 0)
        self.assertEqual(detector.contradictions[0].severity, ContradictionSeverity.C4_SOFT)

    def test_active_with_contradictions(self):
        """C4: Detect ACTIVE node with CONTRADICTS edges."""
        graph = KnowledgeGraph()
        graph.add_node(
            KnowledgeGraphNode(
                id="spec_active",
                node_type="Spec",
                title="Active Spec",
                status="ACTIVE",
                source_path="specs/active.md",
                evidence="",
                updated_at="2026-05-20T00:00:00Z",
                extra_fields={},
            )
        )

        graph.add_node(
            KnowledgeGraphNode(
                id="spec_other",
                node_type="Spec",
                title="Other Spec",
                status="ACTIVE",
                source_path="specs/other.md",
                evidence="",
                updated_at="2026-05-20T00:00:00Z",
                extra_fields={},
            )
        )

        graph.add_edge(
            KnowledgeGraphEdge(
                src="spec_active",
                edge_type="CONTRADICTS",
                dst="spec_other",
                evidence="",
                confidence="HIGH",
                created_at="2026-05-20T00:00:00Z",
            )
        )

        detector = ContradictionDetector(graph)
        detector.detect_soft()
        self.assertGreater(len(detector.contradictions), 0)


class TestRunContradictionDetection(unittest.TestCase):
    """Test batch contradiction detection."""

    def test_detection_returns_structured_result(self):
        """run_contradiction_detection returns structured dict."""
        graph = KnowledgeGraph()
        graph.add_node(
            KnowledgeGraphNode(
                id="spec_clean",
                node_type="Spec",
                title="Clean Spec",
                status="ACTIVE",
                source_path="specs/clean.md",
                evidence="",
                updated_at="2026-05-20T00:00:00Z",
                extra_fields={},
            )
        )

        result = run_contradiction_detection(graph)
        self.assertIn("total_contradictions", result)
        self.assertIn("by_severity", result)
        self.assertIn("health", result)
        self.assertEqual(result["total_contradictions"], 0)
        self.assertEqual(result["health"], "CLEAR")

    def test_health_classification(self):
        """Health status classified correctly."""
        graph = KnowledgeGraph()
        # Add PENDING node without documentation
        graph.add_node(
            KnowledgeGraphNode(
                id="spec_pending",
                node_type="Spec",
                title="Pending Spec",
                status="PENDING",
                source_path="specs/pending.md",
                evidence="",
                updated_at="2026-05-20T00:00:00Z",
                extra_fields={},
            )
        )

        result = run_contradiction_detection(graph)
        self.assertEqual(result["health"], "WARN")  # Soft contradictions = WARN


if __name__ == "__main__":
    unittest.main()

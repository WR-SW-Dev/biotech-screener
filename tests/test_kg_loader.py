"""
Phase 2 Step 4a: Knowledge Graph Loader Tests

17 test cases for KnowledgeGraphNode, KnowledgeGraphEdge, and KnowledgeGraph.
"""

import unittest
import json
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from kg_loader import KnowledgeGraphNode, KnowledgeGraphEdge, KnowledgeGraph


class TestKnowledgeGraphNode(unittest.TestCase):
    """Test KnowledgeGraphNode creation and validation."""

    def test_node_creation(self):
        """Valid node creation succeeds."""
        node = KnowledgeGraphNode(
            id="spec_100",
            node_type="Spec",
            title="True Ranker IC Tooling",
            status="PENDING",
            source_path="specs/changes/spec_100_*.md",
            evidence="specs/changes/spec_100_governance_follow_up_2026_05_13.md",
            updated_at="2026-05-14T00:00:00Z",
            extra_fields={"spec_number": 100},
        )
        self.assertEqual(node.id, "spec_100")
        self.assertEqual(node.node_type, "Spec")

    def test_invalid_node_type(self):
        """Invalid node_type raises ValueError."""
        with self.assertRaises(ValueError):
            KnowledgeGraphNode(
                id="bad",
                node_type="InvalidType",
                title="Test",
                status="ACTIVE",
                source_path="path",
                evidence="evidence",
                updated_at="2026-05-14T00:00:00Z",
                extra_fields={},
            )

    def test_invalid_status(self):
        """Invalid status raises ValueError."""
        with self.assertRaises(ValueError):
            KnowledgeGraphNode(
                id="bad",
                node_type="Spec",
                title="Test",
                status="INVALID_STATUS",
                source_path="path",
                evidence="evidence",
                updated_at="2026-05-14T00:00:00Z",
                extra_fields={},
            )


class TestKnowledgeGraphEdge(unittest.TestCase):
    """Test KnowledgeGraphEdge creation and validation."""

    def test_edge_creation(self):
        """Valid edge creation succeeds."""
        edge = KnowledgeGraphEdge(
            src="spec_100",
            edge_type="DEPENDS_ON",
            dst="action_forward_return_wiring",
            evidence="spec_100_governance_follow_up.md",
            confidence="HIGH",
            created_at="2026-05-14T00:00:00Z",
        )
        self.assertEqual(edge.src, "spec_100")
        self.assertEqual(edge.edge_type, "DEPENDS_ON")

    def test_invalid_edge_type(self):
        """Invalid edge_type raises ValueError."""
        with self.assertRaises(ValueError):
            KnowledgeGraphEdge(
                src="a",
                edge_type="INVALID_EDGE",
                dst="b",
                evidence="e",
                confidence="HIGH",
                created_at="2026-05-14T00:00:00Z",
            )

    def test_invalid_confidence(self):
        """Invalid confidence raises ValueError."""
        with self.assertRaises(ValueError):
            KnowledgeGraphEdge(
                src="a",
                edge_type="DEPENDS_ON",
                dst="b",
                evidence="e",
                confidence="INVALID",
                created_at="2026-05-14T00:00:00Z",
            )


class TestKnowledgeGraph(unittest.TestCase):
    """Test KnowledgeGraph class."""

    def setUp(self):
        """Create a test graph with sample nodes."""
        self.kg = KnowledgeGraph()

        self.node1 = KnowledgeGraphNode(
            id="spec_100",
            node_type="Spec",
            title="Test Spec",
            status="PENDING",
            source_path="specs/spec_100.md",
            evidence="memo.md",
            updated_at="2026-05-14T00:00:00Z",
            extra_fields={"spec_number": 100},
        )
        self.node2 = KnowledgeGraphNode(
            id="action_wire",
            node_type="Action",
            title="Wire Implementation",
            status="ACTIVE",
            source_path="actions.md",
            evidence="memo.md",
            updated_at="2026-05-14T00:00:00Z",
            extra_fields={},
        )

        self.kg.add_node(self.node1)
        self.kg.add_node(self.node2)

    def test_add_node(self):
        """Adding a node stores it."""
        self.assertIn("spec_100", self.kg.nodes)
        self.assertEqual(self.kg.nodes["spec_100"].title, "Test Spec")

    def test_duplicate_node_id(self):
        """Adding duplicate node ID raises ValueError."""
        with self.assertRaises(ValueError):
            self.kg.add_node(self.node1)

    def test_add_edge(self):
        """Adding a valid edge succeeds."""
        edge = KnowledgeGraphEdge(
            src="spec_100",
            edge_type="DEPENDS_ON",
            dst="action_wire",
            evidence="memo.md",
            confidence="HIGH",
            created_at="2026-05-14T00:00:00Z",
        )
        self.kg.add_edge(edge)
        self.assertEqual(len(self.kg.edges), 1)

    def test_edge_missing_src(self):
        """Adding edge with missing src node raises ValueError."""
        edge = KnowledgeGraphEdge(
            src="nonexistent",
            edge_type="DEPENDS_ON",
            dst="action_wire",
            evidence="memo.md",
            confidence="HIGH",
            created_at="2026-05-14T00:00:00Z",
        )
        with self.assertRaises(ValueError):
            self.kg.add_edge(edge)

    def test_edge_missing_dst(self):
        """Adding edge with missing dst node raises ValueError."""
        edge = KnowledgeGraphEdge(
            src="spec_100",
            edge_type="DEPENDS_ON",
            dst="nonexistent",
            evidence="memo.md",
            confidence="HIGH",
            created_at="2026-05-14T00:00:00Z",
        )
        with self.assertRaises(ValueError):
            self.kg.add_edge(edge)

    def test_outgoing_edges(self):
        """outgoing_edges returns edges where node is source."""
        edge = KnowledgeGraphEdge(
            src="spec_100",
            edge_type="DEPENDS_ON",
            dst="action_wire",
            evidence="memo.md",
            confidence="HIGH",
            created_at="2026-05-14T00:00:00Z",
        )
        self.kg.add_edge(edge)

        outgoing = self.kg.outgoing_edges("spec_100")
        self.assertEqual(len(outgoing), 1)
        self.assertEqual(outgoing[0].src, "spec_100")

    def test_incoming_edges(self):
        """incoming_edges returns edges where node is destination."""
        edge = KnowledgeGraphEdge(
            src="spec_100",
            edge_type="DEPENDS_ON",
            dst="action_wire",
            evidence="memo.md",
            confidence="HIGH",
            created_at="2026-05-14T00:00:00Z",
        )
        self.kg.add_edge(edge)

        incoming = self.kg.incoming_edges("action_wire")
        self.assertEqual(len(incoming), 1)
        self.assertEqual(incoming[0].dst, "action_wire")

    def test_validate_schema_empty(self):
        """Empty graph validates."""
        kg = KnowledgeGraph()
        errors = kg.validate_schema()
        self.assertEqual(errors, [])

    def test_validate_schema_valid(self):
        """Valid graph with nodes and edges passes validation."""
        edge = KnowledgeGraphEdge(
            src="spec_100",
            edge_type="DEPENDS_ON",
            dst="action_wire",
            evidence="memo.md",
            confidence="HIGH",
            created_at="2026-05-14T00:00:00Z",
        )
        self.kg.add_edge(edge)

        errors = self.kg.validate_schema()
        self.assertEqual(errors, [])

    def test_load_seed_basic(self):
        """Loading a valid seed file populates the graph."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write(
                '{"type": "node", "id": "spec_100", "node_type": "Spec", "title": "Test", "status": "PENDING", "source_path": "path", "evidence": "ev", "updated_at": "2026-05-14T00:00:00Z", "extra_fields": {}}\n'
            )
            f.write(
                '{"type": "node", "id": "action_wire", "node_type": "Action", "title": "Wire", "status": "ACTIVE", "source_path": "path", "evidence": "ev", "updated_at": "2026-05-14T00:00:00Z", "extra_fields": {}}\n'
            )
            f.write(
                '{"type": "edge", "src": "spec_100", "edge_type": "DEPENDS_ON", "dst": "action_wire", "evidence": "ev", "confidence": "HIGH", "created_at": "2026-05-14T00:00:00Z"}\n'
            )
            temp_path = f.name

        try:
            kg = KnowledgeGraph()
            kg.load_seed(temp_path)

            self.assertEqual(len(kg.nodes), 2)
            self.assertEqual(len(kg.edges), 1)
            self.assertIn("spec_100", kg.nodes)
            self.assertIn("action_wire", kg.nodes)
        finally:
            Path(temp_path).unlink()

    def test_load_seed_missing_file(self):
        """Loading missing seed file raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            self.kg.load_seed("/nonexistent/path.jsonl")

    def test_stats(self):
        """stats() returns graph statistics."""
        edge = KnowledgeGraphEdge(
            src="spec_100",
            edge_type="DEPENDS_ON",
            dst="action_wire",
            evidence="memo.md",
            confidence="HIGH",
            created_at="2026-05-14T00:00:00Z",
        )
        self.kg.add_edge(edge)

        stats = self.kg.stats()
        self.assertEqual(stats["total_nodes"], 2)
        self.assertEqual(stats["total_edges"], 1)
        self.assertIn("Spec", stats["node_types"])
        self.assertIn("DEPENDS_ON", stats["edge_types"])


if __name__ == "__main__":
    unittest.main()

"""
Phase 2 Step 4a: Knowledge Graph Loader

In-memory knowledge graph for governance queries.
Three classes: KnowledgeGraphNode, KnowledgeGraphEdge, KnowledgeGraph.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class KnowledgeGraphNode:
    """Represents a single node in the governance knowledge graph.

    Attributes:
        id: Unique node identifier (e.g., "spec_100", "policy_alpha_freeze")
        node_type: One of 11 types: Spec, Policy, Commit, Artifact, CodeFile, Signal,
                   ModelComponent, Action, Gate, Review, Snapshot
        title: Human-readable title
        status: One of ACTIVE, PENDING, CLOSED, CONFLICT, MONITORING, FROZEN
        source_path: Path to authoritative source (spec file, policy memo, etc.)
        evidence: Additional evidence path or memo reference
        updated_at: ISO 8601 timestamp
        extra_fields: Type-specific fields (spec_number, policy_id, commit_hash, etc.)
    """

    id: str
    node_type: str
    title: str
    status: str
    source_path: str
    evidence: str
    updated_at: str
    extra_fields: dict[str, Any]

    def __post_init__(self):
        """Validate node on creation."""
        valid_types = {
            "Spec",
            "Policy",
            "Commit",
            "Artifact",
            "CodeFile",
            "Signal",
            "ModelComponent",
            "Action",
            "Gate",
            "Review",
            "Snapshot",
        }
        if self.node_type not in valid_types:
            raise ValueError(f"Invalid node_type: {self.node_type}. Must be one of {valid_types}")

        valid_statuses = {
            "ACTIVE",
            "PENDING",
            "CLOSED",
            "CONFLICT",
            "MONITORING",
            "FROZEN",
        }
        if self.status not in valid_statuses:
            raise ValueError(f"Invalid status: {self.status}. Must be one of {valid_statuses}")


@dataclass
class KnowledgeGraphEdge:
    """Represents a directed edge between two nodes.

    Attributes:
        src: Source node ID
        edge_type: One of 15 types: IMPLEMENTS, DOCUMENTS, BLOCKS, DEPENDS_ON, REQUIRES,
                   GOVERNS, TOUCHES, CONTRADICTS, READS, WRITES, PROMOTES, DEMOTES,
                   GATES, BACKFILLS, AWAITS
        dst: Destination node ID
        evidence: Path or reference supporting this edge
        confidence: One of HIGH, MEDIUM, LOW
        created_at: ISO 8601 timestamp
    """

    src: str
    edge_type: str
    dst: str
    evidence: str
    confidence: str
    created_at: str

    def __post_init__(self):
        """Validate edge on creation."""
        valid_types = {
            "IMPLEMENTS",
            "DOCUMENTS",
            "BLOCKS",
            "DEPENDS_ON",
            "REQUIRES",
            "GOVERNS",
            "TOUCHES",
            "CONTRADICTS",
            "READS",
            "WRITES",
            "PROMOTES",
            "DEMOTES",
            "GATES",
            "BACKFILLS",
            "AWAITS",
        }
        if self.edge_type not in valid_types:
            raise ValueError(f"Invalid edge_type: {self.edge_type}. Must be one of {valid_types}")

        valid_confidences = {"HIGH", "MEDIUM", "LOW"}
        if self.confidence not in valid_confidences:
            raise ValueError(f"Invalid confidence: {self.confidence}. Must be one of {valid_confidences}")


class KnowledgeGraph:
    """In-memory knowledge graph for governance queries.

    Manages nodes and edges, validates schema, provides query-ready access.
    """

    def __init__(self):
        """Initialize empty graph."""
        self.nodes: dict[str, KnowledgeGraphNode] = {}
        self.edges: list[KnowledgeGraphEdge] = []
        self._edges_by_src: dict[str, list[KnowledgeGraphEdge]] = {}
        self._edges_by_dst: dict[str, list[KnowledgeGraphEdge]] = {}

    def add_node(self, node: KnowledgeGraphNode) -> None:
        """Add a node to the graph. Raises ValueError if duplicate ID."""
        if node.id in self.nodes:
            raise ValueError(f"Duplicate node ID: {node.id}")
        self.nodes[node.id] = node

    def add_edge(self, edge: KnowledgeGraphEdge) -> None:
        """Add an edge to the graph. Raises ValueError if src/dst don't exist."""
        if edge.src not in self.nodes:
            raise ValueError(f"Edge source node not found: {edge.src}")
        if edge.dst not in self.nodes:
            raise ValueError(f"Edge destination node not found: {edge.dst}")

        self.edges.append(edge)

        # Maintain indices for efficient traversal
        if edge.src not in self._edges_by_src:
            self._edges_by_src[edge.src] = []
        self._edges_by_src[edge.src].append(edge)

        if edge.dst not in self._edges_by_dst:
            self._edges_by_dst[edge.dst] = []
        self._edges_by_dst[edge.dst].append(edge)

    def get_node(self, node_id: str) -> Optional[KnowledgeGraphNode]:
        """Retrieve a node by ID."""
        return self.nodes.get(node_id)

    def outgoing_edges(self, node_id: str) -> list[KnowledgeGraphEdge]:
        """All edges where this node is the source."""
        return self._edges_by_src.get(node_id, [])

    def incoming_edges(self, node_id: str) -> list[KnowledgeGraphEdge]:
        """All edges where this node is the destination."""
        return self._edges_by_dst.get(node_id, [])

    def validate_schema(self) -> list[str]:
        """Run all schema validation checks. Returns list of error messages (empty = valid)."""
        errors = []

        # Check 1: No duplicate node IDs (enforced in add_node, but double-check)
        seen_ids = set()
        for node_id in self.nodes.keys():
            if node_id in seen_ids:
                errors.append(f"Duplicate node ID: {node_id}")
            seen_ids.add(node_id)

        # Check 2: All edge src/dst reference existing nodes
        for i, edge in enumerate(self.edges):
            if edge.src not in self.nodes:
                errors.append(f"Edge {i}: source node '{edge.src}' not found")
            if edge.dst not in self.nodes:
                errors.append(f"Edge {i}: destination node '{edge.dst}' not found")

        # Check 3: No self-edges (optional, but good practice)
        for i, edge in enumerate(self.edges):
            if edge.src == edge.dst:
                errors.append(f"Edge {i}: self-edge detected ({edge.src} → {edge.dst})")

        # Check 4: All required node fields present
        for node_id, node in self.nodes.items():
            if not node.id or not node.node_type or not node.status:
                errors.append(f"Node '{node_id}': missing required field(s)")

        # Check 5: All required edge fields present
        for i, edge in enumerate(self.edges):
            if not edge.src or not edge.edge_type or not edge.dst or not edge.confidence:
                errors.append(f"Edge {i}: missing required field(s)")

        return errors

    def load_seed(self, seed_path: str | Path) -> None:
        """Load seed graph from JSONL file.

        Seed format: one JSON object per line. Object must have 'type' field:
        - "node": Load as KnowledgeGraphNode
        - "edge": Load as KnowledgeGraphEdge

        Example node:
        {"type": "node", "id": "spec_100", "node_type": "Spec", "title": "True Ranker IC Tooling",
         "status": "PENDING", "source_path": "specs/changes/spec_100_*.md",
         "evidence": "specs/changes/spec_100_governance_follow_up_2026_05_13.md",
         "updated_at": "2026-05-14T00:00:00Z", "extra_fields": {"spec_number": 100, "phase": "scaffold"}}

        Example edge:
        {"type": "edge", "src": "spec_100", "edge_type": "DEPENDS_ON",
         "dst": "action_forward_return_wiring", "evidence": "spec_100_governance_follow_up.md",
         "confidence": "HIGH", "created_at": "2026-05-14T00:00:00Z"}
        """
        seed_path = Path(seed_path)
        if not seed_path.exists():
            raise FileNotFoundError(f"Seed graph file not found: {seed_path}")

        with open(seed_path, "r") as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue  # Skip empty lines and comments

                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSON at line {line_num}: {e}")

                obj_type = obj.get("type")
                if obj_type == "node":
                    node = KnowledgeGraphNode(
                        id=obj["id"],
                        node_type=obj["node_type"],
                        title=obj["title"],
                        status=obj["status"],
                        source_path=obj["source_path"],
                        evidence=obj["evidence"],
                        updated_at=obj["updated_at"],
                        extra_fields=obj.get("extra_fields", {}),
                    )
                    self.add_node(node)

                elif obj_type == "edge":
                    edge = KnowledgeGraphEdge(
                        src=obj["src"],
                        edge_type=obj["edge_type"],
                        dst=obj["dst"],
                        evidence=obj["evidence"],
                        confidence=obj["confidence"],
                        created_at=obj["created_at"],
                    )
                    self.add_edge(edge)

                else:
                    raise ValueError(f"Unknown object type at line {line_num}: {obj_type}")

    def stats(self) -> dict:
        """Return graph statistics."""
        node_types = {}
        for node in self.nodes.values():
            node_types[node.node_type] = node_types.get(node.node_type, 0) + 1

        edge_types = {}
        for edge in self.edges:
            edge_types[edge.edge_type] = edge_types.get(edge.edge_type, 0) + 1

        return {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "node_types": node_types,
            "edge_types": edge_types,
        }

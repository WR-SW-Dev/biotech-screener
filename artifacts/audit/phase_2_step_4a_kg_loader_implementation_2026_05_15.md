# Phase 2 Step 4a — Knowledge Graph Loader Implementation (2026-05-15)

**Status**: Design locked (specification only; do NOT implement until cohort clearance is explicitly verified).

**Scope**: ~150 lines of code specification, zero lines removed. Builds the in-memory KG foundation for phases 4b–4e.

**Implementation Gate**: Do NOT begin Phase 4a until:
1. May 19 watchdog verification PASSES
2. May 23–26 cohort clearance is explicitly CONFIRMED (not estimated)

---

## Overview

Phase 4a builds three classes that form the knowledge graph's data structure:

1. **KnowledgeGraphNode** — Represents a single governance node (Spec, Policy, Commit, etc.)
2. **KnowledgeGraphEdge** — Represents a directed edge between nodes
3. **KnowledgeGraph** — In-memory container; loads seed graph, validates schema, provides access

**Output file**: `tools/kg_loader.py` (new file)

**Seed graph file**: `artifacts/audit/kg_seed.jsonl` (one JSON object per line; manually authored in Phase 4e prep or after Phase 4a is ready)

---

## Data Classes

### KnowledgeGraphNode

```python
from dataclasses import dataclass
from typing import Any

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
            "Spec", "Policy", "Commit", "Artifact", "CodeFile", 
            "Signal", "ModelComponent", "Action", "Gate", "Review", "Snapshot"
        }
        if self.node_type not in valid_types:
            raise ValueError(f"Invalid node_type: {self.node_type}. Must be one of {valid_types}")
        
        valid_statuses = {"ACTIVE", "PENDING", "CLOSED", "CONFLICT", "MONITORING", "FROZEN"}
        if self.status not in valid_statuses:
            raise ValueError(f"Invalid status: {self.status}. Must be one of {valid_statuses}")
```

### KnowledgeGraphEdge

```python
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
            "IMPLEMENTS", "DOCUMENTS", "BLOCKS", "DEPENDS_ON", "REQUIRES",
            "GOVERNS", "TOUCHES", "CONTRADICTS", "READS", "WRITES", "PROMOTES",
            "DEMOTES", "GATES", "BACKFILLS", "AWAITS"
        }
        if self.edge_type not in valid_types:
            raise ValueError(f"Invalid edge_type: {self.edge_type}. Must be one of {valid_types}")
        
        valid_confidences = {"HIGH", "MEDIUM", "LOW"}
        if self.confidence not in valid_confidences:
            raise ValueError(f"Invalid confidence: {self.confidence}. Must be one of {valid_confidences}")
```

---

## KnowledgeGraph Class

```python
import json
from pathlib import Path
from typing import Optional

class KnowledgeGraph:
    """In-memory knowledge graph for governance queries.
    
    Manages nodes and edges, validates schema, provides query-ready access.
    """
    
    def __init__(self):
        """Initialize empty graph."""
        self.nodes: dict[str, KnowledgeGraphNode] = {}
        self.edges: list[KnowledgeGraphEdge] = []
        self._edges_by_src: dict[str, list[KnowledgeGraphEdge]] = {}  # For efficient traversal
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
                        extra_fields=obj.get("extra_fields", {})
                    )
                    self.add_node(node)
                
                elif obj_type == "edge":
                    edge = KnowledgeGraphEdge(
                        src=obj["src"],
                        edge_type=obj["edge_type"],
                        dst=obj["dst"],
                        evidence=obj["evidence"],
                        confidence=obj["confidence"],
                        created_at=obj["created_at"]
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
            "edge_types": edge_types
        }
```

---

## Test Cases

**File**: `tests/test_kg_loader.py`

```python
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
            extra_fields={"spec_number": 100}
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
                extra_fields={}
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
                extra_fields={}
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
            created_at="2026-05-14T00:00:00Z"
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
                created_at="2026-05-14T00:00:00Z"
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
                created_at="2026-05-14T00:00:00Z"
            )


class TestKnowledgeGraph(unittest.TestCase):
    """Test KnowledgeGraph class."""
    
    def setUp(self):
        """Create a test graph with sample nodes."""
        self.kg = KnowledgeGraph()
        
        self.node1 = KnowledgeGraphNode(
            id="spec_100", node_type="Spec", title="Test Spec",
            status="PENDING", source_path="specs/spec_100.md", evidence="memo.md",
            updated_at="2026-05-14T00:00:00Z", extra_fields={"spec_number": 100}
        )
        self.node2 = KnowledgeGraphNode(
            id="action_wire", node_type="Action", title="Wire Implementation",
            status="ACTIVE", source_path="actions.md", evidence="memo.md",
            updated_at="2026-05-14T00:00:00Z", extra_fields={}
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
            src="spec_100", edge_type="DEPENDS_ON", dst="action_wire",
            evidence="memo.md", confidence="HIGH", created_at="2026-05-14T00:00:00Z"
        )
        self.kg.add_edge(edge)
        self.assertEqual(len(self.kg.edges), 1)
    
    def test_edge_missing_src(self):
        """Adding edge with missing src node raises ValueError."""
        edge = KnowledgeGraphEdge(
            src="nonexistent", edge_type="DEPENDS_ON", dst="action_wire",
            evidence="memo.md", confidence="HIGH", created_at="2026-05-14T00:00:00Z"
        )
        with self.assertRaises(ValueError):
            self.kg.add_edge(edge)
    
    def test_edge_missing_dst(self):
        """Adding edge with missing dst node raises ValueError."""
        edge = KnowledgeGraphEdge(
            src="spec_100", edge_type="DEPENDS_ON", dst="nonexistent",
            evidence="memo.md", confidence="HIGH", created_at="2026-05-14T00:00:00Z"
        )
        with self.assertRaises(ValueError):
            self.kg.add_edge(edge)
    
    def test_outgoing_edges(self):
        """outgoing_edges returns edges where node is source."""
        edge = KnowledgeGraphEdge(
            src="spec_100", edge_type="DEPENDS_ON", dst="action_wire",
            evidence="memo.md", confidence="HIGH", created_at="2026-05-14T00:00:00Z"
        )
        self.kg.add_edge(edge)
        
        outgoing = self.kg.outgoing_edges("spec_100")
        self.assertEqual(len(outgoing), 1)
        self.assertEqual(outgoing[0].src, "spec_100")
    
    def test_incoming_edges(self):
        """incoming_edges returns edges where node is destination."""
        edge = KnowledgeGraphEdge(
            src="spec_100", edge_type="DEPENDS_ON", dst="action_wire",
            evidence="memo.md", confidence="HIGH", created_at="2026-05-14T00:00:00Z"
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
            src="spec_100", edge_type="DEPENDS_ON", dst="action_wire",
            evidence="memo.md", confidence="HIGH", created_at="2026-05-14T00:00:00Z"
        )
        self.kg.add_edge(edge)
        
        errors = self.kg.validate_schema()
        self.assertEqual(errors, [])
    
    def test_load_seed_basic(self):
        """Loading a valid seed file populates the graph."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"type": "node", "id": "spec_100", "node_type": "Spec", "title": "Test", "status": "PENDING", "source_path": "path", "evidence": "ev", "updated_at": "2026-05-14T00:00:00Z", "extra_fields": {}}\n')
            f.write('{"type": "node", "id": "action_wire", "node_type": "Action", "title": "Wire", "status": "ACTIVE", "source_path": "path", "evidence": "ev", "updated_at": "2026-05-14T00:00:00Z", "extra_fields": {}}\n')
            f.write('{"type": "edge", "src": "spec_100", "edge_type": "DEPENDS_ON", "dst": "action_wire", "evidence": "ev", "confidence": "HIGH", "created_at": "2026-05-14T00:00:00Z"}\n')
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
            src="spec_100", edge_type="DEPENDS_ON", dst="action_wire",
            evidence="memo.md", confidence="HIGH", created_at="2026-05-14T00:00:00Z"
        )
        self.kg.add_edge(edge)
        
        stats = self.kg.stats()
        self.assertEqual(stats["total_nodes"], 2)
        self.assertEqual(stats["total_edges"], 1)
        self.assertIn("Spec", stats["node_types"])
        self.assertIn("DEPENDS_ON", stats["edge_types"])


if __name__ == "__main__":
    unittest.main()
```

---

## Acceptance Criteria

Before committing May 24:

1. ✅ KnowledgeGraphNode class defined with validation
2. ✅ KnowledgeGraphEdge class defined with validation
3. ✅ KnowledgeGraph class with add_node, add_edge, traversal methods
4. ✅ Schema validation function (check all nodes/edges valid)
5. ✅ Seed graph loader (parse JSONL, create nodes/edges)
6. ✅ Graph statistics function
7. ✅ All 17 test cases pass
8. ✅ No regressions (existing tests still pass)

---

## Commit Checklist

**May 24 (Phase 4a complete)**:

1. Create tools/kg_loader.py with all three classes
2. Create tests/test_kg_loader.py with 17 test methods
3. Run tests: `python3 -m pytest tests/test_kg_loader.py -v`
4. Verify all pass
5. Verify no regressions: `python3 -m pytest tests/ -v`
6. Commit: `tools: implement knowledge graph loader (Phase 2 Step 4a)`
7. Message includes Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>

---

## Integration Points

**Phase 4b** (May 24–25): Import KnowledgeGraph, load seed, implement 5 query methods  
**Phase 4c** (May 25–26): Import KnowledgeGraph, implement contradiction detection rules  
**Phase 4d** (May 26–27): CLI wrapper around KGQueries  
**Phase 4e** (May 27–28): Validation test suite using loaded seed graph

---

**Status**: Implementation design locked. Ready for May 24 coding session (2 hours to code + test).

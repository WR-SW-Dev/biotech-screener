"""
Phase 2 Step 4c: Contradiction Detection

Automated contradiction detection in knowledge graph.
Identifies C0–C5 contradictions per Spec 089 schema.

C0: Structural (missing nodes/edges)
C1: Hard (mutually exclusive states)
C2: Semantic (conflicting definitions)
C3: Temporal (temporal dependencies violated)
C4: Soft (policy guidelines)
C5: Possible (requires manual review)
"""

from typing import Dict, List, Set, Optional, Tuple
from enum import Enum
from tools.kg_loader import KnowledgeGraph, KnowledgeGraphNode, KnowledgeGraphEdge


class ContradictionSeverity(str, Enum):
    """Contradiction severity levels."""
    C0_STRUCTURAL = "C0_STRUCTURAL"
    C1_HARD = "C1_HARD"
    C2_SEMANTIC = "C2_SEMANTIC"
    C3_TEMPORAL = "C3_TEMPORAL"
    C4_SOFT = "C4_SOFT"
    C5_POSSIBLE = "C5_POSSIBLE"


class Contradiction:
    """Represents a detected contradiction."""

    def __init__(self, contradiction_id: str, severity: ContradictionSeverity,
                 description: str, nodes: List[str], edges: Optional[List[Tuple[str, str]]] = None,
                 evidence: str = "", resolution: str = ""):
        self.contradiction_id = contradiction_id
        self.severity = severity
        self.description = description
        self.nodes = nodes
        self.edges = edges or []
        self.evidence = evidence
        self.resolution = resolution

    def to_dict(self) -> dict:
        return {
            "contradiction_id": self.contradiction_id,
            "severity": self.severity.value,
            "description": self.description,
            "nodes": self.nodes,
            "edges": self.edges,
            "evidence": self.evidence,
            "resolution": self.resolution
        }


class ContradictionDetector:
    """Detects contradictions in knowledge graph."""

    def __init__(self, graph: KnowledgeGraph):
        self.graph = graph
        self.contradictions: List[Contradiction] = []

    def detect_all(self) -> List[Contradiction]:
        """Run all contradiction detection checks."""
        self.detect_structural()
        self.detect_hard()
        self.detect_semantic()
        self.detect_temporal()
        self.detect_soft()
        return self.contradictions

    def detect_structural(self) -> None:
        """C0: Detect structural contradictions (missing nodes/edges)."""
        for edge in self.graph.edges:
            if edge.src not in self.graph.nodes:
                self.contradictions.append(Contradiction(
                    contradiction_id=f"C0_missing_src_{edge.src}",
                    severity=ContradictionSeverity.C0_STRUCTURAL,
                    description=f"Edge source '{edge.src}' references missing node",
                    nodes=[edge.src, edge.dst],
                    edges=[(edge.src, edge.dst)],
                    evidence=f"Edge {edge.src} → {edge.dst} has dangling source"
                ))

            if edge.dst not in self.graph.nodes:
                self.contradictions.append(Contradiction(
                    contradiction_id=f"C0_missing_dst_{edge.dst}",
                    severity=ContradictionSeverity.C0_STRUCTURAL,
                    description=f"Edge destination '{edge.dst}' references missing node",
                    nodes=[edge.src, edge.dst],
                    edges=[(edge.src, edge.dst)],
                    evidence=f"Edge {edge.src} → {edge.dst} has dangling destination"
                ))

    def detect_hard(self) -> None:
        """C1: Detect hard contradictions (mutually exclusive states)."""
        # Rule: BLOCKS + IMPLEMENTS cannot both exist on same target
        blocks_targets: Set[str] = set()
        implements_targets: Set[str] = set()

        for edge in self.graph.edges:
            if edge.edge_type == "BLOCKS":
                blocks_targets.add(edge.dst)
            elif edge.edge_type == "IMPLEMENTS":
                implements_targets.add(edge.dst)

        for node_id in blocks_targets & implements_targets:
            self.contradictions.append(Contradiction(
                contradiction_id=f"C1_hard_blocks_and_implements_{node_id}",
                severity=ContradictionSeverity.C1_HARD,
                description=f"Node '{node_id}' has both BLOCKS and IMPLEMENTS edges (mutually exclusive)",
                nodes=[node_id],
                evidence="A node cannot be both blocked and implemented"
            ))

        # Rule: FROZEN status + ACTIVE status cannot coexist
        for node_id, node in self.graph.nodes.items():
            if node.status == "FROZEN":
                for edge in self.graph.outgoing_edges(node_id):
                    target = self.graph.get_node(edge.dst)
                    if target and target.status == "ACTIVE" and edge.edge_type in ["PROMOTES", "REQUIRES"]:
                        self.contradictions.append(Contradiction(
                            contradiction_id=f"C1_frozen_promotes_active_{node_id}_{edge.dst}",
                            severity=ContradictionSeverity.C1_HARD,
                            description=f"Frozen node '{node_id}' requires active node '{edge.dst}' (invalid)",
                            nodes=[node_id, edge.dst],
                            edges=[(node_id, edge.dst)],
                            evidence="Frozen components cannot promote or require active changes"
                        ))

    def detect_semantic(self) -> None:
        """C2: Detect semantic contradictions (conflicting definitions)."""
        # Rule: conflicting edge types on same pair
        edge_pairs: Dict[Tuple[str, str], List[str]] = {}
        for edge in self.graph.edges:
            pair = (edge.src, edge.dst)
            if pair not in edge_pairs:
                edge_pairs[pair] = []
            edge_pairs[pair].append(edge.edge_type)

        for (src, dst), types in edge_pairs.items():
            if len(set(types)) > 1:
                # Multiple edge types between same nodes
                conflicting = list(set(types))
                if "BLOCKS" in conflicting and "DEPENDS_ON" in conflicting:
                    self.contradictions.append(Contradiction(
                        contradiction_id=f"C2_semantic_blocks_and_depends_{src}_{dst}",
                        severity=ContradictionSeverity.C2_SEMANTIC,
                        description=f"Node pair ({src} → {dst}) has conflicting edge types: {conflicting}",
                        nodes=[src, dst],
                        edges=[(src, dst)],
                        evidence="Conflicting semantic relationships between same pair"
                    ))

    def detect_temporal(self) -> None:
        """C3: Detect temporal contradictions (time ordering violations)."""
        # Rule: newer node cannot depend on older node in a blocking relationship
        for edge in self.graph.edges:
            src = self.graph.get_node(edge.src)
            dst = self.graph.get_node(edge.dst)
            if not src or not dst:
                continue

            src_time = src.updated_at
            dst_time = dst.updated_at
            if edge.edge_type == "BLOCKS" and src_time > dst_time:
                self.contradictions.append(Contradiction(
                    contradiction_id=f"C3_temporal_newer_blocks_older_{edge.src}",
                    severity=ContradictionSeverity.C3_TEMPORAL,
                    description=f"Newer node '{edge.src}' (updated {src_time}) blocks older node '{edge.dst}' (updated {dst_time})",
                    nodes=[edge.src, edge.dst],
                    edges=[(edge.src, edge.dst)],
                    evidence="Temporal ordering violated: newer blocks older"
                ))

    def detect_soft(self) -> None:
        """C4: Detect soft contradictions (policy guideline violations)."""
        # Rule: PENDING nodes with no DOCUMENTS or DEPENDS_ON edges
        for node_id, node in self.graph.nodes.items():
            if node.status == "PENDING":
                outgoing = self.graph.outgoing_edges(node_id)
                documented = any(e.edge_type == "DOCUMENTS" for e in outgoing)
                depends = any(e.edge_type == "DEPENDS_ON" for e in outgoing)

                if not documented and not depends:
                    self.contradictions.append(Contradiction(
                        contradiction_id=f"C4_soft_undocumented_pending_{node_id}",
                        severity=ContradictionSeverity.C4_SOFT,
                        description=f"PENDING node '{node_id}' has no documentation or dependencies",
                        nodes=[node_id],
                        evidence="Policy: PENDING nodes should document rationale",
                        resolution="Add DOCUMENTS or DEPENDS_ON edges"
                    ))

        # Rule: ACTIVE nodes with CONTRADICTS edges
        for node_id, node in self.graph.nodes.items():
            if node.status == "ACTIVE":
                contradicts = [e for e in self.graph.outgoing_edges(node_id) if e.edge_type == "CONTRADICTS"]
                if contradicts:
                    self.contradictions.append(Contradiction(
                        contradiction_id=f"C4_soft_active_with_contradictions_{node_id}",
                        severity=ContradictionSeverity.C4_SOFT,
                        description=f"ACTIVE node '{node_id}' has {len(contradicts)} contradiction(s)",
                        nodes=[node_id],
                        evidence="Policy guideline: ACTIVE nodes should not contradict others",
                        resolution="Resolve contradictions or demote to MONITORING status"
                    ))


def run_contradiction_detection(graph: KnowledgeGraph) -> dict:
    """Execute contradiction detection and return results."""
    detector = ContradictionDetector(graph)
    contradictions = detector.detect_all()

    # Classify by severity
    by_severity = {}
    for c in contradictions:
        severity = c.severity.value
        if severity not in by_severity:
            by_severity[severity] = []
        by_severity[severity].append(c.to_dict())

    return {
        "total_contradictions": len(contradictions),
        "by_severity": by_severity,
        "critical": len(by_severity.get("C1_HARD", [])) + len(by_severity.get("C0_STRUCTURAL", [])),
        "warnings": len(by_severity.get("C2_SEMANTIC", [])) + len(by_severity.get("C3_TEMPORAL", [])) + len(by_severity.get("C4_SOFT", [])),
        "requires_review": len(by_severity.get("C5_POSSIBLE", [])),
        "health": "CLEAR" if len(contradictions) == 0 else "WARN" if len(by_severity.get("C1_HARD", [])) == 0 else "FAIL"
    }

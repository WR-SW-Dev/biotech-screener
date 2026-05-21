"""
Phase 2 Step 4b: Knowledge Graph Query Layer

Four deterministic query patterns for governance questions:
1. What_Blocks_Ranker - constraints preventing ranker changes
2. What_Contradicts - contradictions between specs/policies
3. What_Evidence - evidence chain for a decision
4. What_Promotes - promotion path for a spec
"""

from typing import Dict, List, Set, Optional
from tools.kg_loader import KnowledgeGraph, KnowledgeGraphNode, KnowledgeGraphEdge


class QueryContext:
    """Execution context for queries."""

    def __init__(self, graph: KnowledgeGraph):
        self.graph = graph
        self.visited: Set[str] = set()
        self.path: List[str] = []


class WhatBlocksRanker:
    """Query 1: What blocks ranker changes?

    Traverse graph to find all BLOCKS edges pointing to ranker nodes.
    Returns: list of blocking specs/policies/gates
    """

    @staticmethod
    def query(graph: KnowledgeGraph, ranker_node_id: str = "module_ranker") -> dict:
        """Find all nodes that BLOCK the ranker."""
        blockers = []
        visited: Set[str] = set()

        def traverse_blockers(node_id: str) -> None:
            if node_id in visited:
                return
            visited.add(node_id)

            incoming = graph.incoming_edges(node_id)
            for edge in incoming:
                if edge.edge_type == "BLOCKS":
                    blocker = graph.get_node(edge.src)
                    if blocker:
                        blockers.append({
                            "blocker_id": edge.src,
                            "blocker_type": blocker.node_type,
                            "blocker_status": blocker.status,
                            "evidence": edge.evidence,
                            "confidence": edge.confidence
                        })
                    traverse_blockers(edge.src)

        traverse_blockers(ranker_node_id)

        return {
            "query": "What_Blocks_Ranker",
            "target": ranker_node_id,
            "blockers": blockers,
            "blocker_count": len(blockers),
            "can_change_ranker": len(blockers) == 0
        }


class WhatContradicts:
    """Query 2: What contradicts a spec?

    Find all nodes that CONTRADICTS a given spec.
    Returns: list of contradicting specs/signals/gates
    """

    @staticmethod
    def query(graph: KnowledgeGraph, spec_node_id: str) -> dict:
        """Find all contradictions related to a spec."""
        contradictions = []
        visited: Set[str] = set()

        def traverse_contradictions(node_id: str) -> None:
            if node_id in visited:
                return
            visited.add(node_id)

            # Outgoing CONTRADICTS edges
            outgoing = graph.outgoing_edges(node_id)
            for edge in outgoing:
                if edge.edge_type == "CONTRADICTS":
                    target = graph.get_node(edge.dst)
                    if target:
                        contradictions.append({
                            "source": edge.src,
                            "target": edge.dst,
                            "target_type": target.node_type,
                            "evidence": edge.evidence,
                            "confidence": edge.confidence
                        })

            # Incoming CONTRADICTS edges
            incoming = graph.incoming_edges(node_id)
            for edge in incoming:
                if edge.edge_type == "CONTRADICTS":
                    source = graph.get_node(edge.src)
                    if source:
                        contradictions.append({
                            "source": edge.src,
                            "target": edge.dst,
                            "source_type": source.node_type,
                            "evidence": edge.evidence,
                            "confidence": edge.confidence
                        })

        traverse_contradictions(spec_node_id)

        return {
            "query": "What_Contradicts",
            "target": spec_node_id,
            "contradictions": contradictions,
            "contradiction_count": len(contradictions),
            "has_conflicts": len(contradictions) > 0
        }


class WhatEvidence:
    """Query 3: What evidence supports a decision?

    Traverse graph backwards from decision node via DOCUMENTS/IMPLEMENTS edges.
    Returns: evidence chain with source files and dates
    """

    @staticmethod
    def query(graph: KnowledgeGraph, decision_node_id: str) -> dict:
        """Trace evidence chain for a decision."""
        evidence_chain = []
        visited: Set[str] = set()

        def traverse_evidence(node_id: str, depth: int = 0) -> None:
            if node_id in visited or depth > 5:
                return
            visited.add(node_id)

            node = graph.get_node(node_id)
            if not node:
                return

            evidence_chain.append({
                "node_id": node_id,
                "node_type": node.node_type,
                "title": node.title,
                "status": node.status,
                "source": node.source_path,
                "depth": depth
            })

            # Follow incoming DOCUMENTS/IMPLEMENTS edges
            incoming = graph.incoming_edges(node_id)
            for edge in incoming:
                if edge.edge_type in ["DOCUMENTS", "IMPLEMENTS", "DEPENDS_ON"]:
                    traverse_evidence(edge.src, depth + 1)

        traverse_evidence(decision_node_id)

        return {
            "query": "What_Evidence",
            "target": decision_node_id,
            "evidence_chain": evidence_chain,
            "chain_length": len(evidence_chain),
            "sources": list(set(e["source"] for e in evidence_chain if e["source"]))
        }


class WhatPromotes:
    """Query 4: What's the promotion path for a spec?

    Find sequence of requirements (gates, reviews, tests) needed to promote spec.
    Returns: ordered list of blocking gates + success criteria
    """

    @staticmethod
    def query(graph: KnowledgeGraph, spec_node_id: str) -> dict:
        """Trace promotion path for a spec."""
        promotion_path = []
        visited: Set[str] = set()

        def traverse_gates(node_id: str, depth: int = 0) -> None:
            if node_id in visited or depth > 5:
                return
            visited.add(node_id)

            # Find REQUIRES/GATES edges pointing to this node
            incoming = graph.incoming_edges(node_id)
            for edge in incoming:
                if edge.edge_type in ["REQUIRES", "GATES", "DEPENDS_ON"]:
                    gate = graph.get_node(edge.src)
                    if gate and gate.node_type in ["Gate", "Review", "Action"]:
                        promotion_path.append({
                            "gate_id": edge.src,
                            "gate_type": gate.node_type,
                            "title": gate.title,
                            "status": gate.status,
                            "evidence": edge.evidence,
                            "depth": depth
                        })
                    traverse_gates(edge.src, depth + 1)

        traverse_gates(spec_node_id)

        return {
            "query": "What_Promotes",
            "target": spec_node_id,
            "promotion_gates": promotion_path,
            "gates_remaining": len([g for g in promotion_path if g["status"] != "CLOSED"]),
            "ready_for_promotion": all(g["status"] == "CLOSED" for g in promotion_path)
        }


def run_all_queries(graph: KnowledgeGraph, target_nodes: Optional[List[str]] = None) -> dict:
    """Execute all four query patterns.

    Args:
        graph: KnowledgeGraph instance
        target_nodes: list of node IDs to query (default: some standard targets)

    Returns:
        dict with all query results
    """
    if target_nodes is None:
        target_nodes = [
            "module_ranker",
            "policy_alpha_freeze",
            "spec_089",
            "action_promote_spec_057"
        ]

    results = {
        "query_set": "Phase_2_Step_4b",
        "queries": {}
    }

    for node_id in target_nodes:
        if not graph.get_node(node_id):
            continue

        results["queries"][node_id] = {
            "what_blocks_ranker": WhatBlocksRanker.query(graph, "module_ranker"),
            "what_contradicts": WhatContradicts.query(graph, node_id),
            "what_evidence": WhatEvidence.query(graph, node_id),
            "what_promotes": WhatPromotes.query(graph, node_id)
        }

    return results

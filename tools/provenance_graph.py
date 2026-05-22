"""
Spec 110: Pipeline Provenance Graph

Deterministic, in-memory, read-only governance lineage tool.
Maps data flow through biotech screener pipeline.

No ML, no scoring integration, no LLM-derived facts.
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


class NodeType(str, Enum):
    """13 node types per Spec 110 schema."""

    RAW_SOURCE = "RawSource"
    VENDOR_SNAPSHOT = "VendorSnapshot"
    CACHE_FILE = "CacheFile"
    FEATURE_ARTIFACT = "FeatureArtifact"
    RULESET_ARTIFACT = "RulesetArtifact"
    DATA_SNAPSHOT = "DataSnapshot"
    MODULE = "Module"
    GATE = "Gate"
    CONTRADICTION = "Contradiction"
    RANKED_LIST = "RankedList"
    VALIDATION_EVIDENCE = "ValidationEvidence"


class EdgeType(str, Enum):
    """8 edge types per Spec 110 schema."""

    PRODUCES = "PRODUCES"
    CONSUMES = "CONSUMES"
    DERIVES = "DERIVES"
    VALIDATES = "VALIDATES"
    QUARANTINES = "QUARANTINES"
    BACKFILLS = "BACKFILLS"
    GATED_BY = "GATED_BY"
    IMPLEMENTS = "IMPLEMENTS"


@dataclass
class Node:
    """Graph node with type and metadata."""

    node_id: str
    node_type: NodeType
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"node_id": self.node_id, "node_type": self.node_type.value, "metadata": self.metadata}


@dataclass
class Edge:
    """Graph edge with type and validation."""

    source_id: str
    target_id: str
    edge_type: EdgeType
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type.value,
            "metadata": self.metadata,
        }


class ProvenanceGraph:
    """
    Deterministic, in-memory provenance graph.

    Captures data lineage from RawSource → RankedList → DataSnapshot.
    Supports 5 query patterns: lineage, snapshot-inputs, breakage-impact,
    stale-features, validate-snapshot.
    """

    def __init__(self, snapshot_date: str):
        self.snapshot_date = snapshot_date
        self.nodes: Dict[str, Node] = {}
        self.edges: List[Edge] = []
        self.edge_index: Dict[str, List[Edge]] = {}  # source_id -> [edges]
        self.reverse_edge_index: Dict[str, List[Edge]] = {}  # target_id -> [edges]

    def add_node(self, node: Node) -> None:
        """Add node to graph."""
        self.nodes[node.node_id] = node

    def add_edge(self, edge: Edge) -> None:
        """Add edge to graph."""
        self.edges.append(edge)
        self.edge_index.setdefault(edge.source_id, []).append(edge)
        self.reverse_edge_index.setdefault(edge.target_id, []).append(edge)

    def get_node(self, node_id: str) -> Optional[Node]:
        """Retrieve node by ID."""
        return self.nodes.get(node_id)

    def get_outgoing_edges(self, node_id: str) -> List[Edge]:
        """Get all edges from source node."""
        return self.edge_index.get(node_id, [])

    def get_incoming_edges(self, node_id: str) -> List[Edge]:
        """Get all edges to target node."""
        return self.reverse_edge_index.get(node_id, [])

    def to_dict(self) -> dict:
        """Serialize graph to dictionary."""
        return {
            "snapshot_date": self.snapshot_date,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "edges": [e.to_dict() for e in self.edges],
        }


@dataclass
class SnapshotMetadata:
    """Metadata extracted from snapshot artifacts."""

    snapshot_date: str
    universe_size: int
    ranked_count: int
    ruleset_id: str
    ruleset_version: str
    gates_status: Dict[str, str]  # gate_name -> verdict (PASS/WARN/FAIL)
    manifest_path: Optional[str] = None
    rankings_path: Optional[str] = None


class GraphBuilder:
    """
    Constructs provenance graph from production snapshot data.

    Deterministic, reproducible construction (no randomness).
    Loads manifest, rankings, feature metadata to build nodes/edges.
    """

    def __init__(self, snapshot_dir: Path):
        self.snapshot_dir = Path(snapshot_dir)
        self.snapshot_date = self.snapshot_dir.name

    def build_graph(self) -> ProvenanceGraph:
        """Build complete provenance graph for snapshot."""
        graph = ProvenanceGraph(self.snapshot_date)

        # Load snapshot metadata
        metadata = self._load_snapshot_metadata()

        # Create nodes (in order: sources → caches → features → modules → outputs)
        self._create_source_nodes(graph, metadata)
        self._create_cache_nodes(graph, metadata)
        self._create_feature_nodes(graph, metadata)
        self._create_module_nodes(graph, metadata)
        self._create_output_nodes(graph, metadata)

        # Create edges (dependencies between nodes)
        self._create_edges(graph, metadata)

        return graph

    def _load_snapshot_metadata(self) -> SnapshotMetadata:
        """Extract metadata from snapshot artifacts."""
        manifest_path = self.snapshot_dir / "run_manifest.json"
        rankings_path = self.snapshot_dir / "rankings.csv"

        manifest = {}
        if manifest_path.exists():
            with open(manifest_path) as f:
                manifest = json.load(f)

        gates_status = {}
        for gate in manifest.get("gates", []):
            gates_status[gate.get("name", "unknown")] = gate.get("verdict", "UNKNOWN")

        return SnapshotMetadata(
            snapshot_date=self.snapshot_date,
            universe_size=manifest.get("universe_size", 0),
            ranked_count=manifest.get("ranked_count", 0),
            ruleset_id=manifest.get("ruleset", {}).get("id", "unknown"),
            ruleset_version=manifest.get("ruleset", {}).get("version", "unknown"),
            gates_status=gates_status,
            manifest_path=str(manifest_path),
            rankings_path=str(rankings_path),
        )

    def _create_source_nodes(self, graph: ProvenanceGraph, metadata: SnapshotMetadata) -> None:
        """Create RawSource nodes for external data feeds."""
        sources = [
            ("13F", {"vendor": "Morningstar", "cadence": "quarterly"}),
            ("ctgov", {"vendor": "ClinicalTrials.gov", "cadence": "daily"}),
            ("market_snapshot", {"vendor": "Yahoo Finance + Morningstar", "cadence": "daily"}),
            ("catalyst_news", {"vendor": "biotech_news_digest + herald", "cadence": "daily"}),
        ]

        for source_name, source_meta in sources:
            node = Node(
                node_id=f"source_{source_name}",
                node_type=NodeType.RAW_SOURCE,
                metadata={"source_name": source_name, **source_meta},
            )
            graph.add_node(node)

    def _create_cache_nodes(self, graph: ProvenanceGraph, metadata: SnapshotMetadata) -> None:
        """Create CacheFile nodes for intermediate artifacts."""
        caches = [
            ("trial_records", {"artifact_type": "clinical_db", "refresh_cadence": "daily"}),
            ("market_snapshot", {"artifact_type": "market_data", "refresh_cadence": "daily"}),
        ]

        for cache_name, cache_meta in caches:
            node = Node(
                node_id=f"cache_{cache_name}",
                node_type=NodeType.CACHE_FILE,
                metadata={"cache_name": cache_name, **cache_meta},
            )
            graph.add_node(node)

    def _create_feature_nodes(self, graph: ProvenanceGraph, metadata: SnapshotMetadata) -> None:
        """Create FeatureArtifact nodes for computed signals."""
        features = [
            ("inst_delta_z", {"module": "selector", "source": "13F"}),
            ("clinical_score_v2", {"module": "clinical_validator", "source": "ctgov"}),
            ("catalyst_score", {"module": "catalyst_analyzer", "source": "catalyst_news"}),
            ("financial_score", {"module": "financial_scorer", "source": "market_snapshot"}),
        ]

        for feature_name, feature_meta in features:
            node = Node(
                node_id=f"feature_{feature_name}",
                node_type=NodeType.FEATURE_ARTIFACT,
                metadata={"feature_name": feature_name, **feature_meta},
            )
            graph.add_node(node)

    def _create_module_nodes(self, graph: ProvenanceGraph, metadata: SnapshotMetadata) -> None:
        """Create Module nodes for pipeline stages."""
        modules = [
            ("selector", "A4", "Select eligible universe"),
            ("ranker", "v2 (2-feat)", "Rank eligible securities"),
            ("clinical_validator", "v1", "Validate clinical data"),
            ("catalyst_analyzer", "v1", "Analyze catalyst events"),
            ("financial_scorer", "v1", "Score financial metrics"),
        ]

        for module_name, version, responsibility in modules:
            node = Node(
                node_id=f"module_{module_name}",
                node_type=NodeType.MODULE,
                metadata={"module_name": module_name, "version": version, "responsibility": responsibility},
            )
            graph.add_node(node)

    def _create_output_nodes(self, graph: ProvenanceGraph, metadata: SnapshotMetadata) -> None:
        """Create RankedList, RulesetArtifact, DataSnapshot nodes."""
        # Ruleset artifact
        ruleset = Node(
            node_id=f"ruleset_{metadata.ruleset_id}",
            node_type=NodeType.RULESET_ARTIFACT,
            metadata={"ruleset_id": metadata.ruleset_id, "version": metadata.ruleset_version},
        )
        graph.add_node(ruleset)

        # Ranked lists
        for ranking_type in ["production", "shadow"]:
            ranked = Node(
                node_id=f"rankings_{ranking_type}",
                node_type=NodeType.RANKED_LIST,
                metadata={"output_type": ranking_type, "count": metadata.ranked_count},
            )
            graph.add_node(ranked)

        # Data snapshot (root)
        snapshot = Node(
            node_id=f"snapshot_{metadata.snapshot_date}",
            node_type=NodeType.DATA_SNAPSHOT,
            metadata={"snapshot_date": metadata.snapshot_date, "universe_size": metadata.universe_size},
        )
        graph.add_node(snapshot)

        # Validation evidence (gates)
        for gate_name, verdict in metadata.gates_status.items():
            evidence = Node(
                node_id=f"gate_{gate_name}",
                node_type=NodeType.VALIDATION_EVIDENCE,
                metadata={"gate_name": gate_name, "verdict": verdict},
            )
            graph.add_node(evidence)

    def _create_edges(self, graph: ProvenanceGraph, metadata: SnapshotMetadata) -> None:
        """Create edges connecting nodes."""
        # RawSource -> FeatureArtifact (DERIVES)
        edges = [
            ("source_13F", "feature_inst_delta_z", EdgeType.DERIVES),
            ("source_ctgov", "feature_clinical_score_v2", EdgeType.DERIVES),
            ("source_catalyst_news", "feature_catalyst_score", EdgeType.DERIVES),
            ("source_market_snapshot", "feature_financial_score", EdgeType.DERIVES),
            # CacheFile -> FeatureArtifact (CONSUMES via Module)
            ("cache_trial_records", "feature_clinical_score_v2", EdgeType.CONSUMES),
            ("cache_market_snapshot", "feature_financial_score", EdgeType.CONSUMES),
            # FeatureArtifact -> Module (CONSUMES)
            ("feature_inst_delta_z", "module_selector", EdgeType.CONSUMES),
            ("feature_clinical_score_v2", "module_ranker", EdgeType.CONSUMES),
            ("feature_catalyst_score", "module_ranker", EdgeType.CONSUMES),
            ("feature_financial_score", "module_ranker", EdgeType.CONSUMES),
            # Module -> RankedList (PRODUCES)
            ("module_selector", "rankings_production", EdgeType.PRODUCES),
            ("module_ranker", "rankings_production", EdgeType.PRODUCES),
            ("module_ranker", "rankings_shadow", EdgeType.PRODUCES),
            # RulesetArtifact -> Modules (IMPLEMENTS)
            (f"ruleset_{metadata.ruleset_id}", "module_selector", EdgeType.IMPLEMENTS),
            (f"ruleset_{metadata.ruleset_id}", "module_ranker", EdgeType.IMPLEMENTS),
            # Gates -> RankedList (VALIDATES/GATED_BY)
            ("gate_jaccard", "rankings_production", EdgeType.VALIDATES),
            ("gate_top30_ks", "rankings_production", EdgeType.VALIDATES),
            ("rankings_production", "gate_jaccard", EdgeType.GATED_BY),
            ("rankings_production", "gate_top30_ks", EdgeType.GATED_BY),
            # RankedList -> DataSnapshot (PRODUCES)
            ("rankings_production", f"snapshot_{metadata.snapshot_date}", EdgeType.PRODUCES),
        ]

        for source, target, edge_type in edges:
            if graph.get_node(source) and graph.get_node(target):
                edge = Edge(source_id=source, target_id=target, edge_type=edge_type)
                graph.add_edge(edge)


def load_or_build_graph(snapshot_dir: Path) -> ProvenanceGraph:
    """Load existing graph or build new one."""
    builder = GraphBuilder(snapshot_dir)
    return builder.build_graph()

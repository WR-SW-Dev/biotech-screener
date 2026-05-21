#!/usr/bin/env python
"""
Spec 110 PoC: Generate provenance lineage for snapshot and run query patterns.

Usage:
    python -m tools.gen_provenance_lineage 2026-05-20
"""

import json
import sys
from pathlib import Path
from tools.provenance_graph import GraphBuilder
from tools.graph_queries import run_all_queries


def main(snapshot_date: str):
    """Generate lineage for snapshot and save query results."""
    snapshot_dir = Path(f"data/snapshots/{snapshot_date}")

    if not snapshot_dir.exists():
        print(f"Error: {snapshot_dir} not found")
        return 1

    print(f"Building provenance graph for {snapshot_date}...")
    builder = GraphBuilder(snapshot_dir)
    graph = builder.build_graph()

    print(f"  Nodes: {len(graph.nodes)}")
    print(f"  Edges: {len(graph.edges)}")

    # Run all query patterns
    print(f"\nExecuting 5 query patterns...")
    results = run_all_queries(graph)

    # Save results
    artifacts_dir = Path("artifacts/ops/knowledge_layer")
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    output_file = artifacts_dir / f"lineage_{snapshot_date}.json"
    with open(output_file, "w") as f:
        json.dump({
            "snapshot_date": snapshot_date,
            "graph": graph.to_dict(),
            "queries": results
        }, f, indent=2)

    print(f"\nResults saved to {output_file}")

    # Print summaries
    print(f"\nQuery Results Summary:")
    print(f"  Lineage: {results['lineage'].get('node_count', 'N/A')} nodes")
    print(f"  Snapshot Inputs: {results['snapshot_inputs'].get('total_sources', 'N/A')} sources")
    print(f"  Stale Features: {len(results['stale_features'].get('stale_features', []))} stale")
    print(f"  Validate Status: {results['validate_snapshot'].get('overall_status', 'N/A')}")

    return 0


if __name__ == "__main__":
    snapshot_date = sys.argv[1] if len(sys.argv) > 1 else "2026-05-20"
    sys.exit(main(snapshot_date))

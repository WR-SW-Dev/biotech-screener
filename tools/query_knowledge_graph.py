#!/usr/bin/env python3
"""
Query the Spec 089 Knowledge Graph.

Supports 5 query patterns:
- what-blocks <target>: List all blockers for an action/spec
- spec-status <spec_id>: Show spec status, dependencies, contradictions
- contradictions: List all detected contradictions
- next-actions: Find unblocked actions that can proceed
- what-touches <file>: Find specs/actions that touch a file

Read-only. Does NOT modify any state.
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# ============================================================================
# CONFIGURATION
# ============================================================================

REPO_ROOT = Path(__file__).parent.parent
ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "ops" / "knowledge_graph"
NODES_FILE = ARTIFACTS_DIR / "nodes.jsonl"
EDGES_FILE = ARTIFACTS_DIR / "edges.jsonl"


# ============================================================================
# GRAPH LOADER
# ============================================================================


def load_graph() -> Tuple[Dict[str, Dict], List[Dict]]:
    """Load nodes and edges from JSONL files."""
    nodes = {}
    edges = []

    if not NODES_FILE.exists() or not EDGES_FILE.exists():
        print(f"Error: Knowledge graph not found at {ARTIFACTS_DIR}")
        print("Run: python tools/build_knowledge_graph.py")
        sys.exit(1)

    # Load nodes
    with open(NODES_FILE) as f:
        for line in f:
            if line.strip():
                node = json.loads(line)
                nodes[node["id"]] = node

    # Load edges
    with open(EDGES_FILE) as f:
        for line in f:
            if line.strip():
                edge = json.loads(line)
                edges.append(edge)

    return nodes, edges


# ============================================================================
# GRAPH UTILITIES
# ============================================================================


def find_node(nodes: Dict, query: str) -> str:
    """Find node ID by partial match."""
    query_lower = query.lower()

    # Exact match
    if query in nodes:
        return query

    # Substring match in ID
    for node_id in nodes:
        if query_lower in node_id.lower():
            return node_id

    # Substring match in title
    for node_id, node in nodes.items():
        if query_lower in node.get("title", "").lower():
            return node_id

    return None


def bfs_predecessors(node_id: str, edges: List, max_depth: int = 5) -> Dict[str, int]:
    """Find all predecessors (nodes that have edges TO this node)."""
    predecessors = {}
    visited = set()
    queue = [(node_id, 0)]

    while queue:
        current, depth = queue.pop(0)
        if current in visited or depth > max_depth:
            continue
        visited.add(current)

        # Find edges targeting current node
        for edge in edges:
            if edge["target"] == current:
                source = edge["source"]
                if source not in predecessors:
                    predecessors[source] = depth + 1
                    queue.append((source, depth + 1))

    return predecessors


def bfs_successors(node_id: str, edges: List, max_depth: int = 5) -> Dict[str, int]:
    """Find all successors (nodes this node has edges TO)."""
    successors = {}
    visited = set()
    queue = [(node_id, 0)]

    while queue:
        current, depth = queue.pop(0)
        if current in visited or depth > max_depth:
            continue
        visited.add(current)

        # Find edges from current node
        for edge in edges:
            if edge["source"] == current:
                target = edge["target"]
                if target not in successors:
                    successors[target] = depth + 1
                    queue.append((target, depth + 1))

    return successors


def find_blocking_edges(target: str, edges: List) -> List[Dict]:
    """Find all BLOCKS/DEPENDS_ON/PENDING_ON edges targeting a node."""
    blocking_types = {"BLOCKS", "DEPENDS_ON", "PENDING_ON"}
    return [e for e in edges if e["target"] == target and e["type"] in blocking_types]


# ============================================================================
# QUERY: what-blocks
# ============================================================================


def query_what_blocks(target: str, nodes: Dict, edges: List) -> None:
    """Query: what-blocks <target> → list all blockers."""
    target_id = find_node(nodes, target)

    if not target_id:
        print(f"Error: Target '{target}' not found")
        return

    if target_id not in nodes:
        print(f"Error: Target '{target_id}' not in graph")
        return

    blocking = find_blocking_edges(target_id, edges)

    if not blocking:
        print(f"{target_id}: Not blocked (can proceed)")
        return

    target_node = nodes[target_id]
    print(f"\n{target_id} ({target_node.get('type')}: {target_node.get('title')})")
    print(f"Status: {target_node.get('status')}")
    print(f"\nBlocked by ({len(blocking)}):")

    for edge in blocking:
        blocker_id = edge["source"]
        blocker_node = nodes.get(blocker_id, {})
        blocker_type = blocker_node.get("type", "unknown")
        blocker_title = blocker_node.get("title", blocker_id)
        blocker_status = blocker_node.get("status", "unknown")

        print(f"  • {blocker_id} ({blocker_type}, {blocker_status})")
        print(f"    Title: {blocker_title}")
        print(f"    Edge type: {edge['type']}")


# ============================================================================
# QUERY: spec-status
# ============================================================================


def query_spec_status(spec_id: str, nodes: Dict, edges: List) -> None:
    """Query: spec-status <spec_id> → show status, dependencies, contradictions."""
    spec_node_id = find_node(nodes, spec_id)

    if not spec_node_id:
        print(f"Error: Spec '{spec_id}' not found")
        return

    if spec_node_id not in nodes:
        print(f"Error: Spec '{spec_node_id}' not in graph")
        return

    node = nodes[spec_node_id]

    print(f"\n{spec_node_id}")
    print(f"Type: {node.get('type')}")
    print(f"Title: {node.get('title')}")
    print(f"Status: {node.get('status')}")

    # Find dependents (specs that depend on this one)
    dependents = [e["source"] for e in edges if e["target"] == spec_node_id and e["type"] in {"DEPENDS_ON", "REQUIRES"}]

    if dependents:
        print(f"\nRequired by ({len(dependents)}):")
        for dep_id in dependents:
            dep = nodes.get(dep_id, {})
            print(f"  • {dep_id}: {dep.get('title', '(no title)')}")

    # Find dependencies (specs this one depends on)
    dependencies = [
        e["target"] for e in edges if e["source"] == spec_node_id and e["type"] in {"DEPENDS_ON", "REQUIRES"}
    ]

    if dependencies:
        print(f"\nDepends on ({len(dependencies)}):")
        for dep_id in dependencies:
            dep = nodes.get(dep_id, {})
            print(f"  • {dep_id}: {dep.get('title', '(no title)')}")

    # Find contradictions
    contradictions = [
        e for e in edges if (e["source"] == spec_node_id or e["target"] == spec_node_id) and e["type"] == "CONTRADICTS"
    ]

    if contradictions:
        print(f"\nContradictions ({len(contradictions)}):")
        for edge in contradictions:
            other_id = edge["target"] if edge["source"] == spec_node_id else edge["source"]
            other = nodes.get(other_id, {})
            print(f"  • {other_id}: {other.get('title', '(no title)')}")

    # Related artifacts
    artifacts = node.get("related_artifacts", [])
    if artifacts:
        print(f"\nRelated artifacts ({len(artifacts)}):")
        for art in artifacts[:5]:  # Show first 5
            print(f"  • {art}")
        if len(artifacts) > 5:
            print(f"  ... and {len(artifacts) - 5} more")


# ============================================================================
# QUERY: contradictions
# ============================================================================


def query_contradictions(nodes: Dict, edges: List) -> None:
    """Query: contradictions → list all contradictions in graph."""
    contradicts = [e for e in edges if e["type"] == "CONTRADICTS"]

    if not contradicts:
        print("\nNo contradictions detected in graph.")
        return

    print(f"\nContradictions detected ({len(contradicts)}):\n")

    for edge in contradicts:
        source_id = edge["source"]
        target_id = edge["target"]
        source = nodes.get(source_id, {})
        target = nodes.get(target_id, {})

        print(f"  ⚠ {source_id} CONTRADICTS {target_id}")
        print(f"    {source_id}: {source.get('title', '(no title)')} [{source.get('status')}]")
        print(f"    {target_id}: {target.get('title', '(no title)')} [{target.get('status')}]")
        print()


# ============================================================================
# QUERY: next-actions
# ============================================================================


def query_next_actions(nodes: Dict, edges: List) -> None:
    """Query: next-actions → find unblocked actions that can proceed."""
    actions = {node_id: node for node_id, node in nodes.items() if node.get("type") == "Action"}

    if not actions:
        print("\nNo actions in graph.")
        return

    print(f"\nActions in graph ({len(actions)}):\n")

    unblocked = []
    blocked = []

    for action_id, action in actions.items():
        blockers = find_blocking_edges(action_id, edges)

        action_status = action.get("status", "unknown")
        action_title = action.get("title", action_id)

        if blockers:
            blocked.append((action_id, action_title, action_status, len(blockers)))
        else:
            unblocked.append((action_id, action_title, action_status))

    if unblocked:
        print("  ✓ UNBLOCKED (can proceed):")
        for action_id, title, status in unblocked:
            print(f"    • {action_id}: {title} [{status}]")

    if blocked:
        print("\n  ✗ BLOCKED:")
        for action_id, title, status, blocker_count in blocked:
            print(f"    • {action_id}: {title} [{status}] ({blocker_count} blockers)")


# ============================================================================
# QUERY: what-touches
# ============================================================================


def query_what_touches(file_pattern: str, nodes: Dict, edges: List) -> None:
    """Query: what-touches <file> → find specs/actions that touch file."""
    file_lower = file_pattern.lower()

    # Find edges where target matches file pattern
    touching = [e for e in edges if file_lower in e.get("target", "").lower() and e["type"] == "TOUCHES"]

    if not touching:
        print(f"\nNo specs/actions touching '{file_pattern}'")
        return

    print(f"\nSpecs/Actions touching '{file_pattern}' ({len(touching)}):\n")

    for edge in touching:
        source_id = edge["source"]
        source = nodes.get(source_id, {})
        source_type = source.get("type", "unknown")
        source_title = source.get("title", source_id)
        source_status = source.get("status", "unknown")

        print(f"  • {source_id} ({source_type}, {source_status})")
        print(f"    {source_title}")
        print(f"    Touches: {edge['target']}")
        print()


# ============================================================================
# MAIN / CLI
# ============================================================================


def print_help():
    """Print usage help."""
    print("""
Knowledge Graph Query Tool (Spec 089, Phase 1.5A)

Usage:
  python query_knowledge_graph.py [QUERY] [ARGS]

Queries:
  what-blocks <target>          List all blockers for an action/spec
  spec-status <spec_id>         Show spec status and dependencies
  contradictions                List all detected contradictions
  next-actions                  Find unblocked actions
  what-touches <file>           Find specs/actions touching a file
  help                          Show this help

Examples:
  python query_knowledge_graph.py what-blocks production-ranker-change
  python query_knowledge_graph.py spec-status spec_100
  python query_knowledge_graph.py contradictions
  python query_knowledge_graph.py next-actions
  python query_knowledge_graph.py what-touches run_screen.py
""")


def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2 or sys.argv[1] in {"help", "-h", "--help"}:
        print_help()
        return

    # Load graph
    nodes, edges = load_graph()
    print(f"[kg_query] Loaded: {len(nodes)} nodes, {len(edges)} edges\n")

    query = sys.argv[1]
    args = sys.argv[2:] if len(sys.argv) > 2 else []

    # Route query
    if query == "what-blocks":
        if not args:
            print("Usage: what-blocks <target>")
            return
        query_what_blocks(args[0], nodes, edges)

    elif query == "spec-status":
        if not args:
            print("Usage: spec-status <spec_id>")
            return
        query_spec_status(args[0], nodes, edges)

    elif query == "contradictions":
        query_contradictions(nodes, edges)

    elif query == "next-actions":
        query_next_actions(nodes, edges)

    elif query == "what-touches":
        if not args:
            print("Usage: what-touches <file>")
            return
        query_what_touches(args[0], nodes, edges)

    else:
        print(f"Unknown query: {query}")
        print_help()


if __name__ == "__main__":
    main()

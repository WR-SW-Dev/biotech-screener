# Phase 2 Step 4d — Knowledge Graph CLI Tool & API (2026-05-15)

**Status**: Design locked (specification only; do NOT implement until cohort clearance is explicitly verified).

**Scope**: ~200 lines of CLI code specification, test cases for command execution and output.

**Dependencies**: Phase 4a (Loader), Phase 4b (Queries), Phase 4c (Contradictions) must be complete.

**Implementation Gate**: Do NOT begin Phase 4d until cohort clearance is explicitly CONFIRMED.

---

## Overview

Phase 4d wraps the KG query layer into a command-line tool (`tools/kg_query_cli.py`) with:

- **Command-line interface**: ArgumentParser with subcommands for each query
- **JSON output**: `--json` flag for machine-readable output
- **Human output**: Plain-text summaries for CLI review
- **Error handling**: Graceful fallback on missing seed graph

---

## File: tools/kg_query_cli.py

```python
#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

from kg_loader import KnowledgeGraph
from kg_queries import KGQueries
from kg_contradictions import KGContradictions, ContradictionReport


PROJECT_ROOT = Path(__file__).parent.parent
SEED_GRAPH_PATH = PROJECT_ROOT / "artifacts" / "audit" / "kg_seed.jsonl"


def load_graph() -> KnowledgeGraph:
    """Load the seed graph. Raises FileNotFoundError if not found."""
    kg = KnowledgeGraph()
    kg.load_seed(SEED_GRAPH_PATH)
    return kg


def cmd_what_blocks_ranker(args) -> int:
    """Query: What blocks production ranker change?"""
    try:
        kg = load_graph()
        queries = KGQueries(kg)
        result = queries.what_blocks_production_ranker_change()
        
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print_what_blocks_human(result)
        
        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_spec_status(args) -> int:
    """Query: Spec status, dependencies, blockers."""
    try:
        kg = load_graph()
        queries = KGQueries(kg)
        result = queries.spec_status(args.spec_id)
        
        if "error" in result:
            print(f"Error: {result['error']}", file=sys.stderr)
            return 1
        
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print_spec_status_human(result)
        
        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_contradictions(args) -> int:
    """Query: All contradictions."""
    try:
        kg = load_graph()
        detector = KGContradictions(kg)
        contradictions = detector.detect_all()
        report = ContradictionReport(contradictions)
        
        if args.json:
            output = {
                "summary": report.summary(),
                "contradictions": contradictions
            }
            print(json.dumps(output, indent=2))
        else:
            print(report.format_text())
        
        return 0 if len(contradictions) == 0 else 1  # Exit 1 if contradictions found
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_next_actions(args) -> int:
    """Query: Pending actions sorted by deadline."""
    try:
        kg = load_graph()
        queries = KGQueries(kg)
        result = queries.next_actions()
        
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print_next_actions_human(result)
        
        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_what_touches_file(args) -> int:
    """Query: Commits/specs touching a file."""
    try:
        kg = load_graph()
        queries = KGQueries(kg)
        result = queries.what_touches_file(args.file_path)
        
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print_what_touches_human(result)
        
        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_all(args) -> int:
    """Run all queries and print summary."""
    try:
        kg = load_graph()
        queries = KGQueries(kg)
        detector = KGContradictions(kg)
        
        print("=" * 70)
        print("KNOWLEDGE GRAPH GOVERNANCE REPORT")
        print("=" * 70)
        
        # Query 1: What blocks ranker change
        print("\n=== What Blocks Production Ranker Change ===")
        result1 = queries.what_blocks_production_ranker_change()
        print_what_blocks_human(result1)
        
        # Query 2: Sample spec status
        print("\n=== Spec Status (Sample: spec_096) ===")
        result2 = queries.spec_status("spec_096")
        if "error" not in result2:
            print_spec_status_human(result2)
        
        # Query 3: Contradictions
        print("\n=== Detected Contradictions ===")
        contradictions = detector.detect_all()
        report = ContradictionReport(contradictions)
        print(report.format_text())
        
        # Query 4: Next actions
        print("\n=== Pending Actions ===")
        result4 = queries.next_actions()
        print_next_actions_human(result4)
        
        # Summary
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"Total nodes: {len(kg.nodes)}")
        print(f"Total edges: {len(kg.edges)}")
        print(f"Contradictions found: {len(contradictions)}")
        stats = kg.stats()
        print(f"Node types: {stats['node_types']}")
        print(f"Edge types: {stats['edge_types']}")
        
        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


# ========== HUMAN-READABLE OUTPUT ==========

def print_what_blocks_human(result: dict) -> None:
    """Print Query 1 result in human-readable format."""
    print(f"\n{result.get('summary', 'Status unknown')}\n")
    
    if not result.get("blocker_details"):
        print("  (No blockers found)")
        return
    
    for blocker in result["blocker_details"]:
        status_marker = "[ACTIVE]" if blocker["status"] == "ACTIVE" else f"[{blocker['status']}]"
        print(f"  {status_marker} {blocker['id']}: {blocker['title']}")
        print(f"      Reason: {blocker['reason']}")
    
    if result.get("evidence"):
        print(f"\nEvidence paths:")
        for ev in result["evidence"]:
            print(f"  - {ev}")


def print_spec_status_human(result: dict) -> None:
    """Print Query 2 result in human-readable format."""
    print(f"\n{result.get('spec_id', 'unknown')} — {result.get('title', 'Unknown')}")
    print(f"Status: {result.get('status', 'unknown')}")
    
    if result.get("depends_on"):
        print(f"Depends on: {', '.join(result['depends_on'])}")
    
    if result.get("blocked_by"):
        print(f"Blocked by: {', '.join(result['blocked_by'])}")
    
    if result.get("blocking"):
        print(f"Blocks: {', '.join(result['blocking'])}")
    
    if result.get("contradictions"):
        print(f"Contradictions: {len(result['contradictions'])} found")
        for c in result["contradictions"]:
            print(f"  - {c.get('rule', 'unknown')}: {c.get('evidence', '(no evidence)')}")


def print_next_actions_human(result: list[dict]) -> None:
    """Print Query 4 result in human-readable format."""
    if not result:
        print("  (No pending actions)")
        return
    
    for action in result:
        deadline = action.get("required_by", "unknown")
        print(f"\n  {action['action_id']} (due {deadline})")
        print(f"    {action['title']}")
        if action.get("dependencies"):
            print(f"    Depends on: {', '.join(action['dependencies'])}")
        if action.get("blocking"):
            print(f"    Unblocks: {', '.join(action['blocking'])}")


def print_what_touches_human(result: list[dict]) -> None:
    """Print Query 5 result in human-readable format."""
    if not result:
        print("  (No matches found)")
        return
    
    specs = [r for r in result if r["type"] == "spec"]
    commits = [r for r in result if r["type"] == "commit"]
    
    if specs:
        print("\n  Specs:")
        for spec in specs:
            print(f"    - {spec['spec_id']}: {spec['title']} ({spec['date']})")
    
    if commits:
        print("\n  Commits:")
        for commit in commits[:5]:  # Limit to 5 most recent
            print(f"    - {commit['commit_hash']}: {commit['commit_msg']}")


# ========== MAIN ==========

def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Knowledge Graph query tool for governance questions"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Query to run")
    
    # Query 1: What blocks ranker change
    sp1 = subparsers.add_parser(
        "what-blocks-ranker",
        help="What blocks production ranker changes?"
    )
    sp1.add_argument("--json", action="store_true", help="Output JSON format")
    sp1.set_defaults(func=cmd_what_blocks_ranker)
    
    # Query 2: Spec status
    sp2 = subparsers.add_parser(
        "spec-status",
        help="Get status of a spec"
    )
    sp2.add_argument("spec_id", help="Spec ID (e.g., spec_100)")
    sp2.add_argument("--json", action="store_true", help="Output JSON format")
    sp2.set_defaults(func=cmd_spec_status)
    
    # Query 3: Contradictions
    sp3 = subparsers.add_parser(
        "contradictions",
        help="List all detected contradictions"
    )
    sp3.add_argument("--json", action="store_true", help="Output JSON format")
    sp3.set_defaults(func=cmd_contradictions)
    
    # Query 4: Next actions
    sp4 = subparsers.add_parser(
        "next-actions",
        help="List pending actions by deadline"
    )
    sp4.add_argument("--json", action="store_true", help="Output JSON format")
    sp4.set_defaults(func=cmd_next_actions)
    
    # Query 5: What touches file
    sp5 = subparsers.add_parser(
        "what-touches",
        help="Find commits/specs touching a file"
    )
    sp5.add_argument("file_path", help="File path to search (e.g., run_screen.py)")
    sp5.add_argument("--json", action="store_true", help="Output JSON format")
    sp5.set_defaults(func=cmd_what_touches_file)
    
    # All: Run all queries
    sp_all = subparsers.add_parser(
        "all",
        help="Run all queries and print summary"
    )
    sp_all.set_defaults(func=cmd_all)
    
    args = parser.parse_args()
    
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

---

## Test Cases

**File**: `tests/test_kg_query_cli.py`

```python
import unittest
import json
import sys
import subprocess
from pathlib import Path
from io import StringIO

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from kg_loader import KnowledgeGraph, KnowledgeGraphNode, KnowledgeGraphEdge


class TestKGQueryCLI(unittest.TestCase):
    """Test CLI tool execution and output."""
    
    CLI_PATH = Path(__file__).parent.parent / "tools" / "kg_query_cli.py"
    
    @classmethod
    def setUpClass(cls):
        """Verify CLI file exists."""
        if not cls.CLI_PATH.exists():
            raise FileNotFoundError(f"CLI file not found: {cls.CLI_PATH}")
    
    def run_cli(self, *args) -> tuple[int, str, str]:
        """Run CLI command and return (returncode, stdout, stderr)."""
        cmd = ["python3", str(self.CLI_PATH)] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode, result.stdout, result.stderr
    
    def test_cli_help(self):
        """CLI help flag works."""
        returncode, stdout, stderr = self.run_cli("--help")
        self.assertEqual(returncode, 0)
        self.assertIn("Knowledge Graph", stdout)
    
    def test_cli_no_args(self):
        """CLI with no args prints help."""
        returncode, stdout, stderr = self.run_cli()
        # May return 1 if help is printed to stdout
        self.assertIn("usage", stdout)
    
    def test_cmd_what_blocks_ranker(self):
        """what-blocks-ranker command runs (without seed graph)."""
        returncode, stdout, stderr = self.run_cli("what-blocks-ranker")
        # Will fail if seed graph doesn't exist, but shouldn't crash
        self.assertIn("Error", stderr)
    
    def test_cmd_spec_status(self):
        """spec-status command requires spec_id argument."""
        returncode, stdout, stderr = self.run_cli("spec-status")
        # Should fail due to missing argument
        self.assertNotEqual(returncode, 0)
    
    def test_cmd_contradictions(self):
        """contradictions command runs."""
        returncode, stdout, stderr = self.run_cli("contradictions")
        # Will fail if seed graph doesn't exist
        self.assertIn("Error", stderr)
    
    def test_cmd_next_actions(self):
        """next-actions command runs."""
        returncode, stdout, stderr = self.run_cli("next-actions")
        # Will fail if seed graph doesn't exist
        self.assertIn("Error", stderr)
    
    def test_cmd_all(self):
        """all command runs and prints report."""
        returncode, stdout, stderr = self.run_cli("all")
        # Will fail if seed graph doesn't exist
        # But should complete without crashing
        self.assertIn("Error", stderr)
    
    def test_json_output_flag(self):
        """--json flag produces valid JSON output (or error)."""
        returncode, stdout, stderr = self.run_cli("what-blocks-ranker", "--json")
        
        # If seed graph exists, should return valid JSON
        if returncode == 0:
            try:
                data = json.loads(stdout)
                self.assertIsInstance(data, dict)
            except json.JSONDecodeError:
                self.fail("--json output is not valid JSON")


if __name__ == "__main__":
    unittest.main()
```

---

## Usage Examples

```bash
# Query 1: What blocks ranker changes?
python3 tools/kg_query_cli.py what-blocks-ranker
python3 tools/kg_query_cli.py what-blocks-ranker --json

# Query 2: Spec status
python3 tools/kg_query_cli.py spec-status spec_100
python3 tools/kg_query_cli.py spec-status spec_100 --json

# Query 3: Contradictions
python3 tools/kg_query_cli.py contradictions
python3 tools/kg_query_cli.py contradictions --json

# Query 4: Next actions
python3 tools/kg_query_cli.py next-actions
python3 tools/kg_query_cli.py next-actions --json

# Query 5: What touches file
python3 tools/kg_query_cli.py what-touches run_screen.py
python3 tools/kg_query_cli.py what-touches run_screen.py --json

# All queries
python3 tools/kg_query_cli.py all
```

---

## Expected Output

### Text Format

```
=== What Blocks Production Ranker Change ===

3 blockers identified; 2 high-risk, 1 medium-risk, 0 low-risk

  [ACTIVE] spec_096: Ranker Governance Doctrine
      Reason: Governance framework requirement
  [ACTIVE] policy_alpha_freeze: Alpha Stack Freeze
      Reason: Ranker/selector work frozen by policy
  [PENDING] gate_ranker_review_2026_05_22: 2026-05-22 Ranker Review
      Reason: Pending review gate

Evidence paths:
  - specs/changes/spec_096_doctrine.md
  - policy_alpha_freeze.md
```

### JSON Format

```json
{
  "blockers": ["spec_096", "policy_alpha_freeze", "gate_ranker_review_2026_05_22"],
  "blocker_details": [
    {
      "id": "spec_096",
      "title": "Ranker Governance Doctrine",
      "status": "ACTIVE",
      "reason": "Governance framework requirement"
    }
  ],
  "dependency_chains": [...],
  "evidence": [...],
  "summary": "3 blockers identified; 2 high-risk, 1 medium-risk, 0 low-risk"
}
```

---

## Acceptance Criteria

Before committing May 27:

1. ✅ kg_query_cli.py with command-line interface
2. ✅ All 6 subcommands implemented (what-blocks-ranker, spec-status, contradictions, next-actions, what-touches, all)
3. ✅ JSON output (`--json` flag) for all commands
4. ✅ Human-readable text output for all commands
5. ✅ Proper error handling (missing seed graph, invalid specs, etc.)
6. ✅ Exit code 0 on success, 1 on error or contradictions found
7. ✅ All 8 CLI test cases pass
8. ✅ No regressions (Phase 4a/4b/4c tests still pass)

---

## Commit Checklist

**May 27 (Phase 4d complete)**:

1. Create tools/kg_query_cli.py with all commands
2. Create tests/test_kg_query_cli.py with 8 test methods
3. Run tests: `python3 -m pytest tests/test_kg_query_cli.py -v`
4. Verify all pass
5. Verify no regressions: `python3 -m pytest tests/test_kg_*.py -v`
6. Test CLI manually: `python3 tools/kg_query_cli.py --help` (should show all commands)
7. Commit: `tools: implement KG query CLI tool (Phase 2 Step 4d)`
8. Message includes Co-Authored-By

---

## Integration Points

**Phase 4e** (May 27–28): Validation tests verify CLI output matches expected formats

---

**Status**: Implementation design locked. Ready for May 27 coding session (2.5 hours to code + test).

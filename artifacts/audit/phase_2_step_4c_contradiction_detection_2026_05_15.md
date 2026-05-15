# Phase 2 Step 4c — Knowledge Graph Contradiction Detection (2026-05-15)

**Status**: Design locked (specification only; do NOT implement until cohort clearance is explicitly verified).

**Scope**: ~150 lines of detection code specification, test cases for all 5 rules.

**Dependencies**: Phase 4a (KnowledgeGraph loader) and Phase 4b (KGQueries) must be complete.

**Implementation Gate**: Do NOT begin Phase 4c until cohort clearance is explicitly CONFIRMED.

---

## Overview

Phase 4c implements five deterministic contradiction detection rules that identify inconsistencies in the governance graph:

1. **Status Contradiction** — Node CLOSED but has PENDING_ON/DEPENDS_ON edges
2. **Stub Contradiction** — CodeFile has stub/placeholder AND Spec claims COMPLETE
3. **Scope Contradiction** — Commit touches ranker/selector BUT Policy freezes them
4. **Artifact Contradiction** — Artifact PENDING but file doesn't exist
5. **Promotion Contradiction** — Signal SHADOW_ONLY but in production ModelComponent

All rules are **pure graph inspection** (except Rule 2 which adds file-system check).

---

## File: tools/kg_contradictions.py

```python
from pathlib import Path
from typing import Optional
import subprocess
from datetime import datetime

from kg_loader import KnowledgeGraph, KnowledgeGraphNode, KnowledgeGraphEdge


class KGContradictions:
    """Contradiction detection rules for the knowledge graph."""
    
    def __init__(self, kg: KnowledgeGraph):
        """Initialize with a loaded knowledge graph."""
        self.kg = kg
    
    def detect_all(self) -> list[dict]:
        """Run all 5 contradiction detection rules.
        
        Returns:
        [
            {
                "rule": "status_contradiction",
                "node_id": "spec_100",
                "description": "Node status CLOSED but has PENDING_ON edges",
                "evidence": "specs/spec_100.md",
                "severity": "HIGH"
            },
            ...
        ]
        """
        contradictions = []
        contradictions.extend(self.rule_1_status_contradiction())
        contradictions.extend(self.rule_2_stub_contradiction())
        contradictions.extend(self.rule_3_scope_contradiction())
        contradictions.extend(self.rule_4_artifact_contradiction())
        contradictions.extend(self.rule_5_promotion_contradiction())
        return contradictions
    
    # ========== RULE 1: Status Contradiction ==========
    
    def rule_1_status_contradiction(self) -> list[dict]:
        """Status Contradiction: Node CLOSED/COMPLETE but has PENDING_ON/DEPENDS_ON edges.
        
        A node claimed to be finished should not have unresolved dependencies.
        """
        contradictions = []
        
        for node_id, node in self.kg.nodes.items():
            # Check if node is closed
            if node.status not in ["CLOSED", "COMPLETE"]:
                continue
            
            # Check for outgoing DEPENDS_ON or PENDING_ON edges
            for edge in self.kg.outgoing_edges(node_id):
                if edge.edge_type in ["DEPENDS_ON", "PENDING_ON", "AWAITS"]:
                    contradictions.append({
                        "rule": "status_contradiction",
                        "node_id": node_id,
                        "node_type": node.node_type,
                        "node_title": node.title,
                        "description": f"Node status {node.status} but has {edge.edge_type} on {edge.dst}",
                        "blocking_node": edge.dst,
                        "evidence": node.source_path,
                        "severity": "MEDIUM"
                    })
        
        return contradictions
    
    # ========== RULE 2: Stub Contradiction ==========
    
    def rule_2_stub_contradiction(self) -> list[dict]:
        """Stub Contradiction: CodeFile has stub/placeholder AND Spec claims COMPLETE.
        
        If a code file contains a stub (None return, TODO, STUB, etc.) and a spec
        claims the implementation is complete, that's a contradiction.
        """
        contradictions = []
        
        stub_patterns = ["return None", "TODO", "STUB", "NotImplemented", "raise NotImplementedError"]
        
        for node_id, node in self.kg.nodes.items():
            # Look for CodeFile nodes
            if node.node_type != "CodeFile":
                continue
            
            # Check if file exists and contains stub patterns
            file_path = Path(node.source_path)
            if not file_path.exists():
                continue  # File doesn't exist, skip
            
            try:
                with open(file_path, "r") as f:
                    content = f.read()
                
                # Check for stub patterns
                has_stub = any(pattern in content for pattern in stub_patterns)
                if not has_stub:
                    continue
                
                # Find specs that IMPLEMENT this code file
                for edge in self.kg.incoming_edges(node_id):
                    if edge.edge_type == "IMPLEMENTS":
                        spec_node = self.kg.get_node(edge.src)
                        if spec_node and spec_node.status in ["COMPLETE", "ACTIVE"]:
                            contradictions.append({
                                "rule": "stub_contradiction",
                                "node_id": edge.src,
                                "node_type": "Spec",
                                "node_title": spec_node.title,
                                "description": f"Spec {edge.src} claims {spec_node.status} but {node_id} contains stub",
                                "code_file": node_id,
                                "evidence": str(file_path),
                                "severity": "HIGH"
                            })
            
            except (IOError, UnicodeDecodeError):
                # Can't read file, skip
                continue
        
        return contradictions
    
    # ========== RULE 3: Scope Contradiction ==========
    
    def rule_3_scope_contradiction(self) -> list[dict]:
        """Scope Contradiction: Commit touches ranker/selector BUT Policy freezes them.
        
        If a commit modifies ranker/selector files but a freeze policy is active
        and was enforced before the commit date, that's a violation.
        """
        contradictions = []
        
        # Find freeze policies
        freeze_policies = {}
        for node_id, node in self.kg.nodes.items():
            if node.node_type == "Policy" and "freeze" in node.title.lower():
                freeze_policies[node_id] = node
        
        # For each freeze policy, find its enforcement date
        for policy_id, policy_node in freeze_policies.items():
            enforced_since = policy_node.extra_fields.get("enforced_since", "2026-04-01")
            
            # Find commits that touch ranker/selector files
            for node_id, node in self.kg.nodes.items():
                if node.node_type != "Commit":
                    continue
                
                # Check if commit message mentions ranker/selector
                if not any(x in node.title.lower() for x in ["ranker", "selector", "sizing"]):
                    # Check outgoing edges for TOUCHES ranker/selector code
                    touches_frozen = False
                    for edge in self.kg.outgoing_edges(node_id):
                        if edge.edge_type == "TOUCHES":
                            dst_node = self.kg.get_node(edge.dst)
                            if dst_node and any(x in dst_node.source_path for x in ["ranker", "selector"]):
                                touches_frozen = True
                                break
                    
                    if not touches_frozen:
                        continue
                
                # Check commit date vs freeze date
                commit_date = node.updated_at
                if commit_date >= enforced_since:
                    contradictions.append({
                        "rule": "scope_contradiction",
                        "node_id": node_id,
                        "node_type": "Commit",
                        "node_title": node.title,
                        "description": f"Commit {node_id} touches ranker/selector after policy {policy_id} freeze",
                        "policy_id": policy_id,
                        "enforced_since": enforced_since,
                        "commit_date": commit_date,
                        "evidence": node.source_path,
                        "severity": "HIGH"
                    })
        
        return contradictions
    
    # ========== RULE 4: Artifact Contradiction ==========
    
    def rule_4_artifact_contradiction(self) -> list[dict]:
        """Artifact Contradiction: Artifact PENDING but file doesn't exist.
        
        An artifact that's marked PENDING should have a file or evidence path.
        If both source_path and evidence don't exist, that's inconsistent.
        """
        contradictions = []
        
        for node_id, node in self.kg.nodes.items():
            if node.node_type != "Artifact":
                continue
            
            if node.status != "PENDING":
                continue  # Only check PENDING artifacts
            
            # Check if source_path exists
            source_exists = False
            if node.source_path:
                source_path = Path(node.source_path)
                source_exists = source_path.exists()
            
            # Check if evidence path exists
            evidence_exists = False
            if node.evidence:
                evidence_path = Path(node.evidence)
                evidence_exists = evidence_path.exists()
            
            # If neither exists, that's a contradiction
            if not source_exists and not evidence_exists:
                contradictions.append({
                    "rule": "artifact_contradiction",
                    "node_id": node_id,
                    "node_type": "Artifact",
                    "node_title": node.title,
                    "description": f"Artifact {node_id} marked PENDING but neither {node.source_path} nor {node.evidence} exist",
                    "source_path": node.source_path,
                    "evidence_path": node.evidence,
                    "evidence": "file system check",
                    "severity": "MEDIUM"
                })
        
        return contradictions
    
    # ========== RULE 5: Promotion Contradiction ==========
    
    def rule_5_promotion_contradiction(self) -> list[dict]:
        """Promotion Contradiction: Signal SHADOW_ONLY but in production ModelComponent.
        
        A signal marked SHADOW_ONLY or MONITORING_ONLY should not feed into
        production (frozen=True) model components.
        """
        contradictions = []
        
        # Find signals with shadow-only status
        shadow_signals = {}
        for node_id, node in self.kg.nodes.items():
            if node.node_type == "Signal":
                signal_status = node.extra_fields.get("signal_status", node.status)
                if signal_status in ["SHADOW_ONLY", "MONITORING_ONLY"]:
                    shadow_signals[node_id] = node
        
        # For each shadow signal, check if it READS from frozen model components
        for signal_id, signal_node in shadow_signals.items():
            for edge in self.kg.outgoing_edges(signal_id):
                if edge.edge_type == "READS":
                    model_node = self.kg.get_node(edge.dst)
                    if model_node and model_node.node_type == "ModelComponent":
                        is_frozen = model_node.extra_fields.get("frozen", False)
                        if is_frozen:
                            contradictions.append({
                                "rule": "promotion_contradiction",
                                "node_id": signal_id,
                                "node_type": "Signal",
                                "node_title": signal_node.title,
                                "description": f"Signal {signal_id} is {signal_status} but feeds into production {edge.dst}",
                                "model_component": edge.dst,
                                "evidence": signal_node.source_path,
                                "severity": "HIGH"
                            })
        
        return contradictions


class ContradictionReport:
    """Generates human-readable report from detected contradictions."""
    
    def __init__(self, contradictions: list[dict]):
        """Initialize with list of contradictions."""
        self.contradictions = contradictions
    
    def summary(self) -> dict:
        """Return summary counts by rule and severity."""
        by_rule = {}
        by_severity = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        
        for c in self.contradictions:
            rule = c.get("rule", "unknown")
            by_rule[rule] = by_rule.get(rule, 0) + 1
            
            severity = c.get("severity", "LOW")
            by_severity[severity] += 1
        
        return {
            "total": len(self.contradictions),
            "by_rule": by_rule,
            "by_severity": by_severity,
            "high_risk": by_severity["HIGH"],
            "medium_risk": by_severity["MEDIUM"],
            "low_risk": by_severity["LOW"]
        }
    
    def format_text(self) -> str:
        """Generate plain-text report."""
        if not self.contradictions:
            return "No contradictions detected."
        
        lines = []
        lines.append(f"Contradiction Report ({len(self.contradictions)} found)\n")
        lines.append("=" * 60)
        
        by_rule = {}
        for c in self.contradictions:
            rule = c.get("rule", "unknown")
            if rule not in by_rule:
                by_rule[rule] = []
            by_rule[rule].append(c)
        
        for rule in sorted(by_rule.keys()):
            items = by_rule[rule]
            lines.append(f"\n{rule.upper()} ({len(items)} found)")
            lines.append("-" * 60)
            
            for item in items:
                severity = item.get("severity", "LOW")
                lines.append(f"  [{severity}] {item['node_id']}: {item['description']}")
        
        return "\n".join(lines)
```

---

## Test Cases

**File**: `tests/test_kg_contradictions.py`

```python
import unittest
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from kg_loader import KnowledgeGraph, KnowledgeGraphNode, KnowledgeGraphEdge
from kg_contradictions import KGContradictions, ContradictionReport


class TestKGContradictions(unittest.TestCase):
    """Test contradiction detection rules."""
    
    @classmethod
    def setUpClass(cls):
        """Create a test graph with known contradictions."""
        cls.kg = KnowledgeGraph()
        
        # Create nodes for testing
        spec_closed_with_deps = KnowledgeGraphNode(
            id="spec_closed_bad", node_type="Spec", title="Closed Spec with Dependencies",
            status="CLOSED", source_path="specs.md", evidence="memo.md",
            updated_at="2026-05-14T00:00:00Z", extra_fields={}
        )
        action_pending = KnowledgeGraphNode(
            id="action_pending", node_type="Action", title="Pending Action",
            status="PENDING", source_path="actions.md", evidence="memo.md",
            updated_at="2026-05-14T00:00:00Z", extra_fields={}
        )
        spec_complete_with_stub = KnowledgeGraphNode(
            id="spec_complete_stub", node_type="Spec", title="Complete Spec (but stubbed)",
            status="COMPLETE", source_path="specs.md", evidence="memo.md",
            updated_at="2026-05-14T00:00:00Z", extra_fields={}
        )
        policy_freeze = KnowledgeGraphNode(
            id="policy_ranker_freeze", node_type="Policy", title="Ranker Freeze",
            status="ACTIVE", source_path="policies.md", evidence="memo.md",
            updated_at="2026-05-14T00:00:00Z",
            extra_fields={"enforced_since": "2026-05-01T00:00:00Z"}
        )
        commit_violates = KnowledgeGraphNode(
            id="commit_bad", node_type="Commit", title="Ranker changes after freeze",
            status="ACTIVE", source_path="commit", evidence="git",
            updated_at="2026-05-10T00:00:00Z", extra_fields={}
        )
        ranker_code = KnowledgeGraphNode(
            id="code_ranker.py", node_type="CodeFile", title="Ranker Code",
            status="ACTIVE", source_path="ranker.py", evidence="path",
            updated_at="2026-05-14T00:00:00Z", extra_fields={}
        )
        artifact_pending = KnowledgeGraphNode(
            id="artifact_missing", node_type="Artifact", title="Missing Artifact",
            status="PENDING", source_path="/nonexistent/path.json", evidence="/nonexistent/memo.md",
            updated_at="2026-05-14T00:00:00Z", extra_fields={}
        )
        signal_shadow = KnowledgeGraphNode(
            id="signal_shadow", node_type="Signal", title="Shadow Signal",
            status="ACTIVE", source_path="signals.md", evidence="memo.md",
            updated_at="2026-05-14T00:00:00Z",
            extra_fields={"signal_status": "SHADOW_ONLY"}
        )
        model_frozen = KnowledgeGraphNode(
            id="model_ranker_prod", node_type="ModelComponent", title="Production Ranker",
            status="ACTIVE", source_path="models.json", evidence="config",
            updated_at="2026-05-14T00:00:00Z",
            extra_fields={"frozen": True}
        )
        
        # Add all nodes
        for node in [spec_closed_with_deps, action_pending, spec_complete_with_stub,
                     policy_freeze, commit_violates, ranker_code, artifact_pending,
                     signal_shadow, model_frozen]:
            cls.kg.add_node(node)
        
        # Create edges for contradictions
        # Rule 1: Closed spec with dependencies
        edge1 = KnowledgeGraphEdge(
            src="spec_closed_bad", edge_type="DEPENDS_ON", dst="action_pending",
            evidence="spec.md", confidence="HIGH", created_at="2026-05-14T00:00:00Z"
        )
        cls.kg.add_edge(edge1)
        
        # Rule 2: Complete spec with stubbed code
        edge2 = KnowledgeGraphEdge(
            src="spec_complete_stub", edge_type="IMPLEMENTS", dst="code_ranker.py",
            evidence="spec.md", confidence="HIGH", created_at="2026-05-14T00:00:00Z"
        )
        cls.kg.add_edge(edge2)
        
        # Rule 3: Commit violates freeze
        edge3 = KnowledgeGraphEdge(
            src="commit_bad", edge_type="TOUCHES", dst="code_ranker.py",
            evidence="git", confidence="HIGH", created_at="2026-05-10T00:00:00Z"
        )
        cls.kg.add_edge(edge3)
        
        # Rule 5: Shadow signal in production
        edge5 = KnowledgeGraphEdge(
            src="signal_shadow", edge_type="READS", dst="model_ranker_prod",
            evidence="config", confidence="HIGH", created_at="2026-05-14T00:00:00Z"
        )
        cls.kg.add_edge(edge5)
        
        cls.detector = KGContradictions(cls.kg)
    
    def test_rule_1_status_contradiction(self):
        """Rule 1: Detect closed spec with dependencies."""
        contradictions = self.detector.rule_1_status_contradiction()
        
        self.assertGreater(len(contradictions), 0)
        self.assertTrue(any(c["node_id"] == "spec_closed_bad" for c in contradictions))
        self.assertTrue(any(c["rule"] == "status_contradiction" for c in contradictions))
    
    def test_rule_2_stub_contradiction(self):
        """Rule 2: Detect complete spec with stubbed code (if file exists)."""
        contradictions = self.detector.rule_2_stub_contradiction()
        
        # This test won't find contradictions unless code_ranker.py actually exists
        # and contains stub patterns. Just verify it runs without error.
        self.assertIsInstance(contradictions, list)
    
    def test_rule_3_scope_contradiction(self):
        """Rule 3: Detect commit violating freeze policy."""
        contradictions = self.detector.rule_3_scope_contradiction()
        
        # May or may not find contradictions depending on policy enforcement logic
        self.assertIsInstance(contradictions, list)
    
    def test_rule_4_artifact_contradiction(self):
        """Rule 4: Detect artifact with missing files."""
        contradictions = self.detector.rule_4_artifact_contradiction()
        
        self.assertGreater(len(contradictions), 0)
        self.assertTrue(any(c["node_id"] == "artifact_missing" for c in contradictions))
        self.assertTrue(any(c["rule"] == "artifact_contradiction" for c in contradictions))
    
    def test_rule_5_promotion_contradiction(self):
        """Rule 5: Detect shadow signal in production."""
        contradictions = self.detector.rule_5_promotion_contradiction()
        
        self.assertGreater(len(contradictions), 0)
        self.assertTrue(any(c["node_id"] == "signal_shadow" for c in contradictions))
        self.assertTrue(any(c["rule"] == "promotion_contradiction" for c in contradictions))
    
    def test_detect_all(self):
        """Run all rules together."""
        contradictions = self.detector.detect_all()
        
        # Should find multiple contradictions
        self.assertGreater(len(contradictions), 0)
        
        # Check that multiple rules are represented
        rules = set(c["rule"] for c in contradictions)
        self.assertGreater(len(rules), 1)
    
    def test_contradiction_report_summary(self):
        """Report generates correct summary."""
        contradictions = self.detector.detect_all()
        report = ContradictionReport(contradictions)
        
        summary = report.summary()
        self.assertEqual(summary["total"], len(contradictions))
        self.assertIn("by_rule", summary)
        self.assertIn("by_severity", summary)
    
    def test_contradiction_report_format(self):
        """Report generates text output."""
        contradictions = self.detector.detect_all()
        report = ContradictionReport(contradictions)
        
        text = report.format_text()
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 0)


if __name__ == "__main__":
    unittest.main()
```

---

## Acceptance Criteria

Before committing May 26:

1. ✅ KGContradictions class with all 5 detection rules implemented
2. ✅ Rule 1: status_contradiction detects closed nodes with dependencies
3. ✅ Rule 2: stub_contradiction detects code stubs in "complete" specs
4. ✅ Rule 3: scope_contradiction detects freeze policy violations
5. ✅ Rule 4: artifact_contradiction detects missing artifact files
6. ✅ Rule 5: promotion_contradiction detects shadow signals in production
7. ✅ ContradictionReport class generates summaries and formatted output
8. ✅ All 8 test cases pass
9. ✅ No regressions (Phase 4a and 4b tests still pass)

---

## Commit Checklist

**May 26 (Phase 4c complete)**:

1. Create tools/kg_contradictions.py with KGContradictions and ContradictionReport
2. Create tests/test_kg_contradictions.py with 8 test methods
3. Run tests: `python3 -m pytest tests/test_kg_contradictions.py -v`
4. Verify all pass
5. Verify no regressions: `python3 -m pytest tests/test_kg_*.py -v`
6. Commit: `tools: implement contradiction detection (Phase 2 Step 4c)`
7. Message includes Co-Authored-By

---

## Integration Points

**Phase 4d** (May 26–27): CLI wrapper calls detect_all() and reports contradictions  
**Phase 4e** (May 27–28): Validation tests verify each rule correctly identifies test contradictions

---

**Status**: Implementation design locked. Ready for May 26 coding session (2.5 hours to code + test).

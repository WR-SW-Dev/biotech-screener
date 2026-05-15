# Phase 2 Step 4 — Knowledge Graph Implementation Sprint (2026-05-15)

**Status**: Complete design lock (design-only, not implementation).

**Objective**: Build a deterministic KG query layer that answers 5 governance questions without LLM reasoning.

---

## Sprint Overview

**Timeline**: After cohort clearance is explicitly verified (~May 23–26), phases 4a–4e execute (6 days, one phase per day)  
**Prerequisites**: 
- May 19 verification (Phase 2 Step 3) must PASS
- May 23–26 cohort clearance must be CONFIRMED (not estimated)

**Blocker**: Cannot start implementation until both gates above are verified  

| Date | Phase | Task | Est. Time | Output |
|------|-------|------|-----------|--------|
| May 23–24 (Fri–Sat) | 4a | KG loader | 2 hrs | tools/kg_loader.py (150 lines) |
| May 24–25 (Sat–Sun) | 4b | Query implementations | 3 hrs | tools/kg_queries.py (200 lines) |
| May 25–26 (Sun–Mon) | 4c | Contradiction detection | 2.5 hrs | tools/kg_contradictions.py (150 lines) |
| May 26–27 (Mon–Tue) | 4d | CLI tool + API | 2.5 hrs | tools/kg_query_cli.py (200 lines) |
| May 27–28 (Tue–Wed) | 4e | Validation tests | 3 hrs | tests/test_kg_validation.py (400 lines + seed graph) |

**Total**: ~13 hours of coding + testing  
**Commits**: 5 commits (one per phase)  
**Tests**: 60+ test cases across all phases

---

## Implementation Specs

### Phase 4a — Knowledge Graph Loader

**File**: `artifacts/audit/phase_2_step_4a_kg_loader_implementation_2026_05_15.md`

**What**: Build data structures and loader for KG  
**Code**: 
- `KnowledgeGraphNode` class (dataclass with validation)
- `KnowledgeGraphEdge` class (directed edges with types)
- `KnowledgeGraph` class (in-memory container, traversal, schema validation)

**Key Methods**:
- `load_seed(path)` — Parse JSONL seed graph file
- `add_node(node)` — Add node with duplicate check
- `add_edge(edge)` — Add edge with src/dst validation
- `outgoing_edges(node_id)` — Efficient traversal
- `validate_schema()` — Check graph integrity

**Tests**: 17 test cases  
**Duration**: 2 hours

---

### Phase 4b — Query Implementations

**File**: `artifacts/audit/phase_2_step_4b_query_implementations_2026_05_15.md`

**What**: Implement 5 deterministic query functions  
**Code**: 
- `KGQueries` class with methods:
  1. `what_blocks_production_ranker_change()` — All ranker blockers + chains
  2. `spec_status(spec_id)` — Spec dependencies, blockers, contradictions
  3. `contradictions()` — All CONTRADICTS edges
  4. `next_actions()` — PENDING actions sorted by deadline
  5. `what_touches_file(path)` — Commits/specs touching a file

**Key Features**:
- Pure graph traversal (except Query 5 which adds one git log call)
- JSON-serializable output
- Helper methods for risk assessment, dependency chains, etc.

**Tests**: 11 test cases  
**Duration**: 3 hours

---

### Phase 4c — Contradiction Detection

**File**: `artifacts/audit/phase_2_step_4c_contradiction_detection_2026_05_15.md`

**What**: Implement 5 contradiction detection rules  
**Code**: 
- `KGContradictions` class with methods:
  1. `rule_1_status_contradiction()` — Closed node with DEPENDS_ON edges
  2. `rule_2_stub_contradiction()` — Complete spec with stubbed code
  3. `rule_3_scope_contradiction()` — Commit violates freeze policy
  4. `rule_4_artifact_contradiction()` — PENDING artifact with no files
  5. `rule_5_promotion_contradiction()` — Shadow signal in production

- `ContradictionReport` class for summaries + text output

**Key Features**:
- Deterministic rule application
- High/Medium/Low severity classification
- Evidence paths and human-readable descriptions

**Tests**: 8 test cases  
**Duration**: 2.5 hours

---

### Phase 4d — CLI Tool & API

**File**: `artifacts/audit/phase_2_step_4d_cli_tool_api_2026_05_15.md`

**What**: Command-line interface for all queries  
**Code**: 
- `kg_query_cli.py` with 6 subcommands:
  1. `what-blocks-ranker` — Query 1
  2. `spec-status SPEC_ID` — Query 2
  3. `contradictions` — Query 3
  4. `next-actions` — Query 4
  5. `what-touches FILE_PATH` — Query 5
  6. `all` — Run all queries and print summary

**Key Features**:
- JSON output (`--json` flag)
- Human-readable text summaries
- Proper error handling
- Exit codes: 0=success, 1=error or contradictions found

**Usage Examples**:
```bash
python3 tools/kg_query_cli.py what-blocks-ranker
python3 tools/kg_query_cli.py spec-status spec_100 --json
python3 tools/kg_query_cli.py contradictions
python3 tools/kg_query_cli.py all
```

**Tests**: 8 test cases  
**Duration**: 2.5 hours

---

### Phase 4e — Validation Tests

**File**: `artifacts/audit/phase_2_step_4e_validation_tests_2026_05_15.md`

**What**: End-to-end validation with real governance data  
**Code**: 
- `test_kg_validation.py` with 35+ test cases covering:
  - Loader validation (nodes, edges, types, schema)
  - Query validation (all 5 queries + structure)
  - Contradiction detection (all rules)
  - CLI validation (all subcommands)
  - Integration tests (cross-query consistency)
  - Governance constraint validation
  - Edge cases and error handling

**Prerequisites for Phase 4e**:
- `artifacts/audit/kg_seed.jsonl` must be created
- Seed graph must contain:
  - Specs: 096, 100, 072, others
  - Policies: alpha_freeze, checklist_v2
  - Actions: forward_return_wiring, etc.
  - Signals, model components, edges

**Tests**: 35+ test cases  
**Duration**: 3 hours (includes seed graph authoring)

---

## Detailed Implementation Breakdown

### Phase 4a: 2 hours
- Code: `KnowledgeGraphNode`, `KnowledgeGraphEdge`, `KnowledgeGraph` classes (150 lines)
- Tests: Node/edge creation, validation, schema checks (17 tests)
- Commit: `tools: implement knowledge graph loader (Phase 2 Step 4a)`

### Phase 4b: 3 hours
- Code: `KGQueries` class with 5 query methods (200 lines)
- Tests: Each query validated independently + sample data (11 tests)
- Commit: `tools: implement KG query layer (Phase 2 Step 4b)`

### Phase 4c: 2.5 hours
- Code: `KGContradictions` with 5 rules, `ContradictionReport` (150 lines)
- Tests: Each rule tested with known contradictions (8 tests)
- Commit: `tools: implement contradiction detection (Phase 2 Step 4c)`

### Phase 4d: 2.5 hours
- Code: `kg_query_cli.py` with 6 subcommands, argument parsing, output formatting (200 lines)
- Tests: All commands execute, JSON/text output valid (8 tests)
- Commit: `tools: implement KG query CLI tool (Phase 2 Step 4d)`

### Phase 4e: 3 hours
- Code: `test_kg_validation.py` with comprehensive test suite (400 lines)
- Seed authoring: `artifacts/audit/kg_seed.jsonl` with ~80 nodes, ~120 edges
- Tests: 35+ test cases covering all functionality
- Commit: `tools: implement KG validation tests (Phase 2 Step 4e)`

---

## Expected Deliverables

### Code Files
- `tools/kg_loader.py` — KG data structures
- `tools/kg_queries.py` — 5 query implementations
- `tools/kg_contradictions.py` — Contradiction detection
- `tools/kg_query_cli.py` — Command-line interface
- `tests/test_kg_loader.py` — Loader tests (17 tests)
- `tests/test_kg_queries.py` — Query tests (11 tests)
- `tests/test_kg_contradictions.py` — Contradiction tests (8 tests)
- `tests/test_kg_query_cli.py` — CLI tests (8 tests)
- `tests/test_kg_validation.py` — Validation tests (35+ tests)

### Data Files
- `artifacts/audit/kg_seed.jsonl` — Governance seed graph

### Documentation
- This sprint summary
- Individual phase specs (4a–4e)

---

## Success Criteria

### Phase 4a Completion
- ✅ KG loader can parse JSONL seed graph
- ✅ All 17 tests pass
- ✅ No schema validation errors
- ✅ Efficient traversal methods (outgoing/incoming edges)

### Phase 4b Completion
- ✅ All 5 queries return correct structure
- ✅ All 11 tests pass
- ✅ Query results are JSON-serializable
- ✅ Sample test data validates expected output

### Phase 4c Completion
- ✅ All 5 contradiction rules implemented
- ✅ All 8 tests pass
- ✅ ContradictionReport generates summaries
- ✅ Text formatting works

### Phase 4d Completion
- ✅ All 6 subcommands work
- ✅ All 8 tests pass
- ✅ JSON and text output both valid
- ✅ CLI handles missing seed graph gracefully

### Phase 4e Completion
- ✅ All 35+ tests pass
- ✅ Seed graph has 10+ nodes, 10+ edges
- ✅ All queries return expected structure
- ✅ Contradiction detection works
- ✅ No regressions (all prior tests still pass)
- ✅ Total: 60+ tests passing

---

## Risk Mitigation

**Risk**: Seed graph authoring takes longer than expected  
**Mitigation**: Create minimal seed graph first (10 nodes, 10 edges), expand after Phase 4d

**Risk**: Query performance on large graphs  
**Mitigation**: Use indexed edge lookups (_edges_by_src, _edges_by_dst), limit recursion depth

**Risk**: Contradiction rules produce false positives  
**Mitigation**: Each rule has clear, testable condition; validate with real governance data

**Risk**: CLI output doesn't match expected format  
**Mitigation**: Compare with spec examples; use structured output (JSON) as source of truth

---

## Integration with Phase 2 Step 5

Once Phase 4e completes:

- **Phase 2 Step 5** (late phase): Wire KG queries into agent governance enforcement
  - Use Query 1 to check ranker blockers before dispatching agents
  - Use Query 3 to surface contradictions as warnings
  - Use Query 4 to alert on pending actions
  - Extend Phase 3b preflight integration with KG-based blocking

- **Non-Goals for Phase 4**: No production integration, no enforcement loops, no LLM reasoning

---

## How to Use This Sprint Plan

1. **Read specs in order**: 4a → 4b → 4c → 4d → 4e
2. **Implement daily**: One phase per day, May 23–28
3. **Test immediately**: Run tests after each commit
4. **Verify no regressions**: Full test suite each day
5. **Seed graph**: Author incrementally as you build KG
6. **Document**: Update memory/status files as you progress

---

## Next Steps (Post-Phase 4)

- **May 28 afternoon**: All 60+ tests pass, KG ready for use
- **May 29+**: Consider Phase 2 Step 5 (KG gating enforcement) design
- **June onwards**: Operational use of KG queries in governance workflows

---

**Sprint Ready**: All implementation details locked. Five specs provide complete, ready-to-code designs for the May 23–28 implementation window.

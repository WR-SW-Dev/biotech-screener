# Spec 110: Pipeline Provenance Graph — Design Phase

**Status**: PLANNING (first pass, design/spec scaffold)  
**Branch**: `spec-110-pipeline-provenance-graph-2026-05-21`  
**Governance**: Approved by governance_clearance_spec089_spec110_2026_05_21  
**Timeline**: May 21–28, 2026 (design phase only)  
**Phase Target**: Design/test scaffold + one full-cycle proof-of-concept (single snapshot lineage)

---

## Overview

Pipeline provenance graph is a **deterministic, in-memory, read-only governance tool** that maps data lineage through the biotech screener transformation pipeline. It captures:

- **Source → Artifact path**: raw inputs → processed outputs
- **Dependency relationships**: which modules consume/produce which artifacts
- **Validation checkpoints**: gates, rules, quality assertions
- **Quarantine events**: suppressed artifacts, blocked rules, failed gates
- **Query capabilities**: answer "what is the lineage of this ranking?", "what broke this feature?", "which snapshots depend on this external source?"

**Hard constraints** (per Spec 089 pattern):
- ✗ No LLM-derived graph facts
- ✗ No graph centrality / betweenness as signals
- ✗ No scoring/ranking/weighting logic in graph
- ✗ No production-ranker coupling in phase 1
- ✓ Read-only, deterministic
- ✓ CLI queryable
- ✓ Gitignored outputs (like Spec 089)
- ✓ Integration touch-points with governance-spec-enforcement, hermeslink

---

## Node Schema

### Node Types (13 total)

#### Tier 1: External Sources
| Type | Purpose | Cardinality | Lifecycle | Metadata |
|------|---------|-------------|-----------|----------|
| RawSource | External data feed (13F, clinical trial, market data, etc.) | 1..n per ingest | Static until refresh | source_name, vendor, ingest_cadence, last_update |
| VendorSnapshot | Timestamped snapshot of external vendor data | 1..n per RawSource | Ephemeral (90d retention) | source_id, ts, row_count, hash, stale_days |

#### Tier 2: File-Based Artifacts
| Type | Purpose | Cardinality | Lifecycle | Metadata |
|------|---------|-------------|-----------|----------|
| CacheFile | Intermediate serialized state (cached trial records, market snapshots) | 1..n | Transient or persistent | artifact_type, ts_cached, size_bytes, cache_key |
| FeatureArtifact | Computed feature vectors (clinical_score, catalyst_score, inst_delta) | 1..n | Per-snapshot | feature_name, module, ts_computed, dimensions |
| RulesetArtifact | Active governance ruleset version | 1 per snapshot | Per-snapshot | ruleset_id, rule_count, crc, loaded_ts |
| DataSnapshot | Full point-in-time data state (date/universe/ruleset) | 1..n | Immutable after lock | snapshot_date, universe_size, locked_ts, manifest_uri |

#### Tier 3: Processing Modules
| Type | Purpose | Cardinality | Lifecycle | Metadata |
|------|---------|-------------|-----------|----------|
| Module | Named pipeline stage (selector, ranker, clinical_validator, catalyst_analyzer) | 1..n | Static | module_name, phase_tag, responsibility, version |
| Gate | Quantitative validation rule (Jaccard ≥0.70, top-30 KS < 0.35, filed % ≥75) | 1..n | Per-spec | gate_name, spec_id, threshold, kind (HARD/SOFT) |
| Contradiction | Flagged logical inconsistency (see Spec 089 pattern) | 1..n | Cleared or persistent | contradiction_id, severity (C0–C5), node_refs, context |

#### Tier 4: Outputs & Evidence
| Type | Purpose | Cardinality | Lifecycle | Metadata |
|------|---------|-------------|-----------|----------|
| RankedList | Ranked securities output (rankings.csv, rankings_shadow.csv) | 1..n per snapshot | Immutable | output_type, rank_count, top_n_list, crc |
| ValidationEvidence | Gate/rule execution result (13F Jaccard, KS statistic, field coverage %) | 1..n | Per-snapshot | gate_id, verdict (PASS/WARN/FAIL), value, threshold, ts |

---

## Edge Schema

### Edge Types (8 total)

| Type | Direction | Semantics | Validation | Example |
|------|-----------|-----------|------------|---------|
| PRODUCES | A → B | Module/snapshot produces artifact | B depends on A | Module(selector) → RankedList(top-60) |
| CONSUMES | A → B | Module/gate reads artifact | B must exist before A | Module(ranker) ← CacheFile(market_snapshot) |
| DERIVES | A → B | FeatureArtifact computed from RawSource/CacheFile | Provenance chain | FeatureArtifact(inst_delta) ← RawSource(13F) |
| VALIDATES | Gate → (Module\|Snapshot) | Gate checks precondition/postcondition | Gate fires before PRODUCES edge | Gate(Jaccard ≥0.70) → Module(selector) |
| QUARANTINES | Contradiction → (Node\|Edge) | Contradiction blocks or flags node/edge | Mutual exclusion | Contradiction(C2_ghost_ticker) → FeatureArtifact(inst_delta) |
| BACKFILLS | HistoricalSnapshot → CurrentSnapshot | Historical data ingested into current cycle | Lineage for cohort changes | VendorSnapshot(13F 2026-05-01) → DataSnapshot(2026-05-20) |
| GATED_BY | RankedList → Gate | Output requires gate clearance | Dependency for emission | RankedList(rankings_2026-05-20) ← Gate(top-30-KS) |
| IMPLEMENTS | Module → RulesetArtifact | Module executes rules from ruleset | Spec enforcement | Module(financial_penalizer) ← RulesetArtifact(ruleset_8887576e) |

---

## Source/Artifact Inventory

### Raw Sources → Final Artifact Path

RawSource: 13F → VendorSnapshot → CacheFile → FeatureArtifact → Module(selector) → RankedList → RulesetArtifact → Module(ranker) → RankedList → DataSnapshot

### Key Inventory Points

1. **13F Cohort Refresh** - RawSource (Morningstar), quarterly cadence, current state 44/48 managers (Jaccard 0.99)
2. **Clinical Trial Database** - RawSource (ClinicalTrials.gov), daily cadence via ctgov_poller
3. **Market Data** - RawSources (Yahoo Finance, Morningstar), daily on market open with 429-retry backoff
4. **Catalyst/News Data** - RawSources (news digest, herald), daily push from producers
5. **Governance Ruleset** - RawSource (ruleset.yaml), loaded as RulesetArtifact per snapshot
6. **Rankings Output** - RankedList produced and gated by validation evidence

---

## Query Patterns

Five deterministic query patterns for provenance graph traversal:

1. **Lineage** - Snapshot → all upstream sources (RawSource → VendorSnapshot → FeatureArtifact → Module → RankedList)
2. **Snapshot-Inputs** - Snapshot → external input sources (RawSource, CacheFile, VendorSnapshot) with staleness status
3. **Breakage-Impact** - Artifact → all downstream dependents with severity classification
4. **Stale-Features** - Snapshot + threshold-hours → features older than threshold, grouped by status
5. **Validate-Snapshot** - Snapshot → assertion results for all edges/nodes (CONSUMES completeness, QUARANTINE status, GATED_BY gates)

---

## Acceptance Tests (15 total)

**Lineage Tests (3)**: T1 single-feature, T2 full-snapshot, T3 shadow rankings
**Snapshot-Inputs Tests (2)**: T4 current-sources, T5 stale-sources
**Breakage-Impact Tests (3)**: T6 feature-to-module, T7 gate-to-output, T8 cache-miss
**Stale-Features Tests (2)**: T9 stale-detection, T10 refresh-ready
**Validate-Snapshot Tests (3)**: T11 edge-completeness, T12 gate-consistency, T13 quarantine-accuracy
**Integration Tests (2)**: T14 cross-snapshot consistency, T15 error handling

---

## Non-Goals

What this graph does NOT do:
- Not an ML system (no embeddings, centrality as alpha)
- Not a scoring input (hard firewall from ranker/selector)
- Not a feature store (separate from Hermes skill caching)
- Not a data warehouse (no materialization of values)
- Not LLM-augmented (manual definitions only)
- Not real-time streaming (snapshot-based only)
- Not cross-snapshot aggregation (independent lineages)
- Not a replacement for specs/tests (governance tool only)

---

## Test Plan

### Phase 1: Schema Validation
- Node schema unit tests (13 types, metadata fields, cardinality)
- Edge schema unit tests (8 types, direction semantics, consistency)
- Inventory tests (RawSource → RankedList completeness)

### Phase 2: Integration Tests
- Use snapshot 2026-05-20 (latest available)
- Query pattern tests (T1–T15, 15 acceptance tests)
- Error case handling

### Phase 3: Proof-of-Concept
- Generate lineage for 2026-05-20
- Execute all 5 query patterns
- Verify JSON output, assertion results, no broken edges

### Phase 4: Success Criteria
- Schema stability (13 node + 8 edge types frozen)
- Test coverage (20+ tests, 100% pass)
- Stakeholder review (governance memo signed)
- Operational readiness (CLI designed, artifacts directory, gitignore rules)
- Phase 1 stop criteria (design locked, PoC complete, no production wiring)

---

## Architecture & Implementation Boundaries

**In Scope**:
- Node/edge schema definition
- Source/artifact inventory mapping
- Query pattern signatures
- In-memory graph from production snapshot
- Deterministic edge building
- JSON/CLI output

**Out of Scope**:
- Implementation of specs 4a–4e (unless diff small + tests clear)
- Production-ranker integration
- LLM-derived facts
- Graph database (Neo4j, etc.)
- Time-series aggregation
- Feature-value materialization
- Real-time streaming
- Cron automation

---

## Related Documentation

- Spec 089: Ranker Governance Knowledge Graph (schema pattern)
- governance_clearance_spec089_spec110_2026_05_21: Governance approval
- Spec 111/112: Feature/agent-ops provenance (deferred)
- hermeslink-state-capture.md: Operational state capture

---

**Status**: DESIGN COMPLETE (pending PoC + test verification)  
**Branch**: spec-110-pipeline-provenance-graph-2026-05-21  
**Next**: Implementation (specs 4a–4e) awaits Phase 1 PoC + h20d 2026-05-26 governance decision

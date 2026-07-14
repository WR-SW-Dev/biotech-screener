# Organizational Judgment Codification Principles

**Status:** Governing workflow doctrine  
**Scope:** Research, model governance, agent/skill design, vendor selection, institutional memory, and investment-process documentation  
**Production impact:** None. This document changes how work is documented and evaluated; it does not alter ranking, selection, sizing, scoring, or portfolio decisions.

## Governing idea

Competitive advantage comes from accumulated judgment. Architecture earns its keep only by preserving that judgment in forms that remain understandable, extractable, and reconstructable without dependence on any particular model, vendor, implementation, or individual.

This doctrine is bounded. It applies most cleanly to internal organizational capital. It does not reduce relational capital to files, and it does not assume all tacit judgment should or can be codified.

## Capital dimensions

Treat codified, tacit, and relational capital as coordinates, not mutually exclusive buckets.

### Codified capital

Knowledge that survives in durable artifacts:

- datasets and provenance
- eval suites and historical outcomes
- decision logs and governance records
- taxonomies, schemas, and business rules
- research evidence and reproducible calculations

### Tacit capital

Judgment that remains embodied in competent people:

- scientific intuition
- credibility assessment
- exception handling
- judgment under uncertainty
- knowing when a rule no longer fits its context

### Relational capital

Value that exists in relationships and cannot be reconstructed from internal backups:

- manager access and trust
- LP and operating relationships
- reputation
- proprietary conversations
- network position

Relational capital is protected primarily through stewardship and continuity, not portability engineering.

## Codification is compression

Codification is not a neutral copy of judgment. It transforms judgment into a different object with different failure modes.

Some knowledge compresses well:

- provenance requirements
- point-in-time rules
- formulas and schemas
- data lineage
- approval thresholds

Some knowledge compresses poorly:

- reading management credibility
- weighing conflicting scientific evidence
- knowing when an exception is justified
- interpreting relational context

Do not maximize codification. Codify only where the expected benefit of preservation exceeds the expected distortion from compression.

## Required treatment decision

Every material piece of knowledge should receive one of four treatments.

1. **Rule** — use when knowledge compresses with high fidelity.
2. **Heuristic** — use when guidance is useful but boundary conditions and human judgment remain material.
3. **Case library** — use when examples, counterexamples, and outcomes preserve more value than abstraction.
4. **Apprenticeship / named ownership** — use when exercised judgment is categorically superior to the codified form.

For heuristics and rules, explicitly state where literal application could fail.

## Required fields for important artifacts

Every material research, governance, skill, or workflow artifact should answer:

```text
DURABLE_ASSET:
What judgment, evidence, relationship, or capability is intended to compound?

CAPITAL_PROFILE:
Codified __ / Tacit __ / Relational __

COMPRESSION_RISK:
What nuance or context is lost by converting this into a rule, dataset, prompt, workflow, or automated process?

BOUNDARY_CONDITIONS:
When should this reasoning no longer be trusted or mechanically applied?

RECONSTRUCTABILITY:
What is required to reproduce the capability without the present vendor, model, implementation, or author?

RESIDUAL_HUMAN_JUDGMENT:
What must still be exercised by a competent person in context?

ALPHA_MECHANISM:
How should this improve the probability, speed, consistency, or auditability of better biotech capital-allocation decisions?

REOPEN_OR_INVALIDATION_CONDITIONS:
What future evidence would disprove the decision or justify reopening it?
```

Not every lightweight artifact needs a full block, but every material initiative must address the substance of these questions.

## Decision-record standard

Important decisions must record:

1. **Decision** — what was decided.
2. **Evidence** — what was known at the time.
3. **Reasoning** — why the evidence supported the decision.
4. **Boundary conditions** — where the reasoning would stop applying.
5. **Exceptions** — what contextual fact justified any override.
6. **Reopen conditions** — what new evidence would change the decision.

A documented output is not documented judgment unless the reasoning and its limits are preserved.

## Vendor and architecture test

Before adopting a material platform or workflow, ask:

> If this vendor, model, or implementation disappeared tomorrow, what could be reconstructed from artifacts the firm controls?

Classify each important component as:

- fully reconstructable
- exportable but lossy
- manually recoverable
- trapped
- relational and not meaningfully exportable

Model independence is a design constraint, not a competitive asset. Prefer open standards and portable stores over bespoke orchestration. Do not build wrappers merely to demonstrate optionality.

## Exception library

Correct overrides are high-value evidence. When a human overrides a model, rule, or workflow, capture:

- default rule or recommendation
- actual decision
- contextual signal that justified the override
- whether the rule was defective, incomplete, or correctly bypassed
- whether the case should change the rule, become a heuristic example, or remain exceptional

This library records where codification fails and is often more valuable than expanding the rulebook.

## Standing review discipline

For every strong principle, process, or model change, answer:

1. What does it explain?
2. What does it not explain?
3. What failure mode remains even if it is followed perfectly?

This is a mandatory defense against confident-but-subtly-wrong doctrine.

## Biotech-specific interpretation

The project’s durable value is not primarily its current orchestrator, wrappers, or frontier model. It is the accumulated judgment embedded in:

- point-in-time datasets and deterministic provenance
- catalyst and manager histories
- scientific cartography and evidence taxonomies
- IC and validation harnesses
- governance decisions, failure archaeology, and reopen conditions
- examples of justified model or process overrides

The purpose of the documentation and governance stack is therefore twofold:

1. improve biotech alpha by making better decisions more reproducible and auditable; and
2. reduce key-person and vendor risk without pretending that all expert or relational judgment can be converted into rules.

Where judgment remains irreducibly contextual, protect the person, preserve representative cases, create apprenticeship, and avoid false automation.

## Governing rule

> Codify what survives compression. Preserve cases where rules lose context. Protect and transmit the people and relationships where judgment remains irreducibly exercised. Keep every codified asset reconstructable outside the system that currently uses it.

## Prohibited interpretations

This doctrine does **not** authorize:

- additional orchestration infrastructure without a clear alpha mechanism
- fine-tuning or model training merely to claim ownership of adapted weights
- converting heuristics into mechanical scoring rules without validation
- treating exportability as proof that capability has been preserved
- treating relational capital as a database problem
- using documentation to bypass production governance, model freezes, or promotion gates

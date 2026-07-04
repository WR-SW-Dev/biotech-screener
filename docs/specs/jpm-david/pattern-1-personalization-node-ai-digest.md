# Spec: Role-Aware Personalization Node for the AI Digest Routine

**Status:** DRAFT — proposal for review (not authorized for production)
**Author:** Warrenpoobear (for Darren Schulz)
**Date:** July 4, 2026
**Governance class:** Routine config change (rendering/output only). No scorer/ranker/selector/model change. Shadow/manual-test first.
**Pattern source:** JPMorgan Private Bank "Ask David" (D.A.V.I.D.) — personalization post-processing node (LangChain Interrupt 2025; ZenML LLMOps case study).

---

## 1. Recommendation

Add a **role-aware personalization node** as a final rendering step to the AI Digest routine so a single research pass produces two audience-tuned outputs — a full institutional-depth version for Darren and a condensed huddle-summary version for the Austin/Sadie Friday huddle — instead of one uniform format.

This ports the single highest-value, lowest-risk UX idea from Ask David: *same underlying answer, output depth keyed to the recipient's role.*

## 2. Basis (verified facts)

- Ask David runs a **personalization node** after retrieval: due-diligence specialists get detailed answers, advisors get general summaries — one query, role-keyed depth. [ZenML LLMOps case study; ai.plainenglish.io architecture write-up]
- The node sits in post-processing, **after** the research/retrieval agents and **before** final summarization — it does not alter what is researched, only how it is rendered.
- Darren already maintains an implicit dual-audience split: institutional-depth self-consumption vs. the Austin/Sadie huddle framing (six-plus consistent sections + 3 discussion starters).
- This is a rendering transform, not a data/model change — it does not touch scoring, selection, or ranking logic, so it sits outside the production-lock and architecture-freeze boundaries.

## 3. Scope

**In scope**
- A post-research rendering step that emits two variants from one research payload.
- Config/prompt-level change to the AI Digest routine only.

**Out of scope (do NOT touch)**
- Research/retrieval logic, source selection, section taxonomy, discussion-starter generation logic.
- Any biotech screener, SEC alert, or Hermes production component.
- Any scorer/ranker/selector/model.

## 4. Design

### 4.1 Pipeline position
```
[research + section assembly]  ->  [personalization node]  ->  [delivery]
        (unchanged)                    (NEW, rendering)         (two emails/doc variants)
```
The personalization node consumes the fully assembled digest payload (all sections + discussion starters) and produces two renderings. It must be a pure transform: it may condense, reorder for audience, and adjust depth/tone, but it must NOT introduce facts, figures, or claims absent from the research payload.

### 4.2 Two output profiles

**Profile A — Principal (Darren)**
- Full institutional depth: all sections, all data points, all source citations retained.
- Preserve numeric specifics (occupancy %, capex $, rate deltas) and per-item source attributions.
- Tone: direct, concise, active voice; no filler; no exclamation points (per profile).

**Profile B — Huddle (Austin & Sadie)**
- Condensed: lead with the Wake Robin-relevant "so what" per section; drop deep infra/quant items not decision-relevant to the huddle.
- Retain the 3 Discussion Starters verbatim (these ARE the huddle artifact — do not condense).
- Retain any Real Estate Footprint and Proptech/AI items in full; these are the huddle's core.
- Tone: same voice; framed as questions/prompts, not conclusions (per Darren's discussion-starter convention).

### 4.3 Fidelity guardrails (fail-closed)
- **No new facts.** The node may only subtract or reframe; a coherence check should reject any Profile B claim not traceable to the Profile A payload.
- **Discussion Starters are frozen.** They pass through verbatim to both profiles.
- **Source citations survive condensation** in Profile A; in Profile B, at minimum the source name is retained on any retained data point.
- If the node cannot produce Profile B without dropping a Discussion Starter or fabricating a bridge, it fails closed and emits Profile A only, with a flag noting Profile B was suppressed.

## 5. Delivery options (pick one at review)

- **Option 1 (lowest risk):** Two clearly-labeled sections within the *existing* single digest email — "Full Brief" + "Huddle Summary." No new send paths.
- **Option 2:** Two separate emails from the same run — full brief to Darren, huddle summary as a separate deliverable. Requires deciding recipients/timing.
- **Option 3:** Single email + a Town Doc for the huddle summary variant.

Recommended for first test: **Option 1** — no new delivery plumbing, fully reversible.

## 6. Rollout plan (governance-safe)

1. **Shadow/manual test (Phase 0):** Run the personalization node on the *next* real digest payload in manual mode; compare Profile A output against the current digest for parity (no facts lost). Review Profile B by hand.
2. **Validation gate:** Darren confirms Profile B is huddle-ready and Profile A is at full parity with today's output. One clean cycle required before any automation.
3. **Promote (Phase 1):** Only after explicit approval, fold the node into the live AI Digest routine via `update_routine_config`. No cron change beyond the existing digest schedule.
4. **Do not** wire this into any other routine, or generalize the pattern to the screener/SEC/Hermes lanes, without a separate spec.

## 7. Acceptance criteria

- Profile A is at or above content parity with the current digest (zero data-point loss).
- Profile B retains all 3 Discussion Starters verbatim + full Real Estate Footprint + Proptech/AI items.
- No fabricated facts in Profile B (coherence check passes).
- Fail-closed behavior verified: forcing a missing Discussion Starter triggers Profile-A-only fallback with a flag.
- One clean manual cycle reviewed and approved by Darren.

## 8. Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| Condensation drops a decision-relevant item for the huddle | Whitelist Real Estate + Proptech/AI + Discussion Starters as always-full |
| Node hallucinates a "bridge" summary | No-new-facts coherence gate; fail closed |
| Scope creep into research logic | Spec restricts node to post-research rendering only |
| Silent regression in Profile A | Parity check against current digest before promotion |

## 9. What this is NOT

- Not an integration with any JPMorgan system. Ask David is JPMorgan-internal; there is no API or product to connect to. This spec ports an *architecture pattern*, not a vendor.
- Not a model, scorer, ranker, or selector change.
- Not authorized for production until Phase 0 shadow test + explicit approval.

## 10. Next steps after this spec

If approved, the natural follow-on specs (each separate, each gated):
- **Pattern #2:** Reflection / LLM-as-judge gate for SEC alert + biotech screener output.
- **Pattern #4:** Formal confidence-threshold HITL escalation for write-capable routines.
- **Pattern #3:** Two-level planning-node routing for Hermes orchestration (architecture-freeze boundary — observe/spec only).

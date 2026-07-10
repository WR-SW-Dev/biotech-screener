# DEM forward-validation candidate — model-hash equivalence & hash-boundary fix

**Date:** 2026-07-10
**Author:** Biotech IC Council review (ICD-20260710-001), operator-directed
**Status:** Evidence complete; hash-boundary fix implemented on branch `fix/fwd-validation-capture-guard` (not deployed). Candidate re-registration pending operator approval.
**Classification:** Model-freeze integrity — **benign (annotation-only)**. NO change to scoring, selection, feature, or gate logic.
**Affects:** `tools/run_forward_validation.py` (`compute_model_hash`), forward-shadow mandate SM-20260629-001. No production model behavior change.

---

## 1. Finding

The forward-validation daily capture flags `model_hash_match FAIL`: the model hash computed today (`a7a80e85db4e7479`) differs from the frozen candidate registered for SM-20260629-001 (`a9983a67c6954813`, registered 2026-06-26 / recorded 2026-06-28). The question that matters for the mandate: **did the DEM model change during the freeze, or is the hash reacting to something behavior-neutral?**

**Answer: behavior-neutral.** The entire difference is a single type-annotation line. The model under evaluation is semantically identical to the frozen candidate.

## 2. Evidence

`compute_model_hash()` fingerprints exactly three files: `ranker_engine.py`, `selector_engine.py`, `decision_engine.py`. Only one commit touched any of them since the freeze:

- **`b12addd0`** (2026-07-08) — *"fix(mypy): green the type-check CI job (63→0 errors) — #485"*.

Reconstructing the raw-bytes hash from the bytes immediately **before** that commit reproduces the registered candidate hash exactly:

| Bytes | raw-bytes hash | note |
|---|---|---|
| freeze-era (`b12addd0^`) | `a9983a67c6954813` | **exact match** to registered candidate |
| current (`b12addd0`, == working tree) | `a7a80e85db4e7479` | the observed "drift" |

The complete byte-level difference across all three files:

```diff
# decision_engine.py — compute_sort_contribs signature
-) -> Tuple[float, Dict[str, float]]:
+) -> Tuple[Decimal, Dict[str, Decimal]]:
```

- `ranker_engine.py` and `selector_engine.py` are **byte-identical** pre/post.
- The commit message states the function "already returned Decimal; annotation-only." Python does not evaluate annotations during execution, so this line has **zero runtime effect** — the function's returned values are unchanged.

Conclusion: this is the council rubric's **bucket 2** — *only serialization/operational code changed; the model hash boundary is too broad.* No goalpost has moved. The mandate does **not** need reissuing and the model does **not** need reverting.

## 3. Root cause

`compute_model_hash()` hashed the **raw source bytes** of the model files. That makes the model identity sensitive to type annotations, docstrings, comments, and whitespace — none of which affect scoring. A one-character annotation edit therefore invalidated a live freeze.

## 4. Fix — behavioral fingerprint (`HASH_SCHEME = "ast-v1"`)

`compute_model_hash()` now fingerprints an **AST-normalized** form of each model file:

- **stripped** (behavior-neutral): argument/return/variable type annotations, docstrings. Comments and whitespace are already absent from the AST.
- **preserved**: all runtime logic. Annotated assignments keep their effect (`x: int = 5` → `x = 5`); a bare declaration `x: int` (no runtime effect) is dropped.
- the scheme tag `ast-v1` is mixed into the hash so future scheme changes never collide.

The original raw-bytes function is retained as `compute_model_hash_legacy()` for audit and one-time migration.

### Proof the fix is correct

| Scheme | freeze-era | current | equal? |
|---|---|---|---|
| legacy raw-bytes | `a9983a67c6954813` | `a7a80e85db4e7479` | ✗ (the bug) |
| **ast-v1 behavioral** | `827c35a9ed3ee6e1` | `827c35a9ed3ee6e1` | **✓** |

Negative control: injecting a real logic edit into the freeze-era `decision_engine.py` moves the ast-v1 hash (`827c35a9ed3ee6e1` → `48fb8e95092b968e`). So the scheme is insensitive to cosmetics and sensitive to behavior.

Regression test: `tests/test_model_hash_boundary.py` (5 cases) — cosmetic edits stable, logic edit moves, legacy scheme documented as fooled, scheme-tag mixed in, bare-vs-valued annotation handling.

## 5. Blast radius

`compute_model_hash()` is defined and called **only** in `tools/run_forward_validation.py`. Every other consumer (`investability_gate_dashboard`, `run_forward_bootstrap`, `weekly_validation_summary`, dashboards, etc.) **reads a stored hash string** and compares — none recompute — so changing the function cannot alter their behavior. The only effect is the hash written into **new** captures and the `model_hash_match` DQ check.

## 6. Migration — operator action required

Adopting `ast-v1` means new captures fingerprint to `827c35a9ed3ee6e1`, which will not match the candidate's stored legacy hash `a9983a67`. To keep the freeze honest (record the **same behavioral identity**, not a new one):

1. Review and merge this branch.
2. Re-register the frozen candidate under `ast-v1`. Recommended `CANDIDATE.json` fields:
   - `model_hash: "827c35a9ed3ee6e1"`, `hash_scheme: "ast-v1"` <!-- pragma: allowlist secret -->
   - `legacy_model_hash: "a9983a67c6954813"` (raw-bytes, for audit) <!-- pragma: allowlist secret -->
   <!-- Values above are model-file content fingerprints (SHA-256[:16]), not credentials. -->

   - `equivalence_note: "a7a80e85 (legacy) proven annotation-only-equivalent to a9983a67; see docs/governance/2026-07-10-dem-candidate-hash-equivalence.md"`
   - keep `registered: "2026-06-26"` unchanged — the behavioral freeze date is unchanged.
   This is **not** goalpost-moving: §4 proves `ast-v1(freeze) == ast-v1(current)`.

## 7. What this does NOT do

- Does not change any DEM scoring/selection/ranking/gate behavior.
- Does not resolve SM-20260629-001. Eligible **live** windows remain **0**; the mandate stays **HOLD / unresolved**.
- Does not by itself make `model_hash_match` pass on live captures until the candidate is re-registered under `ast-v1` (step 6).

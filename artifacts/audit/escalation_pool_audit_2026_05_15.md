# Escalation Pool Audit — 2026-05-15

## Pool Composition

- **Raw records**: 14,212
- **Raw escalation pool** (needs_review=True, informational_only=False, no collision): 4,223
- **Deduplicated pool**: 2,963

### Category Distribution
| Category | Count | % |
|----------|-------|---|
| other | 1,788 | 60.3% |
| clinical | 721 | 24.3% |
| regulatory | 355 | 12.0% |
| mna | 93 | 3.1% |
| safety | 6 | 0.2% |

### Confidence Distribution
| Range | Count | % |
|-------|-------|---|
| 0.3–0.5 | 1,788 | 60.3% |
| 0.5–0.7 | 1,082 | 36.5% |
| ≥0.7 | 93 | 3.1% |

## Sample Audit (n=30, seed=20260515)

**Purity: 100%** (30/30 CLEAN)

All sampled records passed noise and ticker-collision re-verification:
- No false positives
- No collisions detected
- No need for reclassification

### Sample Breakdown
- Clinical (8): NRIX, TCRX, ANIP, ABVX, RARE, GLUE, FOLD, NTLA, OCS, MCRB
- Regulatory (6): URGN, CGON, RLAY, RCUS, DRUG, RCKT
- M&A (3): EBS, VCEL, ESPR
- Safety (2): NTLA, DAWN
- Other (7): EOLS, CTKB, ACRS, VERA, TECH, FOLD, IVVD, GLUE, REPL

## Verdict

✅ **Escalation pool health: GOOD**

- Target purity threshold (≥80%): **EXCEEDED** at 100%
- No action required
- Pool is suitable for model evaluation/swaps (e.g., FinGPT)
- Continue monitoring on next audit cycle

## Notes

- "Other" category (60%) represents lower-confidence items that may benefit from future tightening
- No high-confidence collisions (c≥0.7) present in audit sample
- Pool composition stable; no evidence of systematic classification drift

---
**Audited**: 2026-05-15 · **Method**: balanced sample, noise/collision re-verification

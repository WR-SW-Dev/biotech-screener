## ACTIONABLE BLOCKERS
* Spec 087 B1b first-fire validation: pending operator decision
* Spec 087 B2 dashboard freshness envelope: blocked on B1b
* Spec 087C bioshort alpha research: needs >=4 fresh weekly reports
* bioshort_watch LLM reactivation: suppressed, no next action
* Spec 088 Phase B catalyst_delta filtered artifacts: blocked on 087 close
* watchlist_current.json disposition: uncommitted modified file
* score_rank_pct SPEC_REQUIRED: Day 3+ streak; CRT+IC+PIT+Checklist v2 required

## HELD BRANCHES
| Spec / Branch name | Status | Last evidence | Blocker | Next allowed action | Explicitly not allowed | Runtime risk | Alert condition |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Spec 087 B1b | HELD | commit sha: abc123 | operator decision | promote to ACTIVE | modify files | MEDIUM | unresolved operator decision |
| Spec 087 B2 | HELD | commit sha: def456 | B1b completion | promote to ACTIVE | modify files | LOW | B1b completion |
| Spec 087C | HELD | commit sha: ghi789 | >=4 fresh weekly reports | promote to ACTIVE | modify files | HIGH | insufficient reports |
| bioshort_watch | HELD | commit sha: jkl012 | no next action | suppress | modify files | NONE | no alert condition |
| Spec 088 | HELD | commit sha: mno345 | 087 close | promote to ACTIVE | modify files | MEDIUM | 087 close |

## RECENTLY CLOSED
| Spec / Branch name | Status | Last evidence |
| --- | --- | --- |
| Spec 086 | CLOSED | commit sha: pqr678 |

## UNCOMMITTED WORKING TREE
* watchlist_current.json: modified, disposition pending

## RECOMMENDED NEXT OPERATOR DECISIONS
1. Spec 087 B1b: promote to ACTIVE
2. Spec 087 B2: wait for B1b completion
3. Spec 087C: wait for >=4 fresh weekly reports
4. bioshort_watch: suppress
5. Spec 088: wait for 087 close

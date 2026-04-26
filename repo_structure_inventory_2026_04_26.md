# Repo Structure Inventory — 2026-04-26

**Status**: AUDIT ARTIFACT ONLY. No file moves, deletions, or archive operations performed.

**Context**: 13F/cohort quarantine active per `cohort_state.json` (38 → 42 manager expansion on 2026-04-25). Quarantine auto-recovers on the 2026-04-27 organic snapshot. Cleanup deferred until that snapshot verifies clean — file moves are technically low-risk but audit-noisy during an active quarantine.

**Scope**: Root-level files of `/mnt/c/Projects/biotech_screener/biotech-screener/`. Reachability traced from `run_screen.py` (canonical production runner) and supporting entry points (`run_daily.py`, `run_production_screen.py`, `run_phase2_daily.py`, active cron scripts in `tools/`).

---

## Summary Counts

| Disposition         | Count |
|---------------------|------:|
| LIVE                |    39 |
| Archive candidates  |   113 |
| UNCLEAR             |     6 |
| **Total cataloged** | **158** |

---

## Top Root-Bloat Categories

| Category                                  | Count | Disposition           |
|-------------------------------------------|------:|-----------------------|
| Stale JSON output dumps in root           |    47 | All archive (zero refs) |
| Design-archaeology `.md` files            |    55 | Archive (Jan-cohort)  |
| Versioned module variants (m2/m3/m4/m5)   |    16 | 11 LIVE / 5 archive   |
| `run_screen.py` peers and patches         |     5 | 3 LIVE / 2 archive    |
| Windows `.bat` / `.ps1` launchers         |    13 | 8 LIVE / 5 UNCLEAR    |
| SEC 13F extractor variants                |     3 | 1 LIVE / 2 archive    |
| Position-of-success (`pos_*`) variants    |     5 | 4 LIVE / 1 archive    |
| Active root docs to keep                  |     3 | `CLAUDE.md`, `CHANGELOG.md`, `GOVERNANCE.md` |

**Stale JSON dumps**: `results_*.json` (13), `screen_*.json` (4), `test_*.json` (11), `enriched_screen_*.json` (3), `production_screen_*.json` (3), `top50_*.json` (2), `screening_output_*.json` (3), plus assorted boot/adapted/momentum dumps. All last-touched Jan–Feb 2026. Live outputs go to `production_data/` exclusively.

**Design-archaeology MDs**: `MODULE_*_FIX.md`, `MODULE_3A_*.md` (7), `*_GUIDE.md`, `*_QUICK_START.md`, `FINAL_CONFIG_*.md`, `FINAL_AGGRESSIVE_*.md`, `*_INTEGRATION.md`, `*_IMPLEMENTATION_*.md`. All Jan 5–18 cohort describing closed lanes superseded by current ruleset `2a3e79eb`.

---

## Top 20 Highest-Risk Ambiguity Files

These are the files where a wrong move would matter — review individually before any disposition decision.

| # | File | Why ambiguous |
|--:|------|---------------|
|  1 | `edgar_13f_extractor_CORRECTED.py` | Filename implies a bug fix; never wired in. **Special review flag — see below.** |
|  2 | `edgar_13f_extractor.py` | Newer than `edgar_13f.py` (Apr 3 vs Mar 20) but `aggregator.py` still imports the older one. Was this an aborted swap? |
|  3 | `module_2_financial.py` | Base version; `_v2.py` is canonical. Confirm no test/research path still imports the base. |
|  4 | `module_3_scoring_v2.py` | Only 3 imports, none in live path. Verify it isn't a parked future-promotion. |
|  5 | `module_4_clinical_dev_v2.py` | 3 imports, dead in live path — but Clinical Stack v2 work is active per memory; verify isolation. |
|  6 | `module_5_composite.py` | Base; used transitively (40 imports). Live but fragile to touch. |
|  7 | `module_5_composite_v2.py` | Live transitive (9 imports). Confirm coexistence with v3 + `_with_defensive` is intentional. |
|  8 | `module_5_diagnostics_v3.py` | Only 4 imports; recent (Apr 9). Live but lightly attached. |
|  9 | `module_5_alpha_cohort.py` | Directly imported by `run_screen.py`; LIVE. Listed only because the name suggests obsolescence. |
| 10 | `module_3_schema.py` | Base; 30 imports. LIVE — do not confuse with `_v2`. |
| 11 | `pos_ablation_framework.py` | Older than `pos_ablation.py`; appears superseded. Confirm no offline framework still uses it. |
| 12 | `pos_prior_engine.py` | Only 1 import; newest variant (Apr 16). Live but lightly attached. |
| 13 | `pos_model_v2.py` | 7 imports; live. Confirm alongside `pos_engine.py`. |
| 14 | `fix_run_screen.py` | Looks like a one-off patch from Mar 20. Verify the fix was merged into `run_screen.py` before archiving. |
| 15 | `patch_topn.py` | Same shape as `fix_run_screen.py`. Verify merge before archive. |
| 16 | `run_phase2_health_calibration.py` | UNCLEAR — no recent activity, not in active cron. May be on-demand only. |
| 17 | `run_phase2_snapshot_delta.py` | Referenced in CLAUDE.md as the ruleset-pinned location. LIVE — do not move. |
| 18 | `cron_bellringer.sh` / `cron_data_auditor.sh` | Older cron scripts (Apr 2). Confirm still scheduled in `crontab -l`. |
| 19 | `get_top60_*.bat` (3 variants) + `phase1_top50.ps1` | UNCLEAR launchers; user-decision. |
| 20 | `cron_one_shot_2026_04_28.sh` | One-shot cleanup memo cron firing Tue 09:00 EDT 2026-04-28. **Do not archive until after it fires.** |

---

## Proposed Archive Buckets

To be created **only after 2026-04-27 organic snapshot verifies clean**.

```
archive/
├── results_dumps_2026-01/        # 47 stale JSON outputs from root
├── docs/design_2026-01/          # 55 design-archaeology .md files + README pointing to CLAUDE.md
├── code_2026-04/                 # 5 dead module variants + 2 dead patches
│   ├── module_2_financial.py
│   ├── module_3_scoring_v2.py
│   ├── module_4_clinical_dev_v2.py
│   ├── pos_ablation_framework.py
│   ├── edgar_13f_extractor.py            # gated on review flag below
│   ├── edgar_13f_extractor_CORRECTED.py  # gated on review flag below
│   ├── fix_run_screen.py
│   └── patch_topn.py
└── launchers_legacy/             # 5 legacy .bat / .ps1 launchers (user-decision)
```

**Files explicitly NOT moved** (stay in root): `CLAUDE.md`, `CHANGELOG.md`, `GOVERNANCE.md`, all live module variants (transitively reachable from `run_screen.py`), all active cron scripts in `tools/`, all entry-point `run_*.py` runners, `IV_QUARANTINE_BLAST_RADIUS_2026_04_25.md`, `IV_UNIT_DRIFT_DIAGNOSIS_2026_04_25.md`, this file.

---

## Post-2026-04-27 Cleanup Sequence

Execute in order. Pause between phases to confirm one production cycle is clean before proceeding to the next (per the "pause between control-plane changes" policy).

1. **Verify 2026-04-27 organic snapshot is clean.** Read `cohort_state.json` and confirm `inst_delta_z_valid: true`, `rank_delta_valid: true`. If still quarantined, halt and reassess.
2. **Phase A — JSON dumps.** Move 47 stale JSONs to `archive/results_dumps_2026-01/`. Zero code references; safe. Run one production cycle. Confirm clean.
3. **Phase B — design archaeology.** Move 55 root `.md` files to `archive/docs/design_2026-01/`. Add a README in that directory pointing to `CLAUDE.md` as the canonical operating doc. Confirm `CLAUDE.md` references still resolve.
4. **Phase C — 13F extractor review (gated).** Resolve `edgar_13f_extractor_CORRECTED.py` question (see flag below) BEFORE archiving any 13F duplicates. Do not move 13F files in the same change as anything else.
5. **Phase D — dead code variants.** Move 5 dead module variants + `fix_run_screen.py` + `patch_topn.py` to `archive/code_2026-04/`. After move, run the full test suite and a production cycle. Any import error → restore immediately.
6. **Phase E — legacy launchers.** User-decision: archive 5 `get_top60_*.bat` / `phase1_top50.ps1` files, or keep them.
7. **Phase F — spent one-shot.** After `cron_one_shot_2026_04_28.sh` fires successfully on 2026-04-28, archive it.

**Hard rule**: Never bundle this cleanup with model/scoring/data work. Per the "no formatter churn in model work" policy, this is a structural-hygiene PR and must stand alone.

---

## Special Review Flag — `edgar_13f_extractor_CORRECTED.py`

**Why this needs human review before archiving**:

- Three coexisting 13F extractor files in root:
  - `edgar_13f.py` (Mar 20) — **LIVE**, imported by `aggregator.py`
  - `edgar_13f_extractor.py` (Apr 3) — newer; not imported anywhere in live code
  - `edgar_13f_extractor_CORRECTED.py` (Apr 5) — newest; filename implies a bug fix; not imported anywhere
- The naming pattern (`_CORRECTED`) strongly suggests a fix was authored but never adopted into the live import path.
- 13F is a load-bearing alpha lane (institutional block = 92.7% of selector variance per Production Model Identity audit). Silently archiving a "corrected" extractor without verifying that the correction either (a) was already folded into `edgar_13f.py`, or (b) is irrelevant to current production, risks losing a real bug fix.

**Required before any disposition**:
1. `git log` and `git blame` both `_CORRECTED.py` and `edgar_13f.py` to find the commit that introduced `_CORRECTED` and the rationale.
2. Diff `edgar_13f_extractor_CORRECTED.py` against `edgar_13f.py` (and against `edgar_13f_extractor.py`) — if the correction is meaningful and absent from the live extractor, this is a bug, not a cleanup.
3. If the correction is real and unmerged: open it as a separate ticket. Do not bundle into the structural cleanup PR.
4. Only after that resolution, archive the unused extractor variants.

**Until resolved**: leave all three files in place.

---

## Hard Constraints in Effect

- No file moves
- No deletions
- No archive directory creation
- No import rewrites
- No cleanup commits
- No touching JSON dumps yet

This artifact is the deliverable. Cleanup execution is gated on the 2026-04-27 organic snapshot.

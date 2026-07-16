# Corrections Log (last 50)

<!-- Raw correction entries, newest first. Compact after 50. -->

## 2026-03-29: f-string table headers
User: pre-commit hook failed repeatedly on f-strings with no placeholders in markdown table headers.
Lesson: Use plain strings for static headers. Promoted to HOT memory.

## 2026-03-29: Open Targets field rename
API returned 400 — maxPhaseForIndication → maxClinicalStage. Silent failure via exception swallowing.
Lesson: Check API schema changes when queries fail silently. Promoted to HOT memory.

## 2026-03-29: Portfolio attribution sign confusion
Initial P&L display used `:.1%` format on values already in percent (e.g., -3.1 displayed as -310%).
Lesson: Check whether values are decimal (0.03) or percent (3.0) before formatting.

## 2026-05-28: LRN-20260525-001 pytest-xdist claim superseded
LRN-20260525-001 stated "pytest-xdist was also required while main still has pytest addopts `-n auto --dist worksteal`". As of 2026-05-28, `pyproject.toml` uses `addopts = "-q -m 'not network'"` — no `-n auto`, no xdist. `pytest-xdist` is not in `requirements.txt`. The `.cursor/environment.json` now installs only `pip install -r requirements.txt` (no xdist). The remainder of LRN-20260525-001 (dotenv missing, Python deps needed) remains valid. See LRN-20260528-002.

## 2026-05-28: CODEGRAPH_RUNBOOK.md version and index counts were stale
Runbook had codegraph `v0.9.4`; installed binary is `v0.9.6`. Index counts (1,668 files / 50,291 nodes / 114,066 edges) were stale; current index is 1,677 files / 50,419 nodes / 113,867 edges. Rollback section had hardcoded WSL `/mnt/c/Projects/...` paths — replaced with `.`.

## 2026-03-29: Snapshot double nesting
--snapshot-dir data/snapshots/2026-03-28 created data/snapshots/2026-03-28/2026-03-28/.
Lesson: Pass parent dir without date suffix. Promoted to HOT memory.

## [2026-07-02 00:30 UTC] ops_supervisor ORANGE
- action: investigate
- summary: ORANGE — 2 new or expired-window anomalies; investigate.
- artifact: artifacts/ops_supervisor/2026-07-01_supervisor.json
- Promotion-lane: skill

## [2026-07-04 00:30 UTC] ops_supervisor ORANGE
- action: investigate
- summary: ORANGE — 2 new or expired-window anomalies; investigate.
- artifact: artifacts/ops_supervisor/2026-07-02_supervisor.json
- Promotion-lane: skill

## [2026-07-04 00:30 UTC] ops_supervisor ORANGE
- action: investigate
- summary: ORANGE — 2 new or expired-window anomalies; investigate.
- artifact: artifacts/ops_supervisor/2026-07-03_supervisor.json
- Promotion-lane: skill

## [2026-07-07 00:30 UTC] ops_supervisor ORANGE
- action: investigate
- summary: ORANGE — 3 new or expired-window anomalies; investigate.
- artifact: artifacts/ops_supervisor/2026-07-06_supervisor.json
- Promotion-lane: skill

## [2026-07-08 00:30 UTC] ops_supervisor ORANGE
- action: investigate
- summary: ORANGE — 2 new or expired-window anomalies; investigate.
- artifact: artifacts/ops_supervisor/2026-07-07_supervisor.json
- Promotion-lane: skill

## [2026-07-15 00:30 UTC] ops_supervisor ORANGE
- action: investigate
- summary: ORANGE — 2 new or expired-window anomalies; investigate.
- artifact: artifacts/ops_supervisor/2026-07-08_supervisor.json
- Promotion-lane: skill

## [2026-07-15 00:30 UTC] ops_supervisor ORANGE
- action: investigate
- summary: ORANGE — 2 new or expired-window anomalies; investigate.
- artifact: artifacts/ops_supervisor/2026-07-09_supervisor.json
- Promotion-lane: skill

## [2026-07-15 00:30 UTC] ops_supervisor ORANGE
- action: investigate
- summary: ORANGE — 4 new or expired-window anomalies; investigate.
- artifact: artifacts/ops_supervisor/2026-07-10_supervisor.json
- Promotion-lane: skill

## [2026-07-15 00:30 UTC] ops_supervisor RED
- action: fix_now
- summary: RED — rankings.csv missing for 2026-07-13 past production-due-time (18:00 ET).
- artifact: artifacts/ops_supervisor/2026-07-13_supervisor.json
- Promotion-lane: skill

## [2026-07-15 00:30 UTC] ops_supervisor RED
- action: fix_now
- summary: RED — rankings.csv missing for 2026-07-14 past production-due-time (18:00 ET).
- artifact: artifacts/ops_supervisor/2026-07-14_supervisor.json
- Promotion-lane: skill

## [2026-07-16 21:30 UTC] ops_supervisor ORANGE
- action: investigate
- summary: ORANGE — 3 new or expired-window anomalies; investigate.
- artifact: artifacts/ops_supervisor/2026-07-16_supervisor.json
- Promotion-lane: skill

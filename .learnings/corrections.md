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

## 2026-03-29: Snapshot double nesting
--snapshot-dir data/snapshots/2026-03-28 created data/snapshots/2026-03-28/2026-03-28/.
Lesson: Pass parent dir without date suffix. Promoted to HOT memory.

import logging
import os
import sys
from pathlib import Path

# tools/ sits one level below repo root — add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.WARNING, format="%(message)s")
os.environ["OPERATOR_DELIVERY_DRY_RUN"] = "1"

from common.operator_delivery import send_operator_event

print("=== dry-run: held_spec_ledger (INFO) ===")
r1 = send_operator_event(
    channel="town",
    severity="INFO",
    event_type="held_spec_ledger",
    title="Held-spec ledger updated",
    summary="6 held items. Spec 087 B1b awaiting first-fire Fri 18:00 ET.",
    artifact="artifacts/ops/held_spec_ledger/latest.md",
    next_operator_action="Validate bioshort first-fire after 18:00 ET",
    extra={"held_count": 6, "first_fire_status": "PENDING_NOT_YET_DUE"},
    skip_dedupe=True,
)
print("result:", r1)

print()
print("=== dry-run: first_fire_fail (FAIL) ===")
r2 = send_operator_event(
    channel="town",
    severity="FAIL",
    event_type="first_fire_fail",
    title="Bioshort first-fire FAILED",
    summary="hedge_report_2026-05-08.json missing past alert deadline.",
    artifact="artifacts/ops/first_fire_ledger/latest.md",
    next_operator_action="Inspect logs/biotech_hedge_report.log",
    extra={
        "spec": "Spec 087 B1b",
        "deadline": "2026-05-09T09:00:00-04:00",
        "not_allowed": ["reactivate bioshort_watch LLM", "run extra producer manually"],
    },
    skip_dedupe=True,
)
print("result:", r2)

print()
print("=== dry-run: snapshot_missing (FAIL) ===")
r3 = send_operator_event(
    channel="town",
    severity="FAIL",
    event_type="snapshot_missing",
    title="Production snapshot missing",
    summary="No snapshot for 2026-05-07 after 16:45 ET.",
    artifact="data/snapshots/2026-05-07/",
    next_operator_action="Check logs/cron.log for cron_daily_production.sh",
    skip_dedupe=True,
)
print("result:", r3)

print()
print("PASS" if all([r1, r2, r3]) else "FAIL")
sys.exit(0 if all([r1, r2, r3]) else 1)

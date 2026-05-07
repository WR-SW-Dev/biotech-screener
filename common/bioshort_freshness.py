"""Spec 087 B0 — bioshort upstream freshness gate.

Read-only check on `output/hedge_report/hedge_report_*.json` to decide whether
`run_screen.py` should invoke `tools/build_bioshort_watch.py` or skip with an
explicit status. Also writes `artifacts/bioshort_watch/latest_status.json` so
downstream readers can distinguish "skipped this run" from "guard never ran".

No scoring touch. No producer side effects. Threshold is calendar days.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

STALE_THRESHOLD_DAYS = 9
HEDGE_REPORT_RE = re.compile(r"^hedge_report_(\d{4}-\d{2}-\d{2})\.json$")

_STATUS_FRESH = "FRESH"
_STATUS_STALE = "STALE"
_STATUS_ORPHANED = "ORPHANED"
_CONSUMER_STATUS = "suppressed"


@dataclass(frozen=True)
class FreshnessResult:
    status: str
    latest_as_of_date: Optional[str]
    age_days: Optional[int]
    threshold_days: int

    def to_status_doc(self) -> dict:
        return {
            "status": self.status,
            "upstream_as_of_date": self.latest_as_of_date,
            "upstream_age_days": self.age_days,
            "threshold_days": self.threshold_days,
            "consumer_status": _CONSUMER_STATUS,
        }


def check_upstream_freshness(
    report_dir: Path,
    *,
    threshold_days: int = STALE_THRESHOLD_DAYS,
    today: Optional[date] = None,
) -> FreshnessResult:
    today_d = today or date.today()
    if not report_dir.exists() or not report_dir.is_dir():
        return FreshnessResult(_STATUS_ORPHANED, None, None, threshold_days)

    latest_date: Optional[date] = None
    latest_str: Optional[str] = None
    for entry in report_dir.iterdir():
        if not entry.is_file():
            continue
        match = HEDGE_REPORT_RE.match(entry.name)
        if not match:
            continue
        candidate_str = match.group(1)
        try:
            candidate_date = date.fromisoformat(candidate_str)
        except ValueError:
            continue
        if latest_date is None or candidate_date > latest_date:
            latest_date = candidate_date
            latest_str = candidate_str

    if latest_date is None or latest_str is None:
        return FreshnessResult(_STATUS_ORPHANED, None, None, threshold_days)

    age = (today_d - latest_date).days
    status = _STATUS_FRESH if age <= threshold_days else _STATUS_STALE
    return FreshnessResult(status, latest_str, age, threshold_days)


def write_status_artifact(artifacts_dir: Path, result: FreshnessResult) -> Path:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    out_path = artifacts_dir / "latest_status.json"
    doc = result.to_status_doc()
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        dir=str(artifacts_dir),
        delete=False,
    ) as tmp:
        json.dump(doc, tmp, indent=2, sort_keys=True)
        tmp_name = tmp.name
    os.replace(tmp_name, str(out_path))
    return out_path

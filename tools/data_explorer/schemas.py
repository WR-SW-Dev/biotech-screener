"""Typed response envelopes for the Data Explorer command contract.

Every command returns a ResponseEnvelope with:
  ok, command, path, snapshot_date, warnings, errors, generated_at, data

The ``data`` field is command-specific.  Typed helpers build each one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def envelope(
    command: str,
    data: Dict[str, Any],
    *,
    ok: bool = True,
    path: str = "",
    snapshot_date: str = "",
    warnings: Optional[List[str]] = None,
    errors: Optional[List[str]] = None,
    elapsed_ms: Optional[int] = None,
    data_source: str = "rankings.csv",
) -> Dict[str, Any]:
    """Build a standard response envelope."""
    resp = {
        "ok": ok,
        "command": command,
        "path": path,
        "snapshot_date": snapshot_date,
        "warnings": warnings or [],
        "errors": errors or [],
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "meta": {
            "elapsed_ms": elapsed_ms,
            "data_source": data_source,
            "cache": False,
        },
        "data": data,
    }
    return resp


# ---------------------------------------------------------------------------
# QA severity helpers
# ---------------------------------------------------------------------------


def qa_severity_summary(issues: List[Dict[str, str]]) -> Dict[str, int]:
    """Count issues by severity level."""
    counts: Dict[str, int] = {"error": 0, "warning": 0, "info": 0}
    for issue in issues:
        sev = issue.get("severity", "info")
        counts[sev] = counts.get(sev, 0) + 1
    return counts


def qa_exit_code(issues: List[Dict[str, str]]) -> int:
    """Determine exit code from QA issues.

    0 = clean, 1 = warnings only, 2 = errors present.
    """
    has_error = any(i.get("severity") == "error" for i in issues)
    has_warning = any(i.get("severity") == "warning" for i in issues)
    if has_error:
        return 2
    if has_warning:
        return 1
    return 0

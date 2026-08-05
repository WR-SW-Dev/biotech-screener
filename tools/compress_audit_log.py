#!/usr/bin/env python3
"""Compress old entries in the trading isolation audit log. Never deletes.

See ``docs/design/MULTI_TENANCY_PR_PLAN.md`` §3 (PR 4).

``artifacts/trading/isolation_audit.jsonl`` records every trading-boundary decision made
by ``common/trading_guard.py`` — every bind, every accepted order, every refusal. It had
no retention logic at all and appended indefinitely.

Operator decision (2026-08-03): it is an audit trail, not routine data, so entries older
than one year are **compressed, not deleted**. Records move into
``isolation_audit-YYYY.jsonl.gz`` beside the live log and stay readable forever.

Design rules, all of which follow from "this is evidence":

* Nothing is discarded. A line that will not parse as JSON, or that carries no usable
  timestamp, is **retained in the live log** rather than dropped — a corrupt audit record
  is itself evidence, and a retention tool is the wrong place to decide it is worthless.
* Idempotent. Cron may run this twice; the second run must archive nothing new.
* Atomic. The live log is rewritten via a temp file and one rename, so an interrupted run
  cannot truncate it.
* Dry-run by default. ``--apply`` is required to change anything.

Usage::

    python3 tools/compress_audit_log.py                      # plan only
    python3 tools/compress_audit_log.py --apply              # archive >1y
    python3 tools/compress_audit_log.py --older-than-days 730 --apply

Python 3.10 compatible.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_OLDER_THAN_DAYS = 365
ENV_AUDIT_PATH = "BIOTECH_TRADING_AUDIT_LOG"


class AuditRetentionError(Exception):
    """Refusing to run with parameters that would risk the audit trail."""


@dataclass
class CompressionResult:
    archived: int = 0
    retained: int = 0
    unparseable: int = 0
    archives: "list[Path]" = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.archives is None:
            self.archives = []


def default_audit_path() -> Path:
    override = os.environ.get(ENV_AUDIT_PATH, "").strip()
    if override:
        return Path(override)
    return REPO_ROOT / "artifacts" / "trading" / "isolation_audit.jsonl"


def archive_path_for(log_path: Path, year: int) -> Path:
    """``isolation_audit.jsonl`` + 2025 -> ``isolation_audit-2025.jsonl.gz``."""
    stem = log_path.name
    for suffix in (".jsonl", ".json", ".log"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return log_path.parent / (stem + "-" + str(year) + ".jsonl.gz")


def _parse_ts(record: Any) -> Optional[datetime]:
    if not isinstance(record, dict):
        return None
    raw = record.get("ts")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def read_all_records(log_path: Path) -> "list[dict]":
    """Every record still readable — live log plus every archive beside it.

    Used by tests and by anyone auditing the trail; the whole point of compressing rather
    than deleting is that this returns the complete history.
    """
    out: "list[dict]" = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"_unparseable": line})
    for arch in sorted(log_path.parent.glob(archive_path_for(log_path, 0).name.replace("-0", "-*"))):
        with gzip.open(arch, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        out.append({"_unparseable": line})
    return out


def compress_audit_log(
    log_path: Path | str,
    *,
    older_than_days: int = DEFAULT_OLDER_THAN_DAYS,
    apply: bool = False,
) -> CompressionResult:
    """Move records older than ``older_than_days`` into per-year gzip archives."""
    if older_than_days < 1:
        raise AuditRetentionError("older_than_days must be >= 1, got " + str(older_than_days))

    log_path = Path(log_path)
    result = CompressionResult()
    if not log_path.is_file():
        return result

    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)

    keep_lines: "list[str]" = []
    by_year: "dict[int, list[str]]" = {}

    for line in log_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            # Corrupt line: keep it. A retention tool does not get to decide that a
            # malformed audit record is worthless.
            result.unparseable += 1
            keep_lines.append(raw)
            continue

        ts = _parse_ts(rec)
        if ts is None or ts >= cutoff:
            # No usable timestamp means we cannot prove it is old enough to archive.
            keep_lines.append(raw)
            continue

        by_year.setdefault(ts.year, []).append(raw)

    result.archived = sum(len(v) for v in by_year.values())
    result.retained = len(keep_lines)

    if not apply or not by_year:
        result.archives = [archive_path_for(log_path, y) for y in sorted(by_year)]
        return result

    for year in sorted(by_year):
        arch = archive_path_for(log_path, year)
        arch.parent.mkdir(parents=True, exist_ok=True)
        # Append mode: a later run adding more records from the same year accumulates
        # rather than replacing what is already archived.
        with gzip.open(arch, "at", encoding="utf-8") as fh:
            for raw in by_year[year]:
                fh.write(raw + "\n")
        result.archives.append(arch)

    tmp = log_path.with_suffix(log_path.suffix + ".tmp")
    tmp.write_text("".join(x + "\n" for x in keep_lines), encoding="utf-8")
    os.replace(tmp, log_path)  # atomic; an interrupted run cannot truncate the live log
    return result


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", type=Path, default=None, help="audit log (default: artifacts/trading/…)")
    parser.add_argument("--older-than-days", type=int, default=DEFAULT_OLDER_THAN_DAYS)
    parser.add_argument("--apply", action="store_true", help="actually archive; default is a dry run")
    args = parser.parse_args(argv)

    path = args.path or default_audit_path()
    try:
        res = compress_audit_log(path, older_than_days=args.older_than_days, apply=args.apply)
    except AuditRetentionError as exc:
        print("refused: " + str(exc), file=sys.stderr)
        return 2

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(
        json.dumps(
            {
                "mode": mode,
                "path": str(path),
                "older_than_days": args.older_than_days,
                "archived": res.archived,
                "retained": res.retained,
                "unparseable_retained": res.unparseable,
                "archives": [str(p) for p in res.archives],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

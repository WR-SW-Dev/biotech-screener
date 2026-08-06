#!/usr/bin/env python3
"""Prune old per-tenant snapshots and caches. Dry-run by default.

See ``docs/design/MULTI_TENANCY.md`` §4.

Nothing in this repository has ever deleted anything, so this tool is written to fail
safe in every ambiguous case:

* **dry-run unless ``--apply``** is passed
* **hard denylist** of paths that are never pruned at any age
* **count floor** as well as an age window, so a long gap in production cannot empty the
  tree
* **containment check** — refuses to delete anything outside the tenant's own root

The denylist exists because two categories of data here are unrecoverable:

``data/caches/massive_options``
    Point-in-time options data that cannot be re-fetched from any vendor.

``artifacts/forward_validation``
    ``captures.jsonl`` is the immutable evidence of record for shadow mandate
    SM-20260629-001. Pruning a snapshot referenced by a capture would orphan that capture
    and destroy the audit trail, so referenced dates are protected too.

Usage::

    python3 tools/prune_user_data.py --user alice                 # dry run
    python3 tools/prune_user_data.py --user alice --apply
    python3 tools/prune_user_data.py --user alice --retention-days 90 --apply

Python 3.10 compatible.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common.paths import SHARED_CACHE_DIRS, UserPaths, for_user  # noqa: E402
from common.tenancy import UserContext, require_user_context  # noqa: E402

DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Path fragments that are never pruned, regardless of age or count.
DENYLIST_FRAGMENTS = (
    "data/caches/massive_options",
    "artifacts/forward_validation",
    "artifacts/ic_council",
    "golden/",
)


class PruneRefusal(Exception):
    """Raised when a prune target fails a safety check."""


def is_denylisted(path: Path, *, base: Path) -> bool:
    """True if ``path`` is protected by :data:`DENYLIST_FRAGMENTS`.

    Compared on the POSIX-style relative path so the check behaves the same on Windows
    mounts and Linux.
    """
    try:
        rel = Path(path).resolve().relative_to(Path(base).resolve()).as_posix()
    except ValueError:
        # Outside the tenant root: not our business to prune, so treat as protected.
        return True
    for fragment in DENYLIST_FRAGMENTS:
        frag = fragment.rstrip("/")
        if rel == frag or rel.startswith(frag + "/"):
            return True
    # Quarantine / provenance-mismatch snapshots are kept deliberately for audits.
    if "__pre_" in Path(path).name:
        return True
    return False


def protected_dates_from_captures(captures_path: Path) -> "set[str]":
    """Snapshot dates referenced by forward-validation captures.

    A malformed line is skipped rather than fatal, but a *missing* file returns an empty
    set — callers must decide whether that is acceptable (see :func:`plan_prune`, which
    treats an unreadable captures file as a reason to refuse).
    """
    dates: set[str] = set()
    if not captures_path.is_file():
        return dates
    with captures_path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            for key in ("date", "snapshot_as_of_date", "effective_price_date"):
                value = rec.get(key)
                if isinstance(value, str) and DATE_DIR_RE.match(value):
                    dates.add(value)
    return dates


def list_snapshot_dirs(snapshots_root: Path) -> "list[Path]":
    """Dated snapshot directories, newest first. Non-date entries are ignored."""
    if not snapshots_root.is_dir():
        return []
    dirs = [p for p in snapshots_root.iterdir() if p.is_dir() and DATE_DIR_RE.match(p.name)]
    return sorted(dirs, key=lambda p: p.name, reverse=True)


def select_prunable(
    snapshot_dirs: Sequence[Path],
    *,
    today: date,
    retention_days: int,
    min_keep: int,
    protected_dates: Iterable[str] = (),
    base: Path,
) -> "list[Path]":
    """Choose which snapshot dirs may be pruned.

    A directory is prunable only if **all** hold:

    * it is older than ``retention_days``
    * it is not among the ``min_keep`` most recent
    * its date is not referenced by a forward-validation capture
    * it is not denylisted

    Ordering matters: the count floor is applied to the newest-first list *before* the age
    test, so a stale tree (e.g. production down for a month) still keeps ``min_keep``.
    """
    if retention_days < 1:
        raise PruneRefusal("retention_days must be >= 1, got " + str(retention_days))
    if min_keep < 0:
        raise PruneRefusal("min_keep must be >= 0, got " + str(min_keep))

    protected = set(protected_dates)
    cutoff = today - timedelta(days=retention_days)
    ordered = sorted(snapshot_dirs, key=lambda p: p.name, reverse=True)
    candidates = ordered[min_keep:]

    prunable: list[Path] = []
    for path in candidates:
        if path.name in protected:
            continue
        if is_denylisted(path, base=base):
            continue
        try:
            dir_date = datetime.strptime(path.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if dir_date < cutoff:
            prunable.append(path)
    return prunable


def plan_prune(
    ctx: UserContext,
    *,
    paths: UserPaths,
    today: date | None = None,
    retention_days: int | None = None,
    min_keep: int | None = None,
) -> "list[Path]":
    """Build the prune plan for one tenant, refusing on unsafe configuration."""
    today = today or date.today()
    retention_days = retention_days if retention_days is not None else ctx.retention_days
    min_keep = min_keep if min_keep is not None else ctx.min_keep_snapshots

    captures = paths.artifacts_root / "forward_validation" / "captures.jsonl"
    protected = protected_dates_from_captures(captures)

    snapshot_dirs = list_snapshot_dirs(paths.snapshots_root)
    plan = select_prunable(
        snapshot_dirs,
        today=today,
        retention_days=retention_days,
        min_keep=min_keep,
        protected_dates=protected,
        base=paths.base,
    )

    # Final containment sweep: never return a path outside the tenant's own tree.
    for path in plan:
        if not paths.owns(path):
            raise PruneRefusal("refusing to prune " + str(path) + " which is outside tenant root " + str(paths.base))
    return plan


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description="Prune old per-tenant snapshots (dry-run by default).")
    parser.add_argument("--user", help="tenant id to prune (else BIOTECH_USER_ID)")
    parser.add_argument("--retention-days", type=int, default=None)
    parser.add_argument("--min-keep", type=int, default=None)
    parser.add_argument("--apply", action="store_true", help="actually delete (default: dry run)")
    parser.add_argument("--as-of", default=None, help="treat this date as today (YYYY-MM-DD)")
    args = parser.parse_args(argv)

    ctx = require_user_context(args.user)
    paths = for_user(ctx)
    today = datetime.strptime(args.as_of, "%Y-%m-%d").date() if args.as_of else date.today()

    plan = plan_prune(
        ctx,
        paths=paths,
        today=today,
        retention_days=args.retention_days,
        min_keep=args.min_keep,
    )

    mode = "APPLY" if args.apply else "DRY-RUN"
    print("prune_user_data [" + mode + "] tenant=" + ctx.user_id + " root=" + str(paths.base))
    print("  shared caches never pruned: " + ", ".join(SHARED_CACHE_DIRS))
    if not plan:
        print("  nothing to prune")
        return 0

    total = 0
    for path in plan:
        print("  " + ("delete " if args.apply else "would delete ") + str(path))
        if args.apply:
            shutil.rmtree(path)
        total += 1
    print("  " + str(total) + (" directories deleted" if args.apply else " directories would be deleted"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

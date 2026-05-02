#!/usr/bin/env python3
"""EES validation filters — diagnostic-side, no production-path touches.

Defines quarantine and universe-membership rules for forward-return validation
of expectation-error scores. Reads rankings.csv but does NOT modify any
producer code, per [freeze-architecture] and [no-formatter-churn] memos.

Three independent classifications per row:

1. is_quarantined(row) — priced_move_pct >= 500.0 indicates upstream
   straddle_price-as-dollars contamination (14/297 rows on 2026-04-30,
   ~4.7%). Quarantined rows are excluded from validation diagnostics that
   use priced_move_pct as a magnitude (Plot B implied-vs-realized scatter,
   Plot D calibration buckets). They are NOT excluded from broad IC tests
   on ees_v3_score, since EES scoring already happened upstream.

2. in_universe_a(row) — broad: ees_v3_score is non-null. Forward-return
   presence is checked separately by the joiner.

3. in_universe_b(row, as_of_date) — event-aligned: next_catalyst_date is
   within window forward of as_of_date. Computed directly because the
   catalyst_in_window boolean flag is dead system-wide (verified 0/297
   on every snapshot 2026-04-13 → 2026-04-30).

Promotion rule: decisive evidence comes from Universe B + non-quarantined.
Universe A is supporting evidence only.

Usage:
    python -m scripts.research.ees_validation_filters \
        data/snapshots/2026-04-30/rankings.csv

Or as a library:
    from scripts.research.ees_validation_filters import (
        classify_snapshot, is_quarantined, in_universe_a, in_universe_b
    )
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

PMV_QUARANTINE_THRESHOLD = 500.0

DEFAULT_CATALYST_WINDOW_CDAYS = 7


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() in ("nan", "null", "none", "na", "n/a"):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _safe_date(v) -> Optional[date]:
    if not v:
        return None
    s = str(v).strip()[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def is_quarantined(
    row: dict,
    threshold: float = PMV_QUARANTINE_THRESHOLD,
) -> bool:
    pmv = _safe_float(row.get("priced_move_pct"))
    if pmv is None:
        return False
    return pmv >= threshold


def in_universe_a(row: dict) -> bool:
    return _safe_float(row.get("ees_v3_score")) is not None


def in_universe_b(
    row: dict,
    as_of: date,
    max_calendar_days: int = DEFAULT_CATALYST_WINDOW_CDAYS,
) -> bool:
    cd = _safe_date(row.get("next_catalyst_date"))
    if cd is None or as_of is None:
        return False
    delta = (cd - as_of).days
    return 0 <= delta <= max_calendar_days


@dataclass
class FilterReport:
    snapshot: str
    n_total: int
    n_universe_a: int
    n_universe_b: int
    n_quarantined: int
    n_a_clean: int
    n_b_clean: int

    def as_row(self) -> dict:
        return {
            "snapshot": self.snapshot,
            "n_total": self.n_total,
            "n_universe_a": self.n_universe_a,
            "n_universe_b": self.n_universe_b,
            "n_quarantined": self.n_quarantined,
            "n_a_clean": self.n_a_clean,
            "n_b_clean": self.n_b_clean,
        }

    def __str__(self) -> str:
        return (
            f"{self.snapshot}: total={self.n_total}  "
            f"A={self.n_universe_a} (clean={self.n_a_clean})  "
            f"B={self.n_universe_b} (clean={self.n_b_clean})  "
            f"quarantined={self.n_quarantined}"
        )


def classify_rows(
    rows: Iterable[dict],
    as_of: date,
    pmv_threshold: float = PMV_QUARANTINE_THRESHOLD,
    catalyst_window_cdays: int = DEFAULT_CATALYST_WINDOW_CDAYS,
) -> dict:
    """Classify a list of rows against the three filters.

    Returns a dict with keys: universe_a, universe_b, quarantined, all.
    Each value is the list of rows matching that filter (or in 'all', every
    row). Rows can appear in both A and B; quarantined is independent.
    """
    rows_list = list(rows)
    out = {
        "all": rows_list,
        "universe_a": [r for r in rows_list if in_universe_a(r)],
        "universe_b": [r for r in rows_list if in_universe_b(r, as_of, catalyst_window_cdays)],
        "quarantined": [r for r in rows_list if is_quarantined(r, pmv_threshold)],
    }
    return out


def classify_snapshot(
    rankings_path: Path,
    as_of: Optional[date] = None,
    pmv_threshold: float = PMV_QUARANTINE_THRESHOLD,
    catalyst_window_cdays: int = DEFAULT_CATALYST_WINDOW_CDAYS,
) -> FilterReport:
    """Read a rankings.csv and return a filter classification report.

    If `as_of` is None, derive it from the parent directory name
    (data/snapshots/YYYY-MM-DD/rankings.csv).
    """
    rankings_path = Path(rankings_path)
    if as_of is None:
        as_of = _safe_date(rankings_path.parent.name)
        if as_of is None:
            raise ValueError(f"Cannot infer as_of date from path: {rankings_path}. " f"Pass as_of explicitly.")

    with rankings_path.open() as f:
        rows = list(csv.DictReader(f))

    classified = classify_rows(rows, as_of, pmv_threshold, catalyst_window_cdays)
    quarantined_set = {id(r) for r in classified["quarantined"]}
    n_a_clean = sum(1 for r in classified["universe_a"] if id(r) not in quarantined_set)
    n_b_clean = sum(1 for r in classified["universe_b"] if id(r) not in quarantined_set)

    return FilterReport(
        snapshot=as_of.isoformat(),
        n_total=len(classified["all"]),
        n_universe_a=len(classified["universe_a"]),
        n_universe_b=len(classified["universe_b"]),
        n_quarantined=len(classified["quarantined"]),
        n_a_clean=n_a_clean,
        n_b_clean=n_b_clean,
    )


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument(
        "rankings_path",
        type=Path,
        help="Path to data/snapshots/YYYY-MM-DD/rankings.csv",
    )
    p.add_argument(
        "--pmv-threshold",
        type=float,
        default=PMV_QUARANTINE_THRESHOLD,
        help=f"priced_move_pct quarantine cutoff (default {PMV_QUARANTINE_THRESHOLD})",
    )
    p.add_argument(
        "--catalyst-window",
        type=int,
        default=DEFAULT_CATALYST_WINDOW_CDAYS,
        help=f"Universe B forward window in calendar days "
        f"(default {DEFAULT_CATALYST_WINDOW_CDAYS}, ≈5 trading days)",
    )
    args = p.parse_args(argv)

    report = classify_snapshot(
        args.rankings_path,
        pmv_threshold=args.pmv_threshold,
        catalyst_window_cdays=args.catalyst_window,
    )
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())

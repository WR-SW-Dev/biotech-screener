"""Shared snapshot loader for research scripts.

Loads rankings from PIT v2 (preferred) or regular snapshots, tags the
source, and warns when sources mix within a single analysis run.

Usage:
    from research._snapshot_loader import SnapshotLoader

    loader = SnapshotLoader()
    ranked = loader.load_ranked("2025-06-30")
    eligible = loader.load_eligible("2025-06-30")
    loader.report_source_mix()  # call at end of analysis
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
PIT_V2_DIR = REPO_ROOT / "data" / "snapshots_pit_v2"
REGULAR_DIR = REPO_ROOT / "data" / "snapshots"

EXCLUDE = {"JBIO"}


class SnapshotLoader:
    """Loads snapshot data with source tracking and mix warnings."""

    def __init__(self):
        self._sources_used: dict[str, str] = {}  # date -> "pit_v2" or "regular"
        self._warned = False

    def _find_path(self, snap_date: str) -> tuple[str | None, str]:
        """Find rankings.csv path, preferring PIT v2. Returns (path, source_tag)."""
        pit_path = PIT_V2_DIR / snap_date / "rankings.csv"
        if pit_path.exists():
            return str(pit_path), "pit_v2"
        reg_path = REGULAR_DIR / snap_date / "rankings.csv"
        if reg_path.exists():
            return str(reg_path), "regular"
        return None, "missing"

    def _track_source(self, snap_date: str, source: str):
        self._sources_used[snap_date] = source

    def load_ranked(self, snap_date: str) -> list[str]:
        """Load full ranked ticker list (for buffer simulation)."""
        path, source = self._find_path(snap_date)
        if not path:
            return []
        self._track_source(snap_date, source)
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        ranked = [r for r in rows if r.get("actionable_rank") and r["actionable_rank"] not in ("", "NA", "None")]
        ranked.sort(key=lambda r: int(float(r["actionable_rank"])))
        return [r["ticker"] for r in ranked if r["ticker"] not in EXCLUDE]

    def load_eligible(self, snap_date: str) -> list[str]:
        """Load eligible ticker list."""
        path, source = self._find_path(snap_date)
        if not path:
            return []
        self._track_source(snap_date, source)
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        return [r["ticker"] for r in rows if r.get("eligible") == "1" and r["ticker"] not in EXCLUDE]

    def load_catalyst_days(self, snap_date: str) -> dict[str, float]:
        """Load catalyst_days for hysteresis simulation."""
        path, source = self._find_path(snap_date)
        if not path:
            return {}
        self._track_source(snap_date, source)
        result = {}
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                tk = row.get("ticker", "")
                cd = row.get("catalyst_days", "")
                if tk and cd and cd not in ("", "NA", "None"):
                    try:
                        result[tk] = float(cd)
                    except (ValueError, TypeError):
                        pass
        return result

    @property
    def is_mixed(self) -> bool:
        """True if both pit_v2 and regular sources were used."""
        sources = set(self._sources_used.values())
        return "pit_v2" in sources and "regular" in sources

    @property
    def source_summary(self) -> dict[str, int]:
        """Count of dates by source."""
        counts: dict[str, int] = {}
        for src in self._sources_used.values():
            counts[src] = counts.get(src, 0) + 1
        return counts

    def report_source_mix(self):
        """Log a warning if sources were mixed. Call at end of analysis."""
        counts = self.source_summary
        if self.is_mixed:
            pit_n = counts.get("pit_v2", 0)
            reg_n = counts.get("regular", 0)
            logger.warning(
                "SNAPSHOT SOURCE MIX: %d pit_v2 + %d regular dates used in same analysis. "
                "Results may show artificial discontinuities at source boundaries.",
                pit_n,
                reg_n,
            )
            # Find the boundary dates
            pit_dates = sorted(d for d, s in self._sources_used.items() if s == "pit_v2")
            reg_dates = sorted(d for d, s in self._sources_used.items() if s == "regular")
            if pit_dates and reg_dates:
                logger.warning(
                    "  PIT v2 range: %s to %s (%d dates)",
                    pit_dates[0],
                    pit_dates[-1],
                    len(pit_dates),
                )
                logger.warning(
                    "  Regular range: %s to %s (%d dates)",
                    reg_dates[0],
                    reg_dates[-1],
                    len(reg_dates),
                )
            print(
                f"WARNING: Snapshot sources mixed — {pit_n} pit_v2 + {reg_n} regular. "
                f"Results may show artificial discontinuities."
            )
        else:
            source = list(counts.keys())[0] if counts else "none"
            n = sum(counts.values())
            logger.info("Snapshot source: %s (%d dates, no mixing)", source, n)

"""Regulatory coverage telemetry for snapshot sidecar output.

Computes and tracks regulatory event coverage across snapshots:
  - Total flagged count and % of eligible universe
  - Breakdown by event_type, source, confidence
  - Delta vs prior snapshot (added/dropped tickers)
  - Source contribution breakdown (which sources are driving coverage)

Output: JSON sidecar written alongside rankings.csv in each snapshot.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

TELEMETRY_SCHEMA = "regulatory_coverage_telemetry.v1"


def extract_regulatory_flags(
    csv_rows: List[Dict[str, str]],
) -> Tuple[int, int, List[Dict[str, str]]]:
    """Extract regulatory coverage from rankings CSV rows.

    Returns (n_eligible, n_flagged, flagged_details).
    """
    eligible = [r for r in csv_rows if r.get("eligible") == "1"]
    flagged = []
    for r in eligible:
        if r.get("has_regulatory_upcoming_180d") == "1":
            flagged.append(
                {
                    "ticker": r.get("ticker", ""),
                    "regulatory_days": r.get("regulatory_days", ""),
                    "regulatory_event_type": r.get("regulatory_event_type", ""),
                    "regulatory_confidence": r.get("regulatory_confidence", ""),
                }
            )
    flagged.sort(key=lambda x: int(x["regulatory_days"]) if x["regulatory_days"] else 999)
    return len(eligible), len(flagged), flagged


def build_coverage_breakdown(
    flagged: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Build coverage breakdown by event_type, confidence."""
    by_type: Dict[str, int] = {}
    by_conf: Dict[str, int] = {}
    by_bucket: Dict[str, int] = {"0_30d": 0, "31_90d": 0, "91_180d": 0}

    for f in flagged:
        et = f.get("regulatory_event_type", "UNKNOWN")
        by_type[et] = by_type.get(et, 0) + 1

        conf = f.get("regulatory_confidence", "")
        if conf:
            by_conf[conf] = by_conf.get(conf, 0) + 1

        try:
            days = int(f.get("regulatory_days", "999"))
        except (ValueError, TypeError):
            days = 999
        if days <= 30:
            by_bucket["0_30d"] += 1
        elif days <= 90:
            by_bucket["31_90d"] += 1
        elif days <= 180:
            by_bucket["91_180d"] += 1

    return {
        "by_event_type": by_type,
        "by_confidence": by_conf,
        "by_proximity_bucket": by_bucket,
    }


def compute_delta(
    current_tickers: Set[str],
    prior_tickers: Set[str],
    current_n_eligible: int,
    prior_n_eligible: int,
) -> Dict[str, Any]:
    """Compute coverage delta between current and prior snapshot."""
    added = current_tickers - prior_tickers
    dropped = prior_tickers - current_tickers

    current_pct = round(len(current_tickers) / max(current_n_eligible, 1) * 100, 1)
    prior_pct = round(len(prior_tickers) / max(prior_n_eligible, 1) * 100, 1)

    return {
        "prior_count": len(prior_tickers),
        "current_count": len(current_tickers),
        "prior_pct": prior_pct,
        "current_pct": current_pct,
        "delta_count": len(current_tickers) - len(prior_tickers),
        "delta_pct": round(current_pct - prior_pct, 1),
        "added": sorted(added),
        "dropped": sorted(dropped),
    }


def load_prior_telemetry(snap_dir: Path) -> Optional[Dict[str, Any]]:
    """Load prior regulatory_coverage.json from a snapshot directory."""
    path = snap_dir / "regulatory_coverage.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def find_prior_snapshot(snapshots_dir: Path, current_date: str) -> Optional[Path]:
    """Find the most recent snapshot before current_date."""
    if not snapshots_dir.exists():
        return None
    snaps = sorted(
        [d for d in snapshots_dir.iterdir() if d.is_dir() and d.name < current_date],
    )
    return snaps[-1] if snaps else None


def build_telemetry(
    csv_rows: List[Dict[str, str]],
    as_of_date: str,
    snapshots_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build complete regulatory coverage telemetry.

    Parameters
    ----------
    csv_rows : rankings CSV rows (list of dicts)
    as_of_date : YYYY-MM-DD
    snapshots_dir : parent directory containing dated snapshot subdirs
        (for computing delta vs prior)
    """
    n_eligible, n_flagged, flagged = extract_regulatory_flags(csv_rows)
    breakdown = build_coverage_breakdown(flagged)
    current_tickers = {f["ticker"] for f in flagged}

    telemetry: Dict[str, Any] = {
        "schema": TELEMETRY_SCHEMA,
        "as_of_date": as_of_date,
        "n_eligible": n_eligible,
        "n_flagged": n_flagged,
        "coverage_pct": round(n_flagged / max(n_eligible, 1) * 100, 1),
        "flagged_tickers": sorted(current_tickers),
        "breakdown": breakdown,
    }

    # Delta vs prior
    if snapshots_dir:
        prior_snap = find_prior_snapshot(snapshots_dir, as_of_date)
        if prior_snap:
            prior_tel = load_prior_telemetry(prior_snap)
            if prior_tel:
                prior_tickers = set(prior_tel.get("flagged_tickers", []))
                prior_n_eligible = prior_tel.get("n_eligible", 0)
                telemetry["delta"] = compute_delta(
                    current_tickers,
                    prior_tickers,
                    n_eligible,
                    prior_n_eligible,
                )
                telemetry["delta"]["prior_snapshot"] = prior_snap.name

    return telemetry


def write_telemetry(
    snap_path: Path,
    csv_rows: List[Dict[str, str]],
    as_of_date: str,
    snapshots_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Write regulatory_coverage.json sidecar into snapshot directory.

    Returns path to written file, or None on error.
    """
    try:
        telemetry = build_telemetry(csv_rows, as_of_date, snapshots_dir)
        out_path = Path(snap_path) / "regulatory_coverage.json"
        out_path.write_text(
            json.dumps(telemetry, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        logger.info(
            "Regulatory coverage: %d/%d (%.1f%%) — %s",
            telemetry["n_flagged"],
            telemetry["n_eligible"],
            telemetry["coverage_pct"],
            out_path,
        )
        return out_path
    except Exception as exc:
        logger.warning("Regulatory coverage telemetry failed: %s", exc)
        return None

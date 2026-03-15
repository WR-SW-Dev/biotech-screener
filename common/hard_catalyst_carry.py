"""Hard catalyst source forward-carry (Spec 011).

Once a hard catalyst source (SEC_8K_FILING, etc.) is observed for a ticker,
carry it forward into subsequent snapshots until the event date passes.
This prevents hard sources from intermittently reverting to CTGOV_CALENDAR
due to transient SEC fetch windows.

State persisted in data/state/hard_catalyst_carry.json.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List

from common.hard_catalyst import classify_hard_catalyst

logger = logging.getLogger(__name__)

# Sources that qualify for forward-carry
_HARD_CARRY_SOURCES = frozenset(
    {
        "SEC_8K_FILING",
        "SEC_10Q_FILING",
        "SEC_10K_FILING",
        "SEC_6K_FILING",
        "FDA_PDUFA_DATE",
        "COMPANY_GUIDANCE",
    }
)

# Soft sources that can be overridden by a carried hard source
_SOFT_SOURCES = frozenset(
    {
        "CTGOV_CALENDAR",
        "CTGOV_PCD_FAR",
        "",
    }
)

DEFAULT_STATE_PATH = Path("data") / "state" / "hard_catalyst_carry.json"


def load_carry_state(state_path: Path = DEFAULT_STATE_PATH) -> Dict[str, Dict[str, Any]]:
    """Load the carry state file. Returns empty dict if missing."""
    if not state_path.exists():
        return {}
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read carry state %s: %s", state_path, e)
        return {}


def save_carry_state(
    state: Dict[str, Dict[str, Any]],
    state_path: Path = DEFAULT_STATE_PATH,
) -> None:
    """Write carry state to disk."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)
        f.write("\n")


def _estimate_event_date(catalyst_days: float, as_of_date: date) -> str:
    """Estimate the event date from catalyst_days + as_of_date."""
    try:
        days = int(float(catalyst_days))
        return (as_of_date + timedelta(days=days)).isoformat()
    except (ValueError, TypeError):
        # Default to 90 days out if catalyst_days is missing
        return (as_of_date + timedelta(days=90)).isoformat()


def forward_carry_hard_catalysts(
    csv_rows: List[dict],
    as_of_date: date,
    state_path: Path = DEFAULT_STATE_PATH,
) -> int:
    """Apply forward-carry of hard catalyst sources to csv_rows (in-place).

    Returns number of rows where a carry was applied.
    """
    state = load_carry_state(state_path)
    carry_count = 0

    # Phase 1: Expire entries where event date has passed
    expired = []
    for ticker, entry in list(state.items()):
        est = entry.get("estimated_event_date", "")
        if est and est < as_of_date.isoformat():
            expired.append(ticker)
            del state[ticker]
    if expired:
        logger.info("[CARRY] Expired %d entries: %s", len(expired), ", ".join(expired))

    # Phase 2: Apply carry to rows with soft sources
    for row in csv_rows:
        ticker = row.get("ticker", "")
        if not ticker:
            continue

        current_source = row.get("catalyst_source", "")
        current_event_type = row.get("catalyst_event_type", "")

        # If today's run already has a hard source, don't override
        hc = classify_hard_catalyst(current_event_type, current_source)
        if hc["is_hard_catalyst"]:
            continue

        # Check if we have a carry entry for this ticker
        if ticker not in state:
            continue

        entry = state[ticker]
        carried_source = entry.get("catalyst_source", "")
        carried_event_type = entry.get("catalyst_event_type", "")

        # Only override soft sources
        if current_source not in _SOFT_SOURCES:
            continue

        # Apply carry — source, event type, and catalyst_days from estimated date
        row["catalyst_source"] = carried_source
        row["catalyst_event_type"] = carried_event_type
        row["is_hard_catalyst"] = "1"

        # Override catalyst_days if the carry has a better estimate
        est_date = entry.get("estimated_event_date", "")
        if est_date:
            try:
                est = date.fromisoformat(est_date)
                carried_days = (est - as_of_date).days
                if carried_days > 0:
                    current_days_str = row.get("catalyst_days", "")
                    try:
                        current_days = int(float(current_days_str)) if current_days_str else 9999
                    except (ValueError, TypeError):
                        current_days = 9999
                    # Only override if the current catalyst_days looks wrong
                    # (e.g. far-future CTGov date when carry has a near-term date)
                    if carried_days < current_days:
                        row["catalyst_days"] = str(carried_days)
            except (ValueError, TypeError):
                pass
        carry_count += 1
        logger.info(
            "[CARRY] %s: %s from %s (first seen %s)",
            ticker,
            carried_event_type,
            carried_source,
            entry.get("first_seen_date", "?"),
        )

    # Phase 3: Learn new hard sources from this run
    new_entries = 0
    for row in csv_rows:
        ticker = row.get("ticker", "")
        if not ticker:
            continue

        source = row.get("catalyst_source", "")
        event_type = row.get("catalyst_event_type", "")

        if source not in _HARD_CARRY_SOURCES:
            continue

        hc = classify_hard_catalyst(event_type, source)
        if not hc["is_hard_catalyst"]:
            continue

        # Only add if not already in state (or if state has a different/older source)
        if ticker not in state:
            cat_days = row.get("catalyst_days", "")
            state[ticker] = {
                "catalyst_event_type": event_type,
                "catalyst_source": source,
                "catalyst_days_at_first_seen": cat_days,
                "first_seen_date": as_of_date.isoformat(),
                "estimated_event_date": _estimate_event_date(cat_days, as_of_date),
            }
            new_entries += 1

    if new_entries:
        logger.info("[CARRY] Learned %d new hard sources", new_entries)

    # Save updated state
    save_carry_state(state, state_path)
    logger.info(
        "[CARRY] State: %d entries, %d carried, %d expired, %d new",
        len(state),
        carry_count,
        len(expired),
        new_entries,
    )

    return carry_count

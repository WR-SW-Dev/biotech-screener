"""Unified Event Store — single interface to all catalyst event sources.

Abstracts over the 6 fragmented sources that currently feed the catalyst
graph (PDUFA dates, catalyst_events, event ledger, CRT resolutions,
manual overrides, trial_records phase enrichment) into one query interface.

This is a read-only facade over existing data. It does NOT replace
the existing loaders — it wraps them into a uniform API for new consumers.

Usage:
    from event_ev.event_store import EventStore

    store = EventStore(prod_data=Path("production_data"), data_dir=Path("data"))
    store.load(as_of=date(2026, 4, 9))

    events = store.get_ticker_events("TVTX")
    resolved = store.get_resolved_events()
    phase = store.get_ticker_phase("BEAM")
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EventStore:
    """Unified read-only interface to all catalyst event data."""

    def __init__(
        self,
        prod_data: Optional[Path] = None,
        data_dir: Optional[Path] = None,
    ):
        self._prod_data = prod_data or Path("production_data")
        self._data_dir = data_dir or Path("data")
        self._graph = None
        self._ticker_phases: Dict[str, str] = {}
        self._resolutions: List[Dict[str, Any]] = []
        self._loaded = False

    def load(self, as_of: date) -> None:
        """Load all event sources for a given as-of date."""
        from .loaders import _build_ticker_phase_map, load_catalyst_graph

        self._graph = load_catalyst_graph(as_of, self._prod_data, self._data_dir)

        # Load phase map from trial records
        trial_path = self._prod_data / "trial_records.json"
        if trial_path.exists():
            try:
                trials = json.loads(trial_path.read_text())
                self._ticker_phases = _build_ticker_phase_map(trials)
            except (json.JSONDecodeError, OSError):
                pass

        # Load resolutions
        res_dir = self._data_dir / "snapshots" / "resolutions"
        if res_dir.exists():
            for month_dir in res_dir.iterdir():
                if not month_dir.is_dir():
                    continue
                for f in month_dir.glob("*.json"):
                    if f.name.startswith(("calibration", "manual", "watchlist")):
                        continue
                    try:
                        rec = json.loads(f.read_text())
                        if isinstance(rec, dict) and "ticker" in rec:
                            self._resolutions.append(rec)
                    except (json.JSONDecodeError, OSError):
                        pass

        self._loaded = True
        logger.info(
            "EventStore loaded: %d graph nodes, %d ticker phases, %d resolutions",
            self._graph.node_count if self._graph else 0,
            len(self._ticker_phases),
            len(self._resolutions),
        )

    @property
    def node_count(self) -> int:
        return self._graph.node_count if self._graph else 0

    def get_ticker_events(self, ticker: str) -> List[Any]:
        """Get all catalyst nodes for a ticker."""
        if not self._graph:
            return []
        return self._graph.get_ticker_nodes(ticker)

    def get_ticker_phase(self, ticker: str) -> str:
        """Get the lead phase for a ticker."""
        return self._ticker_phases.get(ticker.upper(), "unknown")

    def get_resolved_events(
        self,
        outcome_filter: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get CRT resolution records, optionally filtered by outcome."""
        if outcome_filter:
            return [r for r in self._resolutions if r.get("outcome") in outcome_filter]
        return list(self._resolutions)

    def get_resolution_for_ticker(
        self,
        ticker: str,
        catalyst_date: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get the most recent resolution for a ticker."""
        matches = [r for r in self._resolutions if r.get("ticker", "").upper() == ticker.upper()]
        if catalyst_date:
            matches = [r for r in matches if r.get("catalyst_date") == catalyst_date]
        if not matches:
            return None
        return max(matches, key=lambda r: r.get("resolution_date", ""))

    def summary(self) -> Dict[str, Any]:
        """Return summary statistics."""
        from collections import Counter

        phase_dist = Counter(self._ticker_phases.values())
        outcome_dist = Counter(r.get("outcome", "?") for r in self._resolutions)

        return {
            "graph_nodes": self._graph.node_count if self._graph else 0,
            "tickers_with_phase": len(self._ticker_phases),
            "phase_distribution": dict(phase_dist),
            "resolutions": len(self._resolutions),
            "outcome_distribution": dict(outcome_dist),
        }

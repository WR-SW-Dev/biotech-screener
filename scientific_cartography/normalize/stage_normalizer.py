"""Clinical stage normalization."""

from typing import Optional


class StageNormalizer:
    """Normalize clinical stage strings to canonical stages.

    Stage precedence:
    - approved > filed > phase3 > phase2b > phase2 > phase1/2 > phase1 > preclinical > unknown

    Rules:
    - FDA approved product evidence sets stage to 'approved'
    - Explicit company stage can set stage if sourced
    - CTGov phase can set stage
    - Multiple trials: use highest active stage
    - Terminated-only programs do not become active
    - All trials inactive → discontinued only if explicit company evidence supports it
    """

    # Stage hierarchy (higher number = more advanced)
    STAGE_HIERARCHY = {
        "preclinical": 0,
        "phase1": 1,
        "phase1/2": 1.5,
        "phase2": 2,
        "phase2b": 2.5,
        "phase3": 3,
        "filed": 4,
        "approved": 5,
        "discontinued": -1,  # Terminal state, not ordered in hierarchy
        None: -99,
    }

    # Normalization mappings
    STAGE_ALIASES = {
        "preclinical": ["preclinical", "in vitro", "nonclinical", "animal"],
        "phase1": ["phase1", "phase 1", "i", "early phase 1"],
        "phase1/2": ["phase1/2", "phase 1/2", "i/ii", "phase1b"],
        "phase2": ["phase2", "phase 2", "ii", "phase2a"],
        "phase2b": ["phase2b", "phase 2b", "iib"],
        "phase3": ["phase3", "phase 3", "iii"],
        "filed": [
            "filed",
            "bla",
            "nda",
            "anda",
            "under review",
            "submitted",
        ],
        "approved": [
            "approved",
            "fda approved",
            "marketed",
            "commercial",
            "active",
        ],
    }

    def __init__(self):
        """Initialize stage normalizer."""
        self._create_lookup_map()

    def _create_lookup_map(self) -> None:
        """Create lowercase lookup map for aliases."""
        self.lookup_map: dict[str, str] = {}
        for canonical, aliases in self.STAGE_ALIASES.items():
            for alias in aliases:
                self.lookup_map[alias.lower().strip()] = canonical

    def normalize(self, raw_stage: Optional[str]) -> Optional[str]:
        """Normalize a raw stage string to canonical form.

        Args:
            raw_stage: Raw stage string (may be None).

        Returns:
            Canonical stage or None if input is None/unmapped.
        """
        if raw_stage is None:
            return None

        normalized = raw_stage.lower().strip()
        return self.lookup_map.get(normalized, None)

    def select_highest_stage(self, stages: list[Optional[str]]) -> Optional[str]:
        """Select the highest stage from a list.

        Uses stage hierarchy: approved > filed > phase3 > ... > preclinical > unknown

        Args:
            stages: List of stage strings (may contain None).

        Returns:
            Highest stage from the list, or None if all are None.
        """
        if not stages:
            return None

        # Filter out None values
        valid_stages = [s for s in stages if s is not None]
        if not valid_stages:
            return None

        # Find highest by hierarchy value
        return max(valid_stages, key=lambda s: self.STAGE_HIERARCHY.get(s, -99))

    def is_active_stage(self, stage: Optional[str]) -> bool:
        """Check if a stage represents an active program.

        Active stages: preclinical, phase1 through phase3, filed, approved
        Inactive: discontinued, None

        Args:
            stage: Canonical stage string.

        Returns:
            True if stage is active, False otherwise.
        """
        if stage is None or stage == "discontinued":
            return False
        return stage in self.STAGE_HIERARCHY and self.STAGE_HIERARCHY[stage] >= 0

    def get_hierarchy_rank(self, stage: Optional[str]) -> float:
        """Get numeric rank for a stage (higher = more advanced).

        Args:
            stage: Canonical stage string.

        Returns:
            Hierarchy rank, or -99 if unknown.
        """
        return self.STAGE_HIERARCHY.get(stage, -99)

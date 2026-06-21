"""Export map index from programs, clusters, and features."""

from collections import defaultdict
from pathlib import Path

from scientific_cartography.io import write_json
from scientific_cartography.schemas.cluster_schema import CompetitiveClusterRecord
from scientific_cartography.schemas.landscape_feature_schema import LandscapeFeatureRecord
from scientific_cartography.schemas.program_schema import ProgramRecord


class MapIndexExporter:
    """Export a diagnostic map index from cartography records."""

    def __init__(self, as_of_date: str = ""):
        """Initialize exporter.

        Args:
            as_of_date: Date for index snapshot (YYYY-MM-DD).
        """
        self.as_of_date = as_of_date

    def build_index(
        self,
        programs: list[ProgramRecord],
        clusters: list[CompetitiveClusterRecord],
        features: list[LandscapeFeatureRecord],
    ) -> dict:
        """Build map index from records.

        Args:
            programs: List of ProgramRecords.
            clusters: List of CompetitiveClusterRecords.
            features: List of LandscapeFeatureRecords.

        Returns:
            Index dict suitable for JSON serialization.
        """
        # Aggregate disease-level data
        disease_map = self._build_disease_map(programs, clusters, features)

        # Count public tickers and programs by mechanism knowledge
        ticker_set = set()
        known_mech_count = 0
        unknown_mech_count = 0

        for program in programs:
            if program.ticker:
                ticker_set.add(program.ticker)
            if program.mechanism_class and program.mechanism_class != "unknown":
                known_mech_count += 1
            else:
                unknown_mech_count += 1

        # Build disease list (sorted alphabetically, unknown last)
        diseases_list = []
        for disease_key in sorted(disease_map.keys()):
            disease_data = disease_map[disease_key]
            disease_data["disease_id"] = disease_data.get("disease_id") or "unknown"
            disease_data["disease_name"] = disease_data.get("disease_name") or "unknown"
            diseases_list.append(disease_data)

        # Sort: known diseases first, unknown last
        diseases_list.sort(key=lambda d: (d["disease_name"] == "unknown", d["disease_name"] or ""))

        index = {
            "as_of_date": self.as_of_date,
            "artifact_type": "scientific_cartography_map_index",
            "governance": {
                "classification": "READ_ONLY_DIAGNOSTIC",
                "production_wiring": False,
                "ranker_change": False,
                "selector_change": False,
                "sizing_change": False,
                "final_score_change": False,
            },
            "counts": {
                "program_records": len(programs),
                "competitive_clusters": len(clusters),
                "landscape_features": len(features),
                "disease_count": len([d for d in disease_map.keys() if d != "unknown"]),
                "ticker_count": len(ticker_set),
                "known_mechanism_programs": known_mech_count,
                "unknown_mechanism_programs": unknown_mech_count,
            },
            "diseases": diseases_list,
            "warnings": self._collect_warnings(disease_map),
        }

        return index

    def _build_disease_map(
        self,
        programs: list[ProgramRecord],
        clusters: list[CompetitiveClusterRecord],
        features: list[LandscapeFeatureRecord],
    ) -> dict:
        """Build disease-level aggregation map.

        Args:
            programs: Programs.
            clusters: Clusters.
            features: Features.

        Returns:
            Dict mapping disease_id to disease data.
        """
        disease_map = defaultdict(
            lambda: {
                "disease_id": None,
                "disease_name": None,
                "therapeutic_area": None,
                "program_count": 0,
                "cluster_count": 0,
                "feature_count": 0,
                "public_tickers": set(),
                "known_mechanism_count": 0,
                "unknown_mechanism_count": 0,
                "stage_distribution": {
                    "approved": 0,
                    "filed": 0,
                    "phase3": 0,
                    "phase2": 0,
                    "phase1": 0,
                    "preclinical": 0,
                    "discontinued": 0,
                    "unknown": 0,
                },
                "source_refs": set(),
                "warnings": set(),
            }
        )

        # Aggregate programs
        for program in programs:
            disease_key = program.disease_id or program.disease_name or "unknown"
            entry = disease_map[disease_key]
            entry["disease_id"] = program.disease_id or entry["disease_id"]
            entry["disease_name"] = program.disease_name or entry["disease_name"]
            entry["therapeutic_area"] = program.therapeutic_area or entry["therapeutic_area"]
            entry["program_count"] += 1

            if program.ticker:
                entry["public_tickers"].add(program.ticker)

            if program.mechanism_class and program.mechanism_class != "unknown":
                entry["known_mechanism_count"] += 1
            else:
                entry["unknown_mechanism_count"] += 1

            # Track source refs
            if program.source_refs:
                entry["source_refs"].update(program.source_refs)

        # Aggregate clusters
        for cluster in clusters:
            disease_key = cluster.disease_id or cluster.disease_name or "unknown"
            entry = disease_map[disease_key]
            entry["disease_id"] = cluster.disease_id or entry["disease_id"]
            entry["disease_name"] = cluster.disease_name or entry["disease_name"]
            entry["therapeutic_area"] = cluster.therapeutic_area or entry["therapeutic_area"]
            entry["cluster_count"] += 1

            # Stage distribution
            entry["stage_distribution"]["approved"] += cluster.approved_count
            entry["stage_distribution"]["filed"] += cluster.filed_count
            entry["stage_distribution"]["phase3"] += cluster.phase3_count
            entry["stage_distribution"]["phase2"] += cluster.phase2_count
            entry["stage_distribution"]["phase1"] += cluster.phase1_count
            entry["stage_distribution"]["preclinical"] += cluster.preclinical_count
            entry["stage_distribution"]["discontinued"] += cluster.discontinued_count
            entry["stage_distribution"]["unknown"] += cluster.unknown_stage_count

            # Track source refs
            if cluster.source_refs:
                entry["source_refs"].update(cluster.source_refs)

        # Aggregate features
        for feature in features:
            disease_key = feature.disease_id or feature.disease_name or "unknown"
            entry = disease_map[disease_key]
            entry["feature_count"] += 1

            # Track source refs
            if feature.source_refs:
                entry["source_refs"].update(feature.source_refs)

        # Convert sets to sorted lists
        for disease_key in disease_map:
            entry = disease_map[disease_key]
            entry["public_tickers"] = sorted(entry["public_tickers"])
            entry["source_refs_count"] = len(entry["source_refs"])
            del entry["source_refs"]  # Remove set, keep count
            del entry["warnings"]  # Remove warnings set

        return dict(disease_map)

    def _collect_warnings(self, disease_map: dict) -> list[str]:
        """Collect warnings from disease map.

        Args:
            disease_map: Disease aggregation map.

        Returns:
            Sorted list of unique warnings.
        """
        warnings = set()
        if "unknown" in disease_map:
            warnings.add("unknown_disease_present")
        return sorted(warnings)

    def write_index(self, index: dict, output_path: Path) -> None:
        """Write index to JSON file.

        Args:
            index: Index dict.
            output_path: Path to output file.
        """
        write_json(output_path, index)

"""Export disease-level diagnostic maps."""

from collections import defaultdict
from pathlib import Path

from scientific_cartography.io import atomic_write_text, write_json
from scientific_cartography.schemas.cluster_schema import CompetitiveClusterRecord
from scientific_cartography.schemas.landscape_feature_schema import LandscapeFeatureRecord
from scientific_cartography.schemas.program_schema import ProgramRecord


class DiseaseMapExporter:
    """Export disease-level diagnostic summaries."""

    def __init__(self, as_of_date: str = ""):
        """Initialize exporter.

        Args:
            as_of_date: Date for export snapshot (YYYY-MM-DD).
        """
        self.as_of_date = as_of_date

    def build_disease_summary(
        self,
        programs: list[ProgramRecord],
        clusters: list[CompetitiveClusterRecord],
        features: list[LandscapeFeatureRecord],
    ) -> dict:
        """Build disease-level summary.

        Args:
            programs: Programs.
            clusters: Clusters.
            features: Features.

        Returns:
            Disease summary dict.
        """
        disease_summaries = self._aggregate_by_disease(programs, clusters, features)

        # Sort deterministically: known first, unknown last
        sorted_diseases = sorted(
            disease_summaries.values(),
            key=lambda d: (d["disease_name"] == "unknown", d["disease_name"]),
        )

        return {
            "as_of_date": self.as_of_date,
            "artifact_type": "scientific_cartography_disease_summary",
            "diseases": sorted_diseases,
            "warnings": [],
        }

    def _aggregate_by_disease(
        self,
        programs: list[ProgramRecord],
        clusters: list[CompetitiveClusterRecord],
        features: list[LandscapeFeatureRecord],
    ) -> dict:
        """Aggregate data by disease.

        Args:
            programs: Programs.
            clusters: Clusters.
            features: Features.

        Returns:
            Dict mapping disease_id to summary.
        """
        disease_map = defaultdict(
            lambda: {
                "disease_id": "unknown",
                "disease_name": "unknown",
                "therapeutic_area": None,
                "program_count": 0,
                "cluster_count": 0,
                "feature_count": 0,
                "public_tickers": set(),
                "asset_names": set(),
                "mechanism_classes": set(),
                "modalities": set(),
                "targets": set(),
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
                "features_with_mechanism_crowding": 0,
                "features_with_stage_crowding": 0,
                "features_with_white_space": 0,
                "source_refs": set(),
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
            if program.asset_name:
                entry["asset_names"].add(program.asset_name)
            if program.mechanism_class:
                entry["mechanism_classes"].add(program.mechanism_class)
            if program.modality:
                entry["modalities"].add(program.modality)
            if program.target:
                entry["targets"].add(program.target)

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

            # Add mechanism/modality/targets from cluster
            if cluster.mechanism_class:
                entry["mechanism_classes"].add(cluster.mechanism_class)
            if cluster.modality:
                entry["modalities"].add(cluster.modality)
            if cluster.target:
                entry["targets"].add(cluster.target)

            if cluster.source_refs:
                entry["source_refs"].update(cluster.source_refs)

        # Aggregate features
        for feature in features:
            disease_key = feature.disease_id or feature.disease_name or "unknown"
            entry = disease_map[disease_key]
            entry["feature_count"] += 1

            if feature.mechanism_crowding_score is not None:
                entry["features_with_mechanism_crowding"] += 1
            if feature.stage_crowding_score is not None:
                entry["features_with_stage_crowding"] += 1
            if feature.white_space_score is not None:
                entry["features_with_white_space"] += 1

            if feature.source_refs:
                entry["source_refs"].update(feature.source_refs)

        # Convert sets to sorted lists
        for disease_key in disease_map:
            entry = disease_map[disease_key]
            entry["public_tickers"] = sorted(entry["public_tickers"])
            entry["asset_names"] = sorted(entry["asset_names"])
            entry["mechanism_classes"] = sorted(entry["mechanism_classes"])
            entry["modalities"] = sorted(entry["modalities"])
            entry["targets"] = sorted(entry["targets"])
            entry["diagnostic_feature_coverage"] = {
                "features_with_mechanism_crowding_score": entry["features_with_mechanism_crowding"],
                "features_with_stage_crowding_score": entry["features_with_stage_crowding"],
                "features_with_white_space_score": entry["features_with_white_space"],
            }
            del entry["features_with_mechanism_crowding"]
            del entry["features_with_stage_crowding"]
            del entry["features_with_white_space"]
            entry["source_refs_count"] = len(entry["source_refs"])
            del entry["source_refs"]

        return disease_map

    def write_disease_summary(self, summary: dict, output_path: Path) -> None:
        """Write disease summary to JSON.

        Args:
            summary: Summary dict.
            output_path: Output path.
        """
        write_json(output_path, summary)

    def write_disease_summary_markdown(self, summary: dict, output_path: Path) -> None:
        """Write disease summary to Markdown.

        Args:
            summary: Summary dict.
            output_path: Output path.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            "# Scientific Cartography Disease Map Summary",
            "",
            "## Metadata",
            "",
            f"- **as_of_date**: {summary['as_of_date']}",
            "- **artifact_type**: scientific_cartography_disease_summary",
            "- **governance**: READ_ONLY_DIAGNOSTIC",
            "- **production_wiring**: false",
            "- **ranker_change**: false",
            "- **selector_change**: false",
            "- **sizing_change**: false",
            "- **final_score_change**: false",
            "",
            "## Coverage Overview",
            "",
            "| Metric | Count |",
            "|---|---:|",
        ]

        # Count totals
        total_programs = sum(d.get("program_count", 0) for d in summary.get("diseases", []))
        total_clusters = sum(d.get("cluster_count", 0) for d in summary.get("diseases", []))
        total_features = sum(d.get("feature_count", 0) for d in summary.get("diseases", []))
        total_tickers = len(set(t for d in summary.get("diseases", []) for t in d.get("public_tickers", [])))

        lines.extend(
            [
                f"| Program records | {total_programs} |",
                f"| Competitive clusters | {total_clusters} |",
                f"| Landscape feature records | {total_features} |",
                f"| Diseases | {len(summary.get('diseases', []))} |",
                f"| Public tickers | {total_tickers} |",
                "",
            ]
        )

        # Disease summaries
        lines.append("## Disease Summaries")
        lines.append("")

        for disease in summary.get("diseases", []):
            lines.extend(
                [
                    f"### {disease.get('disease_name', 'Unknown')}",
                    "",
                    "| Metric | Count |",
                    "|---|---:|",
                    f"| Programs | {disease.get('program_count', 0)} |",
                    f"| Clusters | {disease.get('cluster_count', 0)} |",
                    f"| Features | {disease.get('feature_count', 0)} |",
                    f"| Known mechanisms | {len([m for m in disease.get('mechanism_classes', []) if m != 'unknown'])} |",
                    f"| Unknown mechanisms | {1 if 'unknown' in disease.get('mechanism_classes', []) else 0} |",
                    f"| Source references | {disease.get('source_refs_count', 0)} |",
                    "",
                ]
            )

            # Stage distribution
            if disease.get("stage_distribution"):
                lines.extend(
                    [
                        "#### Stage Distribution",
                        "",
                        "| Stage | Count |",
                        "|---|---:|",
                    ]
                )
                for stage, count in disease["stage_distribution"].items():
                    lines.append(f"| {stage} | {count} |")
                lines.append("")

            # Mechanism classes
            if disease.get("mechanism_classes"):
                lines.extend(
                    [
                        "#### Mechanism Classes",
                        "",
                    ]
                )
                for mech in disease["mechanism_classes"]:
                    lines.append(f"- {mech}")
                lines.append("")

            # Public tickers
            if disease.get("public_tickers"):
                lines.extend(
                    [
                        "#### Public Tickers",
                        "",
                    ]
                )
                for ticker in disease["public_tickers"]:
                    lines.append(f"- {ticker}")
                lines.append("")

        atomic_write_text(output_path, "\n".join(lines))

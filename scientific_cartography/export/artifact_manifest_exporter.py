"""Export artifact manifest for Phase 6 exports."""

from pathlib import Path
from typing import Optional

from scientific_cartography.io import deterministic_timestamp, write_json


class ArtifactManifestExporter:
    """Export artifact manifest tracking."""

    def __init__(self, as_of_date: str = "", created_at_utc: Optional[str] = None):
        """Initialize exporter.

        Args:
            as_of_date: Date for export snapshot (YYYY-MM-DD).
            created_at_utc: Override creation timestamp for deterministic tests.
        """
        self.as_of_date = as_of_date
        self.created_at_utc = created_at_utc or deterministic_timestamp(as_of_date)

    def build_manifest(
        self,
        inputs: dict,
        outputs: list[str],
    ) -> dict:
        """Build artifact manifest.

        Args:
            inputs: Dict mapping input names to file paths.
            outputs: List of output file paths.

        Returns:
            Manifest dict.
        """
        return {
            "as_of_date": self.as_of_date,
            "created_at_utc": self.created_at_utc,
            "artifact_type": "scientific_cartography_export_manifest",
            "phase": "phase_6_artifact_export",
            "inputs": inputs,
            "outputs": sorted(outputs),
            "governance": {
                "read_only_diagnostic": True,
                "production_wiring": False,
                "ranker_change": False,
                "selector_change": False,
                "sizing_change": False,
                "final_score_change": False,
                "alpha_promotion": False,
            },
            "warnings": [],
        }

    def write_manifest(self, manifest: dict, output_path: Path) -> None:
        """Write manifest to JSON.

        Args:
            manifest: Manifest dict.
            output_path: Output path.
        """
        write_json(output_path, manifest)

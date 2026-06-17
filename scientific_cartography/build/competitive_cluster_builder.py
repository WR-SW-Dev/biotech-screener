"""Build competitive clusters from program records."""

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from scientific_cartography.schemas.cluster_schema import CompetitiveClusterRecord
from scientific_cartography.schemas.program_schema import ProgramRecord


class CompetitiveClusterBuilder:
    """Build competitive clusters from program records."""

    def __init__(self, as_of_date: str = ""):
        """Initialize cluster builder.

        Args:
            as_of_date: Date for cluster snapshot (YYYY-MM-DD).
        """
        self.as_of_date = as_of_date

    def _make_cluster_key(
        self,
        disease_id: str | None,
        mechanism_class: str | None,
        modality: str | None,
        target: str | None,
    ) -> str:
        """Create canonical cluster key.

        Args:
            disease_id: Disease ID or "unknown".
            mechanism_class: Mechanism class or "unknown".
            modality: Modality or "unknown".
            target: Target or "unknown".

        Returns:
            Pipe-delimited cluster key.
        """
        disease = disease_id or "unknown"
        mech = mechanism_class or "unknown"
        mod = modality or "unknown"
        tgt = target or "unknown"
        return f"{disease}|{mech}|{mod}|{tgt}"

    def _make_cluster_id(self, cluster_key: str) -> str:
        """Create deterministic cluster ID from key.

        Args:
            cluster_key: Canonical cluster key.

        Returns:
            Hex digest (first 16 chars of SHA256).
        """
        h = hashlib.sha256(cluster_key.encode())
        return h.hexdigest()[:16]

    def _get_stage_bucket(self, program: ProgramRecord) -> str:
        """Get clinical stage bucket from program.

        Args:
            program: ProgramRecord.

        Returns:
            Stage bucket name (approved, filed, phase3, ..., unknown).
        """
        if not program.clinical_stage:
            return "unknown"

        stage_lower = program.clinical_stage.lower()

        # Map normalized stages to buckets
        if "approved" in stage_lower:
            return "approved"
        elif "filed" in stage_lower:
            return "filed"
        elif "phase 3" in stage_lower or "phase3" in stage_lower:
            return "phase3"
        elif "phase 2" in stage_lower or "phase2" in stage_lower:
            return "phase2"
        elif "phase 1" in stage_lower or "phase1" in stage_lower:
            return "phase1"
        elif "preclinical" in stage_lower or "preclin" in stage_lower:
            return "preclinical"
        elif "discontinued" in stage_lower or "inactive" in stage_lower or "terminated" in stage_lower:
            return "discontinued"
        else:
            return "unknown"

    def _is_public_program(self, program: ProgramRecord) -> bool:
        """Check if program is from public company.

        Args:
            program: ProgramRecord.

        Returns:
            True if company_id is present (indicates public/resolved company).
        """
        return bool(program.company_id) or bool(program.ticker)

    def build_from_programs(self, programs: list[ProgramRecord]) -> tuple[list[CompetitiveClusterRecord], dict]:
        """Build competitive clusters from programs.

        Args:
            programs: List of ProgramRecords.

        Returns:
            Tuple of (cluster records, coverage report dict).
        """
        # Group programs by cluster key
        clusters_dict: dict[str, list[ProgramRecord]] = defaultdict(list)

        for program in programs:
            cluster_key = self._make_cluster_key(
                disease_id=program.disease_id,
                mechanism_class=program.mechanism_class,
                modality=program.modality,
                target=program.target,
            )
            clusters_dict[cluster_key].append(program)

        # Build cluster records
        cluster_records = []
        for cluster_key in sorted(clusters_dict.keys()):
            member_programs = clusters_dict[cluster_key]
            cluster = self._build_single_cluster(cluster_key, member_programs)
            cluster_records.append(cluster)

        # Build coverage report
        coverage_report = self._build_coverage_report(programs, cluster_records)

        return cluster_records, coverage_report

    def _build_single_cluster(self, cluster_key: str, programs: list[ProgramRecord]) -> CompetitiveClusterRecord:
        """Build a single cluster from member programs.

        Args:
            cluster_key: Canonical cluster key.
            programs: List of member ProgramRecords.

        Returns:
            CompetitiveClusterRecord.
        """
        cluster_id = self._make_cluster_id(cluster_key)

        # Extract key components from first program (all same for this cluster)
        first = programs[0]
        disease_id = first.disease_id
        disease_name = first.disease_name
        therapeutic_area = first.therapeutic_area
        mechanism_class = first.mechanism_class
        modality = first.modality
        target = first.target

        # Count programs by public status
        public_count = sum(1 for p in programs if self._is_public_program(p))
        private_or_unknown_count = len(programs) - public_count

        # Count programs by stage
        stage_counts = defaultdict(int)
        for program in programs:
            stage_bucket = self._get_stage_bucket(program)
            stage_counts[stage_bucket] += 1

        # Collect tickers, sponsors, assets
        tickers = set()
        sponsors = set()
        assets = set()
        program_ids = []
        source_refs_set = set()
        confidences = []

        for program in programs:
            if program.ticker:
                tickers.add(program.ticker)
            if program.company_name:
                sponsors.add(program.company_name)
            if program.asset_name:
                assets.add(program.asset_name)
            program_ids.append(program.program_id)

            # Collect source refs
            if program.source_refs:
                source_refs_set.update(program.source_refs)

            # Track confidence
            if program.confidence > 0:
                confidences.append(program.confidence)

        # Sort lists for deterministic output
        sorted_tickers = sorted(tickers)
        sorted_sponsors = sorted(sponsors)
        sorted_assets = sorted(assets)
        sorted_program_ids = sorted(program_ids)
        sorted_source_refs = sorted(source_refs_set)

        # Compute confidence as minimum of member confidences
        min_confidence = min(confidences) if confidences else 0.0

        # Build warnings
        warnings = []
        if not disease_id and not disease_name:
            warnings.append("unknown disease")
        elif disease_name == "unknown":
            warnings.append("unknown disease")

        if not mechanism_class or mechanism_class == "unknown":
            warnings.append("unknown mechanism")

        if not modality or modality == "unknown":
            warnings.append("unknown modality")

        if not target or target == "unknown":
            warnings.append("unknown target")

        for program in programs:
            if not program.source_refs:
                warnings.append(f"program {program.program_id} missing source_refs")

        # Create cluster record
        cluster = CompetitiveClusterRecord(
            cluster_id=cluster_id,
            disease_id=disease_id,
            disease_name=disease_name,
            therapeutic_area=therapeutic_area,
            mechanism_class=mechanism_class,
            modality=modality,
            target=target,
            cluster_key=cluster_key,
            program_count=len(programs),
            public_program_count=public_count,
            private_or_unknown_program_count=private_or_unknown_count,
            approved_count=stage_counts.get("approved", 0),
            filed_count=stage_counts.get("filed", 0),
            phase3_count=stage_counts.get("phase3", 0),
            phase2_count=stage_counts.get("phase2", 0),
            phase1_count=stage_counts.get("phase1", 0),
            preclinical_count=stage_counts.get("preclinical", 0),
            discontinued_count=stage_counts.get("discontinued", 0),
            unknown_stage_count=stage_counts.get("unknown", 0),
            public_tickers=sorted_tickers,
            sponsor_names=sorted_sponsors,
            asset_names=sorted_assets,
            program_ids=sorted_program_ids,
            source_refs=sorted_source_refs,
            as_of_date=self.as_of_date,
            confidence=min_confidence,
            warnings=warnings,
        )

        return cluster

    def _build_coverage_report(self, programs: list[ProgramRecord], clusters: list[CompetitiveClusterRecord]) -> dict:
        """Build cluster coverage report.

        Args:
            programs: All program records.
            clusters: All cluster records.

        Returns:
            Coverage report dict.
        """
        # Count stage programs
        stage_counts = defaultdict(int)
        for program in programs:
            stage_bucket = self._get_stage_bucket(program)
            stage_counts[stage_bucket] += 1

        # Count public programs
        public_count = sum(1 for p in programs if self._is_public_program(p))
        private_or_unknown_count = len(programs) - public_count

        # Count clusters by known/unknown fields
        clusters_with_known_disease = sum(1 for c in clusters if c.disease_id and c.disease_id != "unknown")
        clusters_with_known_mechanism = sum(1 for c in clusters if c.mechanism_class and c.mechanism_class != "unknown")
        clusters_with_known_modality = sum(1 for c in clusters if c.modality and c.modality != "unknown")
        clusters_with_known_target = sum(1 for c in clusters if c.target and c.target != "unknown")

        clusters_with_unknown_disease = len(clusters) - clusters_with_known_disease
        clusters_with_unknown_mechanism = len(clusters) - clusters_with_known_mechanism
        clusters_with_unknown_modality = len(clusters) - clusters_with_known_modality
        clusters_with_unknown_target = len(clusters) - clusters_with_known_target

        report = {
            "as_of_date": self.as_of_date,
            "program_records": len(programs),
            "competitive_clusters": len(clusters),
            "clusters_with_known_disease": clusters_with_known_disease,
            "clusters_with_known_mechanism": clusters_with_known_mechanism,
            "clusters_with_known_modality": clusters_with_known_modality,
            "clusters_with_known_target": clusters_with_known_target,
            "clusters_with_unknown_disease": clusters_with_unknown_disease,
            "clusters_with_unknown_mechanism": clusters_with_unknown_mechanism,
            "clusters_with_unknown_modality": clusters_with_unknown_modality,
            "clusters_with_unknown_target": clusters_with_unknown_target,
            "public_programs": public_count,
            "private_or_unknown_programs": private_or_unknown_count,
            "approved_programs": stage_counts.get("approved", 0),
            "filed_programs": stage_counts.get("filed", 0),
            "phase3_programs": stage_counts.get("phase3", 0),
            "phase2_programs": stage_counts.get("phase2", 0),
            "phase1_programs": stage_counts.get("phase1", 0),
            "preclinical_programs": stage_counts.get("preclinical", 0),
            "discontinued_programs": stage_counts.get("discontinued", 0),
            "unknown_stage_programs": stage_counts.get("unknown", 0),
            "warnings": self._collect_all_warnings(clusters),
        }

        return report

    def _collect_all_warnings(self, clusters: list[CompetitiveClusterRecord]) -> list[str]:
        """Collect all unique warnings from clusters.

        Args:
            clusters: Cluster records.

        Returns:
            Sorted list of unique warnings.
        """
        all_warnings = set()
        for cluster in clusters:
            all_warnings.update(cluster.warnings)
        return sorted(all_warnings)

    def write_clusters_jsonl(self, clusters: list[CompetitiveClusterRecord], output_path: Path) -> None:
        """Write clusters to JSONL file.

        Args:
            clusters: Cluster records.
            output_path: Path to output JSONL file.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            for cluster in clusters:
                f.write(json.dumps(cluster.to_dict()) + "\n")

    def write_coverage_report(self, report: dict, output_path: Path) -> None:
        """Write coverage report to JSON file.

        Args:
            report: Coverage report dict.
            output_path: Path to output JSON file.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)

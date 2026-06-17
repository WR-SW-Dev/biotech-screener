"""Build landscape features from programs and clusters."""

import hashlib
from collections import defaultdict

from scientific_cartography.schemas.cluster_schema import CompetitiveClusterRecord
from scientific_cartography.schemas.landscape_feature_schema import LandscapeFeatureRecord
from scientific_cartography.schemas.program_schema import ProgramRecord


class LandscapeFeatureBuilder:
    """Build landscape features from programs and clusters."""

    def __init__(self, as_of_date: str = ""):
        """Initialize feature builder.

        Args:
            as_of_date: Date for feature snapshot (YYYY-MM-DD).
        """
        self.as_of_date = as_of_date

    def build_from_programs_and_clusters(
        self,
        programs: list[ProgramRecord],
        clusters: list[CompetitiveClusterRecord],
    ) -> tuple[list[LandscapeFeatureRecord], dict]:
        """Build landscape features from programs and clusters.

        Args:
            programs: List of ProgramRecords.
            clusters: List of CompetitiveClusterRecords.

        Returns:
            Tuple of (feature records, coverage report dict).
        """
        # Build cluster lookup by (disease, mechanism, modality, target)
        cluster_lookup = self._build_cluster_lookup(clusters)

        # Build disease-level counts
        disease_counts = self._compute_disease_counts(clusters)

        # Build features for each program
        features = []
        for program in programs:
            feature = self._build_feature_for_program(program, cluster_lookup, disease_counts)
            features.append(feature)

        # Sort by feature_id for determinism
        features.sort(key=lambda f: f.feature_id)

        # Build coverage report
        coverage_report = self._build_coverage_report(features, clusters)

        return features, coverage_report

    def _build_cluster_lookup(self, clusters: list[CompetitiveClusterRecord]) -> dict:
        """Build lookup mapping (disease, mechanism, modality, target) to cluster.

        Args:
            clusters: List of CompetitiveClusterRecords.

        Returns:
            Lookup dict.
        """
        lookup = {}
        for cluster in clusters:
            key = (
                cluster.disease_id or cluster.disease_name or "unknown",
                cluster.mechanism_class or "unknown",
                cluster.modality or "unknown",
                cluster.target or "unknown",
            )
            lookup[key] = cluster
        return lookup

    def _compute_disease_counts(self, clusters: list[CompetitiveClusterRecord]) -> dict:
        """Compute disease-level program counts.

        Args:
            clusters: List of CompetitiveClusterRecords.

        Returns:
            Dict mapping disease_id/disease_name to count.
        """
        counts = defaultdict(int)
        for cluster in clusters:
            disease_key = cluster.disease_id or cluster.disease_name or "unknown"
            counts[disease_key] += cluster.program_count
        return dict(counts)

    def _make_feature_id(self, program: ProgramRecord) -> str:
        """Create deterministic feature ID from program.

        Args:
            program: ProgramRecord.

        Returns:
            Hex digest (first 16 chars of SHA256).
        """
        key = f"{program.program_id}|{self.as_of_date}".lower().strip()
        h = hashlib.sha256(key.encode())
        return h.hexdigest()[:16]

    def _get_stage_bucket(self, program: ProgramRecord) -> str | None:
        """Get clinical stage bucket from program.

        Args:
            program: ProgramRecord.

        Returns:
            Stage bucket name or None if unknown.
        """
        if not program.clinical_stage:
            return None

        stage_lower = program.clinical_stage.lower()

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
        elif "discontinued" in stage_lower or "inactive" in stage_lower:
            return "discontinued"
        else:
            return None

    def _build_feature_for_program(
        self, program: ProgramRecord, cluster_lookup: dict, disease_counts: dict
    ) -> LandscapeFeatureRecord:
        """Build a single feature record for a program.

        Args:
            program: ProgramRecord.
            cluster_lookup: Cluster lookup dict.
            disease_counts: Disease-level counts.

        Returns:
            LandscapeFeatureRecord.
        """
        feature_id = self._make_feature_id(program)

        # Find matching cluster
        cluster_key = (
            program.disease_id or program.disease_name or "unknown",
            program.mechanism_class or "unknown",
            program.modality or "unknown",
            program.target or "unknown",
        )
        cluster = cluster_lookup.get(cluster_key)

        # Compute feature data
        warnings = []
        feature_status = "computed"

        if cluster is None:
            feature_status = "partial"
            warnings.append("missing_cluster_match")

        # Disease-level counts
        disease_key = program.disease_id or program.disease_name or "unknown"
        disease_program_count = disease_counts.get(disease_key)

        # Cluster counts
        mechanism_program_count = cluster.program_count if cluster else None
        approved_incumbent_count = cluster.approved_count if cluster else None
        phase3_program_count = cluster.phase3_count if cluster else None
        phase2_program_count = cluster.phase2_count if cluster else None
        phase1_program_count = cluster.phase1_count if cluster else None
        public_program_count = cluster.public_program_count if cluster else None
        private_or_unknown_count = cluster.private_or_unknown_program_count if cluster else None

        # Same-stage counts
        stage_bucket = self._get_stage_bucket(program)
        same_stage_program_count = None
        if cluster and stage_bucket:
            stage_count_map = {
                "approved": cluster.approved_count,
                "filed": cluster.filed_count,
                "phase3": cluster.phase3_count,
                "phase2": cluster.phase2_count,
                "phase1": cluster.phase1_count,
                "preclinical": cluster.preclinical_count,
                "discontinued": cluster.discontinued_count,
            }
            same_stage_program_count = stage_count_map.get(stage_bucket)

        # Compute scores
        mechanism_crowding_score = None
        stage_crowding_score = None
        white_space_score = None

        if cluster and not (program.disease_id is None and program.disease_name in (None, "unknown")):
            if program.mechanism_class and program.mechanism_class != "unknown":
                # Mechanism crowding
                mechanism_crowding_score = min(
                    1.0,
                    (
                        0.12 * cluster.approved_count
                        + 0.10 * cluster.filed_count
                        + 0.08 * cluster.phase3_count
                        + 0.05 * cluster.phase2_count
                        + 0.03 * cluster.phase1_count
                        + 0.02 * cluster.preclinical_count
                    ),
                )

                # White-space score
                if mechanism_crowding_score is not None:
                    white_space_score = max(0.0, 1.0 - mechanism_crowding_score)
            else:
                warnings.append("unknown_mechanism_no_crowding_score")

        # Stage crowding
        if stage_bucket and same_stage_program_count is not None:
            stage_weight = {
                "approved": 0.12,
                "filed": 0.10,
                "phase3": 0.08,
                "phase2": 0.05,
                "phase1": 0.03,
                "preclinical": 0.02,
                "discontinued": 0.0,
            }
            weight = stage_weight.get(stage_bucket, 0.0)
            stage_crowding_score = min(1.0, weight * same_stage_program_count)
        elif not stage_bucket:
            warnings.append("unknown_stage_no_stage_score")

        # Feature confidence
        feature_confidence = 0.0
        if program.confidence > 0:
            feature_confidence = program.confidence
        if cluster and cluster.confidence > 0:
            feature_confidence = min(feature_confidence, cluster.confidence)
        if not (program.source_refs or (cluster and cluster.source_refs)):
            feature_confidence = min(feature_confidence, 0.5)

        # Aggregate source refs
        source_refs_set = set()
        if program.source_refs:
            source_refs_set.update(program.source_refs)
        if cluster and cluster.source_refs:
            source_refs_set.update(cluster.source_refs)
        sorted_source_refs = sorted(source_refs_set)

        feature = LandscapeFeatureRecord(
            feature_id=feature_id,
            program_id=program.program_id,
            cluster_id=cluster.cluster_id if cluster else None,
            ticker=program.ticker,
            company_id=program.company_id,
            asset_id=program.asset_id,
            asset_name=program.asset_name,
            disease_id=program.disease_id,
            disease_name=program.disease_name,
            mechanism_class=program.mechanism_class,
            modality=program.modality,
            target=program.target,
            clinical_stage=program.clinical_stage,
            disease_program_count=disease_program_count,
            mechanism_program_count=mechanism_program_count,
            same_stage_program_count=same_stage_program_count,
            approved_incumbent_count=approved_incumbent_count,
            phase3_program_count=phase3_program_count,
            phase2_program_count=phase2_program_count,
            phase1_program_count=phase1_program_count,
            public_program_count=public_program_count,
            private_or_unknown_program_count=private_or_unknown_count,
            mechanism_crowding_score=mechanism_crowding_score,
            stage_crowding_score=stage_crowding_score,
            white_space_score=white_space_score,
            differentiation_proxy_score=None,  # Reserved for future
            feature_confidence=feature_confidence,
            feature_status=feature_status,
            source_refs=sorted_source_refs,
            as_of_date=self.as_of_date,
            warnings=warnings,
        )

        return feature

    def _build_coverage_report(
        self, features: list[LandscapeFeatureRecord], clusters: list[CompetitiveClusterRecord]
    ) -> dict:
        """Build feature coverage report.

        Args:
            features: All feature records.
            clusters: All cluster records.

        Returns:
            Coverage report dict.
        """
        # Count computed scores
        with_mechanism_crowding = sum(1 for f in features if f.mechanism_crowding_score is not None)
        with_stage_crowding = sum(1 for f in features if f.stage_crowding_score is not None)
        with_white_space = sum(1 for f in features if f.white_space_score is not None)
        with_differentiation = sum(1 for f in features if f.differentiation_proxy_score is not None)

        # Count reason for no score
        no_score_unknown_disease = sum(1 for f in features if "unknown_disease" in (f.warnings or []))
        no_score_unknown_mechanism = sum(1 for f in features if "unknown_mechanism" in (f.warnings or []))
        no_score_unknown_stage = sum(1 for f in features if "unknown_stage" in (f.warnings or []))
        missing_cluster = sum(1 for f in features if "missing_cluster_match" in (f.warnings or []))

        # Compute means (ignoring None values)
        mechanism_scores = [f.mechanism_crowding_score for f in features if f.mechanism_crowding_score is not None]
        stage_scores = [f.stage_crowding_score for f in features if f.stage_crowding_score is not None]
        white_space_scores = [f.white_space_score for f in features if f.white_space_score is not None]

        report = {
            "as_of_date": self.as_of_date,
            "program_records": len(features),
            "competitive_clusters": len(clusters),
            "landscape_feature_records": len(features),
            "features_with_mechanism_crowding_score": with_mechanism_crowding,
            "features_with_stage_crowding_score": with_stage_crowding,
            "features_with_white_space_score": with_white_space,
            "features_with_differentiation_proxy_score": with_differentiation,
            "features_without_scores_due_unknown_disease": no_score_unknown_disease,
            "features_without_scores_due_unknown_mechanism": no_score_unknown_mechanism,
            "features_without_scores_due_unknown_stage": no_score_unknown_stage,
            "features_with_missing_cluster_match": missing_cluster,
            "mean_mechanism_crowding_score": (
                sum(mechanism_scores) / len(mechanism_scores) if mechanism_scores else None
            ),
            "mean_stage_crowding_score": (sum(stage_scores) / len(stage_scores) if stage_scores else None),
            "mean_white_space_score": (
                sum(white_space_scores) / len(white_space_scores) if white_space_scores else None
            ),
            "warnings": self._collect_all_warnings(features),
        }

        return report

    def _collect_all_warnings(self, features: list[LandscapeFeatureRecord]) -> list[str]:
        """Collect all unique warnings from features.

        Args:
            features: Feature records.

        Returns:
            Sorted list of unique warnings.
        """
        all_warnings = set()
        for feature in features:
            if feature.warnings:
                all_warnings.update(feature.warnings)
        return sorted(all_warnings)

    def write_features_jsonl(self, features: list[LandscapeFeatureRecord], output_path) -> None:
        """Write features to JSONL file.

        Args:
            features: Feature records.
            output_path: Path to output JSONL file.
        """
        import json
        from pathlib import Path

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            for feature in features:
                f.write(json.dumps(feature.to_dict()) + "\n")

    def write_coverage_report(self, report: dict, output_path) -> None:
        """Write coverage report to JSON file.

        Args:
            report: Coverage report dict.
            output_path: Path to output JSON file.
        """
        import json
        from pathlib import Path

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)

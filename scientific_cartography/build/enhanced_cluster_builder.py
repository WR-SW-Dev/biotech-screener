"""Build enhanced competitive clusters from Phase 9 AssetIndicationMapRecord objects."""

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from scientific_cartography.schemas.asset_indication_map_schema import AssetIndicationMapRecord
from scientific_cartography.schemas.enhanced_cluster_schema import (
    EnhancedClusterCoverageReport,
    EnhancedCompetitiveClusterRecord,
)


class EnhancedCompetitiveClusterBuilder:
    """Build enhanced clusters from Phase 9 asset indication map records."""

    def __init__(self, as_of_date: str = ""):
        """Initialize builder.

        Args:
            as_of_date: Record date (YYYY-MM-DD).
        """
        self.as_of_date = as_of_date

    def _get_disease_key(self, record: AssetIndicationMapRecord) -> str:
        """Determine primary disease key for clustering.

        Priority: mondo_id > normalized_disease_name > raw_indication > unknown.

        Args:
            record: AssetIndicationMapRecord.

        Returns:
            Disease key string.
        """
        if record.mondo_id:
            return record.mondo_id
        elif record.normalized_disease_name:
            return record.normalized_disease_name
        elif record.raw_indication:
            return record.raw_indication
        else:
            return "unknown_disease"

    def _get_mechanism_class(self, record: AssetIndicationMapRecord) -> str:
        """Get mechanism class, defaulting to unknown.

        Args:
            record: AssetIndicationMapRecord.

        Returns:
            Mechanism class or "unknown_mechanism".
        """
        return record.mechanism_class or "unknown_mechanism"

    def _get_target(self, record: AssetIndicationMapRecord) -> str:
        """Get target, defaulting to unknown.

        Args:
            record: AssetIndicationMapRecord.

        Returns:
            Target or "unknown_target".
        """
        return record.target or "unknown_target"

    def _get_modality(self, record: AssetIndicationMapRecord) -> str:
        """Get modality, defaulting to unknown.

        Args:
            record: AssetIndicationMapRecord.

        Returns:
            Modality or "unknown_modality".
        """
        return record.modality or "unknown_modality"

    def _make_cluster_key(
        self,
        disease_key: str,
        mechanism_class: str,
        target: str,
        modality: str,
    ) -> str:
        """Create canonical cluster key.

        Args:
            disease_key: Primary disease identifier.
            mechanism_class: Mechanism class.
            target: Target.
            modality: Modality.

        Returns:
            Pipe-delimited cluster key.
        """
        return f"{disease_key}|{mechanism_class}|{target}|{modality}"

    def _make_cluster_id(self, cluster_key: str) -> str:
        """Create deterministic cluster ID.

        Args:
            cluster_key: Canonical cluster key.

        Returns:
            Hex digest (first 16 chars of SHA256).
        """
        h = hashlib.sha256(cluster_key.encode())
        return h.hexdigest()[:16]

    def _get_stage_bucket(self, stage: str | None) -> str:
        """Get clinical stage bucket.

        Args:
            stage: Clinical stage string (or None).

        Returns:
            Stage bucket name.
        """
        if not stage:
            return "unknown"

        stage_lower = stage.lower()

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
        elif "preclin" in stage_lower:
            return "preclinical"
        elif "discontinued" in stage_lower or "inactive" in stage_lower or "terminated" in stage_lower:
            return "discontinued"
        else:
            return "unknown"

    def build_from_asset_indication_records(
        self,
        records: list[AssetIndicationMapRecord],
    ) -> tuple[list[EnhancedCompetitiveClusterRecord], EnhancedClusterCoverageReport]:
        """Build enhanced clusters from Phase 9 asset indication map records.

        Args:
            records: List of AssetIndicationMapRecord.

        Returns:
            Tuple of (enhanced_clusters, coverage_report).
        """
        clusters_by_key = defaultdict(list)

        # Group records by cluster key
        for record in records:
            disease_key = self._get_disease_key(record)
            mechanism_class = self._get_mechanism_class(record)
            target = self._get_target(record)
            modality = self._get_modality(record)

            cluster_key = self._make_cluster_key(disease_key, mechanism_class, target, modality)
            clusters_by_key[cluster_key].append((record, disease_key))

        # Build enhanced cluster records
        enhanced_clusters = []

        for cluster_key, cluster_members in clusters_by_key.items():
            (
                disease_key,
                mechanism_class,
                target,
                modality,
            ) = cluster_key.split("|")

            cluster_id = self._make_cluster_id(cluster_key)

            # Aggregate counts and distributions
            unique_assets = set()
            unique_companies = set()
            unique_tickers = set()
            unique_sponsor_names = set()
            unique_company_names = set()
            unique_asset_names = set()
            unique_asset_ids = set()

            stage_distribution = defaultdict(int)
            source_type_distribution = defaultdict(int)
            source_priority_distribution = defaultdict(int)

            mondo_count = 0
            no_mondo_count = 0
            with_ticker_count = 0
            without_ticker_count = 0
            with_target_count = 0
            without_target_count = 0
            with_mechanism_count = 0
            without_mechanism_count = 0

            confidences = []
            all_source_refs = set()

            warnings = []

            # Extract first record to get disease/therapeutic info
            first_record = cluster_members[0][0]
            normalized_disease_name = first_record.normalized_disease_name
            mondo_id = first_record.mondo_id
            therapeutic_area = first_record.therapeutic_area
            parent_disease = first_record.parent_disease

            source_priority_min = 9

            for record, _ in cluster_members:
                # Counts - prefer asset_id, fallback to asset_name
                if record.asset_id:
                    unique_assets.add(record.asset_id)
                    unique_asset_ids.add(record.asset_id)
                elif record.asset_name:
                    unique_assets.add(record.asset_name)

                if record.asset_name:
                    unique_asset_names.add(record.asset_name)
                if record.company_id:
                    unique_companies.add(record.company_id)
                if record.company_name:
                    unique_company_names.add(record.company_name)
                if record.sponsor_name:
                    unique_sponsor_names.add(record.sponsor_name)
                if record.ticker:
                    unique_tickers.add(record.ticker)

                # Stage distribution
                stage_bucket = self._get_stage_bucket(record.clinical_stage)
                stage_distribution[stage_bucket] += 1

                # Source distribution
                source_type_distribution[record.source_type] += 1
                source_priority_distribution[record.source_priority] += 1

                # Source priority min (lower is better)
                if record.source_priority < source_priority_min:
                    source_priority_min = record.source_priority

                # Mondo mapping coverage
                if record.mondo_id:
                    mondo_count += 1
                else:
                    no_mondo_count += 1

                # Ticker coverage
                if record.ticker:
                    with_ticker_count += 1
                else:
                    without_ticker_count += 1

                # Target coverage
                if record.target and record.target != "unknown_target":
                    with_target_count += 1
                else:
                    without_target_count += 1

                # Mechanism coverage
                if record.mechanism_class and record.mechanism_class != "unknown_mechanism":
                    with_mechanism_count += 1
                else:
                    without_mechanism_count += 1

                # Confidence
                confidences.append(record.overall_confidence)

                # Source refs
                if record.source_refs:
                    all_source_refs.update(record.source_refs)

            # Warnings
            if no_mondo_count > 0 and mondo_count == 0:
                warnings.append(f"Cluster has no MONDO mapping ({no_mondo_count} unmapped records)")
            if without_ticker_count == len(cluster_members):
                warnings.append("Cluster has no public tickers")
            if mechanism_class == "unknown_mechanism":
                warnings.append("Cluster has unknown mechanism")
            if target == "unknown_target":
                warnings.append("Cluster has unknown target")

            # Compute confidence stats
            confidence_min = min(confidences) if confidences else 0.0
            confidence_max = max(confidences) if confidences else 0.0
            confidence_mean = sum(confidences) / len(confidences) if confidences else 0.0

            cluster = EnhancedCompetitiveClusterRecord(
                cluster_id=cluster_id,
                cluster_key=cluster_key,
                disease_key=disease_key,
                normalized_disease_name=normalized_disease_name,
                mondo_id=mondo_id,
                therapeutic_area=therapeutic_area,
                parent_disease=parent_disease,
                mechanism_class=mechanism_class,
                target=target,
                modality=modality,
                program_count=len(cluster_members),
                asset_count=len(unique_assets),
                company_count=len(unique_companies),
                ticker_count=len(unique_tickers),
                public_tickers=sorted(unique_tickers),
                company_names=sorted(unique_company_names),
                sponsor_names=sorted(unique_sponsor_names),
                asset_names=sorted(unique_asset_names),
                asset_ids=sorted(unique_asset_ids),
                clinical_stage_distribution=dict(stage_distribution),
                source_type_distribution=dict(source_type_distribution),
                source_priority_min=source_priority_min,
                source_priority_distribution=dict(source_priority_distribution),
                records_with_mondo_id=mondo_count,
                records_without_mondo_id=no_mondo_count,
                records_with_ticker=with_ticker_count,
                records_without_ticker=without_ticker_count,
                records_with_target=with_target_count,
                records_without_target=without_target_count,
                records_with_mechanism=with_mechanism_count,
                records_without_mechanism=without_mechanism_count,
                confidence_min=confidence_min,
                confidence_max=confidence_max,
                confidence_mean=confidence_mean,
                source_refs=sorted(all_source_refs),
                as_of_date=self.as_of_date,
                warnings=warnings,
            )

            enhanced_clusters.append(cluster)

        # Sort clusters deterministically
        enhanced_clusters.sort(
            key=lambda c: (
                c.therapeutic_area or "zzz",
                c.normalized_disease_name,
                c.mechanism_class,
                c.target,
                c.modality,
                c.cluster_id,
            )
        )

        # Build coverage report
        coverage = self._build_coverage_report(enhanced_clusters, records)

        return enhanced_clusters, coverage

    def _build_coverage_report(
        self,
        clusters: list[EnhancedCompetitiveClusterRecord],
        records: list[AssetIndicationMapRecord],
    ) -> EnhancedClusterCoverageReport:
        """Build coverage report from clusters.

        Args:
            clusters: List of EnhancedCompetitiveClusterRecord.
            records: Original AssetIndicationMapRecord list.

        Returns:
            EnhancedClusterCoverageReport.
        """
        report = EnhancedClusterCoverageReport(as_of_date=self.as_of_date)

        unique_diseases = set()
        unique_mondo_ids = set()
        unique_therapeutic_areas = set()
        unique_mechanisms = set()
        unique_targets = set()
        unique_modalities = set()
        unique_assets = set()
        unique_companies = set()
        unique_tickers = set()

        clusters_by_stage = defaultdict(int)
        clusters_by_therapeutic_area = defaultdict(int)
        records_by_source_type = defaultdict(int)

        for cluster in clusters:
            report.total_clusters += 1

            # Unique values
            if cluster.normalized_disease_name:
                unique_diseases.add(cluster.normalized_disease_name)
            if cluster.mondo_id:
                unique_mondo_ids.add(cluster.mondo_id)
            if cluster.therapeutic_area:
                unique_therapeutic_areas.add(cluster.therapeutic_area)
                clusters_by_therapeutic_area[cluster.therapeutic_area] += 1

            if cluster.mechanism_class != "unknown_mechanism":
                unique_mechanisms.add(cluster.mechanism_class)
            if cluster.target != "unknown_target":
                unique_targets.add(cluster.target)
            if cluster.modality != "unknown_modality":
                unique_modalities.add(cluster.modality)

            unique_assets.update(cluster.asset_ids)
            unique_companies.update(cluster.company_names)
            unique_tickers.update(cluster.public_tickers)

            # Ticket coverage
            if cluster.ticker_count > 0:
                report.clusters_with_ticker += 1
            else:
                report.clusters_without_ticker += 1

            # Mondo coverage
            if cluster.mondo_id:
                report.clusters_with_mondo_id += 1
            else:
                report.clusters_without_mondo_id += 1

            # Mechanism/target coverage
            if cluster.mechanism_class != "unknown_mechanism":
                report.clusters_with_known_mechanism += 1
            if cluster.target != "unknown_target":
                report.clusters_with_known_target += 1

            # Stage distribution
            if cluster.clinical_stage_distribution:
                for stage, count in cluster.clinical_stage_distribution.items():
                    clusters_by_stage[stage] += count

        # Source type distribution
        for record in records:
            records_by_source_type[record.source_type] += 1

        # Set report values
        report.total_records = len(records)
        report.unique_diseases = len(unique_diseases)
        report.unique_mondo_ids = len(unique_mondo_ids)
        report.unique_therapeutic_areas = len(unique_therapeutic_areas)
        report.unique_mechanisms = len(unique_mechanisms)
        report.unique_targets = len(unique_targets)
        report.unique_modalities = len(unique_modalities)
        report.unique_assets = len(unique_assets)
        report.unique_companies = len(unique_companies)
        report.unique_tickers = len(unique_tickers)
        report.records_by_source_type = dict(records_by_source_type)
        report.clusters_by_therapeutic_area = dict(clusters_by_therapeutic_area)
        report.clusters_by_stage_bucket = dict(clusters_by_stage)

        return report

    def write_jsonl(
        self,
        clusters: list[EnhancedCompetitiveClusterRecord],
        path: Path | str,
    ) -> None:
        """Write clusters to JSONL file.

        Args:
            clusters: List of EnhancedCompetitiveClusterRecord.
            path: Output file path.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            for cluster in clusters:
                f.write(json.dumps(cluster.to_dict()) + "\n")

    def write_coverage_report(
        self,
        report: EnhancedClusterCoverageReport,
        path: Path | str,
    ) -> None:
        """Write coverage report to JSON file.

        Args:
            report: EnhancedClusterCoverageReport.
            path: Output file path.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            json.dump(report.to_dict(), f, indent=2)

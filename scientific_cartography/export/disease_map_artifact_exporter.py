"""Export detailed per-disease artifacts from Phase 8-11 diagnostic layers."""

import json
import re
from collections import defaultdict
from pathlib import Path

from scientific_cartography.io import atomic_write_text, deterministic_timestamp, write_csv, write_json
from scientific_cartography.schemas.asset_indication_map_schema import AssetIndicationMapRecord
from scientific_cartography.schemas.disease_ontology_schema import DiseaseOntologyRecord
from scientific_cartography.schemas.enhanced_cluster_schema import EnhancedCompetitiveClusterRecord
from scientific_cartography.schemas.landscape_context_schema import LandscapeContextFeatureRecord


class DiseaseMapArtifactExporter:
    """Export detailed per-disease diagnostic artifacts."""

    def __init__(self, as_of_date: str = "", created_at_utc: str = ""):
        """Initialize exporter.

        Args:
            as_of_date: Date for artifact snapshot (YYYY-MM-DD).
            created_at_utc: Creation timestamp (ISO 8601).
        """
        self.as_of_date = as_of_date
        self.created_at_utc = created_at_utc or deterministic_timestamp(as_of_date)

    def _make_safe_slug(self, disease_name: str) -> str:
        """Create safe filesystem slug from disease name.

        Args:
            disease_name: Disease name.

        Returns:
            Safe slug (lowercase, alphanumeric + dashes).
        """
        if not disease_name or disease_name == "unknown":
            return "unknown-disease"

        # Lowercase and replace non-alphanumeric with dash
        slug = re.sub(r"[^a-z0-9]+", "-", disease_name.lower())

        # Collapse consecutive dashes and strip edges
        slug = re.sub(r"-+", "-", slug).strip("-")

        return slug if slug else "unknown-disease"

    def _get_disease_key(self, record: AssetIndicationMapRecord) -> str:
        """Get disease key from asset indication record.

        Args:
            record: AssetIndicationMapRecord.

        Returns:
            Disease key (mondo_id or normalized_disease_name or raw_indication).
        """
        if record.mondo_id:
            return record.mondo_id
        elif record.normalized_disease_name:
            return record.normalized_disease_name
        elif record.raw_indication:
            return record.raw_indication
        else:
            return "unknown_disease"

    def _build_disease_index(
        self,
        asset_records: list[AssetIndicationMapRecord],
        disease_ontology: dict[str, DiseaseOntologyRecord],
        clusters: list[EnhancedCompetitiveClusterRecord],
        context_features: list[LandscapeContextFeatureRecord],
    ) -> dict[str, dict]:
        """Build index of disease data.

        Args:
            asset_records: Phase 9 records.
            disease_ontology: Disease ontology dict.
            clusters: Phase 10 records.
            context_features: Phase 11 records.

        Returns:
            Dict mapping disease_key to aggregated data.
        """
        disease_index = defaultdict(
            lambda: {
                "asset_records": [],
                "clusters": [],
                "context_features": [],
                "disease_ontology": None,
                "raw_names": set(),
                "tickers": set(),
                "companies": set(),
                "mechanisms": set(),
                "targets": set(),
                "modalities": set(),
                "source_refs": set(),
            }
        )

        # Index asset records
        for record in asset_records:
            disease_key = self._get_disease_key(record)
            disease_index[disease_key]["asset_records"].append(record)
            if record.raw_indication:
                disease_index[disease_key]["raw_names"].add(record.raw_indication)
            if record.ticker:
                disease_index[disease_key]["tickers"].add(record.ticker)
            if record.company_name:
                disease_index[disease_key]["companies"].add(record.company_name)
            if record.mechanism_class and "unknown" not in record.mechanism_class.lower():
                disease_index[disease_key]["mechanisms"].add(record.mechanism_class)
            if record.target and "unknown" not in record.target.lower():
                disease_index[disease_key]["targets"].add(record.target)
            if record.modality and "unknown" not in record.modality.lower():
                disease_index[disease_key]["modalities"].add(record.modality)
            if record.source_refs:
                disease_index[disease_key]["source_refs"].update(record.source_refs)

        # Index clusters
        for cluster in clusters:
            disease_key = cluster.disease_key
            disease_index[disease_key]["clusters"].append(cluster)
            if cluster.source_refs:
                disease_index[disease_key]["source_refs"].update(cluster.source_refs)

        # Index context features
        for feature in context_features:
            disease_key = self._get_disease_key(
                AssetIndicationMapRecord(
                    record_id="temp",
                    raw_indication=feature.raw_indication,
                    normalized_disease_name=feature.normalized_disease_name,
                    mondo_id=feature.mondo_id,
                )
            )
            disease_index[disease_key]["context_features"].append(feature)
            if feature.source_refs:
                disease_index[disease_key]["source_refs"].update(feature.source_refs)

        # Add disease ontology (match by normalized name or mondo_id)
        for ontology_record in disease_ontology.values():
            disease_key = ontology_record.mondo_id or ontology_record.normalized_disease_name or "unknown_disease"
            if disease_key in disease_index:
                disease_index[disease_key]["disease_ontology"] = ontology_record

        return disease_index

    def _build_disease_artifact(
        self,
        disease_key: str,
        disease_data: dict,
    ) -> dict:
        """Build per-disease artifact.

        Args:
            disease_key: Disease key.
            disease_data: Aggregated disease data.

        Returns:
            Disease artifact dict.
        """
        asset_records = disease_data["asset_records"]
        clusters = disease_data["clusters"]
        context_features = disease_data["context_features"]

        # Disease identity
        normalized_disease_name = asset_records[0].normalized_disease_name if asset_records else disease_key
        mondo_id = asset_records[0].mondo_id if asset_records else None
        therapeutic_area = asset_records[0].therapeutic_area if asset_records else None

        # Summaries
        program_count = len(asset_records)
        asset_count = len(disease_data["asset_records"]) if asset_records else 0
        company_count = len(disease_data["companies"])
        ticker_count = len(disease_data["tickers"])
        cluster_count = len(clusters)
        mechanism_count = len(disease_data["mechanisms"])
        target_count = len(disease_data["targets"])
        modality_count = len(disease_data["modalities"])

        # Approved incumbents
        approved_records = [r for r in asset_records if r.clinical_stage and "approved" in r.clinical_stage.lower()]
        approved_incumbent_count = len(approved_records)

        # Near-term readouts
        near_term_records = [
            r for r in context_features if r.next_readout_days is not None and r.next_readout_days <= 365
        ]
        near_term_readout_count = len(near_term_records)

        # Unknown programs
        unknown_count = len([r for r in asset_records if not r.mondo_id])

        # Build artifact
        artifact = {
            "artifact_type": "scientific_cartography_disease_map",
            "as_of_date": self.as_of_date,
            "created_at_utc": self.created_at_utc,
            "disease_key": disease_key,
            "safe_disease_slug": self._make_safe_slug(normalized_disease_name),
            "disease": {
                "raw_disease_names": sorted(disease_data["raw_names"]),
                "normalized_disease_name": normalized_disease_name,
                "mondo_id": mondo_id,
                "therapeutic_area": therapeutic_area,
                "parent_disease": asset_records[0].parent_disease if asset_records else None,
                "disease_warnings": [],
            },
            "summary": {
                "program_count": program_count,
                "asset_count": asset_count,
                "company_count": company_count,
                "ticker_count": ticker_count,
                "cluster_count": cluster_count,
                "mechanism_count": mechanism_count,
                "target_count": target_count,
                "modality_count": modality_count,
                "approved_incumbent_count": approved_incumbent_count,
                "near_term_readout_count": near_term_readout_count,
                "unknown_program_count": unknown_count,
                "source_ref_count": len(disease_data["source_refs"]),
            },
            "standard_of_care": {
                "approved_assets": sorted(set(r.asset_name for r in approved_records if r.asset_name)),
                "approved_companies": sorted(set(r.company_name for r in approved_records if r.company_name)),
                "approved_tickers": sorted(set(r.ticker for r in approved_records if r.ticker)),
                "approved_mechanisms": sorted(
                    set(
                        r.mechanism_class
                        for r in approved_records
                        if r.mechanism_class and "unknown" not in r.mechanism_class.lower()
                    )
                ),
                "source_refs": sorted(disease_data["source_refs"]),
            },
            "observed_tickers": sorted(disease_data["tickers"]),
            "programs": [self._record_to_dict(r) for r in asset_records],
            "clusters": [self._cluster_to_dict(c) for c in clusters],
            "context_features": [self._feature_to_dict(f) for f in context_features],
            "unknowns": {
                "missing_mondo_id_count": len([r for r in asset_records if not r.mondo_id]),
                "missing_ticker_count": len([r for r in asset_records if not r.ticker]),
                "missing_mechanism_count": len([r for r in asset_records if not r.mechanism_class]),
                "missing_target_count": len([r for r in asset_records if not r.target]),
                "missing_stage_count": len([r for r in asset_records if not r.clinical_stage]),
                "warnings": [],
            },
            "governance": {
                "read_only_diagnostic": True,
                "artifact_export_layer_only": True,
                "descriptive_not_scoring": True,
                "production_model_change": False,
                "ranker_change": False,
                "selector_change": False,
                "sizing_change": False,
                "final_score_change": False,
                "alpha_promotion": False,
            },
        }

        return artifact

    def _record_to_dict(self, record: AssetIndicationMapRecord) -> dict:
        """Convert asset indication record to flat dict for CSV/JSON.

        Args:
            record: AssetIndicationMapRecord.

        Returns:
            Flat dict.
        """
        return {
            "ticker": record.ticker,
            "company_name": record.company_name,
            "sponsor_name": record.sponsor_name,
            "asset_name": record.asset_name,
            "asset_id": record.asset_id,
            "raw_indication": record.raw_indication,
            "normalized_disease_name": record.normalized_disease_name,
            "mondo_id": record.mondo_id,
            "therapeutic_area": record.therapeutic_area,
            "mechanism_class": record.mechanism_class,
            "target": record.target,
            "modality": record.modality,
            "clinical_stage": record.clinical_stage,
            "source_type": record.source_type,
            "source_priority": record.source_priority,
            "confidence": round(record.overall_confidence, 4),
            "source_refs": json.dumps(record.source_refs or []),
            "warnings": json.dumps(record.warnings or []),
        }

    def _cluster_to_dict(self, cluster: EnhancedCompetitiveClusterRecord) -> dict:
        """Convert cluster to dict.

        Args:
            cluster: EnhancedCompetitiveClusterRecord.

        Returns:
            Dict.
        """
        return {
            "cluster_id": cluster.cluster_id,
            "cluster_key": cluster.cluster_key,
            "program_count": cluster.program_count,
            "asset_count": cluster.asset_count,
            "company_count": cluster.company_count,
            "ticker_count": cluster.ticker_count,
            "mechanism_class": cluster.mechanism_class,
            "target": cluster.target,
            "modality": cluster.modality,
        }

    def _feature_to_dict(self, feature: LandscapeContextFeatureRecord) -> dict:
        """Convert context feature to dict.

        Args:
            feature: LandscapeContextFeatureRecord.

        Returns:
            Dict.
        """
        return {
            "feature_id": feature.feature_id,
            "ticker": feature.ticker,
            "asset_name": feature.asset_name,
            "disease_competition_count": feature.disease_competition_count,
            "same_mechanism_competition_count": feature.same_mechanism_competition_count,
            "mechanism_novelty_category": feature.mechanism_novelty_category,
            "white_space_category": feature.white_space_category,
            "crowding_category": feature.crowding_category,
        }

    def _build_disease_csv_rows(
        self,
        artifact: dict,
    ) -> list[dict]:
        """Build CSV rows from disease artifact.

        Args:
            artifact: Disease artifact dict.

        Returns:
            List of flat dicts for CSV.
        """
        return artifact["programs"]

    def _build_disease_markdown(self, artifact: dict) -> str:
        """Build markdown report from disease artifact.

        Args:
            artifact: Disease artifact dict.

        Returns:
            Markdown string.
        """
        disease = artifact["disease"]
        summary = artifact["summary"]
        soc = artifact["standard_of_care"]

        md = f"""# {disease['normalized_disease_name']} — Scientific Map

## Governance

**Read-only diagnostic.**
Descriptive content only. No scoring, ranking, or portfolio implications.
Not intended as medical advice or investment recommendation.

## Disease Identity

- **MONDO ID:** {disease['mondo_id'] or 'Unmapped'}
- **Therapeutic Area:** {disease['therapeutic_area'] or 'Unknown'}
- **Parent Disease:** {disease['parent_disease'] or 'None'}
- **Raw Names Observed:** {', '.join(disease['raw_disease_names']) or 'None'}

## Landscape Summary

| Metric | Count |
|--------|-------|
| Programs | {summary['program_count']} |
| Assets | {summary['asset_count']} |
| Companies | {summary['company_count']} |
| Tickers | {summary['ticker_count']} |
| Clusters | {summary['cluster_count']} |
| Mechanisms | {summary['mechanism_count']} |
| Targets | {summary['target_count']} |
| Modalities | {summary['modality_count']} |

## Standard of Care / Approved Incumbents

**Approved Assets:** {', '.join(soc['approved_assets']) or 'None'}
**Approved Companies:** {', '.join(soc['approved_companies']) or 'None'}
**Approved Tickers:** {', '.join(soc['approved_tickers']) or 'None'}
**Approved Mechanisms:** {', '.join(soc['approved_mechanisms']) or 'None'}

## Observed Tickers

{', '.join(artifact['observed_tickers']) or 'None'}

## Unknowns and Low-Coverage Areas

| Field | Count |
|-------|-------|
| Missing MONDO ID | {artifact['unknowns']['missing_mondo_id_count']} |
| Missing Ticker | {artifact['unknowns']['missing_ticker_count']} |
| Missing Mechanism | {artifact['unknowns']['missing_mechanism_count']} |
| Missing Target | {artifact['unknowns']['missing_target_count']} |
| Missing Stage | {artifact['unknowns']['missing_stage_count']} |

## Source References

{', '.join(soc['source_refs'][:10]) or 'None'}
{f'... and {len(soc["source_refs"]) - 10} more references' if len(soc['source_refs']) > 10 else ''}

---

*Artifact: scientific_cartography_disease_map | Date: {artifact['as_of_date']} | Created: {artifact['created_at_utc']}*
"""
        return md

    def export_all(
        self,
        disease_ontology_records: list[DiseaseOntologyRecord],
        asset_indication_records: list[AssetIndicationMapRecord],
        enhanced_clusters: list[EnhancedCompetitiveClusterRecord],
        landscape_context_features: list[LandscapeContextFeatureRecord],
        output_dir: Path | str,
    ) -> None:
        """Export all disease map artifacts.

        Args:
            disease_ontology_records: Phase 8 records.
            asset_indication_records: Phase 9 records.
            enhanced_clusters: Phase 10 records.
            landscape_context_features: Phase 11 records.
            output_dir: Output directory.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Build ontology dict (keyed by mondo_id or normalized name)
        disease_ontology = {}
        for r in disease_ontology_records:
            key = r.mondo_id or r.normalized_disease_name
            disease_ontology[key] = r

        # Build disease index
        disease_index = self._build_disease_index(
            asset_indication_records,
            disease_ontology,
            enhanced_clusters,
            landscape_context_features,
        )

        # Build artifacts
        artifacts = {}
        for disease_key in sorted(disease_index.keys()):
            artifact = self._build_disease_artifact(
                disease_key,
                disease_index[disease_key],
            )
            artifacts[disease_key] = artifact

        # Write per-disease artifacts
        diseases_dir = output_dir / "diseases"
        diseases_dir.mkdir(parents=True, exist_ok=True)

        for disease_key, artifact in artifacts.items():
            safe_slug = artifact["safe_disease_slug"]
            disease_artifact_dir = diseases_dir / safe_slug
            disease_artifact_dir.mkdir(parents=True, exist_ok=True)

            # JSON
            write_json(disease_artifact_dir / "disease_map.json", artifact)

            # CSV
            csv_rows = self._build_disease_csv_rows(artifact)
            if csv_rows:
                write_csv(disease_artifact_dir / "disease_map.csv", csv_rows, list(csv_rows[0].keys()))

            # Markdown
            atomic_write_text(disease_artifact_dir / "disease_map.md", self._build_disease_markdown(artifact))

        # Write index
        self._write_index(artifacts, output_dir)

    def _write_index(self, artifacts: dict[str, dict], output_dir: Path) -> None:
        """Write index artifacts.

        Args:
            artifacts: Disease artifacts dict (keyed by disease_key).
            output_dir: Output directory.
        """
        # Count aggregates
        artifacts_list = list(artifacts.values())
        total_programs = sum(a["summary"]["program_count"] for a in artifacts_list)
        total_assets = sum(a["summary"]["asset_count"] for a in artifacts_list)
        total_companies = sum(a["summary"]["company_count"] for a in artifacts_list)
        total_tickers = sum(a["summary"]["ticker_count"] for a in artifacts_list)
        total_clusters = sum(a["summary"]["cluster_count"] for a in artifacts_list)
        total_context_features = sum(len(a["context_features"]) for a in artifacts_list)

        # Index JSON
        index_data = {
            "artifact_type": "scientific_cartography_disease_map_index",
            "as_of_date": self.as_of_date,
            "created_at_utc": self.created_at_utc,
            "disease_count": len(artifacts),
            "program_count": total_programs,
            "asset_count": total_assets,
            "company_count": total_companies,
            "ticker_count": total_tickers,
            "cluster_count": total_clusters,
            "context_feature_count": total_context_features,
            "diseases": [
                {
                    "disease_key": a["disease_key"],
                    "safe_disease_slug": a["safe_disease_slug"],
                    "normalized_disease_name": a["disease"]["normalized_disease_name"],
                    "mondo_id": a["disease"]["mondo_id"],
                    "therapeutic_area": a["disease"]["therapeutic_area"],
                    "program_count": a["summary"]["program_count"],
                    "asset_count": a["summary"]["asset_count"],
                    "company_count": a["summary"]["company_count"],
                    "ticker_count": a["summary"]["ticker_count"],
                    "cluster_count": a["summary"]["cluster_count"],
                    "artifact_paths": {
                        "json": f"diseases/{a['safe_disease_slug']}/disease_map.json",
                        "csv": f"diseases/{a['safe_disease_slug']}/disease_map.csv",
                        "md": f"diseases/{a['safe_disease_slug']}/disease_map.md",
                    },
                }
                for a in artifacts.values()
            ],
            "governance": {
                "read_only_diagnostic": True,
                "artifact_export_layer_only": True,
                "descriptive_not_scoring": True,
                "production_model_change": False,
                "ranker_change": False,
                "selector_change": False,
                "sizing_change": False,
                "final_score_change": False,
                "alpha_promotion": False,
            },
        }

        write_json(output_dir / "disease_map_index.json", index_data)

        # Index Markdown
        md = """# Scientific Cartography Disease Map Index

## Governance

**Read-only diagnostic.**
Descriptive summary only. No scoring, ranking, or portfolio implications.

## Summary

| Metric | Count |
|--------|-------|
| Diseases | {count_diseases} |
| Programs | {count_programs} |
| Assets | {count_assets} |
| Companies | {count_companies} |
| Tickers | {count_tickers} |
| Clusters | {count_clusters} |
| Context Features | {count_features} |

## Disease Maps

| Disease | MONDO | Therapeutic Area | Programs | Companies | Tickers | Clusters |
|---------|-------|-----------------|----------|-----------|---------|----------|
{disease_rows}

---

*Index: scientific_cartography_disease_map_index | Date: {as_of_date} | Created: {created_at_utc}*
""".format(
            count_diseases=len(artifacts),
            count_programs=total_programs,
            count_assets=total_assets,
            count_companies=total_companies,
            count_tickers=total_tickers,
            count_clusters=total_clusters,
            count_features=total_context_features,
            disease_rows="\n".join(
                f"| {a['disease']['normalized_disease_name']} | {a['disease']['mondo_id'] or 'Unmapped'} | {a['disease']['therapeutic_area'] or 'Unknown'} | {a['summary']['program_count']} | {a['summary']['company_count']} | {a['summary']['ticker_count']} | {a['summary']['cluster_count']} |"
                for a in artifacts.values()
            ),
            as_of_date=self.as_of_date,
            created_at_utc=self.created_at_utc,
        )

        atomic_write_text(output_dir / "disease_map_index.md", md)

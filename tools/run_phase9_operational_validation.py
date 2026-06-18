#!/usr/bin/env python3
"""Phase 9 Asset Indication Map operational validation.

Validates Phase 9 end-to-end with synthetic programs.
Tests disease ontology enrichment, record generation, deduplication, coverage reporting.
"""

import json
from datetime import datetime
from pathlib import Path

from scientific_cartography.build.asset_indication_map_builder import AssetIndicationMapBuilder
from scientific_cartography.build.disease_ontology_builder import DiseaseOntologyBuilder
from scientific_cartography.normalize.disease_normalizer import DiseaseNormalizer
from scientific_cartography.schemas.program_schema import ProgramRecord


def create_synthetic_programs() -> list[ProgramRecord]:
    """Create synthetic programs for validation."""
    return [
        # Public company, mapped disease
        ProgramRecord(
            program_id="prog_001",
            asset_id="asset_vx548",
            asset_name="VX-548",
            company_id="VRTX",
            ticker="VRTX",
            company_name="Vertex Pharmaceuticals",
            disease_id="disease_ad",
            disease_name="Atopic Dermatitis",
            mechanism_class="JAK1 Inhibitor",
            target="JAK1",
            modality="Small Molecule",
            clinical_stage="Phase 3",
            source_priority="ctgov",
            source_refs=["clinicaltrials.gov/ct2/show/NCT04514458"],
            confidence=0.95,
            as_of_date="2026-06-17",
        ),
        # Same company, different asset, same disease (should be separate record)
        ProgramRecord(
            program_id="prog_002",
            asset_id="asset_vx22",
            asset_name="VX-22",
            company_id="VRTX",
            ticker="VRTX",
            company_name="Vertex Pharmaceuticals",
            disease_id="disease_ad",
            disease_name="Atopic Dermatitis",
            mechanism_class="IRAK4 Inhibitor",
            target="IRAK4",
            modality="Small Molecule",
            clinical_stage="Phase 2",
            source_priority="investor_deck",
            source_refs=["vertex_investor_deck_2026.pdf"],
            confidence=0.85,
            as_of_date="2026-06-17",
        ),
        # Different disease
        ProgramRecord(
            program_id="prog_003",
            asset_id="asset_ips1",
            asset_name="IPS-1",
            company_id="IPSEN",
            ticker="IPSEY",
            company_name="Ipsen",
            disease_id="disease_mm",
            disease_name="Multiple Myeloma",
            mechanism_class="BCMA CAR-T",
            target="BCMA",
            modality="Cell Therapy",
            clinical_stage="Phase 2",
            source_priority="ctgov",
            source_refs=["clinicaltrials.gov/ct2/show/NCT04108481"],
            confidence=0.90,
            as_of_date="2026-06-17",
        ),
        # Unknown disease (tests preservation)
        ProgramRecord(
            program_id="prog_004",
            asset_id="asset_unkn1",
            asset_name="UNKN-1",
            company_id="PRIV",
            company_name="Private Biotech",
            disease_id="disease_unkn",
            disease_name="Rare Genetic Syndrome XYZ",
            mechanism_class="Gene Therapy",
            target="GENE_X",
            modality="Gene Therapy",
            clinical_stage="Preclinical",
            source_priority="manual",
            source_refs=["company_database"],
            confidence=0.60,
            as_of_date="2026-06-17",
        ),
        # Missing ticker (public company, no ticker)
        ProgramRecord(
            program_id="prog_005",
            asset_id="asset_gild1",
            asset_name="GS-1234",
            company_id="GILD",
            ticker=None,
            company_name="Gilead Sciences",
            disease_id="disease_hcv",
            disease_name="Hepatitis C",
            mechanism_class="NS5A Inhibitor",
            target="NS5A",
            modality="Small Molecule",
            clinical_stage="Phase 3",
            source_priority="fda",
            source_refs=["FDA_approval_label"],
            confidence=0.98,
            as_of_date="2026-06-17",
        ),
    ]


def run_validation() -> dict:
    """Run Phase 9 operational validation."""
    print("=" * 80)
    print("Phase 9 Asset Indication Map Operational Validation")
    print("=" * 80)
    print()

    # Initialize components
    print("[1/5] Initializing disease normalizer and builders...")
    mondo_cache = {
        "atopic dermatitis": {
            "id": "MONDO:0004980",
            "name": "Atopic Dermatitis",
            "synonyms": ["AD", "eczema", "atopic eczema"],
            "therapeutic_area": "Dermatology",
            "parent_disease": "Skin Diseases",
        },
        "multiple myeloma": {
            "id": "MONDO:0018874",
            "name": "Multiple Myeloma",
            "synonyms": ["MM", "myeloma"],
            "therapeutic_area": "Oncology",
            "parent_disease": "Blood Cancers",
        },
        "hepatitis c": {
            "id": "MONDO:0005154",
            "name": "Hepatitis C",
            "synonyms": ["HCV", "hepatitis c virus"],
            "therapeutic_area": "Infectious Disease",
            "parent_disease": "Viral Infections",
        },
    }

    disease_normalizer = DiseaseNormalizer(mondo_cache=mondo_cache, as_of_date="2026-06-17")
    disease_ontology_builder = DiseaseOntologyBuilder(
        as_of_date="2026-06-17",
        disease_normalizer=disease_normalizer,
    )
    asset_indication_builder = AssetIndicationMapBuilder(
        as_of_date="2026-06-17",
        disease_ontology_builder=disease_ontology_builder,
    )
    print("✓ Builders initialized")
    print()

    # Create synthetic programs
    print("[2/5] Creating synthetic programs...")
    programs = create_synthetic_programs()
    print(f"✓ Created {len(programs)} programs")
    for prog in programs:
        print(f"  - {prog.program_id}: {prog.company_name} / {prog.asset_name} / {prog.disease_name}")
    print()

    # Build asset indication map
    print("[3/5] Building asset indication map...")
    records, coverage = asset_indication_builder.build_from_programs(programs)
    print("✓ Generated {} records".format(len(records)))
    print("✓ Coverage report complete")
    print()

    # Validate records
    print("[4/5] Validating records...")
    validation_results = {
        "total_records": len(records),
        "expected_records": 5,
        "records_with_mondo": 0,
        "records_without_mondo": 0,
        "governance_check": True,
        "records_by_source_type": {},
    }

    for i, record in enumerate(records):
        print(f"  Record {i+1}:")
        print(f"    - record_id: {record.record_id}")
        print(f"    - company: {record.company_name} ({record.ticker or 'no ticker'})")
        print(f"    - asset: {record.asset_name}")
        print(f"    - disease: {record.normalized_disease_name} ({record.mondo_id or 'unmapped'})")
        print(f"    - source: {record.source_type} (priority {record.source_priority})")
        print(f"    - confidence: {record.overall_confidence:.2f}")

        # Check governance
        if not record.governance.get("read_only_diagnostic", False):
            validation_results["governance_check"] = False
        if record.governance.get("production_model_change", False):
            validation_results["governance_check"] = False

        # Count mondo mappings
        if record.mondo_id:
            validation_results["records_with_mondo"] += 1
        else:
            validation_results["records_without_mondo"] += 1

        # Track source types
        if record.source_type not in validation_results["records_by_source_type"]:
            validation_results["records_by_source_type"][record.source_type] = 0
        validation_results["records_by_source_type"][record.source_type] += 1

    print(f"✓ All {len(records)} records validated")
    print()

    # Validate coverage report
    print("[5/5] Validating coverage report...")
    coverage_results = {
        "total_records": coverage.total_records,
        "unique_companies": coverage.unique_companies,
        "unique_tickers": coverage.unique_tickers,
        "unique_assets": coverage.unique_assets,
        "unique_mondo_diseases": coverage.unique_mondo_diseases,
        "mapped_disease_count": coverage.mapped_disease_count,
        "unknown_disease_count": coverage.unknown_disease_count,
        "records_by_source_type": coverage.records_by_source_type,
        "records_with_ticker": coverage.records_with_ticker,
        "records_without_ticker": coverage.records_without_ticker,
        "governance_check": (
            coverage.governance.get("read_only_diagnostic", False)
            and not coverage.governance.get("production_model_change", False)
        ),
    }

    print("  Coverage metrics:")
    print(f"    - Total records: {coverage.total_records}")
    print(f"    - Unique companies: {coverage.unique_companies}")
    print(f"    - Unique tickers: {coverage.unique_tickers}")
    print(f"    - Unique assets: {coverage.unique_assets}")
    print(f"    - Unique MONDO diseases: {coverage.unique_mondo_diseases}")
    print(f"    - Mapped diseases: {coverage.mapped_disease_count}")
    print(f"    - Unknown diseases: {coverage.unknown_disease_count}")
    print(f"    - Records with ticker: {coverage.records_with_ticker}")
    print(f"    - Records without ticker: {coverage.records_without_ticker}")
    print(f"    - Governance OK: {coverage_results['governance_check']}")
    print()

    # Compile results
    print("=" * 80)
    print("Validation Results Summary")
    print("=" * 80)
    print()

    all_valid = True

    # Check record counts
    if validation_results["total_records"] == validation_results["expected_records"]:
        print("✓ Record count: PASS (5 records generated as expected)")
    else:
        print(
            f"✗ Record count: FAIL (expected {validation_results['expected_records']}, got {validation_results['total_records']})"
        )
        all_valid = False

    # Check mondo mapping (at least 3 mapped: AD, MM, HCV; may have 4 if dedup doesn't affect all)
    if validation_results["records_with_mondo"] >= 3:
        print(f"✓ MONDO mapping: PASS ({validation_results['records_with_mondo']} mapped)")
    else:
        print(f"✗ MONDO mapping: FAIL (expected ≥3 mapped, got {validation_results['records_with_mondo']})")
        all_valid = False

    # Check unknown preservation
    if validation_results["records_without_mondo"] >= 1:
        print("✓ Unknown disease preservation: PASS (unknown disease preserved)")
    else:
        print("✗ Unknown disease preservation: FAIL (no unknown diseases preserved)")
        all_valid = False

    # Check governance
    if validation_results["governance_check"]:
        print("✓ Governance flags: PASS (all records read-only diagnostic)")
    else:
        print("✗ Governance flags: FAIL (governance flags not set correctly)")
        all_valid = False

    # Check coverage governance
    if coverage_results["governance_check"]:
        print("✓ Coverage governance: PASS (coverage report read-only diagnostic)")
    else:
        print("✗ Coverage governance: FAIL (coverage governance not set correctly)")
        all_valid = False

    # Check source priority mapping
    expected_sources = {"ctgov", "investor_deck", "fda", "manual"}
    actual_sources = set(validation_results["records_by_source_type"].keys())
    if expected_sources.issubset(actual_sources):
        print(f"✓ Source priority mapping: PASS ({actual_sources})")
    else:
        print(f"✗ Source priority mapping: FAIL (missing {expected_sources - actual_sources})")
        all_valid = False

    # Check ticker handling (prog_001,002,003 have tickers; prog_004,005 don't = 3 with, 2 without)
    if coverage_results["records_with_ticker"] + coverage_results["records_without_ticker"] == 5:
        print(
            f"✓ Ticker handling: PASS ({coverage_results['records_with_ticker']} with, {coverage_results['records_without_ticker']} without)"
        )
    else:
        print(
            f"✗ Ticker handling: FAIL (total mismatch; got {coverage_results['records_with_ticker']} with, {coverage_results['records_without_ticker']} without)"
        )
        all_valid = False

    print()
    print("=" * 80)

    overall_status = "PASS" if all_valid else "FAIL"
    print(f"Overall Status: {overall_status}")
    print()

    return {
        "status": overall_status,
        "timestamp": datetime.now().isoformat(),
        "as_of_date": "2026-06-17",
        "validation": {
            "record_count": validation_results,
            "coverage": coverage_results,
        },
        "records_sample": [record.to_dict() for record in records[:2]],
    }


def main():
    """Run validation and save results."""
    results = run_validation()

    # Save results
    output_dir = Path("artifacts/phase9_operational_validation")
    output_dir.mkdir(parents=True, exist_ok=True)

    results_file = output_dir / "2026-06-17_validation_results.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Results saved to {results_file}")

    # Exit with appropriate code
    exit(0 if results["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()

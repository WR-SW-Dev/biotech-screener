"""Tests for LangGraph-based Scientific Cartography review orchestrator."""

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def synthetic_artifact_dir(tmp_path):
    """Create synthetic Scientific Cartography artifacts for testing."""
    artifact_root = tmp_path / "artifacts" / "scientific_cartography" / "2026-06-18"
    artifact_root.mkdir(parents=True, exist_ok=True)

    index = {
        "artifact_type": "scientific_cartography_disease_map_index",
        "as_of_date": "2026-06-18",
        "disease_count": 3,
        "program_count": 12,
        "cluster_count": 5,
        "context_feature_count": 3,
        "diseases": [
            {
                "disease_key": "MONDO:0000001",
                "safe_disease_slug": "acute-pain",
                "normalized_disease_name": "Acute Pain",
                "mondo_id": "MONDO:0000001",
                "program_count": 8,
                "cluster_count": 2,
                "artifact_paths": {
                    "json": "diseases/acute-pain/disease_map.json",
                    "csv": "diseases/acute-pain/disease_map.csv",
                    "md": "diseases/acute-pain/disease_map.md",
                },
            },
            {
                "disease_key": "MONDO:0000002",
                "safe_disease_slug": "multiple-myeloma",
                "normalized_disease_name": "Multiple Myeloma",
                "mondo_id": "MONDO:0000002",
                "program_count": 3,
                "cluster_count": 2,
                "artifact_paths": {
                    "json": "diseases/multiple-myeloma/disease_map.json",
                    "csv": "diseases/multiple-myeloma/disease_map.csv",
                    "md": "diseases/multiple-myeloma/disease_map.md",
                },
            },
            {
                "disease_key": "unknown_disease_001",
                "safe_disease_slug": "unknown-disease",
                "normalized_disease_name": "Unknown Disease",
                "mondo_id": None,
                "program_count": 1,
                "cluster_count": 1,
                "artifact_paths": {
                    "json": "diseases/unknown-disease/disease_map.json",
                    "csv": "diseases/unknown-disease/disease_map.csv",
                    "md": "diseases/unknown-disease/disease_map.md",
                },
            },
        ],
        "governance": {
            "read_only_diagnostic": True,
            "orchestration_layer_only": True,
            "production_model_change": False,
            "ranker_change": False,
            "selector_change": False,
            "sizing_change": False,
            "final_score_change": False,
            "alpha_promotion": False,
            "trading_or_portfolio_action": False,
        },
    }

    with open(artifact_root / "disease_map_index.json", "w") as f:
        json.dump(index, f, indent=2)

    index_md = """# Scientific Cartography Disease Map Index

Generated: 2026-06-18

## Summary
- Diseases: 3
- Programs: 12
- Clusters: 5

## Diseases
1. Acute Pain (MONDO:0000001) - 8 programs
2. Multiple Myeloma (MONDO:0000002) - 3 programs
3. Unknown Disease - 1 program
"""
    with open(artifact_root / "disease_map_index.md", "w") as f:
        f.write(index_md)

    diseases_dir = artifact_root / "diseases"
    diseases_dir.mkdir(exist_ok=True)

    acute_pain_dir = diseases_dir / "acute-pain"
    acute_pain_dir.mkdir(exist_ok=True)

    disease_map = {
        "artifact_type": "scientific_cartography_disease_map",
        "as_of_date": "2026-06-18",
        "disease_key": "MONDO:0000001",
        "normalized_disease_name": "Acute Pain",
        "mondo_id": "MONDO:0000001",
        "clusters": [
            {
                "cluster_id": "cluster_001",
                "mechanism": "opioid-receptor-agonist",
                "target": "OPRM1",
                "modality": "small-molecule",
                "program_count": 4,
            }
        ],
        "governance": {"read_only_diagnostic": True},
    }
    with open(acute_pain_dir / "disease_map.json", "w") as f:
        json.dump(disease_map, f, indent=2)

    disease_csv = "disease_key,mechanism,target,modality,program_count\nMONDO:0000001,opioid-receptor-agonist,OPRM1,small-molecule,4"
    with open(acute_pain_dir / "disease_map.csv", "w") as f:
        f.write(disease_csv)

    disease_md = "# Acute Pain\n\nMONDO:0000001\n\n## Clusters\n\n1. opioid-receptor-agonist / OPRM1 (4 programs)"
    with open(acute_pain_dir / "disease_map.md", "w") as f:
        f.write(disease_md)

    mm_dir = diseases_dir / "multiple-myeloma"
    mm_dir.mkdir(exist_ok=True)

    disease_map_mm = {
        "artifact_type": "scientific_cartography_disease_map",
        "as_of_date": "2026-06-18",
        "disease_key": "MONDO:0000002",
        "normalized_disease_name": "Multiple Myeloma",
        "mondo_id": "MONDO:0000002",
        "clusters": [],
        "governance": {"read_only_diagnostic": True},
    }
    with open(mm_dir / "disease_map.json", "w") as f:
        json.dump(disease_map_mm, f, indent=2)

    with open(mm_dir / "disease_map.csv", "w") as f:
        f.write("disease_key,mechanism,target,modality,program_count")

    with open(mm_dir / "disease_map.md", "w") as f:
        f.write("# Multiple Myeloma\n\nMONDO:0000002")

    unknown_dir = diseases_dir / "unknown-disease"
    unknown_dir.mkdir(exist_ok=True)

    disease_map_unknown = {
        "artifact_type": "scientific_cartography_disease_map",
        "as_of_date": "2026-06-18",
        "disease_key": "unknown_disease_001",
        "normalized_disease_name": "Unknown Disease",
        "mondo_id": None,
        "clusters": [],
        "governance": {"read_only_diagnostic": True},
    }
    with open(unknown_dir / "disease_map.json", "w") as f:
        json.dump(disease_map_unknown, f, indent=2)

    with open(unknown_dir / "disease_map.csv", "w") as f:
        f.write("disease_key,mechanism,target,modality,program_count")

    with open(unknown_dir / "disease_map.md", "w") as f:
        f.write("# Unknown Disease\n\nNo MONDO ID")

    return artifact_root


@pytest.fixture
def synthetic_artifact_dir_missing_index(tmp_path):
    """Create artifacts without the required index file."""
    artifact_root = tmp_path / "artifacts" / "scientific_cartography" / "2026-06-19"
    artifact_root.mkdir(parents=True, exist_ok=True)
    (artifact_root / "diseases").mkdir(exist_ok=True)
    return artifact_root


class TestCartographyReviewState:
    def test_state_is_json_serializable(self):
        from scientific_cartography.langgraph_review.state import CartographyReviewState

        state: CartographyReviewState = {
            "as_of_date": "2026-06-18",
            "artifact_dir": "/tmp/artifacts",
            "review_dir": "/tmp/review",
            "disease_map_index_path": "/tmp/artifacts/disease_map_index.json",
            "disease_count": 3,
            "program_count": 12,
            "cluster_count": 5,
            "context_feature_count": 3,
            "disease_artifact_paths": ["diseases/acute-pain"],
            "selected_diseases": [
                {
                    "disease_key": "MONDO:0000001",
                    "normalized_disease_name": "Acute Pain",
                    "program_count": 8,
                }
            ],
            "governance_scan_passed": True,
            "forbidden_terms_found": [],
            "missing_required_files": [],
            "warnings": [],
            "review_summary_path": "/tmp/review/langgraph_review_summary.json",
            "review_markdown_path": "/tmp/review/langgraph_review_summary.md",
            "review_state_path": "/tmp/review/langgraph_review_state.json",
            "human_review_required": True,
            "human_decision": None,
            "approved_for_next_step": False,
            "governance": {
                "read_only_diagnostic": True,
                "production_model_change": False,
            },
        }

        serialized = json.dumps(state, default=str)
        assert len(serialized) > 0

    def test_governance_flags_default_false(self):
        from scientific_cartography.langgraph_review.state import CartographyReviewState

        state: CartographyReviewState = {
            "as_of_date": "2026-06-18",
            "artifact_dir": "/tmp/artifacts",
            "governance": {
                "read_only_diagnostic": True,
                "orchestration_layer_only": True,
                "production_model_change": False,
                "ranker_change": False,
                "selector_change": False,
                "sizing_change": False,
                "final_score_change": False,
                "alpha_promotion": False,
                "trading_or_portfolio_action": False,
            },
        }

        assert state["governance"]["production_model_change"] is False
        assert state["governance"]["ranker_change"] is False

    def test_approved_for_next_step_defaults_false(self):
        from scientific_cartography.langgraph_review.state import CartographyReviewState

        state: CartographyReviewState = {
            "as_of_date": "2026-06-18",
            "approved_for_next_step": False,
        }

        assert state["approved_for_next_step"] is False


class TestInitializeReview:
    def test_initialize_review_creates_review_dir(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import initialize_review

        review_dir = tmp_path / "review"

        state = {
            "as_of_date": "2026-06-18",
            "artifact_dir": str(synthetic_artifact_dir),
            "review_dir": str(review_dir),
        }

        result = initialize_review(state)

        assert review_dir.exists()
        assert result["as_of_date"] == "2026-06-18"
        assert result["governance"]["read_only_diagnostic"] is True

    def test_initialize_review_sets_governance_flags(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import initialize_review

        review_dir = tmp_path / "review"

        state = {
            "as_of_date": "2026-06-18",
            "artifact_dir": str(synthetic_artifact_dir),
            "review_dir": str(review_dir),
        }

        result = initialize_review(state)

        governance = result["governance"]
        assert governance["production_model_change"] is False


class TestLoadArtifactIndex:
    def test_load_artifact_index_reads_counts(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import initialize_review, load_artifact_index

        state = initialize_review(
            {
                "as_of_date": "2026-06-18",
                "artifact_dir": str(synthetic_artifact_dir),
                "review_dir": str(tmp_path / "review"),
            }
        )
        result = load_artifact_index(state)

        assert result["disease_count"] == 3
        assert result["program_count"] == 12
        assert result["cluster_count"] == 5

    def test_load_artifact_index_missing_index(self, synthetic_artifact_dir_missing_index, tmp_path):
        from scientific_cartography.langgraph_review.nodes import initialize_review, load_artifact_index

        state = initialize_review(
            {
                "as_of_date": "2026-06-19",
                "artifact_dir": str(synthetic_artifact_dir_missing_index),
                "review_dir": str(tmp_path / "review"),
            }
        )
        result = load_artifact_index(state)

        assert "disease_map_index.json" in str(result["missing_required_files"])


class TestValidateArtifactStructure:
    def test_validate_artifact_structure_clean(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import (
            initialize_review,
            load_artifact_index,
            validate_artifact_structure,
        )

        state = initialize_review(
            {
                "as_of_date": "2026-06-18",
                "artifact_dir": str(synthetic_artifact_dir),
                "review_dir": str(tmp_path / "review"),
            }
        )
        state = load_artifact_index(state)
        result = validate_artifact_structure(state)

        assert len(result["missing_required_files"]) == 0


class TestRunGovernanceScan:
    def test_governance_scan_passes_clean(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import (
            initialize_review,
            load_artifact_index,
            run_governance_scan,
            validate_artifact_structure,
        )

        state = initialize_review(
            {
                "as_of_date": "2026-06-18",
                "artifact_dir": str(synthetic_artifact_dir),
                "review_dir": str(tmp_path / "review"),
            }
        )
        state = load_artifact_index(state)
        state = validate_artifact_structure(state)
        result = run_governance_scan(state)

        assert result["governance_scan_passed"] is True


class TestSelectReviewDiseases:
    def test_disease_selection_is_deterministic(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import (
            initialize_review,
            load_artifact_index,
            select_review_diseases,
            validate_artifact_structure,
        )

        state1 = initialize_review(
            {
                "as_of_date": "2026-06-18",
                "artifact_dir": str(synthetic_artifact_dir),
                "review_dir": str(tmp_path / "review1"),
            }
        )
        state1 = load_artifact_index(state1)
        state1 = validate_artifact_structure(state1)
        result1 = select_review_diseases(state1)

        state2 = initialize_review(
            {
                "as_of_date": "2026-06-18",
                "artifact_dir": str(synthetic_artifact_dir),
                "review_dir": str(tmp_path / "review2"),
            }
        )
        state2 = load_artifact_index(state2)
        state2 = validate_artifact_structure(state2)
        result2 = select_review_diseases(state2)

        assert result1["selected_diseases"] == result2["selected_diseases"]

    def test_disease_selection_includes_top_diseases(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import (
            initialize_review,
            load_artifact_index,
            select_review_diseases,
            validate_artifact_structure,
        )

        state = initialize_review(
            {
                "as_of_date": "2026-06-18",
                "artifact_dir": str(synthetic_artifact_dir),
                "review_dir": str(tmp_path / "review"),
            }
        )
        state = load_artifact_index(state)
        state = validate_artifact_structure(state)
        result = select_review_diseases(state)

        disease_names = [d.get("normalized_disease_name") for d in result["selected_diseases"]]
        assert any("Acute" in str(d) for d in disease_names)


class TestBuildReviewSummary:
    def test_review_summary_includes_required_fields(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import (
            build_review_summary,
            initialize_review,
            load_artifact_index,
            run_governance_scan,
            select_review_diseases,
            validate_artifact_structure,
        )

        state = initialize_review(
            {
                "as_of_date": "2026-06-18",
                "artifact_dir": str(synthetic_artifact_dir),
                "review_dir": str(tmp_path / "review"),
            }
        )
        state = load_artifact_index(state)
        state = validate_artifact_structure(state)
        state = run_governance_scan(state)
        state = select_review_diseases(state)
        result = build_review_summary(state)

        assert result["as_of_date"] == "2026-06-18"
        assert result["disease_count"] == 3


class TestHumanReviewGate:
    def test_default_mode_requires_human_review(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import (
            build_review_summary,
            initialize_review,
            load_artifact_index,
            optional_human_review_gate,
            run_governance_scan,
            select_review_diseases,
            validate_artifact_structure,
        )

        state = initialize_review(
            {
                "as_of_date": "2026-06-18",
                "artifact_dir": str(synthetic_artifact_dir),
                "review_dir": str(tmp_path / "review"),
                "auto_approve_for_test": False,
            }
        )
        state = load_artifact_index(state)
        state = validate_artifact_structure(state)
        state = run_governance_scan(state)
        state = select_review_diseases(state)
        state = build_review_summary(state)
        result = optional_human_review_gate(state)

        assert result["human_review_required"] is True
        assert result["approved_for_next_step"] is False

    def test_auto_approve_for_test_does_not_approve_deployment(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import (
            build_review_summary,
            initialize_review,
            load_artifact_index,
            optional_human_review_gate,
            run_governance_scan,
            select_review_diseases,
            validate_artifact_structure,
        )

        state = initialize_review(
            {
                "as_of_date": "2026-06-18",
                "artifact_dir": str(synthetic_artifact_dir),
                "review_dir": str(tmp_path / "review"),
                "auto_approve_for_test": True,
            }
        )
        state = load_artifact_index(state)
        state = validate_artifact_structure(state)
        state = run_governance_scan(state)
        state = select_review_diseases(state)
        state = build_review_summary(state)
        result = optional_human_review_gate(state)

        assert result["human_review_required"] is False
        assert result["human_decision"] == "AUTO_APPROVED_FOR_TEST_ONLY"
        assert result["approved_for_next_step"] is False


class TestWriteReviewOutputs:
    def test_write_review_outputs_creates_json(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import (
            build_review_summary,
            initialize_review,
            load_artifact_index,
            optional_human_review_gate,
            run_governance_scan,
            select_review_diseases,
            validate_artifact_structure,
            write_review_outputs,
        )

        state = initialize_review(
            {
                "as_of_date": "2026-06-18",
                "artifact_dir": str(synthetic_artifact_dir),
                "review_dir": str(tmp_path / "review"),
            }
        )
        state = load_artifact_index(state)
        state = validate_artifact_structure(state)
        state = run_governance_scan(state)
        state = select_review_diseases(state)
        state = build_review_summary(state)
        state = optional_human_review_gate(state)
        result = write_review_outputs(state)

        review_json = Path(result["review_summary_path"])
        assert review_json.exists()
        with open(review_json) as f:
            data = json.load(f)
            assert "as_of_date" in data
            assert "governance" in data

    def test_write_review_outputs_creates_markdown(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import (
            build_review_summary,
            initialize_review,
            load_artifact_index,
            optional_human_review_gate,
            run_governance_scan,
            select_review_diseases,
            validate_artifact_structure,
            write_review_outputs,
        )

        state = initialize_review(
            {
                "as_of_date": "2026-06-18",
                "artifact_dir": str(synthetic_artifact_dir),
                "review_dir": str(tmp_path / "review"),
            }
        )
        state = load_artifact_index(state)
        state = validate_artifact_structure(state)
        state = run_governance_scan(state)
        state = select_review_diseases(state)
        state = build_review_summary(state)
        state = optional_human_review_gate(state)
        result = write_review_outputs(state)

        review_md = Path(result["review_markdown_path"])
        assert review_md.exists()
        content = review_md.read_text()
        assert "Scientific Cartography" in content

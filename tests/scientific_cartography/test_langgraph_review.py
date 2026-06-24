"""Tests for LangGraph-based Scientific Cartography review orchestrator."""

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def synthetic_artifact_dir(tmp_path):
    """Synthetic artifacts using the current flat JSONL schema (map_index.json + JSONL files)."""
    artifact_root = tmp_path / "artifacts" / "scientific_cartography" / "2026-06-18"
    artifact_root.mkdir(parents=True, exist_ok=True)

    # map_index.json — counts are nested under "counts", diseases use disease_id/disease_name.
    index = {
        "artifact_type": "scientific_cartography_map_index",
        "as_of_date": "2026-06-18",
        "counts": {
            "disease_count": 3,
            "program_records": 12,
            "competitive_clusters": 5,
            "landscape_features": 3,
            "ticker_count": 2,
            "known_mechanism_programs": 4,
            "unknown_mechanism_programs": 8,
        },
        "diseases": [
            {
                "disease_id": "DISEASE_aabbccdd00000001",
                "disease_name": "Acute Pain",
                "therapeutic_area": None,
                "program_count": 8,
                "cluster_count": 2,
                "public_tickers": ["PTGX", "CRBU"],
                "known_mechanism_count": 2,
                "unknown_mechanism_count": 6,
                "feature_count": 1,
                "source_refs_count": 3,
                "stage_distribution": {
                    "phase1": 2,
                    "phase2": 4,
                    "phase3": 2,
                    "approved": 0,
                    "filed": 0,
                    "preclinical": 0,
                    "discontinued": 0,
                    "unknown": 0,
                },
            },
            {
                "disease_id": "DISEASE_aabbccdd00000002",
                "disease_name": "Multiple Myeloma",
                "therapeutic_area": None,
                "program_count": 3,
                "cluster_count": 2,
                "public_tickers": ["JANX"],
                "known_mechanism_count": 1,
                "unknown_mechanism_count": 2,
                "feature_count": 1,
                "source_refs_count": 1,
                "stage_distribution": {
                    "phase1": 1,
                    "phase2": 1,
                    "phase3": 1,
                    "approved": 0,
                    "filed": 0,
                    "preclinical": 0,
                    "discontinued": 0,
                    "unknown": 0,
                },
            },
            {
                "disease_id": "DISEASE_aabbccdd00000003",
                "disease_name": "Unknown Disease",
                "therapeutic_area": None,
                "program_count": 1,
                "cluster_count": 1,
                "public_tickers": [],
                "known_mechanism_count": 0,
                "unknown_mechanism_count": 1,
                "feature_count": 1,
                "source_refs_count": 0,
                "stage_distribution": {
                    "phase1": 0,
                    "phase2": 0,
                    "phase3": 0,
                    "approved": 0,
                    "filed": 0,
                    "preclinical": 1,
                    "discontinued": 0,
                    "unknown": 0,
                },
            },
        ],
        "governance": {"read_only_diagnostic": True},
        "warnings": [],
    }
    with open(artifact_root / "map_index.json", "w") as f:
        json.dump(index, f, indent=2)

    # Flat JSONL artifacts checked by validate_artifact_structure.
    def _write_jsonl(path, records):
        with open(path, "w") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")

    _write_jsonl(
        artifact_root / "program_records.jsonl",
        [
            {
                "disease_id": "DISEASE_aabbccdd00000001",
                "disease_name": "Acute Pain",
                "ticker": "PTGX",
                "mechanism": "unknown",
                "stage": "phase2",
            },
        ],
    )
    _write_jsonl(
        artifact_root / "competitive_clusters.jsonl",
        [
            {
                "cluster_id": "CLU_001",
                "disease_id": "DISEASE_aabbccdd00000001",
                "program_count": 4,
                "public_program_count": 2,
            },
        ],
    )
    _write_jsonl(
        artifact_root / "landscape_features.jsonl",
        [
            {"disease_id": "DISEASE_aabbccdd00000001", "feature_type": "crowding", "value": 0.5},
        ],
    )

    # Taxonomy summary MD — intentionally contains medical "alpha" and "weight"
    # to verify governance scan does NOT scan this file.
    (artifact_root / "disease_map_summary.md").write_text(
        "# Disease Map Summary\n\n" "## Alpha-1 Antitrypsin Deficiency\n" "Body Weight Changes — 3 programs.\n"
    )

    return artifact_root


@pytest.fixture
def synthetic_artifact_dir_missing_index(tmp_path):
    """Artifact directory with none of the required flat files."""
    artifact_root = tmp_path / "artifacts" / "scientific_cartography" / "2026-06-19"
    artifact_root.mkdir(parents=True, exist_ok=True)
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

        assert "map_index.json" in str(result["missing_required_files"])

    def test_load_artifact_index_counts_from_nested_dict(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import initialize_review, load_artifact_index

        state = initialize_review(
            {
                "as_of_date": "2026-06-18",
                "artifact_dir": str(synthetic_artifact_dir),
                "review_dir": str(tmp_path / "review"),
            }
        )
        result = load_artifact_index(state)

        # Counts live under index["counts"] in the current schema, not at the top level.
        assert result["disease_count"] == 3
        assert result["program_count"] == 12
        assert result["cluster_count"] == 5
        assert result["context_feature_count"] == 3

    def test_load_artifact_index_uses_disease_id(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import initialize_review, load_artifact_index

        state = initialize_review(
            {
                "as_of_date": "2026-06-18",
                "artifact_dir": str(synthetic_artifact_dir),
                "review_dir": str(tmp_path / "review"),
            }
        )
        result = load_artifact_index(state)

        paths = result["disease_artifact_paths"]
        assert len(paths) == 3
        assert all(p.startswith("DISEASE_") for p in paths)


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

    def test_validate_artifact_structure_missing_jsonl(self, tmp_path):
        from scientific_cartography.langgraph_review.nodes import initialize_review, validate_artifact_structure

        artifact_root = tmp_path / "artifacts" / "2026-06-18"
        artifact_root.mkdir(parents=True)
        # Only map_index.json present — the 3 JSONL files are missing.
        (artifact_root / "map_index.json").write_text("{}")

        state = initialize_review(
            {
                "as_of_date": "2026-06-18",
                "artifact_dir": str(artifact_root),
                "review_dir": str(tmp_path / "review"),
            }
        )
        result = validate_artifact_structure(state)

        assert "program_records.jsonl" in result["missing_required_files"]
        assert "competitive_clusters.jsonl" in result["missing_required_files"]
        assert "landscape_features.jsonl" in result["missing_required_files"]

    def test_validate_artifact_structure_all_missing(self, synthetic_artifact_dir_missing_index, tmp_path):
        from scientific_cartography.langgraph_review.nodes import initialize_review, validate_artifact_structure

        state = initialize_review(
            {
                "as_of_date": "2026-06-19",
                "artifact_dir": str(synthetic_artifact_dir_missing_index),
                "review_dir": str(tmp_path / "review"),
            }
        )
        result = validate_artifact_structure(state)

        assert "map_index.json" in result["missing_required_files"]
        assert len(result["missing_required_files"]) == 4


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

    def test_governance_scan_does_not_false_positive_on_taxonomy(self, synthetic_artifact_dir, tmp_path):
        """disease_map_summary.md contains medical 'alpha'/'weight' — must not trigger FAIL."""
        from scientific_cartography.langgraph_review.nodes import initialize_review, run_governance_scan

        state = initialize_review(
            {
                "as_of_date": "2026-06-18",
                "artifact_dir": str(synthetic_artifact_dir),
                "review_dir": str(tmp_path / "review"),
            }
        )
        result = run_governance_scan(state)

        assert result["governance_scan_passed"] is True
        assert result["forbidden_terms_found"] == []

    def test_governance_scan_no_forbidden_terms_without_artifacts(self, synthetic_artifact_dir_missing_index, tmp_path):
        from scientific_cartography.langgraph_review.nodes import initialize_review, run_governance_scan

        state = initialize_review(
            {
                "as_of_date": "2026-06-19",
                "artifact_dir": str(synthetic_artifact_dir_missing_index),
                "review_dir": str(tmp_path / "review"),
            }
        )
        result = run_governance_scan(state)

        assert result["governance_scan_passed"] is True
        assert result["forbidden_terms_found"] == []


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

        disease_names = [d.get("disease_name") for d in result["selected_diseases"]]
        assert any("Acute" in str(d) for d in disease_names)

    def test_disease_selection_output_uses_disease_id(self, synthetic_artifact_dir, tmp_path):
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

        selected = result["selected_diseases"]
        assert len(selected) > 0
        for d in selected:
            assert "disease_id" in d
            assert "disease_name" in d
            assert "public_tickers" in d
            # Old schema keys must not appear.
            assert "disease_key" not in d
            assert "normalized_disease_name" not in d
            assert "mondo_id" not in d

    def test_disease_selection_top_by_program_count(self, synthetic_artifact_dir, tmp_path):
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

        # First selected disease must have the highest program_count (8 > 3 > 1).
        first = result["selected_diseases"][0]
        assert first["program_count"] == 8


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
        assert result["program_count"] == 12
        assert result["cluster_count"] == 5

    def test_review_summary_blocked_when_index_missing(self, synthetic_artifact_dir_missing_index, tmp_path):
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
                "as_of_date": "2026-06-19",
                "artifact_dir": str(synthetic_artifact_dir_missing_index),
                "review_dir": str(tmp_path / "review"),
            }
        )
        state = load_artifact_index(state)
        state = validate_artifact_structure(state)
        state = run_governance_scan(state)
        state = select_review_diseases(state)
        result = build_review_summary(state)

        assert result["summary"]["decision"] == "BLOCKED_MISSING_ARTIFACTS"


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


class TestCaptureHumanDecision:
    def test_no_decision_recorded_by_default(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import (
            build_review_summary,
            capture_human_decision,
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
        result = capture_human_decision(state)

        assert result["decision_state"] == "NO_DECISION_RECORDED"
        assert result["review_continuation_approved"] is False
        assert result["automation_approval"] is False

    def test_approve_review_decision(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import (
            build_review_summary,
            capture_human_decision,
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
                "approve_review": True,
                "decision_actor": "darren",
            }
        )
        state = load_artifact_index(state)
        state = validate_artifact_structure(state)
        state = run_governance_scan(state)
        state = select_review_diseases(state)
        state = build_review_summary(state)
        state = optional_human_review_gate(state)
        result = capture_human_decision(state)

        assert result["decision_state"] == "APPROVED_FOR_REVIEW_CONTINUATION"
        assert result["review_continuation_approved"] is True
        assert result["automation_approval"] is False
        assert result["decision_actor"] == "darren"

    def test_reject_review_decision(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import (
            build_review_summary,
            capture_human_decision,
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
                "reject_review": True,
                "decision_reason": "Source refs insufficient",
                "decision_actor": "darren",
            }
        )
        state = load_artifact_index(state)
        state = validate_artifact_structure(state)
        state = run_governance_scan(state)
        state = select_review_diseases(state)
        state = build_review_summary(state)
        state = optional_human_review_gate(state)
        result = capture_human_decision(state)

        assert result["decision_state"] == "REJECTED_WITH_REASON"
        assert result["review_continuation_approved"] is False
        assert result["automation_approval"] is False

    def test_hold_review_decision(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import (
            build_review_summary,
            capture_human_decision,
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
                "hold_review": True,
                "decision_reason": "Waiting for Q3 data",
            }
        )
        state = load_artifact_index(state)
        state = validate_artifact_structure(state)
        state = run_governance_scan(state)
        state = select_review_diseases(state)
        state = build_review_summary(state)
        state = optional_human_review_gate(state)
        result = capture_human_decision(state)

        assert result["decision_state"] == "HOLD_PENDING_MORE_REVIEW"
        assert result["review_continuation_approved"] is False
        assert result["automation_approval"] is False

    def test_reject_requires_reason(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import (
            build_review_summary,
            capture_human_decision,
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
                "reject_review": True,
            }
        )
        state = load_artifact_index(state)
        state = validate_artifact_structure(state)
        state = run_governance_scan(state)
        state = select_review_diseases(state)
        state = build_review_summary(state)
        state = optional_human_review_gate(state)

        with pytest.raises(ValueError, match="--reject-review requires --decision-reason"):
            capture_human_decision(state)

    def test_decision_artifact_jsonl_created(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import (
            build_review_summary,
            capture_human_decision,
            initialize_review,
            load_artifact_index,
            optional_human_review_gate,
            run_governance_scan,
            select_review_diseases,
            validate_artifact_structure,
        )

        review_dir = tmp_path / "review"
        state = initialize_review(
            {
                "as_of_date": "2026-06-18",
                "artifact_dir": str(synthetic_artifact_dir),
                "review_dir": str(review_dir),
                "approve_review": True,
                "decision_actor": "darren",
                "decision_reason": "Test approval",
            }
        )
        state = load_artifact_index(state)
        state = validate_artifact_structure(state)
        state = run_governance_scan(state)
        state = select_review_diseases(state)
        state = build_review_summary(state)
        state = optional_human_review_gate(state)
        result = capture_human_decision(state)

        jsonl_path = review_dir / "langgraph_human_decisions.jsonl"
        assert jsonl_path.exists()

        with open(jsonl_path) as f:
            line = f.readline()
            artifact = json.loads(line)

        assert artifact["artifact_type"] == "scientific_cartography_langgraph_human_decision"
        assert artifact["decision_state"] == "APPROVED_FOR_REVIEW_CONTINUATION"
        assert artifact["automation_approval"] is False
        assert artifact["review_continuation_approved"] is True

    def test_automation_approval_always_false(self, synthetic_artifact_dir, tmp_path):
        from scientific_cartography.langgraph_review.nodes import (
            build_review_summary,
            capture_human_decision,
            initialize_review,
            load_artifact_index,
            optional_human_review_gate,
            run_governance_scan,
            select_review_diseases,
            validate_artifact_structure,
        )

        review_dir = tmp_path / "review"
        state = initialize_review(
            {
                "as_of_date": "2026-06-18",
                "artifact_dir": str(synthetic_artifact_dir),
                "review_dir": str(review_dir),
                "approve_review": True,
            }
        )
        state = load_artifact_index(state)
        state = validate_artifact_structure(state)
        state = run_governance_scan(state)
        state = select_review_diseases(state)
        state = build_review_summary(state)
        state = optional_human_review_gate(state)
        result = capture_human_decision(state)

        assert result["automation_approval"] is False

        jsonl_path = review_dir / "langgraph_human_decisions.jsonl"
        if jsonl_path.exists():
            with open(jsonl_path) as f:
                line = f.readline()
                artifact = json.loads(line)
                assert artifact["automation_approval"] is False
                assert artifact["governance"]["automation_approval"] is False

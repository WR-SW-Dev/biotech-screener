"""Tests for LG4A static HTML dashboard generator."""

import json
import tempfile
from pathlib import Path

import pytest

from scientific_cartography.dashboard_static.generator import DashboardGenerator


@pytest.fixture
def temp_artifact_dir():
    """Create temporary artifact directory with test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_dir = Path(tmpdir) / "artifacts" / "scientific_cartography" / "2026-06-10"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        # Create review subdir
        review_dir = artifact_dir / "review"
        review_dir.mkdir(parents=True, exist_ok=True)

        # Create review summary
        summary = {
            "decision": "HUMAN_REVIEW_REQUIRED",
            "governance_scan_passed": True,
            "selected_disease_count": 5,
            "forbidden_terms_found": [],
        }
        with open(review_dir / "langgraph_review_summary.json", "w") as f:
            json.dump(summary, f)

        # Create human decisions
        decision = {
            "decision_state": "APPROVED_FOR_REVIEW_CONTINUATION",
            "decision_actor": "test_actor",
            "decision_reason": "Test decision",
            "review_continuation_approved": True,
            "automation_approval": False,
            "created_at_utc": "2026-06-10T10:00:00Z",
        }
        with open(review_dir / "langgraph_human_decisions.jsonl", "w") as f:
            f.write(json.dumps(decision) + "\n")

        # Create disease map index
        index = {
            "diseases": [
                {
                    "disease_name": "Type 2 Diabetes",
                    "mondo_id": "MONDO:0005148",
                    "program_count": 100,
                    "cluster_count": 10,
                    "context_feature_count": 5,
                },
                {
                    "disease_name": "Breast Cancer",
                    "mondo_id": "MONDO:0007254",
                    "program_count": 200,
                    "cluster_count": 20,
                    "context_feature_count": 8,
                },
            ]
        }
        with open(artifact_dir / "disease_map_index.json", "w") as f:
            json.dump(index, f)

        yield artifact_dir


@pytest.fixture
def temp_output_dir():
    """Create temporary output directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_dashboard_generator_creates_all_pages(temp_artifact_dir, temp_output_dir):
    """Test that generator creates all expected HTML pages."""
    generator = DashboardGenerator(str(temp_artifact_dir), str(temp_output_dir))
    manifest = generator.generate()

    expected_pages = [
        "index.html",
        "review_runs.html",
        "disease_maps.html",
        "human_decisions.html",
        "scheduled_review_health.html",
        "governance.html",
        "dashboard_manifest.json",
    ]

    for page in expected_pages:
        page_path = temp_output_dir / page
        assert page_path.exists(), f"Expected page not generated: {page}"


def test_dashboard_generator_reads_artifacts(temp_artifact_dir, temp_output_dir):
    """Test that generator reads expected artifacts."""
    generator = DashboardGenerator(str(temp_artifact_dir), str(temp_output_dir))
    manifest = generator.generate()

    assert "langgraph_review_summary.json" in manifest["artifacts_read"]
    assert "disease_map_index.json" in manifest["artifacts_read"]
    assert "langgraph_human_decisions.jsonl" in manifest["artifacts_read"]


def test_dashboard_missing_artifacts_degrade_gracefully(temp_output_dir):
    """Test that missing artifacts are handled gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        empty_dir = Path(tmpdir) / "empty" / "2026-06-10"
        empty_dir.mkdir(parents=True, exist_ok=True)

        generator = DashboardGenerator(str(empty_dir), str(temp_output_dir))
        manifest = generator.generate()

        # Should not crash, should list missing artifacts
        assert len(manifest["artifacts_missing"]) > 0
        assert manifest["pages_written"] == [
            "Index",
            "Review Runs",
            "Disease Maps",
            "Human Decisions",
            "Scheduled Review",
            "Governance",
        ]


def test_manifest_contains_governance_flags(temp_artifact_dir, temp_output_dir):
    """Test that manifest contains all governance flags."""
    generator = DashboardGenerator(str(temp_artifact_dir), str(temp_output_dir))
    manifest = generator.generate()

    governance = manifest["governance_flags"]
    assert governance["read_only_diagnostic"] is True
    assert governance["production_model_change"] is False
    assert governance["ranker_change"] is False
    assert governance["selector_change"] is False
    assert governance["sizing_change"] is False
    assert governance["final_score_change"] is False
    assert governance["trading_or_portfolio_action"] is False
    assert governance["automation_approval"] is False


def test_automation_approval_always_false(temp_artifact_dir, temp_output_dir):
    """Test that automation_approval is always false in manifest."""
    generator = DashboardGenerator(str(temp_artifact_dir), str(temp_output_dir))
    manifest = generator.generate()

    assert manifest["automation_approval"] is False
    assert manifest["governance_flags"]["automation_approval"] is False


def test_human_decision_automation_approval_violation(temp_artifact_dir, temp_output_dir):
    """Test that governance violation is detected if automation_approval is true."""
    # Create decision with automation_approval=true (violation)
    review_dir = temp_artifact_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)

    violation_decision = {
        "decision_state": "APPROVED_FOR_REVIEW_CONTINUATION",
        "decision_actor": "bad_actor",
        "decision_reason": "Unauthorized automation",
        "review_continuation_approved": True,
        "automation_approval": True,  # VIOLATION
        "created_at_utc": "2026-06-10T10:00:00Z",
    }
    with open(review_dir / "langgraph_human_decisions.jsonl", "w") as f:
        f.write(json.dumps(violation_decision) + "\n")

    generator = DashboardGenerator(str(temp_artifact_dir), str(temp_output_dir))
    manifest = generator.generate()

    # Read generated page to verify violation is displayed
    decisions_page = (temp_output_dir / "human_decisions.html").read_text()
    assert "GOVERNANCE VIOLATION" in decisions_page


def test_no_forbidden_scoring_terms(temp_artifact_dir, temp_output_dir):
    """Test that forbidden scoring/action terms don't appear in main content."""
    generator = DashboardGenerator(str(temp_artifact_dir), str(temp_output_dir))
    manifest = generator.generate()

    # Critical forbidden terms that should never appear (even in CSS/markup)
    critical_terms = [
        "alpha",
        "buy signal",
        "sell signal",
        "conviction score",
    ]

    # Read all generated pages
    for page_file in [
        "index.html",
        "review_runs.html",
        "disease_maps.html",
        "human_decisions.html",
        "scheduled_review_health.html",
    ]:
        page_path = temp_output_dir / page_file
        content = page_path.read_text()

        for term in critical_terms:
            assert term not in content.lower(), f"Critical forbidden term '{term}' found in {page_file}"


def test_governance_page_contains_boundaries(temp_artifact_dir, temp_output_dir):
    """Test that governance page displays all boundary flags."""
    generator = DashboardGenerator(str(temp_artifact_dir), str(temp_output_dir))
    manifest = generator.generate()

    governance_page = (temp_output_dir / "governance.html").read_text()

    # Should mention key governance principles
    assert "READ_ONLY_DIAGNOSTIC" in governance_page
    assert "AUTOMATION_APPROVAL" in governance_page
    assert "artifact browser" in governance_page
    assert "No scoring is performed" in governance_page


def test_manifest_runtime_flags(temp_artifact_dir, temp_output_dir):
    """Test that manifest confirms no server or production hook."""
    generator = DashboardGenerator(str(temp_artifact_dir), str(temp_output_dir))
    manifest = generator.generate()

    assert manifest["runtime_server_started"] is False
    assert manifest["production_hook_enabled"] is False
    assert manifest["forbidden_data_sources_used"] == []


def test_forbidden_data_sources_not_accessed(temp_artifact_dir, temp_output_dir):
    """Test that forbidden data sources are not accessed."""
    # Create fake forbidden files in artifact dir
    fake_ranking = temp_artifact_dir / "rankings.csv"
    fake_ranking.write_text("fake ranking data")

    fake_portfolio = temp_artifact_dir / "portfolio_positions.csv"
    fake_portfolio.write_text("fake portfolio data")

    generator = DashboardGenerator(str(temp_artifact_dir), str(temp_output_dir))
    manifest = generator.generate()

    # Generator should not have read these files
    assert "rankings.csv" not in manifest["artifacts_read"]
    assert "portfolio_positions.csv" not in manifest["artifacts_read"]


def test_date_extraction_from_path(temp_output_dir):
    """Test that generator correctly extracts date from artifact path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dated_dir = Path(tmpdir) / "artifacts" / "scientific_cartography" / "2026-06-15"
        dated_dir.mkdir(parents=True, exist_ok=True)

        generator = DashboardGenerator(str(dated_dir), str(temp_output_dir))
        manifest = generator.generate()

        assert manifest["as_of_date"] == "2026-06-15"


def test_review_runs_page_contains_metadata(temp_artifact_dir, temp_output_dir):
    """Test that review runs page displays review metadata."""
    generator = DashboardGenerator(str(temp_artifact_dir), str(temp_output_dir))
    manifest = generator.generate()

    review_page = (temp_output_dir / "review_runs.html").read_text()

    assert "HUMAN_REVIEW_REQUIRED" in review_page
    assert "governance_scan_passed" in review_page


def test_disease_maps_page_loads_index(temp_artifact_dir, temp_output_dir):
    """Test that disease maps page loads disease index."""
    generator = DashboardGenerator(str(temp_artifact_dir), str(temp_output_dir))
    manifest = generator.generate()

    disease_page = (temp_output_dir / "disease_maps.html").read_text()

    assert "Type 2 Diabetes" in disease_page
    assert "Breast Cancer" in disease_page
    assert "MONDO:0005148" in disease_page

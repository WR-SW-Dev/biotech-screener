"""Tests for LG4A static HTML dashboard generator."""

import json
import tempfile
from pathlib import Path

import pytest

from scientific_cartography.dashboard_static.generator import DashboardGenerator


def _make_map_index(diseases=None):
    """Build a map_index.json payload matching the current pipeline schema."""
    if diseases is None:
        diseases = [
            {
                "disease_id": "MONDO:0005148",
                "disease_name": "Type 2 Diabetes",
                "therapeutic_area": "Metabolic Disease",
                "program_count": 100,
                "cluster_count": 10,
                "feature_count": 5,
                "public_tickers": ["NVO", "LLY"],
                "known_mechanism_count": 80,
                "unknown_mechanism_count": 20,
                "stage_distribution": {"phase3": 5, "phase2": 30, "phase1": 65},
                "source_refs_count": 12,
            },
            {
                "disease_id": "MONDO:0007254",
                "disease_name": "Breast Cancer",
                "therapeutic_area": "Oncology",
                "program_count": 200,
                "cluster_count": 20,
                "feature_count": 8,
                "public_tickers": ["REGN", "MRK", "BMY"],
                "known_mechanism_count": 150,
                "unknown_mechanism_count": 50,
                "stage_distribution": {"phase3": 20, "phase2": 80, "phase1": 100},
                "source_refs_count": 30,
            },
        ]
    return {
        "as_of_date": "2026-06-10",
        "artifact_type": "scientific_cartography_map_index",
        "counts": {
            "program_records": 300,
            "competitive_clusters": 30,
            "landscape_features": 13,
            "disease_count": len(diseases),
            "ticker_count": 5,
        },
        "diseases": diseases,
        "warnings": [],
    }


@pytest.fixture
def temp_artifact_dir():
    """Create temporary artifact directory with test data (current flat schema)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_dir = Path(tmpdir) / "artifacts" / "scientific_cartography" / "2026-06-10"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        review_dir = artifact_dir / "review"
        review_dir.mkdir(parents=True, exist_ok=True)

        summary = {
            "decision": "HUMAN_REVIEW_REQUIRED",
            "governance_scan_passed": True,
            "selected_disease_count": 5,
            "forbidden_terms_found": [],
        }
        with open(review_dir / "langgraph_review_summary.json", "w") as f:
            json.dump(summary, f)

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

        with open(artifact_dir / "map_index.json", "w") as f:
            json.dump(_make_map_index(), f)

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
    """Test that generator reads expected artifacts (current schema filenames)."""
    generator = DashboardGenerator(str(temp_artifact_dir), str(temp_output_dir))
    manifest = generator.generate()

    assert "langgraph_review_summary.json" in manifest["artifacts_read"]
    assert "map_index.json" in manifest["artifacts_read"]
    assert "langgraph_human_decisions.jsonl" in manifest["artifacts_read"]


def test_load_disease_maps_reads_map_index_filename(temp_output_dir):
    """Generator reads map_index.json, not the old disease_map_index.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_dir = Path(tmpdir) / "2026-06-10"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        # Write only map_index.json — old name should not be read
        with open(artifact_dir / "map_index.json", "w") as f:
            json.dump(_make_map_index(), f)

        generator = DashboardGenerator(str(artifact_dir), str(temp_output_dir))
        manifest = generator.generate()

        assert "map_index.json" in manifest["artifacts_read"]
        assert "disease_map_index.json" not in manifest["artifacts_read"]
        assert "disease_map_index.json" not in manifest["artifacts_missing"]


def test_dashboard_missing_artifacts_degrade_gracefully(temp_output_dir):
    """Test that missing artifacts are handled gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        empty_dir = Path(tmpdir) / "empty" / "2026-06-10"
        empty_dir.mkdir(parents=True, exist_ok=True)

        generator = DashboardGenerator(str(empty_dir), str(temp_output_dir))
        manifest = generator.generate()

        assert len(manifest["artifacts_missing"]) > 0
        assert manifest["pages_written"] == [
            "Index",
            "Review Runs",
            "Disease Maps",
            "Human Decisions",
            "Scheduled Review",
            "Governance",
        ]


def test_disease_maps_missing_index_reports_artifact_missing(temp_output_dir):
    """Missing map_index.json is reported in artifacts_missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        no_index_dir = Path(tmpdir) / "2026-06-10"
        no_index_dir.mkdir(parents=True, exist_ok=True)

        generator = DashboardGenerator(str(no_index_dir), str(temp_output_dir))
        manifest = generator.generate()

        assert "map_index.json" in manifest["artifacts_missing"]


def test_disease_maps_missing_index_shows_placeholder(temp_output_dir):
    """Missing map_index.json causes disease maps page to show placeholder."""
    with tempfile.TemporaryDirectory() as tmpdir:
        no_index_dir = Path(tmpdir) / "2026-06-10"
        no_index_dir.mkdir(parents=True, exist_ok=True)

        generator = DashboardGenerator(str(no_index_dir), str(temp_output_dir))
        generator.generate()

        disease_page = (temp_output_dir / "disease_maps.html").read_text()
        assert "No disease maps found" in disease_page


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

    decisions_page = (temp_output_dir / "human_decisions.html").read_text()
    assert "GOVERNANCE VIOLATION" in decisions_page


def test_no_forbidden_scoring_terms(temp_artifact_dir, temp_output_dir):
    """Test that forbidden scoring/action terms don't appear in main content."""
    generator = DashboardGenerator(str(temp_artifact_dir), str(temp_output_dir))
    manifest = generator.generate()

    critical_terms = [
        "alpha",
        "buy signal",
        "sell signal",
        "conviction score",
    ]

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
    fake_ranking = temp_artifact_dir / "rankings.csv"
    fake_ranking.write_text("fake ranking data")

    fake_portfolio = temp_artifact_dir / "portfolio_positions.csv"
    fake_portfolio.write_text("fake portfolio data")

    generator = DashboardGenerator(str(temp_artifact_dir), str(temp_output_dir))
    manifest = generator.generate()

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
    """Test that disease maps page renders diseases from map_index.json."""
    generator = DashboardGenerator(str(temp_artifact_dir), str(temp_output_dir))
    manifest = generator.generate()

    disease_page = (temp_output_dir / "disease_maps.html").read_text()

    assert "Type 2 Diabetes" in disease_page
    assert "Breast Cancer" in disease_page
    assert "Metabolic Disease" in disease_page


def test_disease_maps_page_shows_therapeutic_area(temp_artifact_dir, temp_output_dir):
    """Disease maps page renders therapeutic_area column (not old mondo_id)."""
    generator = DashboardGenerator(str(temp_artifact_dir), str(temp_output_dir))
    generator.generate()

    disease_page = (temp_output_dir / "disease_maps.html").read_text()

    assert "Therapeutic Area" in disease_page
    assert "Oncology" in disease_page
    assert "Metabolic Disease" in disease_page
    # Old column header should not appear
    assert "MONDO ID" not in disease_page


def test_disease_maps_page_shows_feature_count(temp_artifact_dir, temp_output_dir):
    """Disease maps page uses feature_count from new schema (not context_feature_count)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_dir = Path(tmpdir) / "2026-06-10"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        diseases = [
            {
                "disease_id": "MONDO:0001",
                "disease_name": "Test Disease",
                "therapeutic_area": "Test Area",
                "program_count": 7,
                "cluster_count": 3,
                "feature_count": 42,  # new schema field
                "public_tickers": [],
            }
        ]
        with open(artifact_dir / "map_index.json", "w") as f:
            json.dump(_make_map_index(diseases=diseases), f)

        generator = DashboardGenerator(str(artifact_dir), str(temp_output_dir))
        generator.generate()

        disease_page = (temp_output_dir / "disease_maps.html").read_text()
        assert "42" in disease_page  # feature_count value rendered
        assert "Context Features" not in disease_page  # old column header gone
        assert "Features" in disease_page


def test_disease_maps_missing_therapeutic_area_shows_dash(temp_output_dir):
    """Diseases without therapeutic_area render '—' placeholder."""
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_dir = Path(tmpdir) / "2026-06-10"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        diseases = [
            {
                "disease_id": "MONDO:0001",
                "disease_name": "Unknown Area Disease",
                "therapeutic_area": None,
                "program_count": 5,
                "cluster_count": 2,
                "feature_count": 1,
                "public_tickers": [],
            }
        ]
        with open(artifact_dir / "map_index.json", "w") as f:
            json.dump(_make_map_index(diseases=diseases), f)

        generator = DashboardGenerator(str(artifact_dir), str(temp_output_dir))
        generator.generate()

        disease_page = (temp_output_dir / "disease_maps.html").read_text()
        assert "Unknown Area Disease" in disease_page
        assert "—" in disease_page


def test_disease_maps_malformed_index_degrades_gracefully(temp_output_dir):
    """Corrupt map_index.json triggers a warning and renders empty disease list."""
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_dir = Path(tmpdir) / "2026-06-10"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        with open(artifact_dir / "map_index.json", "w") as f:
            f.write("not valid json {{{")

        generator = DashboardGenerator(str(artifact_dir), str(temp_output_dir))
        manifest = generator.generate()

        assert len(generator.warnings) > 0
        disease_page = (temp_output_dir / "disease_maps.html").read_text()
        assert "No disease maps found" in disease_page


def test_map_index_counts_key_does_not_cause_errors(temp_output_dir):
    """Index with counts{} at root (current schema) does not raise errors."""
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_dir = Path(tmpdir) / "2026-06-10"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        with open(artifact_dir / "map_index.json", "w") as f:
            json.dump(_make_map_index(), f)

        generator = DashboardGenerator(str(artifact_dir), str(temp_output_dir))
        manifest = generator.generate()

        assert "map_index.json" in manifest["artifacts_read"]
        assert len(generator.warnings) == 0

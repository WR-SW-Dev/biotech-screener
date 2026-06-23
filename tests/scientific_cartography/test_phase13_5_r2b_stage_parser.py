"""Phase 13.5 R2b — stage parser compatibility tests.

Covers the PHASE13_5_R2B_STAGE_PARSER_COMPATIBILITY_FIX in
CTGovIngest._parse_simplified_format: production trial_records.json uses
a singular "phase" string (e.g. "PHASE2") while test fixtures use a
plural "phases" list.  Both formats must be handled correctly.

Tests also verify that parsed phases values interact correctly with
StageNormalizer (the downstream consumer), to confirm the end-to-end
mapping is coherent.
"""

import pytest

from scientific_cartography.ingest.ctgov_ingest import CTGovIngest
from scientific_cartography.normalize.stage_normalizer import StageNormalizer


@pytest.fixture
def ingest():
    return CTGovIngest(as_of_date="2026-06-23")


@pytest.fixture
def normalizer():
    return StageNormalizer()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_trial(extra: dict) -> dict:
    """Minimal valid record merged with extra fields."""
    base = {
        "nct_id": "NCT99999999",
        "brief_title": "R2b Test Trial",
        "sponsor": "R2b Sponsor",
    }
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# 1. Regression: plural "phases" list still works
# ---------------------------------------------------------------------------


class TestPhasesListFormat:
    """Plural 'phases' list — original fixture format must not regress."""

    def test_phases_list_phase2(self, ingest, normalizer):
        """phases list ['Phase 2'] -> phases field ['Phase 2'] -> normalizes to phase2."""
        data = _make_trial({"phases": ["Phase 2"]})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        assert record.phases == ["Phase 2"]
        assert normalizer.normalize(record.phases[0]) == "phase2"

    def test_phases_list_phase3(self, ingest, normalizer):
        """phases list ['PHASE3'] -> normalizes to phase3."""
        data = _make_trial({"phases": ["PHASE3"]})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        assert record.phases == ["PHASE3"]
        assert normalizer.normalize(record.phases[0]) == "phase3"

    def test_phases_list_multiple(self, ingest):
        """phases list with multiple entries preserved."""
        data = _make_trial({"phases": ["Phase 1", "Phase 2"]})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        assert record.phases == ["Phase 1", "Phase 2"]

    def test_phases_list_takes_priority_over_phase_singular(self, ingest, normalizer):
        """When both 'phases' and 'phase' are present, 'phases' wins."""
        data = _make_trial({"phases": ["Phase 3"], "phase": "PHASE1"})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        # 'phases' list is non-empty, so it should win
        assert record.phases == ["Phase 3"]
        assert normalizer.normalize(record.phases[0]) == "phase3"


# ---------------------------------------------------------------------------
# 2. Singular "phase" string — production trial_records.json format
# ---------------------------------------------------------------------------


class TestPhaseSingularFormat:
    """Singular 'phase' string — production format must be parsed correctly."""

    def test_phase_singular_phase2(self, ingest, normalizer):
        """{'phase': 'PHASE2'} -> phases == ['PHASE2'] -> normalizes to phase2."""
        data = _make_trial({"phase": "PHASE2"})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        assert record.phases == ["PHASE2"]
        assert normalizer.normalize(record.phases[0]) == "phase2"

    def test_phase_singular_phase3(self, ingest, normalizer):
        """{'phase': 'PHASE3'} -> phases == ['PHASE3'] -> normalizes to phase3."""
        data = _make_trial({"phase": "PHASE3"})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        assert record.phases == ["PHASE3"]
        assert normalizer.normalize(record.phases[0]) == "phase3"

    def test_phase_singular_phase1(self, ingest, normalizer):
        """{'phase': 'PHASE1'} -> phases == ['PHASE1'] -> normalizes to phase1."""
        data = _make_trial({"phase": "PHASE1"})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        assert record.phases == ["PHASE1"]
        assert normalizer.normalize(record.phases[0]) == "phase1"

    def test_phase_singular_phase4(self, ingest, normalizer):
        """{'phase': 'PHASE4'} -> phases wrapped -> normalizer maps to 'approved'.

        Phase 4 = post-marketing surveillance = drug already has market authorization.
        """
        data = _make_trial({"phase": "PHASE4"})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        assert record.phases == ["PHASE4"]
        assert normalizer.normalize(record.phases[0]) == "approved"


# ---------------------------------------------------------------------------
# 3. Dual-phase string (PHASE1_PHASE2)
# ---------------------------------------------------------------------------


class TestDualPhaseString:
    """PHASE1_PHASE2 compound string — no alias in StageNormalizer, should be preserved."""

    def test_phase1_phase2_wrapped(self, ingest, normalizer):
        """{'phase': 'PHASE1_PHASE2'} -> wrapped in list -> normalizer maps to 'phase1/2'."""
        data = _make_trial({"phase": "PHASE1_PHASE2"})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        assert record.phases == ["PHASE1_PHASE2"]
        assert normalizer.normalize(record.phases[0]) == "phase1/2"

    def test_phases_list_phase1_2_slash(self, ingest, normalizer):
        """{'phases': ['Phase 1/2']} -> normalizes to phase1/2 (alias exists)."""
        data = _make_trial({"phases": ["Phase 1/2"]})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        assert record.phases == ["Phase 1/2"]
        assert normalizer.normalize(record.phases[0]) == "phase1/2"


# ---------------------------------------------------------------------------
# 4. EARLY_PHASE1
# ---------------------------------------------------------------------------


class TestEarlyPhase:
    """EARLY_PHASE1 — no alias in StageNormalizer, should be preserved without crash."""

    def test_early_phase1_wrapped(self, ingest, normalizer):
        """{'phase': 'EARLY_PHASE1'} -> wrapped -> normalizer maps to 'phase1'."""
        data = _make_trial({"phase": "EARLY_PHASE1"})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        assert record.phases == ["EARLY_PHASE1"]
        assert normalizer.normalize(record.phases[0]) == "phase1"

    def test_phases_list_early_phase1(self, ingest, normalizer):
        """{'phases': ['early phase 1']} -> 'early phase 1' alias maps to phase1."""
        data = _make_trial({"phases": ["early phase 1"]})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        assert record.phases == ["early phase 1"]
        assert normalizer.normalize(record.phases[0]) == "phase1"


# ---------------------------------------------------------------------------
# 5. Missing phase — no crash
# ---------------------------------------------------------------------------


class TestMissingPhase:
    """No phase field in input — must not crash, must produce empty list."""

    def test_no_phase_field(self, ingest):
        """Record with neither 'phase' nor 'phases' -> phases == []."""
        data = _make_trial({})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        assert record.phases == []

    def test_empty_phases_list(self, ingest):
        """{'phases': []} -> phases == []."""
        data = _make_trial({"phases": []})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        assert record.phases == []

    def test_empty_phases_falls_through_to_phase_singular(self, ingest):
        """{'phases': [], 'phase': 'PHASE2'} -> phases list empty so fall through to singular."""
        data = _make_trial({"phases": [], "phase": "PHASE2"})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        # phases is falsy (empty list), so fall through to singular "phase"
        assert record.phases == ["PHASE2"]


# ---------------------------------------------------------------------------
# 6. Null phase — no crash
# ---------------------------------------------------------------------------


class TestNullPhase:
    """Null / None phase — must not crash, must produce empty list."""

    def test_null_phase_string(self, ingest):
        """{'phase': None} -> _ensure_list(None) -> [] -> phases == []."""
        data = _make_trial({"phase": None})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        assert record.phases == []

    def test_null_phases_list(self, ingest):
        """{'phases': None} -> phases is falsy, fall through to phase singular (missing) -> []."""
        data = _make_trial({"phases": None})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        assert record.phases == []

    def test_null_both_fields(self, ingest):
        """Both fields None -> phases == []."""
        data = _make_trial({"phases": None, "phase": None})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        assert record.phases == []


# ---------------------------------------------------------------------------
# 7. NOT_APPLICABLE / N/A / NA — no crash, consistent with normalizer convention
# ---------------------------------------------------------------------------


class TestNotApplicablePhase:
    """N/A, NA, NOT_APPLICABLE — preserved without crash; normalizer returns None (unknown)."""

    def test_na_string(self, ingest, normalizer):
        """{'phase': 'N/A'} -> wrapped -> normalizer returns None."""
        data = _make_trial({"phase": "N/A"})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        assert record.phases == ["N/A"]
        assert normalizer.normalize(record.phases[0]) is None

    def test_na_bare_string(self, ingest, normalizer):
        """{'phase': 'NA'} -> wrapped -> normalizer returns None."""
        data = _make_trial({"phase": "NA"})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        assert record.phases == ["NA"]
        assert normalizer.normalize(record.phases[0]) is None

    def test_not_applicable_string(self, ingest, normalizer):
        """{'phase': 'NOT_APPLICABLE'} -> wrapped -> normalizer returns None."""
        data = _make_trial({"phase": "NOT_APPLICABLE"})
        record = ingest._parse_simplified_format(data)
        assert record is not None
        assert record.phases == ["NOT_APPLICABLE"]
        assert normalizer.normalize(record.phases[0]) is None

    def test_is_active_stage_false_for_none(self, normalizer):
        """Stages that normalize to None are not active stages."""
        assert normalizer.is_active_stage(None) is False
        assert normalizer.is_active_stage(normalizer.normalize("N/A")) is False
        assert normalizer.is_active_stage(normalizer.normalize("NOT_APPLICABLE")) is False


# ---------------------------------------------------------------------------
# 8. End-to-end: production-format record is fully parsed (no crash, no silent drop)
# ---------------------------------------------------------------------------


class TestEndToEndProductionRecord:
    """Simulate a record from production trial_records.json going through ingest."""

    def test_production_style_record_phases_populated(self, ingest):
        """A production-style record (singular 'phase') must have a non-empty phases list."""
        production_record = {
            "ticker": "COGT",
            "nct_id": "NCT03456789",
            "title": "Study of Asset A in Atopic Dermatitis",
            "status": "ACTIVE_NOT_RECRUITING",
            "phase": "PHASE2",
            "study_type": "INTERVENTIONAL",
            "conditions": ["Atopic Dermatitis"],
            "interventions": ["Asset A"],
            "first_posted": "2020-01-01",
            "start_date": "2020-03-01",
            "primary_completion_date": "2022-06-01",
            "completion_date": "2022-09-01",
            "results_first_posted": None,
            "last_update_posted": "2026-01-01",
            "enrollment": 120,
            "sponsor": "Cognito Therapeutics",
            "collected_at": "2026-06-23",
        }
        record = ingest._parse_simplified_format(production_record)
        assert record is not None
        assert record.nct_id == "NCT03456789"
        assert record.ticker == "COGT"
        # THE KEY ASSERTION: phases must NOT be empty
        assert record.phases == ["PHASE2"], (
            f"Expected ['PHASE2'] but got {record.phases!r}. "
            "Fix: _parse_simplified_format must fall back to singular 'phase' field."
        )

    def test_production_style_record_na_phase_no_crash(self, ingest):
        """Production records with 'N/A' phase must not crash and phases list is populated."""
        production_record = {
            "nct_id": "NCT09999999",
            "phase": "N/A",
            "conditions": [],
            "interventions": [],
        }
        record = ingest._parse_simplified_format(production_record)
        assert record is not None
        # N/A is a valid string — wrapped in list, downstream normalizer handles it
        assert record.phases == ["N/A"]

    def test_select_highest_stage_from_production_phases(self, ingest, normalizer):
        """select_highest_stage should correctly rank phases from production records."""
        data_p2 = _make_trial({"phase": "PHASE2"})
        data_p3 = _make_trial({"phase": "PHASE3"})
        r2 = ingest._parse_simplified_format(data_p2)
        r3 = ingest._parse_simplified_format(data_p3)
        assert r2 is not None and r3 is not None

        normalized = [normalizer.normalize(p) for r in [r2, r3] for p in r.phases]
        highest = normalizer.select_highest_stage(normalized)
        assert highest == "phase3"

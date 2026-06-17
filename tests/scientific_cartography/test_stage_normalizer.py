"""Tests for stage normalizer."""

import pytest

from scientific_cartography.normalize.stage_normalizer import StageNormalizer


class TestStageNormalizerBasic:
    """Test basic stage normalization."""

    @pytest.fixture
    def normalizer(self):
        return StageNormalizer()

    def test_normalizer_initializes(self, normalizer):
        """Normalizer should initialize."""
        assert normalizer is not None

    def test_none_input_returns_none(self, normalizer):
        """None input should return None."""
        assert normalizer.normalize(None) is None

    def test_preclinical_normalization(self, normalizer):
        """Preclinical aliases should normalize."""
        assert normalizer.normalize("preclinical") == "preclinical"
        assert normalizer.normalize("Preclinical") == "preclinical"
        assert normalizer.normalize("in vitro") == "preclinical"
        assert normalizer.normalize("nonclinical") == "preclinical"

    def test_phase1_normalization(self, normalizer):
        """Phase 1 aliases should normalize."""
        assert normalizer.normalize("phase1") == "phase1"
        assert normalizer.normalize("phase 1") == "phase1"
        assert normalizer.normalize("Phase1") == "phase1"
        assert normalizer.normalize("I") == "phase1"

    def test_phase2_normalization(self, normalizer):
        """Phase 2 aliases should normalize."""
        assert normalizer.normalize("phase2") == "phase2"
        assert normalizer.normalize("phase 2") == "phase2"
        assert normalizer.normalize("II") == "phase2"

    def test_phase3_normalization(self, normalizer):
        """Phase 3 aliases should normalize."""
        assert normalizer.normalize("phase3") == "phase3"
        assert normalizer.normalize("phase 3") == "phase3"
        assert normalizer.normalize("III") == "phase3"

    def test_phase1_2_normalization(self, normalizer):
        """Phase 1/2 should normalize."""
        assert normalizer.normalize("phase1/2") == "phase1/2"
        assert normalizer.normalize("phase 1/2") == "phase1/2"
        assert normalizer.normalize("I/II") == "phase1/2"

    def test_approved_normalization(self, normalizer):
        """Approved aliases should normalize."""
        assert normalizer.normalize("approved") == "approved"
        assert normalizer.normalize("Approved") == "approved"
        assert normalizer.normalize("FDA approved") == "approved"
        assert normalizer.normalize("marketed") == "approved"

    def test_filed_normalization(self, normalizer):
        """Filed aliases should normalize."""
        assert normalizer.normalize("filed") == "filed"
        assert normalizer.normalize("NDA") == "filed"
        assert normalizer.normalize("BLA") == "filed"
        assert normalizer.normalize("under review") == "filed"

    def test_unknown_stage_returns_none(self, normalizer):
        """Unknown stage should return None."""
        assert normalizer.normalize("unknown_stage_xyz") is None
        assert normalizer.normalize("totally_fake") is None

    def test_whitespace_handling(self, normalizer):
        """Whitespace should be normalized."""
        assert normalizer.normalize("  phase1  ") == "phase1"
        assert normalizer.normalize("\tphase2\t") == "phase2"


class TestStageNormalizerHierarchy:
    """Test stage hierarchy and ranking."""

    @pytest.fixture
    def normalizer(self):
        return StageNormalizer()

    def test_hierarchy_order(self, normalizer):
        """Stages should have correct hierarchy order."""
        preclinical = normalizer.get_hierarchy_rank("preclinical")
        phase1 = normalizer.get_hierarchy_rank("phase1")
        phase2 = normalizer.get_hierarchy_rank("phase2")
        phase3 = normalizer.get_hierarchy_rank("phase3")
        filed = normalizer.get_hierarchy_rank("filed")
        approved = normalizer.get_hierarchy_rank("approved")

        assert preclinical < phase1 < phase2 < phase3 < filed < approved

    def test_select_highest_stage_approved(self, normalizer):
        """Approved should be highest stage."""
        stages = ["phase2", "phase3", "approved", "phase1"]
        highest = normalizer.select_highest_stage(stages)
        assert highest == "approved"

    def test_select_highest_stage_phase3(self, normalizer):
        """Phase 3 should rank highest if no approved."""
        stages = ["phase1", "phase2", "phase3"]
        highest = normalizer.select_highest_stage(stages)
        assert highest == "phase3"

    def test_select_highest_stage_mixed(self, normalizer):
        """Should select highest from mixed list."""
        stages = ["preclinical", "phase2", "phase1", "phase3"]
        highest = normalizer.select_highest_stage(stages)
        assert highest == "phase3"

    def test_select_highest_with_none_values(self, normalizer):
        """None values should be ignored."""
        stages = ["phase1", None, "phase3", None, "phase2"]
        highest = normalizer.select_highest_stage(stages)
        assert highest == "phase3"

    def test_select_highest_empty_list(self, normalizer):
        """Empty list should return None."""
        assert normalizer.select_highest_stage([]) is None

    def test_select_highest_all_none(self, normalizer):
        """All None values should return None."""
        assert normalizer.select_highest_stage([None, None, None]) is None

    def test_select_highest_single_stage(self, normalizer):
        """Single stage should be returned."""
        stages = ["phase2"]
        highest = normalizer.select_highest_stage(stages)
        assert highest == "phase2"


class TestStageNormalizerActiveInactive:
    """Test active vs inactive stage classification."""

    @pytest.fixture
    def normalizer(self):
        return StageNormalizer()

    def test_preclinical_is_active(self, normalizer):
        """Preclinical should be active."""
        assert normalizer.is_active_stage("preclinical") is True

    def test_phase1_is_active(self, normalizer):
        """Phase 1 should be active."""
        assert normalizer.is_active_stage("phase1") is True

    def test_phase2_is_active(self, normalizer):
        """Phase 2 should be active."""
        assert normalizer.is_active_stage("phase2") is True

    def test_phase3_is_active(self, normalizer):
        """Phase 3 should be active."""
        assert normalizer.is_active_stage("phase3") is True

    def test_filed_is_active(self, normalizer):
        """Filed should be active."""
        assert normalizer.is_active_stage("filed") is True

    def test_approved_is_active(self, normalizer):
        """Approved should be active."""
        assert normalizer.is_active_stage("approved") is True

    def test_discontinued_is_inactive(self, normalizer):
        """Discontinued should be inactive."""
        assert normalizer.is_active_stage("discontinued") is False

    def test_none_is_inactive(self, normalizer):
        """None should be inactive."""
        assert normalizer.is_active_stage(None) is False

    def test_unknown_is_inactive(self, normalizer):
        """Unknown stages should be inactive."""
        assert normalizer.is_active_stage("unknown_stage") is False


class TestStageNormalizerEdgeCases:
    """Test edge cases and special scenarios."""

    @pytest.fixture
    def normalizer(self):
        return StageNormalizer()

    def test_phase2b_normalization(self, normalizer):
        """Phase 2b should normalize."""
        assert normalizer.normalize("phase2b") == "phase2b"
        assert normalizer.normalize("Phase 2b") == "phase2b"

    def test_phase1_2_is_higher_than_phase1(self, normalizer):
        """Phase 1/2 should rank higher than Phase 1."""
        phase1 = normalizer.get_hierarchy_rank("phase1")
        phase1_2 = normalizer.get_hierarchy_rank("phase1/2")
        assert phase1 < phase1_2

    def test_phase2b_is_higher_than_phase2(self, normalizer):
        """Phase 2b should rank higher than Phase 2."""
        phase2 = normalizer.get_hierarchy_rank("phase2")
        phase2b = normalizer.get_hierarchy_rank("phase2b")
        assert phase2 < phase2b

    def test_hierarchy_rank_discontinued(self, normalizer):
        """Discontinued should have negative rank."""
        rank = normalizer.get_hierarchy_rank("discontinued")
        assert rank < 0

    def test_hierarchy_rank_none(self, normalizer):
        """None should have very negative rank."""
        rank = normalizer.get_hierarchy_rank(None)
        assert rank < normalizer.get_hierarchy_rank("preclinical")

    def test_select_highest_with_discontinued(self, normalizer):
        """Discontinued should not be selected if other active stages exist."""
        stages = ["phase2", "discontinued", "phase3"]
        highest = normalizer.select_highest_stage(stages)
        assert highest == "phase3"

    def test_select_highest_only_discontinued(self, normalizer):
        """Discontinued can be selected if it's the only stage."""
        stages = ["discontinued"]
        highest = normalizer.select_highest_stage(stages)
        assert highest == "discontinued"

    def test_mixed_case_and_spacing(self, normalizer):
        """Mixed case and spacing should normalize."""
        assert normalizer.normalize("  PHASE 3  ") == "phase3"
        assert normalizer.normalize("Phase 2B") == "phase2b"
        assert normalizer.normalize(" FDA APPROVED ") == "approved"

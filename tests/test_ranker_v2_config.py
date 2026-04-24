"""Regression tests for the production ranker v2 configuration.

Validates that the 2-feature ranker model, config, and feature extraction
are correctly aligned. Promoted 2026-04-05 (scoring logic audit).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ranker_v2_pairwise import FEATURES_MINIMAL_V2, RankerV2Config, get_feature_specs


class TestProductionRankerConfig:
    """Verify production ranker is the 2-feature model."""

    def test_production_model_has_2_features(self):
        model = json.loads(Path("production_data/ranker_v2_model.json").read_text())
        assert model["model"]["n_features"] == 2

    def test_production_model_feature_names(self):
        model = json.loads(Path("production_data/ranker_v2_model.json").read_text())
        assert model["model"]["feature_names"] == ["coinvest_score_z", "financial_score"]

    def test_production_model_weights_length(self):
        model = json.loads(Path("production_data/ranker_v2_model.json").read_text())
        assert len(model["model"]["weights"]) == 2

    def test_production_model_is_trained(self):
        model = json.loads(Path("production_data/ranker_v2_model.json").read_text(encoding="utf-8"))
        assert model["model"]["trained"] is True

    def test_production_config_uses_minimal_v2(self):
        """Verify run_screen.py sets feature_set='minimal_v2'."""
        content = Path("run_screen.py").read_text(encoding="utf-8")
        assert 'feature_set="minimal_v2"' in content

    def test_rollback_artifact_exists(self):
        assert Path("production_data/ranker_v2_model_5feat_rollback.json").exists()

    def test_rollback_has_5_features(self):
        model = json.loads(Path("production_data/ranker_v2_model_5feat_rollback.json").read_text(encoding="utf-8"))
        assert model["model"]["n_features"] == 5
        assert len(model["model"]["weights"]) == 5


class TestFeatureSpecDispatch:
    """Verify feature_set dispatch returns correct features."""

    def test_minimal_v2_returns_2_features(self):
        config = RankerV2Config(feature_set="minimal_v2")
        specs = get_feature_specs(config)
        assert len(specs) == 2
        assert specs[0].name == "coinvest_score_z"
        assert specs[1].name == "financial_score"

    def test_minimal_returns_5_features(self):
        config = RankerV2Config(feature_set="minimal")
        specs = get_feature_specs(config)
        assert len(specs) == 5

    def test_features_minimal_v2_constant(self):
        assert len(FEATURES_MINIMAL_V2) == 2
        names = [f.name for f in FEATURES_MINIMAL_V2]
        assert names == ["coinvest_score_z", "financial_score"]


class TestModelWeightDirections:
    """Verify model weight directions match economic logic."""

    def test_coinvest_positive(self):
        """Higher coinvest = better (more institutional sponsorship)."""
        model = json.loads(Path("production_data/ranker_v2_model.json").read_text())
        coinvest_idx = model["model"]["feature_names"].index("coinvest_score_z")
        assert model["model"]["weights"][coinvest_idx] > 0

    def test_financial_negative(self):
        """Higher financial_score = penalty (penalizes safe/profitable names in biotech)."""
        model = json.loads(Path("production_data/ranker_v2_model.json").read_text())
        fin_idx = model["model"]["feature_names"].index("financial_score")
        assert model["model"]["weights"][fin_idx] < 0


class TestDeployedProvenance:
    """Verify the live artifact carries deployment provenance (Family C live pilot).

    The deployed ranker_v2_model.json is the capped live-pilot vector, not the raw
    trained minimal_v2 vector. Operators and downstream tooling rely on the
    provenance block to distinguish the two; these tests pin that invariant.
    """

    def _artifact(self):
        return json.loads(Path("production_data/ranker_v2_model.json").read_text())

    def test_provenance_block_present(self):
        assert "provenance" in self._artifact()

    def test_model_variant_is_deployed_live_pilot(self):
        assert self._artifact()["provenance"]["model_variant"] == "deployed_live_pilot"

    def test_trained_basis_is_minimal_v2(self):
        assert self._artifact()["provenance"]["trained_basis"] == "minimal_v2"

    def test_capped_feature_is_coinvest(self):
        assert self._artifact()["provenance"]["capped_weight_feature"] == "coinvest_score_z"

    def test_coinvest_deployed_weight_below_trained(self):
        art = self._artifact()
        prov = art["provenance"]
        coinvest_idx = art["model"]["feature_names"].index("coinvest_score_z")
        deployed = art["model"]["weights"][coinvest_idx]
        assert deployed == prov["capped_weight_value"]
        assert prov["capped_weight_value"] < prov["trained_weight_value"]

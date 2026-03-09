"""Tests for family-specific portfolio construction."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import build_positions, load_policy


def _make_row(ticker, rank, days=100, family="REGULATORY", mode="specific_days"):
    return {
        "ticker": ticker,
        "actionable_rank": str(rank),
        "eligible": "1",
        "tier_any": "A",
        "target_weight_pct": "1.0",
        "catalyst_days": str(days),
        "catalyst_mode": mode,
        "catalyst_bucket": "",
        "catalyst_strength": "0.5",
        "catalyst_event_type": "PDUFA" if family == "REGULATORY" else "DATA_READOUT",
        "catalyst_family": family,
        "archetype": "drug_developer",
        "mom_state": "neutral",
        "industry_group": "biotech",
        "size_band": "M",
        "de_beta_xbi_60d_source": "hydrated",
    }


def _base_policy():
    return {
        "schema": "portfolio_policy.v2",
        "account_usd": 100_000,
        "bucket_targets": {
            "binary_91_180": 0.60,
            "binary_31_90": 0.20,
            "binary_0_30": 0.10,
            "less_binary": 0.10,
        },
        "bucket_top_k": {
            "binary_91_180": 20,
            "binary_31_90": 15,
            "binary_0_30": 10,
            "less_binary": 15,
        },
        "bucket_name_caps": {
            "binary_91_180": 5.0,
            "binary_31_90": 3.0,
            "binary_0_30": 2.0,
            "less_binary": 3.0,
        },
        "family_overrides": {},
        "gap_risk": {"high_days": 7, "high_cap_pct": 0.5},
    }


class TestFamilyMaxK:
    def test_no_family_overrides_no_cap(self):
        """Without family_overrides, all names pass through."""
        rows = [_make_row(f"REG{i}", i, 100, "REGULATORY") for i in range(10)]
        policy = _base_policy()
        result = build_positions(rows, policy)
        b91 = [p for p in result["positions"] if p["bucket"] == "binary_91_180"]
        assert len(b91) == 10

    def test_family_max_k_caps_regulatory(self):
        """family_overrides max_k=3 for REGULATORY caps at 3 names."""
        rows = [_make_row(f"REG{i}", i, 100, "REGULATORY") for i in range(10)]
        policy = _base_policy()
        policy["family_overrides"] = {
            "binary_91_180": {"REGULATORY": {"max_k": 3}},
        }
        result = build_positions(rows, policy)
        b91 = [p for p in result["positions"] if p["bucket"] == "binary_91_180"]
        assert len(b91) == 3

    def test_family_max_k_mixed(self):
        """Both families capped independently."""
        rows = [_make_row(f"REG{i}", i, 100, "REGULATORY") for i in range(5)] + [
            _make_row(f"CLIN{i}", i + 5, 100, "CLINICAL") for i in range(5)
        ]
        policy = _base_policy()
        policy["family_overrides"] = {
            "binary_91_180": {
                "REGULATORY": {"max_k": 2},
                "CLINICAL": {"max_k": 3},
            },
        }
        result = build_positions(rows, policy)
        b91 = [p for p in result["positions"] if p["bucket"] == "binary_91_180"]
        reg = [p for p in b91 if p["catalyst_family"] == "REGULATORY"]
        clin = [p for p in b91 if p["catalyst_family"] == "CLINICAL"]
        assert len(reg) == 2
        assert len(clin) == 3


class TestFamilyNameCap:
    def test_family_name_cap_applied(self):
        """family name_cap_pct overrides bucket-level cap."""
        rows = [_make_row("REG1", 1, 100, "REGULATORY")]
        policy = _base_policy()
        policy["bucket_name_caps"]["binary_91_180"] = 5.0
        policy["family_overrides"] = {
            "binary_91_180": {"REGULATORY": {"name_cap_pct": 2.0}},
        }
        result = build_positions(rows, policy)
        pos = result["positions"][0]
        assert pos["weight_pct"] <= 2.0

    def test_bucket_cap_used_when_no_family_override(self):
        """Without family override, bucket cap applies."""
        rows = [_make_row("CLIN1", 1, 100, "CLINICAL")]
        policy = _base_policy()
        policy["bucket_name_caps"]["binary_91_180"] = 3.0
        # No family_overrides for CLINICAL
        policy["family_overrides"] = {
            "binary_91_180": {"REGULATORY": {"name_cap_pct": 1.0}},
        }
        result = build_positions(rows, policy)
        pos = result["positions"][0]
        assert pos["weight_pct"] <= 3.0


class TestCatalystFamilyInPositions:
    def test_catalyst_family_field_present(self):
        rows = [_make_row("REG1", 1, 100, "REGULATORY")]
        result = build_positions(rows, _base_policy())
        assert result["positions"][0]["catalyst_family"] == "REGULATORY"

    def test_empty_family_defaults_to_other(self):
        row = _make_row("UNK1", 1, 100, "")
        result = build_positions([row], _base_policy())
        assert result["positions"][0]["catalyst_family"] == "OTHER"


class TestPerBucketFamilySummary:
    def test_summary_has_per_bucket_family(self):
        rows = [
            _make_row("REG1", 1, 100, "REGULATORY"),
            _make_row("CLIN1", 2, 100, "CLINICAL"),
        ]
        result = build_positions(rows, _base_policy())
        pbf = result["summary"]["per_bucket_family"]
        assert "binary_91_180__REGULATORY" in pbf
        assert "binary_91_180__CLINICAL" in pbf
        assert pbf["binary_91_180__REGULATORY"]["count"] == 1
        assert pbf["binary_91_180__CLINICAL"]["count"] == 1

    def test_family_dollars_sum_to_bucket(self):
        rows = [_make_row(f"REG{i}", i, 100, "REGULATORY") for i in range(3)] + [
            _make_row(f"CLIN{i}", i + 3, 100, "CLINICAL") for i in range(2)
        ]
        result = build_positions(rows, _base_policy())
        pbf = result["summary"]["per_bucket_family"]
        pb = result["summary"]["per_bucket"]
        fam_total = sum(v["total_dollars"] for k, v in pbf.items() if k.startswith("binary_91_180__"))
        bucket_total = pb.get("binary_91_180", {}).get("total_dollars", 0)
        assert abs(fam_total - bucket_total) < 0.01


class TestPolicySchema:
    def test_load_policy_with_family_overrides(self, tmp_path):
        pol = _base_policy()
        pol["family_overrides"] = {
            "binary_91_180": {"REGULATORY": {"max_k": 5, "name_cap_pct": 2.5}},
        }
        p = tmp_path / "policy.json"
        p.write_text(json.dumps(pol))
        loaded = load_policy(p)
        assert "family_overrides" in loaded
        assert loaded["family_overrides"]["binary_91_180"]["REGULATORY"]["max_k"] == 5

    def test_default_policy_has_family_overrides(self):
        """Default (fallback) policy includes empty family_overrides."""
        pol = load_policy(Path("/nonexistent/path.json"))
        assert "family_overrides" in pol


class TestSortPreserved:
    def test_rank_order_preserved_after_family_cap(self):
        """After family capping, positions should still be sorted by rank."""
        rows = [_make_row(f"REG{i}", i, 100, "REGULATORY") for i in range(1, 6)] + [
            _make_row(f"CLIN{i}", i + 5, 100, "CLINICAL") for i in range(1, 6)
        ]
        policy = _base_policy()
        policy["family_overrides"] = {
            "binary_91_180": {"REGULATORY": {"max_k": 2}, "CLINICAL": {"max_k": 2}},
        }
        result = build_positions(rows, policy)
        b91 = [p for p in result["positions"] if p["bucket"] == "binary_91_180"]
        ranks = [p["actionable_rank"] for p in b91]
        assert ranks == sorted(ranks)

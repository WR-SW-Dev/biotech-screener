"""Tests for event_ev.runway_severity — dual-severity risk-control overlay."""

from __future__ import annotations

import json

import pytest

from event_ev.runway_severity import RunwaySeverityModel, _catalyst_months, _is_decisive, _severity_bucket

# ── Fixtures ─────────────────────────────────────────────────────────────


def _row(
    ticker: str = "TEST",
    fundamental_red_flag_inputs: str = "",
    runway_months: str = "",
    catalyst_days: str = "90",
    catalyst_type_tier: str = "T3",
    catalyst_event_type: str = "CT_PRIMARY_COMPLETION",
    tier_dev: str = "C",
    market_cap_mm: str = "200",
    short_interest_pct: str = "5.0",
    financing_pressure_score: str = "30",
    has_revenue: str = "false",
    has_commercial_quality: str = "false",
    eligible: str = "1",
    phase: str = "",
    burn_ttm: str = "",
) -> dict:
    rflag = {}
    if runway_months:
        rflag["runway_months"] = float(runway_months)
    if burn_ttm:
        rflag["burn_ttm"] = float(burn_ttm)
    rflag["has_revenue"] = has_revenue == "true"

    return {
        "ticker": ticker,
        "fundamental_red_flag_inputs": json.dumps(rflag) if rflag else "",
        "catalyst_days": catalyst_days,
        "catalyst_type_tier": catalyst_type_tier,
        "catalyst_event_type": catalyst_event_type,
        "tier_dev": tier_dev,
        "market_cap_mm": market_cap_mm,
        "short_interest_pct": short_interest_pct,
        "financing_pressure_score": financing_pressure_score,
        "has_revenue": has_revenue,
        "has_commercial_quality": has_commercial_quality,
        "eligible": eligible,
        "phase": phase,
    }


# ── Helpers ──────────────────────────────────────────────────────────────


class TestHelpers:
    def test_catalyst_months_positive(self):
        assert _catalyst_months(30.44) == pytest.approx(1.0, abs=0.01)
        assert _catalyst_months(91.32) == pytest.approx(3.0, abs=0.01)

    def test_catalyst_months_zero_or_negative(self):
        assert _catalyst_months(0) is None
        assert _catalyst_months(-5) is None
        assert _catalyst_months(None) is None

    def test_is_decisive(self):
        assert _is_decisive("T1") is True
        assert _is_decisive("T2") is True
        assert _is_decisive("T3") is False
        assert _is_decisive("T4") is False
        assert _is_decisive("T5") is False

    def test_severity_bucket(self):
        assert _severity_bucket(0.0) == "safe"
        assert _severity_bucket(0.14) == "safe"
        assert _severity_bucket(0.15) == "moderate"
        assert _severity_bucket(0.39) == "moderate"
        assert _severity_bucket(0.40) == "elevated"
        assert _severity_bucket(0.69) == "elevated"
        assert _severity_bucket(0.70) == "critical"
        assert _severity_bucket(0.91) == "critical"
        assert _severity_bucket(0.92) == "extreme"
        assert _severity_bucket(1.0) == "extreme"


# ── Pivotal CT_PRIMARY_COMPLETION tier promotion ─────────────────────────


class TestPivotalTierPromotion:
    """CT_PRIMARY_COMPLETION should promote to T2 when trial is pivotal."""

    def test_phase3_ct_primary_promoted_to_t2(self):
        """Phase 3 CT_PRIMARY_COMPLETION gets effective T2 for buffer."""
        row = _row(
            runway_months="10",
            catalyst_days="60",
            catalyst_type_tier="T3",
            catalyst_event_type="CT_PRIMARY_COMPLETION",
            phase="Phase 3",
        )
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")
        assert result.catalyst_type_tier == "T2"
        # Buffer should use actual catalyst timing (2mo), not 12mo floor
        assert result.runway_buffer_months > 0

    def test_tier_a_ct_primary_promoted(self):
        """Tier A (late-stage) CT_PRIMARY_COMPLETION gets T2."""
        row = _row(
            runway_months="8",
            catalyst_days="45",
            catalyst_type_tier="T3",
            catalyst_event_type="CT_PRIMARY_COMPLETION",
            tier_dev="A",
        )
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")
        assert result.catalyst_type_tier == "T2"

    def test_tier_b_ct_primary_promoted(self):
        """Tier B CT_PRIMARY_COMPLETION gets T2."""
        row = _row(
            runway_months="8",
            catalyst_days="45",
            catalyst_type_tier="T3",
            catalyst_event_type="CT_PRIMARY_COMPLETION",
            tier_dev="B",
        )
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")
        assert result.catalyst_type_tier == "T2"

    def test_tier_c_phase2_not_promoted(self):
        """Tier C, Phase 2 CT_PRIMARY_COMPLETION stays T3."""
        row = _row(
            runway_months="8",
            catalyst_days="45",
            catalyst_type_tier="T3",
            catalyst_event_type="CT_PRIMARY_COMPLETION",
            tier_dev="C",
            phase="Phase 2",
        )
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")
        assert result.catalyst_type_tier == "T3"

    def test_tier_d_not_promoted(self):
        """Tier D early-stage stays T3."""
        row = _row(
            runway_months="8",
            catalyst_days="45",
            catalyst_type_tier="T3",
            catalyst_event_type="CT_PRIMARY_COMPLETION",
            tier_dev="D",
        )
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")
        assert result.catalyst_type_tier == "T3"

    def test_data_readout_already_t2_unchanged(self):
        """DATA_READOUT is already T2 — no promotion needed."""
        row = _row(
            runway_months="8",
            catalyst_days="45",
            catalyst_type_tier="T2",
            catalyst_event_type="DATA_READOUT",
        )
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")
        assert result.catalyst_type_tier == "T2"

    def test_fda_pdufa_t1_unchanged(self):
        """FDA_PDUFA_DATE is T1 — no promotion logic applies."""
        row = _row(
            runway_months="8",
            catalyst_days="30",
            catalyst_type_tier="T1",
            catalyst_event_type="FDA_PDUFA_DATE",
        )
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")
        assert result.catalyst_type_tier == "T1"


# ── Dual severity paths ──────────────────────────────────────────────────


class TestDualSeverityPaths:
    """Truth severity and EV severity should diverge for non-decisive T3 names."""

    def test_t3_near_catalyst_diverges(self):
        """T3 with near catalyst: truth uses 12mo floor, EV uses actual 2mo."""
        row = _row(
            runway_months="15",
            catalyst_days="60",  # ~2 months
            catalyst_type_tier="T3",
            catalyst_event_type="CT_PRIMARY_COMPLETION",
            tier_dev="C",  # not pivotal, stays T3
            phase="Phase 2",
        )
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")

        # Truth: buffer = 15 - 12 = 3 (T3 uses 12mo floor)
        # EV: buffer = 15 - 2 = 13 (uses actual timing)
        assert result.runway_severity_score > result.ev_severity_score
        assert result.ev_severity_score < 0.10  # very low EV severity

    def test_t1_no_divergence(self):
        """T1 decisive: truth and EV should be similar."""
        row = _row(
            runway_months="8",
            catalyst_days="90",
            catalyst_type_tier="T1",
            catalyst_event_type="FDA_PDUFA_DATE",
        )
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")
        # Both use actual catalyst timing
        assert abs(result.runway_severity_score - result.ev_severity_score) < 0.01

    def test_ev_severity_drives_haircut(self):
        """dilution_haircut should use ev_severity, not truth_severity."""
        row = _row(
            runway_months="15",
            catalyst_days="60",
            catalyst_type_tier="T3",
            catalyst_event_type="CT_PRIMARY_COMPLETION",
            tier_dev="C",
            phase="Phase 2",
        )
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")

        expected_haircut = 0.35 * result.ev_severity_score
        assert result.dilution_haircut == pytest.approx(expected_haircut, abs=0.001)

    def test_ev_severity_drives_size_multiplier(self):
        """size_multiplier should use ev_severity."""
        row = _row(
            runway_months="5",
            catalyst_days="60",
            catalyst_type_tier="T3",
            catalyst_event_type="CT_PRIMARY_COMPLETION",
            tier_dev="C",
            phase="Phase 2",
        )
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")

        expected_mult = max(0.40, 1.0 - 0.60 * result.ev_severity_score)
        assert result.size_multiplier == pytest.approx(expected_mult, abs=0.001)


# ── Truth gate + override ────────────────────────────────────────────────


class TestTruthGate:
    def test_high_severity_fails_gate(self):
        """Severity > 0.92 should fail the truth gate."""
        row = _row(
            runway_months="3",
            catalyst_days="600",
            catalyst_type_tier="T3",
            tier_dev="D",
        )
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")
        assert result.financing_truth_gate is False
        assert result.runway_severity_score > 0.92

    def test_safe_passes_gate(self):
        """Safe names pass the truth gate."""
        row = _row(runway_months="24", catalyst_days="90", catalyst_type_tier="T2")
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")
        assert result.financing_truth_gate is True
        assert result.runway_severity_score < 0.50

    def test_imminent_decisive_overrides_gate(self):
        """Within 60 days + decisive (T1/T2) overrides truth gate failure."""
        row = _row(
            runway_months="2",
            catalyst_days="30",  # 1 month, decisive
            catalyst_type_tier="T1",
            catalyst_event_type="FDA_PDUFA_DATE",
        )
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")
        # Severity may be high but gate should pass due to override
        assert result.financing_truth_gate is True

    def test_imminent_non_decisive_no_override(self):
        """Within 60 days but T3 does NOT override gate failure."""
        row = _row(
            runway_months="2",
            catalyst_days="30",
            catalyst_type_tier="T3",
            catalyst_event_type="CT_PRIMARY_COMPLETION",
            tier_dev="D",  # not pivotal
        )
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")
        # High severity, non-decisive → no override
        if result.runway_severity_score > 0.92:
            assert result.financing_truth_gate is False

    def test_no_runway_data_moderate_default(self):
        """Missing runway data → severity = 0.35 (moderate), gate passes."""
        row = _row(runway_months="", catalyst_days="90")
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")
        assert result.runway_severity_score == pytest.approx(0.35, abs=0.01)
        assert result.financing_truth_gate is True


# ── Regression fixtures (real-world edge cases) ──────────────────────────


class TestRegressionFixtures:
    """Real-world edge cases from the 2026-04-15 gate audit."""

    def test_dnth_style_high_rank_near_catalyst(self):
        """DNTH pattern: rank 3, 10mo runway, 76d catalyst, Phase 3 → should PASS."""
        row = _row(
            ticker="DNTH",
            runway_months="9.8",
            catalyst_days="76",
            catalyst_type_tier="T3",
            catalyst_event_type="CT_PRIMARY_COMPLETION",
            tier_dev="B",  # late-stage → promoted to T2
        )
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")
        assert result.financing_truth_gate is True
        assert result.catalyst_type_tier == "T2"
        assert result.runway_severity_score < 0.20

    def test_sldb_style_moderate_buffer(self):
        """SLDB pattern: 8mo runway, 183d catalyst, Phase 3 → should PASS (barely)."""
        row = _row(
            ticker="SLDB",
            runway_months="7.7",
            catalyst_days="183",
            catalyst_type_tier="T3",
            catalyst_event_type="CT_PRIMARY_COMPLETION",
            tier_dev="B",
        )
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")
        assert result.financing_truth_gate is True
        assert result.catalyst_type_tier == "T2"

    def test_vnda_style_non_pivotal_near_catalyst(self):
        """VNDA pattern: T3 non-pivotal, 45d catalyst → truth fails, EV low."""
        row = _row(
            ticker="VNDA",
            runway_months="5.8",
            catalyst_days="45",
            catalyst_type_tier="T3",
            catalyst_event_type="CT_PRIMARY_COMPLETION",
            tier_dev="C",  # not pivotal, stays T3
        )
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")
        # Truth severity high (5.8mo - 12mo floor = negative buffer)
        assert result.runway_severity_score > 0.70
        # EV severity much lower than truth (5.8mo - 1.5mo = +4.3mo buffer)
        # but small-cap penalty pushes it up; still well below truth severity
        assert result.ev_severity_score < result.runway_severity_score - 0.20

    def test_trda_style_distant_catalyst(self):
        """TRDA pattern: 24mo runway, 1051d catalyst → always fails."""
        row = _row(
            ticker="TRDA",
            runway_months="23.6",
            catalyst_days="1051",
            catalyst_type_tier="T3",
            catalyst_event_type="CT_PRIMARY_COMPLETION",
            tier_dev="C",
        )
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")
        assert result.financing_truth_gate is False
        assert result.runway_severity_score > 0.95

    def test_revenue_backed_reduces_severity(self):
        """Revenue-backed name should get severity reduction."""
        base = _row(runway_months="8", catalyst_days="180", has_revenue="false")
        rev = _row(runway_months="8", catalyst_days="180", has_revenue="true")
        model = RunwaySeverityModel()
        r_base = model.score_row(base, "2026-04-15")
        r_rev = model.score_row(rev, "2026-04-15")
        assert r_rev.runway_severity_score < r_base.runway_severity_score


# ── Overlay shape ────────────────────────────────────────────────────────


class TestOverlayShape:
    def test_to_dict_has_required_fields(self):
        row = _row(runway_months="12", catalyst_days="90")
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")
        d = result.to_dict()

        required = [
            "ticker",
            "as_of_date",
            "months_to_cash_out",
            "runway_buffer_months",
            "runway_severity_score",
            "ev_severity_score",
            "financing_truth_gate",
            "dilution_haircut",
            "size_multiplier",
            "catalyst_type_tier",
            "severity_bucket",
            "severity_notes",
            "model_version",
        ]
        for field in required:
            assert field in d, f"Missing field: {field}"

    def test_model_version(self):
        row = _row(runway_months="12", catalyst_days="90")
        model = RunwaySeverityModel()
        result = model.score_row(row, "2026-04-15")
        assert result.model_version == "runway_severity_v1.1"

    def test_score_batch(self):
        rows = [_row(ticker="A", runway_months="12"), _row(ticker="B", runway_months="6")]
        model = RunwaySeverityModel()
        results = model.score_batch(rows, "2026-04-15")
        assert len(results) == 2
        assert results[0].ticker == "A"
        assert results[1].ticker == "B"


# ── CSV Export (Spec 101) ────────────────────────────────────────────────


class TestCSVExport:
    def test_enrich_csv_rows_exports_ev_severity_score(self):
        """enrich_csv_rows should inject ev_severity_score into each row."""
        from event_ev.runway_severity import RUNWAY_SEVERITY_CSV_COLUMNS, enrich_csv_rows

        rows = [_row(ticker="TEST", runway_months="12"), _row(ticker="TEST2", runway_months="6")]
        overlays = enrich_csv_rows(rows, "2026-04-15")

        # Check that ev_severity_score was added to each row
        assert "ev_severity_score" in rows[0]
        assert "ev_severity_score" in rows[1]
        assert isinstance(rows[0]["ev_severity_score"], float)
        assert isinstance(rows[1]["ev_severity_score"], float)

        # Check that ev_severity_score is in the column list
        assert "ev_severity_score" in RUNWAY_SEVERITY_CSV_COLUMNS

        # Check that injected values match the overlay scores
        assert rows[0]["ev_severity_score"] == overlays[0].ev_severity_score
        assert rows[1]["ev_severity_score"] == overlays[1].ev_severity_score

    def test_csv_columns_include_ev_severity_score(self):
        """RUNWAY_SEVERITY_CSV_COLUMNS should include ev_severity_score."""
        from event_ev.runway_severity import RUNWAY_SEVERITY_CSV_COLUMNS

        assert "ev_severity_score" in RUNWAY_SEVERITY_CSV_COLUMNS
        assert "runway_severity_score" in RUNWAY_SEVERITY_CSV_COLUMNS
        # ev_severity_score should be near runtime_severity_score for readability
        idx_ev = RUNWAY_SEVERITY_CSV_COLUMNS.index("ev_severity_score")
        idx_run = RUNWAY_SEVERITY_CSV_COLUMNS.index("runway_severity_score")
        assert abs(idx_ev - idx_run) <= 2, "ev_severity_score should be near runway_severity_score"


# ── Schema Registration (Spec 101) ───────────────────────────────────────


class TestSchemaRegistration:
    def test_ev_severity_score_in_snapshot_columns(self):
        """SNAPSHOT_COLUMNS should include ev_severity_score in Runway Severity block."""
        from run_screen_columns import SNAPSHOT_COLUMNS

        assert "ev_severity_score" in SNAPSHOT_COLUMNS
        # Should be placed near runway_severity_score
        idx_ev = SNAPSHOT_COLUMNS.index("ev_severity_score")
        idx_run = SNAPSHOT_COLUMNS.index("runway_severity_score")
        assert abs(idx_ev - idx_run) <= 2, "ev_severity_score should be near runway_severity_score in schema"

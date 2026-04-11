"""Tests for event_ev.expectation_error_model (EES v1)."""

from __future__ import annotations

import pytest

from event_ev.expectation_error_model import (
    EES_CSV_COLUMNS,
    ExpectationErrorModel,
    _clamp,
    _phase_bucket,
    _safe_float,
    enrich_csv_rows,
)

# ── Fixtures ─────────────────────────────────────────────────────────────


def _row(
    ticker: str = "ACAD",
    priced_move_pct: str = "15.0",
    short_interest_pct: str = "8.5",
    market_cap_mm: str = "4500.0",
    close_price: str = "22.50",
    implied_event_move: str = "12.0",
    catalyst_family: str = "CLINICAL",
    lead_program_phase: str = "3",
    clinical_days_precision: str = "DAY",
) -> dict:
    return {
        "ticker": ticker,
        "priced_move_pct": priced_move_pct,
        "short_interest_pct": short_interest_pct,
        "market_cap_mm": market_cap_mm,
        "close_price": close_price,
        "implied_event_move": implied_event_move,
        "catalyst_family": catalyst_family,
        "lead_program_phase": lead_program_phase,
        "clinical_days_precision": clinical_days_precision,
    }


# ── Helpers ──────────────────────────────────────────────────────────────


class TestHelpers:
    def test_clamp(self):
        assert _clamp(-2, -1, 1) == -1
        assert _clamp(0.5, -1, 1) == 0.5
        assert _clamp(2, -1, 1) == 1

    def test_safe_float_valid(self):
        assert _safe_float("3.14") == pytest.approx(3.14)
        assert _safe_float(42) == pytest.approx(42.0)

    def test_safe_float_none_cases(self):
        assert _safe_float(None) is None
        assert _safe_float("") is None
        assert _safe_float("None") is None
        assert _safe_float("nan") is None
        assert _safe_float("bad") is None

    def test_phase_bucket(self):
        assert _phase_bucket("3") == "phase3"
        assert _phase_bucket("2") == "phase2"
        assert _phase_bucket("1") == "early"
        assert _phase_bucket("unknown") == "early"
        assert _phase_bucket("") == "early"


# ── Base Rate Gap ────────────────────────────────────────────────────────


class TestBaseRateGap:
    def test_above_base_rate(self):
        """Implied move well above historical → positive gap score."""
        model = ExpectationErrorModel()
        r = _row(priced_move_pct="80.0", catalyst_family="CLINICAL", lead_program_phase="3")
        result = model.score_row(r, "2026-04-10")
        assert result.base_rate_gap_score > 0.5

    def test_below_base_rate(self):
        """Implied move well below historical → negative gap score."""
        model = ExpectationErrorModel()
        r = _row(priced_move_pct="5.0", catalyst_family="CLINICAL", lead_program_phase="3")
        result = model.score_row(r, "2026-04-10")
        assert result.base_rate_gap_score < -0.5

    def test_at_base_rate(self):
        """Implied move near historical median → near-zero gap."""
        model = ExpectationErrorModel()
        # CLINICAL|phase3 base rate p50 = 35.0
        r = _row(priced_move_pct="35.0")
        result = model.score_row(r, "2026-04-10")
        assert abs(result.base_rate_gap_score) < 0.1

    def test_missing_priced_move(self):
        model = ExpectationErrorModel()
        r = _row(priced_move_pct="")
        result = model.score_row(r, "2026-04-10")
        assert result.base_rate_gap_score == 0.0


# ── Conditional Misprice ─────────────────────────────────────────────────


class TestConditionalMisprice:
    def test_underpriced_scenario(self):
        """Implied move < conditional EV → positive (underpriced)."""
        model = ExpectationErrorModel()
        # CLINICAL|phase3 conditional EV ≈ 29.2
        r = _row(priced_move_pct="10.0")
        result = model.score_row(r, "2026-04-10")
        assert result.conditional_misprice_score > 0.5

    def test_overpriced_scenario(self):
        """Implied move >> conditional EV → negative (overpriced)."""
        model = ExpectationErrorModel()
        r = _row(priced_move_pct="80.0")
        result = model.score_row(r, "2026-04-10")
        assert result.conditional_misprice_score < -0.5


# ── Slippage Penalty ─────────────────────────────────────────────────────


class TestSlippagePenalty:
    def test_large_cap_no_penalty(self):
        model = ExpectationErrorModel()
        r = _row(market_cap_mm="5000.0", close_price="50.0")
        result = model.score_row(r, "2026-04-10")
        assert result.slippage_penalty_score == 0.0

    def test_micro_cap_penalty(self):
        model = ExpectationErrorModel()
        r = _row(market_cap_mm="80.0", close_price="3.50")
        result = model.score_row(r, "2026-04-10")
        assert result.slippage_penalty_score == 1.0  # penny + micro cap

    def test_small_cap_moderate(self):
        model = ExpectationErrorModel()
        r = _row(market_cap_mm="200.0", close_price="12.0")
        result = model.score_row(r, "2026-04-10")
        assert result.slippage_penalty_score == pytest.approx(0.30)


# ── Divergence ───────────────────────────────────────────────────────────


class TestDivergence:
    def test_options_rich(self):
        """Option implied >> realised → positive divergence."""
        model = ExpectationErrorModel()
        r = _row(priced_move_pct="30.0", implied_event_move="10.0")
        result = model.score_row(r, "2026-04-10")
        assert result.divergence_score > 0.5

    def test_options_cheap(self):
        """Option implied << realised → negative divergence."""
        model = ExpectationErrorModel()
        r = _row(priced_move_pct="5.0", implied_event_move="20.0")
        result = model.score_row(r, "2026-04-10")
        assert result.divergence_score < -0.5

    def test_missing_implied_event_move(self):
        model = ExpectationErrorModel()
        r = _row(implied_event_move="")
        result = model.score_row(r, "2026-04-10")
        assert result.divergence_score == 0.0


# ── Crowding Bias ────────────────────────────────────────────────────────


class TestCrowdingBias:
    def test_high_short_interest(self):
        model = ExpectationErrorModel()
        r = _row(short_interest_pct="25.0")
        result = model.score_row(r, "2026-04-10", si_p50=5.0, si_p90=20.0)
        assert result.crowding_bias_score > 0.5

    def test_low_short_interest(self):
        model = ExpectationErrorModel()
        r = _row(short_interest_pct="2.0")
        result = model.score_row(r, "2026-04-10", si_p50=5.0, si_p90=20.0)
        assert result.crowding_bias_score < 0.0

    def test_missing_short_interest(self):
        model = ExpectationErrorModel()
        r = _row(short_interest_pct="")
        result = model.score_row(r, "2026-04-10", si_p50=5.0, si_p90=20.0)
        assert result.crowding_bias_score == 0.0


# ── Timing Decay Risk ────────────────────────────────────────────────────


class TestTimingDecayRisk:
    def test_exact_date_no_risk(self):
        model = ExpectationErrorModel()
        r = _row(priced_move_pct="15.0", clinical_days_precision="DAY")
        result = model.score_row(r, "2026-04-10")
        assert result.timing_decay_risk_score == 0.0

    def test_uncertain_timing_high_move(self):
        model = ExpectationErrorModel()
        r = _row(priced_move_pct="30.0", clinical_days_precision="UNKNOWN")
        result = model.score_row(r, "2026-04-10")
        assert result.timing_decay_risk_score > 0.5

    def test_quarter_moderate(self):
        model = ExpectationErrorModel()
        r = _row(priced_move_pct="15.0", clinical_days_precision="QUARTER")
        result = model.score_row(r, "2026-04-10")
        assert result.timing_decay_risk_score == pytest.approx(0.75)


# ── Composite Score ──────────────────────────────────────────────────────


class TestCompositeScore:
    def test_positive_ees_when_underpriced(self):
        """Name at base rate with underpriced conditional + no frictions → positive EES."""
        model = ExpectationErrorModel()
        # REGULATORY|phase3: base rate p50=19, conditional EV ≈15.1
        # priced_move_pct=10 is below conditional EV (underpriced) and below base rate
        # But conditional_misprice dominates since we pick family with lower spread
        r = _row(
            priced_move_pct="10.0",
            short_interest_pct="2.0",  # below P50 → negative crowding (favorable)
            market_cap_mm="5000.0",
            close_price="50.0",
            implied_event_move="10.0",  # no divergence
            clinical_days_precision="DAY",
            catalyst_family="REGULATORY",
            lead_program_phase="3",
        )
        result = model.score_row(r, "2026-04-10", si_p50=5.0, si_p90=20.0)
        # conditional misprice is positive (+0.51), base rate negative (-0.33)
        # but frictions all zero → net positive
        assert result.conditional_misprice_score > 0.3

    def test_negative_ees_high_friction(self):
        """Micro-cap penny stock with uncertain timing → large penalties."""
        model = ExpectationErrorModel()
        r = _row(
            priced_move_pct="35.0",  # at base rate (neutral)
            short_interest_pct="5.0",
            market_cap_mm="50.0",  # micro cap
            close_price="2.0",  # penny stock
            implied_event_move="35.0",
            clinical_days_precision="UNKNOWN",
        )
        result = model.score_row(r, "2026-04-10", si_p50=5.0, si_p90=20.0)
        # slippage = 1.0, timing = high → penalties dominate
        assert result.slippage_penalty_score == 1.0
        assert result.timing_decay_risk_score > 0.5


# ── v2 Overlays ─────────────────────────────────────────────────────────


class TestV2Overlays:
    def test_quality_negative_for_micro_cap(self):
        """Micro-cap penny stock → quality score strongly negative."""
        model = ExpectationErrorModel()
        r = _row(market_cap_mm="50.0", close_price="2.0", clinical_days_precision="UNKNOWN")
        result = model.score_row(r, "2026-04-10")
        assert result.quality_overlay_score < -0.5

    def test_quality_zero_for_clean_name(self):
        """Large cap, known date → quality near zero (no penalty)."""
        model = ExpectationErrorModel()
        r = _row(market_cap_mm="5000.0", close_price="50.0", clinical_days_precision="DAY")
        result = model.score_row(r, "2026-04-10")
        assert result.quality_overlay_score == pytest.approx(0.0, abs=0.01)

    def test_trap_negative_for_obvious_cheap(self):
        """Name that looks underpriced by scenario EV → trap detector fires (negative)."""
        model = ExpectationErrorModel()
        # priced_move=10 is well below conditional EV (~29) → positive conditional_misprice
        # trap flips this: trap_score should be negative (avoid this name)
        r = _row(priced_move_pct="10.0", clinical_days_precision="DAY")
        result = model.score_row(r, "2026-04-10")
        assert result.trap_overlay_score < 0.0

    def test_trap_less_negative_when_overpriced(self):
        """Name that looks overpriced → trap is less alarmed."""
        model = ExpectationErrorModel()
        r = _row(priced_move_pct="80.0", clinical_days_precision="DAY")
        result = model.score_row(r, "2026-04-10")
        # conditional_misprice is negative (overpriced), base_rate_gap positive
        # Flipped: trap should be less negative / more positive
        assert result.trap_overlay_score > -0.2

    def test_v2_combines_quality_and_trap(self):
        """v2 is a 60/40 blend of quality and trap."""
        model = ExpectationErrorModel()
        r = _row(
            priced_move_pct="10.0",
            market_cap_mm="50.0",
            close_price="2.0",
            clinical_days_precision="UNKNOWN",
        )
        result = model.score_row(r, "2026-04-10")
        # Quality strongly negative (micro-cap + uncertain timing)
        assert result.quality_overlay_score < -0.5
        # v2 = 0.60*quality + 0.40*trap, so v2 is between quality and trap
        expected = 0.60 * result.quality_overlay_score + 0.40 * result.trap_overlay_score
        assert result.ees_v2_score == pytest.approx(expected, abs=0.01)

    def test_v2_fields_present_in_to_dict(self):
        model = ExpectationErrorModel()
        r = _row()
        result = model.score_row(r, "2026-04-10")
        d = result.to_dict()
        assert "quality_overlay_score" in d
        assert "trap_overlay_score" in d
        assert "ees_v2_score" in d

    def test_v2_model_version(self):
        model = ExpectationErrorModel()
        r = _row()
        result = model.score_row(r, "2026-04-10")
        assert result.model_version == "ees_v2.0"


# ── Confidence ───────────────────────────────────────────────────────────


class TestConfidence:
    def test_full_data_high_confidence(self):
        model = ExpectationErrorModel()
        r = _row(clinical_days_precision="DAY")
        result = model.score_row(r, "2026-04-10")
        assert result.expectation_confidence == pytest.approx(1.0)

    def test_missing_priced_move_lower(self):
        model = ExpectationErrorModel()
        r = _row(priced_move_pct="", clinical_days_precision="DAY")
        result = model.score_row(r, "2026-04-10")
        assert result.expectation_confidence == pytest.approx(0.75)

    def test_uncertain_timing_lower(self):
        model = ExpectationErrorModel()
        r = _row(clinical_days_precision="UNKNOWN")
        result = model.score_row(r, "2026-04-10")
        assert result.expectation_confidence == pytest.approx(0.80)

    def test_all_missing_lowest(self):
        model = ExpectationErrorModel()
        r = _row(
            priced_move_pct="",
            short_interest_pct="",
            market_cap_mm="",
            clinical_days_precision="UNKNOWN",
        )
        result = model.score_row(r, "2026-04-10")
        assert result.expectation_confidence < 0.5


# ── Batch Scoring ────────────────────────────────────────────────────────


class TestBatchScoring:
    def test_batch_returns_same_length(self):
        rows = [_row(ticker="A"), _row(ticker="B"), _row(ticker="C")]
        model = ExpectationErrorModel()
        results = model.score_batch(rows, "2026-04-10")
        assert len(results) == 3

    def test_batch_preserves_order(self):
        rows = [_row(ticker="AAAA"), _row(ticker="ZZZZ")]
        model = ExpectationErrorModel()
        results = model.score_batch(rows, "2026-04-10")
        assert results[0].ticker == "AAAA"
        assert results[1].ticker == "ZZZZ"

    def test_batch_cross_sectional_crowding(self):
        """Names with extreme SI should differ from median SI names."""
        rows = [
            _row(ticker="LOW_SI", short_interest_pct="1.0"),
            _row(ticker="MED_SI", short_interest_pct="5.0"),
            _row(ticker="HIGH_SI", short_interest_pct="30.0"),
        ]
        model = ExpectationErrorModel()
        results = model.score_batch(rows, "2026-04-10")
        by_ticker = {r.ticker: r for r in results}
        assert by_ticker["HIGH_SI"].crowding_bias_score > by_ticker["LOW_SI"].crowding_bias_score


# ── Notes ────────────────────────────────────────────────────────────────


class TestNotes:
    def test_notes_include_crowded(self):
        model = ExpectationErrorModel()
        r = _row(short_interest_pct="25.0")
        result = model.score_row(r, "2026-04-10", si_p50=5.0, si_p90=10.0)
        assert "crowded" in result.expectation_notes

    def test_notes_include_timing(self):
        model = ExpectationErrorModel()
        r = _row(priced_move_pct="30.0", clinical_days_precision="UNKNOWN")
        result = model.score_row(r, "2026-04-10")
        assert "timing decay" in result.expectation_notes

    def test_notes_empty_when_unremarkable(self):
        model = ExpectationErrorModel()
        r = _row(
            priced_move_pct="35.0",  # near base rate
            short_interest_pct="5.0",
            market_cap_mm="5000.0",
            close_price="50.0",
            implied_event_move="30.0",
            clinical_days_precision="DAY",
        )
        result = model.score_row(r, "2026-04-10", si_p50=5.0, si_p90=20.0)
        assert result.expectation_notes == ""


# ── enrich_csv_rows ──────────────────────────────────────────────────────


class TestEnrichCsvRows:
    def test_injects_all_columns(self):
        rows = [_row()]
        enrich_csv_rows(rows, "2026-04-10")
        for col in EES_CSV_COLUMNS:
            assert col in rows[0], f"Missing column: {col}"

    def test_returns_scores(self):
        rows = [_row(), _row(ticker="BIIB")]
        scores = enrich_csv_rows(rows, "2026-04-10")
        assert len(scores) == 2
        assert scores[0].ticker == "ACAD"


# ── Dataclass serialisation ──────────────────────────────────────────────


class TestSerialisation:
    def test_to_dict_roundtrip(self):
        model = ExpectationErrorModel()
        r = _row()
        result = model.score_row(r, "2026-04-10")
        d = result.to_dict()
        assert d["ticker"] == "ACAD"
        assert "base_rate_gap_score" in d
        assert "model_version" in d
        assert isinstance(d["expectation_notes"], str)


# ── Gate computation ─────────────────────────────────────────────────────


class TestGateComputation:
    def test_gates_filter_worst_names(self):
        """Micro-cap penny stocks should fail quality gate while large caps pass."""
        rows = [
            # 5 bad names: micro-cap + penny stock
            _row(ticker="BAD0", market_cap_mm="30", close_price="0.50"),
            _row(ticker="BAD1", market_cap_mm="50", close_price="1.00"),
            _row(ticker="BAD2", market_cap_mm="80", close_price="2.00"),
            _row(ticker="BAD3", market_cap_mm="90", close_price="3.00"),
            _row(ticker="BAD4", market_cap_mm="150", close_price="4.00"),
            # 5 good names: large cap
            _row(ticker="OK0", market_cap_mm="2000", close_price="30.0"),
            _row(ticker="OK1", market_cap_mm="3000", close_price="40.0"),
            _row(ticker="OK2", market_cap_mm="5000", close_price="50.0"),
            _row(ticker="OK3", market_cap_mm="8000", close_price="60.0"),
            _row(ticker="OK4", market_cap_mm="10000", close_price="70.0"),
        ]
        model = ExpectationErrorModel()
        scores = model.score_batch(rows, "2026-04-10")
        gates = ExpectationErrorModel.compute_gates(scores, quality_cut_pct=40, trap_cut_pct=0)
        # All OK names should pass quality gate
        for ticker in ["OK0", "OK1", "OK2", "OK3", "OK4"]:
            assert gates[ticker]["ees_quality_gate"] is True, f"{ticker} should pass"
        # At least some BAD names should fail
        bad_fails = sum(1 for t in ["BAD0", "BAD1", "BAD2", "BAD3", "BAD4"] if not gates[t]["ees_quality_gate"])
        assert bad_fails >= 3

    def test_high_cut_filters_more(self):
        """Higher cutoff should filter more names."""
        rows = [
            _row(ticker="MICRO", market_cap_mm="50", close_price="1.0"),
            _row(ticker="SMALL", market_cap_mm="200", close_price="8.0"),
            _row(ticker="MID", market_cap_mm="2000", close_price="30.0"),
            _row(ticker="LARGE", market_cap_mm="10000", close_price="50.0"),
        ]
        model = ExpectationErrorModel()
        scores = model.score_batch(rows, "2026-04-10")
        gates_20 = ExpectationErrorModel.compute_gates(scores, quality_cut_pct=20, trap_cut_pct=0)
        gates_50 = ExpectationErrorModel.compute_gates(scores, quality_cut_pct=50, trap_cut_pct=0)
        n_pass_20 = sum(1 for g in gates_20.values() if g["ees_quality_gate"])
        n_pass_50 = sum(1 for g in gates_50.values() if g["ees_quality_gate"])
        assert n_pass_20 >= n_pass_50

    def test_gate_output_has_percentiles(self):
        rows = [_row(ticker=f"T{i}") for i in range(5)]
        model = ExpectationErrorModel()
        scores = model.score_batch(rows, "2026-04-10")
        gates = ExpectationErrorModel.compute_gates(scores)
        first = next(iter(gates.values()))
        assert "quality_pctile" in first
        assert "trap_pctile" in first
        assert "quality_threshold" in first


# ── Regime toggle ────────────────────────────────────────────────────────


class TestRegimeToggle:
    def test_normal_mode(self):
        from event_ev.expectation_error_model import resolve_gate_mode

        cfg = resolve_gate_mode("normal")
        assert cfg["quality_cut_pct"] == 15
        assert cfg["trap_cut_pct"] == 20

    def test_conservative_mode(self):
        from event_ev.expectation_error_model import resolve_gate_mode

        cfg = resolve_gate_mode("conservative")
        assert cfg["quality_cut_pct"] == 20
        assert cfg["trap_cut_pct"] == 30

    def test_unknown_mode_falls_back(self):
        from event_ev.expectation_error_model import resolve_gate_mode

        cfg = resolve_gate_mode("unknown_mode")
        assert cfg["quality_cut_pct"] == 15  # falls back to normal

    def test_enrich_accepts_gate_mode(self):
        rows = [_row(ticker="A"), _row(ticker="B")]
        enrich_csv_rows(rows, "2026-04-10", gate_mode="conservative")
        assert "ees_quality_gate" in rows[0]


# ── Gate diagnostics ─────────────────────────────────────────────────────


class TestGateDiagnostics:
    def test_diagnostics_structure(self):
        from event_ev.expectation_error_model import build_gate_diagnostics

        rows = [_row(ticker=f"T{i}", market_cap_mm=str(50 + i * 100)) for i in range(20)]
        scores = enrich_csv_rows(rows, "2026-04-10")
        diag = build_gate_diagnostics(scores, rows, "2026-04-10")
        assert diag["as_of_date"] == "2026-04-10"
        assert diag["model_version"] == "ees_v2.0"
        assert "universe" in diag
        assert diag["universe"]["total"] == 20
        assert "eligible" in diag["universe"]
        assert "quality_fail" in diag["universe"]
        assert "trap_fail" in diag["universe"]
        assert "quality_trap_correlation" in diag
        assert "quality_distribution" in diag
        assert "trap_distribution" in diag

    def test_diagnostics_eligible_count_matches(self):
        from event_ev.expectation_error_model import build_gate_diagnostics

        rows = [_row(ticker=f"T{i}") for i in range(10)]
        scores = enrich_csv_rows(rows, "2026-04-10")
        diag = build_gate_diagnostics(scores, rows, "2026-04-10")
        n_elig = sum(1 for r in rows if r.get("ees_eligible") is True)
        assert diag["universe"]["eligible"] == n_elig


# ── Gate performance ─────────────────────────────────────────────────────


class TestGatePerformance:
    def test_returns_none_without_prior(self):
        from event_ev.expectation_error_model import build_gate_performance

        rows = [_row()]
        result = build_gate_performance(rows, None, "2026-04-10")
        assert result is None

    def test_computes_bucket_returns(self):
        from event_ev.expectation_error_model import build_gate_performance

        # Prior: price=10, eligible
        prior = [
            {
                "ticker": "A",
                "close_price": "10.0",
                "ees_quality_gate": True,
                "ees_trap_gate": True,
                "ees_eligible": True,
            }
        ]
        # Current: price=11 (+10%)
        current = [{"ticker": "A", "close_price": "11.0"}]
        result = build_gate_performance(current, prior, "2026-04-10")
        assert result is not None
        assert result["eligible"]["n"] == 1
        assert result["eligible"]["mean_ret"] == pytest.approx(10.0, abs=0.1)  # +10%

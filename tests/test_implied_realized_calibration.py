"""Tests for Spec 059 Phase A — Implied-vs-Realized Calibration + Payoff Engine Options Adjustment.

Tests written BEFORE implementation per spec template.
"""

from __future__ import annotations

from datetime import date

# ============================================================================
# Fixtures
# ============================================================================

# Minimal CRT-options join records for testing calibration
_CRT_RECORDS = [
    # REGULATORY phase3 HIT — liquid, implied 15%, realized +25%
    {
        "ticker": "PVLA",
        "catalyst_date": "2026-01-15",
        "catalyst_type": "PDUFA_ACTION",
        "outcome": "HIT",
        "opt_liquidity_state": "liquid",
        "implied_event_move": 0.15,
        "realized_1d_return": 0.25,
        "realized_5d_return": 0.22,
        "event_family": "REGULATORY",
        "phase": "3",
    },
    # REGULATORY phase3 HIT — liquid, implied 12%, realized +8%
    {
        "ticker": "ALKS",
        "catalyst_date": "2026-01-20",
        "catalyst_type": "PDUFA_ACTION",
        "outcome": "HIT",
        "opt_liquidity_state": "liquid",
        "implied_event_move": 0.12,
        "realized_1d_return": 0.08,
        "realized_5d_return": 0.10,
        "event_family": "REGULATORY",
        "phase": "3",
    },
    # REGULATORY phase3 MISS — liquid, implied 18%, realized -35%
    {
        "ticker": "CELC",
        "catalyst_date": "2026-02-10",
        "catalyst_type": "PDUFA_ACTION",
        "outcome": "MISS",
        "opt_liquidity_state": "liquid",
        "implied_event_move": 0.18,
        "realized_1d_return": -0.35,
        "realized_5d_return": -0.30,
        "event_family": "REGULATORY",
        "phase": "3",
    },
    # CLINICAL phase2 HIT — liquid, implied 20%, realized +45%
    {
        "ticker": "ACAD",
        "catalyst_date": "2026-02-15",
        "catalyst_type": "DATA_READOUT",
        "outcome": "HIT",
        "opt_liquidity_state": "liquid",
        "implied_event_move": 0.20,
        "realized_1d_return": 0.45,
        "realized_5d_return": 0.38,
        "event_family": "CLINICAL",
        "phase": "2",
    },
    # CLINICAL phase2 HIT — liquid, implied 22%, realized +30%
    {
        "ticker": "IONS",
        "catalyst_date": "2026-02-20",
        "catalyst_type": "DATA_READOUT",
        "outcome": "HIT",
        "opt_liquidity_state": "liquid",
        "implied_event_move": 0.22,
        "realized_1d_return": 0.30,
        "realized_5d_return": 0.28,
        "event_family": "CLINICAL",
        "phase": "2",
    },
    # CLINICAL phase2 MISS — thin liquidity (should be excluded)
    {
        "ticker": "TBPH",
        "catalyst_date": "2026-03-01",
        "catalyst_type": "DATA_READOUT",
        "outcome": "MISS",
        "opt_liquidity_state": "thin",
        "implied_event_move": 0.25,
        "realized_1d_return": -0.40,
        "realized_5d_return": -0.38,
        "event_family": "CLINICAL",
        "phase": "2",
    },
    # Record with missing implied move (should be excluded)
    {
        "ticker": "BIIB",
        "catalyst_date": "2026-03-05",
        "catalyst_type": "PDUFA_ACTION",
        "outcome": "HIT",
        "opt_liquidity_state": "liquid",
        "implied_event_move": None,
        "realized_1d_return": 0.05,
        "realized_5d_return": 0.03,
        "event_family": "REGULATORY",
        "phase": "3",
    },
]


def _make_node(**overrides):
    from event_ev.data_contracts import CatalystNode

    defaults = {
        "ticker": "ACAD",
        "event_family": "CLINICAL",
        "event_type": "DATA_READOUT",
        "event_subtype": "TOPLINE",
        "expected_date": "2026-06-15",
        "date_range_start": "2026-06-15",
        "date_range_end": None,
        "date_precision": "MONTH",
        "date_confidence": 0.6,
        "source": "CTGOV",
        "source_uid": "NCT12345678",
        "disclosed_at": "2026-01-15",
        "phase": "3",
        "indication": "oncology",
    }
    defaults.update(overrides)
    return CatalystNode(**defaults)


def _make_outcome(p_hit=0.6, p_miss=0.3, p_mixed=0.1, node_id="test"):
    from event_ev.data_contracts import OutcomeProbabilities

    return OutcomeProbabilities(
        node_id=node_id,
        as_of_date="2026-04-06",
        p_hit=p_hit,
        p_miss=p_miss,
        p_mixed=p_mixed,
        confidence=0.7,
        prior_source="test",
    )


# ============================================================================
# Test: Calibration Table Build
# ============================================================================


class TestCalibrationBuild:
    def test_builds_from_crt_records(self):
        from event_ev.implied_realized_calibration import build_calibration_table

        table = build_calibration_table(_CRT_RECORDS)
        assert isinstance(table, dict)
        assert "buckets" in table
        assert "meta" in table

    def test_liquid_only(self):
        """Only liquid records should be included in calibration."""
        from event_ev.implied_realized_calibration import build_calibration_table

        table = build_calibration_table(_CRT_RECORDS)
        # TBPH (thin) should be excluded
        assert table["meta"]["n_included"] <= table["meta"]["n_total"]
        # At least one record excluded (TBPH thin + BIIB missing implied)
        assert table["meta"]["n_excluded_liquidity"] >= 1

    def test_missing_implied_excluded(self):
        """Records with no implied_event_move should be excluded."""
        from event_ev.implied_realized_calibration import build_calibration_table

        table = build_calibration_table(_CRT_RECORDS)
        assert table["meta"]["n_excluded_missing_implied"] >= 1

    def test_bucket_keys(self):
        """Buckets should be keyed by family|phase_bucket|outcome."""
        from event_ev.implied_realized_calibration import build_calibration_table

        table = build_calibration_table(_CRT_RECORDS)
        # We have REGULATORY|phase3|HIT records
        assert "REGULATORY|phase3|HIT" in table["buckets"]

    def test_bucket_statistics(self):
        """Each bucket should have implied_p50, realized_abs_p50, ratio, n."""
        from event_ev.implied_realized_calibration import build_calibration_table

        table = build_calibration_table(_CRT_RECORDS)
        bucket = table["buckets"].get("REGULATORY|phase3|HIT")
        assert bucket is not None
        assert "implied_p50" in bucket
        assert "realized_abs_p50" in bucket
        assert "ratio" in bucket
        assert "n" in bucket
        assert bucket["n"] >= 2  # PVLA + ALKS

    def test_ratio_calculation(self):
        """ratio = realized_abs_p50 / implied_p50."""
        from event_ev.implied_realized_calibration import build_calibration_table

        table = build_calibration_table(_CRT_RECORDS)
        bucket = table["buckets"]["REGULATORY|phase3|HIT"]
        expected_ratio = bucket["realized_abs_p50"] / bucket["implied_p50"]
        assert abs(bucket["ratio"] - expected_ratio) < 0.01

    def test_empty_records(self):
        """Empty input should return empty table."""
        from event_ev.implied_realized_calibration import build_calibration_table

        table = build_calibration_table([])
        assert table["buckets"] == {}
        assert table["meta"]["n_total"] == 0


class TestCalibrationFallback:
    def test_small_n_returns_none(self):
        """Buckets with n < min_n should not appear as usable."""
        from event_ev.implied_realized_calibration import build_calibration_table

        # Only 1 MISS record that's liquid
        table = build_calibration_table(_CRT_RECORDS, min_n=3)
        miss_bucket = table["buckets"].get("REGULATORY|phase3|MISS")
        # Should exist but be flagged as insufficient
        if miss_bucket:
            assert miss_bucket["n"] < 3
            assert miss_bucket["usable"] is False

    def test_sufficient_n_is_usable(self):
        from event_ev.implied_realized_calibration import build_calibration_table

        table = build_calibration_table(_CRT_RECORDS, min_n=2)
        hit_bucket = table["buckets"].get("REGULATORY|phase3|HIT")
        assert hit_bucket is not None
        assert hit_bucket["usable"] is True


class TestCalibrationLookup:
    def test_lookup_existing_bucket(self):
        from event_ev.implied_realized_calibration import CalibrationLookup, build_calibration_table

        table = build_calibration_table(_CRT_RECORDS, min_n=1)
        lookup = CalibrationLookup(table)
        result = lookup.get_adjustment("REGULATORY", "phase3", "HIT")
        assert result is not None
        assert "ratio" in result

    def test_lookup_missing_bucket_returns_none(self):
        from event_ev.implied_realized_calibration import CalibrationLookup, build_calibration_table

        table = build_calibration_table(_CRT_RECORDS, min_n=1)
        lookup = CalibrationLookup(table)
        result = lookup.get_adjustment("SAFETY", "early", "MISS")
        assert result is None

    def test_lookup_unusable_bucket_returns_none(self):
        from event_ev.implied_realized_calibration import CalibrationLookup, build_calibration_table

        table = build_calibration_table(_CRT_RECORDS, min_n=10)
        lookup = CalibrationLookup(table)
        # All buckets should have n < 10
        result = lookup.get_adjustment("REGULATORY", "phase3", "HIT")
        assert result is None


# ============================================================================
# Test: Payoff Engine Options Adjustment
# ============================================================================


class TestPayoffEngineOptionsAdjustment:
    def test_no_options_context_unchanged(self):
        """Without options context, payoff engine behaves exactly as before."""
        from event_ev.payoff_engine import PayoffEngine

        engine = PayoffEngine()
        node = _make_node(event_family="CLINICAL", phase="3")
        outcome = _make_outcome(node_id=node.node_id)
        payoff = engine.estimate(node, outcome, date(2026, 4, 6))
        # Should use static prior
        assert payoff.features_used.get("upside_source") == "prior"

    def test_options_adjusted_uses_implied_move(self):
        """With liquid options data and calibration, payoff should be adjusted."""
        from event_ev.implied_realized_calibration import CalibrationLookup, build_calibration_table
        from event_ev.payoff_engine import PayoffEngine

        table = build_calibration_table(_CRT_RECORDS, min_n=1)
        lookup = CalibrationLookup(table)
        engine = PayoffEngine(options_calibration=lookup)

        node = _make_node(event_family="REGULATORY", phase="3")
        outcome = _make_outcome(node_id=node.node_id)
        context = {
            "implied_event_move": 0.15,
            "opt_liquidity_state": "liquid",
        }
        payoff = engine.estimate(node, outcome, date(2026, 4, 6), context)
        assert payoff.features_used.get("options_adjusted") is True

    def test_thin_liquidity_no_adjustment(self):
        """Thin liquidity should skip options adjustment."""
        from event_ev.implied_realized_calibration import CalibrationLookup, build_calibration_table
        from event_ev.payoff_engine import PayoffEngine

        table = build_calibration_table(_CRT_RECORDS, min_n=1)
        lookup = CalibrationLookup(table)
        engine = PayoffEngine(options_calibration=lookup)

        node = _make_node(event_family="REGULATORY", phase="3")
        outcome = _make_outcome(node_id=node.node_id)
        context = {
            "implied_event_move": 0.15,
            "opt_liquidity_state": "thin",
        }
        payoff = engine.estimate(node, outcome, date(2026, 4, 6), context)
        assert payoff.features_used.get("options_adjusted") is not True

    def test_absent_options_no_adjustment(self):
        """Absent options should skip adjustment entirely."""
        from event_ev.implied_realized_calibration import CalibrationLookup, build_calibration_table
        from event_ev.payoff_engine import PayoffEngine

        table = build_calibration_table(_CRT_RECORDS, min_n=1)
        lookup = CalibrationLookup(table)
        engine = PayoffEngine(options_calibration=lookup)

        node = _make_node(event_family="REGULATORY", phase="3")
        outcome = _make_outcome(node_id=node.node_id)
        context = {"opt_liquidity_state": "absent"}
        payoff = engine.estimate(node, outcome, date(2026, 4, 6), context)
        assert payoff.features_used.get("options_adjusted") is not True

    def test_options_adjusted_move_differs_from_static(self):
        """When options are used, the payoff should differ from static-only."""
        from event_ev.implied_realized_calibration import CalibrationLookup, build_calibration_table
        from event_ev.payoff_engine import PayoffEngine

        table = build_calibration_table(_CRT_RECORDS, min_n=1)
        lookup = CalibrationLookup(table)

        node = _make_node(event_family="REGULATORY", phase="3")
        outcome = _make_outcome(node_id=node.node_id)

        # Static (no options)
        engine_static = PayoffEngine()
        payoff_static = engine_static.estimate(node, outcome, date(2026, 4, 6))

        # Options-adjusted
        engine_opts = PayoffEngine(options_calibration=lookup)
        context = {
            "implied_event_move": 0.15,
            "opt_liquidity_state": "liquid",
        }
        payoff_opts = engine_opts.estimate(node, outcome, date(2026, 4, 6), context)

        # They should differ (options-implied move ≠ static prior)
        # Unless they happen to be identical, which is unlikely
        assert payoff_opts.features_used.get("options_adjusted") is True
        # At minimum, source should differ
        assert payoff_opts.features_used.get("upside_source") != payoff_static.features_used.get("upside_source")

    def test_calibration_blend_weight(self):
        """Options adjustment should blend with static prior, not replace it entirely."""
        from event_ev.implied_realized_calibration import CalibrationLookup, build_calibration_table
        from event_ev.payoff_engine import PayoffEngine

        table = build_calibration_table(_CRT_RECORDS, min_n=1)
        lookup = CalibrationLookup(table)
        engine = PayoffEngine(options_calibration=lookup)

        node = _make_node(event_family="REGULATORY", phase="3")
        outcome = _make_outcome(node_id=node.node_id)

        # Use a very extreme implied move — blend should temper it
        context = {
            "implied_event_move": 0.80,  # 80% implied move
            "opt_liquidity_state": "liquid",
        }
        payoff = engine.estimate(node, outcome, date(2026, 4, 6), context)

        # The upside shouldn't be purely 80% * ratio — it should be blended with the static prior
        static_upside = 8.0  # REGULATORY|phase3|HIT p50 from _DEFAULT_MOVE_PRIORS
        assert payoff.upside_hit != static_upside  # should differ from pure static
        # But shouldn't be astronomical
        assert payoff.upside_hit < 200.0  # sanity cap


class TestForwardLog:
    def test_forward_log_entry_format(self):
        """Forward log entries should have the right fields."""
        from event_ev.implied_realized_calibration import make_forward_log_entry

        entry = make_forward_log_entry(
            ticker="PVLA",
            event_type="PDUFA",
            event_family="REGULATORY",
            phase="3",
            implied_event_move=0.15,
            catalyst_days=7,
            opt_liquidity_state="liquid",
            snapshot_date="2026-04-06",
        )
        assert entry["ticker"] == "PVLA"
        assert entry["implied_event_move"] == 0.15
        assert entry["catalyst_days"] == 7
        assert entry["opt_liquidity_state"] == "liquid"
        assert "snapshot_date" in entry

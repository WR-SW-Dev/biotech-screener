"""Tests for the Event EV Engine (Spec 057).

Covers all six layers + the EV calculator orchestrator.
"""

from __future__ import annotations

from datetime import date
from typing import Any

# ============================================================================
# Fixtures
# ============================================================================


def _make_node(**overrides: Any):
    """Create a test CatalystNode."""
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


def _make_pdufa_node(**overrides: Any):
    """Create a PDUFA test node."""
    defaults = {
        "ticker": "PVLA",
        "event_family": "REGULATORY",
        "event_type": "PDUFA",
        "event_subtype": "FDA_ACTION",
        "expected_date": "2026-05-24",
        "date_range_start": "2026-05-24",
        "date_range_end": "2026-05-24",
        "date_precision": "DAY",
        "date_confidence": 0.9,
        "source": "PDUFA_MANUAL",
        "source_uid": "pdufa_PVLA_2026-05-24",
        "disclosed_at": "2026-01-01",
        "phase": "3",
        "indication": "rare_disease",
    }
    defaults.update(overrides)
    from event_ev.data_contracts import CatalystNode

    return CatalystNode(**defaults)


# ============================================================================
# Layer 1 — Data Contracts & Catalyst Graph
# ============================================================================


class TestCatalystNode:
    def test_node_id_deterministic(self):
        n1 = _make_node()
        n2 = _make_node()
        assert n1.node_id == n2.node_id

    def test_node_id_changes_with_inputs(self):
        n1 = _make_node(ticker="ACAD")
        n2 = _make_node(ticker="BIIB")
        assert n1.node_id != n2.node_id

    def test_days_to_event(self):
        node = _make_node(expected_date="2026-06-15")
        days = node.days_to_event(date(2026, 4, 4))
        assert days == 72

    def test_days_to_event_none(self):
        node = _make_node(expected_date=None)
        assert node.days_to_event(date(2026, 4, 4)) is None

    def test_is_visible_before_disclosure(self):
        node = _make_node(disclosed_at="2026-03-01")
        assert not node.is_visible(date(2026, 2, 1))
        assert node.is_visible(date(2026, 3, 1))
        assert node.is_visible(date(2026, 4, 1))

    def test_is_resolved(self):
        node = _make_node(status="RESOLVED", resolution="HIT")
        assert node.is_resolved()

    def test_not_resolved(self):
        node = _make_node(status="PENDING")
        assert not node.is_resolved()

    def test_to_dict_roundtrip(self):
        node = _make_node()
        d = node.to_dict()
        assert d["ticker"] == "ACAD"
        assert d["event_type"] == "DATA_READOUT"
        assert "node_id" in d

    def test_pit_revisions(self):
        from event_ev.data_contracts import CatalystRevision

        rev1 = CatalystRevision("2026-02-01", "expected_date", "2026-06-15", "2026-07-01", "ledger")
        rev2 = CatalystRevision("2026-05-01", "expected_date", "2026-07-01", "2026-08-01", "ledger")
        node = _make_node(revisions=[rev1, rev2])

        # Only rev1 visible before March
        pit = node.pit_revisions(date(2026, 3, 1))
        assert len(pit) == 1
        assert pit[0].new_value == "2026-07-01"

        # Both visible in June
        pit = node.pit_revisions(date(2026, 6, 1))
        assert len(pit) == 2


class TestCatalystGraph:
    def test_add_and_retrieve(self):
        from event_ev.catalyst_graph import CatalystGraph

        graph = CatalystGraph()
        node = _make_node()
        graph.add_node(node)
        assert graph.node_count == 1
        assert graph.get_node(node.node_id) is node

    def test_ticker_nodes(self):
        from event_ev.catalyst_graph import CatalystGraph

        graph = CatalystGraph()
        n1 = _make_node(ticker="ACAD", source_uid="NCT111")
        n2 = _make_node(ticker="ACAD", source_uid="NCT222")
        n3 = _make_node(ticker="BIIB", source_uid="NCT333")
        graph.add_node(n1)
        graph.add_node(n2)
        graph.add_node(n3)

        acad = graph.get_ticker_nodes("ACAD")
        assert len(acad) == 2
        biib = graph.get_ticker_nodes("BIIB")
        assert len(biib) == 1

    def test_event_cohort_filters(self):
        from event_ev.catalyst_graph import CatalystGraph

        graph = CatalystGraph()
        # Near event (30 days out)
        graph.add_node(
            _make_node(
                expected_date="2026-05-04",
                disclosed_at="2026-01-01",
                source_uid="NCT_NEAR",
            )
        )
        # Far event (300 days out)
        graph.add_node(
            _make_node(
                expected_date="2027-02-01",
                disclosed_at="2026-01-01",
                source_uid="NCT_FAR",
            )
        )
        # Resolved event
        graph.add_node(
            _make_node(
                expected_date="2026-05-04",
                disclosed_at="2026-01-01",
                source_uid="NCT_RESOLVED",
                status="RESOLVED",
                resolution="HIT",
            )
        )

        cohort = graph.get_event_cohort(date(2026, 4, 4), max_days=180)
        assert len(cohort) == 1
        assert cohort[0].source_uid == "NCT_NEAR"

    def test_load_from_pdufa(self):
        from event_ev.catalyst_graph import CatalystGraph

        graph = CatalystGraph()
        entries = [
            {"ticker": "PVLA", "date": "2026-05-24", "indication": "liver"},
            {"ticker": "BIIB", "date": "2026-05-24", "indication": "neuro"},
        ]
        n = graph.load_from_pdufa(entries, date(2026, 4, 4))
        assert n == 2
        assert graph.node_count == 2

    def test_apply_resolutions(self):
        from event_ev.catalyst_graph import CatalystGraph

        graph = CatalystGraph()
        node = _make_node(expected_date="2026-03-31", disclosed_at="2026-01-01")
        graph.add_node(node)

        recs = [
            {
                "ticker": "ACAD",
                "catalyst_date": "2026-03-31",
                "resolution_date": "2026-03-31",
                "outcome": "HIT",
            }
        ]
        applied = graph.apply_resolutions(recs, date(2026, 4, 4))
        assert applied == 1
        assert node.status == "RESOLVED"
        assert node.resolution == "HIT"

    def test_deduplication(self):
        from event_ev.catalyst_graph import CatalystGraph

        graph = CatalystGraph()
        n1 = _make_node()
        n2 = _make_node()  # same inputs → same node_id
        graph.add_node(n1)
        graph.add_node(n2)
        assert graph.node_count == 1  # deduped


# ============================================================================
# Layer 2 — Timing Hazard
# ============================================================================


class TestTimingHazard:
    def test_estimate_returns_valid_probs(self):
        from event_ev.timing_hazard import TimingHazardModel

        model = TimingHazardModel()
        node = _make_node()
        est = model.estimate(node, date(2026, 4, 4))

        assert 0 <= est.prob_on_time <= 1
        assert 0 <= est.prob_slip <= 1
        assert 0 <= est.prob_early <= 1
        assert abs(est.prob_on_time + est.prob_slip + est.prob_early - 1.0) < 0.01

    def test_regulatory_more_on_time(self):
        from event_ev.timing_hazard import TimingHazardModel

        model = TimingHazardModel()
        clinical = _make_node(event_family="CLINICAL", date_precision="MONTH")
        regulatory = _make_pdufa_node()

        est_c = model.estimate(clinical, date(2026, 4, 4))
        est_r = model.estimate(regulatory, date(2026, 4, 4))

        assert est_r.prob_on_time > est_c.prob_on_time

    def test_revisions_reduce_on_time(self):
        from event_ev.data_contracts import CatalystRevision
        from event_ev.timing_hazard import TimingHazardModel

        model = TimingHazardModel()
        no_rev = _make_node()
        with_rev = _make_node(
            revisions=[
                CatalystRevision("2026-02-01", "expected_date", "2026-05-01", "2026-06-15", "ledger"),
                CatalystRevision("2026-03-01", "expected_date", "2026-06-15", "2026-07-01", "ledger"),
            ]
        )

        est_no = model.estimate(no_rev, date(2026, 4, 4))
        est_rev = model.estimate(with_rev, date(2026, 4, 4))

        assert est_rev.prob_on_time < est_no.prob_on_time

    def test_to_dict(self):
        from event_ev.timing_hazard import TimingHazardModel

        model = TimingHazardModel()
        est = model.estimate(_make_node(), date(2026, 4, 4))
        d = est.to_dict()
        assert "prob_on_time" in d
        assert "features_used" in d

    def test_training_data_builder(self):
        from event_ev.timing_hazard import TimingHazardModel

        model = TimingHazardModel()
        node = _make_node(
            expected_date="2026-03-01",
            disclosed_at="2025-01-01",
            status="RESOLVED",
            resolution="HIT",
        )
        records = model.build_training_data(
            [node],
            {node.node_id: "2026-03-15"},
            [date(2026, 2, 1)],
        )
        assert len(records) == 1
        assert records[0]["actual_on_time"] == 1  # 14 days < 30 day window


# ============================================================================
# Layer 3 — Outcome Model
# ============================================================================


class TestOutcomeModel:
    def test_probs_sum_to_one(self):
        from event_ev.outcome_model import OutcomeModel

        model = OutcomeModel()
        probs = model.estimate(_make_node(), date(2026, 4, 4))
        total = probs.p_hit + probs.p_miss + probs.p_mixed
        assert abs(total - 1.0) < 0.01

    def test_phase3_higher_than_phase1(self):
        from event_ev.outcome_model import OutcomeModel

        model = OutcomeModel()
        p3 = model.estimate(_make_node(phase="3"), date(2026, 4, 4))
        p1 = model.estimate(_make_node(phase="1"), date(2026, 4, 4))
        assert p3.p_hit > p1.p_hit

    def test_regulatory_prior(self):
        from event_ev.outcome_model import OutcomeModel

        model = OutcomeModel()
        pdufa = model.estimate(_make_pdufa_node(), date(2026, 4, 4))
        assert pdufa.p_hit > 0.6  # PDUFA base rate is ~85%

    def test_endpoint_strength_shifts_up(self):
        from event_ev.outcome_model import OutcomeModel

        model = OutcomeModel()
        base = model.estimate(_make_node(), date(2026, 4, 4))
        strong = model.estimate(
            _make_node(),
            date(2026, 4, 4),
            context={"endpoint_strength_score": 0.9},
        )
        assert strong.p_hit > base.p_hit

    def test_mixed_allocation_bounded(self):
        from event_ev.outcome_model import OutcomeModel

        model = OutcomeModel()
        probs = model.estimate(_make_node(), date(2026, 4, 4))
        assert 0.02 <= probs.p_mixed <= 0.30

    def test_confidence_varies(self):
        from event_ev.outcome_model import OutcomeModel

        model = OutcomeModel()
        p3 = model.estimate(_make_node(phase="3"), date(2026, 4, 4))
        p1 = model.estimate(_make_node(phase="1"), date(2026, 4, 4))
        # Phase 3 should have higher confidence than phase 1
        assert p3.confidence > p1.confidence

    def test_calibration_eval_with_data(self):
        from event_ev.outcome_model import OutcomeModel

        model = OutcomeModel()
        # Create a set of predictions and actuals
        predictions = [
            model.estimate(_make_node(phase="3"), date(2026, 4, 4)),
            model.estimate(_make_node(phase="2"), date(2026, 4, 4)),
            model.estimate(_make_node(phase="1"), date(2026, 4, 4)),
            model.estimate(_make_node(phase="3"), date(2026, 4, 4)),
            model.estimate(_make_node(phase="2"), date(2026, 4, 4)),
        ]
        actuals = ["HIT", "MISS", "MISS", "HIT", "MIXED"]

        cal = model.evaluate_calibration(predictions, actuals)
        assert "brier_score" in cal
        assert "ece" in cal
        assert cal["n"] == 5


# ============================================================================
# Layer 4 — Expectation Model
# ============================================================================


class TestExpectationModel:
    def test_basic_estimate(self):
        from event_ev.expectation_model import ExpectationModel

        model = ExpectationModel()
        belief = model.estimate(
            _make_node(),
            date(2026, 4, 4),
            {"coinvest_score_z": 1.5, "inst_delta_z": 0.8},
        )
        assert 0 <= belief.implied_p_hit <= 1
        assert belief.belief_direction in ("BULLISH", "BEARISH", "NEUTRAL", "UNCERTAIN")

    def test_high_coinvest_bullish(self):
        from event_ev.expectation_model import ExpectationModel

        model = ExpectationModel()
        bullish = model.estimate(
            _make_node(),
            date(2026, 4, 4),
            {"coinvest_score_z": 2.5, "inst_delta_z": 2.0, "alpha_60d": 0.3},
        )
        bearish = model.estimate(
            _make_node(),
            date(2026, 4, 4),
            {"coinvest_score_z": -1.5, "inst_delta_z": -1.0, "alpha_60d": -0.3},
        )
        assert bullish.implied_p_hit > bearish.implied_p_hit

    def test_mispricing_score(self):
        from event_ev.expectation_model import ExpectationModel

        model = ExpectationModel()
        belief = model.estimate(
            _make_node(),
            date(2026, 4, 4),
            {"coinvest_score_z": -1.0},
            model_p_hit=0.7,
        )
        # Model thinks 70% hit, market is bearish → positive mispricing
        assert belief.mispricing_score > 0

    def test_no_features_neutral(self):
        from event_ev.expectation_model import ExpectationModel

        model = ExpectationModel()
        belief = model.estimate(_make_node(), date(2026, 4, 4), {})
        # With no features, should be near neutral
        assert abs(belief.implied_p_hit - 0.5) < 0.2


# ============================================================================
# Layer 5 — Payoff Engine
# ============================================================================


class TestPayoffEngine:
    def test_basic_payoff(self):
        from event_ev.outcome_model import OutcomeModel
        from event_ev.payoff_engine import PayoffEngine

        engine = PayoffEngine()
        outcome_model = OutcomeModel()

        node = _make_node()
        outcome = outcome_model.estimate(node, date(2026, 4, 4))
        payoff = engine.estimate(node, outcome, date(2026, 4, 4))

        assert payoff.upside_hit > 0
        assert payoff.downside_miss < 0
        assert payoff.analog_count > 0

    def test_asymmetry_ratio(self):
        from event_ev.outcome_model import OutcomeModel
        from event_ev.payoff_engine import PayoffEngine

        engine = PayoffEngine()
        outcome = OutcomeModel().estimate(_make_node(), date(2026, 4, 4))
        payoff = engine.estimate(_make_node(), outcome, date(2026, 4, 4))

        assert payoff.asymmetry_ratio > 0

    def test_small_cap_bigger_moves(self):
        from event_ev.outcome_model import OutcomeModel
        from event_ev.payoff_engine import PayoffEngine

        engine = PayoffEngine()
        outcome = OutcomeModel().estimate(_make_node(), date(2026, 4, 4))

        small = engine.estimate(_make_node(), outcome, date(2026, 4, 4), {"market_cap_mm": 200})
        large = engine.estimate(_make_node(), outcome, date(2026, 4, 4), {"market_cap_mm": 15000})
        assert abs(small.upside_hit) > abs(large.upside_hit)

    def test_kelly_bounded(self):
        from event_ev.outcome_model import OutcomeModel
        from event_ev.payoff_engine import PayoffEngine

        engine = PayoffEngine()
        outcome = OutcomeModel().estimate(_make_node(), date(2026, 4, 4))
        payoff = engine.estimate(_make_node(), outcome, date(2026, 4, 4))

        assert 0 <= payoff.kelly_fraction <= 0.25

    def test_scenario_ev_math(self):
        """Verify scenario EV = p_hit * up + p_miss * down + p_mixed * mixed."""
        from event_ev.outcome_model import OutcomeModel
        from event_ev.payoff_engine import PayoffEngine

        engine = PayoffEngine()
        outcome = OutcomeModel().estimate(_make_node(phase="3"), date(2026, 4, 4))
        payoff = engine.estimate(_make_node(phase="3"), outcome, date(2026, 4, 4))

        expected_ev = (
            outcome.p_hit * payoff.upside_hit
            + outcome.p_miss * payoff.downside_miss
            + outcome.p_mixed * payoff.move_mixed
        )
        assert abs(payoff.scenario_ev - expected_ev) < 0.1


# ============================================================================
# Layer 6 — Portfolio Translator
# ============================================================================


class TestPortfolioTranslator:
    def _make_event_ev(self, ticker: str, ds_adj_ev: float, days: int = 60):
        """Create a minimal EventEV for testing."""
        from event_ev.data_contracts import CrowdBelief, EventEV, OutcomeProbabilities, ScenarioPayoffs, TimingEstimate

        node = _make_node(
            ticker=ticker,
            expected_date=str(date(2026, 4, 4) + __import__("datetime").timedelta(days=days)),
            source_uid=f"NCT_{ticker}",
        )
        timing = TimingEstimate(
            node_id=node.node_id,
            as_of_date="2026-04-04",
            prob_on_time=0.7,
            prob_slip=0.2,
            prob_early=0.1,
            expected_delay_days=5,
            median_arrival_days=float(days),
            hazard_rate=0.01,
        )
        outcome = OutcomeProbabilities(
            node_id=node.node_id,
            as_of_date="2026-04-04",
            p_hit=0.5,
            p_miss=0.4,
            p_mixed=0.1,
            confidence=0.6,
            prior_source="wong_et_al",
        )
        belief = CrowdBelief(
            node_id=node.node_id,
            as_of_date="2026-04-04",
            implied_p_hit=0.45,
            belief_direction="NEUTRAL",
            belief_intensity=0.3,
            priced_move_pct=None,
            mispricing_score=0.05,
        )
        payoff = ScenarioPayoffs(
            node_id=node.node_id,
            as_of_date="2026-04-04",
            upside_hit=30.0,
            downside_miss=-40.0,
            move_mixed=-2.0,
            scenario_ev=ds_adj_ev + 5,
            asymmetry_ratio=0.75,
            downside_adjusted_ev=ds_adj_ev,
            kelly_fraction=0.05,
            analog_count=50,
            analog_confidence="ok",
        )
        return EventEV(node=node, timing=timing, outcome=outcome, expectation=belief, payoff=payoff)

    def test_translate_produces_recommendations(self):
        from event_ev.portfolio_translator import PortfolioTranslator

        translator = PortfolioTranslator()
        evs = [
            self._make_event_ev("ACAD", 5.0),
            self._make_event_ev("PVLA", 3.0),
            self._make_event_ev("BIIB", -2.0),
        ]
        recs = translator.translate(evs, mode="ew_filter")
        # Only positive EV names should get recommendations
        assert len(recs) >= 2

    def test_max_weight_cap(self):
        from event_ev.portfolio_translator import PortfolioTranslator

        translator = PortfolioTranslator(max_weight_pct=3.0)
        evs = [self._make_event_ev("ACAD", 10.0)]
        recs = translator.translate(evs, mode="ev_proportional")
        for rec in recs:
            assert rec.target_weight_pct <= 3.0

    def test_hybrid_mode(self):
        from event_ev.portfolio_translator import PortfolioTranslator

        translator = PortfolioTranslator()
        evs = [self._make_event_ev("ACAD", 5.0)]
        recs = translator.translate(evs, current_weights={"ACAD": 3.0}, mode="hybrid")
        assert len(recs) == 1


# ============================================================================
# EV Calculator — Integration
# ============================================================================


class TestEVCalculator:
    def test_full_pipeline(self):
        from event_ev.ev_calculator import EventEVCalculator

        calc = EventEVCalculator(as_of_date=date(2026, 4, 4))
        nodes = [
            _make_node(
                ticker="ACAD",
                expected_date="2026-06-15",
                source_uid="NCT_A",
            ),
            _make_pdufa_node(
                ticker="PVLA",
                expected_date="2026-05-24",
            ),
        ]

        results = calc.run(
            catalyst_nodes=nodes,
            market_features={
                "ACAD": {"coinvest_score_z": 1.2, "inst_delta_z": 0.5},
                "PVLA": {"coinvest_score_z": 0.8, "inst_delta_z": 1.0},
            },
        )

        assert len(results) == 2
        for ev in results:
            assert ev.node.ticker in ("ACAD", "PVLA")
            assert ev.timing.prob_on_time > 0
            assert abs(ev.outcome.p_hit + ev.outcome.p_miss + ev.outcome.p_mixed - 1.0) < 0.01
            assert ev.payoff.scenario_ev is not None

    def test_filters_resolved(self):
        from event_ev.ev_calculator import EventEVCalculator

        calc = EventEVCalculator(as_of_date=date(2026, 4, 4))
        resolved = _make_node(status="RESOLVED", resolution="HIT", expected_date="2026-05-01")
        results = calc.run(catalyst_nodes=[resolved])
        assert len(results) == 0

    def test_filters_past_events(self):
        from event_ev.ev_calculator import EventEVCalculator

        calc = EventEVCalculator(as_of_date=date(2026, 4, 4))
        past = _make_node(expected_date="2026-03-01")
        results = calc.run(catalyst_nodes=[past])
        assert len(results) == 0

    def test_summary_table(self):
        from event_ev.ev_calculator import EventEVCalculator

        calc = EventEVCalculator(as_of_date=date(2026, 4, 4))
        results = calc.run(catalyst_nodes=[_make_node()])
        table = calc.summary_table(results)
        assert len(table) == 1
        assert "ticker" in table[0]
        assert "scenario_ev" in table[0]

    def test_results_to_json(self, tmp_path):
        from event_ev.ev_calculator import EventEVCalculator

        calc = EventEVCalculator(as_of_date=date(2026, 4, 4))
        results = calc.run(catalyst_nodes=[_make_node()])
        path = tmp_path / "test_output.json"
        json_str = calc.results_to_json(results, path)
        assert path.exists()

        import json

        data = json.loads(json_str)
        assert data["n_events"] == 1

    def test_from_graph(self):
        from event_ev.catalyst_graph import CatalystGraph
        from event_ev.ev_calculator import EventEVCalculator

        graph = CatalystGraph()
        graph.add_node(_make_node(expected_date="2026-06-15"))
        graph.add_node(_make_pdufa_node(expected_date="2026-05-24"))

        calc = EventEVCalculator(as_of_date=date(2026, 4, 4))
        results = calc.run_from_graph(graph)
        assert len(results) == 2


# ============================================================================
# Probability constraint tests
# ============================================================================


class TestProbabilityConstraints:
    """Verify probability outputs are valid across edge cases."""

    def test_outcome_extreme_phases(self):
        from event_ev.outcome_model import OutcomeModel

        model = OutcomeModel()
        for phase in ("1", "1_2", "2", "2_3", "3", "4", "unknown"):
            probs = model.estimate(_make_node(phase=phase), date(2026, 4, 4))
            total = probs.p_hit + probs.p_miss + probs.p_mixed
            assert abs(total - 1.0) < 0.01, f"Phase {phase}: probs sum to {total}"
            assert 0 < probs.p_hit < 1
            assert 0 < probs.p_miss < 1
            assert 0 < probs.p_mixed < 1

    def test_timing_all_families(self):
        from event_ev.timing_hazard import TimingHazardModel

        model = TimingHazardModel()
        for fam in ("REGULATORY", "CLINICAL", "SAFETY"):
            est = model.estimate(_make_node(event_family=fam), date(2026, 4, 4))
            total = est.prob_on_time + est.prob_slip + est.prob_early
            assert abs(total - 1.0) < 0.01, f"Family {fam}: probs sum to {total}"


# ============================================================================
# PIT Safety Tests
# ============================================================================


class TestPITSafety:
    def test_future_node_invisible(self):
        """Nodes disclosed after as_of should be invisible."""
        node = _make_node(disclosed_at="2026-06-01")
        assert not node.is_visible(date(2026, 4, 4))

    def test_future_resolution_not_applied(self):
        from event_ev.catalyst_graph import CatalystGraph

        graph = CatalystGraph()
        node = _make_node(expected_date="2026-06-15")
        graph.add_node(node)

        # Future resolution should NOT be applied
        recs = [
            {
                "ticker": "ACAD",
                "catalyst_date": "2026-06-15",
                "resolution_date": "2026-06-15",
                "outcome": "HIT",
            }
        ]
        applied = graph.apply_resolutions(recs, date(2026, 4, 4))
        assert applied == 0
        assert node.status != "RESOLVED"

    def test_training_data_pit_safe(self):
        """Training data should not use post-event features."""
        from event_ev.timing_hazard import TimingHazardModel

        model = TimingHazardModel()
        node = _make_node(
            expected_date="2026-03-01",
            disclosed_at="2025-06-01",
        )
        records = model.build_training_data(
            [node],
            {node.node_id: "2026-03-10"},
            # Try to use as_of AFTER the event → should be excluded
            [date(2026, 4, 1)],
        )
        assert len(records) == 0  # post-event date should be filtered out

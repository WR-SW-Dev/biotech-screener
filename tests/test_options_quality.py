"""Tests for Spec 045 — options diagnostics robustness layer."""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.options_quality import assess_options_quality, build_options_quality_manifest


def _make_row(**overrides):
    defaults = {
        "ticker": "TEST",
        "opt_has_data": "1",
        "opt_atm_iv": "0.85",
        "opt_front_iv": "1.10",
        "opt_back_iv": "0.65",
        "opt_term_slope": "-0.45",
        "opt_put_call_skew": "0.05",
        "opt_rr_25d": "-0.03",
        "opt_event_premium": "YES",
        "actual_implied_move_pctile": "72",
        "implied_event_move": "0.25",
        "opt_quote_ts": "2026-04-01T12:00:00+00:00",
        "opt_liquidity_ok": "1",
        "opt_use_for_judgment": "YES",
        "opt_iv_regime": "NORMAL",
        "opt_dte": "30",
    }
    defaults.update(overrides)
    return defaults


class TestDataState:
    def test_full_state(self):
        q = assess_options_quality(_make_row(), datetime(2026, 4, 1, 14, tzinfo=timezone.utc))
        assert q.data_state == "full"
        assert q.tier_mode == "full"

    def test_absent_no_data(self):
        q = assess_options_quality(_make_row(opt_has_data="0"))
        assert q.data_state == "absent"
        assert q.tier_mode == "absent"
        assert q.missing_reason == "no_chain"

    def test_stale_quote(self):
        q = assess_options_quality(
            _make_row(opt_quote_ts="2026-03-28T12:00:00+00:00"),
            datetime(2026, 4, 1, 12, tzinfo=timezone.utc),
        )
        assert q.data_state == "stale"
        assert q.staleness_gate_pass is False

    def test_partial_low_oi(self):
        q = assess_options_quality(
            _make_row(opt_liquidity_ok="0"),
            datetime(2026, 4, 1, 14, tzinfo=timezone.utc),
        )
        assert q.data_state in ("partial", "full")
        assert q.oi_gate_pass is False

    def test_partial_few_features(self):
        row = _make_row(
            opt_term_slope="",
            opt_put_call_skew="",
            opt_rr_25d="",
            actual_implied_move_pctile="",
            implied_event_move="",
            opt_liquidity_ok="0",
        )
        q = assess_options_quality(row, datetime(2026, 4, 1, 14, tzinfo=timezone.utc))
        assert q.data_state == "partial"
        assert q.tier_mode in ("reduced", "absent")


class TestMissingnessNotNeutral:
    def test_absent_has_zero_quality(self):
        q = assess_options_quality(_make_row(opt_has_data="0"))
        assert q.chain_quality_score == 0.0

    def test_absent_has_zero_features(self):
        q = assess_options_quality(_make_row(opt_has_data="0"))
        assert q.feature_count_present == 0

    def test_full_has_nonzero_quality(self):
        q = assess_options_quality(_make_row(), datetime(2026, 4, 1, 14, tzinfo=timezone.utc))
        assert q.chain_quality_score > 0.5


class TestFeatureCount:
    def test_all_present(self):
        q = assess_options_quality(_make_row(), datetime(2026, 4, 1, 14, tzinfo=timezone.utc))
        assert q.feature_count_present == 9  # all FULL_FEATURES

    def test_some_missing(self):
        row = _make_row(opt_rr_25d="", opt_term_slope="", actual_implied_move_pctile="")
        q = assess_options_quality(row, datetime(2026, 4, 1, 14, tzinfo=timezone.utc))
        assert q.feature_count_present == 6


class TestQualityScore:
    def test_full_high_quality(self):
        q = assess_options_quality(_make_row(), datetime(2026, 4, 1, 14, tzinfo=timezone.utc))
        assert q.chain_quality_score >= 0.8

    def test_stale_lower_quality(self):
        q_fresh = assess_options_quality(_make_row(), datetime(2026, 4, 1, 14, tzinfo=timezone.utc))
        q_stale = assess_options_quality(
            _make_row(opt_quote_ts="2026-03-28T12:00:00+00:00"),
            datetime(2026, 4, 1, 12, tzinfo=timezone.utc),
        )
        assert q_stale.chain_quality_score < q_fresh.chain_quality_score

    def test_deterministic(self):
        now = datetime(2026, 4, 1, 14, tzinfo=timezone.utc)
        q1 = assess_options_quality(_make_row(), now)
        q2 = assess_options_quality(_make_row(), now)
        assert q1.chain_quality_score == q2.chain_quality_score


class TestToDict:
    def test_dict_has_required_keys(self):
        q = assess_options_quality(_make_row(), datetime(2026, 4, 1, 14, tzinfo=timezone.utc))
        d = q.to_dict()
        assert "options_data_state" in d
        assert "options_missing_reason" in d
        assert "options_chain_quality_score" in d
        assert "options_tier_mode" in d


class TestManifest:
    def test_empty(self):
        m = build_options_quality_manifest([])
        assert m["total_tickers"] == 0

    def test_with_rows(self):
        rows = [_make_row(ticker="A"), _make_row(ticker="B", opt_has_data="0")]
        m = build_options_quality_manifest(rows, datetime(2026, 4, 1, 14, tzinfo=timezone.utc))
        assert m["total_tickers"] == 2
        assert m["state_distribution"]["full"] == 1
        assert m["state_distribution"]["absent"] == 1
        assert m["coverage_pct"] == 50.0

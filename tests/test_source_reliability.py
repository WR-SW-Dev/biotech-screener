"""Tests for empirical catalyst-source reliability policy."""

import csv
from pathlib import Path

from common.source_reliability import (
    DEMOTE_LARGE_SLIP_RATE,
    DEMOTE_MEDIAN_ABS_SLIP,
    MIN_SAMPLE_COUNT,
    SUPPRESS_LARGE_SLIP_RATE,
    SUPPRESS_MEDIAN_ABS_SLIP,
    aggregate_reliability,
    apply_reliability_policy,
    compute_priority_penalty,
    compute_reliability_score,
    enrich_with_reliability_scores,
    get_source_action,
    load_reliability_table,
    render_reliability_md,
    write_reliability_json,
)
from tools.build_source_reliability import discover_slip_dates, load_historical_slips, run_build_reliability


def _slip_row(
    ticker="ACME",
    family="REGULATORY",
    slip_days=0,
    large_slip="0",
    imminent="0",
    new_flag="0",
    dropped_flag="0",
    source="COMPANY_GUIDANCE",
    confidence="HIGH",
):
    return {
        "ticker": ticker,
        "family": family,
        "prior_days": "90",
        "current_days": "83",
        "delta_days": "-7",
        "expected_days": "83",
        "slip_days": str(slip_days),
        "prior_event_type": "PDUFA",
        "current_event_type": "PDUFA",
        "prior_source": source,
        "current_source": source,
        "prior_confidence": confidence,
        "current_confidence": confidence,
        "prior_mode": "specific_days",
        "current_mode": "specific_days",
        "prior_snapshot_date": "2026-03-01",
        "current_snapshot_date": "2026-03-08",
        "new_flag": new_flag,
        "dropped_flag": dropped_flag,
        "large_slip": large_slip,
        "imminent": imminent,
    }


# ---------------------------------------------------------------------------
# 1. Aggregation
# ---------------------------------------------------------------------------


class TestAggregateReliability:
    def test_groups_by_source_confidence_family(self):
        rows = [
            _slip_row(source="A", confidence="HIGH", family="REGULATORY", slip_days=2),
            _slip_row(source="A", confidence="HIGH", family="REGULATORY", slip_days=5),
            _slip_row(source="B", confidence="MED", family="CLINICAL", slip_days=10),
        ]
        result = aggregate_reliability(rows)
        assert len(result) == 2
        # Sorted by (source, confidence, family)
        assert result[0]["source"] == "A"
        assert result[0]["sample_count"] == 2
        assert result[1]["source"] == "B"
        assert result[1]["sample_count"] == 1

    def test_deterministic_ordering(self):
        rows = [
            _slip_row(source="Z", confidence="HIGH", family="OTHER"),
            _slip_row(source="A", confidence="LOW", family="CLINICAL"),
            _slip_row(source="A", confidence="HIGH", family="REGULATORY"),
        ]
        result = aggregate_reliability(rows)
        keys = [(b["source"], b["confidence"], b["family"]) for b in result]
        assert keys == sorted(keys)

    def test_mean_and_median_abs_slip(self):
        rows = [
            _slip_row(slip_days=2),
            _slip_row(slip_days=-8),
            _slip_row(slip_days=20),
        ]
        result = aggregate_reliability(rows)
        assert len(result) == 1
        b = result[0]
        assert b["mean_abs_slip_days"] == 10.0  # (2+8+20)/3
        assert b["median_abs_slip_days"] == 8.0  # sorted: [2,8,20] → median=8

    def test_large_slip_rate(self):
        rows = [
            _slip_row(slip_days=2, large_slip="0"),
            _slip_row(slip_days=2, large_slip="0"),
            _slip_row(slip_days=20, large_slip="1"),
        ]
        result = aggregate_reliability(rows)
        b = result[0]
        assert abs(b["large_slip_rate"] - 1 / 3) < 0.01

    def test_empty_input(self):
        assert aggregate_reliability([]) == []

    def test_dropped_and_new_rates(self):
        rows = [
            _slip_row(new_flag="1"),
            _slip_row(dropped_flag="1"),
            _slip_row(),
            _slip_row(),
        ]
        result = aggregate_reliability(rows)
        b = result[0]
        assert b["new_rate"] == 0.25
        assert b["dropped_rate"] == 0.25


# ---------------------------------------------------------------------------
# 2. Policy mapper
# ---------------------------------------------------------------------------


class TestApplyReliabilityPolicy:
    def test_low_sample_is_unknown(self):
        buckets = [
            {
                "source": "X",
                "confidence": "HIGH",
                "family": "REGULATORY",
                "sample_count": MIN_SAMPLE_COUNT - 1,
                "mean_abs_slip_days": 50.0,
                "median_abs_slip_days": 50.0,
                "large_slip_rate": 1.0,
                "imminent_large_slip_rate": 0,
                "dropped_rate": 0,
                "new_rate": 0,
            }
        ]
        apply_reliability_policy(buckets)
        assert buckets[0]["action"] == "UNKNOWN"

    def test_high_large_slip_rate_suppress(self):
        buckets = [
            {
                "source": "NOISY",
                "confidence": "LOW",
                "family": "REGULATORY",
                "sample_count": 10,
                "mean_abs_slip_days": 15.0,
                "median_abs_slip_days": 10.0,
                "large_slip_rate": SUPPRESS_LARGE_SLIP_RATE,
                "imminent_large_slip_rate": 0,
                "dropped_rate": 0,
                "new_rate": 0,
            }
        ]
        apply_reliability_policy(buckets)
        assert buckets[0]["action"] == "SUPPRESS"

    def test_high_median_suppress(self):
        buckets = [
            {
                "source": "NOISY",
                "confidence": "LOW",
                "family": "REGULATORY",
                "sample_count": 10,
                "mean_abs_slip_days": 25.0,
                "median_abs_slip_days": SUPPRESS_MEDIAN_ABS_SLIP,
                "large_slip_rate": 0.1,
                "imminent_large_slip_rate": 0,
                "dropped_rate": 0,
                "new_rate": 0,
            }
        ]
        apply_reliability_policy(buckets)
        assert buckets[0]["action"] == "SUPPRESS"

    def test_moderate_large_slip_rate_demote(self):
        buckets = [
            {
                "source": "OK_ISH",
                "confidence": "MED",
                "family": "CLINICAL",
                "sample_count": 10,
                "mean_abs_slip_days": 10.0,
                "median_abs_slip_days": 8.0,
                "large_slip_rate": DEMOTE_LARGE_SLIP_RATE,
                "imminent_large_slip_rate": 0,
                "dropped_rate": 0,
                "new_rate": 0,
            }
        ]
        apply_reliability_policy(buckets)
        assert buckets[0]["action"] == "DEMOTE"

    def test_moderate_median_demote(self):
        buckets = [
            {
                "source": "OK_ISH",
                "confidence": "MED",
                "family": "CLINICAL",
                "sample_count": 10,
                "mean_abs_slip_days": 15.0,
                "median_abs_slip_days": DEMOTE_MEDIAN_ABS_SLIP,
                "large_slip_rate": 0.05,
                "imminent_large_slip_rate": 0,
                "dropped_rate": 0,
                "new_rate": 0,
            }
        ]
        apply_reliability_policy(buckets)
        assert buckets[0]["action"] == "DEMOTE"

    def test_clean_source_allow(self):
        buckets = [
            {
                "source": "CLEAN",
                "confidence": "HIGH",
                "family": "REGULATORY",
                "sample_count": 20,
                "mean_abs_slip_days": 3.0,
                "median_abs_slip_days": 2.0,
                "large_slip_rate": 0.05,
                "imminent_large_slip_rate": 0,
                "dropped_rate": 0,
                "new_rate": 0,
            }
        ]
        apply_reliability_policy(buckets)
        assert buckets[0]["action"] == "ALLOW"

    def test_suppress_takes_priority_over_demote(self):
        """When both SUPPRESS and DEMOTE thresholds are met, SUPPRESS wins."""
        buckets = [
            {
                "source": "BAD",
                "confidence": "LOW",
                "family": "REGULATORY",
                "sample_count": 10,
                "mean_abs_slip_days": 30.0,
                "median_abs_slip_days": 25.0,
                "large_slip_rate": 0.50,
                "imminent_large_slip_rate": 0,
                "dropped_rate": 0,
                "new_rate": 0,
            }
        ]
        apply_reliability_policy(buckets)
        assert buckets[0]["action"] == "SUPPRESS"


# ---------------------------------------------------------------------------
# 3. Lookup (get_source_action)
# ---------------------------------------------------------------------------


class TestGetSourceAction:
    def _make_table(self):
        return [
            {"source": "A", "confidence": "HIGH", "family": "REGULATORY", "action": "ALLOW", "reason": "clean"},
            {"source": "A", "confidence": "LOW", "family": "REGULATORY", "action": "DEMOTE", "reason": "noisy"},
            {"source": "B", "confidence": "MED", "family": "CLINICAL", "action": "SUPPRESS", "reason": "bad"},
        ]

    def test_exact_match(self):
        table = self._make_table()
        action, reason = get_source_action(table, "A", "HIGH", "REGULATORY")
        assert action == "ALLOW"

    def test_source_confidence_fallback(self):
        """When family doesn't match, fall back to source+confidence worst."""
        table = self._make_table()
        action, _ = get_source_action(table, "A", "LOW", "CLINICAL")
        assert action == "DEMOTE"

    def test_source_only_fallback_worst(self):
        """When only source matches, take worst action across all buckets."""
        table = self._make_table()
        action, _ = get_source_action(table, "A", "UNKNOWN_CONF", "OTHER")
        # A has ALLOW and DEMOTE → worst is DEMOTE
        assert action == "DEMOTE"

    def test_no_match_is_unknown(self):
        table = self._make_table()
        action, reason = get_source_action(table, "NEVER_SEEN", "HIGH", "REGULATORY")
        assert action == "UNKNOWN"
        assert "no data" in reason

    def test_empty_table_is_unknown(self):
        action, _ = get_source_action([], "A", "HIGH", "REGULATORY")
        assert action == "UNKNOWN"

    def test_all_sources_unknown_preserves_behavior(self):
        """When all sources are UNKNOWN, no penalty is applied."""
        table = [
            {"source": "X", "confidence": "HIGH", "family": "REGULATORY", "action": "UNKNOWN", "reason": "n=2 < 5"},
        ]
        action, _ = get_source_action(table, "X", "HIGH", "REGULATORY")
        assert action == "UNKNOWN"


# ---------------------------------------------------------------------------
# 4. Priority penalty
# ---------------------------------------------------------------------------


class TestComputePriorityPenalty:
    def test_allow_no_penalty(self):
        assert compute_priority_penalty("ALLOW") == 0.0

    def test_unknown_no_penalty(self):
        assert compute_priority_penalty("UNKNOWN") == 0.0

    def test_demote_penalty(self):
        assert compute_priority_penalty("DEMOTE") == 2.0

    def test_suppress_penalty(self):
        assert compute_priority_penalty("SUPPRESS") == 5.0


# ---------------------------------------------------------------------------
# 5. Upstream integration (select_quality_entries)
# ---------------------------------------------------------------------------


class TestUpstreamIntegration:
    def test_reliability_penalizes_noisy_source(self):
        from common.regulatory_calendar import _compute_entry_priority

        rec_clean = {"ticker": "CLEAN", "pdufa_date": "2026-06-01", "source": "COMPANY_GUIDANCE", "confidence": "HIGH"}
        rec_noisy = {"ticker": "NOISY", "pdufa_date": "2026-06-01", "source": "ANALYST_ESTIMATE", "confidence": "LOW"}

        reliability = [
            {
                "source": "COMPANY_GUIDANCE",
                "confidence": "HIGH",
                "family": "REGULATORY",
                "action": "ALLOW",
                "reason": "clean",
            },
            {
                "source": "ANALYST_ESTIMATE",
                "confidence": "LOW",
                "family": "REGULATORY",
                "action": "DEMOTE",
                "reason": "noisy",
            },
        ]

        p_clean = _compute_entry_priority(rec_clean, "2026-03-10", reliability)
        p_noisy = _compute_entry_priority(rec_noisy, "2026-03-10", reliability)
        assert p_clean > p_noisy

    def test_suppress_drops_below_all_others(self):
        from common.regulatory_calendar import _compute_entry_priority

        rec = {"ticker": "X", "pdufa_date": "2026-06-01", "source": "BAD_SOURCE", "confidence": "HIGH"}

        reliability = [
            {
                "source": "BAD_SOURCE",
                "confidence": "HIGH",
                "family": "REGULATORY",
                "action": "SUPPRESS",
                "reason": "terrible",
            },
        ]

        p = _compute_entry_priority(rec, "2026-03-10", reliability)
        # Without reliability: HIGH(3) + default(1) + proximity(2) + tiebreak ~= 6.7
        # With SUPPRESS penalty (-5): ~1.7
        assert p < 3.0  # below even LOW + CTGOV baseline

    def test_no_reliability_table_unchanged(self):
        from common.regulatory_calendar import _compute_entry_priority

        rec = {"ticker": "X", "pdufa_date": "2026-06-01", "source": "COMPANY_GUIDANCE", "confidence": "HIGH"}

        p_without = _compute_entry_priority(rec, "2026-03-10", None)
        p_empty = _compute_entry_priority(rec, "2026-03-10", [])
        assert p_without == p_empty

    def test_select_quality_entries_with_reliability(self):
        from common.regulatory_calendar import select_quality_entries

        records = [
            {
                "ticker": "A",
                "pdufa_date": "2026-06-01",
                "source": "BAD",
                "confidence": "HIGH",
                "as_of_disclosed_at": "2026-01-01",
            },
            {
                "ticker": "B",
                "pdufa_date": "2026-06-01",
                "source": "GOOD",
                "confidence": "HIGH",
                "as_of_disclosed_at": "2026-01-01",
            },
        ]
        reliability = [
            {"source": "BAD", "confidence": "HIGH", "family": "REGULATORY", "action": "SUPPRESS", "reason": "bad"},
            {"source": "GOOD", "confidence": "HIGH", "family": "REGULATORY", "action": "ALLOW", "reason": "ok"},
        ]

        selected, diag = select_quality_entries(records, "2026-03-10", reliability_table=reliability)
        # Both should be selected (SUPPRESS doesn't remove, just deprioritizes)
        assert len(selected) == 2
        # GOOD source should rank first
        assert selected[0]["ticker"] == "B"
        assert selected[1]["ticker"] == "A"
        # Diagnostics should show reliability action
        assert "reliability_actions" in diag
        assert any(r["ticker"] == "A" and r["action"] == "SUPPRESS" for r in diag["reliability_actions"])

    def test_select_quality_entries_without_reliability(self):
        """Existing behavior unchanged when no reliability table provided."""
        from common.regulatory_calendar import select_quality_entries

        records = [
            {
                "ticker": "A",
                "pdufa_date": "2026-06-01",
                "source": "COMPANY_GUIDANCE",
                "confidence": "HIGH",
                "as_of_disclosed_at": "2026-01-01",
            },
        ]
        selected, diag = select_quality_entries(records, "2026-03-10")
        assert len(selected) == 1
        assert "reliability_actions" not in diag


# ---------------------------------------------------------------------------
# 6. I/O and CLI tool
# ---------------------------------------------------------------------------


class TestReliabilityIO:
    def test_write_and_load_roundtrip(self, tmp_path):
        buckets = [
            {
                "source": "A",
                "confidence": "HIGH",
                "family": "REGULATORY",
                "sample_count": 10,
                "mean_abs_slip_days": 3.0,
                "median_abs_slip_days": 2.0,
                "large_slip_rate": 0.05,
                "imminent_large_slip_rate": 0,
                "dropped_rate": 0,
                "new_rate": 0,
                "action": "ALLOW",
                "reason": "clean",
            }
        ]
        out_path = tmp_path / "rel.json"
        write_reliability_json(buckets, out_path, as_of_date="2026-03-10", n_weeks=10)
        loaded = load_reliability_table(out_path)
        assert len(loaded) == 1
        assert loaded[0]["source"] == "A"
        assert loaded[0]["action"] == "ALLOW"

    def test_load_missing_file(self, tmp_path):
        result = load_reliability_table(tmp_path / "missing.json")
        assert result == []

    def test_render_md_contains_actions(self):
        buckets = [
            {
                "source": "X",
                "confidence": "HIGH",
                "family": "REGULATORY",
                "sample_count": 10,
                "mean_abs_slip_days": 3.0,
                "median_abs_slip_days": 2.0,
                "large_slip_rate": 0.05,
                "action": "ALLOW",
                "reason": "clean",
            }
        ]
        md = render_reliability_md(buckets, as_of_date="2026-03-10", n_weeks=5)
        assert "ALLOW" in md
        assert "Source Reliability" in md


# ---------------------------------------------------------------------------
# 7. CLI tool integration
# ---------------------------------------------------------------------------


class TestBuildSourceReliability:
    def _write_slips_csv(self, slip_dir: Path, rows):
        slip_dir.mkdir(parents=True, exist_ok=True)
        csv_path = slip_dir / "slips.csv"
        from tools.track_calendar_slips import SLIPS_COLUMNS

        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=SLIPS_COLUMNS)
            w.writeheader()
            for row in rows:
                w.writerow({k: row.get(k, "") for k in SLIPS_COLUMNS})

    def test_discover_slip_dates(self, tmp_path):
        self._write_slips_csv(tmp_path / "2026-03-01", [_slip_row()])
        self._write_slips_csv(tmp_path / "2026-03-08", [_slip_row()])
        dates = discover_slip_dates(tmp_path)
        assert dates == ["2026-03-01", "2026-03-08"]

    def test_load_historical_slips_window(self, tmp_path):
        for i in range(5):
            d = f"2026-03-{i + 1:02d}"
            self._write_slips_csv(tmp_path / d, [_slip_row(ticker=f"T{i}")])

        rows, dates = load_historical_slips(tmp_path, "2026-03-05", n_weeks=3)
        assert len(dates) == 3
        assert dates == ["2026-03-03", "2026-03-04", "2026-03-05"]
        assert len(rows) == 3

    def test_run_build_full_pipeline(self, tmp_path):
        slips_root = tmp_path / "slips"
        out_root = tmp_path / "out"

        # Create enough rows to exceed MIN_SAMPLE_COUNT
        clean_rows = [_slip_row(source="COMPANY_GUIDANCE", slip_days=i) for i in range(6)]
        noisy_rows = [_slip_row(source="CTGOV", slip_days=20, large_slip="1") for _ in range(6)]

        self._write_slips_csv(slips_root / "2026-03-01", clean_rows + noisy_rows)

        result = run_build_reliability(
            "2026-03-10",
            slips_root=slips_root,
            out_root=out_root,
            n_weeks=4,
        )

        assert result["status"] == "OK"
        assert result["n_rows"] == 12
        assert result["n_buckets"] == 2

        # Verify files written
        assert Path(result["paths"]["json_path"]).is_file()
        assert Path(result["paths"]["md_path"]).is_file()

        # Verify policy applied correctly
        by_source = {b["source"]: b for b in result["buckets"]}
        assert by_source["COMPANY_GUIDANCE"]["action"] == "ALLOW"
        # CTGOV with all large slips → SUPPRESS
        assert by_source["CTGOV"]["action"] == "SUPPRESS"

    def test_no_slips_returns_skip(self, tmp_path):
        result = run_build_reliability(
            "2026-03-10",
            slips_root=tmp_path / "empty",
            out_root=tmp_path / "out",
        )
        assert result["status"] == "SKIP"


# ---------------------------------------------------------------------------
# Reliability score tests
# ---------------------------------------------------------------------------


class TestReliabilityScore:
    def test_perfect_source(self):
        bucket = {"sample_count": 20, "large_slip_rate": 0.0, "mean_abs_slip_days": 0.0}
        score = compute_reliability_score(bucket)
        assert score == 1.0

    def test_terrible_source(self):
        bucket = {"sample_count": 20, "large_slip_rate": 1.0, "mean_abs_slip_days": 90.0}
        score = compute_reliability_score(bucket)
        assert score == 0.0

    def test_zero_events(self):
        bucket = {"sample_count": 0, "large_slip_rate": 0.0, "mean_abs_slip_days": 0.0}
        assert compute_reliability_score(bucket) == 0.0

    def test_small_sample_penalty(self):
        full = {"sample_count": 20, "large_slip_rate": 0.1, "mean_abs_slip_days": 5.0}
        small = {"sample_count": 5, "large_slip_rate": 0.1, "mean_abs_slip_days": 5.0}
        assert compute_reliability_score(full) > compute_reliability_score(small)

    def test_score_between_zero_and_one(self):
        bucket = {"sample_count": 8, "large_slip_rate": 0.25, "mean_abs_slip_days": 10.0}
        score = compute_reliability_score(bucket)
        assert 0.0 <= score <= 1.0

    def test_enrich_adds_field(self):
        buckets = [
            {"sample_count": 10, "large_slip_rate": 0.1, "mean_abs_slip_days": 5.0},
            {"sample_count": 3, "large_slip_rate": 0.5, "mean_abs_slip_days": 30.0},
        ]
        result = enrich_with_reliability_scores(buckets)
        assert result is buckets  # mutates in-place
        assert all("reliability_score" in b for b in buckets)
        assert buckets[0]["reliability_score"] > buckets[1]["reliability_score"]

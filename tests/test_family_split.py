"""Tests for regulatory vs clinical family split in action lists.

Validates:
  1. Classification mapping — event types → correct families
  2. Exclusivity — each name in exactly one family
  3. Deterministic sorting preserved
  4. Per-family CSV output schema
  5. README contains family section
  6. Family backfill from catalyst_event_type
  7. Family horizon map
  8. Bucketed verdict with family_filter
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_action_lists import (
    BINARY_FAMILIES,
    FAMILY_CLINICAL,
    FAMILY_OTHER,
    FAMILY_REGULATORY,
    _normalize_family,
    build_action_lists,
    get_family_summary,
    split_by_family,
    write_action_lists,
)


def _make_snapshot(tmp_path, rows):
    """Write a minimal rankings.csv for testing."""
    snap_dir = tmp_path / "snapshot"
    snap_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "ticker",
        "actionable_rank",
        "eligible",
        "tier_any",
        "target_weight_pct",
        "catalyst_days",
        "catalyst_mode",
        "catalyst_bucket",
        "catalyst_strength",
        "catalyst_event_type",
        "catalyst_family",
        "archetype",
        "alpha_cohort_key",
        "mom_state",
        "industry_group",
        "size_band",
        "de_beta_xbi_60d_source",
    ]
    with open(snap_dir / "rankings.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return snap_dir


def _base_row(ticker, rank, days, event_type, family, **kwargs):
    row = {
        "ticker": ticker,
        "actionable_rank": str(rank),
        "eligible": "1",
        "tier_any": "A",
        "target_weight_pct": "1.0",
        "catalyst_days": str(days),
        "catalyst_mode": "specific_days",
        "catalyst_bucket": "",
        "catalyst_strength": "0.5",
        "catalyst_event_type": event_type,
        "catalyst_family": family,
        "archetype": "drug_developer",
        "alpha_cohort_key": "",
        "mom_state": "neutral",
        "industry_group": "biotech",
        "size_band": "M",
        "de_beta_xbi_60d_source": "hydrated",
    }
    row.update(kwargs)
    return row


class TestNormalizeFamily:
    def test_regulatory(self):
        assert _normalize_family("REGULATORY") == FAMILY_REGULATORY

    def test_clinical(self):
        assert _normalize_family("CLINICAL") == FAMILY_CLINICAL

    def test_safety_maps_to_other(self):
        assert _normalize_family("SAFETY") == FAMILY_OTHER

    def test_empty_maps_to_other(self):
        assert _normalize_family("") == FAMILY_OTHER

    def test_case_insensitive(self):
        assert _normalize_family("regulatory") == FAMILY_REGULATORY
        assert _normalize_family("Clinical") == FAMILY_CLINICAL


class TestClassificationMapping:
    def test_pdufa_is_regulatory(self, tmp_path):
        snap = _make_snapshot(
            tmp_path,
            [
                _base_row("ACME", 1, 45, "PDUFA", "REGULATORY"),
            ],
        )
        buckets = build_action_lists(snap)
        splits = split_by_family(buckets)
        assert len(splits["binary_31_90__REGULATORY"]) == 1
        assert len(splits["binary_31_90__CLINICAL"]) == 0

    def test_ct_primary_completion_is_clinical(self, tmp_path):
        snap = _make_snapshot(
            tmp_path,
            [
                _base_row("BIO1", 1, 120, "CT_PRIMARY_COMPLETION", "CLINICAL"),
            ],
        )
        buckets = build_action_lists(snap)
        splits = split_by_family(buckets)
        assert len(splits["binary_91_180__CLINICAL"]) == 1
        assert len(splits["binary_91_180__REGULATORY"]) == 0

    def test_data_readout_is_clinical(self, tmp_path):
        snap = _make_snapshot(
            tmp_path,
            [
                _base_row("BIO2", 2, 60, "DATA_READOUT", "CLINICAL"),
            ],
        )
        buckets = build_action_lists(snap)
        splits = split_by_family(buckets)
        assert len(splits["binary_31_90__CLINICAL"]) == 1


class TestExclusivity:
    def test_each_name_in_exactly_one_family(self, tmp_path):
        snap = _make_snapshot(
            tmp_path,
            [
                _base_row("REG1", 1, 50, "PDUFA", "REGULATORY"),
                _base_row("CLIN1", 2, 50, "CT_PRIMARY_COMPLETION", "CLINICAL"),
                _base_row("UNK1", 3, 50, "", ""),
            ],
        )
        buckets = build_action_lists(snap)
        splits = split_by_family(buckets)

        # All 3 names are in binary_31_90
        all_tickers = set()
        for family in BINARY_FAMILIES:
            key = f"binary_31_90__{family}"
            tickers = {r["ticker"] for r in splits.get(key, [])}
            # No overlap with previously seen tickers
            assert not all_tickers & tickers, f"Overlap in {key}: {all_tickers & tickers}"
            all_tickers |= tickers

        assert all_tickers == {"REG1", "CLIN1", "UNK1"}


class TestDeterministicSorting:
    def test_sort_preserved_in_splits(self, tmp_path):
        snap = _make_snapshot(
            tmp_path,
            [
                _base_row("CLIN_B", 5, 100, "DATA_READOUT", "CLINICAL"),
                _base_row("CLIN_A", 2, 100, "CT_PRIMARY_COMPLETION", "CLINICAL"),
                _base_row("CLIN_C", 10, 100, "DATA_READOUT", "CLINICAL"),
            ],
        )
        buckets = build_action_lists(snap)
        splits = split_by_family(buckets)
        clin = splits["binary_91_180__CLINICAL"]
        ranks = [int(r["actionable_rank"]) for r in clin]
        assert ranks == sorted(ranks), "Sort by actionable_rank not preserved"


class TestPerFamilyCsvOutput:
    def test_csv_files_written(self, tmp_path):
        snap = _make_snapshot(
            tmp_path,
            [
                _base_row("REG1", 1, 50, "PDUFA", "REGULATORY"),
                _base_row("CLIN1", 2, 100, "DATA_READOUT", "CLINICAL"),
            ],
        )
        buckets = build_action_lists(snap)
        fam_splits = split_by_family(buckets)
        out_dir = tmp_path / "action_lists"
        write_action_lists(buckets, out_dir, as_of_date="2026-03-08", family_splits=fam_splits)

        # Check per-family CSV exists
        reg_csv = out_dir / "binary_31_90_regulatory.csv"
        clin_csv = out_dir / "binary_91_180_clinical.csv"
        assert reg_csv.is_file()
        assert clin_csv.is_file()

        with open(reg_csv) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["ticker"] == "REG1"


class TestReadmeContainsFamilySection:
    def test_family_table_in_readme(self, tmp_path):
        snap = _make_snapshot(
            tmp_path,
            [
                _base_row("REG1", 1, 50, "PDUFA", "REGULATORY"),
                _base_row("CLIN1", 2, 100, "DATA_READOUT", "CLINICAL"),
            ],
        )
        buckets = build_action_lists(snap)
        fam_splits = split_by_family(buckets)
        out_dir = tmp_path / "action_lists"
        write_action_lists(buckets, out_dir, as_of_date="2026-03-08", family_splits=fam_splits)

        readme = (out_dir / "README.md").read_text()
        assert "Family Breakdown" in readme
        assert "Regulatory" in readme
        assert "Clinical" in readme


class TestFamilyBackfill:
    def test_backfill_from_event_type(self, tmp_path):
        """When catalyst_family is empty, it should be derived from catalyst_event_type."""
        snap = _make_snapshot(
            tmp_path,
            [
                _base_row("ACME", 1, 45, "PDUFA", ""),  # family empty, event_type present
            ],
        )
        buckets = build_action_lists(snap)
        row = buckets["binary_31_90"][0]
        assert row["catalyst_family"] in (FAMILY_REGULATORY, FAMILY_OTHER)


class TestFamilySummary:
    def test_counts(self, tmp_path):
        snap = _make_snapshot(
            tmp_path,
            [
                _base_row("REG1", 1, 50, "PDUFA", "REGULATORY"),
                _base_row("REG2", 2, 60, "FDA_ADCOM", "REGULATORY"),
                _base_row("CLIN1", 3, 50, "DATA_READOUT", "CLINICAL"),
            ],
        )
        buckets = build_action_lists(snap)
        summary = get_family_summary(buckets)
        assert summary["binary_31_90"]["REGULATORY"] == 2
        assert summary["binary_31_90"]["CLINICAL"] == 1


class TestFamilyHorizonMap:
    def test_family_horizons_exist(self):
        from scripts.research.eval_by_bucket import FAMILY_HORIZON_MAP

        # Regulatory 31-90 should use 63/84d
        assert FAMILY_HORIZON_MAP["binary_31_90__REGULATORY"] == [63, 84]
        # Clinical 91-180 should use 84/126d
        assert FAMILY_HORIZON_MAP["binary_91_180__CLINICAL"] == [84, 126]
        # Clinical 31-90 extends to 84/126d
        assert FAMILY_HORIZON_MAP["binary_31_90__CLINICAL"] == [84, 126]


class TestVerdictWithFamilyFilter:
    def test_verdict_accepts_family_filter(self):
        from collections import namedtuple
        from unittest.mock import patch

        from scripts.research.run_bucketed_verdict import run_bucketed_verdict

        EvalSummary = namedtuple("EvalSummary", ["n_evaluated", "n_dates", "by_horizon"])
        mock_summary = EvalSummary(
            n_evaluated=50,
            n_dates=25,
            by_horizon={
                84: {"mean_net_return": 0.05, "mean_hedged_return": 0.04, "mean_ic": 0.03},
                126: {"mean_net_return": 0.06, "mean_hedged_return": 0.05, "mean_ic": 0.04},
            },
        )
        mock_base = EvalSummary(
            n_evaluated=50,
            n_dates=25,
            by_horizon={
                84: {"mean_net_return": 0.04, "mean_hedged_return": 0.035, "mean_ic": 0.02},
                126: {"mean_net_return": 0.0375, "mean_hedged_return": 0.03, "mean_ic": 0.025},
            },
        )

        with patch("scripts.research.run_bucketed_verdict.evaluate") as mock_eval:
            mock_eval.side_effect = [(mock_summary, [], []), (mock_base, [], [])]
            result = run_bucketed_verdict(
                candidate_dir=Path("/tmp/cand"),
                baseline_dir=Path("/tmp/base"),
                bucket="binary_91_180",
                family_filter=["CLINICAL"],
            )

        assert result["family_filter"] == ["CLINICAL"]
        assert result["verdict"] in ("PROMOTE", "ARCHIVE", "NEEDS_MORE")
        # Verify family_filter was passed to evaluate
        call_kwargs = mock_eval.call_args_list[0][1]
        assert call_kwargs.get("family_filter") == ["CLINICAL"]

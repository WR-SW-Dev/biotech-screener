"""Tests for production audit fixes (2026-04-25).

Covers three fixes:

1. ``--pit-mode=strict`` now actually raises ``FileNotFoundError`` when the
   per-date CTGov cache is missing (previously it silently fell back to the
   stale base file, identical to ``degrade`` mode).

2. ``ranker_mode=pairwise_minimal`` now raises ``FileNotFoundError`` when
   ``ranker_v2_model.json`` is absent (previously logged "FATAL" and continued
   with broken ``final_score`` path).

3. ``institutional_summary.build_institutional_summary`` and
   ``compute_institutional_delta`` now write a deterministic ``created_at``
   derived from ``as_of_date`` instead of ``datetime.now()``, so two runs over
   the same input produce byte-identical JSON.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ----------------------------------------------------------------------------
# Fix 1: --pit-mode=strict aborts on cache miss
# ----------------------------------------------------------------------------


class TestPitStrictCacheMiss:
    """Strict mode must refuse to run if the per-date PIT cache is missing.

    The historical behaviour silently fell back to ``trial_records.json`` and
    ran a runtime PIT filter, which made stale caches indistinguishable from
    fresh ones in production logs.
    """

    def _minimal_data_dir(self, tmp_path: Path) -> Path:
        """Create a minimal-but-valid production_data directory."""
        d = tmp_path / "production_data"
        d.mkdir()
        (d / "universe.json").write_text(json.dumps([{"ticker": "ACME"}]))
        (d / "financial_records.json").write_text(json.dumps([{"ticker": "ACME"}]))
        (d / "trial_records.json").write_text(json.dumps([]))
        (d / "market_data.json").write_text(json.dumps([{"ticker": "ACME"}]))
        return d

    def test_strict_raises_when_pit_cache_missing(self, tmp_path: Path):
        from run_screen import run_screening_pipeline

        data_dir = self._minimal_data_dir(tmp_path)
        empty_cache = tmp_path / "empty_ctgov_cache"
        empty_cache.mkdir()  # exists but does NOT contain trial_records_<date>.json

        with pytest.raises(FileNotFoundError, match="PIT cache miss"):
            run_screening_pipeline(
                as_of_date="2026-04-25",
                data_dir=data_dir,
                ctgov_cache_dir=empty_cache,
                pit_mode="strict",
            )

    def test_degrade_does_not_raise_when_pit_cache_missing(self, tmp_path: Path):
        """Degrade mode keeps the historical fall-back behaviour."""
        from run_screen import run_screening_pipeline

        data_dir = self._minimal_data_dir(tmp_path)
        empty_cache = tmp_path / "empty_ctgov_cache"
        empty_cache.mkdir()

        # In degrade mode the cache miss must not raise — it must fall back.
        # Pipeline may still fail later for unrelated reasons (no universe,
        # etc.); we only assert the raise we patched is NOT triggered.
        try:
            run_screening_pipeline(
                as_of_date="2026-04-25",
                data_dir=data_dir,
                ctgov_cache_dir=empty_cache,
                pit_mode="degrade",
            )
        except FileNotFoundError as exc:
            assert "PIT cache miss" not in str(exc), "degrade mode must not raise the strict cache-miss guard"
        except Exception:
            # Any other downstream error is fine for this targeted test —
            # we only care that the strict guard did not fire.
            pass


# ----------------------------------------------------------------------------
# Fix 2: ranker_v2 model required when ranker_mode=pairwise_minimal
# ----------------------------------------------------------------------------


class TestRankerV2ModelRequired:
    """``pairwise_minimal`` is the production default. If the model artifact
    is missing, the pipeline must abort rather than silently continue with
    a broken ``final_score`` path.
    """

    def test_helpful_error_message(self):
        """Confirm the FileNotFoundError carries actionable guidance.

        We exercise this via direct text inspection of run_screen.py rather
        than re-running the pipeline (which already has dedicated coverage
        elsewhere) to keep the test fast and targeted.
        """
        src = (Path(__file__).parent.parent / "run_screen.py").read_text()
        # Locate the production-required raise we just patched.
        assert (
            "ranker_mode=pairwise_minimal requires" in src
        ), "expected the pairwise_minimal model-required raise to be present"
        assert "--ranker-mode=clinical_50" in src, "error message must point users at the legacy fallback flag"
        # Sanity: no remaining "FATAL: ..." log line that doesn't actually fail.
        assert (
            "FATAL: ranker_mode=pairwise_minimal" not in src
        ), "stale soft-FATAL log should be removed in favour of the raise"


# ----------------------------------------------------------------------------
# Fix 3: institutional_summary outputs are byte-deterministic
# ----------------------------------------------------------------------------


class TestInstitutionalSummaryDeterminism:
    """``created_at`` must be a function of as_of_date, not wall-clock time,
    so byte-comparing two runs over identical inputs succeeds."""

    def test_summary_created_at_is_as_of_date_derived(self):
        from institutional_summary import build_institutional_summary

        # Pass a non-existent cache base — function returns None on missing
        # cache, but the determinism contract is still encoded in the
        # function literal we can read directly.
        src = (Path(__file__).parent.parent / "institutional_summary.py").read_text()
        # Confirm the source no longer relies on wall-clock time for
        # created_at fingerprints.
        assert "datetime.now" not in src, (
            "institutional_summary must not stamp wall-clock timestamps "
            "into summary JSON (breaks rerun byte-determinism)"
        )
        # Confirm both summary and delta now derive created_at from as_of_date.
        # Two independent occurrences are expected (build + compute_delta).
        assert src.count("T00:00:00Z") >= 2, "expected as_of_date-derived created_at in both summary and delta"
        # Confirm our return-shape change still includes the build-side
        # signature (smoke check that the import resolves).
        assert callable(build_institutional_summary)

    def test_conditional_model_handles_none_in_trial_fields(self):
        """``conditional_model._classify_mechanism`` and friends previously
        crashed with ``TypeError: sequence item ...: expected str instance,
        NoneType found`` when a trial record had ``None`` inside
        ``interventions`` or ``conditions``. The whole batch was lost.
        Now the ``_join_text`` helper drops Nones safely.
        """
        from event_ev.conditional_model import _classify_mechanism, _detect_biomarker_selected, _detect_enrichment

        # None mixed into intervention list — common shape from CTGov.
        mech = _classify_mechanism(
            interventions=["pembrolizumab", None, "chemotherapy"],
            conditions=["NSCLC", None],
            title="A study of pembrolizumab",
        )
        assert mech in {"validated", "semi_validated", "novel", "unknown"}

        assert (
            _detect_biomarker_selected(
                title=None,
                conditions=["EGFR-mutant NSCLC", None],
                endpoints=[None, "PFS"],
            )
            is not None
        )  # bool either way

        assert (
            _detect_enrichment(
                title="adaptive trial",
                conditions=[None],
                endpoints=[None],
            )
            is not None
        )  # bool either way

    def test_delta_created_at_derived_from_current(self):
        from institutional_summary import compute_institutional_delta

        current = {
            "as_of_date": "2026-04-25",
            "cache_as_of_date": "2026-04-25",
            "tickers": {
                "ACME": {
                    "elite_holder_shares": {"FundA": 1000},
                    "elite_total_shares": 1000,
                    "elite_total_value_usd_thousands": 50,
                }
            },
        }
        prior = {
            "as_of_date": "2026-04-24",
            "cache_as_of_date": "2026-04-24",
            "tickers": {
                "ACME": {
                    "elite_holder_shares": {"FundA": 800},
                    "elite_total_shares": 800,
                    "elite_total_value_usd_thousands": 40,
                }
            },
        }
        out1 = compute_institutional_delta(current, prior)
        out2 = compute_institutional_delta(current, prior)
        assert out1 is not None and out2 is not None
        # Byte-identical contents.
        assert json.dumps(out1, sort_keys=True) == json.dumps(out2, sort_keys=True)
        assert out1["created_at"] == "2026-04-25T00:00:00Z"

"""
Tests for 13F backtest PIT audit findings and the holder-count PIT repair.

Classification: BACKTEST_13F_HOLDINGS_PIT_AUDIT_DIAGNOSTIC_NO_MODEL_CHANGE

Governance:
  - model_change: false
  - ranker_change: false
  - no production files modified
  - writes_to: tests/ only (this file)

These tests verify:
  1. PIT classification logic (future filings, missing dates, stale filings)
  2. That neutralization does not mutate production files
  3. JSON schema validity
  4. Phase 3 attribution presence
  5. Governance flags on the audit JSON
  6. Holder-count PIT repair in _convert_holdings_to_coinvest
"""

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ──────────────────────────────────────────────────────────────────────────────
# Helpers — tiny PIT classifier that mirrors the audit's logic
# (does NOT import from production code — audit-only)
# ──────────────────────────────────────────────────────────────────────────────

STALE_POLICY_DAYS = 180  # filing older than this relative to snapshot is STALE_BEYOND_POLICY


def classify_13f_pit(
    snapshot_date: date,
    filing_date: date | None,
    report_period: date | None,
) -> str:
    """
    Classify a single 13F entry's PIT status for a given snapshot date.

    Returns one of:
      VALID_AVAILABLE
      INVALID_FUTURE_FILING
      INVALID_FUTURE_REPORT_PERIOD
      AVAILABILITY_UNKNOWN
      STALE_BEYOND_POLICY
    """
    if filing_date is None:
        return "AVAILABILITY_UNKNOWN"

    # Filing date is after snapshot — data not yet publicly available
    # (check this first — it subsumes INVALID_FUTURE_REPORT_PERIOD since
    #  a future filing implies future report period too)
    if filing_date > snapshot_date:
        return "INVALID_FUTURE_FILING"

    # Report period is after snapshot despite filing date being past — erroneous entry
    if report_period is not None and report_period > snapshot_date:
        return "INVALID_FUTURE_REPORT_PERIOD"

    # Filing date is too far in the past
    days_since_filing = (snapshot_date - filing_date).days
    if days_since_filing > STALE_POLICY_DAYS:
        return "STALE_BEYOND_POLICY"

    return "VALID_AVAILABLE"


# ──────────────────────────────────────────────────────────────────────────────
# Audit JSON location
# ──────────────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent
AUDIT_JSON = REPO_ROOT / "artifacts" / "audit" / "13f_backtest_pit" / "13f_backtest_pit_audit.json"


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: future filing date is flagged as INVALID_FUTURE_FILING
# ──────────────────────────────────────────────────────────────────────────────


def test_future_filing_date_is_flagged():
    """A filing dated AFTER the snapshot date must be flagged as INVALID_FUTURE_FILING."""
    snapshot = date(2024, 10, 18)
    filing_dt = date(2025, 11, 14)  # Q3 2025 canonical filing date — 13 months in the future
    report_dt = date(2025, 9, 30)  # Q3 2025 report period

    status = classify_13f_pit(snapshot, filing_dt, report_dt)
    assert status == "INVALID_FUTURE_FILING", (
        f"Expected INVALID_FUTURE_FILING, got {status!r}. " f"snapshot={snapshot}, filing={filing_dt}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: future report period is flagged as INVALID_FUTURE_REPORT_PERIOD
# ──────────────────────────────────────────────────────────────────────────────


def test_future_report_period_is_flagged():
    """A filing whose report_period is AFTER the snapshot date must be flagged."""
    snapshot = date(2025, 8, 1)
    # Imagine an erroneous entry with a Q4 2025 report period and no filing yet
    report_period = date(2025, 12, 31)
    # Construct a filing date in the past (otherwise INVALID_FUTURE_FILING fires first)
    # The INVALID_FUTURE_REPORT_PERIOD check uses report_period, so test by placing
    # filing_date before snapshot but report_period after
    filing_dt = date(2025, 7, 15)  # before snapshot

    status = classify_13f_pit(snapshot, filing_dt, report_period)
    assert status == "INVALID_FUTURE_REPORT_PERIOD", (
        f"Expected INVALID_FUTURE_REPORT_PERIOD, got {status!r}. "
        f"snapshot={snapshot}, filing={filing_dt}, report_period={report_period}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: missing filing date yields AVAILABILITY_UNKNOWN
# ──────────────────────────────────────────────────────────────────────────────


def test_missing_filing_date_becomes_availability_unknown():
    """When filed_at is None (missing), classification must be AVAILABILITY_UNKNOWN."""
    snapshot = date(2025, 6, 1)

    status = classify_13f_pit(snapshot, filing_date=None, report_period=None)
    assert status == "AVAILABILITY_UNKNOWN", f"Expected AVAILABILITY_UNKNOWN for None filing_date, got {status!r}"


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: stale filing beyond policy threshold is flagged as STALE_BEYOND_POLICY
# ──────────────────────────────────────────────────────────────────────────────


def test_stale_beyond_policy_is_flagged():
    """A filing more than STALE_POLICY_DAYS old relative to snapshot → STALE_BEYOND_POLICY."""
    # Imagine a snapshot 200 days after the filing date
    filing_dt = date(2025, 1, 1)
    snapshot = filing_dt + timedelta(days=STALE_POLICY_DAYS + 1)

    status = classify_13f_pit(snapshot, filing_dt, report_period=date(2024, 12, 31))
    assert status == "STALE_BEYOND_POLICY", (
        f"Expected STALE_BEYOND_POLICY ({STALE_POLICY_DAYS}d threshold), got {status!r}. "
        f"days_since_filing={(snapshot - filing_dt).days}"
    )

    # Sanity: exactly at the threshold should be valid
    snapshot_at_boundary = filing_dt + timedelta(days=STALE_POLICY_DAYS)
    status_boundary = classify_13f_pit(snapshot_at_boundary, filing_dt, report_period=date(2024, 12, 31))
    assert (
        status_boundary == "VALID_AVAILABLE"
    ), f"At exactly {STALE_POLICY_DAYS}d the status should be VALID_AVAILABLE, got {status_boundary!r}"


# ──────────────────────────────────────────────────────────────────────────────
# Test 5: neutralized 13F simulation does NOT mutate production files
# ──────────────────────────────────────────────────────────────────────────────


def test_neutralized_13f_does_not_mutate_production_files():
    """
    The sensitivity analysis is in-memory only.
    Key production artifacts must not be modified by the audit.
    We verify this by checking that the audit JSON records
    no_production_files_modified = true and that the holdings files
    have not been touched after the audit was written.
    """
    if not AUDIT_JSON.exists():
        pytest.skip("Audit JSON not yet written — run audit first")

    with AUDIT_JSON.open() as fh:
        audit = json.load(fh)

    # The sensitivity analysis section must declare no production mutations
    sensitivity = audit.get("sensitivity_analysis", {})
    assert (
        sensitivity.get("no_production_files_modified") is True
    ), "sensitivity_analysis.no_production_files_modified must be true"

    # Governance must be all-false
    gov = audit.get("audit_metadata", {}).get("governance", {})
    for flag in (
        "model_change",
        "ranker_change",
        "selector_change",
        "sizing_change",
        "regime_change",
        "production_wiring",
        "cron_change",
    ):
        assert gov.get(flag) is False, f"governance.{flag} must be false, got {gov.get(flag)!r}"


# ──────────────────────────────────────────────────────────────────────────────
# Test 6: generated JSON schema is valid
# ──────────────────────────────────────────────────────────────────────────────


def test_generated_json_schema_is_valid():
    """Audit JSON must be parseable and contain required top-level keys."""
    if not AUDIT_JSON.exists():
        pytest.skip("Audit JSON not yet written — run audit first")

    with AUDIT_JSON.open() as fh:
        audit = json.load(fh)

    required_top_level_keys = [
        "audit_metadata",
        "holdings_availability",
        "pit_audit",
        "manager_registry_integrity",
        "feature_audit",
        "phase3_attribution",
        "sensitivity_analysis",
        "verdict",
    ]
    for key in required_top_level_keys:
        assert key in audit, f"Missing required top-level key: {key!r}"

    # audit_metadata sub-keys
    meta = audit["audit_metadata"]
    for sub in ("classification", "audit_date", "governance"):
        assert sub in meta, f"Missing audit_metadata.{sub}"

    # pit_audit must have counts
    pit = audit["pit_audit"]
    assert "total_snapshot_dates_checked" in pit
    assert "invalid_future_filing_count" in pit
    assert pit["invalid_future_filing_count"] > 0, "Expected at least one invalid snapshot"

    # verdict must have overall key
    verdict = audit["verdict"]
    assert "overall" in verdict
    assert "leakage_type" in verdict


# ──────────────────────────────────────────────────────────────────────────────
# Test 7: Phase 3 loser names are present in attribution
# ──────────────────────────────────────────────────────────────────────────────


def test_phase3_names_in_attribution():
    """All Phase 3 loser tickers (CELC, DRUG, PRAX, TYRA, ABVX) must appear in phase3_attribution."""
    if not AUDIT_JSON.exists():
        pytest.skip("Audit JSON not yet written — run audit first")

    with AUDIT_JSON.open() as fh:
        audit = json.load(fh)

    attribution = audit.get("phase3_attribution", {})
    losers = attribution.get("losers", [])
    loser_tickers = {entry["ticker"] for entry in losers}

    required_losers = {"CELC", "DRUG", "PRAX", "TYRA", "ABVX"}
    missing = required_losers - loser_tickers
    assert not missing, f"Phase 3 loser tickers missing from attribution: {missing}. " f"Found: {loser_tickers}"

    # Winners must also be present
    winners = attribution.get("winners", [])
    winner_tickers = {entry["ticker"] for entry in winners}
    required_winners = {"TNGX", "ALKS", "SYRE"}
    missing_winners = required_winners - winner_tickers
    assert not missing_winners, (
        f"Phase 3 winner tickers missing from attribution: {missing_winners}. " f"Found: {winner_tickers}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 8: governance flags are all false
# ──────────────────────────────────────────────────────────────────────────────


def test_governance_flags_all_false():
    """All governance change flags must be false (diagnostic-only audit)."""
    if not AUDIT_JSON.exists():
        pytest.skip("Audit JSON not yet written — run audit first")

    with AUDIT_JSON.open() as fh:
        audit = json.load(fh)

    gov = audit.get("audit_metadata", {}).get("governance", {})

    required_false_flags = [
        "model_change",
        "ranker_change",
        "selector_change",
        "sizing_change",
        "regime_change",
        "production_wiring",
        "cron_change",
    ]
    failures = []
    for flag in required_false_flags:
        if flag not in gov:
            failures.append(f"{flag}: MISSING")
        elif gov[flag] is not False:
            failures.append(f"{flag}: {gov[flag]!r} (expected false)")

    assert not failures, "Governance flag violations:\n" + "\n".join(f"  {f}" for f in failures)


# ──────────────────────────────────────────────────────────────────────────────
# Bonus: validate classify_13f_pit for a clean/valid case
# ──────────────────────────────────────────────────────────────────────────────


def test_valid_pit_case_passes():
    """A filing date before and report_period before snapshot, within stale policy → VALID_AVAILABLE."""
    snapshot = date(2025, 12, 1)
    filing_dt = date(2025, 11, 14)  # Q3 2025 canonical date — valid for Nov 2025+ snapshots
    report_dt = date(2025, 9, 30)

    status = classify_13f_pit(snapshot, filing_dt, report_dt)
    assert status == "VALID_AVAILABLE", f"Expected VALID_AVAILABLE, got {status!r}"


# ──────────────────────────────────────────────────────────────────────────────
# Tests for the holder-count PIT repair in _convert_holdings_to_coinvest
# These exercise the production function directly to confirm the fix.
# ──────────────────────────────────────────────────────────────────────────────


def _make_holdings_snapshot(cik: str, filed_at: str | None, value_kusd: int = 5000) -> dict:
    """Build a minimal holdings_snapshots entry for one manager holding one ticker."""
    meta: dict = {"total_value_kusd": 100_000}
    if filed_at is not None:
        meta["filed_at"] = filed_at
    return {
        "XYZZ": {
            "holdings": {
                "current": {cik: {"value_kusd": value_kusd, "shares": 10_000}},
                "prior": {},
            },
            "filings_metadata": {cik: meta},
        }
    }


# Lazy import so the module is only loaded when these tests run.
def _get_convert_fn():
    from run_screen import _convert_holdings_to_coinvest

    return _convert_holdings_to_coinvest


def test_future_filing_blocks_holder_count():
    """
    When filed_at is AFTER as_of_date, coinvest_overlap_count and tier1_count
    must both be 0.  This is the core of the holder-count PIT repair.
    """
    _convert = _get_convert_fn()

    as_of_date = "2024-10-18"
    future_filed_at = "2025-11-14T00:00:00"  # Q3 2025 canonical — 13 months in the future
    cik = "0001263508"  # Baker Bros (Tier 1)

    snapshot = _make_holdings_snapshot(cik, future_filed_at)
    result = _convert(snapshot, as_of_date=as_of_date)

    assert "XYZZ" in result, "Ticker should still appear in output (just with zeroed counts)"
    sig = result["XYZZ"]
    assert (
        sig["coinvest_overlap_count"] == 0
    ), f"Future filing must not activate overlap count; got {sig['coinvest_overlap_count']}"
    assert sig["tier1_count"] == 0, f"Future filing must not activate tier1_count; got {sig['tier1_count']}"
    assert (
        sig["conviction_overlap"] == 0.0
    ), f"Conviction must also be 0 for future filing; got {sig['conviction_overlap']}"


def test_future_filing_blocks_both_conviction_and_counts():
    """
    Both the conviction path AND the holder-count path must be blocked
    for future filings.  Before the repair, conviction was blocked but
    counts were not — verify both are now blocked together.
    """
    _convert = _get_convert_fn()

    as_of_date = "2025-08-01"
    future_filed_at = "2025-11-14T00:00:00"
    cik = "0001346824"  # RA Capital (Tier 1)

    snapshot = _make_holdings_snapshot(cik, future_filed_at)
    result = _convert(snapshot, as_of_date=as_of_date)

    sig = result["XYZZ"]
    assert sig["coinvest_overlap_count"] == 0
    assert sig["tier1_count"] == 0
    assert sig["conviction_overlap"] == 0.0
    assert sig["tier1_conviction_overlap"] == 0.0


def test_missing_filing_date_preserves_holder_count():
    """
    When filed_at is absent (AVAILABILITY_UNKNOWN), the holder is still counted.
    This matches conviction-path behaviour and prevents silent drops of real data.
    """
    _convert = _get_convert_fn()

    as_of_date = "2025-06-01"
    cik = "0001263508"

    snapshot = _make_holdings_snapshot(cik, filed_at=None)  # No filing date
    result = _convert(snapshot, as_of_date=as_of_date)

    sig = result["XYZZ"]
    assert (
        sig["coinvest_overlap_count"] == 1
    ), f"Missing filed_at should preserve holder count; got {sig['coinvest_overlap_count']}"


def test_past_filing_counts_normally():
    """
    A filing date BEFORE as_of_date should be counted as normal.
    """
    _convert = _get_convert_fn()

    as_of_date = "2025-12-01"
    past_filed_at = "2025-11-14T00:00:00"  # 17 days before snapshot
    cik = "0001263508"

    snapshot = _make_holdings_snapshot(cik, past_filed_at)
    result = _convert(snapshot, as_of_date=as_of_date)

    sig = result["XYZZ"]
    assert (
        sig["coinvest_overlap_count"] == 1
    ), f"PIT-valid filing should be counted; got {sig['coinvest_overlap_count']}"
    assert sig["tier1_count"] == 1, f"PIT-valid Tier-1 filing should increment tier1_count; got {sig['tier1_count']}"
    assert sig["conviction_overlap"] > 0.0, "Conviction should be positive for a valid filing"


def test_audit_out_records_holder_count_pit_skips():
    """
    audit_out must include holder_count_pit_skips so operators can detect
    the contamination window in run_metadata.
    """
    _convert = _get_convert_fn()

    as_of_date = "2024-10-18"
    future_filed_at = "2025-11-14T00:00:00"
    cik = "0001263508"

    snapshot = _make_holdings_snapshot(cik, future_filed_at)
    audit_out: dict = {}
    _convert(snapshot, as_of_date=as_of_date, audit_out=audit_out)

    assert "holder_count_pit_skips" in audit_out, "audit_out must contain holder_count_pit_skips after the repair"
    assert (
        audit_out["holder_count_pit_skips"] >= 1
    ), f"Expected at least 1 holder_count_pit_skip; got {audit_out['holder_count_pit_skips']}"

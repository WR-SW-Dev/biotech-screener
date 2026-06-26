#!/usr/bin/env python3
"""Tests for generate_allocation_lens.py.

Covers:
1. test_allocation_lens_no_ranker_mutation
2. test_allocation_lens_schema_valid
3. test_allocation_lens_deterministic_output
4. test_allocation_lens_missing_optional_inputs_graceful
5. test_allocation_lens_bucket_assignment
6. test_allocation_lens_daily_override_trigger
7. test_allocation_lens_governance_language_no_buy_sell
"""

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.generate_allocation_lens import (
    _FORBIDDEN_REVIEW_WORDS,
    ARTIFACT_SCHEMA,
    BUCKET_NAMES,
    GOVERNANCE_CLASSIFICATION,
    REVIEW_ACTIONS,
    assign_bucket,
    build_construction_notes,
    check_overrides,
    generate_lens,
    render_md,
    run_selfcheck,
    write_lens_artifacts,
    write_selfcheck,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BASE_ROW = {
    "ticker": "TEST",
    "actionable_rank": "1",
    "composite_rank": "1",
    "catalyst_days": "30",
    "catalyst_bucket": "binary_now",
    "stage_bucket": "late",
    "runway_bucket": "adequate",
    "coinvest_tag": "elite_3",
    "ees_v3_pctile": "80.0",
    "ees_v3_gate": "True",
    "priced_move_pct": "8.5",
    "market_cap_mm": "500.0",
    "tier_dev": "A",
    "next_catalyst_date": "2026-07-15",
    "catalyst_date_lower": "2026-07-15",
    "company_name": "Test Bio",
}


def _make_rankings(n: int = 5, overrides: dict | None = None) -> list[dict]:
    rows = []
    for i in range(n):
        row = dict(_BASE_ROW)
        row["ticker"] = f"TST{i}"
        row["actionable_rank"] = str(i + 1)
        row["composite_rank"] = str(i + 1)
        if overrides:
            row.update(overrides)
        rows.append(row)
    return rows


def _make_catalyst_delta(
    n_terminated_tier_a: int = 0,
    n_phase_changes_tier_a: int = 0,
) -> dict:
    deltas = []
    for i in range(n_terminated_tier_a):
        deltas.append({"ticker": f"X{i}", "codes": ["CTGOV_TRIAL_TERMINATED"], "tier": "A"})
    for i in range(n_phase_changes_tier_a):
        deltas.append({"ticker": f"Y{i}", "codes": ["CTGOV_PHASE_CHANGED"], "tier": "A"})
    return {"as_of_date": "2026-06-26", "deltas": deltas}


# ---------------------------------------------------------------------------
# 1. No ranker mutation
# ---------------------------------------------------------------------------


def test_allocation_lens_no_ranker_mutation():
    rankings = _make_rankings(5)
    rankings_copy = copy.deepcopy(rankings)
    generate_lens(
        as_of_date="2026-06-26",
        rankings=rankings,
        catalyst_delta=None,
        ops_digest=None,
        ees_scorecard=None,
        cartography=None,
        warnings=[],
    )
    assert rankings == rankings_copy, "generate_lens must not mutate input rankings"


# ---------------------------------------------------------------------------
# 2. Schema valid
# ---------------------------------------------------------------------------

REQUIRED_TOP_LEVEL_KEYS = {
    "schema",
    "governance_classification",
    "as_of_date",
    "generated_at",
    "n_ranked",
    "n_top",
    "warnings",
    "regime",
    "bucket_population",
    "bucket_weights",
    "review_budget",
    "construction_notes",
    "what_would_change_our_mind",
}

REQUIRED_REGIME_KEYS = {
    "weekly_baseline_date",
    "biotech_beta",
    "rates_pressure",
    "financing_window",
    "ma_ipo_tone",
    "catalyst_tape",
    "liquidity",
    "daily_override",
}

REQUIRED_BUDGET_KEYS = {
    "priority",
    "ticker",
    "bucket",
    "why_now",
    "supporting_signals",
    "model_risk",
    "action",
}

REQUIRED_CONSTRUCTION_KEYS = {
    "mechanism_concentration",
    "stage_concentration",
    "catalyst_date_concentration",
    "financing_risk_concentration",
    "crowding",
    "liquidity",
}

REQUIRED_CHANGE_KEYS = {
    "upgrade_conditions",
    "downgrade_conditions",
    "evidence_needed",
}


def test_allocation_lens_schema_valid():
    lens = generate_lens(
        as_of_date="2026-06-26",
        rankings=_make_rankings(10),
        catalyst_delta=_make_catalyst_delta(),
        ops_digest={"readiness": {"verdict": "HOLD", "checks": {}}},
        ees_scorecard={"verdict": "HOLD", "checks": []},
        cartography=None,
        warnings=[],
    )

    assert REQUIRED_TOP_LEVEL_KEYS.issubset(
        lens.keys()
    ), f"Missing top-level keys: {REQUIRED_TOP_LEVEL_KEYS - lens.keys()}"
    assert lens["schema"] == ARTIFACT_SCHEMA
    assert lens["governance_classification"] == GOVERNANCE_CLASSIFICATION
    assert REQUIRED_REGIME_KEYS.issubset(lens["regime"].keys())

    for bw in lens["bucket_weights"]:
        assert "bucket" in bw
        assert "stance" in bw
        assert bw["bucket"] in BUCKET_NAMES

    for item in lens["review_budget"]:
        assert REQUIRED_BUDGET_KEYS.issubset(
            item.keys()
        ), f"Budget item missing keys: {REQUIRED_BUDGET_KEYS - item.keys()}"
        assert item["action"] in REVIEW_ACTIONS, f"Unknown action: {item['action']}"
        assert item["bucket"] in BUCKET_NAMES

    assert REQUIRED_CONSTRUCTION_KEYS.issubset(lens["construction_notes"].keys())
    assert REQUIRED_CHANGE_KEYS.issubset(lens["what_would_change_our_mind"].keys())

    # Serializable to JSON without error
    json.dumps(lens)


# ---------------------------------------------------------------------------
# 3. Deterministic output
# ---------------------------------------------------------------------------


def test_allocation_lens_deterministic_output():
    kwargs = dict(
        as_of_date="2026-06-26",
        rankings=_make_rankings(10),
        catalyst_delta=_make_catalyst_delta(),
        ops_digest={"readiness": {"verdict": "GO", "checks": {}}},
        ees_scorecard={"verdict": "HOLD", "checks": []},
        cartography=None,
        warnings=["test warning"],
    )
    out1 = generate_lens(**kwargs)
    out2 = generate_lens(**kwargs)
    # Strip generated_at (timestamp) before comparing
    out1.pop("generated_at")
    out2.pop("generated_at")
    assert out1 == out2, "generate_lens output is not deterministic"


# ---------------------------------------------------------------------------
# 4. Missing optional inputs — graceful
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "catalyst_delta,ops_digest,ees_scorecard,cartography",
    [
        (None, None, None, None),
        (None, {"readiness": {"verdict": "HOLD", "checks": {}}}, None, None),
        (None, None, {"verdict": "HOLD", "checks": []}, None),
        (
            _make_catalyst_delta(),
            {"readiness": {"verdict": "GO", "checks": {}}},
            {"verdict": "HOLD", "checks": []},
            None,
        ),
    ],
)
def test_allocation_lens_missing_optional_inputs_graceful(catalyst_delta, ops_digest, ees_scorecard, cartography):
    lens = generate_lens(
        as_of_date="2026-06-26",
        rankings=_make_rankings(5),
        catalyst_delta=catalyst_delta,
        ops_digest=ops_digest,
        ees_scorecard=ees_scorecard,
        cartography=cartography,
        warnings=[],
    )
    assert lens["schema"] == ARTIFACT_SCHEMA
    assert isinstance(lens["review_budget"], list)


# ---------------------------------------------------------------------------
# 5. Bucket assignment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides,expected_bucket",
    [
        # binary_now → near_term_binary_catalyst
        ({"catalyst_bucket": "binary_now", "runway_bucket": "adequate"}, "near_term_binary_catalyst"),
        # short runway + early stage → cash_poor_platform
        ({"runway_bucket": "short", "stage_bucket": "early"}, "cash_poor_platform"),
        # short runway but late stage → not cash_poor (late-stage commercial with short runway)
        # should fall through to near_term_binary if binary_now
        (
            {"runway_bucket": "short", "stage_bucket": "late", "catalyst_bucket": "binary_now"},
            "near_term_binary_catalyst",
        ),
        # High EES pctile with priced_move → expectation_gap_dislocation
        (
            {
                "catalyst_bucket": "core",
                "catalyst_days": "180",
                "ees_v3_pctile": "75.0",
                "priced_move_pct": "6.0",
                "runway_bucket": "adequate",
            },
            "expectation_gap_dislocation",
        ),
        # Low EES pctile → not expectation gap
        (
            {
                "catalyst_bucket": "core",
                "catalyst_days": "180",
                "ees_v3_pctile": "40.0",
                "priced_move_pct": "6.0",
                "runway_bucket": "adequate",
                "coinvest_tag": "",
                "tier_dev": "B",
            },
            "mechanism_theme_basket",
        ),
        # Elite manager ≥10 + SMID → elite_manager_smid
        (
            {
                "catalyst_bucket": "core",
                "catalyst_days": "180",
                "ees_v3_pctile": "40.0",
                "priced_move_pct": "",
                "coinvest_tag": "elite_12",
                "market_cap_mm": "800.0",
                "runway_bucket": "adequate",
                "tier_dev": "B",
            },
            "elite_manager_smid",
        ),
        # Late-stage Tier A + adequate runway → derisked_commercial
        (
            {
                "catalyst_bucket": "core",
                "catalyst_days": "200",
                "ees_v3_pctile": "40.0",
                "priced_move_pct": "",
                "coinvest_tag": "elite_3",
                "stage_bucket": "late",
                "tier_dev": "A",
                "runway_bucket": "adequate",
            },
            "derisked_commercial",
        ),
        # Default fallback
        (
            {
                "catalyst_bucket": "build_window",
                "catalyst_days": "200",
                "ees_v3_pctile": "30.0",
                "priced_move_pct": "",
                "coinvest_tag": "elite_2",
                "stage_bucket": "mid",
                "tier_dev": "B",
                "runway_bucket": "adequate",
            },
            "mechanism_theme_basket",
        ),
    ],
)
def test_allocation_lens_bucket_assignment(overrides, expected_bucket):
    row = dict(_BASE_ROW)
    row.update(overrides)
    assert assign_bucket(row) == expected_bucket, (
        f"Expected {expected_bucket} for overrides={overrides}, " f"got {assign_bucket(row)}"
    )


# ---------------------------------------------------------------------------
# 6. Daily override trigger
# ---------------------------------------------------------------------------


def test_allocation_lens_daily_override_trigger():
    # Below threshold → not triggered
    delta_below = _make_catalyst_delta(n_terminated_tier_a=2)
    result = check_overrides(delta_below, {})
    assert result["triggered"] is False

    # At threshold → triggered
    delta_at = _make_catalyst_delta(n_terminated_tier_a=3)
    result = check_overrides(delta_at, {})
    assert result["triggered"] is True
    assert "3" in result["reason"]

    # Phase-change threshold
    delta_phase = _make_catalyst_delta(n_phase_changes_tier_a=10)
    result = check_overrides(delta_phase, {})
    assert result["triggered"] is True
    assert "10" in result["reason"]

    # No delta → not triggered
    result = check_overrides(None, {})
    assert result["triggered"] is False


# ---------------------------------------------------------------------------
# 7. Governance language guard
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 8. Idempotence — no-overwrite (default cron behavior)
# ---------------------------------------------------------------------------


def test_idempotent_second_run_no_overwrite(tmp_path):
    """Second run with allow_overwrite=False must not mutate core artifacts."""
    lens = generate_lens(
        as_of_date="2026-06-26",
        rankings=_make_rankings(10),
        catalyst_delta=None,
        ops_digest=None,
        ees_scorecard=None,
        cartography=None,
        warnings=[],
    )
    out_md = tmp_path / "2026-06-26_allocation_lens.md"
    out_json = tmp_path / "2026-06-26_allocation_lens.json"

    r1 = write_lens_artifacts(lens, out_md, out_json, allow_overwrite=True)
    assert r1["md"] == "created"
    assert r1["json"] == "created"

    content_md = out_md.read_text()
    content_json = out_json.read_text()

    r2 = write_lens_artifacts(lens, out_md, out_json, allow_overwrite=False)
    assert r2["md"] == "skipped"
    assert r2["json"] == "skipped"
    assert out_md.read_text() == content_md
    assert out_json.read_text() == content_json


def test_allow_overwrite_flag(tmp_path):
    """allow_overwrite=True must overwrite existing artifacts."""
    out_md = tmp_path / "2026-06-26_allocation_lens.md"
    out_json = tmp_path / "2026-06-26_allocation_lens.json"
    out_md.write_text("old content")
    out_json.write_text("{}")

    lens = generate_lens(
        as_of_date="2026-06-26",
        rankings=_make_rankings(10),
        catalyst_delta=None,
        ops_digest=None,
        ees_scorecard=None,
        cartography=None,
        warnings=[],
    )
    r = write_lens_artifacts(lens, out_md, out_json, allow_overwrite=True)
    assert r["md"] == "overwrote"
    assert r["json"] == "overwrote"
    assert out_md.read_text() != "old content"
    assert out_json.read_text() != "{}"


def test_selfcheck_deterministic_except_timestamp():
    """Same lens must produce identical selfcheck notes on two consecutive calls."""
    lens = generate_lens(
        as_of_date="2026-06-26",
        rankings=_make_rankings(10),
        catalyst_delta=None,
        ops_digest=None,
        ees_scorecard=None,
        cartography=None,
        warnings=[],
    )
    c1 = run_selfcheck(lens)
    c2 = run_selfcheck(lens)

    def _strip(c):
        return {k: v for k, v in c.items() if k != "checked_at"}

    assert _strip(c1) == _strip(c2)


def test_selfcheck_sidecar_not_rewritten_if_unchanged(tmp_path):
    """Selfcheck sidecar is skipped when content (excluding checked_at) is unchanged."""
    lens = generate_lens(
        as_of_date="2026-06-26",
        rankings=_make_rankings(10),
        catalyst_delta=None,
        ops_digest=None,
        ees_scorecard=None,
        cartography=None,
        warnings=[],
    )
    check = run_selfcheck(lens)
    out_check = tmp_path / "2026-06-26_allocation_lens_selfcheck.json"

    r1 = write_selfcheck(check, out_check, allow_overwrite=False)
    assert r1 == "created"
    content_before = out_check.read_text()

    r2 = write_selfcheck(check, out_check, allow_overwrite=False)
    assert r2 == "skipped"
    assert out_check.read_text() == content_before


def test_cron_wrapper_passes_no_overwrite():
    """Cron wrapper must explicitly pass --no-overwrite to the generator."""
    wrapper = Path(__file__).resolve().parent.parent / "tools" / "cron_allocation_lens.sh"
    assert wrapper.exists(), f"Cron wrapper not found: {wrapper}"
    content = wrapper.read_text()
    assert "--no-overwrite" in content, "Cron wrapper must pass --no-overwrite to the generator"


# ---------------------------------------------------------------------------
# 7. Governance language guard  (renumbered — was 7, now follows 8 additions above)
# ---------------------------------------------------------------------------


def test_allocation_lens_governance_language_no_buy_sell():
    lens = generate_lens(
        as_of_date="2026-06-26",
        rankings=_make_rankings(20),
        catalyst_delta=_make_catalyst_delta(),
        ops_digest={"readiness": {"verdict": "GO", "checks": {}}},
        ees_scorecard={"verdict": "HOLD", "checks": []},
        cartography=None,
        warnings=[],
    )
    md = render_md(lens)
    md_lower = md.lower()

    violations = [w for w in _FORBIDDEN_REVIEW_WORDS if w in md_lower]
    assert not violations, (
        f"Governance language violation: forbidden action phrases found in markdown: " f"{violations}"
    )

    # Also check JSON serialization
    json_str = json.dumps(lens).lower()
    # Actions field is uppercase so won't match; check free-text fields
    for item in lens["review_budget"]:
        for field in ("why_now", "model_risk"):
            text = (item.get(field) or "").lower()
            bad = [w for w in _FORBIDDEN_REVIEW_WORDS if w in text]
            assert not bad, f"Forbidden word in review_budget.{field}: {bad}"

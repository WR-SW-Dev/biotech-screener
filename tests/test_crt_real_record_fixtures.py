"""Tests using real CRT resolution records as fixtures.

These validate downstream consumers against actual messy cases:
- AQST: MISS outcome but positive price direction (CRL + market liked resubmission)
- MAZE: MISS with negative price, mid-book rank 36 (taxonomy false positive)
- KOD: HIT with large positive price (+75%), clean case
- PVLA: HIT with flat price (same-day filing)
- ALDX: MISS with extreme negative price (-67%)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "crt_records"


def _load_fixture(name: str) -> dict:
    path = FIXTURE_DIR / f"{name}.json"
    with open(path) as f:
        return json.load(f)


class TestAQSTEdgeCase:
    """AQST: CRL (MISS) but price went UP. Tests outcome/price split."""

    def test_outcome_is_miss(self):
        r = _load_fixture("AQST_2026-03-04")
        assert r["outcome"] == "MISS"

    def test_price_direction_is_up(self):
        r = _load_fixture("AQST_2026-03-04")
        assert r["price_direction"] == "up"

    def test_outcome_and_price_disagree(self):
        r = _load_fixture("AQST_2026-03-04")
        assert r["outcome"] == "MISS" and r["price_direction"] == "up"

    def test_has_source(self):
        r = _load_fixture("AQST_2026-03-04")
        assert r["source_type"] == "MANUAL"


class TestMAZEFalsePositive:
    """MAZE: rank 36, MISS on SAE. Acceptable false positive."""

    def test_outcome_is_miss(self):
        r = _load_fixture("MAZE_2026-03-25")
        assert r["outcome"] == "MISS"

    def test_price_direction_is_down(self):
        r = _load_fixture("MAZE_2026-03-25")
        assert r["price_direction"] == "down"

    def test_has_prediction_context(self):
        r = _load_fixture("MAZE_2026-03-25")
        assert r.get("prediction_snapshot_date") is not None

    def test_price_decline_significant(self):
        r = _load_fixture("MAZE_2026-03-25")
        t1 = r["price_t_minus_1"]
        t0 = r["price_t_0"]
        ret = (t0 - t1) / t1
        assert ret < -0.20  # >20% decline


class TestKODCleanHit:
    """KOD: GLOW2 Phase 3 win, +75%. Clean HIT case."""

    def test_outcome_is_hit(self):
        r = _load_fixture("KOD_2026-03-26")
        assert r["outcome"] == "HIT"

    def test_price_direction_is_up(self):
        r = _load_fixture("KOD_2026-03-26")
        assert r["price_direction"] == "up"

    def test_large_positive_return(self):
        r = _load_fixture("KOD_2026-03-26")
        t1 = r["price_t_minus_1"]
        t0 = r["price_t_0"]
        ret = (t0 - t1) / t1
        assert ret > 0.50  # >50% move


class TestPVLAFlatPrice:
    """PVLA: Phase 3 SELVA HIT but flat price (same-day filing)."""

    def test_outcome_is_hit(self):
        r = _load_fixture("PVLA_2026-03-31")
        assert r["outcome"] == "HIT"

    def test_price_direction_is_flat(self):
        r = _load_fixture("PVLA_2026-03-31")
        assert r["price_direction"] == "flat"


class TestALDXExtremeMiss:
    """ALDX: FDA CRL path, -67%. Extreme negative."""

    def test_outcome_is_miss(self):
        r = _load_fixture("ALDX_2026-03-17")
        assert r["outcome"] == "MISS"

    def test_extreme_negative_return(self):
        r = _load_fixture("ALDX_2026-03-17")
        t1 = r["price_t_minus_1"]
        t0 = r["price_t_0"]
        ret = (t0 - t1) / t1
        assert ret < -0.50  # >50% decline


class TestAllFixturesValid:
    """All fixtures pass basic schema checks."""

    def test_all_have_required_fields(self):
        required = ["ticker", "catalyst_date", "outcome", "source_type", "as_of_date"]
        for f in FIXTURE_DIR.glob("*.json"):
            with open(f) as fh:
                r = json.load(fh)
            for field in required:
                assert field in r, f"{f.name} missing {field}"

    def test_all_have_price_direction(self):
        for f in FIXTURE_DIR.glob("*.json"):
            with open(f) as fh:
                r = json.load(fh)
            assert "price_direction" in r, f"{f.name} missing price_direction"

    def test_all_outcomes_valid(self):
        valid = {"HIT", "MISS", "MIXED", "DELAYED", "WITHDRAWN", "NEEDS_REVIEW", "INFORMATIONAL"}
        for f in FIXTURE_DIR.glob("*.json"):
            with open(f) as fh:
                r = json.load(fh)
            assert r["outcome"] in valid, f"{f.name} has invalid outcome: {r['outcome']}"

    def test_all_have_schema_version(self):
        for f in FIXTURE_DIR.glob("*.json"):
            with open(f) as fh:
                r = json.load(fh)
            assert r.get("schema_version") == "1.0.0", f"{f.name} missing or wrong schema_version"

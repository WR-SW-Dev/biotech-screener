"""Tests for the event-outcome binder."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.event_outcome_binder import (  # noqa: E402
    BINDER_VERSION,
    ResolutionRow,
    bind,
    find_match,
    load_resolution_index,
    reconstruct_expected_date,
    write_sidecar,
)


def write_resolution(dir_: Path, ticker: str, catalyst_date: str, **fields) -> Path:
    """Write one synthetic resolution record."""
    sub = dir_ / catalyst_date[:7]
    sub.mkdir(parents=True, exist_ok=True)
    payload = {
        "ticker": ticker,
        "catalyst_date": catalyst_date,
        "outcome": fields.pop("outcome", "HIT"),
        "resolution_date": fields.pop("resolution_date", catalyst_date),
        "outcome_detail": fields.pop("outcome_detail", ""),
        "catalyst_type": fields.pop("catalyst_type", "PDUFA"),
        **fields,
    }
    p = sub / f"{ticker}_{catalyst_date}.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def write_ledger(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def test_realized_return_computes_when_priced():
    r = ResolutionRow(
        ticker="ABCD",
        catalyst_date="2026-05-01",
        outcome="HIT",
        price_t_minus_1=10.0,
        price_t_plus_5=12.5,
    )
    assert r.realized_return == pytest.approx(0.25)


def test_realized_return_none_when_unpriced():
    r = ResolutionRow(ticker="ABCD", catalyst_date="2026-05-01", outcome="HIT")
    assert r.realized_return is None


def test_realized_return_none_on_zero_baseline():
    # Baseline price of 0 is data corruption; binder should not divide by zero.
    r = ResolutionRow(
        ticker="ABCD",
        catalyst_date="2026-05-01",
        outcome="HIT",
        price_t_minus_1=0.0,
        price_t_plus_5=5.0,
    )
    assert r.realized_return is None


def test_load_resolution_index_skips_aggregates(tmp_path):
    res_dir = tmp_path / "resolutions"
    res_dir.mkdir()
    # Aggregate files at the root must be ignored
    (res_dir / "calibration_summary.json").write_text(json.dumps({"summary": "ignored"}))
    (res_dir / "manual_overrides.json").write_text(json.dumps({"ticker": "X"}))
    write_resolution(res_dir, "ABCD", "2026-05-01", outcome="HIT")
    write_resolution(res_dir, "ABCD", "2026-06-01", outcome="MISS")
    write_resolution(res_dir, "EFGH", "2026-05-15", outcome="DELAYED")
    idx = load_resolution_index(res_dir)
    assert set(idx.keys()) == {"ABCD", "EFGH"}
    assert len(idx["ABCD"]) == 2
    assert idx["ABCD"][0].catalyst_date == "2026-05-01"  # sorted ascending


def test_load_resolution_index_skips_pending(tmp_path):
    res_dir = tmp_path / "resolutions"
    res_dir.mkdir()
    write_resolution(res_dir, "ABCD", "2026-05-01", outcome="PENDING")
    write_resolution(res_dir, "ABCD", "2026-06-01", outcome="HIT")
    idx = load_resolution_index(res_dir)
    assert len(idx["ABCD"]) == 1
    assert idx["ABCD"][0].outcome == "HIT"


def test_reconstruct_expected_date_prefers_explicit():
    cn = {"expected_date": "2026-06-15", "days_to_event": 30}
    assert reconstruct_expected_date(cn, "2026-05-01") == "2026-06-15"


def test_reconstruct_expected_date_uses_days_to_event():
    cn = {"days_to_event": 30}
    assert reconstruct_expected_date(cn, "2026-05-01") == "2026-05-31"


def test_reconstruct_expected_date_returns_none_when_no_anchor():
    assert reconstruct_expected_date({}, "2026-05-01") is None
    assert reconstruct_expected_date({"days_to_event": 5}, None) is None


def test_find_match_exact(tmp_path):
    res_dir = tmp_path / "resolutions"
    res_dir.mkdir()
    write_resolution(res_dir, "ABCD", "2026-05-01", outcome="HIT")
    idx = load_resolution_index(res_dir)
    match, kind, dist = find_match("ABCD", "2026-05-01", idx)
    assert kind == "exact"
    assert dist == 0
    assert match is not None
    assert match.outcome == "HIT"


def test_find_match_windowed_picks_closest(tmp_path):
    res_dir = tmp_path / "resolutions"
    res_dir.mkdir()
    write_resolution(res_dir, "ABCD", "2026-05-01", outcome="MISS")
    write_resolution(res_dir, "ABCD", "2026-05-04", outcome="HIT")
    idx = load_resolution_index(res_dir)
    # Target 2026-05-03 — both candidates within 7 days; closer is 05-04.
    match, kind, dist = find_match("ABCD", "2026-05-03", idx)
    assert kind == "windowed"
    assert dist == 1
    assert match.outcome == "HIT"


def test_find_match_outside_window(tmp_path):
    res_dir = tmp_path / "resolutions"
    res_dir.mkdir()
    write_resolution(res_dir, "ABCD", "2026-05-01", outcome="HIT")
    idx = load_resolution_index(res_dir)
    # Target 2026-05-15 is 14 days off — outside default 7-day window.
    match, kind, dist = find_match("ABCD", "2026-05-15", idx)
    assert kind == "none"
    assert match is None


def test_find_match_unknown_ticker(tmp_path):
    res_dir = tmp_path / "resolutions"
    res_dir.mkdir()
    write_resolution(res_dir, "ABCD", "2026-05-01", outcome="HIT")
    idx = load_resolution_index(res_dir)
    match, kind, _ = find_match("EFGH", "2026-05-01", idx)
    assert kind == "none"
    assert match is None


def test_bind_end_to_end(tmp_path):
    res_dir = tmp_path / "resolutions"
    res_dir.mkdir()
    # Two resolved catalysts and one orphan
    write_resolution(
        res_dir,
        "ABCD",
        "2026-06-15",
        outcome="HIT",
        price_t_minus_1=10.0,
        price_t_plus_5=12.0,
    )
    write_resolution(res_dir, "EFGH", "2026-07-01", outcome="MISS")

    ledger = tmp_path / "shadow.jsonl"
    write_ledger(
        ledger,
        [
            {
                "as_of_date": "2026-05-01",
                "n_changed_names": 3,
                "changed_names": [
                    # Exact match
                    {
                        "ticker": "ABCD",
                        "event_type": "PDUFA",
                        "expected_date": "2026-06-15",
                        "catalyst_id": "id_abcd",
                        "days_to_event": 45,
                    },
                    # Windowed match (3 days off)
                    {
                        "ticker": "EFGH",
                        "event_type": "DATA_READOUT",
                        "expected_date": "2026-06-28",
                        "days_to_event": 58,
                    },
                    # No match — ticker not in resolutions
                    {"ticker": "ZZZZ", "event_type": "PDUFA", "expected_date": "2026-07-15"},
                ],
            }
        ],
    )

    result = bind(ledger_path=ledger, resolutions_dir=res_dir)
    assert result.n_ledger_entries == 1
    assert result.n_changed_names == 3
    assert result.n_bound == 2
    assert result.n_match_exact == 1
    assert result.n_match_windowed == 1
    assert result.n_unresolved == 1

    by_ticker = {r["ticker"]: r for r in result.bound_rows}
    assert by_ticker["ABCD"]["resolution"]["outcome"] == "HIT"
    assert by_ticker["ABCD"]["resolution"]["realized_return"] == pytest.approx(0.2)
    assert by_ticker["ABCD"]["match_type"] == "exact"
    assert by_ticker["EFGH"]["match_type"] == "windowed"
    assert by_ticker["EFGH"]["resolution"]["outcome"] == "MISS"
    assert by_ticker["EFGH"]["resolution"]["realized_return"] is None


def test_bind_handles_legacy_rows_without_expected_date(tmp_path):
    """Old ledger rows pre-date catalyst_id/expected_date; binder reconstructs from days_to_event."""
    res_dir = tmp_path / "resolutions"
    res_dir.mkdir()
    write_resolution(res_dir, "ABCD", "2026-06-15", outcome="HIT")

    ledger = tmp_path / "shadow.jsonl"
    write_ledger(
        ledger,
        [
            {
                "as_of_date": "2026-05-01",
                "changed_names": [
                    # Legacy schema — no expected_date, no catalyst_id, days_to_event=45
                    # 2026-05-01 + 45d = 2026-06-15 → exact match.
                    {"ticker": "ABCD", "event_type": "PDUFA", "days_to_event": 45},
                ],
            }
        ],
    )

    result = bind(ledger_path=ledger, resolutions_dir=res_dir)
    assert result.n_bound == 1
    assert result.n_match_exact == 1
    assert result.bound_rows[0]["expected_date"] == "2026-06-15"
    # catalyst_id absent on the row → bound row carries None.
    assert result.bound_rows[0]["catalyst_id"] is None


def test_bind_drops_rows_with_no_anchor(tmp_path):
    """Rows lacking both expected_date and days_to_event cannot be bound."""
    res_dir = tmp_path / "resolutions"
    res_dir.mkdir()
    ledger = tmp_path / "shadow.jsonl"
    write_ledger(
        ledger,
        [{"as_of_date": "2026-05-01", "changed_names": [{"ticker": "ABCD", "event_type": "PDUFA"}]}],
    )
    result = bind(ledger_path=ledger, resolutions_dir=res_dir)
    assert result.n_no_expected_date == 1
    assert result.n_bound == 0


def test_bind_idempotent_rewrites_sidecar(tmp_path):
    res_dir = tmp_path / "resolutions"
    res_dir.mkdir()
    write_resolution(res_dir, "ABCD", "2026-06-15", outcome="HIT")

    ledger = tmp_path / "shadow.jsonl"
    write_ledger(
        ledger,
        [
            {
                "as_of_date": "2026-05-01",
                "changed_names": [{"ticker": "ABCD", "event_type": "PDUFA", "expected_date": "2026-06-15"}],
            }
        ],
    )

    out = tmp_path / "shadow_resolved.jsonl"

    r1 = bind(ledger_path=ledger, resolutions_dir=res_dir)
    write_sidecar(out, r1.bound_rows)
    text1 = out.read_text()
    n_lines1 = len(text1.splitlines())

    r2 = bind(ledger_path=ledger, resolutions_dir=res_dir)
    write_sidecar(out, r2.bound_rows)
    text2 = out.read_text()
    n_lines2 = len(text2.splitlines())

    # Same row count both runs (no append-mode duplication)
    assert n_lines1 == n_lines2 == 1
    # Schema/version unchanged
    row = json.loads(text2.splitlines()[0])
    assert row["binder_version"] == BINDER_VERSION


def test_bind_handles_missing_ledger(tmp_path):
    """Binder must not crash if the ledger file is absent — empty result is correct."""
    res_dir = tmp_path / "resolutions"
    res_dir.mkdir()
    result = bind(ledger_path=tmp_path / "does_not_exist.jsonl", resolutions_dir=res_dir)
    assert result.n_ledger_entries == 0
    assert result.n_bound == 0


def test_bind_handles_missing_resolutions_dir(tmp_path):
    """Binder must not crash if resolutions dir is absent — every row goes unresolved."""
    ledger = tmp_path / "shadow.jsonl"
    write_ledger(
        ledger,
        [
            {
                "as_of_date": "2026-05-01",
                "changed_names": [{"ticker": "ABCD", "event_type": "PDUFA", "expected_date": "2026-06-15"}],
            }
        ],
    )
    result = bind(ledger_path=ledger, resolutions_dir=tmp_path / "no_such_dir")
    assert result.n_changed_names == 1
    assert result.n_bound == 0
    assert result.n_unresolved == 1

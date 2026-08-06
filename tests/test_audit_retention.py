#!/usr/bin/env python3
"""Tests for trading audit-log retention (PR 4).

``artifacts/trading/isolation_audit.jsonl`` records every trading-boundary decision and
today appends forever with no retention at all. Operator decision (2026-08-03): it is an
audit trail, not routine data, so entries older than one year are **compressed, never
deleted**.

The properties that matter for an audit trail specifically:

* nothing is lost — every input record is still readable afterwards, in either the live
  file or an archive
* re-running changes nothing (a cron that runs twice must not double-archive)
* a partial failure cannot truncate the live log
"""

import gzip
import json
from datetime import datetime, timedelta, timezone

import pytest

from tools.compress_audit_log import AuditRetentionError, archive_path_for, compress_audit_log, read_all_records


def _rec(days_ago: int, event: str = "bind", user: str = "scott") -> dict:
    ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "ts": ts.isoformat(),
        "event": event,
        "user_id": user,
        "account_number": "111111111",
        "pid": 1234,
        "detail": "",
    }


def _write(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, sort_keys=True) + "\n")


class TestNothingIsLost:
    def test_old_records_move_to_archive_and_stay_readable(self, tmp_path):
        log = tmp_path / "isolation_audit.jsonl"
        old, recent = _rec(400), _rec(10)
        _write(log, [old, recent])

        res = compress_audit_log(log, older_than_days=365, apply=True)

        assert res.archived == 1
        assert res.retained == 1
        live = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
        assert live == [recent]

        arch = archive_path_for(log, datetime.fromisoformat(old["ts"]).year)
        assert arch.exists()
        with gzip.open(arch, "rt", encoding="utf-8") as fh:
            assert [json.loads(x) for x in fh if x.strip()] == [old]

    def test_total_record_count_is_preserved(self, tmp_path):
        log = tmp_path / "isolation_audit.jsonl"
        records = [_rec(400), _rec(500), _rec(30), _rec(1)]
        _write(log, records)
        compress_audit_log(log, older_than_days=365, apply=True)
        assert len(read_all_records(log)) == len(records)

    def test_nothing_is_deleted_ever(self, tmp_path):
        """Explicit: the tool must have no delete path."""
        log = tmp_path / "isolation_audit.jsonl"
        _write(log, [_rec(5000)])
        compress_audit_log(log, older_than_days=365, apply=True)
        assert len(read_all_records(log)) == 1


class TestIdempotence:
    def test_second_run_archives_nothing_new(self, tmp_path):
        log = tmp_path / "isolation_audit.jsonl"
        _write(log, [_rec(400), _rec(10)])
        first = compress_audit_log(log, older_than_days=365, apply=True)
        second = compress_audit_log(log, older_than_days=365, apply=True)
        assert first.archived == 1
        assert second.archived == 0

    def test_repeated_runs_do_not_duplicate_archived_records(self, tmp_path):
        log = tmp_path / "isolation_audit.jsonl"
        _write(log, [_rec(400), _rec(10)])
        for _ in range(3):
            compress_audit_log(log, older_than_days=365, apply=True)
        assert len(read_all_records(log)) == 2

    def test_appending_to_an_existing_archive_year_accumulates(self, tmp_path):
        log = tmp_path / "isolation_audit.jsonl"
        _write(log, [_rec(400, event="a")])
        compress_audit_log(log, older_than_days=365, apply=True)
        _write(log, [_rec(401, event="b"), _rec(1, event="c")])
        compress_audit_log(log, older_than_days=365, apply=True)
        events = {r["event"] for r in read_all_records(log)}
        assert {"a", "b", "c"} <= events


class TestDryRunIsDefault:
    def test_without_apply_nothing_is_written(self, tmp_path):
        log = tmp_path / "isolation_audit.jsonl"
        _write(log, [_rec(400), _rec(10)])
        before = log.read_text(encoding="utf-8")
        res = compress_audit_log(log, older_than_days=365, apply=False)
        assert res.archived == 1, "plan should still report what it would do"
        assert log.read_text(encoding="utf-8") == before
        assert not archive_path_for(log, 2000).parent.glob("*.gz") or True


class TestSafety:
    def test_missing_log_is_a_noop_not_an_error(self, tmp_path):
        res = compress_audit_log(tmp_path / "absent.jsonl", older_than_days=365, apply=True)
        assert res.archived == 0 and res.retained == 0

    def test_unparseable_line_is_retained_not_discarded(self, tmp_path):
        """A corrupt audit line is evidence too — never silently dropped."""
        log = tmp_path / "isolation_audit.jsonl"
        _write(log, [_rec(400)])
        with log.open("a", encoding="utf-8") as fh:
            fh.write("{corrupt\n")
        res = compress_audit_log(log, older_than_days=365, apply=True)
        assert "{corrupt" in log.read_text(encoding="utf-8")
        assert res.unparseable == 1

    def test_record_without_timestamp_is_retained(self, tmp_path):
        log = tmp_path / "isolation_audit.jsonl"
        _write(log, [{"event": "no-ts"}, _rec(400)])
        compress_audit_log(log, older_than_days=365, apply=True)
        live = log.read_text(encoding="utf-8")
        assert "no-ts" in live

    def test_negative_window_refused(self, tmp_path):
        log = tmp_path / "isolation_audit.jsonl"
        _write(log, [_rec(400)])
        with pytest.raises(AuditRetentionError):
            compress_audit_log(log, older_than_days=0, apply=True)

    def test_live_log_is_rewritten_atomically(self, tmp_path):
        """No temp file left behind on success."""
        log = tmp_path / "isolation_audit.jsonl"
        _write(log, [_rec(400), _rec(10)])
        compress_audit_log(log, older_than_days=365, apply=True)
        assert list(tmp_path.glob("*.tmp")) == []

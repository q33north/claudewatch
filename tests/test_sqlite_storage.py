"""Test oracle for SQLite storage backend (Phase 1).

These tests define the expected behavior of the SQLite storage module.
Written BEFORE implementation per the test-oracle pattern.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from claudewatch.models import QuotaEvent, UsageRecord


def _make_usage(
    session_id: str = "sess-001",
    minutes_ago: int = 5,
    machine_id: str = "machine-a",
    input_tokens: int = 1000,
    output_tokens: int = 500,
    cache_read: int = 5000,
    cache_create: int = 200,
    model: str = "claude-opus-4-6",
    project: str = "test-project",
    slug: str = "test-slug",
) -> UsageRecord:
    return UsageRecord(
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        session_id=session_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_create,
        project=project,
        machine_id=machine_id,
        slug=slug,
    )


def _make_quota(
    event_type: str = "quota_hit",
    minutes_ago: int = 5,
    machine_id: str = "machine-a",
) -> QuotaEvent:
    return QuotaEvent(
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        event_type=event_type,
        cumulative_input=100_000,
        cumulative_output=50_000,
        message="You've hit your limit",
        machine_id=machine_id,
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


class TestInitDb:
    def test_creates_tables(self, db_path: Path) -> None:
        from claudewatch.storage.sqlite import init_db

        init_db(db_path)
        assert db_path.exists()

        import sqlite3

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        assert "usage_records" in tables
        assert "quota_events" in tables

    def test_idempotent(self, db_path: Path) -> None:
        """Calling init_db twice should not error or lose data."""
        from claudewatch.storage.sqlite import init_db, insert_usage

        init_db(db_path)
        insert_usage(db_path, _make_usage())
        init_db(db_path)  # second call
        # Data should still be there
        from claudewatch.storage.sqlite import read_usage

        records = read_usage(db_path)
        assert len(records) == 1


class TestInsertAndReadUsage:
    def test_round_trip(self, db_path: Path) -> None:
        from claudewatch.storage.sqlite import init_db, insert_usage, read_usage

        init_db(db_path)
        original = _make_usage(session_id="sess-round-trip", machine_id="box-1")
        insert_usage(db_path, original)

        records = read_usage(db_path)
        assert len(records) == 1
        r = records[0]
        assert r.session_id == "sess-round-trip"
        assert r.machine_id == "box-1"
        assert r.input_tokens == original.input_tokens
        assert r.output_tokens == original.output_tokens
        assert r.cache_read_input_tokens == original.cache_read_input_tokens
        assert r.cache_creation_input_tokens == original.cache_creation_input_tokens
        assert r.model == original.model
        assert r.project == original.project
        assert r.slug == original.slug

    def test_multiple_records(self, db_path: Path) -> None:
        from claudewatch.storage.sqlite import init_db, insert_usage, read_usage

        init_db(db_path)
        for i in range(5):
            insert_usage(db_path, _make_usage(session_id=f"sess-{i}", minutes_ago=i))

        records = read_usage(db_path)
        assert len(records) == 5


class TestInsertAndReadQuotaEvent:
    def test_round_trip(self, db_path: Path) -> None:
        from claudewatch.storage.sqlite import (
            init_db,
            insert_quota_event,
            read_quota_events,
        )

        init_db(db_path)
        original = _make_quota(event_type="rate_limit", machine_id="box-2")
        insert_quota_event(db_path, original)

        events = read_quota_events(db_path)
        assert len(events) == 1
        e = events[0]
        assert e.event_type == "rate_limit"
        assert e.machine_id == "box-2"
        assert e.cumulative_input == original.cumulative_input


class TestFilters:
    def test_filter_by_machine(self, db_path: Path) -> None:
        from claudewatch.storage.sqlite import init_db, insert_usage, read_usage

        init_db(db_path)
        insert_usage(db_path, _make_usage(machine_id="laptop"))
        insert_usage(db_path, _make_usage(machine_id="server"))
        insert_usage(db_path, _make_usage(machine_id="laptop"))

        laptop_records = read_usage(db_path, machine_id="laptop")
        assert len(laptop_records) == 2
        assert all(r.machine_id == "laptop" for r in laptop_records)

        server_records = read_usage(db_path, machine_id="server")
        assert len(server_records) == 1

    def test_filter_by_since(self, db_path: Path) -> None:
        from claudewatch.storage.sqlite import init_db, insert_usage, read_usage

        init_db(db_path)
        insert_usage(db_path, _make_usage(minutes_ago=120))  # 2 hours ago
        insert_usage(db_path, _make_usage(minutes_ago=30))  # 30 min ago
        insert_usage(db_path, _make_usage(minutes_ago=5))  # 5 min ago

        since = datetime.now(timezone.utc) - timedelta(minutes=60)
        recent = read_usage(db_path, since=since)
        assert len(recent) == 2

    def test_filter_combined(self, db_path: Path) -> None:
        from claudewatch.storage.sqlite import init_db, insert_usage, read_usage

        init_db(db_path)
        insert_usage(db_path, _make_usage(machine_id="a", minutes_ago=5))
        insert_usage(db_path, _make_usage(machine_id="b", minutes_ago=5))
        insert_usage(db_path, _make_usage(machine_id="a", minutes_ago=120))

        since = datetime.now(timezone.utc) - timedelta(minutes=60)
        results = read_usage(db_path, machine_id="a", since=since)
        assert len(results) == 1


class TestActiveSessions:
    def test_returns_recent_sessions(self, db_path: Path) -> None:
        from claudewatch.storage.sqlite import init_db, insert_usage, read_active_sessions

        init_db(db_path)
        insert_usage(db_path, _make_usage(session_id="active-1", minutes_ago=2, machine_id="box-a"))
        insert_usage(db_path, _make_usage(session_id="active-2", minutes_ago=3, machine_id="box-b"))

        sessions = read_active_sessions(db_path, minutes=10)
        assert len(sessions) == 2
        session_ids = {s["session_id"] for s in sessions}
        assert "active-1" in session_ids
        assert "active-2" in session_ids

    def test_excludes_stale_sessions(self, db_path: Path) -> None:
        from claudewatch.storage.sqlite import init_db, insert_usage, read_active_sessions

        init_db(db_path)
        insert_usage(db_path, _make_usage(session_id="active", minutes_ago=2))
        insert_usage(db_path, _make_usage(session_id="stale", minutes_ago=60))

        sessions = read_active_sessions(db_path, minutes=10)
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "active"

    def test_includes_machine_info(self, db_path: Path) -> None:
        from claudewatch.storage.sqlite import init_db, insert_usage, read_active_sessions

        init_db(db_path)
        insert_usage(db_path, _make_usage(
            session_id="s1", minutes_ago=1, machine_id="my-laptop", model="claude-opus-4-6",
            project="claudewatch", slug="test-slug",
        ))

        sessions = read_active_sessions(db_path, minutes=10)
        assert len(sessions) == 1
        s = sessions[0]
        assert s["machine_id"] == "my-laptop"
        assert s["model"] == "claude-opus-4-6"
        assert s["project"] == "claudewatch"


class TestReadTodayUsage:
    def test_returns_only_today(self, db_path: Path) -> None:
        from claudewatch.storage.sqlite import init_db, insert_usage, read_today_usage

        init_db(db_path)
        insert_usage(db_path, _make_usage(minutes_ago=5))  # today
        insert_usage(db_path, _make_usage(minutes_ago=60 * 25))  # yesterday

        today = read_today_usage(db_path)
        assert len(today) == 1


class TestMigrateJsonl:
    def test_migrates_existing_data(self, db_path: Path, tmp_path: Path) -> None:
        from claudewatch.storage.jsonl import append_usage
        from claudewatch.storage.sqlite import init_db, migrate_jsonl_to_sqlite, read_usage

        jsonl_path = tmp_path / "usage.jsonl"
        for i in range(3):
            append_usage(
                _make_usage(session_id=f"migrated-{i}", minutes_ago=i + 1),
                path=jsonl_path,
            )

        init_db(db_path)
        count = migrate_jsonl_to_sqlite(jsonl_path, db_path)
        assert count == 3

        records = read_usage(db_path)
        assert len(records) == 3
        session_ids = {r.session_id for r in records}
        assert "migrated-0" in session_ids

    def test_migrate_empty_jsonl(self, db_path: Path, tmp_path: Path) -> None:
        from claudewatch.storage.sqlite import init_db, migrate_jsonl_to_sqlite

        jsonl_path = tmp_path / "usage.jsonl"
        jsonl_path.touch()

        init_db(db_path)
        count = migrate_jsonl_to_sqlite(jsonl_path, db_path)
        assert count == 0

    def test_migrate_missing_jsonl(self, db_path: Path, tmp_path: Path) -> None:
        from claudewatch.storage.sqlite import init_db, migrate_jsonl_to_sqlite

        jsonl_path = tmp_path / "does-not-exist.jsonl"
        init_db(db_path)
        count = migrate_jsonl_to_sqlite(jsonl_path, db_path)
        assert count == 0


class TestConcurrentInserts:
    def test_threaded_writes_dont_corrupt(self, db_path: Path) -> None:
        """Multiple threads inserting simultaneously should not lose data."""
        from claudewatch.storage.sqlite import init_db, insert_usage, read_usage

        init_db(db_path)
        n_threads = 10
        records_per_thread = 20
        errors: list[Exception] = []

        def worker(thread_id: int) -> None:
            try:
                for i in range(records_per_thread):
                    insert_usage(
                        db_path,
                        _make_usage(
                            session_id=f"thread-{thread_id}-{i}",
                            machine_id=f"machine-{thread_id}",
                            minutes_ago=i,
                        ),
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent insert errors: {errors}"

        records = read_usage(db_path)
        assert len(records) == n_threads * records_per_thread

"""Test oracle for DataSource abstraction (Phase 4).

Tests the protocol for local and server data sources.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from claudewatch.models import UsageRecord


def _make_usage(
    session_id: str = "sess-ds",
    machine_id: str = "box",
    minutes_ago: int = 2,
) -> UsageRecord:
    return UsageRecord(
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        session_id=session_id,
        model="claude-opus-4-6",
        input_tokens=1000,
        output_tokens=500,
        cache_read_input_tokens=5000,
        cache_creation_input_tokens=200,
        project="test",
        machine_id=machine_id,
    )


class TestLocalDataSource:
    def test_reads_jsonl(self, tmp_path: Path) -> None:
        from claudewatch.storage.jsonl import append_usage
        from claudewatch.tui.data_source import LocalDataSource

        jsonl_path = tmp_path / "usage.jsonl"
        append_usage(_make_usage(session_id="s1"), path=jsonl_path)
        append_usage(_make_usage(session_id="s2"), path=jsonl_path)

        source = LocalDataSource(usage_path=jsonl_path)
        records = source.get_all_records()
        assert len(records) == 2

    def test_get_active_sessions(self, tmp_path: Path) -> None:
        from claudewatch.storage.jsonl import append_usage
        from claudewatch.tui.data_source import LocalDataSource

        jsonl_path = tmp_path / "usage.jsonl"
        append_usage(_make_usage(session_id="active", minutes_ago=2), path=jsonl_path)
        append_usage(_make_usage(session_id="stale", minutes_ago=60), path=jsonl_path)

        source = LocalDataSource(usage_path=jsonl_path)
        sessions = source.get_active_sessions(minutes=10)
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "active"

    def test_get_today_records(self, tmp_path: Path) -> None:
        from claudewatch.storage.jsonl import append_usage
        from claudewatch.tui.data_source import LocalDataSource

        jsonl_path = tmp_path / "usage.jsonl"
        append_usage(_make_usage(minutes_ago=5), path=jsonl_path)

        source = LocalDataSource(usage_path=jsonl_path)
        today = source.get_today_records()
        assert len(today) == 1

    def test_get_session_records(self, tmp_path: Path) -> None:
        from claudewatch.storage.jsonl import append_usage
        from claudewatch.tui.data_source import LocalDataSource

        jsonl_path = tmp_path / "usage.jsonl"
        append_usage(_make_usage(session_id="target"), path=jsonl_path)
        append_usage(_make_usage(session_id="other"), path=jsonl_path)

        source = LocalDataSource(usage_path=jsonl_path)
        recs = source.get_session_records("target")
        assert len(recs) == 1
        assert recs[0].session_id == "target"


class TestServerDataSource:
    def test_fetches_from_api(self, tmp_path: Path) -> None:
        """Server source should fetch records from the API."""
        from fastapi.testclient import TestClient

        from claudewatch.server.app import create_app
        from claudewatch.tui.data_source import ServerDataSource

        db_path = tmp_path / "test.db"
        token = "test-token"
        app = create_app(db_path=db_path, auth_token=token)
        client = TestClient(app)

        # Insert via API
        payload = _make_usage(session_id="api-sess").model_dump(mode="json")
        client.post("/api/usage", json=payload, headers={"Authorization": f"Bearer {token}"})

        source = ServerDataSource(base_url="http://testserver", auth_token=token, client=client)
        records = source.get_all_records()
        assert len(records) >= 1

    def test_get_active_sessions_from_api(self, tmp_path: Path) -> None:
        from fastapi.testclient import TestClient

        from claudewatch.server.app import create_app
        from claudewatch.tui.data_source import ServerDataSource

        db_path = tmp_path / "test.db"
        token = "test-token"
        app = create_app(db_path=db_path, auth_token=token)
        client = TestClient(app)

        payload = _make_usage(session_id="active-api", minutes_ago=1).model_dump(mode="json")
        client.post("/api/usage", json=payload, headers={"Authorization": f"Bearer {token}"})

        source = ServerDataSource(base_url="http://testserver", auth_token=token, client=client)
        sessions = source.get_active_sessions(minutes=10)
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "active-api"

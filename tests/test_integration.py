"""Integration tests for the full multi-machine pipeline (Phase 5).

Tests the end-to-end flow: server + push + query.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from claudewatch.models import UsageRecord
from claudewatch.server.app import create_app


def _make_usage(
    session_id: str,
    machine_id: str,
    minutes_ago: int = 2,
    input_tokens: int = 50_000,
) -> UsageRecord:
    return UsageRecord(
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        session_id=session_id,
        model="claude-opus-4-6",
        input_tokens=input_tokens,
        output_tokens=5_000,
        cache_read_input_tokens=30_000,
        cache_creation_input_tokens=10_000,
        project="test",
        machine_id=machine_id,
        slug=f"session-on-{machine_id}",
    )


@pytest.fixture
def server_setup(tmp_path: Path):
    """Create a server with TestClient and auth token."""
    db_path = tmp_path / "integration.db"
    token = secrets.token_urlsafe(16)
    app = create_app(db_path=db_path, auth_token=token)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    return client, headers, token


class TestFullPipeline:
    def test_two_machines_visible(self, server_setup) -> None:
        """Push from 2 machines, query active sessions, both appear."""
        client, headers, token = server_setup

        # Machine A pushes
        rec_a = _make_usage("sess-laptop", "petes-laptop", minutes_ago=1)
        resp = client.post("/api/usage", json=rec_a.model_dump(mode="json"), headers=headers)
        assert resp.status_code == 201

        # Machine B pushes
        rec_b = _make_usage("sess-server", "umich-hpc", minutes_ago=2)
        resp = client.post("/api/usage", json=rec_b.model_dump(mode="json"), headers=headers)
        assert resp.status_code == 201

        # Query active sessions
        resp = client.get("/api/sessions/active", headers=headers)
        sessions = resp.json()
        assert len(sessions) == 2

        machines = {s["machine_id"] for s in sessions}
        assert "petes-laptop" in machines
        assert "umich-hpc" in machines

    def test_aggregated_today_usage(self, server_setup) -> None:
        """Today's usage should aggregate across all machines."""
        client, headers, _ = server_setup

        client.post(
            "/api/usage",
            json=_make_usage("s1", "laptop", input_tokens=10_000).model_dump(mode="json"),
            headers=headers,
        )
        client.post(
            "/api/usage",
            json=_make_usage("s2", "server", input_tokens=20_000).model_dump(mode="json"),
            headers=headers,
        )

        resp = client.get("/api/usage/today", headers=headers)
        records = resp.json()
        total_input = sum(r["input_tokens"] for r in records)
        assert total_input == 30_000

    def test_session_goes_inactive(self, server_setup) -> None:
        """A session with no recent activity should not appear as active."""
        client, headers, _ = server_setup

        # Old session
        client.post(
            "/api/usage",
            json=_make_usage("old-sess", "laptop", minutes_ago=30).model_dump(mode="json"),
            headers=headers,
        )
        # Recent session
        client.post(
            "/api/usage",
            json=_make_usage("new-sess", "laptop", minutes_ago=1).model_dump(mode="json"),
            headers=headers,
        )

        resp = client.get("/api/sessions/active", params={"minutes": 10}, headers=headers)
        sessions = resp.json()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "new-sess"

    def test_session_records_per_session(self, server_setup) -> None:
        """Can fetch records for a specific session across multiple pushes."""
        client, headers, _ = server_setup

        for i in range(5):
            rec = _make_usage("tracked-sess", "laptop", minutes_ago=i, input_tokens=1000 * (i + 1))
            client.post("/api/usage", json=rec.model_dump(mode="json"), headers=headers)

        # Also push some noise
        client.post(
            "/api/usage",
            json=_make_usage("other-sess", "server").model_dump(mode="json"),
            headers=headers,
        )

        resp = client.get("/api/usage/session/tracked-sess", headers=headers)
        records = resp.json()
        assert len(records) == 5
        assert all(r["session_id"] == "tracked-sess" for r in records)


class TestLocalModeUnchanged:
    def test_local_data_source_works(self, tmp_path: Path) -> None:
        """Local mode should work without any server configuration."""
        from claudewatch.storage.jsonl import append_usage
        from claudewatch.tui.data_source import LocalDataSource

        jsonl_path = tmp_path / "usage.jsonl"
        for i in range(3):
            append_usage(
                _make_usage(f"local-{i}", "localhost", minutes_ago=i + 1),
                path=jsonl_path,
            )

        source = LocalDataSource(usage_path=jsonl_path)
        records = source.get_all_records()
        assert len(records) == 3

        sessions = source.get_active_sessions(minutes=10)
        assert len(sessions) == 3

        today = source.get_today_records()
        assert len(today) == 3


class TestServerDataSourceIntegration:
    def test_server_data_source_reads_from_api(self, server_setup) -> None:
        """ServerDataSource should be able to read from the API."""
        client, headers, token = server_setup

        from claudewatch.tui.data_source import ServerDataSource

        # Push some data
        for i in range(3):
            rec = _make_usage(f"srv-{i}", "box", minutes_ago=i + 1)
            client.post("/api/usage", json=rec.model_dump(mode="json"), headers=headers)

        source = ServerDataSource(base_url="http://testserver", auth_token=token, client=client)

        records = source.get_all_records()
        assert len(records) == 3

        sessions = source.get_active_sessions(minutes=10)
        assert len(sessions) == 3

"""Test oracle for the FastAPI ingest + query server (Phase 2).

Uses FastAPI TestClient for synchronous endpoint testing.
Written BEFORE implementation per the test-oracle pattern.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _usage_payload(
    session_id: str = "sess-001",
    machine_id: str = "machine-a",
    minutes_ago: int = 2,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    model: str = "claude-opus-4-6",
    project: str = "test-project",
    slug: str = "test-slug",
) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    return {
        "timestamp": ts,
        "session_id": session_id,
        "machine_id": machine_id,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": 5000,
        "cache_creation_input_tokens": 200,
        "project": project,
        "service_tier": "standard",
        "speed": "standard",
        "user_id": "default",
        "slug": slug,
    }


def _quota_payload(
    event_type: str = "quota_hit",
    machine_id: str = "machine-a",
    minutes_ago: int = 2,
) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    return {
        "timestamp": ts,
        "event_type": event_type,
        "cumulative_input": 100_000,
        "cumulative_output": 50_000,
        "message": "You've hit your limit",
        "machine_id": machine_id,
    }


@pytest.fixture
def server_db(tmp_path: Path) -> Path:
    return tmp_path / "server.db"


@pytest.fixture
def auth_token() -> str:
    return secrets.token_urlsafe(32)


@pytest.fixture
def client(server_db: Path, auth_token: str) -> TestClient:
    from claudewatch.server.app import create_app

    app = create_app(db_path=server_db, auth_token=auth_token)
    return TestClient(app)


@pytest.fixture
def auth_headers(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}"}


class TestHealth:
    def test_health_no_auth_required(self, client: TestClient) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestAuth:
    def test_post_without_token_rejected(self, client: TestClient) -> None:
        resp = client.post("/api/usage", json=_usage_payload())
        assert resp.status_code == 401

    def test_post_with_bad_token_rejected(self, client: TestClient) -> None:
        resp = client.post(
            "/api/usage",
            json=_usage_payload(),
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    def test_get_without_token_rejected(self, client: TestClient) -> None:
        resp = client.get("/api/sessions/active")
        assert resp.status_code == 401

    def test_post_with_valid_token_accepted(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        resp = client.post("/api/usage", json=_usage_payload(), headers=auth_headers)
        assert resp.status_code == 201


class TestPostUsage:
    def test_post_and_verify(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.post("/api/usage", json=_usage_payload(), headers=auth_headers)
        assert resp.status_code == 201
        assert resp.json()["status"] == "ok"

    def test_post_invalid_payload(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.post(
            "/api/usage", json={"bad": "data"}, headers=auth_headers
        )
        assert resp.status_code == 422

    def test_post_minimal_payload(self, client: TestClient, auth_headers: dict) -> None:
        """Only required fields should be enough."""
        resp = client.post(
            "/api/usage",
            json={
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": "minimal-sess",
                "machine_id": "box",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201


class TestPostQuota:
    def test_post_quota_event(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.post(
            "/api/quota", json=_quota_payload(), headers=auth_headers
        )
        assert resp.status_code == 201


class TestGetActiveSessions:
    def test_returns_sessions(self, client: TestClient, auth_headers: dict) -> None:
        client.post("/api/usage", json=_usage_payload(session_id="s1", machine_id="box-a"), headers=auth_headers)
        client.post("/api/usage", json=_usage_payload(session_id="s2", machine_id="box-b"), headers=auth_headers)

        resp = client.get("/api/sessions/active", headers=auth_headers)
        assert resp.status_code == 200
        sessions = resp.json()
        assert len(sessions) == 2
        sids = {s["session_id"] for s in sessions}
        assert "s1" in sids
        assert "s2" in sids

    def test_empty_when_no_data(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get("/api/sessions/active", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_excludes_stale(self, client: TestClient, auth_headers: dict) -> None:
        # Post an old record
        client.post(
            "/api/usage",
            json=_usage_payload(session_id="stale", minutes_ago=60),
            headers=auth_headers,
        )
        # Post a recent record
        client.post(
            "/api/usage",
            json=_usage_payload(session_id="active", minutes_ago=1),
            headers=auth_headers,
        )

        resp = client.get("/api/sessions/active", headers=auth_headers)
        sessions = resp.json()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "active"


class TestGetTodayUsage:
    def test_returns_today_only(self, client: TestClient, auth_headers: dict) -> None:
        # Post a recent record (today)
        client.post("/api/usage", json=_usage_payload(minutes_ago=5), headers=auth_headers)

        resp = client.get("/api/usage/today", headers=auth_headers)
        assert resp.status_code == 200
        records = resp.json()
        assert len(records) == 1

    def test_aggregates_across_machines(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        client.post(
            "/api/usage",
            json=_usage_payload(machine_id="laptop", input_tokens=1000),
            headers=auth_headers,
        )
        client.post(
            "/api/usage",
            json=_usage_payload(machine_id="server", input_tokens=2000),
            headers=auth_headers,
        )

        resp = client.get("/api/usage/today", headers=auth_headers)
        records = resp.json()
        assert len(records) == 2


class TestGetSessionRecords:
    def test_returns_session_records(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        client.post(
            "/api/usage",
            json=_usage_payload(session_id="target", minutes_ago=5),
            headers=auth_headers,
        )
        client.post(
            "/api/usage",
            json=_usage_payload(session_id="target", minutes_ago=3),
            headers=auth_headers,
        )
        client.post(
            "/api/usage",
            json=_usage_payload(session_id="other", minutes_ago=2),
            headers=auth_headers,
        )

        resp = client.get("/api/usage/session/target", headers=auth_headers)
        assert resp.status_code == 200
        records = resp.json()
        assert len(records) == 2
        assert all(r["session_id"] == "target" for r in records)

    def test_empty_session(self, client: TestClient, auth_headers: dict) -> None:
        resp = client.get("/api/usage/session/nonexistent", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []


class TestMultiMachine:
    def test_records_tagged_by_machine(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        client.post(
            "/api/usage",
            json=_usage_payload(machine_id="laptop", session_id="s1"),
            headers=auth_headers,
        )
        client.post(
            "/api/usage",
            json=_usage_payload(machine_id="umich-server", session_id="s2"),
            headers=auth_headers,
        )

        resp = client.get("/api/sessions/active", headers=auth_headers)
        sessions = resp.json()
        machines = {s["machine_id"] for s in sessions}
        assert "laptop" in machines
        assert "umich-server" in machines

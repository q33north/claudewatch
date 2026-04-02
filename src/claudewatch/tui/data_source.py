"""Data source abstraction for the TUI.

Supports two modes:
- LocalDataSource: reads from JSONL files (existing single-machine behavior)
- ServerDataSource: reads from the claudewatch server API
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from claudewatch.models import QuotaEvent, UsageRecord


class DataSource(Protocol):
    """Protocol for TUI data sources."""

    def get_all_records(self) -> list[UsageRecord]: ...
    def get_today_records(self) -> list[UsageRecord]: ...
    def get_active_sessions(self, minutes: int = 10) -> list[dict]: ...
    def get_session_records(self, session_id: str) -> list[UsageRecord]: ...
    def get_quota_events(self) -> list[QuotaEvent]: ...


class LocalDataSource:
    """Reads from local JSONL files (existing behavior)."""

    def __init__(
        self,
        usage_path: Path | None = None,
        quota_path: Path | None = None,
    ) -> None:
        from claudewatch.config import QUOTA_EVENTS_JSONL, USAGE_JSONL

        self._usage_path = usage_path or USAGE_JSONL
        self._quota_path = quota_path or QUOTA_EVENTS_JSONL

    def get_all_records(self) -> list[UsageRecord]:
        from claudewatch.storage.jsonl import read_usage

        return read_usage(path=self._usage_path)

    def get_today_records(self) -> list[UsageRecord]:
        records = self.get_all_records()
        today = datetime.now().date()
        return [r for r in records if r.timestamp.astimezone().date() == today]

    def get_active_sessions(self, minutes: int = 10) -> list[dict]:
        records = self.get_all_records()
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        by_session: dict[str, list[UsageRecord]] = defaultdict(list)
        for r in records:
            ts = r.timestamp if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                by_session[r.session_id].append(r)

        sessions = []
        for sid, recs in by_session.items():
            latest = max(recs, key=lambda r: r.timestamp)
            sessions.append({
                "session_id": sid,
                "machine_id": latest.machine_id,
                "model": latest.model,
                "project": latest.project,
                "slug": latest.slug,
                "last_activity": latest.timestamp.isoformat(),
                "record_count": len(recs),
            })
        sessions.sort(key=lambda s: s["last_activity"], reverse=True)
        return sessions

    def get_session_records(self, session_id: str) -> list[UsageRecord]:
        return [r for r in self.get_all_records() if r.session_id == session_id]

    def get_quota_events(self) -> list[QuotaEvent]:
        from claudewatch.storage.jsonl import read_quota_events

        return read_quota_events(path=self._quota_path)


class ServerDataSource:
    """Reads from a claudewatch server API."""

    def __init__(
        self,
        base_url: str,
        auth_token: str,
        client=None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {auth_token}"}
        # Allow injecting a TestClient for testing
        self._client = client

    def _get(self, path: str, params: dict | None = None):
        if self._client is not None:
            return self._client.get(path, headers=self._headers, params=params)
        import httpx

        return httpx.get(f"{self._base_url}{path}", headers=self._headers, params=params, timeout=5)

    def get_all_records(self) -> list[UsageRecord]:
        resp = self._get("/api/usage/today")
        if resp.status_code != 200:
            return []
        return [UsageRecord.model_validate(r) for r in resp.json()]

    def get_today_records(self) -> list[UsageRecord]:
        return self.get_all_records()

    def get_active_sessions(self, minutes: int = 10) -> list[dict]:
        resp = self._get("/api/sessions/active", params={"minutes": minutes})
        if resp.status_code != 200:
            return []
        return resp.json()

    def get_session_records(self, session_id: str) -> list[UsageRecord]:
        resp = self._get(f"/api/usage/session/{session_id}")
        if resp.status_code != 200:
            return []
        return [UsageRecord.model_validate(r) for r in resp.json()]

    def get_quota_events(self) -> list[QuotaEvent]:
        # Not yet implemented on server side
        return []

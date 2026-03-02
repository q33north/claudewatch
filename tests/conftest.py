"""Shared test fixtures for claudewatch."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from claudewatch.models import UsageRecord


@pytest.fixture
def sample_usage_record() -> UsageRecord:
    return UsageRecord(
        timestamp=datetime(2026, 2, 28, 12, 0, 0, tzinfo=timezone.utc),
        session_id="test-session-001",
        model="claude-opus-4-6",
        input_tokens=1000,
        output_tokens=500,
        cache_read_input_tokens=5000,
        cache_creation_input_tokens=200,
        project="Q33North",
        service_tier="standard",
        speed="standard",
        slug="test-cool-slug",
    )


@pytest.fixture
def sample_assistant_entry() -> dict:
    """A realistic assistant JSONL entry as found in Claude Code transcripts."""
    return {
        "parentUuid": "abc123",
        "isSidechain": False,
        "userType": "external",
        "cwd": "/home/pabsju/Q33North",
        "sessionId": "test-session-001",
        "slug": "test-cool-slug",
        "version": "2.1.63",
        "type": "assistant",
        "timestamp": "2026-02-28T12:00:00.000Z",
        "message": {
            "model": "claude-opus-4-6",
            "id": "msg_test123",
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Here is my response."}
            ],
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_creation_input_tokens": 200,
                "cache_read_input_tokens": 5000,
                "server_tool_use": {
                    "web_search_requests": 0,
                    "web_fetch_requests": 0,
                },
                "service_tier": "standard",
                "cache_creation": {
                    "ephemeral_1h_input_tokens": 200,
                    "ephemeral_5m_input_tokens": 0,
                },
                "speed": "standard",
            },
        },
    }


@pytest.fixture
def sample_transcript(tmp_path: Path, sample_assistant_entry: dict) -> Path:
    """Create a temporary JSONL transcript file with a sample assistant entry."""
    transcript = tmp_path / "session.jsonl"
    # Write a user entry followed by an assistant entry
    user_entry = {
        "type": "human",
        "sessionId": "test-session-001",
        "timestamp": "2026-02-28T11:59:55.000Z",
        "message": {"role": "user", "content": "Hello"},
    }
    with open(transcript, "w") as f:
        f.write(json.dumps(user_entry) + "\n")
        f.write(json.dumps(sample_assistant_entry) + "\n")
    return transcript


@pytest.fixture
def empty_usage_file(tmp_path: Path) -> Path:
    """Create an empty usage JSONL file."""
    path = tmp_path / "usage.jsonl"
    path.touch()
    return path

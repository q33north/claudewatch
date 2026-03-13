"""Tests for the backfill module."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from claudewatch.collector.backfill import (
    extract_records_from_session,
    find_session_files,
)
from claudewatch.config import decode_project_dir


def test_decode_project_dir():
    assert decode_project_dir("-home-pabsju-Q33North") == "Q33North"
    assert decode_project_dir("-home-user-my-project") == "project"
    assert decode_project_dir("standalone") == "standalone"


def test_extract_records_from_session(tmp_path, sample_assistant_entry):
    path = tmp_path / "session.jsonl"
    user = {"type": "human", "timestamp": "2026-02-28T11:59:00Z"}

    with open(path, "w") as f:
        f.write(json.dumps(user) + "\n")
        f.write(json.dumps(sample_assistant_entry) + "\n")

    records = extract_records_from_session(path, "TestProject")
    assert len(records) == 1
    assert records[0].project == "TestProject"
    assert records[0].output_tokens == 500
    # session_id comes from entry's sessionId field
    assert records[0].session_id == "test-session-001"


def test_extract_session_id_falls_back_to_stem(tmp_path):
    """When entry has no sessionId, fall back to filename stem."""
    path = tmp_path / "abc123.jsonl"
    entry = {
        "type": "assistant",
        "timestamp": "2026-02-28T12:00:00Z",
        "message": {
            "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        },
    }
    with open(path, "w") as f:
        f.write(json.dumps(entry) + "\n")

    records = extract_records_from_session(path, "Test")
    assert len(records) == 1
    assert records[0].session_id == "abc123"


def test_extract_subagent_uses_parent_session_id(tmp_path):
    """Subagent JSONL entries carry the parent's sessionId."""
    path = tmp_path / "agent-a238236e03a4b987a.jsonl"
    entry = {
        "type": "assistant",
        "timestamp": "2026-02-28T12:00:00Z",
        "sessionId": "fec6de19-parent-session",
        "agentId": "a238236e03a4b987a",
        "message": {
            "model": "claude-sonnet-4-6",
            "usage": {
                "input_tokens": 5000,
                "output_tokens": 200,
                "cache_read_input_tokens": 1000,
                "cache_creation_input_tokens": 3000,
            },
        },
    }
    with open(path, "w") as f:
        f.write(json.dumps(entry) + "\n")

    records = extract_records_from_session(path, "TestProject")
    assert len(records) == 1
    assert records[0].session_id == "fec6de19-parent-session"
    assert records[0].input_tokens == 5000


def test_extract_skips_zero_output(tmp_path):
    path = tmp_path / "session.jsonl"
    entry = {
        "type": "assistant",
        "timestamp": "2026-02-28T12:00:00Z",
        "sessionId": "s1",
        "message": {
            "model": "claude-opus-4-6",
            "usage": {"input_tokens": 100, "output_tokens": 0},
        },
    }
    with open(path, "w") as f:
        f.write(json.dumps(entry) + "\n")

    records = extract_records_from_session(path, "Test")
    assert len(records) == 0


def test_extract_handles_malformed_lines(tmp_path):
    path = tmp_path / "session.jsonl"
    with open(path, "w") as f:
        f.write("not json\n")
        f.write('{"type": "assistant"}\n')  # missing usage

    records = extract_records_from_session(path, "Test")
    assert len(records) == 0


def test_find_session_files_includes_subagents(tmp_path, monkeypatch):
    """find_session_files discovers both parent and subagent JSONL files."""
    import claudewatch.collector.backfill as backfill_mod

    monkeypatch.setattr(backfill_mod, "PROJECTS_DIR", tmp_path)

    # Create fake project structure
    project_dir = tmp_path / "-home-user-myproject"
    project_dir.mkdir()

    # Parent transcript
    parent = project_dir / "aaa-bbb-ccc.jsonl"
    parent.write_text("{}\n")

    # Subagent transcripts
    subagent_dir = project_dir / "aaa-bbb-ccc" / "subagents"
    subagent_dir.mkdir(parents=True)
    (subagent_dir / "agent-a1234.jsonl").write_text("{}\n")
    (subagent_dir / "agent-a5678.jsonl").write_text("{}\n")
    # meta.json should NOT be picked up
    (subagent_dir / "agent-a1234.meta.json").write_text("{}\n")

    files = find_session_files()
    paths = [f[0].name for f in files]

    assert "aaa-bbb-ccc.jsonl" in paths
    assert "agent-a1234.jsonl" in paths
    assert "agent-a5678.jsonl" in paths
    assert "agent-a1234.meta.json" not in paths
    assert len(files) == 3

"""Tests for the backfill module."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from claudewatch.collector.backfill import (
    extract_records_from_session,
    decode_project_dir,
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
    assert records[0].session_id == path.stem


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

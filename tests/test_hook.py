"""Tests for the Stop hook collector logic."""

import json
from pathlib import Path

from claudewatch.collector.hook import (
    tail_read_last_assistant,
    extract_usage_record,
    check_quota_patterns,
)


def test_tail_read_finds_assistant(sample_transcript):
    entry = tail_read_last_assistant(str(sample_transcript))
    assert entry is not None
    assert entry["type"] == "assistant"
    assert entry["message"]["usage"]["output_tokens"] == 500


def test_tail_read_empty_file(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.touch()
    assert tail_read_last_assistant(str(empty)) is None


def test_tail_read_no_assistant(tmp_path):
    path = tmp_path / "no_assistant.jsonl"
    with open(path, "w") as f:
        f.write(json.dumps({"type": "human", "message": {"content": "hi"}}) + "\n")
    assert tail_read_last_assistant(str(path)) is None


def test_tail_read_skips_zero_output(tmp_path):
    """Should skip assistant entries with output_tokens == 0 (partial streaming)."""
    path = tmp_path / "partial.jsonl"
    good_entry = {
        "type": "assistant",
        "timestamp": "2026-02-28T10:00:00Z",
        "sessionId": "s1",
        "message": {
            "model": "claude-opus-4-6",
            "usage": {"input_tokens": 100, "output_tokens": 200},
        },
    }
    bad_entry = {
        "type": "assistant",
        "timestamp": "2026-02-28T10:01:00Z",
        "sessionId": "s1",
        "message": {
            "model": "claude-opus-4-6",
            "usage": {"input_tokens": 100, "output_tokens": 0},
        },
    }
    with open(path, "w") as f:
        f.write(json.dumps(good_entry) + "\n")
        f.write(json.dumps(bad_entry) + "\n")

    result = tail_read_last_assistant(str(path))
    assert result is not None
    assert result["message"]["usage"]["output_tokens"] == 200


def test_extract_usage_record(sample_assistant_entry):
    record = extract_usage_record(sample_assistant_entry, "/home/pabsju/Q33North")
    assert record.session_id == "test-session-001"
    assert record.model == "claude-opus-4-6"
    assert record.input_tokens == 1000
    assert record.output_tokens == 500
    assert record.project == "Q33North"


def test_check_quota_patterns_hit():
    entry = {
        "message": {
            "content": [{"type": "text", "text": "You've hit your limit for today."}]
        }
    }
    assert check_quota_patterns(entry) == "quota_hit"


def test_check_quota_patterns_rate_limit():
    entry = {
        "message": {
            "content": [{"type": "text", "text": "overloaded_error: too many requests"}]
        }
    }
    assert check_quota_patterns(entry) == "rate_limit"


def test_check_quota_patterns_none():
    entry = {
        "message": {
            "content": [{"type": "text", "text": "Here is your answer."}]
        }
    }
    assert check_quota_patterns(entry) is None


def test_extract_usage_record_slug():
    entry = {
        "type": "assistant",
        "timestamp": "2026-02-28T12:00:00.000Z",
        "sessionId": "test-session-001",
        "slug": "test-cool-slug",
        "message": {
            "model": "claude-opus-4-6",
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        },
    }
    record = extract_usage_record(entry, "/home/user/project")
    assert record.slug == "test-cool-slug"

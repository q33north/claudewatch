"""Tests for the Stop and PostToolUse hook collector logic."""

import json
from datetime import datetime, timezone
from pathlib import Path

from claudewatch.collector.hook import (
    tail_read_last_assistant,
    extract_usage_record,
    check_quota_patterns,
    _is_duplicate,
)
from claudewatch.models import UsageRecord
from claudewatch.storage.jsonl import append_usage, read_last_usage


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


def test_read_last_usage(tmp_path):
    """read_last_usage should return the most recently appended record."""
    path = tmp_path / "usage.jsonl"
    r1 = UsageRecord(
        timestamp=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
        session_id="s1",
        output_tokens=100,
    )
    r2 = UsageRecord(
        timestamp=datetime(2026, 3, 1, 10, 5, tzinfo=timezone.utc),
        session_id="s1",
        output_tokens=200,
    )
    append_usage(r1, path=path)
    append_usage(r2, path=path)
    last = read_last_usage(path=path)
    assert last is not None
    assert last.output_tokens == 200


def test_read_last_usage_empty(tmp_path):
    path = tmp_path / "usage.jsonl"
    path.touch()
    assert read_last_usage(path=path) is None


def test_is_duplicate_true(tmp_path, monkeypatch):
    """Duplicate detection should catch same (session_id, input_tokens, output_tokens)."""
    path = tmp_path / "usage.jsonl"
    record = UsageRecord(
        timestamp=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
        session_id="s1",
        model="claude-opus-4-6",
        input_tokens=1000,
        output_tokens=500,
    )
    append_usage(record, path=path)

    # Monkey-patch read_last_usage to use our tmp file
    monkeypatch.setattr(
        "claudewatch.collector.hook.read_last_usage",
        lambda: read_last_usage(path=path),
    )
    assert _is_duplicate(record) is True


def test_is_duplicate_true_different_timestamp(tmp_path, monkeypatch):
    """Same session/input/output but different timestamp should still be a duplicate.

    PostToolUse hooks fire rapidly with slightly different timestamps for the
    same assistant response.
    """
    path = tmp_path / "usage.jsonl"
    r1 = UsageRecord(
        timestamp=datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
        session_id="s1",
        input_tokens=1000,
        output_tokens=500,
    )
    r2 = UsageRecord(
        timestamp=datetime(2026, 3, 1, 12, 0, 2, tzinfo=timezone.utc),
        session_id="s1",
        input_tokens=1000,
        output_tokens=500,
    )
    append_usage(r1, path=path)

    monkeypatch.setattr(
        "claudewatch.collector.hook.read_last_usage",
        lambda: read_last_usage(path=path),
    )
    assert _is_duplicate(r2) is True


def test_is_duplicate_false_different_output(tmp_path, monkeypatch):
    """Different output_tokens means different API call, not a duplicate."""
    path = tmp_path / "usage.jsonl"
    r1 = UsageRecord(
        timestamp=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
        session_id="s1",
        output_tokens=500,
    )
    r2 = UsageRecord(
        timestamp=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
        session_id="s1",
        output_tokens=800,
    )
    append_usage(r1, path=path)

    monkeypatch.setattr(
        "claudewatch.collector.hook.read_last_usage",
        lambda: read_last_usage(path=path),
    )
    assert _is_duplicate(r2) is False


def test_is_duplicate_false_empty(tmp_path, monkeypatch):
    """No previous records means nothing to duplicate."""
    path = tmp_path / "usage.jsonl"
    path.touch()
    monkeypatch.setattr(
        "claudewatch.collector.hook.read_last_usage",
        lambda: read_last_usage(path=path),
    )
    record = UsageRecord(
        timestamp=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
        session_id="s1",
        output_tokens=500,
    )
    assert _is_duplicate(record) is False


def test_hook_input_accepts_posttool_fields():
    """HookInput should accept PostToolUse-specific fields."""
    from claudewatch.models import HookInput
    raw = json.dumps({
        "session_id": "s1",
        "transcript_path": "/tmp/t.jsonl",
        "cwd": "/home/user",
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
    })
    hi = HookInput.model_validate_json(raw)
    assert hi.hook_event_name == "PostToolUse"
    assert hi.tool_name == "Bash"

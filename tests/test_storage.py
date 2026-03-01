"""Tests for JSONL storage operations."""

from datetime import datetime, timezone
from pathlib import Path

from claudewatch.models import UsageRecord, QuotaEvent
from claudewatch.storage.jsonl import (
    append_usage,
    append_quota_event,
    read_usage,
    read_quota_events,
    tail_read_new_lines,
    iter_usage_from_offset,
)


def test_append_and_read_usage(tmp_path):
    path = tmp_path / "usage.jsonl"
    record = UsageRecord(
        timestamp=datetime(2026, 2, 28, 12, 0, tzinfo=timezone.utc),
        session_id="s1",
        model="claude-opus-4-6",
        input_tokens=100,
        output_tokens=50,
    )
    append_usage(record, path=path)
    append_usage(record, path=path)

    records = read_usage(path=path)
    assert len(records) == 2
    assert records[0].session_id == "s1"


def test_append_and_read_quota_events(tmp_path):
    path = tmp_path / "quota.jsonl"
    event = QuotaEvent(
        timestamp=datetime(2026, 2, 28, 12, 0, tzinfo=timezone.utc),
        event_type="quota_hit",
        message="test",
    )
    append_quota_event(event, path=path)

    events = read_quota_events(path=path)
    assert len(events) == 1
    assert events[0].event_type == "quota_hit"


def test_read_nonexistent_file(tmp_path):
    assert read_usage(path=tmp_path / "nope.jsonl") == []
    assert read_quota_events(path=tmp_path / "nope.jsonl") == []


def test_tail_read_new_lines(tmp_path):
    path = tmp_path / "test.jsonl"
    path.write_text("line1\nline2\n")

    # Read from start
    lines, offset = tail_read_new_lines(path, 0)
    assert lines == ["line1", "line2"]
    assert offset > 0

    # No new data
    lines2, offset2 = tail_read_new_lines(path, offset)
    assert lines2 == []
    assert offset2 == offset

    # Append more data
    with open(path, "a") as f:
        f.write("line3\n")

    lines3, offset3 = tail_read_new_lines(path, offset)
    assert lines3 == ["line3"]
    assert offset3 > offset


def test_iter_usage_from_offset(tmp_path):
    path = tmp_path / "usage.jsonl"
    record = UsageRecord(
        timestamp=datetime(2026, 2, 28, 12, 0, tzinfo=timezone.utc),
        session_id="s1",
    )
    append_usage(record, path=path)

    results = list(iter_usage_from_offset(path, 0))
    assert len(results) == 1
    assert results[0][0].session_id == "s1"

"""Tests for pydantic models."""

from datetime import datetime, timezone

from claudewatch.models import UsageRecord, QuotaEvent, SessionSummary, HookInput


def test_usage_record_total_tokens(sample_usage_record):
    assert sample_usage_record.total_tokens == 1000 + 500 + 5000 + 200


def test_usage_record_cost_estimate(sample_usage_record):
    cost = sample_usage_record.cost_estimate
    assert cost > 0
    # Opus pricing: (1000*15 + 500*75 + 5000*1.5 + 200*18.75) / 1_000_000
    expected = (15000 + 37500 + 7500 + 3750) / 1_000_000
    assert abs(cost - expected) < 0.001


def test_usage_record_defaults():
    record = UsageRecord(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        session_id="s1",
    )
    assert record.model == "unknown"
    assert record.input_tokens == 0
    assert record.total_tokens == 0


def test_usage_record_serialization(sample_usage_record):
    json_str = sample_usage_record.model_dump_json()
    restored = UsageRecord.model_validate_json(json_str)
    assert restored.session_id == sample_usage_record.session_id
    assert restored.total_tokens == sample_usage_record.total_tokens


def test_quota_event():
    event = QuotaEvent(
        timestamp=datetime(2026, 2, 28, tzinfo=timezone.utc),
        event_type="quota_hit",
        cumulative_input=1_000_000,
        cumulative_output=500_000,
        message="Hit limit",
    )
    assert event.event_type == "quota_hit"


def test_session_summary_duration():
    summary = SessionSummary(
        session_id="s1",
        start_time=datetime(2026, 2, 28, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 2, 28, 10, 30, tzinfo=timezone.utc),
        message_count=5,
    )
    assert summary.duration_minutes == 30.0


def test_hook_input():
    raw = '{"session_id": "s1", "transcript_path": "/tmp/t.jsonl", "cwd": "/home/user/project"}'
    hi = HookInput.model_validate_json(raw)
    assert hi.session_id == "s1"
    assert hi.stop_hook_active is False


def test_usage_record_cache_hit_ratio(sample_usage_record):
    # cache_read=5000, cache_create=200 -> 5000/5200
    ratio = sample_usage_record.cache_hit_ratio
    assert abs(ratio - 5000 / 5200) < 0.001


def test_usage_record_cache_hit_ratio_zero():
    record = UsageRecord(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        session_id="s1",
    )
    assert record.cache_hit_ratio == 0.0


def test_session_summary_cache_hit_ratio():
    summary = SessionSummary(
        session_id="s1",
        start_time=datetime(2026, 2, 28, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 2, 28, 10, 30, tzinfo=timezone.utc),
        total_cache_read=8000,
        total_cache_create=2000,
        message_count=5,
    )
    assert abs(summary.cache_hit_ratio - 0.8) < 0.001


def test_slug_field_roundtrip(sample_usage_record):
    json_str = sample_usage_record.model_dump_json()
    restored = UsageRecord.model_validate_json(json_str)
    assert restored.slug == "test-cool-slug"


def test_slug_default():
    record = UsageRecord(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        session_id="s1",
    )
    assert record.slug == ""

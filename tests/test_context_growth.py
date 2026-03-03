"""Tests for the ContextGrowth widget logic."""

from datetime import datetime, timedelta, timezone

from claudewatch.models import UsageRecord
from claudewatch.tui.widgets.context_growth import ContextGrowth
from claudewatch.tui.widgets.timeline import format_tokens


def _make_record(
    session_id: str,
    minutes_ago: int,
    input_tokens: int = 100,
    cache_read: int = 50000,
    cache_create: int = 10000,
    slug: str = "",
) -> UsageRecord:
    """Helper to create a usage record with a timestamp relative to now."""
    return UsageRecord(
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        session_id=session_id,
        model="claude-opus-4-6",
        input_tokens=input_tokens,
        output_tokens=500,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_create,
        project="test",
        slug=slug,
    )


def test_sparkline_uses_full_context_window():
    """Context growth should use input + cache_read + cache_create, not just input_tokens."""
    records = [
        _make_record("s1", 30, input_tokens=100, cache_read=50000, cache_create=10000),
        _make_record("s1", 20, input_tokens=150, cache_read=80000, cache_create=12000),
        _make_record("s1", 10, input_tokens=200, cache_read=120000, cache_create=15000),
    ]
    widget = ContextGrowth()
    widget._records = records
    sparks = widget._session_sparklines(top_n=5)

    assert len(sparks) == 1
    label, spark_str, peak_str = sparks[0]

    # Peak should be 200 + 120000 + 15000 = 135200, formatted as "135K"
    expected_peak = 200 + 120000 + 15000
    assert peak_str == format_tokens(expected_peak)


def test_sparkline_not_just_input_tokens():
    """Verify we're NOT just using input_tokens (the old bug)."""
    records = [
        _make_record("s1", 30, input_tokens=3, cache_read=100000, cache_create=20000),
        _make_record("s1", 20, input_tokens=3, cache_read=150000, cache_create=25000),
    ]
    widget = ContextGrowth()
    widget._records = records
    sparks = widget._session_sparklines(top_n=5)

    assert len(sparks) == 1
    _, _, peak_str = sparks[0]

    # If the bug returned, peak would be "3" (just input_tokens)
    assert peak_str != "3"
    # Actual peak: 3 + 150000 + 25000 = 175003
    assert peak_str == format_tokens(175003)


def test_sparkline_growing_context():
    """Sparkline values should increase as context accumulates across turns."""
    records = [
        _make_record("s1", 50, input_tokens=100, cache_read=20000, cache_create=30000),
        _make_record("s1", 40, input_tokens=100, cache_read=60000, cache_create=5000),
        _make_record("s1", 30, input_tokens=100, cache_read=90000, cache_create=3000),
        _make_record("s1", 20, input_tokens=100, cache_read=120000, cache_create=2000),
        _make_record("s1", 10, input_tokens=100, cache_read=150000, cache_create=1000),
    ]
    widget = ContextGrowth()
    widget._records = records
    sparks = widget._session_sparklines(top_n=5)

    assert len(sparks) == 1
    _, _, peak_str = sparks[0]
    # Peak turn: 100 + 150000 + 1000 = 151100
    assert peak_str == format_tokens(151100)


def test_single_record_session_excluded():
    """Sessions with only 1 record should not generate a sparkline."""
    records = [
        _make_record("s1", 10, input_tokens=100, cache_read=50000, cache_create=10000),
    ]
    widget = ContextGrowth()
    widget._records = records
    sparks = widget._session_sparklines(top_n=5)
    assert len(sparks) == 0


def test_multiple_sessions_ordered_by_recency():
    """Most recent sessions should appear first."""
    records = [
        _make_record("old-session", 120, slug="old-sess"),
        _make_record("old-session", 100, slug="old-sess"),
        _make_record("new-session", 20, slug="new-sess"),
        _make_record("new-session", 10, slug="new-sess"),
    ]
    widget = ContextGrowth()
    widget._records = records
    sparks = widget._session_sparklines(top_n=5)

    assert len(sparks) == 2
    assert sparks[0][0] == "new-sess"
    assert sparks[1][0] == "old-sess"


def test_render_shows_axis_labels():
    """Rendered output should include 0 and peak value as y-axis."""
    records = [
        _make_record("s1", 30, input_tokens=100, cache_read=50000, cache_create=10000),
        _make_record("s1", 10, input_tokens=200, cache_read=120000, cache_create=15000),
    ]
    widget = ContextGrowth()
    widget._records = records
    rendered = str(widget.render())

    assert "0" in rendered
    peak = 200 + 120000 + 15000  # 135200
    assert format_tokens(peak) in rendered


def test_render_empty_data():
    """Widget should render gracefully with no data."""
    widget = ContextGrowth()
    widget._records = []
    rendered = str(widget.render())
    assert "not enough session data yet" in rendered

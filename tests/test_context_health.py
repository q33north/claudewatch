"""Tests for the ContextHealth widget logic."""

from datetime import datetime, timezone

from claudewatch.models import UsageRecord
from claudewatch.tui.widgets.context_health import _cache_bar


def test_cache_bar_high():
    bar = _cache_bar(0.9)
    assert "green" in bar
    assert "90%" in bar


def test_cache_bar_medium():
    bar = _cache_bar(0.6)
    assert "yellow" in bar
    assert "60%" in bar


def test_cache_bar_low():
    bar = _cache_bar(0.3)
    assert "red" in bar
    assert "30%" in bar


def test_cache_bar_zero():
    bar = _cache_bar(0.0)
    assert "0%" in bar


def test_context_health_renders_empty():
    """Widget should render gracefully with no data."""
    from claudewatch.tui.widgets.context_health import ContextHealth

    widget = ContextHealth()
    # Simulate update with empty data
    widget.update_data([], [])
    rendered = widget.render()
    assert "Context Health" in rendered
    assert "cache ratio" in rendered

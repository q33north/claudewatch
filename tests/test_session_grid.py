"""Test oracle for the SessionGrid widget (Phase 4).

Tests the multi-session grid container that manages per-session ContextGrids.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from claudewatch.models import UsageRecord


def _make_usage(
    session_id: str = "sess-grid",
    machine_id: str = "box",
    minutes_ago: int = 2,
    model: str = "claude-opus-4-6",
    slug: str = "",
) -> UsageRecord:
    return UsageRecord(
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        session_id=session_id,
        model=model,
        input_tokens=50_000,
        output_tokens=5_000,
        cache_read_input_tokens=30_000,
        cache_creation_input_tokens=10_000,
        project="test",
        machine_id=machine_id,
        slug=slug,
    )


class TestDiscoverActiveSessions:
    def test_finds_recent_sessions(self) -> None:
        from claudewatch.tui.widgets.session_grid import discover_active_sessions

        records = [
            _make_usage(session_id="s1", minutes_ago=2, machine_id="a"),
            _make_usage(session_id="s2", minutes_ago=3, machine_id="b"),
            _make_usage(session_id="s3", minutes_ago=5, machine_id="a"),
        ]
        sessions = discover_active_sessions(records, minutes=10)
        assert len(sessions) == 3

    def test_excludes_stale(self) -> None:
        from claudewatch.tui.widgets.session_grid import discover_active_sessions

        records = [
            _make_usage(session_id="active", minutes_ago=2),
            _make_usage(session_id="stale", minutes_ago=60),
        ]
        sessions = discover_active_sessions(records, minutes=10)
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "active"

    def test_max_three(self) -> None:
        from claudewatch.tui.widgets.session_grid import discover_active_sessions

        records = [
            _make_usage(session_id=f"s{i}", minutes_ago=i) for i in range(1, 6)
        ]
        sessions = discover_active_sessions(records, minutes=10)
        # Should cap at 3 (the dashboard has 3 grid slots)
        assert len(sessions) <= 3

    def test_ordered_by_recency(self) -> None:
        from claudewatch.tui.widgets.session_grid import discover_active_sessions

        records = [
            _make_usage(session_id="old", minutes_ago=8),
            _make_usage(session_id="newest", minutes_ago=1),
            _make_usage(session_id="mid", minutes_ago=4),
        ]
        sessions = discover_active_sessions(records, minutes=10)
        assert sessions[0]["session_id"] == "newest"

    def test_empty(self) -> None:
        from claudewatch.tui.widgets.session_grid import discover_active_sessions

        sessions = discover_active_sessions([], minutes=10)
        assert sessions == []

    def test_includes_metadata(self) -> None:
        from claudewatch.tui.widgets.session_grid import discover_active_sessions

        records = [
            _make_usage(session_id="s1", machine_id="laptop", slug="my-session"),
        ]
        sessions = discover_active_sessions(records, minutes=10)
        assert len(sessions) == 1
        s = sessions[0]
        assert s["machine_id"] == "laptop"
        assert s["session_id"] == "s1"

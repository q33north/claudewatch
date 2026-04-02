"""Tests for the ContextGrid widget logic."""

from datetime import datetime, timedelta, timezone

from claudewatch.models import UsageRecord
from claudewatch.tui.widgets.context_grid import (
    ContextGrid,
    _get_context_window,
    _latest_session_records,
    SYM_FULL,
    SYM_PARTIAL,
    SYM_FREE,
)


def _make_record(
    session_id: str = "sess-abc",
    minutes_ago: int = 5,
    input_tokens: int = 50_000,
    output_tokens: int = 5_000,
    cache_read: int = 30_000,
    cache_create: int = 10_000,
    model: str = "claude-opus-4-6",
    slug: str = "test-session",
) -> UsageRecord:
    return UsageRecord(
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        session_id=session_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_create,
        project="test",
        slug=slug,
    )


class TestContextWindow:
    def test_opus_1m(self):
        assert _get_context_window("claude-opus-4-6") == 1_000_000

    def test_sonnet_1m(self):
        assert _get_context_window("claude-sonnet-4-6") == 1_000_000

    def test_haiku_200k(self):
        assert _get_context_window("claude-haiku-4-5-20251001") == 200_000

    def test_unknown_defaults_200k(self):
        assert _get_context_window("claude-unknown-9000") == 200_000


class TestLatestSession:
    def test_picks_most_recent(self):
        records = [
            _make_record("old", minutes_ago=120, slug="old"),
            _make_record("old", minutes_ago=100, slug="old"),
            _make_record("new", minutes_ago=10, slug="new"),
            _make_record("new", minutes_ago=5, slug="new"),
        ]
        recs, label = _latest_session_records(records)
        assert label == "new"
        assert all(r.session_id == "new" for r in recs)

    def test_empty_records(self):
        recs, label = _latest_session_records([])
        assert recs == []
        assert label == ""


class TestBuildGrid:
    def test_grid_dimensions(self):
        records = [
            _make_record(minutes_ago=10),
            _make_record(minutes_ago=5),
        ]
        widget = ContextGrid()
        widget._records = records
        grid_rows, legend, label, model, ctx = widget._build_grid(cols=20, rows=8)

        assert len(grid_rows) == 8
        assert all(len(row) == 20 for row in grid_rows)
        assert ctx == 1_000_000

    def test_has_category_squares(self):
        records = [
            _make_record(minutes_ago=5, input_tokens=100_000, output_tokens=50_000),
        ]
        widget = ContextGrid()
        widget._records = records
        grid_rows, legend, *_ = widget._build_grid(cols=10, rows=10)

        # Flatten and check we have non-free squares
        all_cells = [cell for row in grid_rows for cell in row]
        categories = {cell["name"] for cell in all_cells}
        assert "input" in categories
        assert "free" in categories

    def test_legend_entries(self):
        records = [_make_record(minutes_ago=5)]
        widget = ContextGrid()
        widget._records = records
        _, legend, *_ = widget._build_grid()

        names = [e["name"] for e in legend]
        assert "input" in names
        assert "output" in names
        assert "free" in names

    def test_no_data_returns_empty(self):
        widget = ContextGrid()
        widget._records = []
        grid_rows, legend, label, model, ctx = widget._build_grid()
        assert grid_rows == []
        assert label == ""


class TestRender:
    def test_render_with_data(self):
        records = [
            _make_record(minutes_ago=10),
            _make_record(minutes_ago=5),
        ]
        widget = ContextGrid()
        widget._records = records
        rendered = widget.render()
        text = str(rendered)

        assert "Context Grid" in text
        assert SYM_FREE.strip() in text

    def test_render_empty(self):
        widget = ContextGrid()
        widget._records = []
        rendered = widget.render()
        assert "no session data" in str(rendered)

    def test_render_shows_model(self):
        records = [_make_record(minutes_ago=5)]
        widget = ContextGrid()
        widget._records = records
        text = str(widget.render())
        assert "opus" in text

    def test_symbols_present(self):
        """Grid should contain the expected unicode symbols."""
        records = [
            _make_record(minutes_ago=5, input_tokens=200_000, output_tokens=100_000),
        ]
        widget = ContextGrid()
        widget._records = records
        text = str(widget.render())
        # Should have at least free space symbols
        assert "⛶" in text

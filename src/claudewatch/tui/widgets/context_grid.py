"""Context grid widget - Claude Code style token usage matrix.

Ported from the /context display in Claude Code's source (React/Ink -> Textual).
Shows a grid of unicode symbols representing token usage categories for the
most recent active session.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from claudewatch.models import UsageRecord
from claudewatch.tui.widgets.timeline import format_tokens

# Grid symbols
SYM_FULL = "⛁ "  # category cell >= 70% full
SYM_PARTIAL = "⛀ "  # category cell < 70% full
SYM_FREE = "⛶ "  # free space

# Category definitions: (name, color, description)
CATEGORIES = [
    ("input", "bright_blue", "Input tokens"),
    ("output", "bright_green", "Output tokens"),
    ("cache_read", "bright_yellow", "Cache read"),
    ("cache_create", "bright_magenta", "Cache create"),
]

FREE_COLOR = "bright_black"

# Context window sizes per model family (tokens)
CONTEXT_WINDOWS: dict[str, int] = {
    "claude-opus-4-6": 1_000_000,
    "claude-sonnet-4-6": 1_000_000,
    "claude-haiku-4-5-20251001": 200_000,
    "default": 200_000,
}


def _get_context_window(model: str) -> int:
    """Get context window size for a model."""
    return CONTEXT_WINDOWS.get(model, CONTEXT_WINDOWS["default"])


def _latest_session_records(records: list[UsageRecord]) -> tuple[list[UsageRecord], str]:
    """Get records for the most recent session today, plus its label."""
    today = datetime.now().date()
    today_records = [r for r in records if r.timestamp.astimezone().date() == today]
    if not today_records:
        return [], ""

    by_session: dict[str, list[UsageRecord]] = defaultdict(list)
    for r in today_records:
        by_session[r.session_id].append(r)

    # Most recent session by latest timestamp
    latest_sid = max(
        by_session.keys(),
        key=lambda sid: max(r.timestamp for r in by_session[sid]),
    )
    recs = sorted(by_session[latest_sid], key=lambda r: r.timestamp)
    label = next((r.slug for r in recs if r.slug), latest_sid[:8])
    return recs, label


class ContextGrid(Static):
    """Claude Code-style grid showing token usage as colored unicode symbols."""

    _record_count = reactive(0)

    def __init__(self, **kwargs) -> None:
        super().__init__(markup=False, **kwargs)
        self._records: list[UsageRecord] = []

    def update_records(self, records: list[UsageRecord]) -> None:
        self._records = records
        self._record_count = len(records)

    def _build_grid(
        self, cols: int = 20, rows: int = 10
    ) -> tuple[list[list[dict]], list[dict], str, str, int]:
        """Build the grid data structure.

        Returns (grid_rows, legend_entries, session_label, model_name, context_window).
        """
        recs, label = _latest_session_records(self._records)
        if not recs:
            return [], [], "", "", 0

        latest = recs[-1]
        model = latest.model
        context_window = _get_context_window(model)
        model_short = model.replace("claude-", "").split("-20")[0]

        # Sum tokens across all turns in this session (cumulative = last turn's input)
        # The last record's input_tokens is the current context size
        total_input = latest.input_tokens
        total_output = sum(r.output_tokens for r in recs)
        total_cache_read = latest.cache_read_input_tokens
        total_cache_create = latest.cache_creation_input_tokens

        cat_tokens = [
            ("input", "bright_blue", total_input),
            ("output", "bright_green", total_output),
            ("cache_read", "bright_yellow", total_cache_read),
            ("cache_create", "bright_magenta", total_cache_create),
        ]

        total_used = sum(t for _, _, t in cat_tokens)
        free_tokens = max(0, context_window - total_used)
        total_squares = cols * rows

        # Allocate squares proportionally (min 1 per active category)
        legend: list[dict] = []
        squares: list[dict] = []

        for name, color, tokens in cat_tokens:
            if tokens == 0:
                legend.append({"name": name, "color": color, "tokens": 0, "pct": 0.0, "squares": 0})
                continue
            raw = tokens / context_window * total_squares
            n_squares = max(1, round(raw))
            pct = tokens / context_window * 100
            legend.append({"name": name, "color": color, "tokens": tokens, "pct": pct, "squares": n_squares})

            # Build individual square objects with fullness
            full_squares = int(raw)
            frac = raw - full_squares
            for i in range(n_squares):
                fullness = 1.0
                if i == full_squares and frac > 0:
                    fullness = frac
                squares.append({"color": color, "name": name, "fullness": fullness})

        # Pad with free space
        free_pct = free_tokens / context_window * 100
        legend.append({"name": "free", "color": FREE_COLOR, "tokens": free_tokens, "pct": free_pct, "squares": 0})

        while len(squares) < total_squares:
            squares.append({"color": FREE_COLOR, "name": "free", "fullness": 1.0})

        # Trim if over-allocated
        squares = squares[:total_squares]

        # Chunk into rows
        grid_rows = [squares[i * cols : (i + 1) * cols] for i in range(rows)]
        return grid_rows, legend, label, model_short, context_window

    def render(self) -> Text:
        cols, rows = 20, 8
        grid_rows, legend, label, model_short, ctx_window = self._build_grid(cols, rows)

        text = Text()
        text.append("Context Grid", style="bold")
        if label:
            text.append(f"  {label}", style="dim")
        text.append("\n")

        if not grid_rows:
            text.append("no session data yet", style="dim")
            return text

        text.append(f"{model_short} ", style="dim")
        text.append(f"· {format_tokens(ctx_window)} window\n\n", style="dim")

        # Render grid
        for row in grid_rows:
            for cell in row:
                if cell["name"] == "free":
                    text.append(SYM_FREE, style="dim bright_black")
                elif cell["fullness"] >= 0.7:
                    text.append(SYM_FULL, style=cell["color"])
                else:
                    text.append(SYM_PARTIAL, style=cell["color"])
            text.append("\n")

        text.append("\n")

        # Legend
        for entry in legend:
            if entry["tokens"] == 0 and entry["name"] != "free":
                continue
            sym = SYM_FREE.strip() if entry["name"] == "free" else SYM_FULL.strip()
            text.append(sym, style=entry["color"] if entry["name"] != "free" else "dim")
            text.append(f" {entry['name']}: ", style="default")
            tok_str = format_tokens(entry["tokens"])
            pct_str = f"{entry['pct']:.1f}%"
            text.append(f"{tok_str} ({pct_str})", style="dim")
            text.append("\n")

        return text

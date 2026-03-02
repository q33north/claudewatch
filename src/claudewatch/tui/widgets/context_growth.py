"""Per-session context growth sparklines widget."""

from __future__ import annotations

from collections import defaultdict

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from claudewatch.models import UsageRecord
from claudewatch.tui.widgets.timeline import (
    SPARK_WIDTH_RIGHT,
    format_tokens,
    sparkline,
)


class ContextGrowth(Static):
    """Per-session context growth sparklines showing input_tokens over turns."""

    _record_count = reactive(0)

    def __init__(self, **kwargs) -> None:
        super().__init__(markup=True, **kwargs)
        self._records: list[UsageRecord] = []

    def update_records(self, records: list[UsageRecord]) -> None:
        self._records = records
        self._record_count = len(records)

    def _session_sparklines(self, top_n: int = 5) -> list[tuple[str, str, str]]:
        """Generate context growth sparklines for the most recent sessions.

        Returns (label, sparkline_str, peak_str) tuples.
        """
        by_session: dict[str, list[UsageRecord]] = defaultdict(list)
        for r in self._records:
            by_session[r.session_id].append(r)

        session_order = sorted(
            by_session.keys(),
            key=lambda sid: max(r.timestamp for r in by_session[sid]),
            reverse=True,
        )

        results = []
        for sid in session_order[:top_n]:
            recs = sorted(by_session[sid], key=lambda r: r.timestamp)
            values = [r.input_tokens for r in recs]
            if len(values) < 2:
                continue
            label = next((r.slug for r in recs if r.slug), sid[:8])
            spark = sparkline(values, width=SPARK_WIDTH_RIGHT)
            peak = format_tokens(max(values))
            results.append((label, spark, peak))
        return results

    def render(self) -> Text:
        lines = [
            "[bold]Context Growth[/]",
            "[dim]input tokens/turn (rising = filling window)[/]",
            "",
        ]

        sparks = self._session_sparklines(top_n=5)
        if sparks:
            for label, spark, peak in sparks:
                display_label = label[:12].ljust(12)
                lines.append(f"{display_label} {spark}")
                axis = "0" + " " * (SPARK_WIDTH_RIGHT - len(peak) - 1) + peak
                lines.append(f"             [dim]{axis}[/]")
        else:
            lines.append("[dim]not enough session data yet[/]")

        return Text.from_markup("\n".join(lines))

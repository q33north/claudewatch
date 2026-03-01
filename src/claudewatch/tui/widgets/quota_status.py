"""Quota tracking and prediction widget."""

from __future__ import annotations

from datetime import datetime, timezone

from textual.reactive import reactive
from textual.widgets import Static

from claudewatch.models import QuotaEvent, UsageRecord
from claudewatch.quota.detector import QuotaTracker


class QuotaStatus(Static):
    """Displays quota window tracking, last hit, and ceiling estimate."""

    _data_version = reactive(0)

    def __init__(self, **kwargs) -> None:
        super().__init__(markup=True, **kwargs)
        self._tracker = QuotaTracker()
        self._records: list[UsageRecord] = []

    def update_data(
        self, records: list[UsageRecord], events: list[QuotaEvent]
    ) -> None:
        self._records = records
        self._tracker.events = events
        self._data_version += 1

    def render(self) -> str:
        window = self._tracker.estimate_window_usage(self._records)
        ceiling = self._tracker.estimate_ceiling()
        last_hit = self._tracker.last_hit
        since = self._tracker.time_since_last_hit()

        lines = ["[bold]Quota Status[/]\n"]

        # Current window usage
        lines.append(f"  5h window tokens: {window['total']:>12,}")
        lines.append(f"  Window messages:  {window['record_count']:>12,}")

        # Last quota hit
        if last_hit:
            since_str = (
                f"{since.total_seconds() / 3600:.1f}h ago" if since else "unknown"
            )
            lines.append(f"\n  Last hit: {last_hit.event_type} ({since_str})")

            # Ceiling estimate
            if ceiling["output_ceiling"]:
                lines.append(
                    f"  Est. output ceiling: {ceiling['output_ceiling']:,}"
                )
        else:
            lines.append("\n  No quota hits recorded yet")
            lines.append("  (this is good!)")

        return "\n".join(lines)

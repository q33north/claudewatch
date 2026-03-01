"""Usage timeline with sparkline visualizations."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from textual.reactive import reactive
from textual.widgets import Static

from claudewatch.models import UsageRecord

SPARK_CHARS = " ▁▂▃▄▅▆▇█"


def sparkline(values: list[int], width: int | None = None) -> str:
    """Generate a sparkline string from a list of values."""
    if not values:
        return ""
    if width and len(values) > width:
        values = values[-width:]
    max_val = max(values) if max(values) > 0 else 1
    return "".join(
        SPARK_CHARS[min(int(v / max_val * (len(SPARK_CHARS) - 1)), len(SPARK_CHARS) - 1)]
        for v in values
    )


class Timeline(Static):
    """Hourly and daily sparkline visualizations of token usage."""

    _record_count = reactive(0)

    def __init__(self, **kwargs) -> None:
        super().__init__(markup=True, **kwargs)
        self._records: list[UsageRecord] = []

    def update_records(self, records: list[UsageRecord]) -> None:
        self._records = records
        self._record_count = len(records)

    def render(self) -> str:
        if not self._records:
            return "Timeline\n\nNo data yet"

        now = datetime.now(timezone.utc)

        # Hourly: last 24 hours (in local time)
        hourly: dict[int, int] = defaultdict(int)
        day_start = now - timedelta(hours=24)
        for r in self._records:
            if r.timestamp >= day_start:
                local_hour = r.timestamp.astimezone().hour
                hourly[local_hour] = hourly.get(local_hour, 0) + r.total_tokens

        hourly_vals = [hourly.get(h, 0) for h in range(24)]
        hour_spark = sparkline(hourly_vals)
        # peak hour stats
        peak_hour = max(range(24), key=lambda h: hourly.get(h, 0))
        hour_total = sum(hourly_vals)

        # Daily: last 30 days
        daily: dict[str, int] = defaultdict(int)
        month_start = now - timedelta(days=30)
        for r in self._records:
            if r.timestamp >= month_start:
                day_key = r.timestamp.date().isoformat()
                daily[day_key] += r.total_tokens

        day_range = [
            (month_start + timedelta(days=i)).date().isoformat() for i in range(31)
        ]
        daily_vals = [daily.get(d, 0) for d in day_range]
        day_spark = sparkline(daily_vals)
        # date labels for 30d
        start_label = (now - timedelta(days=30)).strftime("%m/%d")
        end_label = now.strftime("%m/%d")

        return (
            f"[bold]Timeline[/]\n\n"
            f"  24h: {hour_spark}  peak: {peak_hour}:00\n"
            f"       12am              12pm              now\n\n"
            f"  30d: {day_spark}\n"
            f"       {start_label}                         {end_label}"
        )

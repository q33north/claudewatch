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


def format_tokens(n: int) -> str:
    """Format token count compactly: 1.2M, 450K, 800."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


class Timeline(Static):
    """Hourly and daily sparkline visualizations of token usage."""

    _record_count = reactive(0)

    def __init__(self, **kwargs) -> None:
        super().__init__(markup=True, **kwargs)
        self._records: list[UsageRecord] = []

    def update_records(self, records: list[UsageRecord]) -> None:
        self._records = records
        self._record_count = len(records)

    def _bucket_24h(self) -> tuple[list[int], list[int]]:
        """Bucket records into 24 rolling hour slots (0 = 24h ago, 23 = now).

        Returns (input_vals, output_vals) lists of length 24.
        """
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)
        input_buckets: dict[int, int] = defaultdict(int)
        output_buckets: dict[int, int] = defaultdict(int)

        for r in self._records:
            if r.timestamp >= start:
                # Hours ago from now, inverted so 0 = oldest, 23 = most recent
                hours_ago = (now - r.timestamp).total_seconds() / 3600
                slot = 23 - min(int(hours_ago), 23)
                input_buckets[slot] += r.input_tokens + r.cache_read_input_tokens
                output_buckets[slot] += r.output_tokens

        input_vals = [input_buckets.get(i, 0) for i in range(24)]
        output_vals = [output_buckets.get(i, 0) for i in range(24)]
        return input_vals, output_vals

    def _bucket_30d(self) -> tuple[list[int], list[int]]:
        """Bucket records into 31 daily slots.

        Returns (input_vals, output_vals) lists of length 31.
        """
        now = datetime.now(timezone.utc)
        month_start = now - timedelta(days=30)
        input_daily: dict[str, int] = defaultdict(int)
        output_daily: dict[str, int] = defaultdict(int)

        for r in self._records:
            if r.timestamp >= month_start:
                day_key = r.timestamp.date().isoformat()
                input_daily[day_key] += r.input_tokens + r.cache_read_input_tokens
                output_daily[day_key] += r.output_tokens

        day_range = [
            (month_start + timedelta(days=i)).date().isoformat() for i in range(31)
        ]
        input_vals = [input_daily.get(d, 0) for d in day_range]
        output_vals = [output_daily.get(d, 0) for d in day_range]
        return input_vals, output_vals

    def _burn_rate(self, window_hours: int = 3) -> tuple[float, float]:
        """Calculate tokens/hr over the last `window_hours`.

        Returns (input_per_hr, output_per_hr).
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=window_hours)
        recent = [r for r in self._records if r.timestamp >= cutoff]
        if not recent:
            return 0.0, 0.0
        # Use actual time span if less than window
        earliest = min(r.timestamp for r in recent)
        span_hours = max((now - earliest).total_seconds() / 3600, 0.1)
        total_in = sum(r.input_tokens + r.cache_read_input_tokens for r in recent)
        total_out = sum(r.output_tokens for r in recent)
        return total_in / span_hours, total_out / span_hours

    def render(self) -> str:
        if not self._records:
            return "[bold]Timeline[/]\n\nNo data yet"

        now = datetime.now(timezone.utc)

        # 24h sparklines (rolling hours-ago buckets)
        h_in, h_out = self._bucket_24h()
        h_in_spark = sparkline(h_in)
        h_out_spark = sparkline(h_out)
        h_in_max = max(h_in) if h_in else 0
        h_out_max = max(h_out) if h_out else 0

        # 30d sparklines
        d_in, d_out = self._bucket_30d()
        d_in_spark = sparkline(d_in)
        d_out_spark = sparkline(d_out)
        d_in_max = max(d_in) if d_in else 0
        d_out_max = max(d_out) if d_out else 0

        start_label = (now - timedelta(days=30)).strftime("%m/%d")
        end_label = now.strftime("%m/%d")

        # Burn rate
        in_rate, out_rate = self._burn_rate(window_hours=3)

        return (
            f"[bold]Timeline[/]"
            f"                                              "
            f"[dim]burn rate (3h):[/] "
            f"[green]{format_tokens(int(in_rate))}[/]"
            f"[dim] in/hr[/]  "
            f"[yellow]{format_tokens(int(out_rate))}[/]"
            f"[dim] out/hr[/]\n\n"
            f"  24h [green]in [/] {h_in_spark}  [dim]peak {format_tokens(h_in_max)}[/]\n"
            f"      [yellow]out[/] {h_out_spark}  [dim]peak {format_tokens(h_out_max)}[/]\n"
            f"       [dim]-24h                          now[/]\n\n"
            f"  30d [green]in [/] {d_in_spark}  [dim]peak {format_tokens(d_in_max)}[/]\n"
            f"      [yellow]out[/] {d_out_spark}  [dim]peak {format_tokens(d_out_max)}[/]\n"
            f"       [dim]{start_label}                        {end_label}[/]"
        )

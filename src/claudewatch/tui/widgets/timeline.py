"""Usage timeline with sparkline visualizations."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from rich.text import Text
from rich.table import Table

from textual.reactive import reactive
from textual.widgets import Static

from claudewatch.models import UsageRecord

SPARK_CHARS = " ▁▂▃▄▅▆▇█"

# Sparkline width for the left column (24h/30d).
# Right column (context growth) uses a narrower width.
SPARK_WIDTH_LEFT = 40
SPARK_WIDTH_RIGHT = 30


def _resample(values: list[int], target: int) -> list[int]:
    """Resample a list of values to a target length via nearest-neighbor."""
    n = len(values)
    if n == 0 or n == target:
        return values
    return [values[int(i * n / target)] for i in range(target)]


def sparkline(values: list[int], width: int = SPARK_WIDTH_LEFT) -> str:
    """Generate a sparkline string from a list of values, resampled to width."""
    if not values:
        return ""
    values = _resample(values, width)
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

    def _session_context_sparklines(self, top_n: int = 3) -> list[tuple[str, str, str]]:
        """Generate context growth sparklines for the most recent sessions.

        Groups records by session_id, takes the top_n most recent sessions,
        and plots input_tokens values as sparklines (these grow as context accumulates).

        Returns (label, sparkline_str, peak_str) tuples.
        """
        by_session: dict[str, list[UsageRecord]] = defaultdict(list)
        for r in self._records:
            by_session[r.session_id].append(r)

        # Sort sessions by most recent record, take top_n
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
            label = next(
                (r.slug for r in recs if r.slug), sid[:8]
            )
            spark = sparkline(values, width=SPARK_WIDTH_RIGHT)
            peak = format_tokens(max(values))
            results.append((label, spark, peak))
        return results

    def _build_axis(self, width: int, count: int, label_fn, interval: int, force_last: bool = False) -> str:
        """Build an x-axis string with labels at regular intervals, aligned to width."""
        chars = [" "] * width
        for i in range(count):
            if i % interval == 0 or (force_last and i == count - 1):
                pos = int(i * width / count)
                label = label_fn(i)
                for j, ch in enumerate(label):
                    if pos + j < width:
                        chars[pos + j] = ch
        return "".join(chars)

    def render(self) -> Table:
        if not self._records:
            return Text.from_markup("[bold]Timeline[/]\n\nNo data yet")

        now = datetime.now(timezone.utc)

        # 24h sparklines
        h_in, h_out = self._bucket_24h()
        h_in_spark = sparkline(h_in, width=SPARK_WIDTH_LEFT)
        h_out_spark = sparkline(h_out, width=SPARK_WIDTH_LEFT)
        h_in_max = max(h_in) if h_in else 0
        h_out_max = max(h_out) if h_out else 0

        # 30d sparklines
        d_in, d_out = self._bucket_30d()
        d_in_spark = sparkline(d_in, width=SPARK_WIDTH_LEFT)
        d_out_spark = sparkline(d_out, width=SPARK_WIDTH_LEFT)
        d_in_max = max(d_in) if d_in else 0
        d_out_max = max(d_out) if d_out else 0

        # Burn rate
        in_rate, out_rate = self._burn_rate(window_hours=3)

        # X-axes
        h_start = now - timedelta(hours=23)
        h_axis = self._build_axis(
            SPARK_WIDTH_LEFT, 24, interval=6,
            label_fn=lambda i: (h_start + timedelta(hours=i)).astimezone().strftime("%H"),
        )
        d_start = now - timedelta(days=30)
        d_axis = self._build_axis(
            SPARK_WIDTH_LEFT, 31, interval=7, force_last=True,
            label_fn=lambda i: (d_start + timedelta(days=i)).strftime("%m/%d"),
        )

        # Left column: 24h + 30d sparklines
        left = (
            f"[bold]24h[/]"
            f"     [dim]burn rate (3h):[/] "
            f"[green]{format_tokens(int(in_rate))}[/]"
            f"[dim] in/hr[/]  "
            f"[yellow]{format_tokens(int(out_rate))}[/]"
            f"[dim] out/hr[/]\n"
            f"  [green]in [/] {h_in_spark}  [dim]pk {format_tokens(h_in_max)}[/]\n"
            f"  [yellow]out[/] {h_out_spark}  [dim]pk {format_tokens(h_out_max)}[/]\n"
            f"   [dim]{h_axis}[/]\n\n"
            f"[bold]30d[/]\n"
            f"  [green]in [/] {d_in_spark}  [dim]pk {format_tokens(d_in_max)}[/]\n"
            f"  [yellow]out[/] {d_out_spark}  [dim]pk {format_tokens(d_out_max)}[/]\n"
            f"   [dim]{d_axis}[/]"
        )

        # Right column: context growth sparklines
        ctx_sparks = self._session_context_sparklines(top_n=5)
        if ctx_sparks:
            right_lines = [
                "[bold]Context growth[/]",
                "[dim]input tokens/turn (rising = filling window)[/]",
                "",
            ]
            for label, spark, peak in ctx_sparks:
                display_label = label[:12].ljust(12)
                right_lines.append(f"{display_label} {spark}")
                right_lines.append(f"             [dim]peak {peak}[/]")
            right = "\n".join(right_lines)
        else:
            right = "[bold]Context growth[/]\n\n[dim]not enough session data yet[/]"

        # Two-column layout using Rich Table
        table = Table.grid(expand=True, padding=(0, 2))
        table.add_column(ratio=3)
        table.add_column(ratio=2)
        table.add_row(
            Text.from_markup(left),
            Text.from_markup(right),
        )
        return table

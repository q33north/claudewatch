"""Context health widget - memory sizes, cache ratio, autocompacts, quota essentials."""

from __future__ import annotations

from datetime import datetime, timezone

from textual.reactive import reactive
from textual.widgets import Static

from claudewatch.config import (
    estimate_file_tokens,
    find_autocompact_files,
    find_memory_files_grouped,
)
from claudewatch.models import QuotaEvent, UsageRecord
from claudewatch.quota.detector import QuotaTracker

CACHE_BAR_WIDTH = 10


def _cache_bar(ratio: float) -> str:
    """Render a 10-char bar for cache hit ratio with color coding."""
    filled = int(ratio * CACHE_BAR_WIDTH)
    bar = "█" * filled + "░" * (CACHE_BAR_WIDTH - filled)
    pct = f"{ratio * 100:.0f}%"
    if ratio >= 0.8:
        return f"[green]{bar}[/] {pct}"
    if ratio >= 0.5:
        return f"[yellow]{bar}[/] {pct}"
    return f"[red]{bar}[/] {pct}"


def _active_session_info(records: list[UsageRecord]) -> tuple[str, str, str]:
    """Infer the most recent active session from today's records.

    Returns (session_label, project, model) or empty strings if no data.
    """
    today = datetime.now().date()
    today_records = [
        r for r in records
        if r.timestamp.astimezone().date() == today
    ]
    if not today_records:
        return "", "", ""
    latest = max(today_records, key=lambda r: r.timestamp)
    label = latest.slug or latest.session_id[:8]
    return label, latest.project, latest.model.replace("claude-", "").split("-20")[0]


class ContextHealth(Static):
    """Displays memory file sizes, cache hit ratio, autocompact events, and quota essentials."""

    _data_version = reactive(0)

    def __init__(self, **kwargs) -> None:
        super().__init__(markup=True, **kwargs)
        self._records: list[UsageRecord] = []
        self._tracker = QuotaTracker()

    def update_data(
        self, records: list[UsageRecord], events: list[QuotaEvent]
    ) -> None:
        self._records = records
        self._tracker.events = events
        self._data_version += 1

    def _today_cache_ratio(self) -> float:
        """Aggregate cache hit ratio for today's records."""
        today = datetime.now().date()
        today_records = [
            r for r in self._records
            if r.timestamp.astimezone().date() == today
        ]
        if not today_records:
            return 0.0
        total_read = sum(r.cache_read_input_tokens for r in today_records)
        total_create = sum(r.cache_creation_input_tokens for r in today_records)
        total = total_read + total_create
        if total == 0:
            return 0.0
        return total_read / total

    def render(self) -> str:
        lines = ["[bold]Context Health[/]  [dim](all projects)[/]\n"]

        # Active session info
        sess_label, sess_project, sess_model = _active_session_info(self._records)
        if sess_label:
            lines.append(
                f"  latest: [bold]{sess_label}[/]"
                f"  [dim]{sess_project} / {sess_model}[/]"
            )
            lines.append("")

        # Memory file sizes, grouped by project
        groups = find_memory_files_grouped()
        if groups:
            grand_total = 0
            for project, files in sorted(groups.items()):
                project_tokens = 0
                file_lines: list[str] = []
                for label, path in files:
                    tokens = estimate_file_tokens(path)
                    project_tokens += tokens
                    try:
                        kb = path.stat().st_size / 1024
                    except OSError:
                        kb = 0.0
                    file_lines.append(f"    {label}: ~{tokens:,} tok ({kb:.1f}KB)")
                lines.append(f"  [bold]{project}[/]  [dim]~{project_tokens:,} tok[/]")
                lines.extend(file_lines)
                grand_total += project_tokens
            lines.append(f"  [bold]total: ~{grand_total:,} tokens[/]")
        else:
            lines.append("  no memory files found")

        # Cache hit ratio (today)
        lines.append("")
        ratio = self._today_cache_ratio()
        lines.append(f"  cache ratio: {_cache_bar(ratio)}")

        # Autocompact events
        compacts = find_autocompact_files()
        if compacts:
            lines.append(f"\n  autocompacts: {len(compacts)} total")
            for c in compacts[:3]:
                lines.append(f"    {c['project']} ({c['date']})")

        # Quota essentials (compact)
        last_hit = self._tracker.last_hit
        if last_hit:
            since = self._tracker.time_since_last_hit()
            since_str = (
                f"{since.total_seconds() / 3600:.1f}h ago" if since else "?"
            )
            lines.append(f"\n  last quota: {last_hit.event_type} ({since_str})")

        return "\n".join(lines)

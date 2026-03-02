"""Session list widget with sortable DataTable."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from textual.widgets import DataTable

from claudewatch.models import UsageRecord, SessionSummary


def aggregate_sessions(records: list[UsageRecord]) -> list[SessionSummary]:
    """Aggregate usage records into session summaries."""
    by_session: dict[str, list[UsageRecord]] = defaultdict(list)
    for r in records:
        by_session[r.session_id].append(r)

    summaries = []
    for session_id, session_records in by_session.items():
        if not session_records:
            continue
        sorted_recs = sorted(session_records, key=lambda r: r.timestamp)
        # Use first non-empty slug from the session
        slug = next((r.slug for r in sorted_recs if r.slug), "")
        summaries.append(
            SessionSummary(
                session_id=session_id,
                project=sorted_recs[0].project,
                model=sorted_recs[0].model,
                start_time=sorted_recs[0].timestamp,
                end_time=sorted_recs[-1].timestamp,
                total_input=sum(r.input_tokens for r in sorted_recs),
                total_output=sum(r.output_tokens for r in sorted_recs),
                total_cache_read=sum(r.cache_read_input_tokens for r in sorted_recs),
                total_cache_create=sum(r.cache_creation_input_tokens for r in sorted_recs),
                message_count=len(sorted_recs),
                slug=slug,
            )
        )
    return sorted(summaries, key=lambda s: s.end_time, reverse=True)


class SessionList(DataTable):
    """Sortable table of recent sessions."""

    DEFAULT_CSS = """
    SessionList {
        height: 1fr;
    }
    """

    def on_mount(self) -> None:
        self.add_columns("Session", "Project", "Model", "Messages", "Tokens", "Duration", "Time")
        self.cursor_type = "row"
        self.zebra_stripes = True

    def update_records(self, records: list[UsageRecord]) -> None:
        """Rebuild the table from usage records."""
        self.clear()
        summaries = aggregate_sessions(records)

        for s in summaries[:50]:  # cap at 50 rows for performance
            session_label = s.slug or s.session_id[:8]
            model_short = s.model.replace("claude-", "").split("-20")[0]
            tokens = f"{s.total_tokens:,}"
            dur = f"{s.duration_minutes:.0f}m" if s.duration_minutes > 0 else "<1m"
            time_str = s.end_time.strftime("%m/%d %H:%M")
            self.add_row(session_label, s.project, model_short, str(s.message_count), tokens, dur, time_str)

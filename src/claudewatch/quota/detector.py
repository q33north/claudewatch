"""Quota detection and window tracking.

Analyzes quota events to estimate token limits per billing window.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from claudewatch.models import QuotaEvent, UsageRecord
from claudewatch.storage.jsonl import read_quota_events, read_usage


class QuotaTracker:
    """Track quota events and estimate usage ceilings."""

    def __init__(self) -> None:
        self.events: list[QuotaEvent] = []
        self.window_hours: float = 5.0  # default 5-hour rolling window

    def load(self) -> None:
        """Load quota events from storage."""
        self.events = read_quota_events()

    @property
    def last_hit(self) -> QuotaEvent | None:
        """Most recent quota event."""
        if not self.events:
            return None
        return max(self.events, key=lambda e: e.timestamp)

    def time_since_last_hit(self) -> timedelta | None:
        """Time elapsed since the last quota hit."""
        hit = self.last_hit
        if hit is None:
            return None
        return datetime.now(timezone.utc) - hit.timestamp

    def estimate_window_usage(self, records: list[UsageRecord]) -> dict[str, int]:
        """Estimate token usage in the current billing window."""
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(hours=self.window_hours)

        window_records = [r for r in records if r.timestamp >= window_start]
        return {
            "input": sum(r.input_tokens for r in window_records),
            "output": sum(r.output_tokens for r in window_records),
            "cache_read": sum(r.cache_read_input_tokens for r in window_records),
            "cache_create": sum(r.cache_creation_input_tokens for r in window_records),
            "total": sum(r.total_tokens for r in window_records),
            "record_count": len(window_records),
        }

    def estimate_ceiling(self) -> dict[str, int | None]:
        """Estimate the approximate token ceiling based on quota-hit events.

        Returns the cumulative tokens at the most recent quota hit as a rough ceiling.
        """
        hit = self.last_hit
        if hit is None:
            return {"input_ceiling": None, "output_ceiling": None}
        return {
            "input_ceiling": hit.cumulative_input,
            "output_ceiling": hit.cumulative_output,
        }

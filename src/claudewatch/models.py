"""Pydantic v2 models for claudewatch data."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


def _default_machine_id() -> str:
    """Return a stable machine identifier (hostname)."""
    import socket
    return socket.gethostname()


class UsageRecord(BaseModel):
    """Single usage record extracted from a Claude Code assistant message."""

    timestamp: datetime
    session_id: str
    model: str = "unknown"
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    project: str = "unknown"
    service_tier: str = "standard"
    speed: str = "standard"
    user_id: str = "default"
    slug: str = ""
    machine_id: str = Field(default_factory=_default_machine_id)

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_input_tokens
            + self.cache_creation_input_tokens
        )

    @property
    def cost_estimate(self) -> float:
        """Rough cost estimate in USD using Opus 4.6 pricing as default."""
        from claudewatch.config import MODEL_PRICING

        pricing = MODEL_PRICING.get(self.model, MODEL_PRICING["default"])
        return (
            self.input_tokens * pricing["input"]
            + self.output_tokens * pricing["output"]
            + self.cache_read_input_tokens * pricing["cache_read"]
            + self.cache_creation_input_tokens * pricing["cache_create"]
        ) / 1_000_000

    @property
    def cache_hit_ratio(self) -> float:
        """Ratio of cache reads to total cache tokens (0.0 if no cache activity)."""
        total_cache = self.cache_read_input_tokens + self.cache_creation_input_tokens
        if total_cache == 0:
            return 0.0
        return self.cache_read_input_tokens / total_cache


class QuotaEvent(BaseModel):
    """A detected quota-related event (rate limit, slowdown, quota hit)."""

    timestamp: datetime
    event_type: str  # "quota_hit", "rate_limit", "slowdown"
    cumulative_input: int = 0
    cumulative_output: int = 0
    message: str = ""
    user_id: str = "default"
    machine_id: str = Field(default_factory=_default_machine_id)


class SessionSummary(BaseModel):
    """Aggregated summary of a single Claude Code session."""

    session_id: str
    project: str = "unknown"
    model: str = "unknown"
    start_time: datetime
    end_time: datetime
    total_input: int = 0
    total_output: int = 0
    total_cache_read: int = 0
    total_cache_create: int = 0
    message_count: int = 0
    slug: str = ""

    @property
    def total_tokens(self) -> int:
        return (
            self.total_input
            + self.total_output
            + self.total_cache_read
            + self.total_cache_create
        )

    @property
    def duration_minutes(self) -> float:
        return (self.end_time - self.start_time).total_seconds() / 60

    @property
    def cache_hit_ratio(self) -> float:
        """Ratio of cache reads to total cache tokens (0.0 if no cache activity)."""
        total_cache = self.total_cache_read + self.total_cache_create
        if total_cache == 0:
            return 0.0
        return self.total_cache_read / total_cache


class HookInput(BaseModel):
    """JSON payload received on stdin by Stop and PostToolUse hooks."""

    session_id: str
    transcript_path: str
    cwd: str = ""
    stop_hook_active: bool = False
    hook_event_name: str = ""
    tool_name: str = ""

"""Configuration, paths, and pricing defaults for claudewatch."""

from __future__ import annotations

from pathlib import Path

# Storage paths
CLAUDE_DIR = Path.home() / ".claude"
CLAUDEWATCH_DIR = CLAUDE_DIR / "claudewatch"
USAGE_JSONL = CLAUDEWATCH_DIR / "usage.jsonl"
QUOTA_EVENTS_JSONL = CLAUDEWATCH_DIR / "quota-events.jsonl"
HOOKS_DIR = CLAUDE_DIR / "hooks"
HOOK_SCRIPT = HOOKS_DIR / "claudewatch-stop.sh"
SETTINGS_JSON = CLAUDE_DIR / "settings.json"
PROJECTS_DIR = CLAUDE_DIR / "projects"

# Per-million-token pricing (USD) as of Feb 2026
# https://docs.anthropic.com/en/docs/about-claude/pricing
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.5,
        "cache_create": 18.75,
    },
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.3,
        "cache_create": 3.75,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80,
        "output": 4.0,
        "cache_read": 0.08,
        "cache_create": 1.0,
    },
    "default": {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.5,
        "cache_create": 18.75,
    },
}

# Quota detection patterns (found in assistant message content)
QUOTA_PATTERNS: list[dict[str, str]] = [
    {"pattern": "hit your limit", "event_type": "quota_hit"},
    {"pattern": "overloaded_error", "event_type": "rate_limit"},
    {"pattern": "rate_limit", "event_type": "rate_limit"},
    {"pattern": "slower responses", "event_type": "slowdown"},
    {"pattern": "capacity constraints", "event_type": "slowdown"},
]

# Tail-read settings
TAIL_CHUNK_SIZE = 8192  # 8KB chunks for backwards reading

# Hook recursion guard
HOOK_ACTIVE_ENV = "CLAUDEWATCH_HOOK_ACTIVE"


def ensure_dirs() -> None:
    """Create storage directories if they don't exist."""
    CLAUDEWATCH_DIR.mkdir(parents=True, exist_ok=True)


def decode_project_dir(dirname: str) -> str:
    """Decode a Claude project directory name to a human-readable project name.

    e.g. '-home-pabsju-Q33North' -> 'Q33North'
    """
    parts = dirname.strip("-").split("-")
    # Take last meaningful segment
    if parts:
        return parts[-1]
    return dirname


def project_from_cwd(cwd: str) -> str:
    """Extract a short project name from a working directory path."""
    p = Path(cwd)
    return p.name if p.name else "unknown"

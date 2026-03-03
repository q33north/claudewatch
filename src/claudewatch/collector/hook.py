"""Hook logic: tail-read transcript, extract usage, append to storage.

Runs on both Stop and PostToolUse hooks for live monitoring.
Performance target: <50ms, zero LLM calls.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from claudewatch.config import (
    QUOTA_PATTERNS,
    TAIL_CHUNK_SIZE,
    project_from_cwd,
)
from claudewatch.models import HookInput, QuotaEvent, UsageRecord
from claudewatch.storage.jsonl import append_quota_event, append_usage, read_last_usage


def tail_read_last_assistant(transcript_path: str) -> dict | None:
    """Read the transcript JSONL backwards to find the last assistant message with usage.

    Uses 8KB chunk backward seeking for speed on large files.
    """
    path = Path(transcript_path)
    if not path.exists():
        return None

    file_size = path.stat().st_size
    if file_size == 0:
        return None

    # Read backwards in chunks, collecting complete lines
    buffer = b""
    with open(path, "rb") as f:
        pos = file_size
        while pos > 0:
            read_size = min(TAIL_CHUNK_SIZE, pos)
            pos -= read_size
            f.seek(pos)
            chunk = f.read(read_size)
            buffer = chunk + buffer

            # Try to find assistant messages with output_tokens in the buffer
            lines = buffer.split(b"\n")

            # Process from the end (most recent first)
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                if entry.get("type") != "assistant":
                    continue

                usage = entry.get("message", {}).get("usage", {})
                if usage.get("output_tokens", 0) > 0:
                    return entry

            # Keep the first (possibly incomplete) line for next iteration
            buffer = lines[0] if lines else b""

    return None


def extract_usage_record(entry: dict, cwd: str) -> UsageRecord:
    """Convert a raw JSONL assistant entry to a UsageRecord."""
    msg = entry.get("message", {})
    usage = msg.get("usage", {})
    timestamp_str = entry.get("timestamp", "")

    try:
        ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        ts = datetime.now(timezone.utc)

    return UsageRecord(
        timestamp=ts,
        session_id=entry.get("sessionId", "unknown"),
        model=msg.get("model", "unknown"),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cache_read_input_tokens=usage.get("cache_read_input_tokens", 0),
        cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
        project=project_from_cwd(cwd),
        service_tier=usage.get("service_tier", "standard"),
        speed=usage.get("speed", "standard"),
        slug=entry.get("slug", ""),
    )


def check_quota_patterns(entry: dict) -> str | None:
    """Check if the assistant message content contains quota-related patterns."""
    content_parts = entry.get("message", {}).get("content", [])
    text = ""
    for part in content_parts:
        if isinstance(part, dict) and part.get("type") == "text":
            text += part.get("text", "")
        elif isinstance(part, str):
            text += part

    text_lower = text.lower()
    for pattern_info in QUOTA_PATTERNS:
        if pattern_info["pattern"] in text_lower:
            return pattern_info["event_type"]
    return None


def _is_duplicate(record: UsageRecord) -> bool:
    """Check if this record is a duplicate of the last recorded entry.

    During agentic loops, multiple PostToolUse hooks may fire for the same
    assistant message (e.g., when Claude requests 3 tool calls at once).
    We dedup by comparing (session_id, timestamp, output_tokens).
    """
    last = read_last_usage()
    if last is None:
        return False
    return (
        last.session_id == record.session_id
        and last.timestamp == record.timestamp
        and last.output_tokens == record.output_tokens
    )


def run_hook() -> None:
    """Main hook entrypoint. Reads stdin JSON, processes transcript, writes storage."""
    try:
        raw = sys.stdin.read()
        hook_input = HookInput.model_validate_json(raw)
    except Exception:
        return

    if hook_input.stop_hook_active:
        return

    # Find last assistant message with usage
    entry = tail_read_last_assistant(hook_input.transcript_path)
    if entry is None:
        return

    cwd = hook_input.cwd or entry.get("cwd", "")
    record = extract_usage_record(entry, cwd)

    # Dedup: skip if we already recorded this exact entry
    if _is_duplicate(record):
        return

    append_usage(record)

    # Check for quota patterns (only worth doing on Stop, but harmless either way)
    quota_type = check_quota_patterns(entry)
    if quota_type:
        event = QuotaEvent(
            timestamp=record.timestamp,
            event_type=quota_type,
            cumulative_input=record.input_tokens,
            cumulative_output=record.output_tokens,
            message=f"Detected {quota_type} in session {record.session_id}",
        )
        append_quota_event(event)


if __name__ == "__main__":
    run_hook()

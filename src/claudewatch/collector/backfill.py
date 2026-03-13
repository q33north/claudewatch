"""Backfill historical usage data from Claude Code session JSONL files."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from claudewatch.config import PROJECTS_DIR, decode_project_dir
from claudewatch.models import UsageRecord
from claudewatch.storage.jsonl import append_usage, read_usage


def find_session_files(since: datetime | None = None) -> list[tuple[Path, str]]:
    """Find all session JSONL files under ~/.claude/projects/.

    Discovers both parent session transcripts ({uuid}.jsonl) and subagent
    transcripts ({uuid}/subagents/agent-*.jsonl). Subagent files contain
    their own token usage that is NOT included in the parent transcript.

    Returns list of (path, project_name) tuples.
    """
    if not PROJECTS_DIR.exists():
        return []

    files = []
    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        project_name = decode_project_dir(project_dir.name)

        # Parent session transcripts
        for jsonl_file in project_dir.glob("*.jsonl"):
            if since and jsonl_file.stat().st_mtime < since.timestamp():
                continue
            files.append((jsonl_file, project_name))

        # Subagent transcripts (spawned by the Agent tool)
        for jsonl_file in project_dir.glob("*/subagents/agent-*.jsonl"):
            if since and jsonl_file.stat().st_mtime < since.timestamp():
                continue
            files.append((jsonl_file, project_name))

    return files


def extract_records_from_session(
    path: Path, project: str
) -> list[UsageRecord]:
    """Extract all assistant usage records from a session or subagent JSONL file.

    Works identically for parent transcripts and subagent transcripts since
    the JSONL format is the same. Uses sessionId from each entry (falling back
    to the filename stem) so subagent records are correctly attributed to their
    parent session.
    """
    records = []
    fallback_session_id = path.stem

    with open(path, "rb") as f:
        for raw_line in f:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            if entry.get("type") != "assistant":
                continue

            msg = entry.get("message", {})
            usage = msg.get("usage", {})
            if usage.get("output_tokens", 0) == 0:
                continue

            timestamp_str = entry.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

            records.append(
                UsageRecord(
                    timestamp=ts,
                    session_id=entry.get("sessionId", fallback_session_id),
                    model=msg.get("model", "unknown"),
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    cache_read_input_tokens=usage.get("cache_read_input_tokens", 0),
                    cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
                    project=project,
                    service_tier=usage.get("service_tier", "standard"),
                    speed=usage.get("speed", "standard"),
                    slug=entry.get("slug", ""),
                )
            )
    return records


def backfill(since: datetime | None = None, target_path: Path | None = None) -> int:
    """Scan all historical session files and append usage records.

    Deduplicates by (session_id, timestamp) against existing records.
    Returns the number of new records written.
    """
    # Load existing records for dedup
    existing = read_usage() if target_path is None else []
    seen = {(r.session_id, r.timestamp.isoformat()) for r in existing}

    session_files = find_session_files(since=since)
    if not session_files:
        return 0

    new_count = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total} files"),
        TimeElapsedColumn(),
    ) as progress:
        task = progress.add_task("Scanning sessions...", total=len(session_files))

        for path, project in session_files:
            try:
                records = extract_records_from_session(path, project)
            except Exception:
                progress.advance(task)
                continue

            for record in records:
                key = (record.session_id, record.timestamp.isoformat())
                if key not in seen:
                    seen.add(key)
                    if target_path:
                        append_usage(record, path=target_path)
                    else:
                        append_usage(record)
                    new_count += 1

            progress.advance(task)

    return new_count

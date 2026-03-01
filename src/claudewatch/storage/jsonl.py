"""Append-only JSONL storage with file watching for live updates."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from claudewatch.config import USAGE_JSONL, QUOTA_EVENTS_JSONL, ensure_dirs
from claudewatch.models import UsageRecord, QuotaEvent

if TYPE_CHECKING:
    from collections.abc import Iterator


def append_usage(record: UsageRecord, path: Path = USAGE_JSONL) -> None:
    """Append a usage record to the JSONL file using O_APPEND for atomicity."""
    ensure_dirs()
    line = record.model_dump_json() + "\n"
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode())
    finally:
        os.close(fd)


def append_quota_event(event: QuotaEvent, path: Path = QUOTA_EVENTS_JSONL) -> None:
    """Append a quota event to the quota events JSONL file."""
    ensure_dirs()
    line = event.model_dump_json() + "\n"
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode())
    finally:
        os.close(fd)


def read_usage(path: Path = USAGE_JSONL) -> list[UsageRecord]:
    """Read all usage records from the JSONL file."""
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(UsageRecord.model_validate_json(line))
    return records


def read_quota_events(path: Path = QUOTA_EVENTS_JSONL) -> list[QuotaEvent]:
    """Read all quota events from the JSONL file."""
    if not path.exists():
        return []
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(QuotaEvent.model_validate_json(line))
    return events


def tail_read_new_lines(path: Path, offset: int) -> tuple[list[str], int]:
    """Read new lines from a file starting at the given byte offset.

    Returns (new_lines, new_offset).
    """
    if not path.exists():
        return [], 0
    with open(path, "rb") as f:
        f.seek(0, 2)  # end
        size = f.tell()
        if size <= offset:
            return [], offset
        f.seek(offset)
        data = f.read()
        new_offset = offset + len(data)
    lines = [l for l in data.decode("utf-8", errors="replace").splitlines() if l.strip()]
    return lines, new_offset


def iter_usage_from_offset(path: Path, offset: int) -> Iterator[tuple[UsageRecord, int]]:
    """Yield new UsageRecords from a file starting at the given byte offset."""
    lines, new_offset = tail_read_new_lines(path, offset)
    for line in lines:
        try:
            record = UsageRecord.model_validate_json(line)
            yield record, new_offset
        except Exception:
            continue

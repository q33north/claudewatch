"""SQLite storage backend for multi-machine claudewatch.

Uses WAL mode for concurrent read/write safety.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from claudewatch.models import QuotaEvent, UsageRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    session_id TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT 'unknown',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_input_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_input_tokens INTEGER NOT NULL DEFAULT 0,
    project TEXT NOT NULL DEFAULT 'unknown',
    service_tier TEXT NOT NULL DEFAULT 'standard',
    speed TEXT NOT NULL DEFAULT 'standard',
    user_id TEXT NOT NULL DEFAULT 'default',
    slug TEXT NOT NULL DEFAULT '',
    machine_id TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS quota_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    cumulative_input INTEGER NOT NULL DEFAULT 0,
    cumulative_output INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL DEFAULT 'default',
    machine_id TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_records(timestamp);
CREATE INDEX IF NOT EXISTS idx_usage_session ON usage_records(session_id);
CREATE INDEX IF NOT EXISTS idx_usage_machine ON usage_records(machine_id);
CREATE INDEX IF NOT EXISTS idx_quota_timestamp ON quota_events(timestamp);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with WAL mode and busy timeout."""
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    """Create tables and indexes if they don't exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path)
    try:
        conn.executescript(_SCHEMA)
    finally:
        conn.close()


def insert_usage(db_path: Path, record: UsageRecord) -> None:
    """Insert a single usage record."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT INTO usage_records
            (timestamp, session_id, model, input_tokens, output_tokens,
             cache_read_input_tokens, cache_creation_input_tokens,
             project, service_tier, speed, user_id, slug, machine_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.timestamp.isoformat(),
                record.session_id,
                record.model,
                record.input_tokens,
                record.output_tokens,
                record.cache_read_input_tokens,
                record.cache_creation_input_tokens,
                record.project,
                record.service_tier,
                record.speed,
                record.user_id,
                record.slug,
                record.machine_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def insert_quota_event(db_path: Path, event: QuotaEvent) -> None:
    """Insert a single quota event."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT INTO quota_events
            (timestamp, event_type, cumulative_input, cumulative_output,
             message, user_id, machine_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                event.timestamp.isoformat(),
                event.event_type,
                event.cumulative_input,
                event.cumulative_output,
                event.message,
                event.user_id,
                event.machine_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _row_to_usage(row: sqlite3.Row) -> UsageRecord:
    """Convert a database row to a UsageRecord."""
    return UsageRecord(
        timestamp=datetime.fromisoformat(row["timestamp"]),
        session_id=row["session_id"],
        model=row["model"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        cache_read_input_tokens=row["cache_read_input_tokens"],
        cache_creation_input_tokens=row["cache_creation_input_tokens"],
        project=row["project"],
        service_tier=row["service_tier"],
        speed=row["speed"],
        user_id=row["user_id"],
        slug=row["slug"],
        machine_id=row["machine_id"],
    )


def _row_to_quota(row: sqlite3.Row) -> QuotaEvent:
    """Convert a database row to a QuotaEvent."""
    return QuotaEvent(
        timestamp=datetime.fromisoformat(row["timestamp"]),
        event_type=row["event_type"],
        cumulative_input=row["cumulative_input"],
        cumulative_output=row["cumulative_output"],
        message=row["message"],
        user_id=row["user_id"],
        machine_id=row["machine_id"],
    )


def read_usage(
    db_path: Path,
    *,
    since: datetime | None = None,
    machine_id: str | None = None,
) -> list[UsageRecord]:
    """Read usage records with optional filters."""
    conn = _connect(db_path)
    try:
        clauses: list[str] = []
        params: list[str | int] = []
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since.isoformat())
        if machine_id is not None:
            clauses.append("machine_id = ?")
            params.append(machine_id)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor = conn.execute(
            f"SELECT * FROM usage_records {where} ORDER BY timestamp", params
        )
        return [_row_to_usage(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def read_quota_events(
    db_path: Path,
    *,
    since: datetime | None = None,
    machine_id: str | None = None,
) -> list[QuotaEvent]:
    """Read quota events with optional filters."""
    conn = _connect(db_path)
    try:
        clauses: list[str] = []
        params: list[str | int] = []
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since.isoformat())
        if machine_id is not None:
            clauses.append("machine_id = ?")
            params.append(machine_id)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor = conn.execute(
            f"SELECT * FROM quota_events {where} ORDER BY timestamp", params
        )
        return [_row_to_quota(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def read_active_sessions(db_path: Path, minutes: int = 10) -> list[dict]:
    """Return sessions with activity in the last N minutes.

    Each entry: {session_id, machine_id, model, project, slug, last_activity, record_count}.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            """SELECT session_id, machine_id, model, project, slug,
                      MAX(timestamp) as last_activity, COUNT(*) as record_count
               FROM usage_records
               WHERE timestamp >= ?
               GROUP BY session_id
               ORDER BY last_activity DESC""",
            (cutoff,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def read_today_usage(db_path: Path) -> list[UsageRecord]:
    """Read all usage records from today (UTC)."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return read_usage(db_path, since=today_start)


def migrate_jsonl_to_sqlite(jsonl_path: Path, db_path: Path) -> int:
    """Migrate records from a JSONL file into SQLite. Returns count of migrated records."""
    if not jsonl_path.exists() or jsonl_path.stat().st_size == 0:
        return 0

    from claudewatch.storage.jsonl import read_usage as read_jsonl

    records = read_jsonl(path=jsonl_path)
    conn = _connect(db_path)
    try:
        for record in records:
            conn.execute(
                """INSERT INTO usage_records
                (timestamp, session_id, model, input_tokens, output_tokens,
                 cache_read_input_tokens, cache_creation_input_tokens,
                 project, service_tier, speed, user_id, slug, machine_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.timestamp.isoformat(),
                    record.session_id,
                    record.model,
                    record.input_tokens,
                    record.output_tokens,
                    record.cache_read_input_tokens,
                    record.cache_creation_input_tokens,
                    record.project,
                    record.service_tier,
                    record.speed,
                    record.user_id,
                    record.slug,
                    record.machine_id,
                ),
            )
        conn.commit()
        return len(records)
    finally:
        conn.close()

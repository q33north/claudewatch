"""Multi-session grid container.

Discovers active sessions and renders a ContextGrid for each one.
Used in the 2x2 dashboard layout (3 slots for session grids).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from claudewatch.models import UsageRecord

MAX_GRIDS = 3  # 2x2 layout minus the TodayUsage panel


def discover_active_sessions(
    records: list[UsageRecord],
    minutes: int = 10,
) -> list[dict]:
    """Find active sessions from records, ordered by most recent activity.

    Returns up to MAX_GRIDS sessions, each as a dict with:
    {session_id, machine_id, model, project, slug, last_activity}.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    by_session: dict[str, list[UsageRecord]] = defaultdict(list)

    for r in records:
        ts = r.timestamp if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=timezone.utc)
        if ts >= cutoff:
            by_session[r.session_id].append(r)

    sessions = []
    for sid, recs in by_session.items():
        latest = max(recs, key=lambda r: r.timestamp)
        sessions.append({
            "session_id": sid,
            "machine_id": latest.machine_id,
            "model": latest.model,
            "project": latest.project,
            "slug": latest.slug,
            "last_activity": latest.timestamp.isoformat(),
        })

    sessions.sort(key=lambda s: s["last_activity"], reverse=True)
    return sessions[:MAX_GRIDS]

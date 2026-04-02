"""Fire-and-forget HTTP push of usage records to a claudewatch server.

Designed to be called from hooks without blocking Claude Code.
All errors are silently swallowed - local JSONL is the source of truth,
the server push is best-effort.
"""

from __future__ import annotations

import json
from pathlib import Path

from claudewatch.config import SERVER_CONFIG
from claudewatch.models import UsageRecord

# Short timeout: we must not slow down Claude Code
_PUSH_TIMEOUT = 2.0


def _load_push_config(config_path: Path = SERVER_CONFIG) -> dict | None:
    """Load server URL + auth token from config. Returns None if not configured."""
    if not config_path.exists():
        return None
    try:
        data = json.loads(config_path.read_text())
        if "server_url" in data and "auth_token" in data:
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def push_record(
    record: UsageRecord,
    server_url: str,
    auth_token: str,
) -> None:
    """POST a usage record to the server. Fails silently on any error."""
    try:
        import httpx

        payload = record.model_dump(mode="json")
        httpx.post(
            f"{server_url}/api/usage",
            json=payload,
            headers={"Authorization": f"Bearer {auth_token}"},
            timeout=_PUSH_TIMEOUT,
        )
    except Exception:
        pass  # best-effort: local JSONL is the source of truth


def maybe_push(record: UsageRecord) -> None:
    """Push a record to the server if configured. Called from hooks."""
    config = _load_push_config()
    if config is None:
        return
    push_record(record, server_url=config["server_url"], auth_token=config["auth_token"])

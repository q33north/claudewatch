"""Test oracle for the HTTP push module and hook integration (Phase 3).

Written BEFORE implementation per the test-oracle pattern.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

from claudewatch.models import UsageRecord


def _make_usage(
    session_id: str = "sess-push",
    machine_id: str = "test-box",
    minutes_ago: int = 1,
) -> UsageRecord:
    return UsageRecord(
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        session_id=session_id,
        model="claude-opus-4-6",
        input_tokens=1000,
        output_tokens=500,
        cache_read_input_tokens=5000,
        cache_creation_input_tokens=200,
        project="test",
        machine_id=machine_id,
    )


class _CaptureHandler(BaseHTTPRequestHandler):
    """Captures POST payloads for test inspection."""

    captured: list[dict] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        payload = json.loads(body)
        # Also capture auth header
        auth = self.headers.get("Authorization", "")
        _CaptureHandler.captured.append({"payload": payload, "auth": auth})
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

    def log_message(self, format, *args):
        pass  # silence logs


class _SlowHandler(BaseHTTPRequestHandler):
    """Responds after a long delay to test timeout behavior."""

    def do_POST(self):
        time.sleep(10)  # way longer than the push timeout
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass


@pytest.fixture
def capture_server():
    """Start a local HTTP server that captures POST payloads."""
    _CaptureHandler.captured = []
    server = HTTPServer(("127.0.0.1", 0), _CaptureHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}", _CaptureHandler.captured
    server.shutdown()


@pytest.fixture
def slow_server():
    """Start a server that responds very slowly."""
    server = HTTPServer(("127.0.0.1", 0), _SlowHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


class TestPushRecord:
    def test_success(self, capture_server) -> None:
        from claudewatch.collector.push import push_record

        url, captured = capture_server
        record = _make_usage()
        push_record(record, server_url=url, auth_token="test-token")

        assert len(captured) == 1
        assert captured[0]["payload"]["session_id"] == "sess-push"
        assert captured[0]["payload"]["machine_id"] == "test-box"

    def test_includes_auth_header(self, capture_server) -> None:
        from claudewatch.collector.push import push_record

        url, captured = capture_server
        push_record(_make_usage(), server_url=url, auth_token="secret-123")

        assert len(captured) == 1
        assert captured[0]["auth"] == "Bearer secret-123"

    def test_timeout_doesnt_block(self, slow_server) -> None:
        """Push to a slow server should complete quickly (not hang)."""
        from claudewatch.collector.push import push_record

        start = time.time()
        push_record(_make_usage(), server_url=slow_server, auth_token="tok")
        elapsed = time.time() - start

        # Should timeout in ~2s, definitely not 10s
        assert elapsed < 5

    def test_server_down_doesnt_raise(self) -> None:
        """Connection refused should be silently handled."""
        from claudewatch.collector.push import push_record

        # Nothing listening on this port
        push_record(_make_usage(), server_url="http://127.0.0.1:19999", auth_token="tok")
        # No exception = pass

    def test_includes_machine_id(self, capture_server) -> None:
        from claudewatch.collector.push import push_record

        url, captured = capture_server
        record = _make_usage(machine_id="umich-hpc-01")
        push_record(record, server_url=url, auth_token="tok")

        assert captured[0]["payload"]["machine_id"] == "umich-hpc-01"


class TestHookIntegration:
    def test_hook_skips_push_when_no_server(self, tmp_path: Path) -> None:
        """When no server_url is configured, push should not be called."""
        from claudewatch.collector.push import _load_push_config

        # Empty config = no server
        config = _load_push_config(tmp_path / "nonexistent.json")
        assert config is None

    def test_hook_loads_config(self, tmp_path: Path) -> None:
        """When server.json exists with url+token, config is returned."""
        from claudewatch.collector.push import _load_push_config

        config_path = tmp_path / "server.json"
        config_path.write_text(json.dumps({
            "server_url": "http://mini.local:8420",
            "auth_token": "abc123",
        }))

        config = _load_push_config(config_path)
        assert config is not None
        assert config["server_url"] == "http://mini.local:8420"
        assert config["auth_token"] == "abc123"


class TestHookCoexistence:
    """Verify install/uninstall doesn't clobber other hooks."""

    def test_install_preserves_existing_hooks(self, tmp_path: Path) -> None:
        """Installing claudewatch hooks should not remove other hooks like memsearch."""
        from claudewatch.cli import _register_hook

        settings: dict = {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "memsearch-hook stop",
                            }
                        ]
                    }
                ]
            }
        }

        _register_hook(settings, "Stop", "~/.claude/hooks/claudewatch-stop.sh")

        stop_hooks = settings["hooks"]["Stop"]
        # Should have both: memsearch + claudewatch
        assert len(stop_hooks) == 2
        commands = [
            h["command"]
            for group in stop_hooks
            for h in group.get("hooks", [])
        ]
        assert any("memsearch" in c for c in commands)
        assert any("claudewatch" in c for c in commands)

    def test_install_doesnt_duplicate(self, tmp_path: Path) -> None:
        """Installing twice should not create duplicate hooks."""
        from claudewatch.cli import _register_hook

        settings: dict = {"hooks": {}}
        _register_hook(settings, "Stop", "~/.claude/hooks/claudewatch-stop.sh")
        added = _register_hook(settings, "Stop", "~/.claude/hooks/claudewatch-stop.sh")

        assert added is False
        assert len(settings["hooks"]["Stop"]) == 1

    def test_uninstall_preserves_other_hooks(self) -> None:
        """Removing claudewatch hooks should leave other hooks intact."""
        settings = {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {"type": "command", "command": "memsearch-hook stop"}
                        ]
                    },
                    {
                        "hooks": [
                            {"type": "command", "command": "~/.claude/hooks/claudewatch-stop.sh"}
                        ]
                    },
                ]
            }
        }

        # Simulate uninstall logic: filter out claudewatch hooks
        hooks = settings["hooks"]
        hooks["Stop"] = [
            group for group in hooks["Stop"]
            if not any("claudewatch" in h.get("command", "") for h in group.get("hooks", []))
        ]

        assert len(hooks["Stop"]) == 1
        assert "memsearch" in hooks["Stop"][0]["hooks"][0]["command"]

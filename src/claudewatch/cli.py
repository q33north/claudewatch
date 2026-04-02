"""CLI interface for claudewatch. Commands: watch, backfill, install, serve, connect, summary."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from claudewatch import __version__
from claudewatch.config import (
    CLAUDEWATCH_DIR,
    DEFAULT_PORT,
    HOOKS_DIR,
    HOOK_SCRIPT,
    POSTTOOL_HOOK_SCRIPT,
    SERVER_CONFIG,
    SERVER_DB,
    SETTINGS_JSON,
    USAGE_JSONL,
    ensure_dirs,
)


def _read_settings() -> dict:
    """Read settings.json, handling trailing commas and other common JSON issues."""
    if not SETTINGS_JSON.exists():
        return {}
    raw = SETTINGS_JSON.read_text()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Try fixing trailing commas (common after manual edits)
    import re
    fixed = re.sub(r",\s*([}\]])", r"\1", raw)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        console.print(f"[red]Could not parse {SETTINGS_JSON} (even after fixing trailing commas)[/]")
        console.print("[dim]Check it manually or restore from a backup.[/]")
        return {}

app = typer.Typer(
    name="claudewatch",
    help="Real-time TUI dashboard for Claude Code token usage monitoring.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def watch(
    server: Optional[str] = typer.Option(
        None, help="Server URL to connect to (e.g. http://mini.local:8420)"
    ),
) -> None:
    """Launch the live TUI dashboard."""
    from claudewatch.tui.app import ClaudeWatchApp

    ensure_dirs()

    server_url = server
    auth_token = None

    # If no --server flag, check if we have a saved connection
    if not server_url:
        config = _load_server_config()
        if config.get("server_url"):
            server_url = config["server_url"]
            auth_token = config.get("auth_token")

    # If --server was explicit, load token from config
    if server_url and not auth_token:
        config = _load_server_config()
        auth_token = config.get("auth_token")

    app_instance = ClaudeWatchApp(server_url=server_url, auth_token=auth_token)
    app_instance.run()


@app.command()
def backfill(
    since: Optional[str] = typer.Option(
        None, help="Only backfill sessions modified after this date (YYYY-MM-DD)"
    ),
) -> None:
    """Scan historical Claude Code sessions and import usage data."""
    from claudewatch.collector.backfill import backfill as run_backfill

    ensure_dirs()
    since_dt = None
    if since:
        since_dt = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    console.print(f"[bold]Scanning historical sessions...[/]")
    count = run_backfill(since=since_dt)
    console.print(f"[green]Done![/] Imported {count:,} new usage records to {USAGE_JSONL}")


def _write_hook_script(path, description: str) -> str:
    """Write a hook shell script and return its path as a string."""
    hook_content = (
        "#!/usr/bin/env bash\n"
        f"# claudewatch {description} - extracts usage from Claude Code transcripts\n"
        "# Managed by: claudewatch install / claudewatch uninstall\n"
        "set -euo pipefail\n"
        "\n"
        # Resolve python at install time so hooks work without conda env active
        f'exec "{sys.executable}" -m claudewatch.collector.hook\n'
    )
    path.write_text(hook_content)
    path.chmod(0o755)
    return str(path)


def _register_hook(settings: dict, event_name: str, hook_command: str) -> bool:
    """Register a hook in settings if not already present. Returns True if added."""
    hooks = settings.setdefault("hooks", {})
    event_hooks = hooks.setdefault(event_name, [])

    for hook_group in event_hooks:
        for hook in hook_group.get("hooks", []):
            if "claudewatch" in hook.get("command", ""):
                return False

    event_hooks.append(
        {
            "hooks": [
                {
                    "type": "command",
                    "command": hook_command,
                    "async": True,
                }
            ]
        }
    )
    return True


@app.command()
def install() -> None:
    """Install claudewatch hooks (Stop + PostToolUse) for live monitoring."""
    ensure_dirs()
    HOOKS_DIR.mkdir(parents=True, exist_ok=True)

    # Write hook scripts
    _write_hook_script(HOOK_SCRIPT, "Stop hook")
    console.print(f"[green]Wrote hook script[/] -> {HOOK_SCRIPT}")

    _write_hook_script(POSTTOOL_HOOK_SCRIPT, "PostToolUse hook")
    console.print(f"[green]Wrote hook script[/] -> {POSTTOOL_HOOK_SCRIPT}")

    # Use ~ paths so hooks work across machines (linux + mac)
    stop_cmd = f"~/.claude/hooks/{HOOK_SCRIPT.name}"
    posttool_cmd = f"~/.claude/hooks/{POSTTOOL_HOOK_SCRIPT.name}"

    # Read existing settings and register hooks
    settings = _read_settings()
    added_stop = _register_hook(settings, "Stop", stop_cmd)
    added_posttool = _register_hook(settings, "PostToolUse", posttool_cmd)

    if not added_stop and not added_posttool:
        console.print("[yellow]claudewatch hooks already registered in settings.json![/]")
        return

    SETTINGS_JSON.write_text(json.dumps(settings, indent=4) + "\n")

    if added_stop:
        console.print(f"[green]Registered Stop hook[/] in {SETTINGS_JSON}")
    else:
        console.print("[dim]Stop hook already registered[/]")

    if added_posttool:
        console.print(f"[green]Registered PostToolUse hook[/] in {SETTINGS_JSON}")
    else:
        console.print("[dim]PostToolUse hook already registered[/]")

    # Dry-run validation
    console.print("\n[dim]Validating hook...[/]")
    try:
        import subprocess

        result = subprocess.run(
            ["python3", "-c", "from claudewatch.collector.hook import run_hook; print('ok')"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if "ok" in result.stdout:
            console.print("[green]Hook validation passed[/]")
        else:
            console.print(f"[yellow]Hook validation warning:[/] {result.stderr[:200]}")
    except Exception as e:
        console.print(f"[yellow]Could not validate hook:[/] {e}")


@app.command()
def uninstall() -> None:
    """Remove all claudewatch hooks from settings and delete hook scripts."""
    # Remove from settings.json
    settings = _read_settings()
    removed_any = False
    if settings:
        hooks = settings.get("hooks", {})
        for event_name in ["Stop", "PostToolUse"]:
            event_hooks = hooks.get(event_name, [])
            original_len = len(event_hooks)
            hooks[event_name] = [
                group for group in event_hooks
                if not any("claudewatch" in h.get("command", "") for h in group.get("hooks", []))
            ]
            if not hooks[event_name]:
                del hooks[event_name]
            if len(hooks.get(event_name, [])) < original_len:
                console.print(f"[green]Removed {event_name} hook[/] from {SETTINGS_JSON}")
                removed_any = True

        if removed_any:
            SETTINGS_JSON.write_text(json.dumps(settings, indent=4) + "\n")
        else:
            console.print("[dim]No claudewatch hooks found in settings.json[/]")

    # Remove hook scripts
    for script in [HOOK_SCRIPT, POSTTOOL_HOOK_SCRIPT]:
        if script.exists():
            script.unlink()
            console.print(f"[green]Deleted[/] {script}")

    console.print("\n[dim]Usage data at ~/.claude/claudewatch/ was not removed.[/]")


def _load_server_config() -> dict:
    """Load server config from disk."""
    if SERVER_CONFIG.exists():
        return json.loads(SERVER_CONFIG.read_text())
    return {}


def _save_server_config(config: dict) -> None:
    """Save server config to disk."""
    ensure_dirs()
    SERVER_CONFIG.write_text(json.dumps(config, indent=2) + "\n")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address (use 0.0.0.0 for network access)"),
    port: int = typer.Option(DEFAULT_PORT, help="Port to listen on"),
    db: Optional[str] = typer.Option(None, help="SQLite database path"),
) -> None:
    """Start the claudewatch ingest server."""
    import secrets

    try:
        import uvicorn
    except ImportError:
        console.print("[red]Server dependencies not installed.[/]")
        console.print("Install with: [bold]pip install claudewatch\\[server][/]")
        raise typer.Exit(1)

    ensure_dirs()
    db_path = Path(db) if db else SERVER_DB

    # Load or generate auth token
    config = _load_server_config()
    if "auth_token" not in config:
        config["auth_token"] = secrets.token_urlsafe(32)
        _save_server_config(config)
        console.print(f"\n[bold green]Generated new auth token:[/]")
        console.print(f"  {config['auth_token']}")
        console.print(f"\n  Save this! Clients need it to connect.\n")
    else:
        console.print(f"\n[dim]Using existing auth token from {SERVER_CONFIG}[/]")

    from claudewatch.server.app import create_app

    fastapi_app = create_app(db_path=db_path, auth_token=config["auth_token"])

    console.print(f"[bold]claudewatch server[/]")
    console.print(f"  Database: {db_path}")
    console.print(f"  Listening: http://{host}:{port}")
    if host == "127.0.0.1":
        console.print(f"  [dim]Localhost only. Use --host 0.0.0.0 for network access.[/]")
    console.print(f"\n  Data is stored locally. Nothing leaves this machine.\n")

    uvicorn.run(fastapi_app, host=host, port=port, log_level="info")


@app.command()
def connect(
    server_url: str = typer.Argument(help="Server URL, e.g. http://mini.local:8420"),
    token: str = typer.Option(..., help="Auth token from 'claudewatch serve'"),
) -> None:
    """Connect this machine to a claudewatch server (one-time setup)."""
    ensure_dirs()

    # Normalize URL
    url = server_url.rstrip("/")
    if not url.startswith("http"):
        url = f"http://{url}"

    # Save to config
    config = _load_server_config()
    config["server_url"] = url
    config["auth_token"] = token
    _save_server_config(config)

    console.print(f"[green]Connected![/] Server: {url}")
    console.print(f"Config saved to {SERVER_CONFIG}")
    console.print(f"\n[dim]Hooks will now push data to the server automatically.[/]")

    # Quick health check
    try:
        import httpx

        resp = httpx.get(f"{url}/api/health", timeout=3)
        if resp.status_code == 200:
            console.print(f"[green]Server is reachable.[/]")
        else:
            console.print(f"[yellow]Server responded with status {resp.status_code}[/]")
    except Exception:
        console.print(f"[yellow]Could not reach server (it may not be running yet).[/]")


@app.command()
def summary() -> None:
    """Print a summary of today's usage to the terminal."""
    from claudewatch.storage.jsonl import read_usage

    records = read_usage()
    if not records:
        console.print("[dim]No usage data found. Run 'claudewatch backfill' first.[/]")
        return

    today = datetime.now(timezone.utc).date()
    today_records = [r for r in records if r.timestamp.date() == today]

    table = Table(title=f"Usage Summary - {today}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    total_in = sum(r.input_tokens for r in today_records)
    total_out = sum(r.output_tokens for r in today_records)
    total_cache_r = sum(r.cache_read_input_tokens for r in today_records)
    total_cache_c = sum(r.cache_creation_input_tokens for r in today_records)
    total_cost = sum(r.cost_estimate for r in today_records)
    sessions = len(set(r.session_id for r in today_records))

    table.add_row("Messages", f"{len(today_records):,}")
    table.add_row("Sessions", f"{sessions:,}")
    table.add_row("Input tokens", f"{total_in:,}")
    table.add_row("Output tokens", f"{total_out:,}")
    table.add_row("Cache read", f"{total_cache_r:,}")
    table.add_row("Cache write", f"{total_cache_c:,}")
    table.add_row("Total tokens", f"{total_in + total_out + total_cache_r + total_cache_c:,}")
    table.add_row("Est. cost", f"${total_cost:.2f}")

    console.print(table)

    # All-time stats
    all_cost = sum(r.cost_estimate for r in records)
    all_sessions = len(set(r.session_id for r in records))
    console.print(f"\n[dim]All time: {len(records):,} messages, {all_sessions:,} sessions, ${all_cost:.2f} est. cost[/]")


@app.command()
def version() -> None:
    """Print the claudewatch version."""
    console.print(f"claudewatch v{__version__}")


# Expose the hook runner as a CLI-accessible module
@app.command(hidden=True)
def hook() -> None:
    """Run the Stop hook (called by Claude Code, not directly)."""
    from claudewatch.collector.hook import run_hook

    run_hook()

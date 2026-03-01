"""CLI interface for claudewatch. Commands: watch, backfill, install, summary."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from claudewatch import __version__
from claudewatch.config import (
    CLAUDEWATCH_DIR,
    HOOKS_DIR,
    HOOK_SCRIPT,
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
def watch() -> None:
    """Launch the live TUI dashboard."""
    from claudewatch.tui.app import ClaudeWatchApp

    ensure_dirs()
    app_instance = ClaudeWatchApp()
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


@app.command()
def install() -> None:
    """Install the claudewatch Stop hook into ~/.claude/hooks/ and register it in settings."""
    ensure_dirs()

    # Write hook script to ~/.claude/hooks/
    HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    hook_content = (
        "#!/usr/bin/env bash\n"
        "# claudewatch Stop hook - extracts usage from Claude Code transcripts\n"
        "# Managed by: claudewatch install / claudewatch uninstall\n"
        "set -euo pipefail\n"
        "\n"
        "export CLAUDEWATCH_HOOK_ACTIVE=1\n"
        "exec python3 -m claudewatch.collector.hook\n"
    )
    HOOK_SCRIPT.write_text(hook_content)
    HOOK_SCRIPT.chmod(0o755)
    hook_command = str(HOOK_SCRIPT)
    console.print(f"[green]Wrote hook script[/] -> {HOOK_SCRIPT}")

    # Read existing settings
    settings = _read_settings()

    # Add/update Stop hook
    hooks = settings.setdefault("hooks", {})
    stop_hooks = hooks.setdefault("Stop", [])

    # Check if already installed
    for hook_group in stop_hooks:
        for hook in hook_group.get("hooks", []):
            if "claudewatch" in hook.get("command", ""):
                console.print("[yellow]claudewatch hook already registered in settings.json![/]")
                return

    # Add our hook
    stop_hooks.append(
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

    SETTINGS_JSON.write_text(json.dumps(settings, indent=4) + "\n")
    console.print(f"[green]Registered Stop hook[/] in {SETTINGS_JSON}")

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
    """Remove the claudewatch Stop hook from settings and delete the hook script."""
    # Remove from settings.json
    settings = _read_settings()
    if settings:
        hooks = settings.get("hooks", {})
        stop_hooks = hooks.get("Stop", [])
        original_len = len(stop_hooks)
        hooks["Stop"] = [
            group for group in stop_hooks
            if not any("claudewatch" in h.get("command", "") for h in group.get("hooks", []))
        ]
        if not hooks["Stop"]:
            del hooks["Stop"]

        if len(hooks.get("Stop", [])) < original_len:
            SETTINGS_JSON.write_text(json.dumps(settings, indent=4) + "\n")
            console.print(f"[green]Removed Stop hook[/] from {SETTINGS_JSON}")
        else:
            console.print("[dim]No claudewatch hook found in settings.json[/]")

    # Remove hook script
    if HOOK_SCRIPT.exists():
        HOOK_SCRIPT.unlink()
        console.print(f"[green]Deleted[/] {HOOK_SCRIPT}")
    else:
        console.print(f"[dim]No hook script at {HOOK_SCRIPT}[/]")

    console.print("\n[dim]Usage data at ~/.claude/claudewatch/ was not removed.[/]")


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

"""Live scrolling event feed widget."""

from __future__ import annotations

from datetime import datetime, timezone

from textual.widgets import RichLog

# Color scheme for event tags
TAG_STYLES: dict[str, str] = {
    "New": "green",
    "Loaded": "cyan",
    "Refresh": "blue",
    "QUOTA": "bold red",
    "COMPACT": "yellow",
    "WARN": "bold yellow",
    "ERROR": "bold red",
    "Session": "magenta",
    "Cost": "yellow",
    "Spike": "bold yellow",
    "Cache": "green",
    "Window": "red",
    "Model": "cyan",
}


class EventLog(RichLog):
    """Live scrolling log of usage events and system messages."""

    DEFAULT_CSS = """
    EventLog {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(markup=True, **kwargs)

    def on_mount(self) -> None:
        self.write("[bold]Event Log[/]")
        self.write("")

    def add_event(
        self, tag: str, message: str, style: str = ""
    ) -> None:
        """Add a timestamped event to the log."""
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        # Use explicit style if provided, otherwise look up by tag
        if not style:
            style = TAG_STYLES.get(tag, "")
        tag_style = TAG_STYLES.get(tag, "dim")
        tag_str = f"[{tag_style}]{tag:>8}[/{tag_style.split()[0]}]"
        if style:
            self.write(f"  [dim]{now}[/] {tag_str} [{style}]{message}[/{style.split()[0]}]")
        else:
            self.write(f"  [dim]{now}[/] {tag_str} {message}")

"""Live scrolling event feed widget."""

from __future__ import annotations

from datetime import datetime, timezone

from textual.widgets import RichLog


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
        style_open = f"[{style}]" if style else ""
        style_close = f"[/{style.split()[0]}]" if style else ""
        self.write(f"  {now} [{tag:>8}] {style_open}{message}{style_close}")

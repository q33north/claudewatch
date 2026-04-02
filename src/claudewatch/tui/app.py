"""Main textual TUI application for claudewatch.

Supports two layouts:
- Local mode (default): 3-column top + session list bottom
- Server mode (--server): 2x2 grid with per-session context grids
"""

from __future__ import annotations

from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Footer, Header, Static

from claudewatch.config import USAGE_JSONL, QUOTA_EVENTS_JSONL
from claudewatch.models import UsageRecord, QuotaEvent
from claudewatch.storage.jsonl import read_usage, read_quota_events
from claudewatch.tui.widgets.today_usage import TodayUsage
from claudewatch.tui.widgets.session_list import SessionList
from claudewatch.tui.widgets.context_health import ContextHealth
from claudewatch.tui.widgets.context_grid import ContextGrid
from claudewatch.tui.widgets.session_grid import discover_active_sessions


class NewUsageEvent(Message):
    """Posted when a new usage record is detected via file watcher."""

    def __init__(self, record: UsageRecord) -> None:
        self.record = record
        super().__init__()


class NewQuotaEvent(Message):
    """Posted when a new quota event is detected."""

    def __init__(self, event: QuotaEvent) -> None:
        self.event = event
        super().__init__()


class EmptyGridPlaceholder(Static):
    """Placeholder shown when no active session occupies a grid slot."""

    def render(self) -> str:
        return "[dim]waiting for session...[/]"


class ClaudeWatchApp(App):
    """Real-time Claude Code token usage dashboard."""

    TITLE = "claudewatch"
    SUB_TITLE = "token usage dashboard"
    CSS_PATH = "dashboard.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "focus_panel('today')", "Today", show=False),
        Binding("2", "focus_panel('grid1')", "Grid 1", show=False),
        Binding("3", "focus_panel('grid2')", "Grid 2", show=False),
        Binding("4", "focus_panel('grid3')", "Grid 3", show=False),
    ]

    def __init__(self, server_url: str | None = None, auth_token: str | None = None) -> None:
        super().__init__()
        self._usage_offset: int = 0
        self._quota_offset: int = 0
        self._observer = None
        self._shutting_down = False
        self._seen_sessions: set[str] = set()
        self._last_model: str = ""
        self._server_url = server_url
        self._auth_token = auth_token
        self._data_source = None

    def _init_data_source(self):
        """Initialize the data source (local or server)."""
        if self._server_url and self._auth_token:
            from claudewatch.tui.data_source import ServerDataSource
            self._data_source = ServerDataSource(
                base_url=self._server_url,
                auth_token=self._auth_token,
            )
        else:
            from claudewatch.tui.data_source import LocalDataSource
            self._data_source = LocalDataSource()

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="dashboard"):
            with Horizontal(id="top-row"):
                yield TodayUsage(id="today-usage")
                yield ContextGrid(id="grid-1")
            with Horizontal(id="bottom-row"):
                yield ContextGrid(id="grid-2")
                yield ContextGrid(id="grid-3")
        yield Footer()

    def on_mount(self) -> None:
        """Load initial data and start file watcher or server poller."""
        self._init_data_source()
        self.load_data()
        if self._server_url:
            self._start_server_poller()
        else:
            self.start_file_watcher()

    def _get_grid_widgets(self) -> list[ContextGrid]:
        """Return the 3 grid widgets."""
        return [
            self.query_one("#grid-1", ContextGrid),
            self.query_one("#grid-2", ContextGrid),
            self.query_one("#grid-3", ContextGrid),
        ]

    def _update_session_grids(self, records: list[UsageRecord]) -> None:
        """Update the 3 grid slots based on active sessions."""
        sessions = discover_active_sessions(records, minutes=10)
        grids = self._get_grid_widgets()

        for i, grid in enumerate(grids):
            if i < len(sessions):
                sess = sessions[i]
                grid.set_session(sess["session_id"], meta=sess)
                grid.update_records(records)
            else:
                grid.clear_session()

    def load_data(self) -> None:
        """Load all existing records from storage."""
        if self._data_source:
            records = self._data_source.get_all_records()
            events = self._data_source.get_quota_events()
        else:
            records = read_usage()
            events = read_quota_events()

        self.query_one(TodayUsage).update_records(records)
        self._update_session_grids(records)

        # Seed seen sessions
        self._seen_sessions = set(r.session_id for r in records)
        if records:
            last = max(records, key=lambda r: r.timestamp)
            self._last_model = last.model.replace("claude-", "").split("-20")[0]

        # Track file offsets for incremental reads (local mode only)
        if not self._server_url:
            if USAGE_JSONL.exists():
                self._usage_offset = USAGE_JSONL.stat().st_size
            if QUOTA_EVENTS_JSONL.exists():
                self._quota_offset = QUOTA_EVENTS_JSONL.stat().st_size

    @work(thread=True)
    def _start_server_poller(self) -> None:
        """Poll the server for new data periodically."""
        import time

        while not self._shutting_down:
            time.sleep(3)  # poll every 3 seconds
            try:
                self.call_from_thread(self.load_data)
            except Exception:
                pass

    @work(thread=True)
    def start_file_watcher(self) -> None:
        """Watch usage.jsonl for new records using watchdog."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler, FileModifiedEvent
        except ImportError:
            return

        app = self

        class UsageFileHandler(FileSystemEventHandler):
            def on_modified(self, event: FileModifiedEvent) -> None:
                if not isinstance(event, FileModifiedEvent):
                    return
                path = Path(event.src_path)
                if path.name == "usage.jsonl":
                    self._handle_usage_update(path)
                elif path.name == "quota-events.jsonl":
                    self._handle_quota_update(path)

            def _handle_usage_update(self, path: Path) -> None:
                from claudewatch.storage.jsonl import iter_usage_from_offset

                for record, new_offset in iter_usage_from_offset(path, app._usage_offset):
                    app._usage_offset = new_offset
                    app.post_message(NewUsageEvent(record))

            def _handle_quota_update(self, path: Path) -> None:
                from claudewatch.storage.jsonl import tail_read_new_lines

                lines, new_offset = tail_read_new_lines(path, app._quota_offset)
                app._quota_offset = new_offset
                for line in lines:
                    try:
                        event = QuotaEvent.model_validate_json(line)
                        app.post_message(NewQuotaEvent(event))
                    except Exception:
                        continue

        watch_dir = USAGE_JSONL.parent
        watch_dir.mkdir(parents=True, exist_ok=True)

        USAGE_JSONL.touch(exist_ok=True)
        QUOTA_EVENTS_JSONL.touch(exist_ok=True)

        handler = UsageFileHandler()
        observer = Observer()
        observer.daemon = True
        observer.schedule(handler, str(watch_dir), recursive=False)
        observer.start()
        self._observer = observer

        import time
        while not self._shutting_down:
            time.sleep(0.5)

        observer.stop()
        observer.join(timeout=2)

    @on(NewUsageEvent)
    def handle_new_usage(self, event: NewUsageEvent) -> None:
        """Handle a new usage record from the file watcher."""
        records = read_usage()

        self.query_one(TodayUsage).update_records(records)
        self._update_session_grids(records)

        self._seen_sessions.add(event.record.session_id)
        short_model = event.record.model.replace("claude-", "").split("-20")[0]
        self._last_model = short_model

    @on(NewQuotaEvent)
    def handle_new_quota(self, event: NewQuotaEvent) -> None:
        """Handle a new quota event."""
        # Quota events don't affect the grid layout, just log them
        pass

    def on_unmount(self) -> None:
        """Clean up file watcher on app shutdown."""
        self._shutting_down = True
        if self._observer:
            self._observer.stop()

    def action_refresh(self) -> None:
        """Manual refresh of all data."""
        self.load_data()

    def action_focus_panel(self, panel: str) -> None:
        """Focus a specific panel."""
        panel_map = {
            "today": "today-usage",
            "grid1": "grid-1",
            "grid2": "grid-2",
            "grid3": "grid-3",
        }
        widget_id = panel_map.get(panel)
        if widget_id:
            self.query_one(f"#{widget_id}").focus()

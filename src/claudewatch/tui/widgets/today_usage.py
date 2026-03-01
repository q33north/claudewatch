"""Today's token usage summary widget."""

from __future__ import annotations

from datetime import datetime, timezone

from textual.reactive import reactive
from textual.widgets import Static

from claudewatch.models import UsageRecord


class TodayUsage(Static):
    """Displays today's token totals by type and model, plus cost estimate."""

    _record_count = reactive(0)

    def __init__(self, **kwargs) -> None:
        super().__init__(markup=True, **kwargs)
        self._records: list[UsageRecord] = []

    def update_records(self, records: list[UsageRecord]) -> None:
        today = datetime.now().date()
        self._records = [
            r for r in records
            if r.timestamp.astimezone().date() == today
        ]
        self._record_count = len(self._records)

    def render(self) -> str:
        records = self._records
        if not records:
            return "Today's Usage\n\nNo data yet"

        total_in = sum(r.input_tokens for r in records)
        total_out = sum(r.output_tokens for r in records)
        total_cache_r = sum(r.cache_read_input_tokens for r in records)
        total_cache_c = sum(r.cache_creation_input_tokens for r in records)
        total_cost = sum(r.cost_estimate for r in records)

        # Group by model
        by_model: dict[str, int] = {}
        for r in records:
            model_short = r.model.replace("claude-", "").split("-20")[0]
            by_model[model_short] = by_model.get(model_short, 0) + r.total_tokens

        model_lines = "\n".join(
            f"  {m}: {t:,}" for m, t in sorted(by_model.items(), key=lambda x: -x[1])
        )

        return (
            f"[bold]Today's Usage[/]  ({len(records)} messages)\n\n"
            f"  Input:       {total_in:>12,}\n"
            f"  Output:      {total_out:>12,}\n"
            f"  Cache read:  {total_cache_r:>12,}\n"
            f"  Cache write: {total_cache_c:>12,}\n"
            f"  [bold]Total:     {total_in + total_out + total_cache_r + total_cache_c:>14,}[/]\n\n"
            f"  API equiv: [bold yellow]${total_cost:.2f}[/]\n\n"
            f"  By model:\n{model_lines}"
        )

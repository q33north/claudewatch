# claudewatch

Real-time TUI dashboard for monitoring Claude Code token usage, costs, and quota status.

Built by [Q33 North](https://github.com/q33north) as part of the [AI for Bioinformaticians](https://substack.com) blog series.

## What it does

- **Live monitoring** - watches your Claude Code usage in real-time via a Stop hook
- **Token tracking** - input, output, cache read/write tokens broken down by model and project
- **Cost estimates** - per-session and daily cost estimates using current API pricing
- **Quota awareness** - detects rate limits and quota hits, estimates your usage ceiling
- **Historical backfill** - imports all your past Claude Code session data
- **Sparkline timeline** - hourly and daily usage trends at a glance

## Install

```bash
# Clone and install
git clone https://github.com/q33north/claudewatch.git
cd claudewatch

# Using conda/mamba
mamba env create -f environment.yml
conda activate claudewatch

# Or pip
pip install -e ".[dev]"
```

## Quick start

```bash
# Install the Stop hook into Claude Code
claudewatch install

# Backfill historical data (optional but recommended)
claudewatch backfill

# Launch the dashboard
claudewatch watch
```

## Commands

| Command | Description |
|---------|-------------|
| `claudewatch watch` | Launch the live TUI dashboard |
| `claudewatch backfill` | Import historical session data |
| `claudewatch install` | Install the Stop hook into Claude Code |
| `claudewatch summary` | Print today's usage summary to terminal |

## How it works

```
Claude Code response
       |
  [Stop hook fires]
       |
  hook.py: tail-read transcript -> extract usage -> append to usage.jsonl
       |
  TUI: watchdog detects file change -> parse new line -> update widgets
```

1. A **Stop hook** fires after every Claude Code response
2. It tail-reads the session transcript to extract the usage block (input/output/cache tokens, model, etc.)
3. Appends a single line to `~/.claude/claudewatch/usage.jsonl`
4. The TUI uses **watchdog** (inotify on Linux) to detect the new line and update all widgets in real-time

The hook is designed to be fast (<50ms) and never makes any API calls.

## Dashboard layout

```
+----------------------------+----------------------------+
|       Today's Usage        |       Quota Status         |
|  tokens by type + model    |  window tracking, last hit |
|  cost estimate             |  ceiling estimate          |
+----------------------------+----------------------------+
|              Usage Timeline (sparklines)                |
|              hourly today / daily last 30d              |
+----------------------------+----------------------------+
|       Session List         |       Event Log            |
|  DataTable, sortable       |  live scrolling feed       |
+----------------------------+----------------------------+
```

**Keybindings:** `q` quit, `r` refresh, `1-4` focus panels

## Development

```bash
pip install -e ".[dev]"
pytest tests/
```

## License

MIT

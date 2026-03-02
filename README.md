# claudewatch

Real-time TUI dashboard for monitoring Claude Code token usage, costs, and quota status.

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

# Using conda (recommended if you use miniforge/mambaforge)
conda env create -f environment.yml
conda activate claudewatch

# Or using pip directly
pip install -e ".[dev]"
```

> **Note:** If you have both `conda` (miniforge) and `micromamba` (homebrew) installed,
> they use different env directories. `mamba env create` may create the env under
> micromamba's prefix (e.g. `/opt/homebrew/Cellar/micromamba/.../envs/claudewatch`)
> which `conda activate` won't find. Either use `conda env create` so the env lands
> in your miniforge `envs/` directory, or activate by full path:
> `conda activate /path/to/envs/claudewatch`.

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

## How Claude Code stores data

Understanding Claude Code's internals is key to understanding what claudewatch
can (and can't) monitor.

### Session transcripts

Every Claude Code session is recorded as a JSONL file under
`~/.claude/projects/<encoded-project-path>/<session-uuid>.jsonl`. Each line is a
JSON object representing a conversation turn — user messages, assistant
responses, tool use, progress updates, etc.

Assistant response entries include a `usage` block with detailed token
breakdowns:

```json
{
  "input_tokens": 12500,
  "output_tokens": 843,
  "cache_read_input_tokens": 9200,
  "cache_creation_input_tokens": 3100,
  "service_tier": "standard"
}
```

This is the primary data source for claudewatch. The stop hook tail-reads the
active transcript after each response to extract these numbers.

### Memory and context files

Claude Code maintains a layered memory system:

| File | Scope | Purpose |
|------|-------|---------|
| `~/.claude/CLAUDE.md` | Global | User preferences, workflow instructions |
| `<project>/CLAUDE.md` | Project | Project-specific instructions |
| `~/.claude/projects/<project>/memory/MEMORY.md` | Project | Auto-managed notes that persist across sessions |
| `~/.claude/memory/YYYY-MM-DD.md` | Global | Daily session summaries, auto-compacted |

These files are loaded into the context window at session start, consuming
tokens. Claude Code's `/context` slash command shows the breakdown — context
window fill %, free space, autocompact buffer, and per-file token costs — but
this data is only available inside an active session and is **not currently
exposed via CLI or hook metadata**.

### What claudewatch can see vs. what it can't

| Data | Available? | Source |
|------|-----------|--------|
| Per-response token usage | Yes | Transcript JSONL `usage` block |
| Model, session ID, project | Yes | Transcript JSONL entry metadata |
| Cache read/creation tokens | Yes | Transcript JSONL `usage` block |
| Quota/rate-limit events | Yes | Pattern matching on response text |
| Context window fill % | No | Only visible via `/context` in-session |
| Autocompact buffer size | No | Internal to Claude Code |
| Skills/plugin token overhead | No | Internal to Claude Code |
| Memory file token costs | Approximated | File size / ~4 chars per token |

## How claudewatch works

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
4. The TUI uses **watchdog** (FSEvents on macOS, inotify on Linux) to detect the new line and update all widgets in real-time

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

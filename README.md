# claudewatch

Real-time TUI dashboard for monitoring Claude Code token usage, costs, and context health.

## Features
The goal of this tool is to make Claude Code token usage and quotas more transparent. Visibility into token flow can 
help spot waste: oversized memory files, poor cache utilization, and runaway sessions all become more obvious when you 
can see them happening.

This tool provides:

- **Live monitoring** - watches your Claude Code usage in real-time via a Stop hook
- **Token tracking** - input, output, cache read/write tokens broken down by model and project
- **Cost estimates** - per-session and daily cost estimates using current API pricing
- **Context health** - cache efficiency, memory file sizes, autocompact history, quota events
- **Historical backfill** - imports all your past Claude Code session data
- **Sparkline timeline** - hourly/daily usage trends + per-session context growth curves

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
JSON object representing a conversation turn: user messages, assistant
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

This is the primary data source for claudewatch. A Claude Code stop [hook](https://code.claude.com/docs/en/hooks) tail-reads the
active transcript after each response to extract these numbers.

### Memory and context files

Claude Code maintains a layered memory system:

| File | Scope | Purpose |
|------|-------|---------|
| `~/.claude/CLAUDE.md` | Global | User preferences, workflow instructions |
| `<project>/CLAUDE.md` | Project | Project-specific instructions |
| `~/.claude/projects/<project>/memory/MEMORY.md` | Project | Auto-managed notes that persist across sessions |

These files are loaded into the context window at session start, consuming
tokens. Claude Code's `/context` slash command shows the breakdown-- context
window fill %, free space, autocompact buffer, and per-file token costs-- but
this data is only available inside an active session and is not currently
exposed via CLI or hook metadata.

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

## How Claude Code rate limiting works

Claude Code (Max subscription) uses a **rolling 5-hour window** for rate limiting,
not fixed time blocks. At any given moment, Anthropic measures total token usage
over the previous 5 hours. There's no "reset" at a specific clock time: tokens
continuously age out as the window slides forward.

For example: if you burn through a lot of tokens between 6:00-7:00am, those tokens
start dropping off between 11:00-12:00pm. This means your available capacity gradually
recovers rather than resetting all at once.

The **5h window gauge** in the Context Health panel tracks this: it shows your current
rolling-window usage against an estimated ceiling derived from your most recent quota
hit. The ceiling is approximate since Anthropic doesn't expose exact limits.

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
|       Today's Usage        |      Context Health        |
|  tokens by type + model    |  memory sizes, cache ratio |
|  cost estimate             |  5h window gauge, quota    |
+----------------------------+----------------------------+
|       Timeline             |      Context Growth        |
|  24h / 30d sparklines      |  per-session sparklines    |
|  burn rate                 |  with y-axis labels        |
+----------------------------+----------------------------+
|       Session List         |       Event Log            |
|  DataTable, sortable       |  live scrolling feed       |
+----------------------------+----------------------------+
```

**Keybindings:** `q` quit, `r` refresh

## Understanding the panels

### Today's Usage (top left)

Token totals for the day, broken down by type (input, output, cache read, cache write)
and by model. The API cost estimate uses current Anthropic pricing and reflects what
you'd pay if you were on the API directly: not what you pay for a Claude Code
subscription, which is flat-rate.

### Context Health (top right)

A machine-wide snapshot of what's eating your context window and how efficiently caching
is working. The header says "(all projects)" because this panel aggregates across every
Claude Code project on the machine, not just one session.

Claude Code caches the conversation prefix (system prompt, memory files, prior turns) server-side 
between API calls. Cache reads are ~10x cheaper than regular input tokens, so a well-cached session 
dramatically reduces cost. 

- **Latest session** - the most recent session from today's data, showing session slug (or
  truncated ID), project name, and model. This tells you which session the cache ratio
  and today's numbers are most influenced by.
- **Memory file sizes** - grouped by project. Lists every CLAUDE.md and MEMORY.md that
  Claude Code loads into context, with estimated token counts. Each project shows its
  subtotal, plus a grand total at the bottom. These files are loaded every turn, so bloated 
  memory burns tokens fast. If your total is high, you could possibly review your CLAUDE.md and MEMORY.md files 
  for stale or redundant content and remove what you don't need.
- **Cache ratio** - the percentage of cache tokens that are *reads* (reused from a previous
  turn) vs *writes* (freshly created). Higher is better. 90%+ means Claude is efficiently
  reusing your system prompt and conversation prefix from cache rather than re-tokenizing
  it each turn. Cache reads cost ~10x less than cache creation and ~10x less than regular
  input tokens. The ratio drops when you switch projects (different cached prefix), when
  memory files change (invalidates cache), or on the first turn of a session. Computed
  over today's records only.
- **Autocompacts** - counts of `pre-compact-*.md` files across your projects. These are
  snapshots Claude Code saves before auto-compacting memory files that exceed the 200-line
  limit. Frequent autocompacts mean your memory is growing fast.
- **5h window gauge** - rolling-window usage bar showing current token usage vs estimated
  ceiling. The ceiling is estimated from your most recent quota hit. Color-coded: green
  (< 60%), yellow (60-85%), red (> 85%). If no quota hits have been recorded yet, shows
  the raw token total instead.
- **Quota info** - if you've hit a rate limit or quota cap, shows the event type and how
  long ago. Only appears when there's something to show.

> **Note:** claudewatch only monitors Claude Code (the CLI tool). It cannot see usage from
> claude.ai (the web/desktop chat). The "X% used" meter in claude.ai is a subscription
> allocation gauge that's tracked server-side and not exposed to local tooling.

### Timeline (middle left)

Sparkline charts showing usage over time. Each character is one time bucket (hour or day),
and bar height is proportional to the peak within that section. 

Input and output tokens are priced 
differently and behave differently: input grows predictably as your context accumulates, while output 
depends on what you're asking Claude to do. A spike in output tokens usually means Claude is generating 
large code blocks or verbose explanations, which is the most expensive token type. Tracking them separately 
helps you see whether cost is driven by long conversations (input) or heavy generation (output). 

- **24h** - rolling hourly buckets with hour-of-day labels on the x-axis. Green = input
  tokens (includes cache reads), yellow = output tokens.
- **30d** - daily buckets over the last month with date labels.
- **Burn rate** - tokens per hour averaged over the last 3 hours of activity.

### Context Growth (middle right)

Per-session sparklines showing how `input_tokens` increases across turns within a session.
In a Claude Code session, input tokens grow as the conversation gets longer (more context
to send each turn). A steadily rising line is normal. A line that plateaus near 200K means
you're approaching the context ceiling and Claude Code may start auto-compacting.

Each line represents one of the most recent sessions (up to 5). The y-axis runs from 0 to the session's 
peak context size. Sessions with only a single turn are excluded. Sessions are labeled by
slug (if available)-- a short human-readable name that Claude Code auto-generates for each session 
(like "bright-noodling-karp")-- or session ID.

### Session List (bottom left)

A table of all sessions, most recent first. Shows the session slug or a truncated session UUID if no 
slug is available.
Columns: session name, project, model, message count, total tokens, duration, and time.

### Event Log (bottom right)

Live feed of events with color-coded tags. On startup, shows a summary of today's sessions,
cost, model mix, biggest session, cache ratio, and window proximity warnings. During use,
logs new usage records, session switches, model changes, output token spikes (> 5K), quota
hits, and manual refreshes.


## License

MIT

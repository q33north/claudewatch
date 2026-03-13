# claudewatch

Real-time TUI dashboard for monitoring Claude Code token usage, costs, and context health.

## Features
The goal of this tool is to make Claude Code token usage and quotas more transparent. Visibility into token flow can 
help spot waste: oversized memory files, poor cache utilization, and runaway sessions all become more obvious when you 
can see them happening.

This tool provides:

- **Live monitoring** - watches your Claude Code usage in real-time via a hooks
- **Token tracking** - input, output, cache read/write tokens broken down by model and project
- **Cost estimates** - per-session and daily cost estimates using current API pricing
- **Context health** - cache efficiency, memory file sizes, autocompact history, quota events
- **Historical backfill** - imports all past Claude Code session data
- **Context growth** - per-session context growth sparklines showing token accumulation per turn

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
# Install the Stop + PostToolUse hooks into Claude Code
claudewatch install

# Backfill historical data (optional but recommended)
claudewatch backfill

# Launch the dashboard
claudewatch watch
```

> **Multi-machine note:** Hook paths in `~/.claude/settings.json` use `~` (tilde) so they
> resolve correctly if you sync settings across machines (e.g. linux + mac). If you installed
> with an older version that wrote absolute paths, run `claudewatch uninstall && claudewatch install`
> to fix it.

## Commands

| Command | Description |
|---------|-------------|
| `claudewatch watch` | Launch the live TUI dashboard |
| `claudewatch backfill` | Import historical session data |
| `claudewatch install` | Install the Stop + PostToolUse hooks into Claude Code |
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

This is the primary data source for claudewatch. Two Claude Code [hooks](https://code.claude.com/docs/en/hooks) -- a
**Stop** hook (fires at session end) and a **PostToolUse** hook (fires after each
tool call) -- tail-read the active transcript to extract these numbers.

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
  [PostToolUse hook fires]  ──or──  [Stop hook fires]
       |
  hook.py: tail-read transcript -> extract usage -> dedup -> append to usage.jsonl
       |
  TUI: watchdog detects file change -> parse new line -> update widgets
```

1. Two hooks fire during Claude Code usage:
   - **PostToolUse** fires after each tool call, giving live updates during agentic loops
   - **Stop** fires when a session ends, capturing the final state
2. Both run the same logic: tail-read the session transcript, extract the usage block (input/output/cache tokens, model, etc.)
3. A dedup check prevents double-counting when multiple PostToolUse hooks fire for the same assistant message (e.g. parallel tool calls)
4. Appends a single line to `~/.claude/claudewatch/usage.jsonl`
5. The TUI uses **watchdog** (FSEvents on macOS, inotify on Linux) to detect the new line and update all widgets in real-time

Both hooks are designed to be fast (<50ms) and never make any API calls.

## Dashboard layout

```
+--------------------+--------------------+--------------------+
|   Today's Usage    |   Context Growth   |   Context Health   |
|  tokens by type    |  per-session       |  memory sizes,     |
|  + model, cost     |  sparklines        |  cache, quota      |
+--------------------+--------------------+--------------------+
|                     Session List                             |
|  sortable table: session, project, model, messages,          |
|  tokens, cost, cache %, duration, time                       |
+--------------------------------------------------------------+
```

**Keybindings:** `q` quit, `r` refresh

## Understanding the panels

### Today's Usage (top left)

Token totals for the day, broken down by type (input, output, cache read, cache write)
and by model. The API cost estimate uses current Anthropic pricing and reflects what
you'd pay if you were on the API directly: not what you pay for a Claude Code
subscription, which is flat-rate.

### Context Growth (top center)

Per-session sparklines showing the total tokens sent to the API on each turn
(input + cache_read + cache_create). Each turn, Claude Code sends the full
conversation prefix to the API. Most of this is typically cache_read (reused
cheaply from prior turns), but the total still reflects the growing size of
your conversation. A steadily rising line is normal. When the underlying
context window approaches 200K tokens, Claude Code auto-compacts.

Note: this is "tokens billed per turn," not "context window fill level."
A turn showing 160K doesn't mean 160K of context is used. It means 160K
tokens were sent to the API, most of which were cache reads. Claude Code's
`/context` command shows actual window fill, but that data isn't available
to external tools.

Each line represents one of the most recent sessions (up to 5). The y-axis
runs from 0 to the session's peak value. Sessions with only a single turn
are excluded. Sessions are labeled by their slug (if available), a short
human-readable name that Claude Code auto-generates for each session (like
"bright-noodling-karp"), or a truncated session ID.

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

### Reading Context Growth and Cache Ratio together

The Context Growth sparkline shows how many tokens are sent per turn. The
Cache Ratio (in Context Health) shows how much of that is cheap. A session
sending 160K tokens/turn with a 97% cache ratio costs roughly the same as
sending 5K tokens without caching. Cache reads are billed at ~10x less than
regular input tokens (e.g. $1.50/M vs $15/M for Opus).

This is why cache efficiency matters so much in long sessions. Without caching,
every turn at 160K tokens would be enormously expensive. With 97% cache hits,
you're only paying full price for ~5K tokens per turn while the other 155K
ride the cache at a 90% discount.

Things that hurt your cache ratio (and your wallet):
- Switching projects mid-session (different cached prefix)
- Editing CLAUDE.md or MEMORY.md (invalidates the cache)
- First turn of a new session (nothing cached yet)
- Auto-compaction (conversation gets rewritten)

### Session List (bottom, full width)

A table of all sessions, most recent first. Shows the session slug or a truncated session UUID if no
slug is available.
Columns: session name, project, model, message count, total tokens, cost, cache %, duration, and time.


## License

MIT

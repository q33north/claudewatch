# Context Anatomy Widget

## Inspiration

Claude Code's built-in `/context` command shows a real-time breakdown of the
current context window: system prompt, tools, memory files, skills, messages,
free space, and autocompact buffer. It uses a colored grid of unicode glyphs
where each cell represents ~2k tokens, color-coded by category. It also lists
individual memory files with their token counts and gives optimization
suggestions (e.g. "Read results using 33.8k tokens, save ~10.1k").

Screenshot reference: `~/tmp/context.png`

## What We'd Build

A TUI widget showing context composition over time, not just a point-in-time
snapshot. Two possible angles:

### Option A: Per-Session Context Anatomy
Show how a session's context fills up over its lifetime. The JSONL entries
already have `input_tokens` which grows as context accumulates. We could
reconstruct the fill curve and show where the big jumps happen (large file
reads, tool results, etc.).

### Option B: Cross-Session Context Budget
Show what percentage of the 200k window is "pre-committed" before you type
anything: system prompt + tools + memory files + skills. This is the overhead
tax. For Pete's setup it's ~8-9% (~17k tokens). Track how this changes as
CLAUDE.md and memory files grow.

### The Grid
The colored grid from `/context` is a great visualization pattern for a Textual
widget. Each cell = N tokens, color-coded by category. Could show it as a
session timeline where cells fill in left-to-right as the session progresses.

## Data Sources

- `input_tokens` from JSONL entries tracks cumulative context growth
- Memory file sizes from `config.find_memory_files()` (already implemented)
- `config.estimate_file_tokens()` already exists
- System prompt / tool token counts would need to be estimated or hardcoded

## Priority

Low -- nice-to-have visualization. The core token counting and quota detection
are more important. But it's a differentiator vs ccusage/toktrack and makes for
great blog content.

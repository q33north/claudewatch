# claudewatch roadmap

## Context Health Widget

**Goal:** Surface context-window and memory insights in the TUI, approximating
what Claude Code's `/context` slash command shows.

### What we can build now

- **Memory file sizes (in tokens):** Stat `~/.claude/CLAUDE.md`, project
  `CLAUDE.md`, and `MEMORY.md` files. Estimate token count at ~4 chars/token.
  Display in a small panel so users can see when their memory files are bloated
  and eating into context budget.

- **Per-session context growth curve:** Each assistant response's
  `input_tokens` reflects the cumulative context window at that point. Plot
  this as a sparkline per session to visualize how fast sessions approach the
  200k ceiling. Flag sessions that are nearing capacity.

- **Cache efficiency ratio:** We already capture `cache_read_input_tokens` and
  `cache_creation_input_tokens`. Show a hit ratio (reads / total cache tokens)
  — high ratios mean the prompt cache is working well, low ratios mean context
  is churning.

### What we can build with minor hook changes

- **Session slug extraction:** The transcript JSONL has a `slug` field
  (human-readable session name) that we don't currently extract. Adding it to
  `UsageRecord` would make the session list much more useful than showing UUIDs.

- **Inference geo tracking:** `inference_geo` in the usage block tells you
  which region handled the request. Could be interesting for latency analysis.

- **Autocompact detection:** When Claude Code autocompacts, it creates
  `pre-compact-YYYY-MM-DD.md` files in the memory directory. We could watch
  for these with watchdog and log compaction events.

### What requires upstream changes (Claude Code)

These would be instant wins if Anthropic exposes the data:

- **Real-time context window fill %** — currently only visible via `/context`
  inside an active session. If exposed in hook input JSON or a CLI command,
  we could show a live gauge.

- **Autocompact buffer size** — the 16.5% reserved for autocompact is
  interesting to track but not in any file we can read.

- **Skills/plugin token costs** — loaded skills consume context tokens (e.g.
  151 tokens for skills, 67 for a plugin). Not exposed outside `/context`.

### Implementation sketch for v0.2

```
+----------------------------+----------------------------+
|       Today's Usage        |       Context Health       |
|  tokens by type + model    |  memory file sizes (tkns)  |
|  cost estimate             |  cache hit ratio           |
+----------------------------+----------------------------+
|              Usage Timeline (sparklines)                |
|  input/output sparklines + context growth per session   |
+--------------------------------------------------------+
|       Session List         |       Event Log            |
|  with slug names           |  + compaction events       |
+----------------------------+----------------------------+
```

Priority order:
1. Memory file token estimates (new widget, easy)
2. Session slug in session list (hook change, easy)
3. Cache efficiency ratio (computed from existing data, easy)
4. Per-session context growth sparkline (new computation, medium)
5. Autocompact event detection (new watchdog target, medium)

## Other ideas

- **Export to CSV/Parquet** — for users who want to analyze usage in R/Python
- **Multi-day cost trend** — daily cost sparkline over 30 days
- **Alert thresholds** — configurable notifications when daily cost or context
  usage exceeds a threshold

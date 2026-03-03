# Agent Team & Multi-Agent Session Support

## The Problem

When Claude Code spawns agent teams (via `TeamCreate` or the Agent tool), each
agent gets its own session ID and transcript. claudewatch sees these as unrelated
sessions. This means:

- A team of 4 agents shows up as 4 independent sessions in the session list
- Cost isn't rolled up to the parent session that spawned the team
- Context growth sparklines don't show the combined burn rate
- The 5h window gauge underestimates your actual velocity toward quota
  (you're burning tokens across N agents simultaneously)
- No way to answer "how much did that team run cost me?"

This gets worse with the crowd-sourced quota feature: a user running 3 agents
in parallel hits their ceiling 3x faster than the single-agent estimate suggests.

## What Claude Code Exposes

| Signal | Available? | Notes |
|--------|-----------|-------|
| Session ID per agent | Yes | each agent has a unique session UUID |
| Parent session ID | No | not in transcript metadata |
| Team name | No | not in transcript metadata |
| Agent spawn timestamp | Indirectly | first record in child session |
| Shared project path | Yes | parent and children share the same project |
| Shared CWD | Mostly | agents may use worktrees with different paths |
| Concurrent timing | Yes | overlapping session timestamps |

The core challenge: Claude Code doesn't tag child sessions with their parent.
We have to infer the relationship.

## Inference Strategy

### Heuristic: Temporal Clustering + Project Matching

A parent session spawns agents. Those agent sessions:
1. Start within seconds of each other
2. Share the same project (usually)
3. Have a parent session that was active just before they appeared
4. Are short-lived relative to the parent
5. Often have slugs that reflect agent roles

Algorithm:

```
for each session S that started in the last N hours:
    candidates = sessions where:
        - same project as S
        - S.start_time is within 30s of candidate.start_time
        - candidate is not S

    if len(candidates) >= 2:
        # likely a team - find the parent
        # parent is the session in the same project that was active
        # just before the cluster started
        cluster_start = min(c.start_time for c in candidates + [S])
        parent = session where:
            - same project
            - has a record within 60s before cluster_start
            - not in the cluster itself

        if parent:
            mark candidates + S as children of parent
```

This won't be perfect, but it covers the common case: user is working in a
session, spawns a team, 3-4 new sessions pop up within seconds for the same
project.

### Confidence Levels

Tag inferred relationships with confidence:

- **high**: 3+ sessions started within 10s, same project, clear parent active before
- **medium**: 2 sessions started within 30s, same project
- **low**: timing matches but different projects (worktree agents)

Only display relationships at medium+ confidence in the UI. Store all of them
for potential manual override.

### User Override

Allow manual parent-child tagging via a config file or CLI command:

```bash
# manually link sessions
claudewatch link-sessions --parent abc123 --children def456,ghi789

# or auto-detect and confirm
claudewatch detect-teams --interactive
```

## Data Model Changes

### UsageRecord

```python
class UsageRecord(BaseModel):
    # ... existing fields ...

    # Agent team support
    parent_session_id: str = ""
    team_id: str = ""           # shared across all members of a team
    agent_role: str = ""        # "lead", "teammate", inferred from slug
    inference_confidence: str = ""  # "high", "medium", "low", "manual"
```

### New Model: SessionTree

```python
class SessionTree(BaseModel):
    """A parent session and its inferred child agent sessions."""

    parent_id: str
    parent_slug: str = ""
    team_id: str = ""
    children: list[SessionChild] = []
    confidence: str = "medium"
    project: str = ""

    @property
    def all_session_ids(self) -> list[str]:
        return [self.parent_id] + [c.session_id for c in self.children]

    @property
    def total_cost(self) -> float:
        """Aggregate cost across the entire team."""
        ...

    @property
    def total_tokens(self) -> int:
        """Aggregate tokens across the entire team."""
        ...


class SessionChild(BaseModel):
    session_id: str
    slug: str = ""
    role: str = ""  # inferred from slug or position
    start_time: datetime
    total_tokens: int = 0
```

### Storage

New JSONL file: `~/.claude/claudewatch/session-trees.jsonl`

Append-only, same pattern as usage.jsonl. Each line is a `SessionTree` that
gets written/updated when team detection runs.

## TUI Changes

### Session List

Add a tree view mode (toggle with `t` key):

**Flat mode (current):**
```
Session              Project      Model       Tokens    Time
bright-noodling-karp claudewatch  opus-4-6    910,256   03/02 19:51
server-builder       claudewatch  opus-4-6    234,567   03/02 19:51
client-worker        claudewatch  sonnet-4-6  189,234   03/02 19:52
tui-updater          claudewatch  sonnet-4-6  145,678   03/02 19:52
```

**Tree mode:**
```
Session              Project      Model       Tokens    Time
▼ bright-noodling-karp            opus-4-6    1,479,735  03/02 19:51
  ├─ server-builder               opus-4-6      234,567  03/02 19:51
  ├─ client-worker                sonnet-4-6    189,234  03/02 19:52
  └─ tui-updater                  sonnet-4-6    145,678  03/02 19:52
```

Parent row shows aggregated tokens/cost across all children.

### Context Growth

Show team aggregate sparkline alongside individual sessions:

```
Context Growth
input tokens/turn (rising = filling window)

▼ bright-noodl ██████████████████████████████  (team aggregate)
               0                          1.5M
  server-buil  ▁▂▃▅▆█▇████████████████████
               0                          400K
  client-work  ▁▂▃▄▅▆▇███████████████
               0                          300K
```

### 5h Window Gauge

When team sessions are detected, show combined burn rate:

```
5h window: ████████░░ 78%  (1.2M / 1.5M crowd est.)
           ↑ includes 3 agent sessions
```

### Event Log

New event types for team detection:

```
19:51:03  Session  team detected: 3 agents + lead (bright-noodling-karp)
19:51:03  Session    ├─ server-builder (opus-4-6)
19:51:03  Session    ├─ client-worker (sonnet-4-6)
19:51:03  Session    └─ tui-updater (sonnet-4-6)
19:55:12  Cost     team burn: $0.47 across 4 sessions (3m elapsed)
```

## Interaction with Crowd-Sourced Quotas

Team usage matters for quota estimation:

1. **Contribution payloads** should include a `team_session_count` field so the
   server knows this quota hit came from parallel agent usage

2. **Ceiling estimates** could eventually be segmented:
   - single-agent ceiling: ~1.5M tokens/5h
   - team ceiling: might be different (shared quota? per-agent quota?)
   - we won't know until we have crowd data from team users

3. **Window gauge accuracy** - the gauge currently sums all usage in the 5h
   window regardless of session. this is actually correct for quota purposes
   (Anthropic likely counts all your sessions together). team detection just
   makes the display clearer about where the tokens are going.

## Implementation Phases

### Phase 1: Inference Engine
**Effort: 1 day**

- [ ] New module: `src/claudewatch/teams/detector.py`
- [ ] `detect_teams(records: list[UsageRecord]) -> list[SessionTree]`
- [ ] Temporal clustering algorithm with configurable thresholds
- [ ] Confidence scoring
- [ ] Tests with synthetic multi-agent session data
- [ ] Storage: `session-trees.jsonl` read/write

### Phase 2: Data Model
**Effort: half day**

- [ ] Add `parent_session_id`, `team_id`, `agent_role` to UsageRecord
- [ ] SessionTree and SessionChild models
- [ ] Backfill command: `claudewatch detect-teams` to scan existing data
- [ ] Migration: existing records get empty team fields (backward compatible)

### Phase 3: Session List Tree View
**Effort: 1 day**

- [ ] Toggle between flat/tree mode (`t` key binding)
- [ ] Aggregate row for parent showing team totals
- [ ] Indented child rows with tree connectors
- [ ] Sort: teams grouped together, sorted by parent timestamp

### Phase 4: Gauge & Growth Integration
**Effort: half day**

- [ ] Context growth: team aggregate sparkline
- [ ] Window gauge: annotation showing agent count
- [ ] Event log: team detection events with member list

### Phase 5: Manual Override
**Effort: half day**

- [ ] `claudewatch link-sessions` CLI command
- [ ] `claudewatch detect-teams --interactive` for review/confirm
- [ ] Override storage in session-trees.jsonl (manual entries have confidence="manual")

## Total Effort Estimate

| Phase | Work | Cumulative |
|-------|------|------------|
| 1: Inference engine | 1 day | 1 day |
| 2: Data model | 0.5 day | 1.5 days |
| 3: Tree view | 1 day | 2.5 days |
| 4: Gauge integration | 0.5 day | 3 days |
| 5: Manual override | 0.5 day | 3.5 days |

## Open Questions

1. **Does Anthropic share quota across agents?** If each agent in a team has
   its own rate limit (unlikely but possible), the gauge math changes entirely.
   Crowd-sourced data from team users would answer this.

2. **Worktree agents** - agents spawned with `isolation: "worktree"` work in
   a different directory. The project path might differ. Need to handle this
   in the clustering logic (maybe match on base repo path).

3. **Nested teams** - an agent could theoretically spawn its own sub-team.
   The inference engine should handle arbitrary depth, but the UI probably
   only needs to show 2 levels (parent + children).

4. **Agent SDK sessions** - if someone uses the Claude Agent SDK (not Claude
   Code), those sessions won't have transcripts in `~/.claude/projects/`.
   Out of scope for now, but worth noting.

5. **Performance** - team detection scans all records looking for temporal
   clusters. Fine for hundreds of sessions, but might need indexing or
   caching if someone has thousands. Run detection incrementally (only check
   new sessions since last run).

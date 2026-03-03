# Crowd-Sourced Quota Estimation

## The Problem

Claude Code (Max) rate-limits users on a rolling 5-hour window, but Anthropic
doesn't publish the actual token ceilings. Right now claudewatch tries to estimate
your ceiling from your own most recent quota hit, but:

- If you've never hit a quota, there's no estimate at all
- The local estimate is based on a single datapoint (your last hit)
- The `cumulative_input`/`cumulative_output` on quota events are often
  unreliable (we've seen ceilings of "11 tokens")

A crowd-sourced approach pools anonymous quota-hit data from all opted-in users
to produce a statistically meaningful ceiling estimate per subscription tier
and model.

## Architecture

```
┌─────────────────────────────┐
│     claudewatch client      │
│                             │
│  quota hit detected locally │
│         │                   │
│  (opted in?) ── no ── skip  │
│         │                   │
│        yes                  │
│         │                   │
│  POST /api/v1/contribute    │
│  (anonymous, fire & forget) │
│         │                   │
│  GET /api/v1/ceilings       │◄── heartbeat poll every 60s
│  (cached locally)           │
│         │                   │
│  dashboard shows crowd      │
│  ceiling in gauge           │
└─────────────────────────────┘
              │  ▲
              ▼  │
┌─────────────────────────────┐
│     quota.q33north.com      │
│                             │
│  FastAPI + SQLite           │
│                             │
│  /api/v1/contribute  POST   │  ← receives anonymous quota hits
│  /api/v1/ceilings    GET    │  ← returns aggregated estimates
│  /api/v1/health      GET    │  ← uptime check
│  /api/v1/stats       GET    │  ← public contributor stats
│                             │
│  Aggregation worker:        │
│  - rolling 7-day window     │
│  - median, p25, p75, p95    │
│  - per (tier, model) combo  │
│  - outlier filtering (IQR)  │
└─────────────────────────────┘
```

## Anonymous Contribution Payload

What gets sent on a quota hit (if opted in):

```json
{
  "schema_version": 1,
  "timestamp": "2026-03-02T18:30:00Z",
  "tier": "max_5",
  "model": "claude-opus-4-6",
  "event_type": "rate_limit",
  "window_tokens": {
    "input": 450000,
    "output": 28000,
    "cache_read": 380000,
    "cache_create": 42000,
    "total": 900000
  },
  "window_hours": 5.0,
  "window_record_count": 47,
  "client_version": "0.3.0"
}
```

What is explicitly NOT sent:
- No user ID, session ID, or any identifier
- No project names or file paths
- No IP logging on the server (reverse proxy strips it)
- No message content
- No fingerprinting data

## Ceiling Response

```json
{
  "updated_at": "2026-03-02T18:35:00Z",
  "ceilings": {
    "max_5": {
      "claude-opus-4-6": {
        "median": 1200000,
        "p25": 950000,
        "p75": 1450000,
        "p95": 1800000,
        "sample_size": 234,
        "window_days": 7
      },
      "claude-sonnet-4-6": {
        "median": 3500000,
        "p25": 2800000,
        "p75": 4200000,
        "p95": 5000000,
        "sample_size": 412,
        "window_days": 7
      }
    },
    "max_20": {
      "claude-opus-4-6": {
        "median": 4800000,
        "p25": 3900000,
        "p75": 5500000,
        "p95": 6200000,
        "sample_size": 156,
        "window_days": 7
      }
    }
  },
  "contributors_7d": 892,
  "total_contributions": 14203
}
```

## Server Design

### Tech Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Framework | FastAPI | async, fast, pydantic-native (matches client models) |
| Database | SQLite + WAL mode | simple, no separate DB server, handles this scale easily |
| ORM | none, raw SQL | two tables, not worth the abstraction |
| Deployment | fly.io | free tier covers this, global edge, easy SSL, $0/mo to start |
| CI/CD | GitHub Actions | auto-deploy on push to main |

### Why fly.io

- **Free tier**: 3 shared VMs, 3GB storage, 160GB outbound - more than enough
- **Global edge**: users hit the nearest region automatically
- **Persistent volumes**: SQLite file survives deploys
- **Simple deploys**: `fly deploy` from CI, dockerfile-based
- **SSL built-in**: `quota.q33north.com` with automatic certs
- **Scaling path**: if this takes off, scale up without re-architecting

Alternatives considered:
- **Railway**: similar but less generous free tier
- **Lambda + DynamoDB**: overkill, cold starts hurt the heartbeat pattern
- **VPS (Hetzner)**: cheapest at scale but more ops overhead
- **Cloudflare Workers + D1**: interesting but SQLite-over-HTTP is awkward for this

### Database Schema

```sql
CREATE TABLE contributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    tier TEXT NOT NULL,
    model TEXT NOT NULL,
    event_type TEXT NOT NULL,
    total_tokens INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL,
    cache_create_tokens INTEGER NOT NULL,
    window_hours REAL NOT NULL DEFAULT 5.0,
    window_record_count INTEGER NOT NULL DEFAULT 0,
    client_version TEXT NOT NULL DEFAULT '0.0.0',
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX idx_contributions_tier_model ON contributions(tier, model);
CREATE INDEX idx_contributions_received ON contributions(received_at);

-- Pre-computed aggregates, refreshed every 5 minutes
CREATE TABLE ceiling_estimates (
    tier TEXT NOT NULL,
    model TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    sample_size INTEGER NOT NULL,
    median_tokens INTEGER NOT NULL,
    p25_tokens INTEGER NOT NULL,
    p75_tokens INTEGER NOT NULL,
    p95_tokens INTEGER NOT NULL,
    window_days INTEGER NOT NULL DEFAULT 7,
    PRIMARY KEY (tier, model)
);
```

### API Endpoints

**POST /api/v1/contribute**
- Validates payload against pydantic model
- Basic rate limiting: max 10 contributions per IP per hour (IP not stored, just counted)
- Outlier rejection: tokens < 1000 or > 50M are dropped
- Returns 202 Accepted (fire and forget from client's perspective)

**GET /api/v1/ceilings**
- Returns pre-computed aggregates from `ceiling_estimates` table
- Cache-Control header: `max-age=60` (client polls every 60s anyway)
- Tiny response, fast to serve

**GET /api/v1/health**
- Returns `{"status": "ok", "db_size_mb": 1.2, "uptime_seconds": 86400}`

**GET /api/v1/stats**
- Public stats: total contributions, unique tiers, models tracked, last 7d contributor count
- Nice for a future landing page or badge in the README

### Aggregation Worker

Runs every 5 minutes (in-process background task via FastAPI lifespan):

```python
async def recompute_ceilings():
    """Recompute ceiling estimates from the last 7 days of contributions."""
    cutoff = datetime.utcnow() - timedelta(days=7)

    for tier, model in get_tier_model_combos(since=cutoff):
        totals = get_contribution_totals(tier, model, since=cutoff)

        # IQR-based outlier filtering
        q1, q3 = percentile(totals, 25), percentile(totals, 75)
        iqr = q3 - q1
        filtered = [t for t in totals if q1 - 1.5*iqr <= t <= q3 + 1.5*iqr]

        if len(filtered) < 5:
            continue  # not enough data

        upsert_ceiling(tier, model,
            median=percentile(filtered, 50),
            p25=percentile(filtered, 25),
            p75=percentile(filtered, 75),
            p95=percentile(filtered, 95),
            sample_size=len(filtered),
        )
```

### Anti-Gaming

- **Rate limiting**: 10 contributions/IP/hour (uses in-memory counter, IP discarded after)
- **IQR outlier filtering**: extreme values are excluded from aggregates
- **Minimum sample size**: need 5+ datapoints per (tier, model) before publishing
- **Schema version**: allows server to reject outdated/malformed payloads
- **No auth required**: the data is low-stakes enough that gaming isn't worth defending
  against heavily. worst case: estimates are slightly off, which is where we already are

## Client Integration

### Phase 1: Settings & Opt-In

New file: `~/.claude/claudewatch/settings.json`

```json
{
  "share_quotas": true,
  "subscription_tier": "max_5",
  "server_url": "https://quota.q33north.com"
}
```

Added during `claudewatch install` with an interactive prompt:

```
claudewatch can share anonymous quota data to help estimate rate limits
for all users. no identifying information is sent. see:
https://github.com/q33north/claudewatch/blob/main/docs/privacy-quota-sharing.md

share anonymous quota data? [y/N]: y

subscription tier:
  1. max_5   ($5/month - Claude Code basic)
  2. max_20  ($20/month - Claude Code standard)
  3. max_100 ($100/month - Claude Code pro)
  4. max_200 ($200/month - Claude Code team/enterprise)
select [1-4]: 2
```

### Phase 2: Hook Integration

When a quota event is detected in `hook.py`, if `share_quotas` is enabled:

1. Read the last 5h of usage records from `usage.jsonl`
2. Aggregate into `window_tokens`
3. Fire-and-forget POST to the server (subprocess or thread, never blocks the hook)

```python
def maybe_contribute(event: QuotaEvent, record: UsageRecord) -> None:
    """Send anonymous contribution if opted in. Non-blocking."""
    settings = load_claudewatch_settings()
    if not settings.get("share_quotas", False):
        return

    records = read_usage()
    tracker = QuotaTracker()
    usage = tracker.estimate_window_usage(records)

    payload = {
        "schema_version": 1,
        "timestamp": event.timestamp.isoformat(),
        "tier": settings["subscription_tier"],
        "model": record.model,
        "event_type": event.event_type,
        "window_tokens": usage,
        "window_hours": 5.0,
        "window_record_count": usage["record_count"],
        "client_version": __version__,
    }

    # Fire and forget - don't block the hook
    threading.Thread(
        target=_post_contribution,
        args=(settings["server_url"], payload),
        daemon=True,
    ).start()
```

### Phase 3: TUI Heartbeat

New background worker in `app.py` alongside the file watcher:

```python
@work(thread=True)
def start_ceiling_poller(self) -> None:
    """Poll the crowd-sourced ceiling API every 60s."""
    settings = load_claudewatch_settings()
    server = settings.get("server_url", "https://quota.q33north.com")

    while not self._shutting_down:
        try:
            resp = httpx.get(f"{server}/api/v1/ceilings", timeout=5)
            if resp.status_code == 200:
                self.post_message(NewCeilingEstimate(resp.json()))
                # Cache locally for offline use
                save_ceiling_cache(resp.json())
        except Exception:
            pass  # network errors are fine, we have local cache

        time.sleep(60)
```

New message type + handler:

```python
class NewCeilingEstimate(Message):
    def __init__(self, data: dict) -> None:
        self.data = data
        super().__init__()

@on(NewCeilingEstimate)
def handle_ceiling_update(self, event: NewCeilingEstimate) -> None:
    self.query_one(ContextHealth).update_crowd_ceiling(event.data)
    self.query_one(EventLog).add_event("Ceiling", "crowd estimate updated")
```

### Phase 4: Dashboard Display

Update the 5h window gauge to prefer crowd-sourced ceiling:

```
5h window: ████████░░ 78%  (1.2M / 1.5M crowd est. n=234)
```

When crowd data is available, show it with sample size. Fall back to local
estimate if server is unreachable and no cache exists. Show source:

- `crowd est. n=234` - using crowd-sourced data (sample size)
- `local est.` - using your own last quota hit
- `no ceiling estimate yet` - no data from either source

## Implementation Phases

### Phase 0: Server MVP (priority: first)
**Effort: 1 day**

- [ ] Create `server/` directory in the claudewatch repo (monorepo)
- [ ] FastAPI app with /contribute, /ceilings, /health endpoints
- [ ] SQLite database with contributions + ceiling_estimates tables
- [ ] Background aggregation task (every 5 min)
- [ ] Dockerfile
- [ ] Basic tests
- [ ] Deploy to fly.io, point `quota.q33north.com` DNS

### Phase 1: Client Opt-In
**Effort: half day**

- [ ] Add `load_claudewatch_settings()` / `save_claudewatch_settings()` to config.py
- [ ] Add `--share-quotas` / `--tier` flags to `claudewatch install`
- [ ] Interactive prompt during install if not specified via flags
- [ ] `claudewatch config` command to view/change settings after install
- [ ] Add `httpx` to dependencies (already async-friendly, lightweight)

### Phase 2: Hook Contribution
**Effort: half day**

- [ ] Add `maybe_contribute()` to hook.py quota detection flow
- [ ] Fire-and-forget POST via daemon thread
- [ ] Log contribution events to event log
- [ ] Handle network errors gracefully (no retries, just skip)
- [ ] Tests with mocked HTTP

### Phase 3: TUI Integration
**Effort: half day**

- [ ] Add `start_ceiling_poller()` background worker to app.py
- [ ] NewCeilingEstimate message type
- [ ] Local ceiling cache file (`~/.claude/claudewatch/ceiling-cache.json`)
- [ ] Update ContextHealth._window_gauge() to prefer crowd ceiling
- [ ] Event log entries for ceiling updates
- [ ] Show data source + sample size in gauge

### Phase 4: Polish
**Effort: half day**

- [ ] Privacy doc (docs/privacy-quota-sharing.md)
- [ ] README section on crowd-sourced quotas
- [ ] `claudewatch status` command: show opt-in status, last contribution, server health
- [ ] Rate limiting on server
- [ ] Landing page at quota.q33north.com (optional, stretch goal)

## Total Effort Estimate

| Phase | Work | Cumulative |
|-------|------|------------|
| 0: Server MVP | 1 day | 1 day |
| 1: Client opt-in | 0.5 day | 1.5 days |
| 2: Hook contribution | 0.5 day | 2 days |
| 3: TUI integration | 0.5 day | 2.5 days |
| 4: Polish | 0.5 day | 3 days |

## Open Questions

1. **Subscription tier detection** - is there any way to auto-detect this from
   Claude Code config, or does the user always have to self-report?

2. **Cache tokens in ceiling calc** - should the ceiling estimate use total tokens
   (including cache) or just input+output? cache_read tokens are ~10x cheaper and
   may not count the same toward rate limits.

3. **Multiple models per window** - if someone uses opus for 3h then switches to
   sonnet, the 5h window has mixed model usage. should we track per-model or
   aggregate? probably per-model for the ceiling, aggregate for the gauge.

4. **Server costs at scale** - fly.io free tier is fine for hundreds of users.
   at thousands, we're looking at maybe $5-10/mo. worth it for the project's
   visibility, but good to plan for.

5. **Data retention** - how long to keep raw contributions? 30 days is probably
   enough since we only use 7 days for aggregates. auto-purge older data.

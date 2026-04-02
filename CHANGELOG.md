# Changelog

All notable changes to claudewatch are documented here.
This file also serves as persistent memory across Claude Code sessions,
tracking what worked, what failed, and why decisions were made.

## [0.2.0] - In Progress

### Goal
Multi-machine dashboard with central ingest server.

### Phase 1: SQLite Storage
- **Status:** COMPLETE (2026-04-02)
- Added `machine_id` field to UsageRecord and QuotaEvent (default: hostname)
- Created `storage/sqlite.py`: init_db, insert/read for usage and quota, active sessions, migration
- WAL mode + busy_timeout for concurrent write safety
- 16 tests, all passing (including concurrent insert stress test with 10 threads x 20 records)
- Existing 69 tests unaffected by model changes (machine_id has default_factory)

### Phase 2: Server (FastAPI)
- **Status:** COMPLETE (2026-04-02)
- Created `server/app.py` with `create_app()` factory pattern
- Endpoints: POST /api/usage, POST /api/quota, GET /api/sessions/active, GET /api/usage/today, GET /api/usage/session/{id}, GET /api/health
- Bearer token auth on all endpoints except health check
- `claudewatch serve` command: auto-generates token, defaults to localhost:8420
- `claudewatch connect <url> --token <token>`: one-time client setup, saves to server.json, does health check
- Default host is 127.0.0.1 (localhost only) for safety; --host 0.0.0.0 to expose
- fastapi, uvicorn, httpx added as optional [server] deps in pyproject.toml
- 17 tests covering auth, CRUD, multi-machine tagging, edge cases

### Phase 3: Hook Push
- **Status:** COMPLETE (2026-04-02)
- Created `collector/push.py`: fire-and-forget HTTP push with 2s timeout
- `maybe_push()` called from hook after local JSONL write
- Config loaded from `~/.claude/claudewatch/server.json` (shared with serve/connect)
- All errors silently swallowed - local JSONL is source of truth
- 10 tests: push success, auth header, timeout behavior, server down, machine_id, config loading, hook coexistence with memsearch

### Phase 4: TUI Refactor
- **Status:** NOT STARTED

### Phase 5: Integration
- **Status:** NOT STARTED

---

## [0.1.0] - 2026-03-31

### Added
- Initial release: single-machine TUI dashboard
- Hook-based data collection (Stop + PostToolUse)
- JSONL storage with file watching (watchdog)
- Backfill from historical Claude Code sessions
- Widgets: TodayUsage, ContextGrowth (sparklines), ContextHealth, SessionList
- Context grid widget (ported from Claude Code /context display)
- Quota detection and tracking
- CLI: watch, backfill, install, uninstall, summary, version

### Architecture Decisions
- Chose JSONL for simplicity in v0.1 (append-only, human-readable)
- Chose watchdog over inotify for cross-platform compat
- Textual for TUI (Rich rendering, CSS layout, reactive data)
- Pydantic v2 for all data models

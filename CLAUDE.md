# claudewatch

Real-time TUI dashboard for Claude Code token usage monitoring.
Multi-machine, multi-session aware.

## Project Overview

**Current state:** v0.1.0 alpha. Single-machine dashboard with local JSONL storage,
hook-based data collection, and a Textual TUI with sparklines, context grid, and
session list.

**Target state:** v0.2.0. Multi-machine dashboard with a central ingest server,
per-session context grids, and aggregated usage views. Any machine running Claude Code
can push usage data to the dashboard via hooks.

## Architecture (v0.2.0)

```
Machine A (hook fires) ---POST /api/usage---> claudewatch serve (FastAPI + SQLite)
Machine B (hook fires) ---POST /api/usage--->        |
                                                     v
                                              TUI reads from server
                                              (or local SQLite)
```

**Key design decisions:**
- FastAPI + uvicorn for the server (lightweight, async, typed)
- SQLite for multi-writer storage (replaces JSONL for server mode)
- Hooks push data; no polling or pull model
- A session is "active" if it posted data within the last 10 minutes
- TUI can run in two modes: local (existing JSONL) or server (reads from API)
- Machine identity via hostname in the payload

## Stack

- Python 3.11+, pydantic v2, typer, textual, watchdog
- FastAPI + uvicorn (new, for server)
- SQLite via stdlib sqlite3 (new, for server storage)
- httpx (new, for async HTTP in hooks)

## Success Criteria

1. `claudewatch serve` starts a server that accepts usage records via POST
2. `claudewatch install --server <url>` configures hooks to push to a remote server
3. The TUI shows a 4-panel grid: top-left = aggregated today usage, other 3 = per-session context grids for active sessions
4. Data from 2+ machines appears in the dashboard within seconds of hook firing
5. All existing tests continue to pass
6. Each implementation phase has its own test suite written BEFORE the code (test oracle)

## Implementation Plan

### Phase 1: Storage layer - SQLite backend
> **Status: COMPLETE**

Add a SQLite storage module alongside the existing JSONL. This is the foundation
for multi-machine support since SQLite handles concurrent writes.

**Tasks:**
- [x] 1.1 Create `src/claudewatch/storage/sqlite.py` with:
  - `init_db(path)` - create tables (usage_records, quota_events)
  - `insert_usage(db_path, record)` - write a record
  - `insert_quota_event(db_path, event)` - write an event
  - `read_usage(db_path, since, machine_id)` - filtered reads
  - `read_active_sessions(db_path, minutes)` - sessions with recent activity
  - `read_today_usage(db_path)` - today's records
- [x] 1.2 Add `machine_id: str` field to `UsageRecord` and `QuotaEvent` models (default: hostname)
- [x] 1.3 Write migration helper: `migrate_jsonl_to_sqlite()` for existing data

**Test oracle (write these FIRST):**
- `tests/test_sqlite_storage.py`:
  - `test_init_creates_tables` - verify schema after init_db
  - `test_insert_and_read_usage` - round-trip a UsageRecord
  - `test_insert_and_read_quota_event` - round-trip a QuotaEvent
  - `test_read_usage_filters_by_machine` - machine_id filtering works
  - `test_read_usage_filters_by_since` - date filtering works
  - `test_read_active_sessions` - returns sessions with recent timestamps
  - `test_read_active_sessions_excludes_stale` - old sessions not returned
  - `test_migrate_jsonl_to_sqlite` - existing JSONL data migrates correctly
  - `test_concurrent_inserts` - threaded writes don't corrupt (WAL mode)

---

### Phase 2: Server - FastAPI ingest + query API
> **Status: NOT STARTED**

HTTP server that accepts usage records and serves them to the TUI.

**Tasks:**
- [ ] 2.1 Create `src/claudewatch/server/__init__.py` and `src/claudewatch/server/app.py`:
  - `POST /api/usage` - accepts UsageRecord JSON, stores in SQLite
  - `POST /api/quota` - accepts QuotaEvent JSON
  - `GET /api/sessions/active` - returns active sessions (last 10 min)
  - `GET /api/usage/today` - returns today's aggregated usage
  - `GET /api/usage/session/{session_id}` - returns records for a session
  - `GET /api/health` - server health check
- [ ] 2.2 Add `claudewatch serve` CLI command (typer):
  - `--host` (default 0.0.0.0), `--port` (default 8420), `--db` (default ~/.claude/claudewatch/server.db)
- [ ] 2.3 Add request models: `UsageRecordCreate` (UsageRecord + machine_id)

**Test oracle (write these FIRST):**
- `tests/test_server.py`:
  - `test_health_endpoint` - GET /api/health returns 200
  - `test_post_usage` - POST a record, verify 201
  - `test_post_usage_invalid` - bad payload returns 422
  - `test_post_quota` - POST a quota event
  - `test_get_active_sessions` - returns sessions after posting records
  - `test_get_active_sessions_empty` - no data returns empty list
  - `test_get_today_usage` - returns today's records only
  - `test_get_session_records` - returns records for specific session
  - `test_multi_machine_isolation` - records from different machines are tagged correctly
  - Use `httpx.AsyncClient` + `TestClient` from FastAPI for all tests

---

### Phase 3: Hook modification - push to server
> **Status: NOT STARTED**

Modify the existing hook to optionally POST records to a remote server.

**Tasks:**
- [ ] 3.1 Add `server_url: str | None` to claudewatch config (stored in `~/.claude/claudewatch/config.json`)
- [ ] 3.2 Create `src/claudewatch/collector/push.py`:
  - `push_record(record: UsageRecord, server_url: str)` - POST to server (fire-and-forget, non-blocking)
  - Uses httpx with short timeout (2s), fails silently (don't block Claude Code)
- [ ] 3.3 Modify `collector/hook.py` to call `push_record()` after writing local JSONL (if server_url configured)
- [ ] 3.4 Add `claudewatch install --server <url>` flag to configure the server URL
- [ ] 3.5 Add `claudewatch connect <url>` command to set server URL without reinstalling hooks

**Test oracle (write these FIRST):**
- `tests/test_push.py`:
  - `test_push_record_success` - mock server, verify POST payload
  - `test_push_record_timeout` - slow server doesn't block (completes in <3s)
  - `test_push_record_server_down` - connection refused doesn't raise
  - `test_push_includes_machine_id` - payload includes hostname
  - `test_hook_pushes_when_configured` - end-to-end: hook writes JSONL AND pushes
  - `test_hook_skips_push_when_no_server` - no server_url = local-only behavior preserved
  - `test_install_preserves_existing_hooks` - other hooks (e.g. memsearch) not clobbered
  - `test_uninstall_preserves_other_hooks` - removing claudewatch leaves other hooks intact

---

### Phase 4: TUI refactor - 4-panel grid layout
> **Status: NOT STARTED**

Redesign the TUI to show aggregated usage + per-session context grids.

**Tasks:**
- [ ] 4.1 Create `src/claudewatch/tui/widgets/session_grid.py` - container that manages N context grids:
  - Discovers active sessions from server or local data
  - Renders up to 3 ContextGrid widgets dynamically (4th panel = TodayUsage)
  - Handles the case of 0, 1, 2, 3, or 4+ active sessions gracefully
- [ ] 4.2 Refactor `app.py` compose() to use 2x2 grid layout:
  - Top-left: TodayUsage (aggregated across all machines)
  - Top-right, bottom-left, bottom-right: ContextGrid per active session
  - If <3 sessions: show placeholder or expand existing grids
- [ ] 4.3 Update `dashboard.tcss` for 2x2 grid layout (equal-sized panels)
- [ ] 4.4 Add data source abstraction: `DataSource` protocol with `LocalDataSource` and `ServerDataSource` implementations
  - `LocalDataSource`: reads JSONL (existing behavior)
  - `ServerDataSource`: reads from server API via httpx
- [ ] 4.5 Wire TUI to use `ServerDataSource` when `--server` flag is passed to `claudewatch watch`

**Test oracle (write these FIRST):**
- `tests/test_session_grid.py`:
  - `test_discovers_active_sessions` - with 3 sessions, returns 3
  - `test_max_three_grids` - with 5 sessions, shows 3 most recent
  - `test_no_sessions_shows_placeholder` - empty state renders
- `tests/test_data_source.py`:
  - `test_local_source_reads_jsonl` - existing behavior preserved
  - `test_server_source_fetches_api` - mocked server returns records
  - `test_server_source_handles_failure` - falls back gracefully

---

### Phase 5: Integration + polish
> **Status: NOT STARTED**

End-to-end testing, docs, and release prep.

**Tasks:**
- [ ] 5.1 Integration test: start server, push from 2 mock machines, verify TUI shows both
- [ ] 5.2 Add `--server` flag to `claudewatch watch` command
- [ ] 5.3 Update pyproject.toml: add fastapi, uvicorn, httpx to dependencies
- [ ] 5.4 Update README with multi-machine setup instructions
- [ ] 5.5 Version bump to 0.2.0

**Test oracle:**
- `tests/test_integration.py`:
  - `test_full_pipeline` - server + 2 pushers + query = correct aggregation
  - `test_session_goes_inactive` - session disappears after timeout
  - `test_existing_local_mode_unchanged` - `claudewatch watch` without --server works as before

---

## Operational Instructions

These instructions govern how Claude Code should work on this project:

1. **Test oracle first.** Before implementing any phase, write the full test file.
   Tests should fail (red) until the implementation is done.
2. **Run `pytest tests/ -x -q` before every commit.** Never commit code that breaks
   existing passing tests.
3. **Commit and push after every meaningful unit of work.** A "unit" is roughly one
   task checkbox above.
4. **Update CHANGELOG.md after completing each task.** Record what was done, what
   failed, and any design decisions that changed.
5. **Update this file** if the plan changes. Mark task checkboxes, update phase status.
6. **Keep the ralph loop going.** After finishing a task, check: "Are the tests green?
   Did I update CHANGELOG.md? Is the next task clear?" If yes, proceed. If not, fix.
7. **Preserve existing functionality.** Local-only mode must keep working. Don't break
   the hook -> JSONL -> TUI pipeline.

## File Map

```
src/claudewatch/
  cli.py              - CLI entry point (typer)
  config.py           - Paths, pricing, helpers
  models.py           - Pydantic models (UsageRecord, QuotaEvent, etc.)
  collector/
    hook.py           - Stop/PostToolUse hook handler
    backfill.py       - Historical session scanner
    push.py           - [NEW] HTTP push to server
  storage/
    jsonl.py          - Append-only JSONL storage
    sqlite.py         - [NEW] SQLite storage backend
  server/
    __init__.py       - [NEW]
    app.py            - [NEW] FastAPI server
  quota/
    detector.py       - Quota event detection
  tui/
    app.py            - Main Textual app
    dashboard.tcss    - Layout CSS
    widgets/
      today_usage.py  - Aggregated daily usage
      context_grid.py - Claude Code-style token grid
      context_health.py - Memory/cache health
      session_grid.py - [NEW] Multi-session grid container
      session_list.py - Session table
      timeline.py     - Sparkline utilities
```

"""Configuration, paths, and pricing defaults for claudewatch."""

from __future__ import annotations

from pathlib import Path

# Storage paths
CLAUDE_DIR = Path.home() / ".claude"
CLAUDEWATCH_DIR = CLAUDE_DIR / "claudewatch"
USAGE_JSONL = CLAUDEWATCH_DIR / "usage.jsonl"
QUOTA_EVENTS_JSONL = CLAUDEWATCH_DIR / "quota-events.jsonl"
HOOKS_DIR = CLAUDE_DIR / "hooks"
HOOK_SCRIPT = HOOKS_DIR / "claudewatch-stop.sh"
POSTTOOL_HOOK_SCRIPT = HOOKS_DIR / "claudewatch-posttool.sh"
SETTINGS_JSON = CLAUDE_DIR / "settings.json"
PROJECTS_DIR = CLAUDE_DIR / "projects"

# Per-million-token pricing (USD) as of Feb 2026
# https://docs.anthropic.com/en/docs/about-claude/pricing
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.5,
        "cache_create": 18.75,
    },
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.3,
        "cache_create": 3.75,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80,
        "output": 4.0,
        "cache_read": 0.08,
        "cache_create": 1.0,
    },
    "default": {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.5,
        "cache_create": 18.75,
    },
}

# Quota detection patterns (found in assistant message content)
QUOTA_PATTERNS: list[dict[str, str]] = [
    {"pattern": "hit your limit", "event_type": "quota_hit"},
    {"pattern": "overloaded_error", "event_type": "rate_limit"},
    {"pattern": "rate_limit", "event_type": "rate_limit"},
    {"pattern": "slower responses", "event_type": "slowdown"},
    {"pattern": "capacity constraints", "event_type": "slowdown"},
]

# Context estimation
CHARS_PER_TOKEN = 4
GLOBAL_CLAUDE_MD = CLAUDE_DIR / "CLAUDE.md"

# Server config
SERVER_CONFIG = CLAUDEWATCH_DIR / "server.json"
SERVER_DB = CLAUDEWATCH_DIR / "server.db"
DEFAULT_PORT = 8420

# Tail-read settings
TAIL_CHUNK_SIZE = 8192  # 8KB chunks for backwards reading


def ensure_dirs() -> None:
    """Create storage directories if they don't exist."""
    CLAUDEWATCH_DIR.mkdir(parents=True, exist_ok=True)


def decode_project_dir(dirname: str) -> str:
    """Decode a Claude project directory name to a human-readable project name.

    e.g. '-home-pabsju-Q33North' -> 'Q33North'
    """
    parts = dirname.strip("-").split("-")
    # Take last meaningful segment
    if parts:
        return parts[-1]
    return dirname


def project_from_cwd(cwd: str) -> str:
    """Extract a short project name from a working directory path."""
    p = Path(cwd)
    return p.name if p.name else "unknown"


def estimate_file_tokens(path: Path) -> int:
    """Estimate token count from file size. Returns 0 if file is missing."""
    try:
        return path.stat().st_size // CHARS_PER_TOKEN
    except (FileNotFoundError, OSError):
        return 0


def find_memory_files() -> list[tuple[str, Path]]:
    """Find all CLAUDE.md and MEMORY.md files that contribute to context.

    Returns (label, path) tuples.
    """
    files: list[tuple[str, Path]] = []

    # Global CLAUDE.md
    if GLOBAL_CLAUDE_MD.exists():
        files.append(("global CLAUDE.md", GLOBAL_CLAUDE_MD))

    if not PROJECTS_DIR.exists():
        return files

    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        project_name = decode_project_dir(project_dir.name)

        # Project-level CLAUDE.md
        project_claude = project_dir / "CLAUDE.md"
        if project_claude.exists():
            files.append((f"{project_name}/CLAUDE.md", project_claude))

        # Memory files
        memory_dir = project_dir / "memory"
        if memory_dir.is_dir():
            memory_md = memory_dir / "MEMORY.md"
            if memory_md.exists():
                files.append((f"{project_name}/MEMORY.md", memory_md))

    return files


def find_memory_files_grouped() -> dict[str, list[tuple[str, Path]]]:
    """Find all context files, grouped by project.

    Returns {"(global)": [(label, path), ...], "ProjectName": [...], ...}.
    """
    groups: dict[str, list[tuple[str, Path]]] = {}

    if GLOBAL_CLAUDE_MD.exists():
        groups["(global)"] = [("CLAUDE.md", GLOBAL_CLAUDE_MD)]

    if not PROJECTS_DIR.exists():
        return groups

    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        project_name = decode_project_dir(project_dir.name)
        project_files: list[tuple[str, Path]] = []

        project_claude = project_dir / "CLAUDE.md"
        if project_claude.exists():
            project_files.append(("CLAUDE.md", project_claude))

        memory_dir = project_dir / "memory"
        if memory_dir.is_dir():
            memory_md = memory_dir / "MEMORY.md"
            if memory_md.exists():
                project_files.append(("MEMORY.md", memory_md))

        if project_files:
            groups[project_name] = project_files

    return groups


def find_autocompact_files() -> list[dict]:
    """Find pre-compact memory snapshots across all projects.

    Returns list of {"project": str, "date": str, "path": Path, "size": int}.
    """
    results: list[dict] = []
    if not PROJECTS_DIR.exists():
        return results

    for compact_file in PROJECTS_DIR.glob("*/memory/pre-compact-*.md"):
        project_name = decode_project_dir(compact_file.parts[-3])
        # Extract date from filename like pre-compact-2026-03-01.md
        stem = compact_file.stem  # pre-compact-2026-03-01
        date_part = stem.replace("pre-compact-", "")
        results.append({
            "project": project_name,
            "date": date_part,
            "path": compact_file,
            "size": compact_file.stat().st_size,
        })

    return sorted(results, key=lambda x: x["date"], reverse=True)

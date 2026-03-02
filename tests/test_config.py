"""Tests for config utilities (token estimation, memory/autocompact discovery)."""

from pathlib import Path

from claudewatch.config import estimate_file_tokens, find_autocompact_files, CHARS_PER_TOKEN


def test_estimate_file_tokens(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("a" * 400)  # 400 chars -> 100 tokens at 4 chars/token
    assert estimate_file_tokens(f) == 400 // CHARS_PER_TOKEN


def test_estimate_file_tokens_missing(tmp_path):
    missing = tmp_path / "nope.md"
    assert estimate_file_tokens(missing) == 0


def test_find_autocompact_files(tmp_path, monkeypatch):
    """Create mock pre-compact files and verify discovery."""
    import claudewatch.config as config_mod

    # Set up a fake projects dir
    projects = tmp_path / "projects"
    proj_mem = projects / "-home-user-myproject" / "memory"
    proj_mem.mkdir(parents=True)
    (proj_mem / "pre-compact-2026-02-28.md").write_text("old memory")
    (proj_mem / "pre-compact-2026-03-01.md").write_text("newer memory stuff here")

    monkeypatch.setattr(config_mod, "PROJECTS_DIR", projects)

    results = find_autocompact_files()
    assert len(results) == 2
    # Should be sorted most recent first
    assert results[0]["date"] == "2026-03-01"
    assert results[1]["date"] == "2026-02-28"
    assert results[0]["project"] == "myproject"
    assert results[0]["size"] > 0

"""Tests for analyze-memory.py: parsing, classification, redundancy, domain detection."""
import sys
import importlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "forge" / "scripts"))
am = importlib.import_module("analyze-memory")


# ---------------------------------------------------------------------------
# TestSanitizeText
# ---------------------------------------------------------------------------

class TestSanitizeText:
    """Verify control character removal and truncation."""

    def test_strips_control_chars_preserves_whitespace(self):
        """Null bytes and BEL stripped; newlines and tabs survive."""
        result = am._sanitize_text("line1\x00\nline2\x07\ttab")
        assert result == "line1\nline2\ttab"

    def test_truncation_applied_after_sanitization(self):
        """Truncation counts clean characters, not raw bytes."""
        result = am._sanitize_text("\x00abc\x00defgh", max_len=5)
        assert result == "abcde"


# ---------------------------------------------------------------------------
# TestClassifyEntry
# ---------------------------------------------------------------------------

class TestClassifyEntry:
    """Verify entry classification by pattern scoring."""

    def test_preference(self):
        assert am.classify_entry("Always use pnpm instead of npm") == "preference"

    def test_convention(self):
        assert am.classify_entry("Tests go in the tests/ directory following naming convention") == "convention"

    def test_workflow(self):
        assert am.classify_entry("Deploy process: first run tests, then build, finally deploy") == "workflow"

    def test_command_backtick(self):
        assert am.classify_entry("Run `pnpm test` to execute tests") == "command"

    def test_debugging(self):
        assert am.classify_entry("If you see a 502 error, usually means the backend crashed") == "debugging"

    def test_empty_returns_default(self):
        assert am.classify_entry("") == "preference"

    def test_no_patterns_returns_default(self):
        assert am.classify_entry("The sky is blue") == "preference"

    def test_highest_score_wins(self):
        """When multiple categories match, highest score determines result."""
        text = "The deployment process has steps: first run build, then run test, next deploy"
        assert am.classify_entry(text) == "workflow"

    def test_ambiguous_input_picks_strongest(self):
        """'fix' and 'error' trigger debugging even when 'run' triggers command."""
        text = "To fix the issue, resolve the module path error"
        assert am.classify_entry(text) == "debugging"


# ---------------------------------------------------------------------------
# TestParseMemoryEntries
# ---------------------------------------------------------------------------

class TestParseMemoryEntries:
    """Verify markdown-to-entries splitting."""

    def test_blank_line_separated(self):
        text = "Entry one content here.\n\nEntry two content here.\n"
        entries = am.parse_memory_entries(text)
        assert len(entries) == 2

    def test_header_separated(self):
        text = "# Topic A\nContent A.\n# Topic B\nContent B.\n"
        entries = am.parse_memory_entries(text)
        assert len(entries) == 2
        assert "Topic A" in entries[0]
        assert "Topic B" in entries[1]

    def test_frontmatter_splits_at_delimiters(self):
        """--- delimiters start new entries, frontmatter content is accessible."""
        text = "---\nname: test\ntype: user\n---\nActual content here.\n"
        entries = am.parse_memory_entries(text)
        assert any("Actual content" in e for e in entries)

    def test_consecutive_list_items_each_become_entry(self):
        text = "- First item entry here\n- Second item entry\n- Third item entry\n"
        entries = am.parse_memory_entries(text)
        assert len(entries) == 3

    def test_short_entries_below_threshold_filtered(self):
        """Entries <=5 chars are dropped to avoid noise."""
        text = "Hi\n\nThis is a longer entry that should survive filtering.\n"
        entries = am.parse_memory_entries(text)
        assert len(entries) == 1

    def test_empty_and_whitespace_only(self):
        assert am.parse_memory_entries("") == []
        assert am.parse_memory_entries("   \n  \n   ") == []

    def test_header_with_nested_list_items(self):
        """Header content and subsequent list items parse as separate entries."""
        text = "# Header\nSome context line.\n- Item one detail\n- Item two detail\n"
        entries = am.parse_memory_entries(text)
        assert len(entries) >= 2

    def test_paragraph_after_list_starts_new_entry(self):
        """Non-list text after a blank line starts a fresh entry."""
        text = "- List item entry.\n\nParagraph after blank line.\n"
        entries = am.parse_memory_entries(text)
        assert len(entries) == 2


# ---------------------------------------------------------------------------
# TestCheckRedundancy
# ---------------------------------------------------------------------------

class TestCheckRedundancy:
    """Verify redundancy checking against CLAUDE.md and rules."""

    def test_redundant_with_claude_md(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(
            "Always use pytest for testing. Run with coverage enabled.\n"
        )
        assert am.check_redundancy("always use pytest for testing", tmp_path) is True

    def test_not_redundant(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Project\nGeneric content only.\n")
        assert am.check_redundancy("deploy to kubernetes cluster staging", tmp_path) is False

    def test_redundant_with_rule(self, tmp_path):
        rules_dir = tmp_path / ".claude" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "style.md").write_text(
            "Use black formatter for Python code. Run ruff for linting.\n"
        )
        assert am.check_redundancy("use black formatter for python code", tmp_path) is True

    def test_short_entry_skips_check(self, tmp_path):
        """Entries under 10 chars always return False (not enough signal)."""
        (tmp_path / "CLAUDE.md").write_text("Use pytest.\n")
        assert am.check_redundancy("short", tmp_path) is False

    def test_no_claude_md_not_redundant(self, tmp_path):
        assert am.check_redundancy("use pytest for all testing needs", tmp_path) is False

    def test_partial_overlap_below_threshold(self, tmp_path):
        """<60% word overlap doesn't trigger redundancy."""
        (tmp_path / "CLAUDE.md").write_text("Use pytest for testing.\n")
        assert am.check_redundancy("deploy staging kubernetes cluster", tmp_path) is False

    def test_all_short_words_skipped_by_filter(self, tmp_path):
        """Words <=3 chars are filtered out; entry with only short words is never redundant."""
        (tmp_path / "CLAUDE.md").write_text("Use the new API for all of the old app.\n")
        # All significant words are short: "use", "the", "new", "api", "for", "all", "old", "app"
        # Only "the" exceeds 3 chars... wait "new" is 3 chars, gets filtered.
        # Actually words > 3: none of these are > 3 chars. So match_count=0, returns False.
        assert am.check_redundancy("use the new api for all", tmp_path) is False


# ---------------------------------------------------------------------------
# TestFindMemoryDir
# ---------------------------------------------------------------------------

class TestFindMemoryDir:
    """Verify memory directory discovery strategies."""

    def test_exact_normalized_path_match(self, tmp_path, monkeypatch):
        projects_dir = tmp_path / ".claude" / "projects"
        project_root = tmp_path / "code" / "myapp"
        project_root.mkdir(parents=True)

        normalized = str(project_root).replace("/", "-").replace("\\", "-").lstrip("-")
        mem_dir = projects_dir / normalized / "memory"
        mem_dir.mkdir(parents=True)

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert am.find_memory_dir(project_root) == mem_dir

    def test_partial_path_component_match(self, tmp_path, monkeypatch):
        """Strategy 2: last 3 path components matched against directory names."""
        projects_dir = tmp_path / ".claude" / "projects"
        mem_dir = projects_dir / "code-myapp-repo" / "memory"
        mem_dir.mkdir(parents=True)

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = am.find_memory_dir(Path("/some/code/myapp/repo"))
        assert result == mem_dir

    def test_no_projects_dir_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert am.find_memory_dir(Path("/some/project")) is None

    def test_project_dir_without_memory_subdir(self, tmp_path, monkeypatch):
        """Project directory exists but has no memory/ subdirectory."""
        projects_dir = tmp_path / ".claude" / "projects"
        (projects_dir / "some-project").mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert am.find_memory_dir(Path("/some/project")) is None

    def test_strategy3_matches_by_project_name_in_memory_md(self, tmp_path, monkeypatch):
        """Strategy 3: MEMORY.md content contains the project name."""
        projects_dir = tmp_path / ".claude" / "projects"
        mem_dir = projects_dir / "unrelated-dirname" / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "MEMORY.md").write_text("# Notes for myapp\nSome memory content.\n")

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = am.find_memory_dir(Path("/somewhere/else/myapp"))
        assert result == mem_dir

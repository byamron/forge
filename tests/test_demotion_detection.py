"""Tests for tier demotion detection in analyze-config.py."""
import sys
import importlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "forge" / "scripts"))
ac = importlib.import_module("analyze-config")


class TestClassifyDomain:
    """Verify domain classification for CLAUDE.md entries."""

    def test_react_tsx(self):
        result = ac._classify_domain("Use functional components in .tsx files")
        assert result is not None
        name, filename, paths = result
        assert name == "react"
        assert "**/*.tsx" in paths

    def test_react_jsx(self):
        result = ac._classify_domain("Prefer .jsx for React components")
        assert result is not None
        assert result[0] == "react"

    def test_react_framework(self):
        result = ac._classify_domain("Always use React hooks for state")
        assert result is not None
        assert result[0] == "react"

    def test_python(self):
        result = ac._classify_domain("Use type hints in .py files")
        assert result is not None
        assert result[0] == "python"

    def test_python_framework(self):
        result = ac._classify_domain("Use Django ORM for database queries")
        assert result is not None
        assert result[0] == "python"

    def test_rust(self):
        result = ac._classify_domain("Format .rs files with rustfmt")
        assert result is not None
        assert result[0] == "rust"

    def test_go(self):
        result = ac._classify_domain("Run gofmt on save")
        assert result is not None
        assert result[0] == "go"

    def test_testing(self):
        result = ac._classify_domain("Put unit tests in tests/ directory")
        assert result is not None
        assert result[0] == "testing"

    def test_api(self):
        result = ac._classify_domain("All endpoints live in api/ directory")
        assert result is not None
        assert result[0] == "api"

    def test_no_domain(self):
        result = ac._classify_domain("Keep functions short and focused")
        assert result is None

    def test_case_insensitive(self):
        result = ac._classify_domain("Use REACT for the frontend")
        assert result is not None
        assert result[0] == "react"


class TestFindDemotionCandidates:
    """Verify demotion candidate detection."""

    def test_groups_by_domain(self):
        issues = [
            {"type": "domain_specific_in_claude_md", "line_number": 10,
             "content": "Use .tsx for React components"},
            {"type": "domain_specific_in_claude_md", "line_number": 15,
             "content": "Always use React hooks"},
        ]
        result = ac.find_demotion_candidates(
            Path("/tmp/fake"), issues, {"claude_md_lines": 100}
        )
        assert len(result["claude_md_to_rule"]) == 1
        group = result["claude_md_to_rule"][0]
        assert group["domain"] == "react"
        assert len(group["entries"]) == 2

    def test_single_entry_not_promoted(self):
        """A single entry doesn't justify creating a rule file."""
        issues = [
            {"type": "domain_specific_in_claude_md", "line_number": 5,
             "content": "Use .tsx extensions"},
        ]
        result = ac.find_demotion_candidates(
            Path("/tmp/fake"), issues, {"claude_md_lines": 100}
        )
        assert len(result["claude_md_to_rule"]) == 0

    def test_multiple_domains_grouped_separately(self):
        issues = [
            {"type": "domain_specific_in_claude_md", "line_number": 1,
             "content": "Use React hooks in .tsx"},
            {"type": "domain_specific_in_claude_md", "line_number": 2,
             "content": "React components should be pure"},
            {"type": "domain_specific_in_claude_md", "line_number": 3,
             "content": "Run pytest for .py files"},
            {"type": "domain_specific_in_claude_md", "line_number": 4,
             "content": "Use type hints in .py files"},
        ]
        result = ac.find_demotion_candidates(
            Path("/tmp/fake"), issues, {"claude_md_lines": 100}
        )
        assert len(result["claude_md_to_rule"]) == 2
        domains = {g["domain"] for g in result["claude_md_to_rule"]}
        assert domains == {"react", "python"}

    def test_non_placement_issues_ignored(self):
        issues = [
            {"type": "other_issue", "content": "Use React hooks"},
            {"type": "other_issue", "content": "Use .tsx files"},
        ]
        result = ac.find_demotion_candidates(
            Path("/tmp/fake"), issues, {"claude_md_lines": 100}
        )
        assert len(result["claude_md_to_rule"]) == 0

    def test_oversized_rule_detected(self, tmp_path):
        rules_dir = tmp_path / ".claude" / "rules"
        rules_dir.mkdir(parents=True)
        big_rule = rules_dir / "verbose.md"
        big_rule.write_text("\n".join(f"Line {i}" for i in range(100)))

        result = ac.find_demotion_candidates(
            tmp_path, [], {"claude_md_lines": 50}
        )
        assert len(result["rule_to_reference"]) == 1
        assert result["rule_to_reference"][0]["filename"] == "verbose"
        assert result["rule_to_reference"][0]["line_count"] == 100

    def test_normal_rule_not_flagged(self, tmp_path):
        rules_dir = tmp_path / ".claude" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "small.md").write_text("Short rule\n")

        result = ac.find_demotion_candidates(
            tmp_path, [], {"claude_md_lines": 50}
        )
        assert len(result["rule_to_reference"]) == 0

    def test_budget_over_200_flagged(self):
        result = ac.find_demotion_candidates(
            Path("/tmp/fake"), [], {"claude_md_lines": 250}
        )
        assert result["budget"]["over_budget"] is True

    def test_budget_under_200_ok(self):
        result = ac.find_demotion_candidates(
            Path("/tmp/fake"), [], {"claude_md_lines": 150}
        )
        assert result["budget"]["over_budget"] is False

    def test_total_demotable_lines_counted(self):
        issues = [
            {"type": "domain_specific_in_claude_md", "line_number": 1,
             "content": "React hooks in .tsx"},
            {"type": "domain_specific_in_claude_md", "line_number": 2,
             "content": "React components in .jsx"},
            {"type": "domain_specific_in_claude_md", "line_number": 3,
             "content": "Use pytest in tests/ dir"},
            {"type": "domain_specific_in_claude_md", "line_number": 4,
             "content": "Test files in tests/ folder"},
        ]
        result = ac.find_demotion_candidates(
            Path("/tmp/fake"), issues, {"claude_md_lines": 100}
        )
        assert result["budget"]["total_demotable_lines"] == 4

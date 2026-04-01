"""Tests for tier demotion detection in analyze-config.py."""
import re
import sys
import importlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "forge" / "scripts"))
ac = importlib.import_module("analyze-config")


class TestIsVerboseSection:
    """Verify prose detection for CLAUDE.md sections."""

    def test_prose_paragraphs_are_verbose(self):
        content = (
            "The system uses a layered architecture with clear separation of concerns between all components.\n"
            "Each layer communicates only with the layer below it through well-defined interface contracts.\n"
            "The data layer handles all persistence using SQLAlchemy as the ORM for database operations.\n"
            "The service layer orchestrates between data and presentation layers and contains business logic."
        )
        assert ac._is_verbose_section(content) is True

    def test_short_content_not_verbose(self):
        assert ac._is_verbose_section("Use pytest\nRun with -v") is False

    def test_bullet_list_not_verbose(self):
        content = "\n".join(f"- Rule {i}: keep it short" for i in range(8))
        assert ac._is_verbose_section(content) is False

    def test_mixed_content_with_enough_prose(self):
        content = (
            "- Use pytest for all tests\n"
            "The testing framework is configured to discover tests automatically in the tests directory always.\n"
            "- Run with coverage enabled\n"
            "Coverage thresholds are enforced at the CI level with a minimum requirement of eighty percent.\n"
            "- Never skip flaky tests\n"
            "Flaky tests should be investigated immediately and the root cause fixed rather than being marked skip."
        )
        # Has 3 prose lines (>60 chars, not bullet) — should be verbose
        assert ac._is_verbose_section(content) is True

    def test_empty_lines_filtered(self):
        content = "\n\n\n- One\n\n- Two\n\n"
        assert ac._is_verbose_section(content) is False

    def test_custom_min_lines(self):
        content = (
            "This is a moderately long explanation of how the deployment system works across environments.\n"
            "It also covers the rollback procedure and monitoring steps that need to happen post-deploy."
        )
        assert ac._is_verbose_section(content, min_lines=2) is True
        assert ac._is_verbose_section(content, min_lines=4) is False

    def test_code_block_not_counted_as_prose(self):
        """Lines inside fenced code blocks should be excluded from prose detection."""
        content = (
            "Brief intro to the module that explains what it does in the project and how to use it.\n"
            "```python\n"
            "very_long_variable_name_that_exceeds_sixty_characters_in_this_code_block = True\n"
            "another_long_line_of_code_that_looks_like_prose_but_is_inside_code_block = False\n"
            "yet_another_extremely_verbose_line_in_the_code_block_that_should_not_count = 42\n"
            "```\n"
            "And one more closing line."
        )
        # Only 2 non-code lines, neither exceeds 60 chars threshold
        # (intro is 86 chars but only 1 prose line — needs 2)
        assert ac._is_verbose_section(content) is False

    def test_code_block_with_surrounding_prose_still_detected(self):
        """Sections with prose + code blocks are verbose if enough prose outside blocks."""
        content = (
            "The deployment system is designed to handle multiple environments with careful validation steps.\n"
            "Each environment has its own configuration that must be validated before any deployment begins.\n"
            "```bash\n"
            "deploy --env staging --validate\n"
            "deploy --env production --require-approval\n"
            "```\n"
            "After deployment, the monitoring dashboard should show green status for all health checks.\n"
            "If any check fails, the automatic rollback procedure will restore the previous version safely."
        )
        assert ac._is_verbose_section(content) is True

    def test_bold_and_italic_lines_counted_as_prose(self):
        """Markdown-formatted lines (bold, italic) should count as prose, not be excluded."""
        content = (
            "**Important Security Note:** This system requires very careful configuration and ongoing attention.\n"
            "*Critical consideration:* All access tokens must be rotated on a regular quarterly schedule.\n"
            "The authentication middleware validates tokens against the centralized identity provider service.\n"
            "**Performance Impact:** Each validation adds approximately five milliseconds of latency to requests."
        )
        assert ac._is_verbose_section(content) is True

    def test_table_lines_not_counted_as_prose(self):
        """Markdown table rows starting with | should not count as prose."""
        content = (
            "The following table describes our API conventions and the expectations for each endpoint.\n"
            "All endpoints must follow these conventions to ensure consistency across the platform.\n"
            "| Endpoint | Method | Description | Auth Required |\n"
            "| /users | GET | Retrieve all users from the database system | Yes |\n"
            "| /users/:id | GET | Retrieve a single user by their unique identifier | Yes |\n"
            "| /health | GET | Health check endpoint for monitoring and alerting systems | No |\n"
        )
        # 2 prose lines + table lines (excluded) — meets threshold
        assert ac._is_verbose_section(content) is True

    def test_only_table_not_verbose(self):
        """A section that is purely a table with no prose is not verbose."""
        content = (
            "| Column A | Column B | Column C | Column D | Extra Column E |\n"
            "| val1 | val2 | val3 | val4 | val5678901234567890123456789012345 |\n"
            "| val6 | val7 | val8 | val9 | val0123456789012345678901234567890 |\n"
            "| val1 | val2 | val3 | val4 | val5678901234567890123456789012345 |\n"
            "| val6 | val7 | val8 | val9 | val0123456789012345678901234567890 |\n"
        )
        assert ac._is_verbose_section(content) is False

    def test_large_section_detected(self):
        """Very large sections (100+ lines) should be detected."""
        lines = [
            f"This is line number {i} of the verbose section content that exceeds sixty characters easily."
            for i in range(100)
        ]
        content = "\n".join(lines)
        assert ac._is_verbose_section(content) is True


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

    def test_swift(self):
        result = ac._classify_domain("Use SwiftUI views for .swift files")
        assert result is not None
        assert result[0] == "swift"
        assert "**/*.swift" in result[2]

    def test_swift_framework(self):
        result = ac._classify_domain("Use SwiftData for persistence")
        assert result is not None
        assert result[0] == "swift"

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

    def test_verbose_section_detected(self):
        """CLAUDE.md sections with 4+ lines of prose are flagged."""
        sections = [{
            "heading": "Architecture Overview",
            "content": (
                "The system uses a layered architecture with clear separation of concerns. "
                "Each layer communicates only with the layer directly below it via well-defined interfaces.\n"
                "The data layer handles persistence and uses SQLAlchemy for ORM mapping across all database operations.\n"
                "The service layer contains business logic and orchestrates between data and presentation layers for every request.\n"
                "The presentation layer handles HTTP concerns and delegates all processing to the service layer immediately."
            ),
            "line_start": 10,
            "line_end": 18,
        }]
        result = ac.find_demotion_candidates(
            Path("/tmp/fake"), [], {"claude_md_lines": 100},
            claude_md_sections=sections,
        )
        verbose = result["claude_md_verbose_to_reference"]
        assert len(verbose) == 1
        assert verbose[0]["heading"] == "Architecture Overview"
        assert verbose[0]["name"] == "architecture-overview"
        assert verbose[0]["line_count"] == 4

    def test_short_section_not_flagged(self):
        """Short CLAUDE.md sections are fine where they are."""
        sections = [{
            "heading": "Testing",
            "content": "- Use pytest\n- Run with `python -m pytest`",
            "line_start": 1,
            "line_end": 3,
        }]
        result = ac.find_demotion_candidates(
            Path("/tmp/fake"), [], {"claude_md_lines": 50},
            claude_md_sections=sections,
        )
        assert len(result["claude_md_verbose_to_reference"]) == 0

    def test_bullet_list_not_flagged(self):
        """Pure bullet lists aren't verbose even if long."""
        sections = [{
            "heading": "Code Style",
            "content": "\n".join(
                f"- Rule {i}: keep it short" for i in range(10)
            ),
            "line_start": 1,
            "line_end": 12,
        }]
        result = ac.find_demotion_candidates(
            Path("/tmp/fake"), [], {"claude_md_lines": 50},
            claude_md_sections=sections,
        )
        assert len(result["claude_md_verbose_to_reference"]) == 0

    def test_verbose_lines_included_in_budget(self):
        """Verbose section line counts are included in total_demotable_lines."""
        sections = [{
            "heading": "Deployment Process",
            "content": (
                "The deployment process involves multiple stages across environments with careful validation at each step.\n"
                "First, the CI pipeline runs all tests and linting checks against the pull request branch automatically.\n"
                "Then staging is deployed automatically when the PR merges into main, triggering the deployment pipeline.\n"
                "Finally production requires manual approval from the on-call engineer who verifies staging metrics first."
            ),
            "line_start": 20,
            "line_end": 28,
        }]
        result = ac.find_demotion_candidates(
            Path("/tmp/fake"), [], {"claude_md_lines": 250},
            claude_md_sections=sections,
        )
        assert result["budget"]["total_demotable_lines"] == 4

    def test_verbose_name_truncated_and_sanitized(self):
        """Heading names are kebab-cased and truncated to 30 chars."""
        sections = [{
            "heading": "Very Long Section Title That Exceeds The Maximum Length Allowed",
            "content": (
                "This section explains the entire history of the project architecture and why decisions were made in detail.\n"
                "It covers the reasoning behind each major technical choice including database selection and caching strategy.\n"
                "The document also includes performance benchmarks and comparison data from the original evaluation period.\n"
                "Finally it describes the migration path from the legacy system and the rollback procedures in case of failure."
            ),
            "line_start": 1,
            "line_end": 8,
        }]
        result = ac.find_demotion_candidates(
            Path("/tmp/fake"), [], {"claude_md_lines": 50},
            claude_md_sections=sections,
        )
        verbose = result["claude_md_verbose_to_reference"]
        assert len(verbose) == 1
        assert len(verbose[0]["name"]) <= 30
        assert re.match(r'^[a-z0-9-]+$', verbose[0]["name"])

    def test_special_char_heading_gets_fallback_name(self):
        """Headings with only special characters get 'section' as fallback."""
        sections = [{
            "heading": "---",
            "content": (
                "This is a verbose section that has more than enough prose to trigger detection easily.\n"
                "It contains multiple lines of explanatory text about the project architecture and design.\n"
                "The content describes how various components interact with each other in the system overall.\n"
                "And it keeps going with yet more detailed explanation of the deployment and testing process."
            ),
            "line_start": 1,
            "line_end": 8,
        }]
        result = ac.find_demotion_candidates(
            Path("/tmp/fake"), [], {"claude_md_lines": 50},
            claude_md_sections=sections,
        )
        verbose = result["claude_md_verbose_to_reference"]
        assert len(verbose) == 1
        assert verbose[0]["name"] == "section"

    def test_no_sections_passed(self):
        """Works correctly when claude_md_sections is not provided."""
        result = ac.find_demotion_candidates(
            Path("/tmp/fake"), [], {"claude_md_lines": 50}
        )
        assert result["claude_md_verbose_to_reference"] == []

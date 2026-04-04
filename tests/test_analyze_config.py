"""Tests for analyze-config.py: context budget, tech stack, gaps, placement issues, sections."""
import json
import sys
import importlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "forge" / "scripts"))
ac = importlib.import_module("analyze-config")


# ---------------------------------------------------------------------------
# TestComputeContextBudget
# ---------------------------------------------------------------------------

class TestComputeContextBudget:
    """Verify context budget computation across project shapes."""

    def test_empty_project(self, tmp_path):
        """Empty directory returns all zeros and empty inventories."""
        budget, skills, agents, hooks, rules = ac.compute_context_budget(tmp_path)
        assert budget["claude_md_lines"] == 0
        assert budget["rules_count"] == 0
        assert budget["skills_count"] == 0
        assert budget["agents_count"] == 0
        assert budget["hooks_count"] == 0
        assert budget["estimated_tier1_lines"] == 0
        assert skills == []
        assert agents == []
        assert rules == []

    def test_root_claude_md_takes_priority_over_dotclaude(self, tmp_path):
        """When CLAUDE.md exists at both root and .claude/, root wins."""
        (tmp_path / "CLAUDE.md").write_text("line1\nline2\n")
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "CLAUDE.md").write_text("single\n")
        budget, *_ = ac.compute_context_budget(tmp_path)
        assert budget["claude_md_lines"] == 2

    def test_dotclaude_fallback(self, tmp_path):
        """CLAUDE.md inside .claude/ found when not at root."""
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "CLAUDE.md").write_text("# Alt location\n")
        budget, *_ = ac.compute_context_budget(tmp_path)
        assert budget["claude_md_lines"] == 1

    def test_tier1_includes_local_md(self, tmp_path):
        """estimated_tier1_lines = CLAUDE.md + CLAUDE.local.md."""
        (tmp_path / "CLAUDE.md").write_text("main\n")
        (tmp_path / "CLAUDE.local.md").write_text("local1\nlocal2\n")
        budget, *_ = ac.compute_context_budget(tmp_path)
        assert budget["estimated_tier1_lines"] == 3

    def test_rules_counted(self, tmp_path):
        rules_dir = tmp_path / ".claude" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "security.md").write_text("# Security\nRule 1\nRule 2\n")
        (rules_dir / "style.md").write_text("# Style\nRule A\n")
        budget, _, _, _, rules = ac.compute_context_budget(tmp_path)
        assert budget["rules_count"] == 2
        assert budget["rules_total_lines"] == 5
        assert len(rules) == 2

    def test_skills_parsed_with_metadata(self, tmp_path):
        """Skills are parsed and carry name + format metadata."""
        skill_dir = tmp_path / ".claude" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: Does things\n---\n\nBody here.\n"
        )
        budget, skills, *_ = ac.compute_context_budget(tmp_path)
        assert budget["skills_count"] == 1
        assert skills[0]["name"] == "my-skill"
        assert skills[0]["format"] == "skill"

    def test_legacy_commands_counted_as_skills(self, tmp_path):
        """Legacy .claude/commands/*.md files appear in skills inventory."""
        cmd_dir = tmp_path / ".claude" / "commands"
        cmd_dir.mkdir(parents=True)
        (cmd_dir / "deploy.md").write_text("Deploy the app to staging.\n")
        budget, skills, *_ = ac.compute_context_budget(tmp_path)
        assert budget["skills_count"] == 1
        assert skills[0]["format"] == "legacy_command"

    def test_agents_format_set(self, tmp_path):
        """Agent .md files get format='agent' even though they use skill parser."""
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "reviewer.md").write_text(
            "---\nname: reviewer\ndescription: Reviews code\nmodel: sonnet\n---\nBody.\n"
        )
        budget, _, agents, *_ = ac.compute_context_budget(tmp_path)
        assert budget["agents_count"] == 1
        assert agents[0]["format"] == "agent"

    def test_hooks_parsed_from_nested_settings_structure(self, tmp_path):
        """Hooks extracted from the deeply nested settings.json hooks schema."""
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir(exist_ok=True)
        settings = {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Write|Edit",
                        "hooks": [
                            {"type": "command", "command": "prettier --write $FILE"},
                            {"type": "command", "command": "eslint --fix $FILE"},
                        ],
                    }
                ]
            }
        }
        (settings_dir / "settings.json").write_text(json.dumps(settings))
        budget, _, _, hooks, _ = ac.compute_context_budget(tmp_path)
        assert budget["hooks_count"] == 2
        assert hooks[0]["event"] == "PostToolUse"
        assert "prettier" in hooks[0]["command"]

    def test_malformed_settings_json_handled(self, tmp_path):
        """Invalid JSON in settings.json doesn't crash — hooks count stays 0."""
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        (settings_dir / "settings.json").write_text("not json {{{")
        budget, *_ = ac.compute_context_budget(tmp_path)
        assert budget["hooks_count"] == 0


# ---------------------------------------------------------------------------
# TestDetectTechStack
# ---------------------------------------------------------------------------

class TestDetectTechStack:
    """Verify tech stack detection from manifest files."""

    def test_empty_project(self, tmp_path):
        result = ac.detect_tech_stack(tmp_path)
        assert result["detected"] == []
        assert result["package_manager"] is None
        assert result["formatter"] is None

    @pytest.mark.parametrize("lockfile,expected", [
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lockb", "bun"),
        ("package-lock.json", "npm"),
    ])
    def test_package_manager_from_lockfile(self, tmp_path, lockfile, expected):
        (tmp_path / "package.json").write_text(json.dumps({"name": "app"}))
        (tmp_path / lockfile).write_text("")
        assert ac.detect_tech_stack(tmp_path)["package_manager"] == expected

    def test_react_ts_full_detection(self, tmp_path):
        """Realistic React/TS project detects stack, formatter, linter, and test framework."""
        pkg = {
            "name": "app",
            "dependencies": {"react": "^18.0.0"},
            "devDependencies": {"prettier": "^3.0.0", "eslint": "^8.0.0", "vitest": "^1.0.0"},
        }
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        (tmp_path / "tsconfig.json").write_text("{}")
        result = ac.detect_tech_stack(tmp_path)
        assert set(result["detected"]) >= {"node", "react", "typescript"}
        assert result["formatter"] == "prettier"
        assert result["linter"] == "eslint"
        assert result["test_framework"] == "vitest"

    def test_python_project(self, tmp_path):
        pyproject = "[tool.black]\nline-length = 88\n[tool.ruff]\n[tool.pytest.ini_options]\n"
        (tmp_path / "pyproject.toml").write_text(pyproject)
        result = ac.detect_tech_stack(tmp_path)
        assert "python" in result["detected"]
        assert result["formatter"] == "black"
        assert result["linter"] == "ruff"
        assert result["test_framework"] == "pytest"

    def test_rust_gets_rustfmt_by_default(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text("[package]\nname = \"myapp\"\n")
        result = ac.detect_tech_stack(tmp_path)
        assert "rust" in result["detected"]
        assert result["formatter"] == "rustfmt"

    def test_go_gets_gofmt_by_default(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/app\n")
        result = ac.detect_tech_stack(tmp_path)
        assert "go" in result["detected"]
        assert result["formatter"] == "gofmt"

    def test_multi_stack_detected(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"name": "app"}))
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        (tmp_path / "go.mod").write_text("module app\n")
        result = ac.detect_tech_stack(tmp_path)
        assert set(result["detected"]) >= {"node", "python", "go"}

    def test_config_file_fallback_prettier(self, tmp_path):
        """Formatter detected from .prettierrc when not in package.json deps."""
        (tmp_path / ".prettierrc").write_text("{}")
        assert ac.detect_tech_stack(tmp_path)["formatter"] == "prettier"

    def test_config_file_fallback_eslint(self, tmp_path):
        (tmp_path / "eslint.config.js").write_text("module.exports = {}")
        assert ac.detect_tech_stack(tmp_path)["linter"] == "eslint"

    def test_config_file_fallback_vitest(self, tmp_path):
        (tmp_path / "vitest.config.ts").write_text("export default {}")
        assert ac.detect_tech_stack(tmp_path)["test_framework"] == "vitest"

    def test_biome_in_deps_detected(self, tmp_path):
        pkg = {"devDependencies": {"@biomejs/biome": "^1.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert ac.detect_tech_stack(tmp_path)["formatter"] == "biome"

    def test_malformed_package_json_no_crash(self, tmp_path):
        """Invalid JSON in package.json doesn't crash — just skips node detection."""
        (tmp_path / "package.json").write_text("not json {{{")
        result = ac.detect_tech_stack(tmp_path)
        assert "node" not in result["detected"]

    def test_deduplication(self, tmp_path):
        """react appearing in both deps and devDeps only shows once."""
        pkg = {"dependencies": {"react": "^18"}, "devDependencies": {"react": "^18"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert ac.detect_tech_stack(tmp_path)["detected"].count("react") == 1


# ---------------------------------------------------------------------------
# TestFindGaps
# ---------------------------------------------------------------------------

class TestFindGaps:
    """Verify gap detection for missing hooks and references."""

    def test_missing_formatter_hook(self, tmp_path):
        tech = {"formatter": "prettier", "linter": None, "test_framework": None}
        gaps = ac.find_gaps(tmp_path, tech)
        assert len(gaps) == 1
        assert gaps[0]["type"] == "missing_hook"
        assert gaps[0]["severity"] == "high"
        assert "prettier" in gaps[0]["description"]

    def test_no_gaps_when_hooks_exist(self, tmp_path):
        """Hooks matching the formatter+linter suppress those gaps."""
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings = {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Write|Edit",
                        "hooks": [
                            {"type": "command", "command": "prettier --write $FILE"},
                            {"type": "command", "command": "eslint --fix $FILE"},
                        ],
                    }
                ]
            }
        }
        (settings_dir / "settings.json").write_text(json.dumps(settings))
        tech = {"formatter": "prettier", "linter": "eslint", "test_framework": None}
        gaps = ac.find_gaps(tmp_path, tech)
        assert len(gaps) == 0

    def test_test_framework_gap_low_severity(self, tmp_path):
        tech = {"formatter": None, "linter": None, "test_framework": "pytest"}
        gaps = ac.find_gaps(tmp_path, tech)
        assert len(gaps) == 1
        assert gaps[0]["severity"] == "low"

    def test_docs_dir_unreferenced_creates_gap(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "CLAUDE.md").write_text("# Project\nNo docs reference.\n")
        tech = {"formatter": None, "linter": None, "test_framework": None}
        gaps = ac.find_gaps(tmp_path, tech)
        assert any(g["type"] == "missing_reference" for g in gaps)

    def test_docs_dir_referenced_no_gap(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "CLAUDE.md").write_text("# Project\nSee docs/ for API reference.\n")
        tech = {"formatter": None, "linter": None, "test_framework": None}
        assert not any(g["type"] == "missing_reference" for g in ac.find_gaps(tmp_path, tech))

    def test_nothing_detected_no_gaps(self, tmp_path):
        tech = {"formatter": None, "linter": None, "test_framework": None}
        assert ac.find_gaps(tmp_path, tech) == []

    def test_all_tools_missing_creates_three_gaps(self, tmp_path):
        tech = {"formatter": "black", "linter": "ruff", "test_framework": "pytest"}
        assert len(ac.find_gaps(tmp_path, tech)) == 3


# ---------------------------------------------------------------------------
# TestFindPlacementIssues
# ---------------------------------------------------------------------------

class TestFindPlacementIssues:
    """Verify detection of domain-specific content in CLAUDE.md."""

    def test_file_extension_flagged(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Project\n\nUse hooks in .tsx files.\n")
        issues = ac.find_placement_issues(tmp_path)
        assert len(issues) == 1
        assert "file extensions" in issues[0]["suggestion"]

    def test_framework_name_flagged(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Proj\n\nAlways use React hooks.\n")
        issues = ac.find_placement_issues(tmp_path)
        assert len(issues) == 1
        assert "framework" in issues[0]["suggestion"]

    def test_directory_path_flagged(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Proj\n\nPut helpers in src/ dir.\n")
        assert len(ac.find_placement_issues(tmp_path)) == 1

    def test_generic_content_clean(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(
            "# Project\n\nKeep functions short.\nWrite clear commit messages.\n"
        )
        assert ac.find_placement_issues(tmp_path) == []

    def test_code_blocks_excluded(self, tmp_path):
        """Domain-specific content inside fenced code blocks is ignored."""
        (tmp_path / "CLAUDE.md").write_text("# Proj\n\n```\nUse .tsx for components\n```\n")
        assert ac.find_placement_issues(tmp_path) == []

    def test_tree_drawing_chars_excluded(self, tmp_path):
        """File tree listings with box-drawing characters are ignored."""
        content = "# Proj\n\n## Structure\n\n├── src/\n│   └── components/\n└── tests/\n"
        (tmp_path / "CLAUDE.md").write_text(content)
        assert ac.find_placement_issues(tmp_path) == []

    def test_line_numbers_accurate(self, tmp_path):
        content = "# Proj\n\nGeneric line.\nUse React for frontend.\nAnother generic.\n"
        (tmp_path / "CLAUDE.md").write_text(content)
        issues = ac.find_placement_issues(tmp_path)
        assert issues[0]["line_number"] == 4

    def test_no_claude_md_returns_empty(self, tmp_path):
        assert ac.find_placement_issues(tmp_path) == []


# ---------------------------------------------------------------------------
# TestParseCladeMdSections
# ---------------------------------------------------------------------------

class TestParseCladeMdSections:
    """Verify CLAUDE.md section parsing."""

    def test_multiple_sections_parsed(self, tmp_path):
        content = "# Main\n\n## Architecture\nLayered design.\n\n## Testing\nUse pytest.\n"
        (tmp_path / "CLAUDE.md").write_text(content)
        sections = ac._parse_claude_md_sections(tmp_path)
        assert len(sections) == 2
        assert sections[0]["heading"] == "Architecture"
        assert sections[1]["heading"] == "Testing"

    def test_empty_sections_skipped(self, tmp_path):
        content = "## Empty\n\n## Has Content\nSome text.\n"
        (tmp_path / "CLAUDE.md").write_text(content)
        sections = ac._parse_claude_md_sections(tmp_path)
        assert len(sections) == 1
        assert sections[0]["heading"] == "Has Content"

    def test_line_ranges_correct(self, tmp_path):
        content = "## First\nLine A\nLine B\n## Second\nLine C\n"
        (tmp_path / "CLAUDE.md").write_text(content)
        sections = ac._parse_claude_md_sections(tmp_path)
        assert sections[0]["line_start"] == 1
        assert sections[0]["line_end"] == 3
        assert sections[1]["line_start"] == 4

    def test_no_claude_md_returns_empty(self, tmp_path):
        assert ac._parse_claude_md_sections(tmp_path) == []

    def test_dotclaude_location(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "CLAUDE.md").write_text("## Section\nContent here.\n")
        assert len(ac._parse_claude_md_sections(tmp_path)) == 1


# ---------------------------------------------------------------------------
# TestHookHelpers
# ---------------------------------------------------------------------------

class TestHookHelpers:
    """Verify hook collection and pattern matching."""

    def test_collect_from_nested_settings(self, tmp_path):
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings = {
            "hooks": {
                "PostToolUse": [
                    {"matcher": "Write", "hooks": [{"type": "command", "command": "fmt"}]}
                ]
            }
        }
        (settings_dir / "settings.json").write_text(json.dumps(settings))
        cmds = ac._collect_hook_commands(tmp_path)
        assert cmds == [("PostToolUse", "fmt")]

    def test_match_requires_both_event_and_command(self):
        """Matching checks both event pattern AND command pattern."""
        cmds = [("PostToolUse", "prettier --write $FILE")]
        assert ac._any_hook_matches(cmds, r"PostToolUse", r"prettier") is True
        assert ac._any_hook_matches(cmds, r"PreCommit", r"prettier") is False
        assert ac._any_hook_matches(cmds, r"PostToolUse", r"eslint") is False


# ---------------------------------------------------------------------------
# TestParseSkill
# ---------------------------------------------------------------------------

class TestParseSkill:
    """Verify SKILL.md frontmatter parsing."""

    def test_extracts_name_description_and_body(self, tmp_path):
        f = tmp_path / "SKILL.md"
        f.write_text("---\nname: my-skill\ndescription: Does things\n---\n\nBody text.\n")
        result = ac._parse_skill(f)
        assert result["name"] == "my-skill"
        assert result["description"] == "Does things"
        assert "Body text" in result["content"]

    def test_no_frontmatter_returns_none(self, tmp_path):
        f = tmp_path / "SKILL.md"
        f.write_text("Just body text.\n")
        assert ac._parse_skill(f) is None

    def test_multiline_description(self, tmp_path):
        """Multiline YAML values (>) are joined into a single string."""
        f = tmp_path / "SKILL.md"
        f.write_text("---\nname: test\ndescription: >\n  Line one\n  line two\n---\nBody.\n")
        result = ac._parse_skill(f)
        assert "Line one" in result["description"]
        assert "line two" in result["description"]


# ---------------------------------------------------------------------------
# TestParseRule
# ---------------------------------------------------------------------------

class TestParseRule:
    """Verify rule .md parsing with paths frontmatter."""

    def test_extracts_paths_frontmatter(self, tmp_path):
        f = tmp_path / "react.md"
        f.write_text("---\npaths:\n  - '**/*.tsx'\n  - '**/*.jsx'\n---\nReact rules.\n")
        result = ac._parse_rule(f)
        assert result["name"] == "react"
        assert "**/*.tsx" in result["paths_frontmatter"]
        assert "**/*.jsx" in result["paths_frontmatter"]

    def test_no_frontmatter_still_parses(self, tmp_path):
        f = tmp_path / "simple.md"
        f.write_text("Just a simple rule.\n")
        result = ac._parse_rule(f)
        assert result["name"] == "simple"
        assert result["paths_frontmatter"] == []
        assert "simple rule" in result["content"]

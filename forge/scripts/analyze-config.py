#!/usr/bin/env python3
"""Analyze a project's Claude Code configuration and detect gaps.

Scans the project root for Claude Code artifacts (.claude/ directory, CLAUDE.md,
hooks, rules, skills, agents), detects the tech stack from manifest files, finds
missing hooks and placement issues, and outputs structured JSON to stdout.

Usage:
    python3 analyze-config.py [--project-root /path/to/project]
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_lines(path: Path):
    """Return list of lines from *path*, or empty list if unreadable."""
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def _read_json(path: Path):
    """Return parsed JSON from *path*, or None on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _count_md_files(directory: Path):
    """Return (count, total_lines) of .md files recursively in *directory*."""
    count = 0
    total_lines = 0
    if directory.is_dir():
        for f in sorted(directory.rglob("*.md")):
            if f.is_file():
                count += 1
                total_lines += len(_read_lines(f))
    return count, total_lines


def _glob_exists(directory: Path, pattern: str) -> bool:
    """Return True if any file matching *pattern* exists in *directory*."""
    return any(True for _ in directory.glob(pattern))


def _parse_skill(skill_path: Path) -> Optional[Dict[str, Any]]:
    """Parse a SKILL.md file, returning name, description, full content, and path.

    Uses simple string splitting for frontmatter (no pyyaml dependency).
    Returns the full file content so the LLM can compare existing skill
    behavior against detected patterns, not just the description summary.
    """
    try:
        text = skill_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    # Find closing ---
    end = -1
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end = i
            break
    if end < 0:
        return None

    frontmatter: Dict[str, str] = {}
    current_key = ""
    current_val = ""

    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped:
            continue
        # Check for key: value or key: >
        if ":" in stripped and not stripped.startswith("-") and not stripped.startswith(" "):
            if current_key:
                frontmatter[current_key] = current_val.strip()
            parts = stripped.split(":", 1)
            current_key = parts[0].strip()
            val = parts[1].strip()
            if val == ">" or val == "|":
                current_val = ""
            else:
                current_val = val
        elif current_key:
            # Continuation line for multiline value
            current_val += " " + stripped

    if current_key:
        frontmatter[current_key] = current_val.strip()

    name = frontmatter.get("name", skill_path.parent.name)
    description = frontmatter.get("description", "")
    body = "\n".join(lines[end + 1:]).strip()

    return {
        "name": name,
        "description": description,
        "content": body,
        "path": str(skill_path),
        "format": "skill",
    }


def _parse_legacy_command(cmd_path: Path) -> Optional[Dict[str, Any]]:
    """Parse a legacy .claude/commands/*.md file.

    These predate the skills format but still work in Claude Code.
    Returns the same structure as _parse_skill with format='legacy_command'.
    """
    try:
        text = cmd_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    lines = text.splitlines()
    name = cmd_path.stem  # e.g., "link" from "link.md"

    # Try to extract description from frontmatter if present
    description = ""
    body_start = 0
    if lines and lines[0].strip() == "---":
        end = -1
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                end = i
                break
        if end > 0:
            body_start = end + 1
            for line in lines[1:end]:
                stripped = line.strip()
                if stripped.startswith("description:"):
                    description = stripped.split(":", 1)[1].strip().strip('"').strip("'")

    body = "\n".join(lines[body_start:]).strip()

    return {
        "name": name,
        "description": description,
        "content": body,
        "path": str(cmd_path),
        "format": "legacy_command",
    }


# ---------------------------------------------------------------------------
# Context budget
# ---------------------------------------------------------------------------

def compute_context_budget(root: Path):
    budget = {
        "claude_md_lines": 0,
        "claude_local_md_lines": 0,
        "rules_count": 0,
        "rules_total_lines": 0,
        "skills_count": 0,
        "agents_count": 0,
        "hooks_count": 0,
        "estimated_tier1_lines": 0,
    }

    # CLAUDE.md -- can live at root or .claude/
    for candidate in [root / "CLAUDE.md", root / ".claude" / "CLAUDE.md"]:
        if candidate.is_file():
            budget["claude_md_lines"] = len(_read_lines(candidate))
            break

    # CLAUDE.local.md
    for candidate in [root / "CLAUDE.local.md", root / ".claude" / "CLAUDE.local.md"]:
        if candidate.is_file():
            budget["claude_local_md_lines"] = len(_read_lines(candidate))
            break

    # Rules
    rules_dir = root / ".claude" / "rules"
    budget["rules_count"], budget["rules_total_lines"] = _count_md_files(rules_dir)

    # Skills (SKILL.md files) and legacy commands (.claude/commands/*.md)
    skills_dir = root / ".claude" / "skills"
    commands_dir = root / ".claude" / "commands"
    skills_inventory: List[Dict[str, Any]] = []
    if skills_dir.is_dir():
        for f in sorted(skills_dir.rglob("SKILL.md")):
            if f.is_file():
                info = _parse_skill(f)
                if info:
                    skills_inventory.append(info)
    if commands_dir.is_dir():
        for f in sorted(commands_dir.iterdir()):
            if f.is_file() and f.suffix == ".md":
                info = _parse_legacy_command(f)
                if info:
                    skills_inventory.append(info)
    budget["skills_count"] = len(skills_inventory)

    # Agents
    agents_dir = root / ".claude" / "agents"
    agents_inventory: List[Dict[str, Any]] = []
    if agents_dir.is_dir():
        for f in sorted(agents_dir.iterdir()):
            if f.is_file() and f.suffix == ".md":
                info = _parse_skill(f)  # same frontmatter format as skills
                if info:
                    info["format"] = "agent"
                    agents_inventory.append(info)
    budget["agents_count"] = len(agents_inventory)

    # Hooks -- from settings.json (project-level and user-level)
    hooks_inventory: List[Dict[str, Any]] = []
    hooks_count = 0
    for settings_path in [
        root / ".claude" / "settings.json",
        Path.home() / ".claude" / "settings.json",
    ]:
        data = _read_json(settings_path)
        if data and isinstance(data, dict):
            hooks_sec = data.get("hooks", {})
            if isinstance(hooks_sec, dict):
                for event_name, event_hooks in hooks_sec.items():
                    if isinstance(event_hooks, list):
                        for group in event_hooks:
                            if isinstance(group, dict):
                                matcher = group.get("matcher", "")
                                inner = group.get("hooks", [])
                                if isinstance(inner, list):
                                    hooks_count += len(inner)
                                    for hook in inner:
                                        if isinstance(hook, dict):
                                            hooks_inventory.append({
                                                "event": event_name,
                                                "matcher": matcher,
                                                "type": hook.get("type", ""),
                                                "command": hook.get("command", ""),
                                                "source": str(settings_path),
                                            })
                                else:
                                    hooks_count += 1
                    elif isinstance(event_hooks, dict):
                        hooks_count += 1
    budget["hooks_count"] = hooks_count

    budget["estimated_tier1_lines"] = (
        budget["claude_md_lines"] + budget["claude_local_md_lines"]
    )

    return budget, skills_inventory, agents_inventory, hooks_inventory


# ---------------------------------------------------------------------------
# Tech-stack detection
# ---------------------------------------------------------------------------

def detect_tech_stack(root: Path):
    result = {
        "detected": [],
        "package_manager": None,
        "formatter": None,
        "linter": None,
        "test_framework": None,
    }

    # Package manager
    if (root / "pnpm-lock.yaml").exists():
        result["package_manager"] = "pnpm"
    elif (root / "yarn.lock").exists():
        result["package_manager"] = "yarn"
    elif (root / "bun.lockb").exists():
        result["package_manager"] = "bun"
    elif (root / "package-lock.json").exists():
        result["package_manager"] = "npm"

    # package.json
    pkg = _read_json(root / "package.json")
    if pkg and isinstance(pkg, dict):
        result["detected"].append("node")
        all_deps = {}
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            d = pkg.get(key)
            if isinstance(d, dict):
                all_deps.update(d)

        # Frameworks
        for name, label in [
            ("react", "react"),
            ("vue", "vue"),
            ("@angular/core", "angular"),
            ("svelte", "svelte"),
            ("next", "next.js"),
            ("nuxt", "nuxt"),
        ]:
            if name in all_deps:
                result["detected"].append(label)

        # Formatter
        if "prettier" in all_deps:
            result["formatter"] = "prettier"
        elif "@biomejs/biome" in all_deps or "biome" in all_deps:
            result["formatter"] = "biome"

        # Linter
        if "eslint" in all_deps:
            result["linter"] = "eslint"

        # Test framework
        for name, label in [
            ("vitest", "vitest"),
            ("jest", "jest"),
            ("mocha", "mocha"),
            ("@playwright/test", "playwright"),
        ]:
            if name in all_deps:
                result["test_framework"] = label
                break

    # TypeScript
    if (root / "tsconfig.json").exists():
        if "typescript" not in result["detected"]:
            result["detected"].append("typescript")

    # Config-file-based formatter/linter detection (fallback)
    if result["formatter"] is None:
        if (
            _glob_exists(root, ".prettierrc*")
            or (root / "prettier.config.js").exists()
            or (root / "prettier.config.mjs").exists()
        ):
            result["formatter"] = "prettier"
        elif (root / "biome.json").exists() or (root / "biome.jsonc").exists():
            result["formatter"] = "biome"

    if result["linter"] is None:
        if _glob_exists(root, ".eslintrc*") or _glob_exists(root, "eslint.config.*"):
            result["linter"] = "eslint"

    # Test config files (fallback)
    if result["test_framework"] is None:
        for pattern, label in [
            ("vitest.config.*", "vitest"),
            ("jest.config.*", "jest"),
            ("playwright.config.*", "playwright"),
        ]:
            if _glob_exists(root, pattern):
                result["test_framework"] = label
                break

    # Rust
    if (root / "Cargo.toml").exists():
        result["detected"].append("rust")
        if result["formatter"] is None:
            result["formatter"] = "rustfmt"

    # Python
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        result["detected"].append("python")
        pyproject = root / "pyproject.toml"
        if pyproject.is_file():
            try:
                content = pyproject.read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = ""
            if "black" in content.lower():
                result["formatter"] = result["formatter"] or "black"
            if "ruff" in content.lower():
                result["linter"] = result["linter"] or "ruff"
                if result["formatter"] is None and "ruff format" in content.lower():
                    result["formatter"] = "ruff"
            if "pytest" in content.lower():
                result["test_framework"] = result["test_framework"] or "pytest"

    # Go
    if (root / "go.mod").exists():
        result["detected"].append("go")
        if result["formatter"] is None:
            result["formatter"] = "gofmt"

    # Deduplicate while preserving order
    result["detected"] = list(dict.fromkeys(result["detected"]))

    return result


# ---------------------------------------------------------------------------
# Hooks helpers
# ---------------------------------------------------------------------------

def _collect_hook_commands(root: Path):
    """Return list of (event, command_str) from project and user settings."""
    commands = []
    for settings_path in [
        root / ".claude" / "settings.json",
        Path.home() / ".claude" / "settings.json",
    ]:
        data = _read_json(settings_path)
        if not data or not isinstance(data, dict):
            continue
        hooks_sec = data.get("hooks", {})
        if not isinstance(hooks_sec, dict):
            continue
        for event, event_hooks in hooks_sec.items():
            if isinstance(event_hooks, list):
                for group in event_hooks:
                    if isinstance(group, dict):
                        for h in group.get("hooks", []):
                            if isinstance(h, dict) and "command" in h:
                                commands.append((event, h["command"]))
            elif isinstance(event_hooks, dict) and "command" in event_hooks:
                commands.append((event, event_hooks["command"]))
    return commands


def _any_hook_matches(hook_commands, event_pattern: str, cmd_pattern: str) -> bool:
    """Check if any hook matches event and command patterns."""
    for event, cmd in hook_commands:
        if re.search(event_pattern, event, re.IGNORECASE):
            if re.search(cmd_pattern, cmd, re.IGNORECASE):
                return True
    return False


# ---------------------------------------------------------------------------
# Gap detection
# ---------------------------------------------------------------------------

_FORMATTER_COMMANDS = {
    "prettier": r"prettier",
    "biome": r"biome",
    "black": r"black",
    "rustfmt": r"rustfmt|cargo\s+fmt",
    "gofmt": r"gofmt|go\s+fmt",
    "ruff": r"ruff\s+format",
}

_LINTER_COMMANDS = {
    "eslint": r"eslint",
    "ruff": r"ruff",
}


def find_gaps(root: Path, tech_stack: dict):
    gaps = []
    hook_commands = _collect_hook_commands(root)

    # Formatter hook gap
    formatter = tech_stack.get("formatter")
    if formatter:
        pattern = _FORMATTER_COMMANDS.get(formatter, re.escape(formatter))
        if not _any_hook_matches(hook_commands, r"PostToolUse", pattern):
            gaps.append({
                "type": "missing_hook",
                "severity": "high",
                "description": (
                    f"{formatter} detected but no PostToolUse auto-format hook "
                    f"configured for Write/Edit operations."
                ),
                "suggested_artifact": "hook",
                "detail": {
                    "hook_event": "PostToolUse",
                    "matcher": "Write|Edit",
                    "formatter": formatter,
                },
            })

    # Linter hook gap
    linter = tech_stack.get("linter")
    if linter:
        pattern = _LINTER_COMMANDS.get(linter, re.escape(linter))
        if not _any_hook_matches(hook_commands, r"PostToolUse", pattern):
            gaps.append({
                "type": "missing_hook",
                "severity": "high",
                "description": (
                    f"{linter} detected but no PostToolUse auto-lint hook "
                    f"configured for Write/Edit operations."
                ),
                "suggested_artifact": "hook",
                "detail": {
                    "hook_event": "PostToolUse",
                    "matcher": "Write|Edit",
                    "linter": linter,
                },
            })

    # Test framework hook gap (lower severity)
    test_fw = tech_stack.get("test_framework")
    if test_fw:
        if not _any_hook_matches(
            hook_commands, r"Stop|PreCommit|Notification",
            r"test|jest|vitest|pytest|cargo.test|go.test",
        ):
            gaps.append({
                "type": "missing_hook",
                "severity": "low",
                "description": (
                    f"Test framework '{test_fw}' detected but no hook runs "
                    f"tests automatically."
                ),
                "suggested_artifact": "hook",
                "detail": {
                    "test_framework": test_fw,
                },
            })

    # Docs directory not referenced
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        claude_md_content = ""
        for candidate in [root / "CLAUDE.md", root / ".claude" / "CLAUDE.md"]:
            if candidate.is_file():
                try:
                    claude_md_content = candidate.read_text(
                        encoding="utf-8", errors="replace"
                    ).lower()
                except OSError:
                    pass
                break
        if "docs/" not in claude_md_content and "docs\\" not in claude_md_content:
            gaps.append({
                "type": "missing_reference",
                "severity": "medium",
                "description": (
                    "A docs/ directory exists but CLAUDE.md does not reference it. "
                    "Claude may not discover your project documentation."
                ),
                "suggested_artifact": "claude_md_entry",
                "detail": {"directory": "docs/"},
            })

    return gaps


# ---------------------------------------------------------------------------
# Placement-issue detection
# ---------------------------------------------------------------------------

_EXTENSION_RE = re.compile(
    r"\.(tsx|jsx|ts|js|py|rs|go|vue|svelte|test\.[tj]s|spec\.[tj]s)\b"
)
_FRAMEWORK_RE = re.compile(
    r"\b(React|Vue|Angular|Django|Flask|FastAPI|Express|Next\.js|Nuxt|Svelte)\b",
    re.IGNORECASE,
)
_DIRECTORY_RE = re.compile(
    r"\b(src/|tests/|test/|api/|components/|pages/|lib/|app/|routes/)\b"
)
# Tree-drawing characters used in file tree listings — skip these lines
_TREE_CHARS_RE = re.compile(r"[├└│─┌┐┘┬┴┼]")


def find_placement_issues(root: Path):
    issues = []
    claude_md_path = None
    for candidate in [root / "CLAUDE.md", root / ".claude" / "CLAUDE.md"]:
        if candidate.is_file():
            claude_md_path = candidate
            break
    if claude_md_path is None:
        return issues

    lines = _read_lines(claude_md_path)
    in_code_block = False

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Track code blocks — skip content inside them
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        if not stripped or stripped.startswith("#"):
            continue

        # Skip file tree listings (lines with tree-drawing characters)
        if _TREE_CHARS_RE.search(stripped):
            continue

        reasons = []
        if _EXTENSION_RE.search(stripped):
            reasons.append("mentions specific file extensions")
        if _FRAMEWORK_RE.search(stripped):
            reasons.append("mentions a framework name")
        if _DIRECTORY_RE.search(stripped):
            reasons.append("mentions a specific directory")

        if reasons:
            issues.append({
                "type": "domain_specific_in_claude_md",
                "severity": "medium",
                "line_number": i,
                "content": stripped,
                "suggestion": (
                    "Consider moving to a scoped rule in .claude/rules/ "
                    f"with path frontmatter ({', '.join(reasons)})."
                ),
            })

    return issues


# ---------------------------------------------------------------------------
# Demotion candidate detection
# ---------------------------------------------------------------------------

# Maps content signals to domains for grouping placement issues into rules
_DOMAIN_CLASSIFIERS = [
    # (domain_name, rule_filename, paths_frontmatter, content_patterns)
    ("react", "react", ["**/*.tsx", "**/*.jsx"],
     [r"\.tsx\b", r"\.jsx\b", r"\breact\b"]),
    ("vue", "vue", ["**/*.vue"],
     [r"\.vue\b", r"\bvue\b", r"\bnuxt\b"]),
    ("angular", "angular", ["**/*.ts"],
     [r"\bangular\b"]),
    ("svelte", "svelte", ["**/*.svelte"],
     [r"\bsvelte\b"]),
    ("python", "python", ["**/*.py"],
     [r"\.py\b", r"\bdjango\b", r"\bflask\b", r"\bfastapi\b"]),
    ("rust", "rust", ["**/*.rs"],
     [r"\.rs\b", r"\brustfmt\b", r"\bcargo\b"]),
    ("go", "go", ["**/*.go"],
     [r"\.go\b", r"\bgofmt\b"]),
    ("testing", "testing",
     ["tests/**", "test/**", "**/*.test.*", "**/*.spec.*"],
     [r"\btests?/", r"\.test\.", r"\.spec\."]),
    ("api", "api", ["**/api/**", "**/routes/**"],
     [r"\bapi/", r"\broutes/"]),
]


def _classify_domain(content: str) -> Optional[Tuple[str, str, List[str]]]:
    """Classify a line's domain. Returns (name, rule_filename, paths) or None."""
    for name, filename, paths, patterns in _DOMAIN_CLASSIFIERS:
        for pat in patterns:
            if re.search(pat, content, re.IGNORECASE):
                return (name, filename, paths)
    return None


def find_demotion_candidates(root: Path, placement_issues: List[Dict], context_budget: Dict) -> Dict[str, Any]:
    """Find candidates for tier demotion.

    Returns structured demotion candidates:
    - claude_md_to_rule: domain-specific CLAUDE.md entries grouped by domain
    - rule_to_reference: oversized rule files (>80 lines)
    """
    candidates = {
        "claude_md_to_rule": [],
        "rule_to_reference": [],
    }  # type: Dict[str, Any]

    # --- Group placement issues by domain ---
    domain_groups = {}  # type: Dict[str, List[Dict]]

    for issue in placement_issues:
        if issue.get("type") != "domain_specific_in_claude_md":
            continue
        content = issue.get("content", "")
        classified = _classify_domain(content)
        if classified is None:
            continue

        name, filename, paths = classified
        if name not in domain_groups:
            domain_groups[name] = {
                "domain": name,
                "filename": filename,
                "paths": paths,
                "entries": [],
            }
        domain_groups[name]["entries"].append({
            "line_number": issue.get("line_number", 0),
            "content": content,
        })

    # Only suggest demotion when 2+ entries share a domain
    # (a single entry isn't worth a whole rule file)
    for group in domain_groups.values():
        if len(group["entries"]) >= 2:
            candidates["claude_md_to_rule"].append(group)

    # --- Detect oversized rule files ---
    rules_dir = root / ".claude" / "rules"
    if rules_dir.is_dir():
        for rule_file in sorted(rules_dir.rglob("*.md")):
            if not rule_file.is_file():
                continue
            lines = _read_lines(rule_file)
            if len(lines) > 80:
                try:
                    rel = str(rule_file.relative_to(root))
                except ValueError:
                    rel = str(rule_file)
                try:
                    unique_name = rule_file.relative_to(rules_dir).with_suffix("").as_posix().replace("/", "-")
                except ValueError:
                    unique_name = rule_file.stem
                candidates["rule_to_reference"].append({
                    "path": rel,
                    "filename": unique_name,
                    "line_count": len(lines),
                })

    # --- Budget context ---
    claude_md_lines = context_budget.get("claude_md_lines", 0)
    candidates["budget"] = {
        "claude_md_lines": claude_md_lines,
        "over_budget": claude_md_lines > 200,
        "total_demotable_lines": sum(
            len(g["entries"]) for g in candidates["claude_md_to_rule"]
        ),
    }

    return candidates


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analyze a project's Claude Code configuration."
    )
    parser.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="Path to the project root (defaults to cwd).",
    )
    args = parser.parse_args()

    root = (
        Path(args.project_root).resolve()
        if args.project_root
        else Path.cwd().resolve()
    )

    if not root.is_dir():
        print(f"Error: project root '{root}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    try:
        budget, skills_inventory, agents_inventory, hooks_inventory = (
            compute_context_budget(root)
        )
        tech_stack = detect_tech_stack(root)
        gaps = find_gaps(root, tech_stack)
        placement_issues = find_placement_issues(root)
        demotion_candidates = find_demotion_candidates(
            root, placement_issues, budget
        )

        output = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "project_root": str(root),
            "context_budget": budget,
            "existing_skills": skills_inventory,
            "existing_agents": agents_inventory,
            "existing_hooks": hooks_inventory,
            "tech_stack": tech_stack,
            "gaps": gaps,
            "placement_issues": placement_issues,
            "demotion_candidates": demotion_candidates,
        }

        json.dump(output, sys.stdout, indent=2)
        sys.stdout.write("\n")

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

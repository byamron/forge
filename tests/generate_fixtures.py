#!/usr/bin/env python3
"""Generate synthetic project fixtures for Forge pipeline integration tests.

Creates self-contained project directories with realistic configurations,
transcript JSONL files, and memory entries that exercise specific detection
signals across the full analysis pipeline.

Each profile targets a distinct detection surface:
- swift-ios: memory-only proposals, no config/transcript signals
- react-ts: full config analysis (tech stack, hooks, placement, demotion, budget)
- python-corrections: transcript analysis (corrections, post-actions, repeated prompts)
- rust-minimal: threshold enforcement (below-threshold signals filtered out)
- fullstack-mature: dismissed/suppressed filtering, dedup against existing artifacts

Usage:
    python3 generate_fixtures.py [--output-dir /path/to/dir]
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SessionDef:
    """Definition of a single transcript session to generate."""
    session_id: str
    entries: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ProjectProfile:
    """Describes a synthetic project to generate."""
    name: str
    config_files: Dict[str, str] = field(default_factory=dict)
    sessions: List[SessionDef] = field(default_factory=list)
    memory_files: Dict[str, str] = field(default_factory=dict)
    dismissed: List[Dict[str, Any]] = field(default_factory=list)
    suppressed_themes: List[str] = field(default_factory=list)
    expected_signals: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

_BASE_TIME = datetime(2026, 3, 28, 10, 0, 0, tzinfo=timezone.utc)


def _ts(session_idx: int = 0, turn_idx: int = 0, offset_secs: int = 0) -> str:
    """Generate a deterministic ISO8601 timestamp."""
    dt = _BASE_TIME + timedelta(
        hours=session_idx * 2,
        minutes=turn_idx * 2,
        seconds=offset_secs,
    )
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


# ---------------------------------------------------------------------------
# JSONL entry builders
# ---------------------------------------------------------------------------

def make_user_entry(
    text: str,
    session_id: str,
    timestamp: str,
) -> Dict[str, Any]:
    """Create a user message JSONL entry."""
    return {
        "type": "user",
        "message": {"role": "user", "content": text},
        "timestamp": timestamp,
        "sessionId": session_id,
        "isSidechain": False,
    }


def make_assistant_entry(
    text: str,
    tools: Optional[List[Dict[str, Any]]] = None,
    session_id: str = "",
    timestamp: str = "",
) -> Dict[str, Any]:
    """Create an assistant message JSONL entry."""
    content: List[Dict[str, Any]] = [{"type": "text", "text": text}]
    if tools:
        for tool in tools:
            content.append({
                "type": "tool_use",
                "name": tool.get("name", ""),
                "input": tool.get("input", {}),
            })
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": content},
        "timestamp": timestamp,
        "sessionId": session_id,
        "isSidechain": False,
    }


def make_edit_tool(file_path: str) -> Dict[str, Any]:
    """Shorthand for an Edit tool use."""
    return {"name": "Edit", "input": {"file_path": file_path}}


def make_write_tool(file_path: str) -> Dict[str, Any]:
    """Shorthand for a Write tool use."""
    return {"name": "Write", "input": {"file_path": file_path}}


def make_bash_tool(command: str) -> Dict[str, Any]:
    """Shorthand for a Bash tool use."""
    return {"name": "Bash", "input": {"command": command}}


# ---------------------------------------------------------------------------
# Session builder helpers
# ---------------------------------------------------------------------------

def make_correction_session(
    session_id: str,
    session_idx: int,
    corrections: List[Dict[str, str]],
    opener: Optional[str] = None,
) -> SessionDef:
    """Build a session with user corrections after assistant actions.

    Each correction is a dict with:
      - user_text: the corrective user message
      - assistant_text: what the assistant said/did before
      - file_path: file the assistant edited (optional)
    """
    entries: List[Dict[str, Any]] = []
    turn = 0

    if opener:
        entries.append(make_user_entry(opener, session_id, _ts(session_idx, turn)))
        turn += 1
        entries.append(make_assistant_entry(
            "I'll get started on that.",
            session_id=session_id,
            timestamp=_ts(session_idx, turn),
        ))
        turn += 1

    for corr in corrections:
        # Assistant action
        tools = []
        fp = corr.get("file_path", "")
        if fp:
            tools.append(make_edit_tool(fp))
        entries.append(make_assistant_entry(
            corr.get("assistant_text", "I've made the change."),
            tools=tools if tools else None,
            session_id=session_id,
            timestamp=_ts(session_idx, turn),
        ))
        turn += 1

        # User correction
        entries.append(make_user_entry(
            corr["user_text"],
            session_id,
            _ts(session_idx, turn),
        ))
        turn += 1

    return SessionDef(session_id=session_id, entries=entries)


def make_post_action_session(
    session_id: str,
    session_idx: int,
    actions: List[Dict[str, str]],
    opener: Optional[str] = None,
) -> SessionDef:
    """Build a session where user runs commands after assistant edits.

    Each action is a dict with:
      - file_path: file the assistant edited
      - user_command: the command the user runs after
    """
    entries: List[Dict[str, Any]] = []
    turn = 0

    if opener:
        entries.append(make_user_entry(opener, session_id, _ts(session_idx, turn)))
        turn += 1

    for action in actions:
        # Assistant edits
        entries.append(make_assistant_entry(
            "I've updated the file.",
            tools=[make_edit_tool(action["file_path"])],
            session_id=session_id,
            timestamp=_ts(session_idx, turn),
        ))
        turn += 1

        # User runs command
        entries.append(make_user_entry(
            action["user_command"],
            session_id,
            _ts(session_idx, turn),
        ))
        turn += 1

    return SessionDef(session_id=session_id, entries=entries)


# ---------------------------------------------------------------------------
# Content generators
# ---------------------------------------------------------------------------

def make_package_json(
    name: str = "test-project",
    deps: Optional[Dict[str, str]] = None,
    dev_deps: Optional[Dict[str, str]] = None,
) -> str:
    """Generate a package.json file."""
    pkg: Dict[str, Any] = {"name": name, "version": "1.0.0"}
    if deps:
        pkg["dependencies"] = deps
    if dev_deps:
        pkg["devDependencies"] = dev_deps
    return json.dumps(pkg, indent=2)


def make_pyproject_toml(
    name: str = "test-project",
    deps: Optional[List[str]] = None,
    dev_section: str = "",
) -> str:
    """Generate a pyproject.toml file."""
    lines = [
        "[project]",
        f'name = "{name}"',
        'version = "1.0.0"',
    ]
    if deps:
        lines.append("dependencies = [")
        for d in deps:
            lines.append(f'    "{d}",')
        lines.append("]")
    if dev_section:
        lines.append("")
        lines.append(dev_section)
    return "\n".join(lines) + "\n"


def make_cargo_toml(name: str = "test-project") -> str:
    """Generate a Cargo.toml file."""
    return f"""[package]
name = "{name}"
version = "0.1.0"
edition = "2021"

[dependencies]
"""


def make_settings_json(hooks: Optional[Dict[str, Any]] = None) -> str:
    """Generate a .claude/settings.json file."""
    data: Dict[str, Any] = {}
    if hooks:
        data["hooks"] = hooks
    return json.dumps(data, indent=2)


def make_skill_md(name: str, description: str, body: str = "") -> str:
    """Generate a SKILL.md file."""
    return f"""---
name: {name}
description: >-
  {description}
---

{body or '## Steps'}
"""


def make_agent_md(
    name: str,
    description: str,
    model: str = "sonnet",
    effort: str = "low",
) -> str:
    """Generate an agent markdown file."""
    return f"""---
name: {name}
description: >-
  {description}
model: {model}
effort: {effort}
maxTurns: 10
disallowedTools:
  - Write
  - Edit
  - Bash
---

## Instructions

{description}
"""


def make_rule_md(
    content: str,
    paths: Optional[List[str]] = None,
) -> str:
    """Generate a rule markdown file."""
    if paths:
        paths_yaml = "\n".join(f'  - "{p}"' for p in paths)
        return f"---\npaths:\n{paths_yaml}\n---\n\n{content}\n"
    return content + "\n"


# ---------------------------------------------------------------------------
# Session JSONL serialization
# ---------------------------------------------------------------------------

def session_to_jsonl(session: SessionDef) -> str:
    """Serialize a SessionDef to JSONL string."""
    lines = []
    for entry in session.entries:
        lines.append(json.dumps(entry))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Profile definitions
# ---------------------------------------------------------------------------

def profile_swift_ios() -> ProjectProfile:
    """Clean Swift/SwiftUI project with memory promotions only.

    No tech stack detection files (no package.json/pyproject.toml).
    Short CLAUDE.md with no placement issues.
    Memory files with promotable entries.
    No transcripts.
    """
    claude_md = """# Priority App

## Overview
A fast, minimal todo app for iOS and macOS using SwiftUI.

## Architecture
- MVVM pattern with SwiftData persistence
- CloudKit sync for cross-device data
- Centralized design tokens (colors, spacing, typography)

## Build
Open in Xcode and build for iOS 17+ or macOS 14+.

## Testing
Run tests via Xcode Test Navigator or `xcodebuild test`.
"""

    memory_md = """# Memory Index

- [user_preferences.md](user_preferences.md) - User coding preferences
- [swift_conventions.md](swift_conventions.md) - Swift coding conventions
- [debug_notes.md](debug_notes.md) - Debugging notes
"""

    user_prefs = """---
name: user_preferences
description: User prefers minimal UI and accessibility-first design
type: user
---

User always uses SF Symbols for icons, never custom assets.
Prefers `async/await` over completion handlers.
"""

    swift_conventions = """---
name: swift_conventions
description: Swift naming and structure conventions for this project
type: feedback
---

Tests go in the Tests/ directory, mirroring the source structure.
Use `@Observable` macro instead of `ObservableObject` protocol.
Views follow the naming pattern: FeatureNameView.swift.
"""

    debug_notes = """---
name: debug_notes
description: Common debugging solutions for CloudKit sync issues
type: reference
---

When CloudKit sync fails silently, check the console for CKError codes.
If you see error 14, it usually means the schema hasn't been deployed.
The fix is to run the CloudKit Dashboard migration tool.
Workaround: reset the development container.
"""

    claude_local = """# Local Notes

- The build automation scripts in src/build use .py for CI/CD pipelines
- Run the codegen tool to regenerate components/Tokens from design-tokens.json
"""

    return ProjectProfile(
        name="swift-ios",
        config_files={
            "CLAUDE.md": claude_md,
            # No package.json, pyproject.toml, or Cargo.toml
        },
        sessions=[],  # No transcripts
        memory_files={
            "MEMORY.md": memory_md,
            "user_preferences.md": user_prefs,
            "swift_conventions.md": swift_conventions,
            "debug_notes.md": debug_notes,
            "CLAUDE.local.md": claude_local,  # goes to project root, not memory/
        },
        expected_signals={
            "memory_promotions": True,
            "config_gaps": False,
            "transcript_corrections": False,
            "transcript_post_actions": False,
        },
    )


def profile_react_ts() -> ProjectProfile:
    """Overgrown React/TypeScript project with placement issues and missing hooks.

    250+ line CLAUDE.md full of domain-specific content.
    package.json with react, typescript, prettier, eslint, vitest.
    docs/ directory not referenced.
    No hooks configured.
    """
    # Build a bloated CLAUDE.md with domain-specific entries
    claude_md_lines = [
        "# My React App",
        "",
        "## Overview",
        "A large-scale React application with TypeScript.",
        "",
        "## Architecture",
        "",
        "### Component Guidelines",
        "- All React components must use functional components with hooks.",
        "- Every .tsx file must export a single default component.",
        "- Use React.memo() for expensive render components.",
        "- Components in src/components/ must have a corresponding test file.",
        "- API route handlers in api/ must validate request bodies.",
        "- Always use `next/image` for image components in .tsx files.",
        "- Server components should be the default for pages/ directory.",
        "",
        "### Testing Conventions",
        "- Every .test.js file must have at least 80% code coverage.",
        "- Test specs using .spec.ts must follow the AAA pattern.",
        "- Put integration tests in tests/integration alongside unit tests.",
        "",
        "### API Patterns",
        "- API endpoints live in api/v2 and follow REST conventions.",
        "- Each route handler in routes/admin must check auth first.",
        "- Use zod for request validation in api/handlers code.",
        "",
        "## State Management",
        "Use Zustand for global state, React Query for server state.",
        "",
        "## Styling",
        "Use Tailwind CSS utility classes. No inline styles.",
        "",
    ]

    # Pad to 250+ lines with generic content (not domain-specific)
    for i in range(220):
        claude_md_lines.append(f"- Guideline {i + 1}: Follow best practices for code quality.")

    claude_md = "\n".join(claude_md_lines)

    package_json = make_package_json(
        name="react-app",
        deps={
            "react": "^18.2.0",
            "react-dom": "^18.2.0",
            "next": "^14.0.0",
        },
        dev_deps={
            "typescript": "^5.0.0",
            "prettier": "^3.0.0",
            "eslint": "^8.0.0",
            "vitest": "^1.0.0",
            "@types/react": "^18.2.0",
        },
    )

    return ProjectProfile(
        name="react-ts",
        config_files={
            "CLAUDE.md": claude_md,
            "package.json": package_json,
            "tsconfig.json": '{"compilerOptions": {"jsx": "react-jsx"}}',
            "docs/README.md": "# Documentation\nProject docs go here.\n",
            "docs/api.md": "# API Reference\nEndpoint documentation.\n",
        },
        sessions=[],  # No transcripts needed for config testing
        memory_files={},
        expected_signals={
            "tech_stack": ["node", "react", "next.js", "typescript"],
            "formatter": "prettier",
            "linter": "eslint",
            "test_framework": "vitest",
            "missing_hooks": ["prettier", "eslint"],
            "placement_issues_min": 8,  # domain-specific entries in CLAUDE.md
            "over_budget": True,
            "demotion_domains": ["react", "testing", "api"],
            "docs_gap": True,
        },
    )


def profile_python_corrections() -> ProjectProfile:
    """Python project with rich transcript signals.

    Transcripts contain:
    - Repeated corrections about pathlib vs os.path (5 occurrences, 4 sessions)
    - Post-action: user runs pytest after Claude edits (6 occurrences, 4 sessions)
    - Repeated opening prompt: "run the test suite and fix failures" (4 sessions)
    """
    claude_md = """# Python Tool

## Overview
A command-line tool for data processing.

## Development
- Python 3.8+, stdlib only
- Use pathlib for filesystem operations
- Run tests with `pytest`
"""

    pyproject = make_pyproject_toml(
        name="python-tool",
        dev_section="""[tool.ruff]
line-length = 100

[tool.ruff.format]
quote-style = "double"

[tool.pytest.ini_options]
testpaths = ["tests"]
""",
    )

    settings = make_settings_json(hooks={
        "PostToolUse": [{
            "matcher": "Write|Edit",
            "hooks": [{
                "type": "command",
                "command": 'ruff format "$CLAUDE_TOOL_INPUT_FILE_PATH"',
                "timeout": 10,
            }],
        }],
    })

    rule_content = """# Code style

- Use type hints on all public functions.
- Prefer list comprehensions over map/filter.
"""

    # --- Build transcript sessions ---
    sessions = []

    # Pathlib correction text variations
    pathlib_corrections = [
        "No, don't use os.path for this. Use pathlib.Path instead.",
        "I told you to use pathlib, not os.path. Switch to Path objects.",
        "That's not right — we use pathlib in this project, not os.path.",
        "Use pathlib instead. We never use os.path here.",
        "Don't use os.path. Should be using pathlib.Path for all filesystem ops.",
        "Actually, switch to pathlib. We don't use os.path in this codebase.",
    ]

    # Session 1: 2 pathlib corrections + opens with test runner prompt
    sessions.append(make_correction_session(
        session_id="session-corr-1",
        session_idx=0,
        opener="Run the test suite and fix any failures you find",
        corrections=[
            {
                "user_text": pathlib_corrections[0],
                "assistant_text": "I'll update the file path handling using os.path.join.",
                "file_path": "/src/utils.py",
            },
            {
                "user_text": pathlib_corrections[1],
                "assistant_text": "I've used os.path.exists to check the file.",
                "file_path": "/src/loader.py",
            },
        ],
    ))

    # Session 2: 1 pathlib correction + pytest post-action
    s2_entries = []
    s2_entries.append(make_user_entry("Fix the data parser", "session-corr-2", _ts(1, 0)))
    s2_entries.append(make_assistant_entry(
        "I'll fix the parser.",
        tools=[make_edit_tool("/src/parser.py")],
        session_id="session-corr-2",
        timestamp=_ts(1, 1),
    ))
    s2_entries.append(make_user_entry(pathlib_corrections[2], "session-corr-2", _ts(1, 2)))
    # Post-action: pytest
    s2_entries.append(make_assistant_entry(
        "I've made the fix.",
        tools=[make_edit_tool("/src/parser.py")],
        session_id="session-corr-2",
        timestamp=_ts(1, 3),
    ))
    s2_entries.append(make_user_entry("pytest tests/", "session-corr-2", _ts(1, 4)))
    sessions.append(SessionDef(session_id="session-corr-2", entries=s2_entries))

    # Session 3: 1 pathlib correction + 2 pytest post-actions
    s3_entries = []
    s3_entries.append(make_user_entry("Refactor the config module", "session-corr-3", _ts(2, 0)))
    s3_entries.append(make_assistant_entry(
        "I'll refactor the config handling with os.path.",
        tools=[make_edit_tool("/src/config.py")],
        session_id="session-corr-3",
        timestamp=_ts(2, 1),
    ))
    s3_entries.append(make_user_entry(pathlib_corrections[3], "session-corr-3", _ts(2, 2)))
    s3_entries.append(make_assistant_entry(
        "Updated to use pathlib.",
        tools=[make_edit_tool("/src/config.py")],
        session_id="session-corr-3",
        timestamp=_ts(2, 3),
    ))
    s3_entries.append(make_user_entry("pytest", "session-corr-3", _ts(2, 4)))
    s3_entries.append(make_assistant_entry(
        "Fixed another module.",
        tools=[make_edit_tool("/src/helpers.py")],
        session_id="session-corr-3",
        timestamp=_ts(2, 5),
    ))
    s3_entries.append(make_user_entry("pytest tests/ -v", "session-corr-3", _ts(2, 6)))
    sessions.append(SessionDef(session_id="session-corr-3", entries=s3_entries))

    # Session 4: opens with test runner prompt + 1 pathlib correction + 1 pytest
    sessions.append(make_correction_session(
        session_id="session-corr-4",
        session_idx=3,
        opener="Run the test suite and fix the failures",
        corrections=[
            {
                "user_text": pathlib_corrections[4],
                "assistant_text": "I used os.path.dirname to get the parent dir.",
                "file_path": "/src/output.py",
            },
        ],
    ))
    # Add post-action
    sessions[-1].entries.append(make_assistant_entry(
        "Applied the pathlib fix.",
        tools=[make_edit_tool("/src/output.py")],
        session_id="session-corr-4",
        timestamp=_ts(3, 5),
    ))
    sessions[-1].entries.append(make_user_entry("pytest", "session-corr-4", _ts(3, 6)))

    # Session 5: 2 pytest post-actions, no corrections
    sessions.append(make_post_action_session(
        session_id="session-corr-5",
        session_idx=4,
        actions=[
            {"file_path": "/src/main.py", "user_command": "pytest tests/ -x"},
            {"file_path": "/src/cli.py", "user_command": "pytest"},
        ],
    ))

    # Session 6: opens with test runner prompt
    s6_entries = []
    s6_entries.append(make_user_entry(
        "Run the tests and fix any failures",
        "session-corr-6", _ts(5, 0),
    ))
    s6_entries.append(make_assistant_entry(
        "Running tests now.",
        tools=[make_bash_tool("pytest tests/ -v")],
        session_id="session-corr-6",
        timestamp=_ts(5, 1),
    ))
    s6_entries.append(make_user_entry("Thanks, looks good.", "session-corr-6", _ts(5, 2)))
    sessions.append(SessionDef(session_id="session-corr-6", entries=s6_entries))

    # Session 7: 1 pytest post-action
    sessions.append(make_post_action_session(
        session_id="session-corr-7",
        session_idx=6,
        actions=[
            {"file_path": "/src/validator.py", "user_command": "pytest tests/test_validator.py"},
        ],
    ))

    # Session 8: opens with test runner prompt
    s8_entries = []
    s8_entries.append(make_user_entry(
        "Run the test suite and fix failures",
        "session-corr-8", _ts(7, 0),
    ))
    s8_entries.append(make_assistant_entry(
        "I'll run the test suite.",
        session_id="session-corr-8",
        timestamp=_ts(7, 1),
    ))
    sessions.append(SessionDef(session_id="session-corr-8", entries=s8_entries))

    return ProjectProfile(
        name="python-corrections",
        config_files={
            "CLAUDE.md": claude_md,
            "pyproject.toml": pyproject,
            ".claude/settings.json": settings,
            ".claude/rules/code-style.md": rule_content,
        },
        sessions=sessions,
        memory_files={},
        expected_signals={
            "correction_themes_min": 1,  # pathlib theme
            "post_actions_min": 1,  # pytest
            "repeated_prompts_min": 1,  # test runner opener
            "ruff_hook_exists": True,  # should NOT propose formatter hook
        },
    )


def profile_rust_minimal() -> ProjectProfile:
    """Minimal Rust project with oversized rule but below-threshold transcripts.

    Tests threshold enforcement: signals exist but don't meet minimums.
    """
    claude_md = """# Rust CLI Tool

## Overview
A command-line tool written in Rust.

## Build
Run `cargo build` to compile. `cargo test` for tests.

## Code Style
Follow standard Rust conventions. Use `cargo fmt` before committing.
"""

    # Oversized rule (120+ lines)
    rule_lines = ["# Rust Error Handling Guide", ""]
    for i in range(120):
        rule_lines.append(f"- Rule {i + 1}: Always handle Result types explicitly.")
    oversized_rule = "\n".join(rule_lines)

    settings = make_settings_json(hooks={
        "PostToolUse": [{
            "matcher": "Write|Edit",
            "hooks": [{
                "type": "command",
                "command": 'cargo fmt -- "$CLAUDE_TOOL_INPUT_FILE_PATH"',
                "timeout": 10,
            }],
        }],
    })

    # Below-threshold transcripts: 2 corrections in 1 session (need 3+ in 2+)
    sessions = []
    sessions.append(make_correction_session(
        session_id="session-rust-1",
        session_idx=0,
        corrections=[
            {
                "user_text": "Don't use unwrap, use the ? operator instead.",
                "assistant_text": "I'll read the file with unwrap().",
                "file_path": "/src/main.rs",
            },
            {
                "user_text": "Use ? not unwrap here.",
                "assistant_text": "Updated with unwrap().",
                "file_path": "/src/lib.rs",
            },
        ],
    ))

    # 1 repeated prompt, but only 2 sessions (need 3+)
    s2_entries = []
    s2_entries.append(make_user_entry(
        "Build and run the tests",
        "session-rust-2", _ts(1, 0),
    ))
    s2_entries.append(make_assistant_entry(
        "Running cargo test.",
        session_id="session-rust-2",
        timestamp=_ts(1, 1),
    ))
    sessions.append(SessionDef(session_id="session-rust-2", entries=s2_entries))

    s3_entries = []
    s3_entries.append(make_user_entry(
        "Build and run the tests",
        "session-rust-3", _ts(2, 0),
    ))
    s3_entries.append(make_assistant_entry(
        "I'll run cargo test.",
        session_id="session-rust-3",
        timestamp=_ts(2, 1),
    ))
    sessions.append(SessionDef(session_id="session-rust-3", entries=s3_entries))

    return ProjectProfile(
        name="rust-minimal",
        config_files={
            "CLAUDE.md": claude_md,
            "Cargo.toml": make_cargo_toml("rust-cli"),
            ".claude/settings.json": settings,
            ".claude/rules/error-handling.md": oversized_rule,
        },
        sessions=sessions,
        memory_files={},
        expected_signals={
            "tech_stack": ["rust"],
            "formatter_hook_exists": True,
            "oversized_rule": True,
            "transcript_proposals": 0,  # all below threshold
        },
    )


def profile_fullstack_mature() -> ProjectProfile:
    """Well-configured project where strong signals are filtered by dismissals.

    Tests the negative path: dismissed proposals, suppressed themes,
    and dedup against existing skills.
    """
    claude_md = """# Full-Stack App

## Overview
A Next.js application with a PostgreSQL backend.

## Development
- Use `pnpm` as the package manager.
- Run `pnpm dev` to start the development server.
- Run `pnpm test` to run the test suite.
- Format with Prettier, lint with ESLint.

## Deployment
Run the deploy skill to push to staging.
"""

    package_json = make_package_json(
        name="fullstack-app",
        deps={
            "next": "^14.0.0",
            "react": "^18.2.0",
        },
        dev_deps={
            "prettier": "^3.0.0",
            "eslint": "^8.0.0",
            "jest": "^29.0.0",
        },
    )

    settings = make_settings_json(hooks={
        "PostToolUse": [
            {
                "matcher": "Write|Edit",
                "hooks": [
                    {
                        "type": "command",
                        "command": 'npx prettier --write "$CLAUDE_TOOL_INPUT_FILE_PATH"',
                        "timeout": 10,
                    },
                    {
                        "type": "command",
                        "command": 'npx eslint --no-warn-ignored --quiet "$CLAUDE_FILE_PATHS"',
                        "timeout": 10,
                    },
                ],
            },
        ],
    })

    deploy_skill = make_skill_md(
        name="deploy",
        description="Deploy the application to staging. Use when the user asks to deploy.",
        body="## Steps\n\n1. Run tests\n2. Build the app\n3. Deploy to staging\n",
    )

    reviewer_agent = make_agent_md(
        name="reviewer",
        description="Review code changes for quality and security issues.",
    )

    # Strong transcript signals that will be dismissed
    sessions = []

    # Repeated opening prompt: "deploy to staging" — 7 occurrences, 5 sessions
    for i in range(5):
        s_entries = []
        s_entries.append(make_user_entry(
            "Deploy to staging" if i < 3 else "Deploy the app to staging",
            f"session-fs-{i + 1}", _ts(i, 0),
        ))
        s_entries.append(make_assistant_entry(
            "I'll deploy to staging now.",
            session_id=f"session-fs-{i + 1}",
            timestamp=_ts(i, 1),
        ))
        if i < 2:
            # Extra deploy requests in some sessions
            s_entries.append(make_user_entry(
                "Deploy to staging again",
                f"session-fs-{i + 1}", _ts(i, 2),
            ))
            s_entries.append(make_assistant_entry(
                "Deploying again.",
                session_id=f"session-fs-{i + 1}",
                timestamp=_ts(i, 3),
            ))
        sessions.append(SessionDef(session_id=f"session-fs-{i + 1}", entries=s_entries))

    # Correction pattern: "always use server components" — 4 occurrences, 3 sessions
    server_component_corrections = [
        "Don't use client components here. Always use server components.",
        "Should not be a client component. Use server components instead.",
        "Use server components, not client components.",
        "Never use client components in this directory.",
    ]
    for i, corr_text in enumerate(server_component_corrections[:3]):
        sessions.append(make_correction_session(
            session_id=f"session-fs-corr-{i + 1}",
            session_idx=5 + i,
            corrections=[
                {
                    "user_text": corr_text,
                    "assistant_text": "I've added the 'use client' directive.",
                    "file_path": f"/app/page{i}.tsx",
                },
            ],
        ))
    # 4th correction in existing session
    sessions[5].entries.extend([
        make_assistant_entry(
            "Updated the component.",
            tools=[make_edit_tool("/app/layout.tsx")],
            session_id="session-fs-corr-1",
            timestamp=_ts(5, 4),
        ),
        make_user_entry(
            server_component_corrections[3],
            "session-fs-corr-1", _ts(5, 5),
        ),
    ])

    # Memory with promotable notes
    memory_md = """# Memory

- [preferences.md](preferences.md) - User coding preferences
"""

    preferences = """---
name: preferences
description: User prefers pnpm and server components
type: user
---

Always use pnpm, never npm or yarn.
Prefers server components over client components in Next.js.
Dark mode should be the default theme.
"""

    # Build dismissed list — deploy skill was already dismissed
    dismissed = [
        {
            "id": "deploy-to-staging-skill",
            "description": "Create /deploy-to-staging skill from repeated pattern",
            "status": "dismissed",
        },
    ]

    # The correction theme hash for "server components" — we need to compute it
    # Using the same algorithm as analyze-transcripts.py
    from hashlib import md5
    server_terms = sorted({"client", "components", "server"})[:5]
    theme_hash = md5("|".join(server_terms).encode()).hexdigest()[:8]

    return ProjectProfile(
        name="fullstack-mature",
        config_files={
            "CLAUDE.md": claude_md,
            "package.json": package_json,
            "tsconfig.json": '{"compilerOptions": {"jsx": "react-jsx"}}',
            ".claude/settings.json": settings,
            ".claude/skills/deploy/SKILL.md": deploy_skill,
            ".claude/agents/reviewer.md": reviewer_agent,
        },
        sessions=sessions,
        memory_files={
            "MEMORY.md": memory_md,
            "preferences.md": preferences,
        },
        dismissed=dismissed,
        suppressed_themes=[theme_hash],
        expected_signals={
            "formatter_hook_exists": True,
            "linter_hook_exists": True,
            "deploy_skill_exists": True,
            "deploy_dismissed": True,
            "correction_suppressed": True,
            "memory_promotions": True,
        },
    )


# ---------------------------------------------------------------------------
# Fixture materialization
# ---------------------------------------------------------------------------

def materialize_profile(profile: ProjectProfile, base_dir: Path) -> Path:
    """Write all files for a profile to disk. Returns the project root path."""
    project_root = base_dir / profile.name
    project_root.mkdir(parents=True, exist_ok=True)

    # Write config files
    for rel_path, content in profile.config_files.items():
        file_path = project_root / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    # Write transcript JSONL files
    transcripts_dir = project_root / "_transcripts"
    if profile.sessions:
        transcripts_dir.mkdir(parents=True, exist_ok=True)
        for session in profile.sessions:
            jsonl_path = transcripts_dir / f"{session.session_id}.jsonl"
            jsonl_path.write_text(
                session_to_jsonl(session),
                encoding="utf-8",
            )

    # Write memory files
    if profile.memory_files:
        for filename, content in profile.memory_files.items():
            if filename == "CLAUDE.local.md":
                # CLAUDE.local.md goes in project root
                (project_root / filename).write_text(content, encoding="utf-8")
            else:
                memory_dir = project_root / "_memory"
                memory_dir.mkdir(parents=True, exist_ok=True)
                (memory_dir / filename).write_text(content, encoding="utf-8")

    # Write dismissed.json
    if profile.dismissed:
        forge_dir = project_root / "_forge_data"
        forge_dir.mkdir(parents=True, exist_ok=True)
        (forge_dir / "dismissed.json").write_text(
            json.dumps(profile.dismissed, indent=2),
            encoding="utf-8",
        )

    # Write suppressed themes into analyzer-stats.json
    if profile.suppressed_themes:
        forge_dir = project_root / "_forge_data"
        forge_dir.mkdir(parents=True, exist_ok=True)
        stats = {
            "version": 1,
            "corrections": {"proposed": 0, "approved": 0, "dismissed": 0},
            "post_actions": {"proposed": 0, "approved": 0, "dismissed": 0},
            "repeated_prompts": {"proposed": 0, "approved": 0, "dismissed": 0},
            "theme_outcomes": {},
            "suppressed_themes": profile.suppressed_themes,
        }
        (forge_dir / "analyzer-stats.json").write_text(
            json.dumps(stats, indent=2),
            encoding="utf-8",
        )

    # Write expected signals metadata
    meta_path = project_root / "_expected.json"
    meta_path.write_text(
        json.dumps(profile.expected_signals, indent=2),
        encoding="utf-8",
    )

    return project_root


# ---------------------------------------------------------------------------
# All profiles
# ---------------------------------------------------------------------------

ALL_PROFILES = [
    profile_swift_ios,
    profile_react_ts,
    profile_python_corrections,
    profile_rust_minimal,
    profile_fullstack_mature,
]


def generate_all(output_dir: Path) -> Dict[str, Path]:
    """Generate all profiles and return {name: project_root} mapping."""
    results = {}
    for profile_fn in ALL_PROFILES:
        profile = profile_fn()
        root = materialize_profile(profile, output_dir)
        results[profile.name] = root
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic Forge test fixtures."
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: creates temp dir).",
    )
    args = parser.parse_args()

    if args.output_dir:
        output = Path(args.output_dir)
    else:
        import tempfile
        output = Path(tempfile.mkdtemp(prefix="forge-fixtures-"))

    output.mkdir(parents=True, exist_ok=True)
    results = generate_all(output)

    print(f"Generated {len(results)} profiles in: {output}")
    for name, path in results.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()

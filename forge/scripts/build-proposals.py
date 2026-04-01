#!/usr/bin/env python3
"""Build proposals from analysis results.

Takes the JSON output of all three analysis scripts (config, transcripts,
memory) and produces a ready-to-present list of proposals. This moves the
heavy cross-referencing, threshold filtering, and impact scoring from
LLM processing time to zero-cost Python execution.

Usage:
    python3 build-proposals.py --config <config.json> --transcripts <transcripts.json> --memory <memory.json> [--dismissed <dismissed.json>] [--pending <pending.json>]

Or pipe combined JSON:
    python3 build-proposals.py --combined <combined.json>

Output: JSON object with "proposals" array and "context_health" summary.
"""

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Evidence thresholds
# ---------------------------------------------------------------------------

THRESHOLDS = {
    "skill": {"min_occurrences": 4, "min_sessions": 3},
    "hook": {"min_occurrences": 5, "min_sessions": 3},
    "rule": {"min_occurrences": 3, "min_sessions": 2},
    "claude_md_entry": {"min_occurrences": 3, "min_sessions": 2},
    "agent": {"min_occurrences": 5, "min_sessions": 3},
}

STALENESS_THRESHOLDS = {
    "min_sessions_for_analysis": 10,
    "stale_session_count": 15,   # not seen in last N sessions → stale
}


# ---------------------------------------------------------------------------
# Text similarity for cross-referencing
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> set:
    """Simple word tokenization, lowercased, alpha-only."""
    return {w.lower() for w in re.findall(r'[a-zA-Z]{3,}', text)}


def _similarity(text_a: str, text_b: str) -> float:
    """Jaccard similarity between two texts."""
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _matches_existing(pattern_text: str, existing_items: List[Dict],
                      threshold: float = 0.3) -> Optional[Dict]:
    """Check if a pattern matches an existing skill/agent/hook.

    Returns the matching item if found, None otherwise.
    Checks both description and full content for semantic overlap.
    """
    for item in existing_items:
        # Check against name
        name = item.get("name", "")
        if name and _similarity(pattern_text, name) > 0.4:
            return item

        # Check against description
        desc = item.get("description", "")
        if desc and _similarity(pattern_text, desc) > threshold:
            return item

        # Check against full content (more lenient threshold)
        content = item.get("content", "")
        if content and _similarity(pattern_text, content) > 0.2:
            return item

    return None


# ---------------------------------------------------------------------------
# Impact scoring
# ---------------------------------------------------------------------------

def _score_impact(proposal_type: str, occurrences: int = 0,
                  sessions: int = 0, severity: str = "") -> str:
    """Score a proposal's impact as high, medium, or low."""
    if proposal_type == "skill":
        if occurrences >= 8 or sessions >= 6:
            return "high"
        elif occurrences >= 4:
            return "medium"
        return "low"

    if proposal_type == "hook":
        if severity == "high":
            return "high"
        return "medium"

    if proposal_type == "skill_update":
        return "medium"

    if proposal_type in ("rule", "claude_md_entry"):
        if occurrences >= 5 or sessions >= 4:
            return "high"
        return "medium"

    if proposal_type == "agent":
        if occurrences >= 8 or sessions >= 5:
            return "high"
        elif occurrences >= 5:
            return "medium"
        return "low"

    if proposal_type == "stale_artifact":
        # Never referenced → high; referenced in very few → medium
        if occurrences == 0:
            return "high"
        return "medium"

    if proposal_type == "reference_doc":
        return "low"

    if proposal_type == "demotion":
        if severity == "over_budget":
            return "high"
        return "medium"

    return "medium"


# ---------------------------------------------------------------------------
# Template generators for suggested content
# ---------------------------------------------------------------------------

def _generate_skill_content(pattern: str, examples: List[str]) -> str:
    """Generate a draft skill from a repeated prompt pattern."""
    # Derive a name from the pattern
    name = re.sub(r'[^a-z0-9]+', '-', pattern.lower()).strip('-')[:30]

    example_text = ""
    if examples:
        example_text = "\n".join(f"- \"{ex}\"" for ex in examples[:3])

    return f"""---
name: {name}
description: >-
  {pattern}. Use when the user asks to {pattern.lower()}.
---

<!-- Draft generated by Forge — test and iterate -->

## Steps

1. [TODO: Define the specific steps for this workflow]

## Trigger phrases

Users typically say:
{example_text or '- [Add common trigger phrases]'}
"""


def _generate_hook_content(gap: Dict) -> str:
    """Generate a hook JSON snippet from a config gap."""
    detail = gap.get("detail", {})
    hook_event = detail.get("hook_event", "PostToolUse")
    matcher = detail.get("matcher", "Write|Edit")
    tool_name = (detail.get("linter") or detail.get("formatter")
                 or detail.get("test_framework") or "eslint")

    # Formatter commands
    _formatter_cmds = {
        "prettier": 'npx prettier --write "$CLAUDE_TOOL_INPUT_FILE_PATH"',
        "biome": 'npx biome format --write "$CLAUDE_TOOL_INPUT_FILE_PATH"',
        "black": 'black "$CLAUDE_TOOL_INPUT_FILE_PATH"',
        "rustfmt": 'rustfmt "$CLAUDE_TOOL_INPUT_FILE_PATH"',
        "gofmt": 'gofmt -w "$CLAUDE_TOOL_INPUT_FILE_PATH"',
        "ruff": 'ruff format "$CLAUDE_TOOL_INPUT_FILE_PATH"',
    }
    # Linter commands
    _linter_cmds = {
        "eslint": (
            'npx eslint --no-warn-ignored --quiet '
            '--max-warnings 0 "$CLAUDE_FILE_PATHS"'
        ),
        "ruff": 'ruff check "$CLAUDE_TOOL_INPUT_FILE_PATH"',
    }

    if tool_name in _formatter_cmds:
        command = _formatter_cmds[tool_name]
    elif tool_name in _linter_cmds:
        command = _linter_cmds[tool_name]
    else:
        command = f'{tool_name} "$CLAUDE_TOOL_INPUT_FILE_PATH"'

    return json.dumps({
        "hooks": {
            hook_event: [{
                "matcher": matcher,
                "hooks": [{
                    "type": "command",
                    "command": command,
                    "timeout": 10
                }]
            }]
        }
    }, indent=2)


def _generate_rule_content(issue: Dict) -> str:
    """Generate a rule file from a placement issue."""
    content = issue.get("content", "")
    suggestion = issue.get("suggestion", "")
    return f"""---
paths:
  - "**/*"
---

{content}
"""


def _generate_agent_content(pattern: str, phase_sequence: List[str],
                            evidence: List[Dict]) -> str:
    """Generate a draft agent markdown from a workflow pattern.

    Maps phase sequences to agent role descriptions, tool constraints,
    and workflow steps following the template in artifact-templates.md.
    """
    # Derive a kebab-case name from the pattern text
    name = re.sub(r'[^a-z0-9]+', '-', pattern.lower()).strip('-')[:30]
    # Clean up trailing hyphens from truncation
    name = name.rstrip('-')
    if not name:
        name = "workflow-agent"

    # Recognize well-known workflow archetypes by phase sequence
    phase_tuple = tuple(phase_sequence)
    archetype = _AGENT_ARCHETYPES.get(phase_tuple)
    if archetype is None:
        # Fall back to phase-set heuristic
        archetype = _archetype_from_phases(phase_sequence)

    role_description = archetype["role"]
    disallowed = archetype["disallowed"]
    description = archetype["description"]
    step_templates = archetype["steps"]

    # maxTurns based on sequence length
    seq_len = len(phase_sequence)
    if seq_len <= 3:
        max_turns = 10
    elif seq_len <= 4:
        max_turns = 15
    else:
        max_turns = 20

    # Build disallowedTools section
    if disallowed:
        tools_yaml = "\n".join("  - {}".format(t) for t in disallowed)
        disallowed_tools_section = (
            "disallowedTools:\n{}\n".format(tools_yaml)
        )
    else:
        disallowed_tools_section = ""

    # Build workflow steps
    workflow_steps = []
    for i, phase in enumerate(phase_sequence, 1):
        if isinstance(step_templates, list):
            template = (step_templates[i - 1]
                        if i - 1 < len(step_templates)
                        else _DEFAULT_STEP.get(phase, {}))
        else:
            template = step_templates.get(phase, _DEFAULT_STEP.get(phase, {}))
        title = template.get("title", phase.capitalize())
        instructions = template.get("instructions", "")
        tools = template.get("tools", "")
        step_parts = ["## Step {}: {}".format(i, title)]
        if instructions:
            step_parts.append(instructions)
        if tools:
            step_parts.append("**Tools:** {}".format(tools))
        workflow_steps.append("\n".join(step_parts))
    workflow_text = "\n\n".join(workflow_steps)

    # Build evidence summary from session data
    evidence_lines = []
    for ev in evidence[:3]:
        tools_used = ev.get("tools_used", [])
        turns = ev.get("turn_count", 0)
        if tools_used:
            evidence_lines.append(
                "- Session {}: {} turns, tools: {}".format(
                    ev.get("session", "?")[:8],
                    turns,
                    ", ".join(tools_used[:6]),
                )
            )
    evidence_text = ""
    if evidence_lines:
        evidence_text = (
            "\n## Evidence\n\n"
            "This agent was derived from recurring workflow patterns:\n"
            + "\n".join(evidence_lines)
        )

    return """---
name: {name}
description: >-
  {description}. Use when the user asks to {trigger}.
model: sonnet
effort: low
maxTurns: {max_turns}
{disallowed_section}---

<!-- Draft generated by Forge -- test and iterate -->

You are the {name} agent. Your role is to {role}.

{workflow}
{evidence}
## Constraints

- Complete your work within {max_turns} turns
- Report findings clearly with file paths and line numbers
- If a step fails, report the failure rather than retrying silently
""".format(
        name=name,
        description=description,
        trigger=pattern.lower(),
        max_turns=max_turns,
        disallowed_section=disallowed_tools_section,
        role=role_description,
        workflow=workflow_text,
        evidence=evidence_text,
    )


# ---------------------------------------------------------------------------
# Agent archetype definitions
# ---------------------------------------------------------------------------

_DEFAULT_STEP = {
    "read": {
        "title": "Research",
        "instructions": (
            "Read relevant files, search the codebase, and gather context "
            "needed for the task."
        ),
        "tools": "Read, Grep, Glob",
    },
    "write": {
        "title": "Implement",
        "instructions": "Make the necessary code changes.",
        "tools": "Edit, Write",
    },
    "execute": {
        "title": "Verify",
        "instructions": (
            "Run tests, linters, or other checks to validate the changes."
        ),
        "tools": "Bash",
    },
}

_AGENT_ARCHETYPES = {
    ("read", "write", "execute"): {
        "role": (
            "plan an approach by researching the codebase, implement the "
            "changes, then verify correctness by running tests or checks"
        ),
        "disallowed": [],
        "description": "Plan, implement, and verify workflow agent",
        "steps": {
            "read": {
                "title": "Plan",
                "instructions": (
                    "Understand the task requirements. Search for relevant "
                    "files, read existing implementations, and identify what "
                    "needs to change. Form a plan before writing any code."
                ),
                "tools": "Read, Grep, Glob",
            },
            "write": {
                "title": "Implement",
                "instructions": (
                    "Apply the planned changes. Edit existing files or create "
                    "new ones as needed. Keep changes minimal and focused."
                ),
                "tools": "Edit, Write",
            },
            "execute": {
                "title": "Verify",
                "instructions": (
                    "Run the project's test suite or relevant checks to "
                    "confirm the changes work correctly. If tests fail, "
                    "report what went wrong."
                ),
                "tools": "Bash",
            },
        },
    },
    ("read", "write"): {
        "role": (
            "research the codebase to understand context, then implement "
            "changes based on findings"
        ),
        "disallowed": [],
        "description": "Research and implement agent",
        "steps": {
            "read": {
                "title": "Research",
                "instructions": (
                    "Search the codebase for relevant files, patterns, and "
                    "conventions. Understand the existing architecture before "
                    "making changes."
                ),
                "tools": "Read, Grep, Glob",
            },
            "write": {
                "title": "Implement",
                "instructions": (
                    "Apply changes based on research findings. Follow "
                    "existing patterns and conventions found in the codebase."
                ),
                "tools": "Edit, Write",
            },
        },
    },
    ("read", "execute"): {
        "role": (
            "audit the codebase by reading files and running checks, "
            "reporting findings without making changes"
        ),
        "disallowed": ["Write", "Edit"],
        "description": "Audit and validate agent",
        "steps": {
            "read": {
                "title": "Investigate",
                "instructions": (
                    "Read the relevant files and search for patterns that "
                    "need validation."
                ),
                "tools": "Read, Grep, Glob",
            },
            "execute": {
                "title": "Validate",
                "instructions": (
                    "Run checks, tests, or analysis commands. Report "
                    "results with specific file paths and line numbers."
                ),
                "tools": "Bash",
            },
        },
    },
    ("read", "write", "execute", "write"): {
        "role": (
            "research, implement, run tests, then fix any issues found -- "
            "an iterative development cycle"
        ),
        "disallowed": [],
        "description": "Iterative development agent",
        "steps": [
            {
                "title": "Research",
                "instructions": (
                    "Understand the task. Read relevant files and gather "
                    "context for the implementation."
                ),
                "tools": "Read, Grep, Glob",
            },
            {
                "title": "Implement",
                "instructions": "Make the initial code changes.",
                "tools": "Edit, Write",
            },
            {
                "title": "Test",
                "instructions": (
                    "Run the test suite or relevant checks. Note any "
                    "failures for the next step."
                ),
                "tools": "Bash",
            },
            {
                "title": "Fix",
                "instructions": (
                    "Fix any issues found during testing. Apply targeted "
                    "corrections based on test output."
                ),
                "tools": "Edit, Write",
            },
        ],
    },
    ("read", "write", "execute", "write", "execute"): {
        "role": (
            "follow a test-driven workflow: research the task, write an "
            "initial implementation, test it, fix failures, and re-verify"
        ),
        "disallowed": [],
        "description": "Test-driven development agent",
        "steps": [
            {
                "title": "Research",
                "instructions": (
                    "Understand the requirements. Read tests, specs, and "
                    "related code."
                ),
                "tools": "Read, Grep, Glob",
            },
            {
                "title": "Implement",
                "instructions": "Write the initial implementation.",
                "tools": "Edit, Write",
            },
            {
                "title": "Test",
                "instructions": "Run the test suite. Record any failures.",
                "tools": "Bash",
            },
            {
                "title": "Fix",
                "instructions": (
                    "Fix failures found during testing. Apply targeted "
                    "corrections."
                ),
                "tools": "Edit, Write",
            },
            {
                "title": "Re-verify",
                "instructions": (
                    "Run the test suite again to confirm all fixes work "
                    "correctly."
                ),
                "tools": "Bash",
            },
        ],
    },
    ("read", "execute", "write"): {
        "role": (
            "diagnose an issue by reading code and running checks, then "
            "apply a fix based on the diagnosis"
        ),
        "disallowed": [],
        "description": "Diagnose and fix agent",
        "steps": {
            "read": {
                "title": "Investigate",
                "instructions": (
                    "Read error logs, relevant source files, and any "
                    "related configuration to understand the issue."
                ),
                "tools": "Read, Grep, Glob",
            },
            "execute": {
                "title": "Diagnose",
                "instructions": (
                    "Run diagnostic commands to reproduce and confirm "
                    "the issue. Identify the root cause."
                ),
                "tools": "Bash",
            },
            "write": {
                "title": "Fix",
                "instructions": (
                    "Apply the fix based on the diagnosis. Keep the change "
                    "minimal and targeted."
                ),
                "tools": "Edit, Write",
            },
        },
    },
    ("execute", "read", "write"): {
        "role": (
            "run a command to identify issues, analyze the results, then "
            "apply fixes"
        ),
        "disallowed": [],
        "description": "Run, analyze, and fix agent",
        "steps": {
            "execute": {
                "title": "Run",
                "instructions": (
                    "Execute the relevant command (tests, linter, build) "
                    "to identify issues."
                ),
                "tools": "Bash",
            },
            "read": {
                "title": "Analyze",
                "instructions": (
                    "Read the failing files and error output to understand "
                    "what went wrong."
                ),
                "tools": "Read, Grep, Glob",
            },
            "write": {
                "title": "Fix",
                "instructions": "Apply targeted fixes based on the analysis.",
                "tools": "Edit, Write",
            },
        },
    },
}


def _archetype_from_phases(phase_sequence: List[str]) -> Dict[str, Any]:
    """Fallback archetype when no exact match exists in _AGENT_ARCHETYPES."""
    phase_set = set(phase_sequence)
    if phase_set == {"read"}:
        return {
            "role": "research and analyze code, reporting findings",
            "disallowed": ["Write", "Edit", "Bash"],
            "description": "Read-only analysis agent",
            "steps": {
                "read": _DEFAULT_STEP["read"],
            },
        }
    if "execute" in phase_set and "write" in phase_set:
        return {
            "role": (
                "complete a full workflow cycle: research, implement, "
                "and verify"
            ),
            "disallowed": [],
            "description": "Full-cycle workflow agent",
            "steps": _DEFAULT_STEP,
        }
    if "write" in phase_set:
        return {
            "role": (
                "research the codebase and implement changes based on "
                "findings"
            ),
            "disallowed": [],
            "description": "Research and implement agent",
            "steps": _DEFAULT_STEP,
        }
    return {
        "role": "audit the codebase by reading files and running checks",
        "disallowed": ["Write", "Edit"],
        "description": "Audit and check agent",
        "steps": _DEFAULT_STEP,
    }


# ---------------------------------------------------------------------------
# Proposal builders — one per source type
# ---------------------------------------------------------------------------

def _build_from_demotions(config: Dict) -> List[Dict]:
    """Build proposals from demotion candidates (tier rebalancing).

    Detects domain-specific CLAUDE.md entries that should be scoped rules,
    and oversized rules that should become reference docs.
    """
    proposals = []
    demotions = config.get("demotion_candidates", {})
    if not demotions:
        return proposals

    budget_info = demotions.get("budget", {})
    over_budget = budget_info.get("over_budget", False)
    seen_ids = set()  # type: set

    # --- CLAUDE.md → scoped rules ---
    for group in demotions.get("claude_md_to_rule", []):
        domain = group["domain"]
        filename = group["filename"]
        paths = group["paths"]
        entries = group["entries"]
        lines_saved = len(entries)

        paths_yaml = "\n".join(f'  - "{p}"' for p in paths)
        entries_md = "\n".join(f"- {e['content']}" for e in entries)

        suggested_content = (
            f"---\npaths:\n{paths_yaml}\n---\n\n"
            f"# {domain.title()} conventions\n\n{entries_md}\n"
        )
        pointer = (
            f"See .claude/rules/{filename}.md for {domain} conventions."
        )

        proposals.append({
            "id": f"demote-{filename}-to-rule",
            "type": "demotion",
            "impact": _score_impact(
                "demotion",
                severity="over_budget" if over_budget else "",
            ),
            "confidence": "high",
            "description": (
                f"Move {lines_saved} {domain}-specific entries from "
                f"CLAUDE.md to .claude/rules/{filename}.md"
            ),
            "evidence_summary": (
                f"{lines_saved} entries in CLAUDE.md are specific to "
                f"{domain} — scoping them to relevant files reduces "
                f"always-loaded context by ~{lines_saved} lines"
            ),
            "suggested_content": suggested_content,
            "suggested_path": f".claude/rules/{filename}.md",
            "demotion_detail": {
                "action": "claude_md_to_rule",
                "source_file": "CLAUDE.md",
                "entries": entries,
                "pointer": pointer,
                "lines_saved": lines_saved,
            },
            "status": "pending",
        })

    # --- Verbose CLAUDE.md sections → reference docs ---
    for section in demotions.get("claude_md_verbose_to_reference", []):
        heading = section["heading"]
        name = section["name"]
        line_count = section["line_count"]
        content = section["content"]

        # Deduplicate IDs (and paths) for sections with identical headings
        base_id = f"extract-{name}-to-ref"
        proposal_id = base_id
        ref_name = name
        idx = 2
        while proposal_id in seen_ids:
            proposal_id = f"{base_id}-{idx}"
            ref_name = f"{name}-{idx}"
            idx += 1
        seen_ids.add(proposal_id)

        pointer = (
            f"For detailed {heading.lower()} guidelines, see "
            f".claude/references/{ref_name}.md"
        )

        proposals.append({
            "id": proposal_id,
            "type": "demotion",
            "impact": _score_impact(
                "demotion",
                severity="over_budget" if over_budget else "",
            ),
            "confidence": "high" if line_count >= 8 else "medium",
            "description": (
                f"Extract verbose section \"{heading}\" from CLAUDE.md "
                f"({line_count} lines) to .claude/references/{ref_name}.md"
            ),
            "evidence_summary": (
                f"The \"{heading}\" section in CLAUDE.md is {line_count} "
                f"lines of prose — extracting to a reference doc keeps "
                f"CLAUDE.md concise while preserving the detail."
            ),
            "suggested_content": content,
            "suggested_path": f".claude/references/{ref_name}.md",
            "demotion_detail": {
                "action": "claude_md_verbose_to_reference",
                "source_file": "CLAUDE.md",
                "heading": heading,
                "line_start": section.get("line_start", 0),
                "line_end": section.get("line_end", 0),
                "pointer": pointer,
                "lines_saved": line_count,
            },
            "status": "pending",
        })

    # --- Oversized rules → reference docs ---
    for rule in demotions.get("rule_to_reference", []):
        rule_path = rule["path"]
        filename = rule["filename"]
        line_count = rule["line_count"]

        proposals.append({
            "id": f"demote-{filename}-rule-to-ref",
            "type": "demotion",
            "impact": "medium",
            "confidence": "medium",
            "description": (
                f"Extract detail from {rule_path} ({line_count} lines) "
                f"to .claude/references/{filename}.md"
            ),
            "evidence_summary": (
                f"{rule_path} is {line_count} lines — rules load into "
                f"context every session, so extracting verbose detail to a "
                f"reference doc reduces always-loaded context."
            ),
            "suggested_content": "",  # LLM reads the rule and decides
            "suggested_path": f".claude/references/{filename}.md",
            "demotion_detail": {
                "action": "rule_to_reference",
                "source_file": rule_path,
                "line_count": line_count,
                "pointer": (
                    f"For detailed {filename} guidelines, see "
                    f".claude/references/{filename}.md"
                ),
            },
            "status": "pending",
        })

    return proposals


def _build_from_gaps(config: Dict, existing_hooks: List[Dict]) -> List[Dict]:
    """Build proposals from config audit gaps."""
    proposals = []
    for gap in config.get("gaps", []):
        gap_type = gap.get("type", "")
        detail = gap.get("detail", {})

        if gap_type == "missing_hook":
            # Check if hook already exists
            hook_event = detail.get("hook_event", "")
            matcher = detail.get("matcher", "")
            already_exists = any(
                h.get("event") == hook_event and
                matcher in h.get("matcher", "")
                for h in existing_hooks
            )
            if already_exists:
                continue

            tool_name = (detail.get("linter") or detail.get("formatter")
                         or detail.get("test_framework") or "unknown")
            proposals.append({
                "id": f"auto-{tool_name}-hook",
                "type": "hook",
                "impact": _score_impact("hook", severity=gap.get("severity", "")),
                "confidence": "high",
                "description": f"Auto-{tool_name} hook after Edit/Write operations",
                "evidence_summary": (
                    f"{tool_name.capitalize()} configured but no {hook_event} "
                    f"hook exists — issues won't surface until manual run"
                ),
                "suggested_content": _generate_hook_content(gap),
                "suggested_path": ".claude/settings.json",
                "status": "pending",
            })

    return proposals


def _build_from_repeated_prompts(transcripts: Dict,
                                  existing_skills: List[Dict]) -> List[Dict]:
    """Build proposals from repeated prompt patterns."""
    proposals = []
    candidates = transcripts.get("candidates", {})

    for pattern in candidates.get("repeated_prompts", []):
        text = pattern.get("canonical_text",
                           pattern.get("pattern", ""))
        occurrences = pattern.get("total_occurrences",
                                   pattern.get("occurrences", 0))
        # sessions can be an int or an array of session IDs
        sessions_val = pattern.get("session_count",
                                    pattern.get("sessions", 0))
        sessions = (len(sessions_val) if isinstance(sessions_val, list)
                    else sessions_val)
        examples_raw = pattern.get("example_messages",
                                    pattern.get("evidence", []))
        # Extract user_message strings from evidence dicts
        examples = []
        for ex in examples_raw:
            if isinstance(ex, dict):
                msg = ex.get("user_message", "")
                if msg:
                    examples.append(msg[:100])
            elif isinstance(ex, str):
                examples.append(ex[:100])

        # Skip system-injected patterns (skill invocations, plugin content)
        if any(skip in text.lower() for skip in [
            "base directory for this skill",
            "you are running forge",
            "claude_plugin_root",
            "follow these steps in order",
        ]):
            continue
        # Also check evidence for system content
        if examples and all(
            any(skip in ex.lower() for skip in [
                "base directory for this skill",
                "you are running forge",
            ])
            for ex in examples
        ):
            continue

        # Check thresholds
        thresh = THRESHOLDS["skill"]
        if occurrences < thresh["min_occurrences"]:
            continue
        if sessions < thresh["min_sessions"]:
            continue

        # Cross-reference against existing skills
        match = _matches_existing(text, existing_skills)
        if match:
            # Existing skill covers this pattern — skip or suggest update
            match_name = match.get("name", "unknown")
            match_format = match.get("format", "skill")
            if match_format == "legacy_command":
                # Suggest migration
                proposals.append({
                    "id": f"migrate-{match_name}-to-skill",
                    "type": "skill_update",
                    "impact": "medium",
                    "confidence": "high",
                    "description": (
                        f"Migrate legacy command /{match_name} to modern "
                        f"skill format"
                    ),
                    "evidence_summary": (
                        f"/{match_name} is a .claude/commands/ file — "
                        f"modern skills have richer metadata and trigger "
                        f"detection"
                    ),
                    "suggested_content": "",  # LLM generates migration
                    "suggested_path": match.get("path", ""),
                    "status": "pending",
                })
            continue  # Don't propose a duplicate skill

        # New skill proposal
        name = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:30]
        proposals.append({
            "id": f"{name}-skill",
            "type": "skill",
            "impact": _score_impact("skill", occurrences, sessions),
            "confidence": "high" if occurrences >= 6 else "medium",
            "description": f"Create /{name} skill from repeated pattern",
            "evidence_summary": (
                f'"{text}" — {occurrences} occurrences across '
                f'{sessions} sessions'
            ),
            "suggested_content": _generate_skill_content(text, examples),
            "suggested_path": f".claude/skills/{name}/SKILL.md",
            "status": "pending",
        })

    return proposals


def _build_from_corrections(transcripts: Dict,
                             existing_skills: List[Dict]) -> List[Dict]:
    """Build proposals from correction patterns."""
    proposals = []
    candidates = transcripts.get("candidates", {})

    for correction in candidates.get("corrections", []):
        theme = correction.get("theme", correction.get("pattern", ""))
        occurrences = correction.get("total_occurrences",
                                      correction.get("occurrences", 0))
        sessions_val = correction.get("session_count",
                                       correction.get("sessions", 0))
        sessions = (len(sessions_val) if isinstance(sessions_val, list)
                    else sessions_val)

        thresh = THRESHOLDS["rule"]
        if occurrences < thresh["min_occurrences"]:
            continue
        if sessions < thresh["min_sessions"]:
            continue

        name = re.sub(r'[^a-z0-9]+', '-', theme.lower()).strip('-')[:30]
        proposals.append({
            "id": f"{name}-rule",
            "type": "rule",
            "impact": _score_impact("rule", occurrences, sessions),
            "confidence": "high" if occurrences >= 5 else "medium",
            "description": f"Add rule: {theme}",
            "evidence_summary": (
                f"Corrected {occurrences} times across {sessions} sessions"
            ),
            "suggested_content": "",  # LLM refines the rule content
            "suggested_path": f".claude/rules/{name}.md",
            "status": "pending",
        })

    return proposals


def _build_from_memory(memory: Dict) -> List[Dict]:
    """Build proposals from memory analysis (promotable notes)."""
    proposals = []
    auto_memory = memory.get("auto_memory", {})
    seen_ids = set()  # type: set

    for note in auto_memory.get("promotable_notes", []):
        # Derive topic from source filename (analyze-memory.py has no "topic" field)
        source = note.get("source", "")
        if source:
            # Extract filename stem: "/path/to/swift_conventions.md" -> "swift_conventions"
            source_stem = Path(source).stem
            topic = re.sub(r'[_]+', ' ', source_stem).strip()
        else:
            topic = "unknown"
        suggestion = note.get("suggested_artifact", "rule")
        content = note.get("content", "")

        name = re.sub(r'[^a-z0-9]+', '-', topic.lower()).strip('-')[:30]

        # Ensure unique IDs by appending index if needed
        base_id = f"promote-{name}"
        proposal_id = base_id
        idx = 2
        while proposal_id in seen_ids:
            proposal_id = f"{base_id}-{idx}"
            idx += 1
        seen_ids.add(proposal_id)

        # Map suggested_artifact to the correct target path
        if suggestion == "reference_doc":
            suggested_path = f".claude/references/{name}.md"
        elif suggestion == "skill":
            suggested_path = f".claude/skills/{name}/SKILL.md"
        elif suggestion == "claude_md_entry":
            suggested_path = "CLAUDE.md"
        else:
            # Default: rule
            suggested_path = f".claude/rules/{name}.md"

        proposals.append({
            "id": proposal_id,
            "type": suggestion,
            "impact": "medium",
            "confidence": "medium",
            "description": f"Promote memory note to {suggestion}: {topic}",
            "evidence_summary": f"Auto-memory note about {topic}",
            "suggested_content": content,
            "suggested_path": suggested_path,
            "status": "pending",
        })

    return proposals


def _build_from_workflows(transcripts: Dict,
                           existing_agents: List[Dict]) -> List[Dict]:
    """Build agent proposals from detected workflow patterns."""
    proposals = []
    candidates = transcripts.get("candidates", {})

    for pattern in candidates.get("workflow_patterns", []):
        text = pattern.get("pattern", "")
        phase_sequence = pattern.get("phase_sequence", [])
        occurrences = pattern.get("occurrences", 0)
        sessions_val = pattern.get("sessions", [])
        sessions = (len(sessions_val) if isinstance(sessions_val, list)
                    else sessions_val)
        evidence = pattern.get("evidence", [])

        if not phase_sequence:
            continue

        # Check thresholds
        thresh = THRESHOLDS["agent"]
        if occurrences < thresh["min_occurrences"]:
            continue
        if sessions < thresh["min_sessions"]:
            continue

        # Derive name for cross-referencing and ID
        name = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:30]
        name = name.rstrip('-')
        if not name:
            name = "workflow-agent"

        # Cross-reference against existing agents
        match = _matches_existing(text, existing_agents)
        if match:
            continue  # Don't propose a duplicate agent

        # Build the proposal
        phase_str = " -> ".join(phase_sequence)
        proposals.append({
            "id": "{}-agent".format(name),
            "type": "agent",
            "impact": _score_impact("agent", occurrences, sessions),
            "confidence": "high" if occurrences >= 8 else "medium",
            "description": "Create {} agent from recurring workflow".format(name),
            "evidence_summary": (
                "'{}' workflow -- {} occurrences across {} sessions".format(
                    phase_str, occurrences, sessions
                )
            ),
            "suggested_content": _generate_agent_content(
                text, phase_sequence, evidence
            ),
            "suggested_path": ".claude/agents/{}.md".format(name),
            "status": "pending",
        })

    return proposals


# ---------------------------------------------------------------------------
# Staleness detection — cross-reference artifacts against session data
# ---------------------------------------------------------------------------

def _artifact_keywords(artifact: Dict) -> List[str]:
    """Extract discriminating keywords from an artifact's content.

    Returns the top content tokens (lowercased, 4+ chars, excluding
    generic terms) that can be used for fuzzy session matching.
    """
    content = artifact.get("content", "")
    name = artifact.get("name", "")
    text = name + " " + content
    # Simple frequency-based keyword extraction (no TF-IDF needed here)
    words = re.findall(r"[a-zA-Z]{4,}", text)
    freq = {}  # type: Dict[str, int]
    generic = {
        "that", "this", "with", "from", "have", "will", "when", "your",
        "must", "should", "never", "always", "claude", "code", "file",
        "files", "project", "rule", "rules", "skill", "agent", "hook",
        "path", "paths", "using", "used", "make", "sure", "also",
    }
    for w in words:
        low = w.lower()
        if low not in generic:
            freq[low] = freq.get(low, 0) + 1
    sorted_terms = sorted(freq, key=lambda t: freq[t], reverse=True)
    return sorted_terms[:7]


def _is_artifact_referenced(
    artifact: Dict,
    session_text_index: Dict[str, List[str]],
    session_tool_paths: Dict[str, List[str]],
) -> int:
    """Count how many sessions reference an artifact.

    An artifact is "referenced" in a session if:
    1. Its name appears in the session's token set, OR
    2. For skills: /name appears as a slash-command token, OR
    3. At least 3 of its top 5 content keywords co-occur in a session, OR
    4. For rules with paths frontmatter: session tool paths match the glob.
    """
    name = artifact.get("name", "").lower()
    artifact_format = artifact.get("format", "")
    keywords = _artifact_keywords(artifact)[:5]
    paths_fm = artifact.get("paths_frontmatter", [])
    keyword_threshold = min(3, max(1, len(keywords)))

    sessions_matched = 0

    for session_id, tokens in session_text_index.items():
        token_set = set(tokens)

        # Check 1: name match
        if name and name in token_set:
            sessions_matched += 1
            continue

        # Check 2: slash-command match for skills
        if artifact_format == "skill" and name:
            # Slash commands appear as /<name> in raw text tokens
            if ("/" + name) in token_set or name.replace("-", "") in token_set:
                sessions_matched += 1
                continue

        # Check 3: content keyword co-occurrence
        if keywords:
            matched_keywords = sum(1 for kw in keywords if kw in token_set)
            if matched_keywords >= keyword_threshold:
                sessions_matched += 1
                continue

        # Check 4: path-based matching for scoped rules
        if paths_fm:
            tool_paths = session_tool_paths.get(session_id, [])
            path_matched = False
            for tp in tool_paths:
                # Use just the relative portion after common prefixes
                basename = tp.rsplit("/", 1)[-1] if "/" in tp else tp
                for pattern in paths_fm:
                    if fnmatch.fnmatch(basename, pattern) or fnmatch.fnmatch(tp, pattern):
                        path_matched = True
                        break
                if path_matched:
                    break
            if path_matched:
                sessions_matched += 1
                continue

    return sessions_matched


def _build_from_staleness(config: Dict, transcripts: Dict) -> List[Dict]:
    """Build proposals for stale artifacts not referenced in recent sessions."""
    sessions_analyzed = transcripts.get("sessions_analyzed", 0)
    min_sessions = STALENESS_THRESHOLDS["min_sessions_for_analysis"]
    stale_threshold = STALENESS_THRESHOLDS["stale_session_count"]

    if sessions_analyzed < min_sessions:
        return []

    session_text_index = transcripts.get("session_text_index", {})
    session_tool_paths = transcripts.get("session_tool_paths", {})

    if not session_text_index:
        return []

    # Cap stale threshold to actual session count
    effective_threshold = min(stale_threshold, sessions_analyzed)

    # Gather all artifacts to check
    artifacts = []  # type: List[Dict]
    for rule in config.get("existing_rules", []):
        artifacts.append(rule)
    for skill in config.get("existing_skills", []):
        artifacts.append(skill)
    for agent in config.get("existing_agents", []):
        artifacts.append(agent)

    proposals = []
    for artifact in artifacts:
        sessions_ref = _is_artifact_referenced(
            artifact, session_text_index, session_tool_paths,
        )
        unreferenced_sessions = sessions_analyzed - sessions_ref

        if unreferenced_sessions < effective_threshold:
            continue

        art_type = artifact.get("format", "unknown")
        art_name = artifact.get("name", "unknown")
        art_path = artifact.get("path", "")

        proposals.append({
            "id": "stale-{}-{}".format(art_type, art_name),
            "type": "stale_artifact",
            "impact": _score_impact("stale_artifact", occurrences=sessions_ref),
            "confidence": "high" if sessions_ref == 0 else "medium",
            "description": (
                "{} '{}' not referenced in last {} sessions — "
                "consider archiving or removing".format(
                    art_type.capitalize(), art_name, sessions_analyzed,
                )
            ),
            "evidence_summary": (
                "{} references in {} sessions analyzed".format(
                    sessions_ref, sessions_analyzed,
                )
            ),
            "suggested_content": "",
            "suggested_path": art_path,
            "status": "pending",
        })

    return proposals


# ---------------------------------------------------------------------------
# Context health summary
# ---------------------------------------------------------------------------

def _build_context_health(config: Dict,
                          stale_proposals: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """Build a compact context health summary from config audit.

    When *stale_proposals* is provided (pre-computed by _build_from_staleness),
    includes stale artifact counts in the health summary without recomputing.
    """
    budget = config.get("context_budget", {})
    tech = config.get("tech_stack", {})
    placement = config.get("placement_issues", [])

    stale = stale_proposals or []

    health = {
        "claude_md_lines": budget.get("claude_md_lines", 0),
        "rules_count": budget.get("rules_count", 0),
        "skills_count": budget.get("skills_count", 0),
        "hooks_count": budget.get("hooks_count", 0),
        "agents_count": budget.get("agents_count", 0),
        "tier1_lines": budget.get("estimated_tier1_lines", 0),
        "over_budget": budget.get("estimated_tier1_lines", 0) > 200,
        "tech_stack": tech.get("detected", []),
        "placement_note_count": len(placement),
        "stale_artifacts_count": len(stale),
        "stale_artifacts": [
            {
                "type": p.get("id", "").split("-")[1] if "-" in p.get("id", "") else "unknown",
                "name": p.get("id", "").split("-", 2)[-1] if "-" in p.get("id", "") else "",
                "evidence": p.get("evidence_summary", ""),
            }
            for p in stale
        ],
    }  # type: Dict[str, Any]

    # Build a one-liner
    parts = []
    lines = health["claude_md_lines"]
    parts.append(f"CLAUDE.md: {lines} lines")
    if health["over_budget"]:
        parts.append("(over 200-line budget)")

    counts = []
    for key, label in [("rules_count", "rules"), ("skills_count", "skills"),
                        ("hooks_count", "hooks"), ("agents_count", "agents")]:
        counts.append(f'{health[key]} {label}')
    parts.append(", ".join(counts))

    # Demotion candidates
    demotions = config.get("demotion_candidates", {})
    demotion_count = (
        len(demotions.get("claude_md_to_rule", []))
        + len(demotions.get("rule_to_reference", []))
        + len(demotions.get("claude_md_verbose_to_reference", []))
    )
    health["demotion_candidates"] = demotion_count

    if health["placement_note_count"] > 0:
        parts.append(
            f'{health["placement_note_count"]} placement suggestions'
        )
    if demotion_count > 0:
        parts.append(f"{demotion_count} demotion candidates")

    if health["stale_artifacts_count"] > 0:
        parts.append(
            f'{health["stale_artifacts_count"]} stale artifacts'
        )

    health["summary"] = ". ".join(parts) + "."
    return health


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def build_proposals(config: Dict, transcripts: Dict, memory: Dict,
                    dismissed: List[Dict],
                    pending: List[Dict],
                    applied_history: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """Build the full proposal list from all analysis sources."""
    existing_skills = config.get("existing_skills", [])
    existing_agents = config.get("existing_agents", [])
    existing_hooks = config.get("existing_hooks", [])

    # Collect dismissed IDs and themes for filtering
    dismissed_ids = {d.get("id", "") for d in dismissed}
    dismissed_themes = set()
    for d in dismissed:
        theme = d.get("description", "")
        if theme:
            dismissed_themes.add(theme.lower())

    # Build proposals from all sources
    all_proposals = []
    all_proposals.extend(_build_from_demotions(config))
    all_proposals.extend(_build_from_gaps(config, existing_hooks))
    all_proposals.extend(
        _build_from_repeated_prompts(transcripts, existing_skills)
    )
    all_proposals.extend(
        _build_from_corrections(transcripts, existing_skills)
    )
    all_proposals.extend(_build_from_memory(memory))
    all_proposals.extend(
        _build_from_workflows(transcripts, existing_agents)
    )
    stale_proposals = _build_from_staleness(config, transcripts)
    all_proposals.extend(stale_proposals)

    # Filter dismissed
    filtered = []
    for p in all_proposals:
        if p["id"] in dismissed_ids:
            continue
        if p.get("description", "").lower() in dismissed_themes:
            continue
        filtered.append(p)

    # Filter low impact
    filtered = [p for p in filtered if p.get("impact") != "low"]

    # Deduplicate against pending proposals
    pending_ids = {pp.get("id", "") for pp in pending
                   if pp.get("status") == "pending"}
    final = [p for p in filtered if p["id"] not in pending_ids]

    # Merge with existing pending proposals
    for pp in pending:
        if pp.get("status") == "pending":
            final.append(pp)

    # Sort: high impact first, then medium
    impact_order = {"high": 0, "medium": 1, "low": 2}
    final.sort(key=lambda p: impact_order.get(p.get("impact", "medium"), 1))

    # Build context health (pass pre-computed stale proposals to avoid recomputing)
    context_health = _build_context_health(config, stale_proposals)

    # Compute effectiveness of previously applied proposals
    effectiveness = _compute_effectiveness(
        applied_history or [], transcripts
    )
    if effectiveness:
        effective_count = sum(
            1 for e in effectiveness if e["status"] == "effective"
        )
        ineffective = [e for e in effectiveness if e["status"] == "ineffective"]
        context_health["effectiveness"] = {
            "tracked_artifacts": len(effectiveness),
            "effective": effective_count,
            "ineffective": len(ineffective),
            "ineffective_details": ineffective,
        }

    return {
        "proposals": final,
        "context_health": context_health,
        "stats": {
            "total_candidates": len(all_proposals),
            "after_dedup": len(filtered),
            "final_count": len(final),
            "sessions_analyzed": transcripts.get("sessions_analyzed", 0),
        },
    }


# ---------------------------------------------------------------------------
# Effectiveness tracking — did applied proposals reduce triggering patterns?
# ---------------------------------------------------------------------------

def _compute_effectiveness(
    applied_history: List[Dict],
    transcripts: Dict,
) -> List[Dict]:
    """Check if patterns that triggered applied proposals still appear.

    For each applied proposal that has tracking data, compare the triggering
    pattern against current analysis results. If the pattern is still present
    at similar or higher frequency, the artifact may not be effective.

    Returns a list of effectiveness entries for context_health.
    """
    if not applied_history:
        return []

    # Current correction themes from transcript analysis
    current_corrections = {}  # type: Dict[str, Dict]
    candidates = transcripts.get("candidates", {})
    for corr in candidates.get("corrections", []):
        theme_id = corr.get("theme_hash", "")
        pattern = corr.get("pattern", corr.get("theme", ""))
        if theme_id:
            current_corrections[theme_id] = corr
        if pattern:
            # Also index by pattern text for fuzzy matching
            current_corrections[pattern.lower()] = corr

    # Current post-action patterns
    current_post_actions = {}  # type: Dict[str, Dict]
    for pa in candidates.get("post_actions", []):
        cmd = pa.get("command", "")
        if cmd:
            current_post_actions[cmd.lower()] = pa

    effectiveness = []  # type: List[Dict]

    for entry in applied_history:
        tracking = entry.get("tracking")
        if not tracking:
            continue

        pid = entry.get("id", "unknown")
        applied_at = entry.get("applied_at", "")
        source = tracking.get("source", "")
        pattern_id = tracking.get("pattern_id", "")
        desc = entry.get("description", "")

        # Check if the triggering pattern is still present
        still_present = False
        current_frequency = 0

        if source == "correction":
            # Check if a matching correction theme still appears
            match = current_corrections.get(pattern_id)
            if not match:
                # Try fuzzy: check if description or pattern words overlap
                # Use both description and pattern_id as search terms
                search_texts = [t for t in [desc.lower(), pattern_id.lower()] if t]
                for search in search_texts:
                    for key, corr in current_corrections.items():
                        if isinstance(key, str) and _similarity(search, key) > 0.25:
                            match = corr
                            break
                    if match:
                        break
            if match:
                still_present = True
                current_frequency = match.get("total_occurrences",
                                               match.get("occurrences", 0))

        elif source == "post_action":
            # Check if same command pattern still shows up
            # Match by description keywords or pattern_id words against commands
            search = (desc + " " + pattern_id).lower()
            search_tokens = _tokenize(search)
            for cmd, pa in current_post_actions.items():
                cmd_tokens = _tokenize(cmd)
                if search_tokens and cmd_tokens:
                    overlap = len(search_tokens & cmd_tokens)
                    if overlap >= 1:
                        still_present = True
                        current_frequency = pa.get("count", 0)
                        break

        status = "effective" if not still_present else "ineffective"

        effectiveness.append({
            "id": pid,
            "description": desc,
            "applied_at": applied_at,
            "status": status,
            "still_present": still_present,
            "current_frequency": current_frequency,
        })

    return effectiveness


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_json_file(path: str) -> Dict:
    """Load JSON from a file path, returning empty dict on failure."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _load_json_list(path: str) -> List[Dict]:
    """Load a JSON array from a file path, returning empty list on failure."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except (OSError, json.JSONDecodeError):
        return []


def main():
    parser = argparse.ArgumentParser(
        description="Build proposals from Forge analysis results"
    )
    parser.add_argument("--config", type=str, default=None,
                        help="Path to config audit JSON")
    parser.add_argument("--transcripts", type=str, default=None,
                        help="Path to transcript analysis JSON")
    parser.add_argument("--memory", type=str, default=None,
                        help="Path to memory analysis JSON")
    parser.add_argument("--dismissed", type=str, default=None,
                        help="Path to dismissed.json")
    parser.add_argument("--pending", type=str, default=None,
                        help="Path to pending.json")
    parser.add_argument("--combined", type=str, default=None,
                        help="Path to combined JSON (all three analyses)")
    parser.add_argument("--applied", type=str, default=None,
                        help="Path to applied history JSON")
    args = parser.parse_args()

    if args.combined:
        combined = _load_json_file(args.combined)
        config = combined.get("config", {})
        transcripts = combined.get("transcripts", {})
        memory = combined.get("memory", {})
    else:
        config = _load_json_file(args.config) if args.config else {}
        transcripts = (_load_json_file(args.transcripts)
                       if args.transcripts else {})
        memory = _load_json_file(args.memory) if args.memory else {}

    dismissed = (_load_json_list(args.dismissed)
                 if args.dismissed else [])
    pending = _load_json_list(args.pending) if args.pending else []
    applied = (_load_json_list(args.applied)
               if args.applied else [])

    result = build_proposals(config, transcripts, memory, dismissed, pending,
                             applied_history=applied)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

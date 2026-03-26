#!/usr/bin/env python3
"""Analyze auto-memory and CLAUDE.local.md for promotion candidates.

Scans auto-memory files from ~/.claude/projects/<project>/memory/ and
CLAUDE.local.md to classify entries and suggest which Claude Code artifact
type each should be promoted to.

Usage:
    python3 analyze-memory.py [--project-root /path/to/project]
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Classification patterns
# ---------------------------------------------------------------------------

PREFERENCE_PATTERNS = [
    re.compile(r"\b(uses?|prefers?|always|never)\b", re.IGNORECASE),
    re.compile(r"\b(not|instead of|rather than)\b.*\b(npm|yarn|pnpm|bun)\b", re.IGNORECASE),
    re.compile(r"\b(typescript|javascript|python|rust|go)\b", re.IGNORECASE),
]

CONVENTION_PATTERNS = [
    re.compile(r"\b(tests?\s+go\s+in|convention|pattern|structure)\b", re.IGNORECASE),
    re.compile(r"\b(follows?|naming|style)\b", re.IGNORECASE),
    re.compile(r"(__|src/|lib/|app/|components/|routes/)", re.IGNORECASE),
]

WORKFLOW_PATTERNS = [
    re.compile(r"\b(process|steps?|workflow|deploy|release)\b", re.IGNORECASE),
    re.compile(r"\b(first|then|next|finally|after)\b.*\b(run|build|test)\b", re.IGNORECASE),
    re.compile(r"\d+\.\s+", re.IGNORECASE),  # numbered lists
]

COMMAND_PATTERNS = [
    re.compile(r"`[^`]+`"),  # backtick commands
    re.compile(r"\b(run with|build with|start with|execute)\b", re.IGNORECASE),
    re.compile(r"\b(pnpm|npm|yarn|cargo|go|python|pip)\s+\w+", re.IGNORECASE),
]

DEBUGGING_PATTERNS = [
    re.compile(r"\b(usually means|if you see|troubleshoot|error|issue)\b", re.IGNORECASE),
    re.compile(r"\b(fix|resolve|workaround|solution)\b", re.IGNORECASE),
    re.compile(r"\b(when .+ fails?|when .+ breaks?)\b", re.IGNORECASE),
]

# Domain-specific indicators (for CLAUDE.local.md entries)
DOMAIN_INDICATORS = [
    re.compile(r"\.(tsx|jsx|ts|js|py|rs|go|vue|svelte)\b"),
    re.compile(r"\b(React|Vue|Angular|Django|Flask|Express|Next\.js)\b", re.IGNORECASE),
    re.compile(r"\b(src/|tests?/|api/|components/|pages/)\b"),
]

# Artifact type mapping
CLASSIFICATION_TO_ARTIFACT = {
    "preference": "claude_md_entry",
    "convention": "rule",
    "workflow": "skill",
    "command": "claude_md_entry",
    "debugging": "reference_doc",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_lines(path: Path) -> List[str]:
    """Return lines from file, empty list if unreadable."""
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def _read_text(path: Path) -> str:
    """Return file text, empty string if unreadable."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return ""


def find_memory_dir(project_root: Path) -> Optional[Path]:
    """Find the auto-memory directory for the project."""
    claude_projects = Path.home() / ".claude" / "projects"
    if not claude_projects.is_dir():
        return None

    project_str = str(project_root)

    # Strategy 1: Exact normalized path match
    normalized = project_str.replace("/", "-").replace("\\", "-").lstrip("-")
    candidate = claude_projects / normalized / "memory"
    if candidate.is_dir():
        return candidate

    # Strategy 2: Partial path match
    project_parts = project_str.strip("/").split("/")
    for d in claude_projects.iterdir():
        if not d.is_dir():
            continue
        matches = sum(1 for p in project_parts[-3:] if p in d.name)
        if matches >= 2:
            mem = d / "memory"
            if mem.is_dir():
                return mem

    # Strategy 3: Check all project dirs for memory subdirectory
    for d in sorted(claude_projects.iterdir(), key=lambda x: x.name):
        if not d.is_dir():
            continue
        mem = d / "memory"
        if mem.is_dir():
            # Check if this memory dir seems to be for our project
            memory_md = mem / "MEMORY.md"
            if memory_md.is_file():
                content = _read_text(memory_md).lower()
                # Check if project name appears in memory content
                project_name = project_parts[-1].lower() if project_parts else ""
                if project_name and project_name in content:
                    return mem

    return None


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_entry(text: str) -> str:
    """Classify a memory entry into one of: preference, convention, workflow, command, debugging."""
    text_stripped = text.strip()
    if not text_stripped:
        return "preference"  # default

    scores = {
        "preference": 0,
        "convention": 0,
        "workflow": 0,
        "command": 0,
        "debugging": 0,
    }

    for pattern in PREFERENCE_PATTERNS:
        if pattern.search(text_stripped):
            scores["preference"] += 1

    for pattern in CONVENTION_PATTERNS:
        if pattern.search(text_stripped):
            scores["convention"] += 1

    for pattern in WORKFLOW_PATTERNS:
        if pattern.search(text_stripped):
            scores["workflow"] += 1

    for pattern in COMMAND_PATTERNS:
        if pattern.search(text_stripped):
            scores["command"] += 1

    for pattern in DEBUGGING_PATTERNS:
        if pattern.search(text_stripped):
            scores["debugging"] += 1

    # Return highest-scoring classification
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "preference"  # default when nothing matches
    return best


def is_domain_specific(text: str) -> bool:
    """Check if text is domain-specific (mentions file types, frameworks, dirs)."""
    return any(p.search(text) for p in DOMAIN_INDICATORS)


def generate_suggestion(classification: str, text: str) -> str:
    """Generate a human-readable suggestion for what to do with this entry."""
    suggestions = {
        "preference": f"Promote to CLAUDE.md — persistent preference that should always be in context",
        "convention": f"Create a scoped rule in .claude/rules/ with path frontmatter",
        "workflow": f"Consider creating a skill in .claude/skills/ for this workflow",
        "command": f"Add to CLAUDE.md as a build/run command reference",
        "debugging": f"Extract to a reference doc in .claude/references/ for on-demand access",
    }
    return suggestions.get(classification, "Review and classify manually")


# ---------------------------------------------------------------------------
# Memory parsing
# ---------------------------------------------------------------------------

def parse_memory_entries(text: str) -> list:
    """Parse a memory markdown file into individual entries.

    Handles both MEMORY.md (index with links) and topic files (content).
    Splits on markdown headers, list items, or blank-line-separated paragraphs.
    """
    entries = []
    current = []

    for line in text.splitlines():
        stripped = line.strip()

        # Skip empty lines between entries
        if not stripped:
            if current:
                entries.append("\n".join(current).strip())
                current = []
            continue

        # Skip frontmatter delimiters
        if stripped == "---":
            if current:
                entries.append("\n".join(current).strip())
                current = []
            continue

        # New header = new entry
        if stripped.startswith("#"):
            if current:
                entries.append("\n".join(current).strip())
                current = []
            current.append(stripped)
            continue

        # List items can be individual entries
        if stripped.startswith("- ") or stripped.startswith("* "):
            if current and (current[-1].startswith("- ") or current[-1].startswith("* ")):
                entries.append("\n".join(current).strip())
                current = [stripped]
            else:
                current.append(stripped)
            continue

        current.append(stripped)

    if current:
        entries.append("\n".join(current).strip())

    # Filter out very short or empty entries
    return [e for e in entries if len(e.strip()) > 5]


# ---------------------------------------------------------------------------
# Cross-reference check
# ---------------------------------------------------------------------------

def check_redundancy(entry_text: str, project_root: Path) -> bool:
    """Check if entry content is already covered by CLAUDE.md or rules."""
    entry_lower = entry_text.lower().strip()
    if len(entry_lower) < 10:
        return False

    # Check CLAUDE.md
    for candidate in [project_root / "CLAUDE.md", project_root / ".claude" / "CLAUDE.md"]:
        if candidate.is_file():
            content = _read_text(candidate).lower()
            # Simple substring check — if the key terms appear
            words = [w for w in entry_lower.split() if len(w) > 3]
            if words:
                match_count = sum(1 for w in words if w in content)
                if match_count / len(words) > 0.6:
                    return True
            break

    # Check rules
    rules_dir = project_root / ".claude" / "rules"
    if rules_dir.is_dir():
        for rule_file in rules_dir.rglob("*.md"):
            content = _read_text(rule_file).lower()
            words = [w for w in entry_lower.split() if len(w) > 3]
            if words:
                match_count = sum(1 for w in words if w in content)
                if match_count / len(words) > 0.6:
                    return True

    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analyze auto-memory and CLAUDE.local.md for promotion candidates."
    )
    parser.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="Project root path (defaults to cwd).",
    )
    args = parser.parse_args()

    root = (
        Path(args.project_root).resolve()
        if args.project_root
        else Path.cwd().resolve()
    )

    output = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "auto_memory": {
            "exists": False,
            "memory_md_lines": 0,
            "topic_files": [],
            "promotable_notes": [],
        },
        "claude_local_md": {
            "exists": False,
            "lines": 0,
            "domain_specific_entries": [],
            "redundant_entries": [],
        },
    }

    # --- Auto-memory ---
    memory_dir = find_memory_dir(root)
    if memory_dir and memory_dir.is_dir():
        output["auto_memory"]["exists"] = True

        # Read MEMORY.md
        memory_md = memory_dir / "MEMORY.md"
        if memory_md.is_file():
            lines = _read_lines(memory_md)
            output["auto_memory"]["memory_md_lines"] = len(lines)

        # Find topic files
        topic_files = []
        for f in sorted(memory_dir.iterdir()):
            if f.is_file() and f.suffix == ".md" and f.name != "MEMORY.md":
                topic_files.append(f.name)
        output["auto_memory"]["topic_files"] = topic_files

        # Parse and classify all memory entries
        all_memory_files = [memory_md] + [memory_dir / t for t in topic_files]
        for mem_file in all_memory_files:
            if not mem_file.is_file():
                continue
            text = _read_text(mem_file)
            entries = parse_memory_entries(text)

            for entry in entries:
                # Skip header-only entries or very short ones
                if len(entry.strip()) < 10:
                    continue

                classification = classify_entry(entry)
                is_redundant = check_redundancy(entry, root)

                if is_redundant:
                    continue  # Skip redundant entries

                artifact = CLASSIFICATION_TO_ARTIFACT.get(classification, "claude_md_entry")
                suggestion = generate_suggestion(classification, entry)

                output["auto_memory"]["promotable_notes"].append({
                    "source": str(mem_file),
                    "content": entry[:300],  # truncate long entries
                    "classification": classification,
                    "suggestion": suggestion,
                    "suggested_artifact": artifact,
                })

    # --- CLAUDE.local.md ---
    claude_local_path = None
    for candidate in [root / "CLAUDE.local.md", root / ".claude" / "CLAUDE.local.md"]:
        if candidate.is_file():
            claude_local_path = candidate
            break

    if claude_local_path:
        output["claude_local_md"]["exists"] = True
        lines = _read_lines(claude_local_path)
        output["claude_local_md"]["lines"] = len(lines)

        text = _read_text(claude_local_path)
        entries = parse_memory_entries(text)

        for entry in entries:
            if len(entry.strip()) < 10:
                continue

            # Check if domain-specific
            if is_domain_specific(entry):
                output["claude_local_md"]["domain_specific_entries"].append({
                    "content": entry[:300],
                    "suggestion": (
                        "This entry mentions specific file types or frameworks. "
                        "Consider moving to a scoped rule in .claude/rules/ with "
                        "path frontmatter."
                    ),
                })

            # Check if redundant with CLAUDE.md
            if check_redundancy(entry, root):
                output["claude_local_md"]["redundant_entries"].append({
                    "content": entry[:300],
                    "suggestion": (
                        "This entry appears to duplicate content already in CLAUDE.md. "
                        "Consider removing it from CLAUDE.local.md."
                    ),
                })

    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

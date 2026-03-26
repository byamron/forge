#!/usr/bin/env python3
"""Analyze Claude Code session transcripts for patterns.

Scans session transcript JSONL files from ~/.claude/projects/ to detect:
- Repeated user corrections (same feedback across sessions)
- Post-action patterns (user always runs a command after Claude edits)
- Repeated opening prompts (sessions starting with similar messages)

Usage:
    python3 analyze-transcripts.py [--project-root /path] [--min-occurrences 3] [--max-sessions 20]

Transcript JSONL format (observed structure, not a stable API):
    Each line is a JSON object. Entry types observed:
    - "type": "user" | "assistant" | "queue-operation"
    - "message": {"role": "user"|"assistant", "content": str|list}
    - "uuid": unique message identifier
    - "parentUuid": preceding message UUID (conversation threading)
    - "timestamp": ISO8601 timestamp (e.g., "2026-03-20T14:22:00.123Z")
    - "sessionId": session identifier
    - "isSidechain": boolean (subagent turns)

    User content: either a plain string or list with tool_result blocks.
    System-injected messages start with <system_instruction> or <local-command-caveat>.
    Assistant content: list of blocks — "text", "tool_use", "thinking".
    Tool use blocks: {"type": "tool_use", "name": "Edit", "input": {...}}
"""

import argparse
import datetime
import difflib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Correction detection keywords/phrases
# ---------------------------------------------------------------------------

CORRECTION_PATTERNS = [
    re.compile(r"\bno[,.]?\s", re.IGNORECASE),
    re.compile(r"\bnot that\b", re.IGNORECASE),
    re.compile(r"\bI said\b", re.IGNORECASE),
    re.compile(r"\balways use\b", re.IGNORECASE),
    re.compile(r"\bnever use\b", re.IGNORECASE),
    re.compile(r"\bdon'?t use\b", re.IGNORECASE),
    re.compile(r"\bswitch to\b", re.IGNORECASE),
    re.compile(r"\bI told you\b", re.IGNORECASE),
    re.compile(r"\bactually[,.]", re.IGNORECASE),
    re.compile(r"\bthat'?s not right\b", re.IGNORECASE),
    re.compile(r"\bwe use .+ not\b", re.IGNORECASE),
    re.compile(r"\blet'?s do it this way\b", re.IGNORECASE),
    re.compile(r"\binstead[,.]?\s", re.IGNORECASE),
    re.compile(r"\bwrong\b", re.IGNORECASE),
    re.compile(r"\bshould be\b", re.IGNORECASE),
    re.compile(r"\buse .+ instead\b", re.IGNORECASE),
]

# Post-action commands to watch for
POST_ACTION_COMMANDS = [
    re.compile(r"\bnpx\s+prettier\b", re.IGNORECASE),
    re.compile(r"\bnpm\s+run\s+lint\b", re.IGNORECASE),
    re.compile(r"\bnpm\s+test\b", re.IGNORECASE),
    re.compile(r"\bnpx\s+eslint\b", re.IGNORECASE),
    re.compile(r"\bcargo\s+fmt\b", re.IGNORECASE),
    re.compile(r"\bcargo\s+test\b", re.IGNORECASE),
    re.compile(r"\bblack\s", re.IGNORECASE),
    re.compile(r"\bruff\b", re.IGNORECASE),
    re.compile(r"\bgo\s+fmt\b", re.IGNORECASE),
    re.compile(r"\bgo\s+test\b", re.IGNORECASE),
    re.compile(r"\bpnpm\s+(test|lint|format)\b", re.IGNORECASE),
    re.compile(r"\byarn\s+(test|lint|format)\b", re.IGNORECASE),
    re.compile(r"\bpytest\b", re.IGNORECASE),
    re.compile(r"\bmypy\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Project directory mapping
# ---------------------------------------------------------------------------

def find_project_sessions_dir(project_root: Path) -> Optional[Path]:
    """Find the ~/.claude/projects/ directory for the given project root.

    Claude Code stores sessions under ~/.claude/projects/<hash>/ where <hash>
    is derived from the project path. We try multiple strategies to find it.
    """
    claude_projects = Path.home() / ".claude" / "projects"
    if not claude_projects.is_dir():
        return None

    project_str = str(project_root)

    # Strategy 1: Look for directory names that encode the project path
    # Claude Code uses a path-based hash like "-Users-name-project"
    normalized = project_str.replace("/", "-").replace("\\", "-").lstrip("-")
    for d in claude_projects.iterdir():
        if not d.is_dir():
            continue
        if d.name == normalized:
            return d

    # Strategy 2: Partial match — directory name contains key segments
    project_parts = project_str.strip("/").split("/")
    for d in claude_projects.iterdir():
        if not d.is_dir():
            continue
        # Check if the last 2-3 path components appear in the dir name
        matches = sum(1 for p in project_parts[-3:] if p in d.name)
        if matches >= 2:
            return d

    # Strategy 3: Look for any directory with .jsonl files
    # (fallback — returns the most recently modified one)
    best = None
    best_time = 0
    for d in claude_projects.iterdir():
        if not d.is_dir():
            continue
        jsonl_files = list(d.glob("*.jsonl"))
        if jsonl_files:
            mtime = max(f.stat().st_mtime for f in jsonl_files)
            if mtime > best_time:
                best_time = mtime
                best = d

    return best


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------

def _extract_text_content(content) -> str:
    """Extract plain text from a message content field."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return ""


def _extract_tool_uses(content) -> list:
    """Extract tool use entries from message content."""
    tools = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                tools.append({
                    "name": item.get("name", ""),
                    "input": item.get("input", {}),
                })
    return tools


def parse_transcript(filepath: Path) -> list:
    """Parse a JSONL transcript file into a list of structured messages."""
    messages = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = entry.get("type", "")

                # Skip non-message entry types (e.g., queue-operation)
                if msg_type not in ("user", "assistant"):
                    continue

                # Skip sidechain/subagent entries — these are internal agent
                # conversations, not user-facing interaction
                if entry.get("isSidechain", False):
                    continue

                message = entry.get("message", {})
                role = message.get("role", "") if isinstance(message, dict) else ""
                content = message.get("content", "") if isinstance(message, dict) else ""
                timestamp = entry.get("timestamp", "")

                text = _extract_text_content(content)
                tool_uses = _extract_tool_uses(content)

                # Skip system-injected messages (not real user input)
                if role == "user" and text:
                    if text.lstrip().startswith(("<system", "<local-command")):
                        continue

                messages.append({
                    "type": msg_type,
                    "role": role,
                    "text": text,
                    "tool_uses": tool_uses,
                    "timestamp": timestamp,
                    "raw_type": msg_type,
                })
    except (OSError, UnicodeDecodeError):
        pass

    return messages


def load_sessions(sessions_dir: Path, max_sessions: int) -> dict:
    """Load up to max_sessions most recent session transcripts.

    Returns {session_id: [messages]} sorted by recency.
    """
    jsonl_files = sorted(
        sessions_dir.glob("*.jsonl"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )[:max_sessions]

    sessions = {}
    for filepath in jsonl_files:
        session_id = filepath.stem
        messages = parse_transcript(filepath)
        if messages:
            sessions[session_id] = messages

    return sessions


# ---------------------------------------------------------------------------
# Correction detection
# ---------------------------------------------------------------------------

def is_correction(text: str) -> bool:
    """Check if text contains correction-adjacent phrases."""
    # Skip very short messages
    if len(text.strip()) < 10:
        return False
    # Skip messages that are clearly not corrections
    if text.strip().startswith("/"):  # slash commands
        return False

    return any(p.search(text) for p in CORRECTION_PATTERNS)


def find_corrections(sessions: dict) -> list:
    """Find repeated corrections across sessions."""
    corrections = []  # (session_id, timestamp, user_text, prev_assistant_text)

    for session_id, messages in sessions.items():
        prev_assistant = ""
        for msg in messages:
            if msg["role"] == "assistant" and msg["text"]:
                prev_assistant = msg["text"][:500]  # truncate for efficiency
            elif msg["role"] == "user" and msg["text"]:
                if is_correction(msg["text"]):
                    corrections.append({
                        "session": session_id,
                        "timestamp": msg["timestamp"],
                        "user_message": msg["text"][:500],
                        "preceding_response": prev_assistant[:200],
                    })

    if len(corrections) < 2:
        return []

    # Group similar corrections using SequenceMatcher
    groups = []
    used = set()

    for i, c1 in enumerate(corrections):
        if i in used:
            continue
        group = [c1]
        used.add(i)
        for j, c2 in enumerate(corrections):
            if j in used or j <= i:
                continue
            ratio = difflib.SequenceMatcher(
                None,
                c1["user_message"].lower(),
                c2["user_message"].lower(),
            ).ratio()
            if ratio > 0.6:
                group.append(c2)
                used.add(j)

        if len(group) >= 2:
            group_sessions = list(set(c["session"] for c in group))
            groups.append({
                "pattern": f"Repeated correction ({len(group)} occurrences)",
                "occurrences": len(group),
                "sessions": group_sessions,
                "evidence": group[:5],  # limit evidence items
                "suggested_artifact": "claude_md_entry",
                "suggested_content": "",  # Phase B will draft this
                "confidence": "high" if len(group) >= 4 and len(group_sessions) >= 3 else "medium",
            })

    return groups


# ---------------------------------------------------------------------------
# Post-action detection
# ---------------------------------------------------------------------------

def find_post_actions(sessions: dict) -> list:
    """Find patterns where user runs specific commands after Claude edits."""
    action_counts = defaultdict(lambda: {"count": 0, "sessions": set(), "evidence": []})

    for session_id, messages in sessions.items():
        prev_was_edit = False
        prev_tool = ""

        for msg in messages:
            # Check if assistant used Write/Edit tool
            if msg["role"] == "assistant" and msg["tool_uses"]:
                for tool in msg["tool_uses"]:
                    if tool["name"] in ("Write", "Edit", "write", "edit"):
                        prev_was_edit = True
                        prev_tool = tool["name"]
                        break

            # Check if user's next message contains a known command
            elif msg["role"] == "user" and prev_was_edit and msg["text"]:
                text = msg["text"].strip()
                for pattern in POST_ACTION_COMMANDS:
                    match = pattern.search(text)
                    if match:
                        cmd = match.group(0).lower().strip()
                        entry = action_counts[cmd]
                        entry["count"] += 1
                        entry["sessions"].add(session_id)
                        if len(entry["evidence"]) < 5:
                            entry["evidence"].append({
                                "session": session_id,
                                "timestamp": msg["timestamp"],
                                "user_message": text[:200],
                                "after_tool": prev_tool,
                            })
                        break
                prev_was_edit = False
            elif msg["role"] == "user":
                # User message that didn't match a post-action command — reset
                prev_was_edit = False
            # Entries with empty role (tool_results, summaries) or assistant
            # messages without tool_uses don't reset the flag — they're
            # intermediate entries in the same conversational turn

    results = []
    for cmd, data in action_counts.items():
        if data["count"] >= 3 and len(data["sessions"]) >= 2:
            results.append({
                "pattern": f"User runs '{cmd}' after Claude edits",
                "occurrences": data["count"],
                "sessions": list(data["sessions"]),
                "evidence": data["evidence"],
                "suggested_artifact": "hook",
                "suggested_content": "",  # Phase B will draft this
                "confidence": "high" if data["count"] >= 5 and len(data["sessions"]) >= 3 else "medium",
            })

    return results


# ---------------------------------------------------------------------------
# Repeated prompt detection
# ---------------------------------------------------------------------------

def find_repeated_prompts(sessions: dict) -> list:
    """Find sessions that start with very similar opening messages."""
    openers = []  # (session_id, first_user_message)

    for session_id, messages in sessions.items():
        for msg in messages:
            if msg["role"] == "user" and msg["text"].strip():
                openers.append((session_id, msg["text"][:300]))
                break

    if len(openers) < 3:
        return []

    # Group similar openers
    groups = []
    used = set()

    for i, (sid1, text1) in enumerate(openers):
        if i in used:
            continue
        group = [(sid1, text1)]
        used.add(i)
        for j, (sid2, text2) in enumerate(openers):
            if j in used or j <= i:
                continue
            ratio = difflib.SequenceMatcher(
                None, text1.lower(), text2.lower()
            ).ratio()
            if ratio > 0.5:
                group.append((sid2, text2))
                used.add(j)

        if len(group) >= 3:
            groups.append({
                "pattern": f"Similar opening prompt in {len(group)} sessions",
                "occurrences": len(group),
                "sessions": [s for s, _ in group],
                "evidence": [
                    {"session": s, "user_message": t} for s, t in group[:5]
                ],
                "suggested_artifact": "skill",
                "suggested_content": "",
                "confidence": "high" if len(group) >= 4 else "medium",
            })

    return groups


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analyze Claude Code session transcripts for patterns."
    )
    parser.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="Project root path (defaults to cwd).",
    )
    parser.add_argument(
        "--min-occurrences",
        type=int,
        default=3,
        help="Minimum occurrences to flag a pattern (default: 3).",
    )
    parser.add_argument(
        "--max-sessions",
        type=int,
        default=20,
        help="Maximum sessions to analyze (default: 20).",
    )
    args = parser.parse_args()

    root = (
        Path(args.project_root).resolve()
        if args.project_root
        else Path.cwd().resolve()
    )

    # Find session directory
    sessions_dir = find_project_sessions_dir(root)

    output = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "sessions_analyzed": 0,
        "session_date_range": "",
        "candidates": {
            "corrections": [],
            "post_actions": [],
            "repeated_prompts": [],
            "repeated_sequences": [],
        },
    }

    if sessions_dir is None:
        json.dump(output, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    # Load sessions
    sessions = load_sessions(sessions_dir, args.max_sessions)
    output["sessions_analyzed"] = len(sessions)

    if not sessions:
        json.dump(output, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    # Compute date range from timestamps
    all_timestamps = []
    for msgs in sessions.values():
        for msg in msgs:
            ts = msg.get("timestamp", "")
            if ts:
                all_timestamps.append(ts[:10])  # date portion
    if all_timestamps:
        all_timestamps.sort()
        output["session_date_range"] = f"{all_timestamps[0]} to {all_timestamps[-1]}"

    # Run detectors
    output["candidates"]["corrections"] = find_corrections(sessions)
    output["candidates"]["post_actions"] = find_post_actions(sessions)
    output["candidates"]["repeated_prompts"] = find_repeated_prompts(sessions)

    # Filter by min occurrences
    min_occ = args.min_occurrences
    for key in ["corrections", "post_actions", "repeated_prompts"]:
        output["candidates"][key] = [
            c for c in output["candidates"][key]
            if c["occurrences"] >= min_occ
        ]

    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

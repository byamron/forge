#!/usr/bin/env python3
"""Check for pending Forge proposals and output a nudge system message.

Used by the Stop hook to provide ambient nudges between tasks.
Outputs JSON with a systemMessage field if there are pending proposals
and the user hasn't been nudged this session. Otherwise outputs nothing.

Constraints:
- Once per session maximum (tracked via flag file)
- Only nudges for high-confidence proposals
- Completes in <1 second
- Outputs valid JSON or nothing

Usage:
    python3 check-pending.py [--project-root /path]
"""

import json
import os
import sys
from pathlib import Path


def find_project_root() -> Path:
    """Walk up from cwd looking for .git or .claude to find project root."""
    current = Path.cwd().resolve()
    while current != current.parent:
        if (current / ".git").exists() or (current / ".claude").exists():
            return current
        current = current.parent
    return Path.cwd().resolve()


def main():
    root = find_project_root()
    forge_dir = root / ".claude" / "forge"
    pending_path = forge_dir / "proposals" / "pending.json"
    nudge_flag = forge_dir / ".nudged-this-session"

    # Already nudged this session — stay silent
    if nudge_flag.exists():
        return

    # No pending proposals — stay silent
    if not pending_path.exists():
        return

    try:
        data = json.loads(pending_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    # Find high-confidence pending proposals
    if isinstance(data, list):
        proposals = data
    elif isinstance(data, dict):
        proposals = data.get("proposals", [])
    else:
        return

    pending = [
        p for p in proposals
        if isinstance(p, dict)
        and p.get("status") == "pending"
        and p.get("confidence") == "high"
    ]

    if not pending:
        return

    # Pick the single most impactful proposal for the nudge
    best = pending[0]
    description = best.get("description", "an improvement to your configuration")
    artifact_type = best.get("type", "artifact").replace("_", " ")
    count = len(pending)

    if count == 1:
        nudge = (
            f"Forge has a suggestion: {description}. "
            f"Run `/forge:optimize` to review it, or just keep going."
        )
    else:
        nudge = (
            f"Forge has {count} suggestions, including: {description}. "
            f"Run `/forge:optimize` when you'd like to review them."
        )

    # Output the system message
    output = {"systemMessage": nudge}
    json.dump(output, sys.stdout)
    sys.stdout.write("\n")

    # Set the nudge flag so we don't nudge again this session
    try:
        forge_dir.mkdir(parents=True, exist_ok=True)
        nudge_flag.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass


if __name__ == "__main__":
    main()

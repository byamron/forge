#!/usr/bin/env python3
"""Check if Forge should nudge the user about pending analysis.

Used by the session-start rule in CLAUDE.md to provide ambient nudges.
Checks settings, counts unanalyzed sessions, and outputs a one-line
nudge if the threshold is met. Otherwise outputs nothing.

Nudge levels (configured via /forge:settings):
- quiet:    Never nudge. Output nothing.
- balanced: Nudge when pending proposals exist, or after 5+ unanalyzed sessions (default).
- eager:    Nudge when pending proposals exist, or after 2+ unanalyzed sessions.

Usage:
    python3 check-pending.py [--project-root /path]
"""

import json
import sys
from pathlib import Path

LEVEL_THRESHOLDS = {
    "quiet": None,
    "balanced": 5,
    "eager": 2,
}


def find_project_root() -> Path:
    current = Path.cwd().resolve()
    while current != current.parent:
        if (current / ".git").exists() or (current / ".claude").exists():
            return current
        current = current.parent
    return Path.cwd().resolve()


def load_nudge_level(forge_dir: Path) -> str:
    settings_path = forge_dir / "settings.json"
    if settings_path.is_file():
        try:
            with open(settings_path, "r") as f:
                data = json.load(f)
            level = data.get("nudge_level", "balanced")
            if level in LEVEL_THRESHOLDS:
                return level
        except (json.JSONDecodeError, OSError):
            pass
    return "balanced"


def count_unanalyzed_sessions(forge_dir: Path) -> int:
    log_path = forge_dir / "unanalyzed-sessions.log"
    if not log_path.is_file():
        return 0
    try:
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        return len(lines)
    except OSError:
        return 0


def count_pending_proposals(forge_dir: Path) -> int:
    pending_path = forge_dir / "proposals" / "pending.json"
    if not pending_path.is_file():
        return 0
    try:
        data = json.loads(pending_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            proposals = data
        elif isinstance(data, dict):
            proposals = data.get("proposals", [])
        else:
            return 0
        return sum(
            1 for p in proposals
            if isinstance(p, dict) and p.get("status") == "pending"
        )
    except (OSError, json.JSONDecodeError):
        return 0


def main():
    root = find_project_root()
    forge_dir = root / ".claude" / "forge"

    # Check nudge level
    level = load_nudge_level(forge_dir)
    threshold = LEVEL_THRESHOLDS.get(level)

    # Quiet mode — never nudge
    if threshold is None:
        return

    # Check for pending proposals first (always worth mentioning)
    pending_count = count_pending_proposals(forge_dir)

    # Check unanalyzed session count against threshold
    unanalyzed = count_unanalyzed_sessions(forge_dir)

    # Nothing to say
    if pending_count == 0 and unanalyzed < threshold:
        return

    # Build nudge message
    parts = []
    if pending_count > 0:
        parts.append(
            f"{pending_count} pending proposal{'s' if pending_count != 1 else ''} "
            f"to review"
        )
    if unanalyzed >= threshold:
        parts.append(
            f"{unanalyzed} session{'s' if unanalyzed != 1 else ''} since last analysis"
        )

    nudge = "Forge: " + ", ".join(parts) + ". Run `/forge` to review."
    output = {"systemMessage": nudge}
    json.dump(output, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

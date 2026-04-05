#!/usr/bin/env python3
"""Check if Forge should nudge the user about pending proposals.

Used by the SessionStart hook to provide ambient presence. Outputs a JSON
object with a systemMessage field when there is something worth telling the
user. Otherwise outputs nothing.

The systemMessage is displayed directly in the Claude Code terminal UI as a
startup notification line (e.g. "SessionStart/startup says: forge: ...").
Messages should be concise and user-facing.

Behavior depends on two settings:
- nudge_level (quiet/balanced/eager): quiet suppresses the health signal.
- proactive_proposals (true/false, default true): when true and pending
  proposals exist, shows a proposal count at session start.

Usage:
    python3 check-pending.py [--project-root /path]
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from project_identity import (
    find_project_root,
    get_user_data_dir,
    resolve_user_file,
)

NUDGE_LEVELS = {"quiet", "balanced", "eager"}


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

def load_settings(project_root: Path) -> Dict[str, Any]:
    """Load all Forge settings, returning defaults for missing keys."""
    defaults = {
        "nudge_level": "balanced",
        "proactive_proposals": True,
    }
    settings_path = resolve_user_file(project_root, "settings.json")
    if settings_path.is_file():
        try:
            with open(settings_path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in defaults:
                    if k in data:
                        defaults[k] = data[k]
        except (json.JSONDecodeError, OSError):
            pass
    # Validate nudge_level
    if defaults["nudge_level"] not in NUDGE_LEVELS:
        defaults["nudge_level"] = "balanced"
    return defaults


# ---------------------------------------------------------------------------
# Data readers
# ---------------------------------------------------------------------------

def count_total_sessions(user_data_dir: Path) -> int:
    """Count total sessions Forge has tracked (analyzed + unanalyzed)."""
    log_path = user_data_dir / "unanalyzed-sessions.log"
    unanalyzed = 0
    if log_path.is_file():
        try:
            unanalyzed = len(
                log_path.read_text(encoding="utf-8").strip().splitlines()
            )
        except OSError:
            pass

    # Count from session log (all sessions ever seen)
    session_log_path = user_data_dir / "session-log.jsonl"
    logged = 0
    if session_log_path.is_file():
        try:
            logged = len(
                session_log_path.read_text(encoding="utf-8").strip().splitlines()
            )
        except OSError:
            pass

    return max(logged, unanalyzed)


def load_pending_proposals(project_root: Path) -> List[Dict]:
    """Load all pending proposals from the cache."""
    pending_path = resolve_user_file(project_root, "proposals/pending.json")
    if not pending_path.is_file():
        return []
    try:
        data = json.loads(pending_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            proposals = data
        elif isinstance(data, dict):
            proposals = data.get("proposals", [])
        else:
            return []
        return [
            p for p in proposals
            if isinstance(p, dict) and p.get("status") == "pending"
        ]
    except (OSError, json.JSONDecodeError):
        return []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    root = find_project_root()
    user_data_dir = get_user_data_dir(root)
    settings = load_settings(root)

    nudge_level = settings["nudge_level"]
    proactive_enabled = settings["proactive_proposals"]

    message = None  # type: Optional[str]

    # --- Priority 1: Pending proposals ---
    # Show proposal count when proposals exist and proactive is enabled.
    if proactive_enabled:
        pending_count = len(load_pending_proposals(root))
        if pending_count > 0:
            if pending_count == 1:
                message = "Forge has 1 proposal. Run `/forge` to review."
            else:
                message = "Forge has {} proposals. Run `/forge` to review.".format(
                    pending_count
                )

    # --- Priority 2: Ambient health signal ---
    # When no proposals to show but Forge is tracking sessions, show a brief
    # status. Suppressed in quiet mode.
    if message is None and nudge_level != "quiet":
        total_sessions = count_total_sessions(user_data_dir)
        if total_sessions > 0:
            message = "Forge: tracking {} session{} for this project.".format(
                total_sessions,
                "s" if total_sessions != 1 else "",
            )

    # --- Priority 3: Nothing to report ---
    if message is None:
        return

    output = {"systemMessage": message}
    json.dump(output, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Safely merge a new hook into .claude/settings.json.

Reads hook parameters from stdin (JSON object with event, matcher,
command, timeout), reads the existing settings file, merges the hook
without removing anything, and writes back atomically.

Usage:
    echo '{"event":"PostToolUse","matcher":"Write|Edit","command":"npx prettier --write \\"$CLAUDE_TOOL_INPUT_FILE_PATH\\""}' | \
        python3 merge-settings.py --settings-path .claude/settings.json
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


def merge_hook(
    settings: Dict[str, Any],
    event: str,
    matcher: Optional[str],
    command: str,
    timeout: int,
) -> str:
    """Merge a hook into settings, returning status string."""
    hooks = settings.setdefault("hooks", {})
    event_list: List[Dict[str, Any]] = hooks.setdefault(event, [])

    # Check for duplicate: same command in any existing hook entry
    for entry in event_list:
        for h in entry.get("hooks", []):
            if h.get("command") == command:
                return "already_exists"

    # Build the new hook entry
    hook_def: Dict[str, Any] = {
        "type": "command",
        "command": command,
        "timeout": timeout,
    }

    # Find an existing entry with the same matcher, or create a new one
    if matcher:
        for entry in event_list:
            if entry.get("matcher") == matcher:
                entry["hooks"].append(hook_def)
                return "added"
        # No matching entry — create new
        event_list.append({
            "matcher": matcher,
            "hooks": [hook_def],
        })
    else:
        # No matcher — append as a new entry
        event_list.append({
            "hooks": [hook_def],
        })

    return "added"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge a hook into .claude/settings.json"
    )
    parser.add_argument(
        "--settings-path", type=str, required=True,
        help="Path to .claude/settings.json"
    )
    args = parser.parse_args()

    settings_path = Path(args.settings_path)

    # Read hook spec from stdin
    try:
        raw = sys.stdin.read()
    except Exception as e:
        print("Error reading stdin: {}".format(e), file=sys.stderr)
        sys.exit(1)

    if not raw.strip():
        print("Error: no input on stdin", file=sys.stderr)
        sys.exit(1)

    try:
        hook_spec = json.loads(raw)
    except json.JSONDecodeError as e:
        print("Error: invalid JSON: {}".format(e), file=sys.stderr)
        sys.exit(1)

    event = hook_spec.get("event")
    command = hook_spec.get("command")
    if not event or not command:
        print("Error: 'event' and 'command' are required", file=sys.stderr)
        sys.exit(1)

    matcher: Optional[str] = hook_spec.get("matcher")
    timeout: int = hook_spec.get("timeout", 10)

    # Read existing settings
    settings: Dict[str, Any] = {}
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            if not isinstance(settings, dict):
                settings = {}
        except (json.JSONDecodeError, OSError):
            # Malformed settings — start fresh but warn
            print("Warning: existing settings.json is malformed, starting fresh",
                  file=sys.stderr)
            settings = {}

    # Merge
    status = merge_hook(settings, event, matcher, command, timeout)

    # Write atomically
    if status == "added":
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(settings_path.parent),
                prefix="settings_",
                suffix=".json.tmp",
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, str(settings_path))
        except OSError as e:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            print("Error writing settings: {}".format(e), file=sys.stderr)
            sys.exit(1)

    output = {
        "status": status,
        "settings_path": str(settings_path),
        "hook_event": event,
        "hook_command": command,
    }

    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

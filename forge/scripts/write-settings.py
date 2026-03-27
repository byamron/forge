#!/usr/bin/env python3
"""Update Forge settings.

Reads the existing settings file, applies the change, writes it back.
Creates the file and directory if they don't exist.

Usage:
    python3 write-settings.py --nudge-level <quiet|balanced|eager>
"""

import argparse
import json
import sys
from pathlib import Path

VALID_LEVELS = ("quiet", "balanced", "eager")

LEVEL_DESCRIPTIONS = {
    "quiet": "No automatic nudges. Forge only runs when you invoke /forge.",
    "balanced": "Nudge on session start after 5+ new unanalyzed sessions.",
    "eager": "Nudge on session start after 2+ new unanalyzed sessions.",
}


def find_project_root() -> Path:
    current = Path.cwd().resolve()
    while current != current.parent:
        if (current / ".git").exists() or (current / ".claude").exists():
            return current
        current = current.parent
    return Path.cwd().resolve()


def main():
    parser = argparse.ArgumentParser(description="Update Forge settings.")
    parser.add_argument(
        "--nudge-level",
        choices=VALID_LEVELS,
        help="Set the nudge frequency level.",
    )
    args = parser.parse_args()

    if not args.nudge_level:
        print("No changes specified.", file=sys.stderr)
        sys.exit(1)

    root = find_project_root()
    settings_path = root / ".claude" / "forge" / "settings.json"

    # Load existing settings
    settings = {}
    if settings_path.is_file():
        try:
            with open(settings_path, "r") as f:
                settings = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Apply changes
    settings["nudge_level"] = args.nudge_level

    # Write atomically
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(settings_path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    Path(tmp).replace(settings_path)

    output = {
        "nudge_level": args.nudge_level,
        "description": LEVEL_DESCRIPTIONS[args.nudge_level],
        "settings_path": str(settings_path),
    }
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

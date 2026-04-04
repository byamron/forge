#!/usr/bin/env python3
"""Update Forge settings.

Reads the existing settings file, applies the change, writes it back.
Creates the file and directory if they don't exist.

Usage:
    python3 write-settings.py --nudge-level <quiet|balanced|eager> --proactive-proposals <on|off>
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

from project_identity import find_project_root, get_user_data_dir

VALID_LEVELS = ("quiet", "balanced", "eager")

LEVEL_DESCRIPTIONS = {
    "quiet": "No automatic nudges. Forge only runs when you invoke /forge.",
    "balanced": "Nudge on session start after 5+ new unanalyzed sessions.",
    "eager": "Nudge on session start after 2+ new unanalyzed sessions.",
}


def main():
    parser = argparse.ArgumentParser(description="Update Forge settings.")
    parser.add_argument(
        "--nudge-level",
        choices=VALID_LEVELS,
        help="Set the nudge frequency level.",
    )
    parser.add_argument(
        "--proactive-proposals",
        choices=("on", "off"),
        help="Enable or disable proactive proposal surfacing at session start.",
    )
    args = parser.parse_args()

    if not args.nudge_level and not args.proactive_proposals:
        print("No changes specified.", file=sys.stderr)
        sys.exit(1)

    root = find_project_root()
    settings_path = get_user_data_dir(root) / "settings.json"

    # Load existing settings
    settings = {}
    if settings_path.is_file():
        try:
            with open(settings_path, "r") as f:
                settings = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Apply changes
    if args.nudge_level:
        settings["nudge_level"] = args.nudge_level
    if args.proactive_proposals:
        settings["proactive_proposals"] = args.proactive_proposals == "on"

    # Write atomically
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(settings_path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    os.chmod(tmp, 0o644)
    Path(tmp).replace(settings_path)

    output = {
        "settings_path": str(settings_path),
    }  # type: Dict[str, Any]
    if args.nudge_level:
        output["nudge_level"] = args.nudge_level
        output["nudge_level_description"] = LEVEL_DESCRIPTIONS[args.nudge_level]
    if args.proactive_proposals:
        output["proactive_proposals"] = settings["proactive_proposals"]
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

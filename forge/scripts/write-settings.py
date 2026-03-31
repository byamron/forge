#!/usr/bin/env python3
"""Update Forge settings.

Reads the existing settings file, applies the change, writes it back.
Creates the file and directory if they don't exist.

Usage:
    python3 write-settings.py --nudge-level <quiet|balanced|eager>
    python3 write-settings.py --analysis-depth <standard|deep>
"""

import argparse
import json
import os
import sys
from pathlib import Path

from project_identity import get_user_data_dir

VALID_LEVELS = ("quiet", "balanced", "eager")
VALID_DEPTHS = ("standard", "deep")

LEVEL_DESCRIPTIONS = {
    "quiet": "No automatic nudges. Forge only runs when you invoke /forge.",
    "balanced": "Nudge on session start after 5+ new unanalyzed sessions.",
    "eager": "Nudge on session start after 2+ new unanalyzed sessions.",
}

DEPTH_DESCRIPTIONS = {
    "standard": "Script-only analysis. Fast, zero token cost.",
    "deep": "Scripts + background LLM pass. Finds contextual patterns scripts can't detect.",
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
    parser.add_argument(
        "--analysis-depth",
        choices=VALID_DEPTHS,
        help="Set the analysis depth (standard or deep).",
    )
    args = parser.parse_args()

    if not args.nudge_level and not args.analysis_depth:
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
    if args.analysis_depth:
        settings["analysis_depth"] = args.analysis_depth

    # Write atomically
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(settings_path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    os.chmod(tmp, 0o644)
    Path(tmp).replace(settings_path)

    output = {"settings_path": str(settings_path)}
    if args.nudge_level:
        output["nudge_level"] = args.nudge_level
        output["nudge_level_description"] = LEVEL_DESCRIPTIONS[args.nudge_level]
    if args.analysis_depth:
        output["analysis_depth"] = args.analysis_depth
        output["analysis_depth_description"] = DEPTH_DESCRIPTIONS[args.analysis_depth]
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

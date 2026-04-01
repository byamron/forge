#!/usr/bin/env python3
"""Read Forge settings and output current configuration as JSON.

Settings file: ~/.claude/forge/projects/<hash>/settings.json
Falls back to defaults if the file doesn't exist or is invalid.

Usage:
    python3 read-settings.py [--project-root /path]
"""

import json
import sys
from pathlib import Path

from project_identity import find_project_root, resolve_user_file

DEFAULTS = {
    "nudge_level": "balanced",
    "analysis_depth": "standard",
}

LEVEL_DESCRIPTIONS = {
    "quiet": "No automatic nudges. Forge only runs when you invoke /forge.",
    "balanced": "Nudge when you have pending proposals, or after 5+ sessions since last analysis.",
    "eager": "Nudge when you have any pending proposals, or after 2+ sessions since last analysis.",
}

LEVEL_THRESHOLDS = {
    "quiet": None,
    "balanced": 5,
    "eager": 2,
}

DEPTH_DESCRIPTIONS = {
    "standard": "Script-only analysis. Fast, zero token cost.",
    "deep": "Scripts + background LLM pass. Finds contextual patterns scripts can't detect. Uses ~5K tokens.",
}


def load_settings(project_root: Path) -> dict:
    settings_path = resolve_user_file(project_root, "settings.json")
    settings = dict(DEFAULTS)
    if settings_path.is_file():
        try:
            with open(settings_path, "r") as f:
                user = json.load(f)
            if isinstance(user, dict):
                for k, v in user.items():
                    if k in DEFAULTS:
                        settings[k] = v
        except (json.JSONDecodeError, OSError):
            pass
    return settings


def main():
    root = find_project_root()
    settings = load_settings(root)
    level = settings.get("nudge_level", "balanced")

    # Validate level
    if level not in LEVEL_DESCRIPTIONS:
        level = "balanced"

    depth = settings.get("analysis_depth", "standard")
    if depth not in DEPTH_DESCRIPTIONS:
        depth = "standard"

    output = {
        "nudge_level": level,
        "nudge_level_description": LEVEL_DESCRIPTIONS[level],
        "session_threshold": LEVEL_THRESHOLDS[level],
        "all_levels": {
            name: {"description": desc, "session_threshold": LEVEL_THRESHOLDS[name]}
            for name, desc in LEVEL_DESCRIPTIONS.items()
        },
        "analysis_depth": depth,
        "analysis_depth_description": DEPTH_DESCRIPTIONS[depth],
        "all_depths": {
            name: {"description": desc}
            for name, desc in DEPTH_DESCRIPTIONS.items()
        },
        "settings_path": str(resolve_user_file(root, "settings.json")),
    }

    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

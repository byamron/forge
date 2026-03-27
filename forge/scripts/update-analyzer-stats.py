#!/usr/bin/env python3
"""Update analyzer feedback stats after a proposal decision.

Called by the optimize skill after the user approves, dismisses, or
permanently suppresses a proposal. Updates ~/.claude/forge/analyzer-stats.json
so the transcript analyzer can learn from past decisions.

Usage:
    python3 update-analyzer-stats.py --category corrections \
        --outcome approved --theme-hash a1b2c3d4

    python3 update-analyzer-stats.py --category corrections \
        --outcome suppressed --theme-hash a1b2c3d4 \
        --key-terms "snake_case,variable,names"
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

VALID_CATEGORIES = ("corrections", "post_actions", "repeated_prompts")
VALID_OUTCOMES = ("approved", "dismissed", "suppressed")


def main():
    parser = argparse.ArgumentParser(
        description="Update analyzer feedback stats."
    )
    parser.add_argument(
        "--category",
        required=True,
        choices=VALID_CATEGORIES,
        help="Pattern category.",
    )
    parser.add_argument(
        "--outcome",
        required=True,
        choices=VALID_OUTCOMES,
        help="User decision: approved, dismissed, or suppressed (never show again).",
    )
    parser.add_argument(
        "--theme-hash",
        required=True,
        help="Theme hash from the proposal.",
    )
    parser.add_argument(
        "--key-terms",
        default="",
        help="Comma-separated key terms (for context in stats file).",
    )
    args = parser.parse_args()

    stats_path = Path.home() / ".claude" / "forge" / "analyzer-stats.json"

    # Load existing stats
    stats = {
        "version": 1,
        "corrections": {"proposed": 0, "approved": 0, "dismissed": 0},
        "post_actions": {"proposed": 0, "approved": 0, "dismissed": 0},
        "repeated_prompts": {"proposed": 0, "approved": 0, "dismissed": 0},
        "theme_outcomes": {},
        "suppressed_themes": [],
    }
    if stats_path.is_file():
        try:
            with open(stats_path, "r") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict) and loaded.get("version") == 1:
                stats = loaded
        except (json.JSONDecodeError, OSError):
            pass

    # Ensure category exists
    if args.category not in stats:
        stats[args.category] = {"proposed": 0, "approved": 0, "dismissed": 0}

    # Update category counters
    outcome_key = "dismissed" if args.outcome == "suppressed" else args.outcome
    stats[args.category][outcome_key] = (
        stats[args.category].get(outcome_key, 0) + 1
    )

    # Record theme outcome
    if "theme_outcomes" not in stats:
        stats["theme_outcomes"] = {}
    stats["theme_outcomes"][args.theme_hash] = {
        "outcome": args.outcome,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "key_terms": [t.strip() for t in args.key_terms.split(",") if t.strip()],
    }

    # Suppressed themes — never propose again
    if args.outcome == "suppressed":
        if "suppressed_themes" not in stats:
            stats["suppressed_themes"] = []
        if args.theme_hash not in stats["suppressed_themes"]:
            stats["suppressed_themes"].append(args.theme_hash)

    stats["last_updated"] = datetime.datetime.utcnow().isoformat() + "Z"

    # Write atomically
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(stats_path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(stats, f, indent=2)
        f.write("\n")
    Path(tmp).replace(stats_path)

    output = {
        "updated": True,
        "category": args.category,
        "outcome": args.outcome,
        "theme_hash": args.theme_hash,
    }
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

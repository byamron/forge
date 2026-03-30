#!/usr/bin/env python3
"""Finalize all proposal outcomes in a single call.

Handles all bookkeeping that previously required multiple separate tool calls:
- Updates pending.json with new statuses
- Records applied proposals in history/applied.json
- Appends dismissed proposals to dismissed.json
- Updates analyzer-stats.json for feedback loop

Takes a JSON object on stdin with proposal outcomes.

Usage:
    echo '{"outcomes": [...]}' | python3 finalize-proposals.py --project-root /path

Input format:
    {
        "outcomes": [
            {"id": "auto-eslint-hook", "status": "applied", "type": "hook"},
            {"id": "reduce-claude-md-size", "status": "dismissed", "type": "reference_doc"},
            {"id": "dev-server-skill", "status": "pending", "type": "skill"}
        ],
        "all_proposals": [...]  // Full proposal objects for pending.json
    }
"""

import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List


# Maps proposal types to analyzer stat categories
TYPE_TO_CATEGORY = {
    "skill": "repeated_prompts",
    "skill_update": "repeated_prompts",
    "hook": "post_actions",
    "rule": "corrections",
    "reference_doc": "corrections",
    "claude_md": "corrections",
    "demotion": "tier_management",
}


def _load_json(path: Path) -> Any:
    """Load JSON from a file, returning empty dict/list on failure."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (OSError, json.JSONDecodeError):
        return None


def _write_json_atomic(path: Path, data: Any) -> None:
    """Write JSON atomically via temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.chmod(tmp, 0o644)
    Path(tmp).replace(path)


def _update_pending(project_root: Path, all_proposals: List[Dict]) -> None:
    """Write the full proposal list with updated statuses."""
    pending_path = project_root / ".claude" / "forge" / "proposals" / "pending.json"
    pending_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(pending_path, all_proposals)


def _record_applied(project_root: Path, applied: List[Dict]) -> None:
    """Append applied proposals to history."""
    if not applied:
        return
    history_path = project_root / ".claude" / "forge" / "history" / "applied.json"
    existing = _load_json(history_path)
    if not isinstance(existing, list):
        existing = []
    now = datetime.datetime.utcnow().isoformat() + "Z"
    for p in applied:
        existing.append({
            "id": p["id"],
            "type": p.get("type", "unknown"),
            "applied_at": now,
        })
    _write_json_atomic(history_path, existing)


def _record_dismissed(project_root: Path, dismissed: List[Dict]) -> None:
    """Append dismissed proposals to dismissed.json."""
    if not dismissed:
        return
    dismissed_path = project_root / ".claude" / "forge" / "dismissed.json"
    existing = _load_json(dismissed_path)
    if not isinstance(existing, list):
        existing = []
    now = datetime.datetime.utcnow().isoformat() + "Z"
    for p in dismissed:
        existing.append({
            "id": p["id"],
            "type": p.get("type", "unknown"),
            "dismissed_at": now,
        })
    _write_json_atomic(dismissed_path, existing)


def _update_stats(outcomes: List[Dict]) -> None:
    """Update analyzer-stats.json with all outcomes at once."""
    stats_path = Path.home() / ".claude" / "forge" / "analyzer-stats.json"
    stats = {
        "version": 1,
        "corrections": {"proposed": 0, "approved": 0, "dismissed": 0},
        "post_actions": {"proposed": 0, "approved": 0, "dismissed": 0},
        "repeated_prompts": {"proposed": 0, "approved": 0, "dismissed": 0},
        "theme_outcomes": {},
        "suppressed_themes": [],
    }
    if stats_path.is_file():
        loaded = _load_json(stats_path)
        if isinstance(loaded, dict) and loaded.get("version") == 1:
            stats = loaded

    now = datetime.datetime.utcnow().isoformat() + "Z"

    for outcome in outcomes:
        status = outcome.get("status", "pending")
        if status == "pending":
            continue  # Skipped — no stats update

        proposal_id = outcome.get("id", "")
        proposal_type = outcome.get("type", "")
        category = TYPE_TO_CATEGORY.get(proposal_type, "corrections")

        if category not in stats:
            stats[category] = {"proposed": 0, "approved": 0, "dismissed": 0}

        if status == "applied":
            stats[category]["approved"] = stats[category].get("approved", 0) + 1
            stats.setdefault("theme_outcomes", {})[proposal_id] = {
                "outcome": "approved",
                "timestamp": now,
            }
        elif status == "dismissed":
            stats[category]["dismissed"] = stats[category].get("dismissed", 0) + 1
            stats.setdefault("theme_outcomes", {})[proposal_id] = {
                "outcome": "suppressed",
                "timestamp": now,
            }
            suppressed = stats.setdefault("suppressed_themes", [])
            if proposal_id not in suppressed:
                suppressed.append(proposal_id)

    stats["last_updated"] = now
    _write_json_atomic(stats_path, stats)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Finalize proposal outcomes")
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()

    if not project_root.is_dir():
        print(f"Error: project root does not exist: {project_root}", file=sys.stderr)
        sys.exit(1)

    # Read input from stdin
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        print(json.dumps({"error": "Invalid JSON on stdin"}))
        sys.exit(1)

    outcomes = data.get("outcomes", [])
    all_proposals = data.get("all_proposals", [])

    applied = [o for o in outcomes if o.get("status") == "applied"]
    dismissed = [o for o in outcomes if o.get("status") == "dismissed"]

    # Do all bookkeeping
    _update_pending(project_root, all_proposals)
    _record_applied(project_root, applied)
    _record_dismissed(project_root, dismissed)
    _update_stats(outcomes)

    result = {
        "applied": len(applied),
        "dismissed": len(dismissed),
        "skipped": len([o for o in outcomes if o.get("status") == "pending"]),
    }
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

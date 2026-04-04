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

from project_identity import get_user_data_dir


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
    pending_path = get_user_data_dir(project_root) / "proposals" / "pending.json"
    pending_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(pending_path, all_proposals)


def _record_applied(project_root: Path, applied: List[Dict],
                    all_proposals: List[Dict]) -> None:
    """Append applied proposals to history with triggering pattern data."""
    if not applied:
        return
    history_path = get_user_data_dir(project_root) / "history" / "applied.json"
    existing = _load_json(history_path)
    if not isinstance(existing, list):
        existing = []
    now = datetime.datetime.utcnow().isoformat() + "Z"

    # Build lookup from full proposals for evidence data
    proposal_lookup = {p.get("id"): p for p in all_proposals}

    for p in applied:
        pid = p["id"]
        full = proposal_lookup.get(pid, {})
        entry = {
            "id": pid,
            "type": p.get("type", "unknown"),
            "applied_at": now,
            "evidence_summary": full.get("evidence_summary", ""),
            "description": full.get("description", ""),
        }  # type: Dict[str, Any]

        # Store tracking data based on the proposal type → stat category mapping
        ptype = p.get("type", "")
        category = TYPE_TO_CATEGORY.get(ptype, "")
        if category == "corrections":
            entry["tracking"] = {
                "source": "correction",
                "pattern_id": pid,
            }
        elif category == "post_actions":
            entry["tracking"] = {
                "source": "post_action",
                "pattern_id": pid,
            }
        elif category == "repeated_prompts":
            entry["tracking"] = {
                "source": "repeated_prompt",
                "pattern_id": pid,
            }

        existing.append(entry)
    _write_json_atomic(history_path, existing)


def _record_dismissed(project_root: Path, dismissed: List[Dict]) -> None:
    """Append dismissed proposals to dismissed.json."""
    if not dismissed:
        return
    dismissed_path = get_user_data_dir(project_root) / "dismissed.json"
    existing = _load_json(dismissed_path)
    if not isinstance(existing, list):
        existing = []
    now = datetime.datetime.utcnow().isoformat() + "Z"
    for p in dismissed:
        entry = {
            "id": p["id"],
            "type": p.get("type", "unknown"),
            "dismissed_at": now,
        }  # type: Dict[str, Any]
        reason = p.get("reason", "")
        if reason:
            entry["reason"] = reason
        existing.append(entry)
    _write_json_atomic(dismissed_path, existing)


# Valid dismissal reasons — kept as a set for validation
DISMISSAL_REASONS = {
    "low_impact", "missing_safety", "already_handled", "not_relevant",
    "unspecified",
}

# Valid modification signal types
MODIFICATION_SIGNALS = {
    "added_approval_gate", "narrowed_scope", "rewrote_content", "minor_tweaks",
}

# Safety gate trigger threshold — after this many signals, automation proposals
# get flagged for safety review
SAFETY_GATE_THRESHOLD = 3


def _ensure_feedback_signals(stats: Dict) -> Dict:
    """Ensure stats has a feedback_signals section with all required keys."""
    fs = stats.setdefault("feedback_signals", {})
    fs.setdefault("category_precision", {})
    fs.setdefault("dismissal_reasons", {})
    fs.setdefault("modification_signals", {})
    fs.setdefault("safety_gate", {
        "triggered": False,
        "signal_count": 0,
        "threshold": SAFETY_GATE_THRESHOLD,
    })
    fs.setdefault("skip_counts", {})
    return fs


def _update_feedback_signals(stats: Dict, outcomes: List[Dict]) -> None:
    """Update the feedback_signals section of analyzer-stats.json.

    Tracks per-category precision, dismissal reasons, modification patterns,
    skip counts, and the safety gate state.
    """
    fs = _ensure_feedback_signals(stats)

    for outcome in outcomes:
        status = outcome.get("status", "pending")
        proposal_type = outcome.get("type", "")
        proposal_id = outcome.get("id", "")

        # Per-category precision tracking
        if status in ("applied", "dismissed") and proposal_type:
            cat = fs["category_precision"].setdefault(
                proposal_type, {"approved": 0, "dismissed": 0}
            )
            if status == "applied":
                cat["approved"] = cat.get("approved", 0) + 1
            else:
                cat["dismissed"] = cat.get("dismissed", 0) + 1

        # Dismissal reason tracking
        if status == "dismissed" and proposal_type:
            reason = outcome.get("reason", "unspecified")
            if reason not in DISMISSAL_REASONS:
                reason = "unspecified"
            reasons = fs["dismissal_reasons"].setdefault(proposal_type, {})
            reasons[reason] = reasons.get(reason, 0) + 1

        # Modification signal tracking
        if status == "applied":
            mod_type = outcome.get("modification_type", "")
            if mod_type and mod_type in MODIFICATION_SIGNALS and proposal_type:
                signals = fs["modification_signals"].setdefault(
                    proposal_type, {}
                )
                signals[mod_type] = signals.get(mod_type, 0) + 1

        # Skip count tracking — only for pending; clean up on terminal status
        if status == "pending" and proposal_id:
            fs["skip_counts"][proposal_id] = (
                fs["skip_counts"].get(proposal_id, 0) + 1
            )
        elif status in ("applied", "dismissed") and proposal_id:
            fs["skip_counts"].pop(proposal_id, None)

    # Recompute safety gate state from totals
    total_safety_signals = 0
    for cat_reasons in fs["dismissal_reasons"].values():
        total_safety_signals += cat_reasons.get("missing_safety", 0)
    for cat_mods in fs["modification_signals"].values():
        total_safety_signals += cat_mods.get("added_approval_gate", 0)

    threshold = fs["safety_gate"].get("threshold", SAFETY_GATE_THRESHOLD)
    fs["safety_gate"] = {
        "triggered": total_safety_signals >= threshold,
        "signal_count": total_safety_signals,
        "threshold": threshold,
    }


def _update_stats(outcomes: List[Dict]) -> None:
    """Update analyzer-stats.json with all outcomes at once."""
    stats_path = Path.home() / ".claude" / "forge" / "analyzer-stats.json"
    stats = {
        "version": 2,
        "corrections": {"proposed": 0, "approved": 0, "dismissed": 0},
        "post_actions": {"proposed": 0, "approved": 0, "dismissed": 0},
        "repeated_prompts": {"proposed": 0, "approved": 0, "dismissed": 0},
        "theme_outcomes": {},
        "suppressed_themes": [],
    }
    if stats_path.is_file():
        loaded = _load_json(stats_path)
        if isinstance(loaded, dict) and loaded.get("version") in (1, 2):
            stats = loaded

    now = datetime.datetime.utcnow().isoformat() + "Z"

    for outcome in outcomes:
        status = outcome.get("status", "pending")
        if status == "pending":
            continue  # Skipped — no legacy stats update

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

    # Update feedback signals (per-category precision, reasons, modifications)
    _update_feedback_signals(stats, outcomes)

    stats["version"] = 2
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
    _record_applied(project_root, applied, all_proposals)
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

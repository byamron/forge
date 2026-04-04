#!/usr/bin/env python3
"""Check if Forge should nudge the user about pending analysis.

Used by the SessionStart hook to provide ambient presence. Outputs a JSON
object with a systemMessage field when there is something worth telling the
user. Otherwise outputs nothing.

Behavior depends on two settings:
- nudge_level (quiet/balanced/eager): controls session-count nudges.
- proactive_proposals (true/false, default true): when true and
  high-confidence cached proposals exist, surfaces the top 1-2 proposals
  with enough detail for Claude to present them inline.

Additional signals (always on, independent of nudge level):
- Effectiveness alerts: if an applied artifact appears ineffective (pattern
  still present after 3+ sessions), append a warning.
- Ambient health: when nothing else to say but Forge is tracking sessions,
  emit a brief status line so the user knows Forge is active.

Usage:
    python3 check-pending.py [--project-root /path]
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from project_identity import (
    find_project_root,
    get_project_data_dir,
    get_user_data_dir,
    resolve_user_file,
)

LEVEL_THRESHOLDS = {
    "quiet": None,
    "balanced": 5,
    "eager": 2,
}


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
    if defaults["nudge_level"] not in LEVEL_THRESHOLDS:
        defaults["nudge_level"] = "balanced"
    return defaults


# ---------------------------------------------------------------------------
# Data readers
# ---------------------------------------------------------------------------

def count_unanalyzed_sessions(user_data_dir: Path) -> int:
    log_path = user_data_dir / "unanalyzed-sessions.log"
    if not log_path.is_file():
        return 0
    try:
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        return len(lines)
    except OSError:
        return 0


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


def load_applied_history(project_root: Path) -> List[Dict]:
    """Load applied proposal history from project-level storage."""
    project_data = get_project_data_dir(project_root)
    history_path = project_data / "history" / "applied.json"
    if not history_path.is_file():
        # Try user-level fallback
        user_data = get_user_data_dir(project_root)
        history_path = user_data / "history" / "applied.json"
        if not history_path.is_file():
            return []
    try:
        data = json.loads(history_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except (OSError, json.JSONDecodeError):
        return []


def load_effectiveness(
    project_root: Path,
    applied: List[Dict],
) -> List[Dict]:
    """Compute effectiveness by comparing applied artifacts against transcript cache.

    Reads the transcript analysis cache (candidates.corrections and
    candidates.post_actions) and checks whether patterns that triggered
    applied proposals are still present.
    """
    if not applied:
        return []

    # Read transcript analysis from cache
    cache_path = get_user_data_dir(project_root) / "cache" / "transcripts.cache.json"
    if not cache_path.is_file():
        return []
    try:
        cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
        transcripts = cache_data.get("result", {})
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(transcripts, dict):
        return []

    candidates = transcripts.get("candidates", {})
    if not isinstance(candidates, dict):
        return []

    # Index current patterns by ID/theme for matching
    current_pattern_ids = set()  # type: set
    corrections = candidates.get("corrections", [])
    for corr in corrections:
        if isinstance(corr, dict):
            theme_hash = corr.get("theme_hash", "")
            if theme_hash:
                current_pattern_ids.add(theme_hash)
            pattern = corr.get("pattern", corr.get("theme", ""))
            if pattern:
                current_pattern_ids.add(pattern.lower())

    post_actions = candidates.get("post_actions", [])
    for pa in post_actions:
        if isinstance(pa, dict):
            cmd = pa.get("command", "")
            if cmd:
                current_pattern_ids.add(cmd.lower())

    # Check each applied artifact
    effectiveness = []  # type: List[Dict]
    for entry in applied:
        tracking = entry.get("tracking")
        if not tracking:
            continue

        pid = entry.get("id", "unknown")
        pattern_id = tracking.get("pattern_id", "")
        desc = entry.get("description", pid)

        still_present = (
            pattern_id in current_pattern_ids
            or pattern_id.lower() in current_pattern_ids
        )

        effectiveness.append({
            "id": pid,
            "description": desc,
            "applied_at": entry.get("applied_at", ""),
            "status": "ineffective" if still_present else "effective",
            "still_present": still_present,
            "current_frequency": 0,
        })

    return effectiveness


# ---------------------------------------------------------------------------
# Proactive proposal selection (Step 1)
# ---------------------------------------------------------------------------

def _select_proactive_proposals(
    proposals: List[Dict],
    max_count: int = 2,
) -> List[Dict]:
    """Select high-confidence proposals suitable for proactive surfacing.

    Criteria: confidence == "high" AND (impact == "high" OR occurrences >= 5).
    Returns at most max_count proposals, sorted by impact then occurrences.
    """
    IMPACT_ORDER = {"high": 0, "medium": 1, "low": 2}

    candidates = []
    for p in proposals:
        if p.get("confidence") != "high":
            continue
        impact = p.get("impact", "low")
        occurrences = p.get("occurrences", 0)
        if impact == "high" or occurrences >= 5:
            candidates.append(p)

    # Sort: high impact first, then by occurrences descending
    candidates.sort(
        key=lambda x: (
            IMPACT_ORDER.get(x.get("impact", "low"), 2),
            -(x.get("occurrences", 0)),
        )
    )
    return candidates[:max_count]


def _format_proactive_message(
    proactive: List[Dict],
    total_pending: int,
) -> str:
    """Format proactive proposals into a systemMessage string."""
    lines = []  # type: List[str]

    for p in proactive:
        desc = p.get("description", "Untitled proposal")
        evidence = p.get("evidence_summary", "")
        sessions = p.get("sessions", p.get("session_count", 0))
        occurrences = p.get("occurrences", 0)

        # Build a concise detail line
        detail_parts = []  # type: List[str]
        if occurrences:
            detail_parts.append(
                "{} occurrence{}".format(occurrences, "s" if occurrences != 1 else "")
            )
        if sessions:
            detail_parts.append(
                "across {} session{}".format(sessions, "s" if sessions != 1 else "")
            )
        detail = " ".join(detail_parts)

        line = "**{}**".format(desc)
        if evidence:
            line += " -- {}".format(evidence)
        if detail:
            line += " ({})".format(detail)
        lines.append(line)

    header = "Forge has {} high-confidence suggestion{}:\n".format(
        len(proactive),
        "s" if len(proactive) != 1 else "",
    )
    body = "\n".join("- {}".format(l) for l in lines)

    remaining = total_pending - len(proactive)
    if remaining > 0:
        footer = "\n\nRun `/forge` to review all {} proposals.".format(total_pending)
    else:
        footer = "\n\nRun `/forge` to review and apply."

    return header + body + footer


# ---------------------------------------------------------------------------
# Effectiveness alerts (Step 2)
# ---------------------------------------------------------------------------

def _check_effectiveness(project_root: Path) -> Optional[str]:
    """Check for ineffective applied artifacts and return an alert if found."""
    applied = load_applied_history(project_root)
    if not applied:
        return None

    effectiveness = load_effectiveness(project_root, applied)
    if not effectiveness:
        return None

    alerts = []  # type: List[str]
    for eff in effectiveness:
        if eff.get("status") != "ineffective":
            continue
        desc = eff.get("description", eff.get("id", "unknown"))
        alerts.append(
            "'{}' may not be working -- the triggering pattern is still present.".format(desc)
        )

    if not alerts:
        return None

    return "Note: " + " ".join(alerts)


# ---------------------------------------------------------------------------
# Ambient health signal (Step 3)
# ---------------------------------------------------------------------------

def _format_health_signal(
    total_sessions: int,
    applied_count: int,
    all_effective: bool,
) -> Optional[str]:
    """Format a brief health line when there's nothing else to report."""
    if total_sessions <= 0:
        return None

    parts = ["Forge: tracking {} session{} for this project.".format(
        total_sessions,
        "s" if total_sessions != 1 else "",
    )]

    if applied_count > 0:
        if all_effective:
            parts.append("All {} applied artifact{} effective.".format(
                applied_count,
                "s" if applied_count != 1 else "",
            ))
        # If not all effective, the effectiveness alert handles it
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    root = find_project_root()
    user_data_dir = get_user_data_dir(root)
    settings = load_settings(root)

    nudge_level = settings["nudge_level"]
    proactive_enabled = settings["proactive_proposals"]
    threshold = LEVEL_THRESHOLDS.get(nudge_level)

    # Load data
    pending = load_pending_proposals(root)
    pending_count = len(pending)
    unanalyzed = count_unanalyzed_sessions(user_data_dir)
    total_sessions = count_total_sessions(user_data_dir)

    message_parts = []  # type: List[str]

    # --- Proactive proposals (highest priority) ---
    if proactive_enabled and pending:
        proactive = _select_proactive_proposals(pending)
        if proactive:
            message_parts.append(
                _format_proactive_message(proactive, pending_count)
            )

    # --- Session-count nudge (if no proactive proposals shown) ---
    if not message_parts and threshold is not None:
        nudge_parts = []  # type: List[str]
        if pending_count > 0:
            nudge_parts.append(
                "{} pending proposal{} to review".format(
                    pending_count,
                    "s" if pending_count != 1 else "",
                )
            )
        if unanalyzed >= threshold:
            nudge_parts.append(
                "{} session{} since last analysis".format(
                    unanalyzed,
                    "s" if unanalyzed != 1 else "",
                )
            )
        if nudge_parts:
            message_parts.append(
                "Forge: " + ", ".join(nudge_parts) + ". Run `/forge` to review."
            )

    # --- Effectiveness alerts (always on, independent of nudge level) ---
    effectiveness_alert = _check_effectiveness(root)
    if effectiveness_alert:
        message_parts.append(effectiveness_alert)

    # --- Ambient health signal (only when nothing else to say, suppressed in quiet mode) ---
    if not message_parts and nudge_level != "quiet":
        applied = load_applied_history(root)
        applied_count = len(applied)
        effectiveness = load_effectiveness(root, applied)
        ineffective_ids = {
            e.get("id") for e in effectiveness if e.get("status") == "ineffective"
        }
        all_effective = applied_count == 0 or not ineffective_ids
        health = _format_health_signal(total_sessions, applied_count, all_effective)
        if health:
            message_parts.append(health)

    if not message_parts:
        return

    output = {"systemMessage": "\n\n".join(message_parts)}
    json.dump(output, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

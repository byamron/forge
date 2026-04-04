#!/usr/bin/env python3
"""Format proposals and context health into presentation-ready text.

Reads the JSON output from cache-manager.py --proposals on stdin and
produces a JSON object with pre-formatted markdown tables for the
/forge skill to display directly.

Usage:
    python3 cache-manager.py --proposals | python3 format-proposals.py
"""

import json
import sys
from typing import Any, Dict, List, Optional


def build_changes_summary(
    proposals: List[Dict[str, Any]],
    previous_proposals: Optional[List[Dict[str, Any]]],
) -> str:
    """Compare current proposals to the previous run and summarize differences.

    Returns a human-readable summary string, or empty string if no previous run.
    """
    if previous_proposals is None:
        return ""

    prev_by_id = {p["id"]: p for p in previous_proposals if "id" in p}
    curr_by_id = {p["id"]: p for p in proposals if "id" in p}

    prev_ids = set(prev_by_id.keys())
    curr_ids = set(curr_by_id.keys())

    new_ids = curr_ids - prev_ids
    removed_ids = prev_ids - curr_ids
    impact_changed = []
    for pid in curr_ids & prev_ids:
        old_impact = prev_by_id[pid].get("impact", "")
        new_impact = curr_by_id[pid].get("impact", "")
        if old_impact != new_impact:
            impact_changed.append((pid, old_impact, new_impact))

    if not new_ids and not removed_ids and not impact_changed:
        return ""

    parts = []  # type: List[str]
    if new_ids:
        parts.append("{} new proposal{}".format(
            len(new_ids), "s" if len(new_ids) != 1 else ""))
    if removed_ids:
        parts.append("{} removed".format(len(removed_ids)))
    if impact_changed:
        parts.append("{} impact-adjusted".format(len(impact_changed)))

    return "{} since last review.".format(", ".join(parts)).capitalize()


def build_calibration_notes(
    feedback_signals: Optional[Dict[str, Any]],
) -> List[str]:
    """Build user-facing notes about active feedback calibration.

    Returns a list of human-readable strings explaining which calibration
    mechanisms are currently influencing proposals.
    """
    if not feedback_signals:
        return []

    notes = []  # type: List[str]

    # Impact deflation — check category_precision for categories where
    # dismissals significantly outnumber approvals
    cat_prec = feedback_signals.get("category_precision", {})
    for category, counts in cat_prec.items():
        dismissed = counts.get("dismissed", 0)
        approved = counts.get("approved", 0)
        if dismissed >= 3 and dismissed > approved * 2:
            notes.append(
                "{} impact adjusted based on {} previous low-impact dismissals.".format(
                    category.capitalize(), dismissed
                )
            )

    # Safety gate
    safety = feedback_signals.get("safety_gate", {})
    if safety.get("triggered", False):
        notes.append(
            "Automation proposals flagged for safety review based on your feedback."
        )

    # Skip decay
    skip_counts = feedback_signals.get("skip_counts", {})
    decayed = sum(1 for count in skip_counts.values() if count >= 3)
    if decayed > 0:
        notes.append(
            "{} proposal{} auto-dismissed after being skipped 3 times.".format(
                decayed, "s" if decayed != 1 else ""
            )
        )

    return notes


def format_health_table(ctx: Dict[str, Any]) -> str:
    """Format context_health into a markdown table."""
    if not ctx:
        return ""

    rows: List[str] = []
    rows.append("| Metric           | Value | Status |")
    rows.append("|------------------|-------|--------|")

    # CLAUDE.md lines
    lines = ctx.get("claude_md_lines", 0)
    over = ctx.get("over_budget", False)
    status = "\u26a0" if over else "\u2713"
    rows.append("| CLAUDE.md lines  | {} | {} |".format(lines, status))

    # Rules
    rules = ctx.get("rules_count", 0)
    rows.append("| Rules            | {} | \u2713 |".format(rules))

    # Skills/Commands
    skills = ctx.get("skills_count", 0)
    rows.append("| Skills/Commands  | {} | \u2713 |".format(skills))

    # Hooks
    hooks = ctx.get("hooks_count", 0)
    gaps = ctx.get("gap_count", 0)
    status = "\u26a0" if hooks == 0 and gaps > 0 else "\u2713"
    rows.append("| Hooks            | {} | {} |".format(hooks, status))

    # Agents
    agents = ctx.get("agents_count", 0)
    rows.append("| Agents           | {} | \u2713 |".format(agents))

    # Stale artifacts
    stale = ctx.get("stale_artifacts_count", 0)
    status = "\u26a0" if stale > 0 else "\u2713"
    rows.append("| Stale artifacts  | {} | {} |".format(stale, status))

    # Demotion candidates
    demotions = ctx.get("demotion_candidates", 0)
    if demotions > 0:
        rows.append("| Demotion candidates | {} | \u26a0 |".format(demotions))

    # Effectiveness
    eff = ctx.get("effectiveness", {})
    if eff:
        ineffective = eff.get("ineffective", 0)
        if ineffective > 0:
            rows.append("| Ineffective artifacts | {} | \u26a0 |".format(ineffective))

    return "\n".join(rows)


def format_proposal_table(
    proposals: List[Dict[str, Any]],
    safety_gate: Optional[Dict[str, Any]] = None,
) -> str:
    """Format proposals into a numbered markdown table.

    If safety_gate is triggered, hook and agent proposals are labeled
    with a safety review marker so the user and LLM know to add approval steps.
    """
    if not proposals:
        return ""

    safety_triggered = (
        safety_gate is not None and safety_gate.get("triggered", False)
    )
    safety_types = {"hook", "agent"}

    rows: List[str] = []
    rows.append("| # | Impact | Type | Proposal | Evidence |")
    rows.append("|---|--------|------|----------|----------|")

    for i, p in enumerate(proposals, 1):
        impact = p.get("impact", "medium")
        ptype = p.get("type", "unknown")
        desc = p.get("description", "")
        evidence = p.get("evidence_summary", "")

        # Safety gate label for automation proposals
        if safety_triggered and ptype in safety_types:
            desc = "[Safety review] " + desc

        # Truncate long fields for table readability
        if len(desc) > 80:
            desc = desc[:77] + "..."
        if len(evidence) > 100:
            evidence = evidence[:97] + "..."
        rows.append("| {} | {} | {} | {} | {} |".format(
            i, impact.capitalize(), ptype, desc, evidence))

    return "\n".join(rows)


def main() -> None:
    try:
        raw = sys.stdin.read()
    except Exception as e:
        print("Error reading stdin: {}".format(e), file=sys.stderr)
        sys.exit(1)

    if not raw.strip():
        print("Error: no input on stdin", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print("Error: invalid JSON: {}".format(e), file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict):
        print("Error: expected a JSON object on stdin", file=sys.stderr)
        sys.exit(1)

    proposals = data.get("proposals", [])
    ctx_health = data.get("context_health", {})
    deep_cache = data.get("deep_analysis_cache")
    safety_gate = data.get("safety_gate")
    previous_proposals = data.get("previous_proposals")
    feedback_signals = data.get("feedback_signals")

    changes_summary = build_changes_summary(proposals, previous_proposals)
    calibration_notes = build_calibration_notes(feedback_signals)
    health_table = format_health_table(ctx_health)
    proposal_table = format_proposal_table(proposals, safety_gate=safety_gate)

    # Collect safety-flagged IDs from the formatted table
    safety_flagged_ids = []  # type: List[str]
    if safety_gate and safety_gate.get("triggered", False):
        safety_flagged_ids = [
            p.get("id", "") for p in proposals
            if p.get("type") in ("hook", "agent")
        ]

    output = {
        "health_table": health_table,
        "proposal_table": proposal_table,
        "proposal_count": len(proposals),
        "has_deep_cache": deep_cache is not None,
        "proposals": proposals,
        "safety_flagged_ids": safety_flagged_ids,
        "changes_summary": changes_summary,
        "calibration_notes": calibration_notes,
    }

    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

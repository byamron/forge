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

    safety_flagged_ids = []  # type: List[str]
    for i, p in enumerate(proposals, 1):
        impact = p.get("impact", "medium")
        ptype = p.get("type", "unknown")
        desc = p.get("description", "")
        evidence = p.get("evidence_summary", "")

        # Safety gate label for automation proposals
        if safety_triggered and ptype in safety_types:
            desc = "[Safety review] " + desc
            safety_flagged_ids.append(p.get("id", ""))

        # Truncate long fields for table readability
        if len(desc) > 60:
            desc = desc[:57] + "..."
        if len(evidence) > 60:
            evidence = evidence[:57] + "..."
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
    }

    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Review scoring diagnostics from a cached /forge analysis.

Reads the transcript analysis cache and presents:
- All detected correction themes with weighted scores and confidence
- Top contributing conversation pairs per theme
- Near-miss themes (scored just below threshold)
- Classification distribution across all pairs
- Threshold sensitivity analysis

Usage:
    python3 tests/scoring_eval/review_diagnostics.py --project-root /path/to/project
    python3 tests/scoring_eval/review_diagnostics.py --project-root . --sensitivity
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import importlib
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "forge" / "scripts"))
_pi = importlib.import_module("project_identity")
resolve_user_file = _pi.resolve_user_file


def load_cached_analysis(project_root: Path) -> Optional[dict]:
    """Load cached transcript analysis results."""
    cache_path = resolve_user_file(project_root, "cache/transcripts.cache.json")
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"Error reading cache: {e}", file=sys.stderr)
        return None


def load_cached_proposals(project_root: Path) -> Optional[dict]:
    """Load cached proposals for cross-reference."""
    proposals_path = resolve_user_file(project_root, "cache/proposals.cache.json")
    if not proposals_path.exists():
        return None
    try:
        return json.loads(proposals_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def review(project_root: Path, show_sensitivity: bool = False) -> None:
    """Print diagnostic review of the most recent analysis."""
    data = load_cached_analysis(project_root)
    if data is None:
        print("No cached transcript analysis found.", file=sys.stderr)
        print("Run `/forge` first to generate analysis data.", file=sys.stderr)
        sys.exit(1)

    out = sys.stdout

    out.write("\n=== Scoring Diagnostics ===\n\n")

    # Basic stats
    candidates = data.get("candidates", {})
    sessions_analyzed = data.get("sessions_analyzed", 0)
    out.write(f"Sessions analyzed: {sessions_analyzed}\n")
    out.write(f"Date range: {data.get('session_date_range', 'unknown')}\n\n")

    # Classification distribution from conversation_pairs_sample
    pairs_sample = data.get("conversation_pairs_sample", [])
    if pairs_sample:
        _print_classification_distribution(out, pairs_sample)

    # Correction themes
    corrections = candidates.get("corrections", [])
    if corrections:
        _print_correction_themes(out, corrections)
    else:
        out.write("No correction themes detected.\n\n")

    # Post-action patterns
    post_actions = candidates.get("post_actions", [])
    if post_actions:
        _print_post_actions(out, post_actions)

    # Repeated prompts
    repeated = candidates.get("repeated_prompts", [])
    if repeated:
        _print_repeated_prompts(out, repeated)

    # Workflow patterns
    workflows = candidates.get("workflow_patterns", [])
    if workflows:
        _print_workflow_patterns(out, workflows)

    # Threshold sensitivity
    if show_sensitivity and corrections:
        _print_sensitivity(out, corrections)

    # Cross-reference with proposals
    proposals_data = load_cached_proposals(project_root)
    if proposals_data:
        proposals = proposals_data if isinstance(proposals_data, list) else proposals_data.get("proposals", [])
        if proposals:
            _print_proposal_crossref(out, corrections, proposals)


def _print_classification_distribution(out, pairs: List[dict]) -> None:
    """Show distribution of classifications across conversation pairs."""
    counts: Dict[str, int] = {}
    strengths: List[float] = []
    for p in pairs:
        cls = p.get("classification", "unknown")
        counts[cls] = counts.get(cls, 0) + 1
        if cls == "corrective":
            strengths.append(p.get("correction_strength", 0.0))

    total = sum(counts.values())
    out.write("Classification distribution:\n")
    for cls in ["corrective", "confirmatory", "new_instruction", "followup"]:
        n = counts.get(cls, 0)
        pct = n / total * 100 if total else 0
        out.write(f"  {cls:<18}: {n:>4} ({pct:5.1f}%)\n")
    if strengths:
        avg = sum(strengths) / len(strengths)
        out.write(f"  Avg correction strength: {avg:.3f}\n")
    out.write(f"  Total pairs in sample: {total}\n\n")


def _print_correction_themes(out, corrections: List[dict]) -> None:
    """Show detected correction themes with scores and evidence."""
    out.write(f"--- Correction Themes ({len(corrections)}) ---\n\n")

    for i, theme in enumerate(corrections, 1):
        pattern = theme.get("pattern", "unknown")
        score = theme.get("score", 0.0)
        confidence = theme.get("confidence", "unknown")
        occurrences = theme.get("occurrences", 0)
        sessions = theme.get("sessions", [])
        evidence = theme.get("evidence", [])

        out.write(f"  [{i}] {pattern}\n")
        out.write(
            f"      Score: {score:.2f}  Confidence: {confidence}  "
            f"Occurrences: {occurrences}  Sessions: {len(sessions)}\n"
        )

        # Show top evidence
        for j, ev in enumerate(evidence[:3]):
            msg = ev.get("user_message", "")[:100]
            out.write(f"      Evidence {j+1}: \"{msg}\"\n")

        out.write("\n")


def _print_post_actions(out, post_actions: List[dict]) -> None:
    """Show detected post-action patterns."""
    out.write(f"--- Post-Action Patterns ({len(post_actions)}) ---\n\n")
    for pa in post_actions:
        cmd = pa.get("command", "unknown")
        count = pa.get("count", 0)
        sessions = len(pa.get("sessions", []))
        confidence = pa.get("confidence", "unknown")
        out.write(f"  {cmd}: {count} occurrences across {sessions} sessions ({confidence})\n")
    out.write("\n")


def _print_repeated_prompts(out, repeated: List[dict]) -> None:
    """Show detected repeated opening prompts."""
    out.write(f"--- Repeated Prompts ({len(repeated)}) ---\n\n")
    for rp in repeated:
        pattern = rp.get("pattern", rp.get("representative", "unknown"))
        count = rp.get("occurrences", 0)
        sessions = len(rp.get("sessions", []))
        out.write(f"  \"{str(pattern)[:80]}\": {count} times across {sessions} sessions\n")
    out.write("\n")


def _print_workflow_patterns(out, workflows: List[dict]) -> None:
    """Show detected workflow patterns."""
    out.write(f"--- Workflow Patterns ({len(workflows)}) ---\n\n")
    for wf in workflows:
        name = wf.get("name", "unknown")
        phases = wf.get("phases", wf.get("sequence", []))
        sessions = len(wf.get("sessions", []))
        out.write(f"  {name}: {' → '.join(phases)} ({sessions} sessions)\n")
    out.write("\n")


def _print_sensitivity(out, corrections: List[dict]) -> None:
    """Show what would change at different confidence thresholds."""
    out.write("--- Threshold Sensitivity ---\n\n")

    scores = [(c.get("score", 0), c.get("pattern", "?")) for c in corrections]
    scores.sort(key=lambda x: x[0], reverse=True)

    test_thresholds = [2.0, 3.0, 4.0, 5.0, 6.0, 8.0]

    out.write(f"  {'Threshold':>10}  {'Themes above':>14}  {'Would change':>14}\n")
    out.write("  " + "-" * 42 + "\n")

    # Default thresholds: medium=3.0, high=6.0
    for thresh in test_thresholds:
        above = sum(1 for s, _ in scores if s >= thresh)
        marker = ""
        if thresh == 3.0:
            marker = " ← medium default"
        elif thresh == 6.0:
            marker = " ← high default"
        out.write(f"  {thresh:>10.1f}  {above:>14d}{marker}\n")

    out.write("\n  Near-miss themes (score 2.0-3.0):\n")
    for score, pattern in scores:
        if 2.0 <= score < 3.0:
            out.write(f"    {score:.2f}: {pattern}\n")
    out.write("\n")


def _print_proposal_crossref(
    out, corrections: List[dict], proposals: List[dict]
) -> None:
    """Show which correction themes became proposals and which didn't."""
    out.write("--- Proposal Cross-Reference ---\n\n")

    # Corrections that became proposals
    correction_proposals = [
        p for p in proposals if p.get("source_type") in ("correction", "corrections")
    ]
    out.write(f"  Correction themes: {len(corrections)}\n")
    out.write(f"  Became proposals:  {len(correction_proposals)}\n")

    # Themes that didn't become proposals (filtered by thresholds or dedup)
    if len(corrections) > len(correction_proposals):
        out.write(f"  Filtered out:      {len(corrections) - len(correction_proposals)}\n")
        out.write("  (Check build-proposals.py thresholds and dedup logic)\n")
    out.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Review scoring diagnostics from cached analysis"
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root directory (default: cwd)",
    )
    parser.add_argument(
        "--sensitivity",
        action="store_true",
        help="Show threshold sensitivity analysis",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw cached data as JSON instead of report",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()

    if args.json:
        data = load_cached_analysis(project_root)
        if data:
            json.dump(data, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print("No cached data found.", file=sys.stderr)
            sys.exit(1)
    else:
        review(project_root, show_sensitivity=args.sensitivity)


if __name__ == "__main__":
    main()

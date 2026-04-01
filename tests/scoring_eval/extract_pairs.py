#!/usr/bin/env python3
"""Extract conversation pairs from real JSONL transcripts for labeling.

Reads session transcripts for the current project and outputs assistant→user
conversation pairs in a human-reviewable JSON format suitable for ground-truth
labeling.

Usage:
    python3 tests/scoring_eval/extract_pairs.py --project-root /path/to/project
    python3 tests/scoring_eval/extract_pairs.py --project-root . --max-sessions 10
    python3 tests/scoring_eval/extract_pairs.py --project-root . --output pairs.json

Output goes to stdout as JSON by default, or to --output file.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List

# Add scripts to path for imports — module has hyphens so we use importlib
import importlib
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "forge" / "scripts"))
_at = importlib.import_module("analyze-transcripts")

build_conversation_pairs = _at.build_conversation_pairs
classify_response = _at.classify_response
find_all_project_session_dirs = _at.find_all_project_session_dirs
load_sessions = _at.load_sessions
_sanitize_text = _at._sanitize_text


def extract_pairs_for_labeling(
    project_root: Path,
    max_sessions: int = 20,
    max_pairs: int = 200,
) -> dict:
    """Extract conversation pairs in a format ready for human labeling.

    Returns a dict matching the labeled data format from the README, but with
    label/severity/notes fields set to empty strings for the human to fill in.
    Also includes the classifier's prediction so reviewers can compare.
    """
    session_dirs = find_all_project_session_dirs(project_root)
    if not session_dirs:
        return {
            "project": project_root.name,
            "extraction_date": "",
            "error": "No session directories found",
            "pairs": [],
        }

    sessions = load_sessions(session_dirs, max_sessions)
    if not sessions:
        return {
            "project": project_root.name,
            "extraction_date": "",
            "error": "No sessions with messages found",
            "pairs": [],
        }

    all_pairs = build_conversation_pairs(sessions)

    # Build reviewable output
    labeled_pairs: List[dict] = []
    for i, pair in enumerate(all_pairs[:max_pairs]):
        labeled_pairs.append({
            "id": f"pair_{i + 1:03d}",
            "session_id": pair["session_id"],
            "turn_index": pair["turn_index"],
            "user_text": pair["user_text"],
            "assistant_text": pair["assistant_text"][:300],
            "assistant_tools": pair["assistant_tools"],
            "assistant_files": pair["assistant_files"],
            # Classifier prediction (for comparison during labeling)
            "predicted_label": pair["classification"],
            "predicted_strength": round(pair["correction_strength"], 3),
            # Human labels (to be filled in)
            "label": "",
            "severity": "",
            "notes": "",
        })

    import datetime

    return {
        "project": project_root.name,
        "extraction_date": datetime.date.today().isoformat(),
        "sessions_analyzed": len(sessions),
        "total_pairs_found": len(all_pairs),
        "pairs_included": len(labeled_pairs),
        "classifier_summary": _summarize_predictions(all_pairs),
        "pairs": labeled_pairs,
    }


def _summarize_predictions(pairs: List[dict]) -> dict:
    """Summarize classifier predictions across all pairs."""
    counts = {"corrective": 0, "confirmatory": 0, "new_instruction": 0, "followup": 0}
    strengths: List[float] = []

    for p in pairs:
        cls = p.get("classification", "followup")
        counts[cls] = counts.get(cls, 0) + 1
        if cls == "corrective":
            strengths.append(p.get("correction_strength", 0.0))

    return {
        "total_pairs": len(pairs),
        "classification_distribution": counts,
        "corrective_avg_strength": round(
            sum(strengths) / len(strengths), 3
        ) if strengths else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract conversation pairs for labeling"
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root directory (default: cwd)",
    )
    parser.add_argument(
        "--max-sessions",
        type=int,
        default=20,
        help="Maximum sessions to analyze (default: 20)",
    )
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=200,
        help="Maximum pairs to include (default: 200)",
    )
    parser.add_argument(
        "--output",
        help="Output file path (default: stdout)",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    result = extract_pairs_for_labeling(
        project_root,
        max_sessions=args.max_sessions,
        max_pairs=args.max_pairs,
    )

    output_json = json.dumps(result, indent=2) + "\n"

    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(
            f"Wrote {len(result['pairs'])} pairs to {args.output}",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(output_json)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Evaluate the correction classifier against labeled ground-truth data.

Reads labeled JSON files and runs classify_response() on each pair, comparing
predicted labels against human-assigned ground truth. Reports precision, recall,
F1, and lists specific false positives and false negatives.

Usage:
    python3 tests/scoring_eval/eval_classifier.py tests/scoring_eval/labeled/my_project_pairs.json
    python3 tests/scoring_eval/eval_classifier.py tests/scoring_eval/labeled/*.json
    python3 tests/scoring_eval/eval_classifier.py tests/scoring_eval/labeled/ --verbose
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import importlib
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "forge" / "scripts"))
_at = importlib.import_module("analyze-transcripts")
classify_response = _at.classify_response


def load_labeled_data(paths: List[str]) -> List[dict]:
    """Load labeled pairs from one or more JSON files or directories."""
    all_pairs: List[dict] = []

    for p in paths:
        path = Path(p)
        if path.is_dir():
            files = sorted(path.glob("*.json"))
        else:
            files = [path]

        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                print(f"Warning: skipping {f}: {e}", file=sys.stderr)
                continue

            pairs = data.get("pairs", [])
            for pair in pairs:
                if not pair.get("label"):
                    continue  # Skip unlabeled pairs
                pair["_source_file"] = str(f)
                all_pairs.append(pair)

    return all_pairs


def evaluate(
    pairs: List[dict], verbose: bool = False
) -> dict:
    """Run classifier on all labeled pairs and compute metrics."""
    # Per-class tracking
    classes = ["corrective", "confirmatory", "new_instruction", "followup"]
    true_positives: Dict[str, int] = {c: 0 for c in classes}
    false_positives: Dict[str, int] = {c: 0 for c in classes}
    false_negatives: Dict[str, int] = {c: 0 for c in classes}

    errors: List[dict] = []
    severity_data: List[Tuple[float, str]] = []  # (predicted_strength, true_severity)

    for pair in pairs:
        true_label = pair["label"]
        true_severity = pair.get("severity", "")

        # Build tool list in the format classify_response expects
        tools = [{"name": t} for t in pair.get("assistant_tools", [])]
        files = pair.get("assistant_files", [])

        pred_label, pred_strength = classify_response(
            pair["user_text"],
            pair.get("assistant_text", ""),
            tools,
            files,
        )

        if pred_label == true_label:
            true_positives[true_label] += 1
            if true_label == "corrective" and true_severity:
                severity_data.append((pred_strength, true_severity))
        else:
            false_positives[pred_label] += 1
            false_negatives[true_label] += 1
            errors.append({
                "id": pair.get("id", "?"),
                "true_label": true_label,
                "predicted_label": pred_label,
                "predicted_strength": round(pred_strength, 3),
                "user_text": pair["user_text"][:120],
                "source": pair.get("_source_file", ""),
            })

    # Compute per-class metrics
    metrics: Dict[str, dict] = {}
    for c in classes:
        tp = true_positives[c]
        fp = false_positives[c]
        fn = false_negatives[c]
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        metrics[c] = {
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "support": tp + fn,  # total true instances
        }

    # Severity calibration
    severity_calibration = _compute_severity_calibration(severity_data)

    # Overall accuracy
    total = sum(true_positives.values())
    total_pairs = len(pairs)
    accuracy = total / total_pairs if total_pairs > 0 else 0.0

    result = {
        "total_labeled_pairs": total_pairs,
        "overall_accuracy": round(accuracy, 3),
        "per_class_metrics": metrics,
        "severity_calibration": severity_calibration,
        "error_count": len(errors),
    }

    if verbose:
        result["errors"] = errors

    # Print human-readable report
    _print_report(result, errors if verbose else [])

    return result


def _compute_severity_calibration(
    data: List[Tuple[float, str]],
) -> dict:
    """Check if predicted strength correlates with labeled severity."""
    if not data:
        return {"note": "No severity data (no correctly classified corrective pairs)"}

    by_severity: Dict[str, List[float]] = {"strong": [], "moderate": [], "mild": []}
    for strength, severity in data:
        if severity in by_severity:
            by_severity[severity].append(strength)

    calibration = {}
    for sev, strengths in by_severity.items():
        if strengths:
            calibration[sev] = {
                "count": len(strengths),
                "avg_strength": round(sum(strengths) / len(strengths), 3),
                "min_strength": round(min(strengths), 3),
                "max_strength": round(max(strengths), 3),
            }

    # Check monotonicity: strong > moderate > mild
    avgs = {
        s: calibration[s]["avg_strength"]
        for s in ["strong", "moderate", "mild"]
        if s in calibration
    }
    if len(avgs) >= 2:
        ordered = list(avgs.values())
        calibration["monotonic"] = all(
            ordered[i] >= ordered[i + 1] for i in range(len(ordered) - 1)
        )

    return calibration


def _print_report(result: dict, errors: List[dict]) -> None:
    """Print a human-readable evaluation report to stderr."""
    out = sys.stderr

    out.write("\n=== Correction Classifier Evaluation ===\n\n")
    out.write(f"Total labeled pairs: {result['total_labeled_pairs']}\n")
    out.write(f"Overall accuracy: {result['overall_accuracy']:.1%}\n\n")

    # Per-class table
    out.write(f"{'Class':<18} {'Prec':>6} {'Recall':>7} {'F1':>6} {'Support':>8}\n")
    out.write("-" * 50 + "\n")
    for cls, m in result["per_class_metrics"].items():
        out.write(
            f"{cls:<18} {m['precision']:>6.1%} {m['recall']:>7.1%} "
            f"{m['f1']:>6.3f} {m['support']:>8d}\n"
        )

    # Targets
    out.write("\n")
    corr = result["per_class_metrics"].get("corrective", {})
    prec = corr.get("precision", 0)
    recall = corr.get("recall", 0)
    out.write(f"Correction precision: {prec:.1%} (target: >80%)")
    out.write(" ✓\n" if prec >= 0.8 else " ✗\n")
    out.write(f"Correction recall:    {recall:.1%} (target: >70%)")
    out.write(" ✓\n" if recall >= 0.7 else " ✗\n")

    # Severity calibration
    cal = result.get("severity_calibration", {})
    if cal and cal.get("note") is None:
        out.write("\nSeverity calibration (avg predicted strength):\n")
        for sev in ["strong", "moderate", "mild"]:
            if sev in cal:
                out.write(
                    f"  {sev:<10}: {cal[sev]['avg_strength']:.3f} "
                    f"(n={cal[sev]['count']})\n"
                )
        if "monotonic" in cal:
            out.write(
                f"  Monotonic (strong > moderate > mild): "
                f"{'yes' if cal['monotonic'] else 'NO'}\n"
            )

    # Errors
    if errors:
        out.write(f"\n--- Misclassifications ({len(errors)}) ---\n\n")
        for e in errors:
            out.write(
                f"  [{e['id']}] true={e['true_label']}, "
                f"pred={e['predicted_label']} "
                f"(strength={e['predicted_strength']})\n"
            )
            out.write(f"    \"{e['user_text']}\"\n\n")

    out.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate correction classifier against labeled data"
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Labeled JSON files or directories to evaluate",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show individual misclassifications",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON to stdout",
    )
    args = parser.parse_args()

    pairs = load_labeled_data(args.paths)
    if not pairs:
        print("No labeled pairs found. Label some pairs first.", file=sys.stderr)
        print("See tests/scoring_eval/labeled/README.md for format.", file=sys.stderr)
        sys.exit(1)

    result = evaluate(pairs, verbose=args.verbose)

    if args.json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()

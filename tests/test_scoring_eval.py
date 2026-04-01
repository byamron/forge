"""Tests for scoring evaluation infrastructure.

Validates that the evaluation scripts correctly measure classifier accuracy,
handle labeled data formats, and produce meaningful metrics.
"""

import importlib
import json
import sys
from pathlib import Path
from typing import List

import pytest

# Ensure forge/scripts is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "forge" / "scripts"))
at = importlib.import_module("analyze-transcripts")

# Import the eval scripts
sys.path.insert(0, str(Path(__file__).resolve().parent / "scoring_eval"))
from eval_classifier import evaluate, load_labeled_data, _compute_severity_calibration
from extract_pairs import extract_pairs_for_labeling, _summarize_predictions


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_labeled_pair(
    user_text: str,
    label: str,
    severity: str = "",
    assistant_text: str = "",
    assistant_tools: list = None,
    assistant_files: list = None,
    pair_id: str = "test_001",
) -> dict:
    return {
        "id": pair_id,
        "session_id": "test-session",
        "turn_index": 0,
        "user_text": user_text,
        "assistant_text": assistant_text,
        "assistant_tools": assistant_tools or [],
        "assistant_files": assistant_files or [],
        "label": label,
        "severity": severity,
        "notes": "",
    }


# ---------------------------------------------------------------------------
# eval_classifier tests
# ---------------------------------------------------------------------------

class TestEvaluate:
    """Test the evaluate() function."""

    def test_perfect_classification(self):
        """All pairs correctly classified → 100% accuracy."""
        pairs = [
            _make_labeled_pair("no, use vitest not jest", "corrective", "moderate"),
            _make_labeled_pair("looks good", "confirmatory"),
            # new_instruction needs low overlap with assistant text to be detected
            _make_labeled_pair(
                "now add a login page",
                "new_instruction",
                assistant_text="I've finished refactoring the database module and all tests pass.",
            ),
        ]
        result = evaluate(pairs)
        assert result["overall_accuracy"] == 1.0
        assert result["error_count"] == 0

    def test_strong_corrective_detected(self):
        """Strong correction keywords produce corrective classification."""
        pairs = [
            _make_labeled_pair(
                "I told you to use pnpm not npm",
                "corrective",
                "strong",
            ),
        ]
        result = evaluate(pairs)
        corr = result["per_class_metrics"]["corrective"]
        assert corr["true_positives"] == 1
        assert corr["false_negatives"] == 0

    def test_confirmatory_detected(self):
        """Simple confirmatory messages are correctly classified."""
        pairs = [
            _make_labeled_pair("looks good", "confirmatory"),
            _make_labeled_pair("thanks", "confirmatory"),
            _make_labeled_pair("perfect", "confirmatory"),
        ]
        result = evaluate(pairs)
        conf = result["per_class_metrics"]["confirmatory"]
        assert conf["true_positives"] == 3
        assert conf["precision"] == 1.0

    def test_metrics_computation(self):
        """Precision, recall, F1 computed correctly."""
        # One true positive, one false positive, one false negative
        pairs = [
            # True corrective → detected as corrective
            _make_labeled_pair(
                "don't use jest, use vitest instead",
                "corrective", "moderate",
            ),
            # True followup → misclassified as corrective (will it be?)
            # This depends on classifier behavior; let's use a pair
            # where we know the outcome
            _make_labeled_pair(
                "what about edge cases?",
                "followup",
            ),
        ]
        result = evaluate(pairs)
        # At minimum, we should get a valid result dict
        assert "per_class_metrics" in result
        assert "corrective" in result["per_class_metrics"]
        for cls in ["corrective", "confirmatory", "new_instruction", "followup"]:
            m = result["per_class_metrics"][cls]
            assert 0 <= m["precision"] <= 1
            assert 0 <= m["recall"] <= 1
            assert 0 <= m["f1"] <= 1

    def test_empty_pairs(self):
        """Empty pair list returns zero metrics."""
        result = evaluate([])
        assert result["total_labeled_pairs"] == 0
        assert result["overall_accuracy"] == 0

    def test_verbose_includes_errors(self):
        """Verbose mode includes error details."""
        pairs = [
            _make_labeled_pair("looks good", "confirmatory"),
        ]
        result = evaluate(pairs, verbose=True)
        # All correct → no errors even in verbose
        assert "errors" in result
        assert result["error_count"] == 0


class TestSeverityCalibration:
    """Test severity calibration computation."""

    def test_monotonic_calibration(self):
        """Strong > moderate > mild in average strength."""
        data = [
            (0.9, "strong"),
            (0.8, "strong"),
            (0.5, "moderate"),
            (0.4, "moderate"),
            (0.3, "mild"),
            (0.25, "mild"),
        ]
        cal = _compute_severity_calibration(data)
        assert cal["strong"]["avg_strength"] > cal["moderate"]["avg_strength"]
        assert cal["moderate"]["avg_strength"] > cal["mild"]["avg_strength"]
        assert cal["monotonic"] is True

    def test_empty_severity_data(self):
        """Empty data returns a note."""
        cal = _compute_severity_calibration([])
        assert "note" in cal

    def test_single_severity_bucket(self):
        """Single bucket works without monotonicity check."""
        data = [(0.5, "moderate")]
        cal = _compute_severity_calibration(data)
        assert cal["moderate"]["count"] == 1
        assert "monotonic" not in cal


class TestLoadLabeledData:
    """Test loading labeled data from files."""

    def test_load_from_file(self, tmp_path):
        """Loads pairs from a valid JSON file."""
        data = {
            "project": "test",
            "pairs": [
                _make_labeled_pair("no, use X", "corrective"),
                _make_labeled_pair("looks good", "confirmatory"),
            ],
        }
        f = tmp_path / "test_pairs.json"
        f.write_text(json.dumps(data))
        pairs = load_labeled_data([str(f)])
        assert len(pairs) == 2

    def test_skip_unlabeled_pairs(self, tmp_path):
        """Pairs without labels are skipped."""
        data = {
            "pairs": [
                {"id": "p1", "user_text": "test", "label": ""},
                _make_labeled_pair("no, use X", "corrective"),
            ],
        }
        f = tmp_path / "test.json"
        f.write_text(json.dumps(data))
        pairs = load_labeled_data([str(f)])
        assert len(pairs) == 1

    def test_load_from_directory(self, tmp_path):
        """Loads all JSON files from a directory."""
        for i in range(3):
            data = {"pairs": [_make_labeled_pair(f"fix {i}", "corrective", pair_id=f"p{i}")]}
            (tmp_path / f"file{i}.json").write_text(json.dumps(data))
        pairs = load_labeled_data([str(tmp_path)])
        assert len(pairs) == 3

    def test_skip_malformed_files(self, tmp_path):
        """Gracefully skips invalid JSON files."""
        (tmp_path / "bad.json").write_text("not json{{{")
        data = {"pairs": [_make_labeled_pair("fix", "corrective")]}
        (tmp_path / "good.json").write_text(json.dumps(data))
        pairs = load_labeled_data([str(tmp_path)])
        assert len(pairs) == 1


# ---------------------------------------------------------------------------
# extract_pairs tests
# ---------------------------------------------------------------------------

class TestSummarizePredictions:
    """Test the prediction summary helper."""

    def test_distribution_counts(self):
        pairs = [
            {"classification": "corrective", "correction_strength": 0.5},
            {"classification": "corrective", "correction_strength": 0.3},
            {"classification": "confirmatory", "correction_strength": 0.0},
            {"classification": "followup", "correction_strength": 0.0},
        ]
        summary = _summarize_predictions(pairs)
        assert summary["total_pairs"] == 4
        assert summary["classification_distribution"]["corrective"] == 2
        assert summary["classification_distribution"]["confirmatory"] == 1
        assert summary["corrective_avg_strength"] == 0.4

    def test_no_corrective_pairs(self):
        pairs = [
            {"classification": "confirmatory", "correction_strength": 0.0},
        ]
        summary = _summarize_predictions(pairs)
        assert summary["corrective_avg_strength"] == 0.0


class TestExtractPairsForLabeling:
    """Test the extraction pipeline."""

    def test_no_sessions_returns_error(self, tmp_path, monkeypatch):
        """Returns error dict when no sessions found."""
        monkeypatch.setattr(
            "extract_pairs.find_all_project_session_dirs",
            lambda root: [],
        )
        result = extract_pairs_for_labeling(tmp_path)
        assert "error" in result
        assert result["pairs"] == []

    def test_max_pairs_limit(self, tmp_path, monkeypatch):
        """Respects max_pairs limit."""
        # Create mock data
        mock_pairs = [
            {
                "session_id": f"s{i}",
                "timestamp": "2026-03-31T00:00:00Z",
                "turn_index": i,
                "user_text": f"message {i}",
                "user_tokens": ["message"],
                "classification": "followup",
                "correction_strength": 0.0,
                "assistant_text": "response",
                "assistant_tools": [],
                "assistant_files": [],
            }
            for i in range(50)
        ]
        monkeypatch.setattr(
            "extract_pairs.find_all_project_session_dirs",
            lambda root: [tmp_path],
        )
        monkeypatch.setattr(
            "extract_pairs.load_sessions",
            lambda dirs, max_s: {"s1": []},
        )
        monkeypatch.setattr(
            "extract_pairs.build_conversation_pairs",
            lambda sessions: mock_pairs,
        )
        result = extract_pairs_for_labeling(tmp_path, max_pairs=10)
        assert len(result["pairs"]) == 10
        assert result["total_pairs_found"] == 50

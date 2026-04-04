"""Tests for the proposal feedback loop system.

Covers: feedback signal recording (finalize-proposals.py), impact calibration
and skip decay (build-proposals.py), safety gate labels (format-proposals.py),
and per-category precision (analyze-transcripts.py).
"""
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "forge" / "scripts"))
fp = importlib.import_module("finalize-proposals")
bp = importlib.import_module("build-proposals")
fmt = importlib.import_module("format-proposals")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stats(feedback_signals: Dict = None) -> Dict:
    """Build a minimal analyzer-stats.json structure."""
    stats = {
        "version": 2,
        "corrections": {"proposed": 0, "approved": 0, "dismissed": 0},
        "post_actions": {"proposed": 0, "approved": 0, "dismissed": 0},
        "repeated_prompts": {"proposed": 0, "approved": 0, "dismissed": 0},
        "theme_outcomes": {},
        "suppressed_themes": [],
    }
    if feedback_signals:
        stats["feedback_signals"] = feedback_signals
    return stats


def _make_outcomes(*entries) -> List[Dict]:
    """Shorthand for building outcome arrays."""
    return list(entries)


# ---------------------------------------------------------------------------
# TestFeedbackSignalRecording — finalize-proposals.py
# ---------------------------------------------------------------------------

class TestFeedbackSignalRecording:
    """Verify _update_feedback_signals records all signal types correctly."""

    def test_dismissed_with_reason_stored(self):
        stats = _make_stats()
        outcomes = [
            {"id": "x", "status": "dismissed", "type": "hook", "reason": "low_impact"},
        ]
        fp._update_feedback_signals(stats, outcomes)
        fs = stats["feedback_signals"]
        assert fs["category_precision"]["hook"]["dismissed"] == 1
        assert fs["dismissal_reasons"]["hook"]["low_impact"] == 1

    def test_missing_reason_defaults_to_unspecified(self):
        stats = _make_stats()
        outcomes = [
            {"id": "x", "status": "dismissed", "type": "rule"},
        ]
        fp._update_feedback_signals(stats, outcomes)
        fs = stats["feedback_signals"]
        assert fs["dismissal_reasons"]["rule"]["unspecified"] == 1

    def test_invalid_reason_defaults_to_unspecified(self):
        stats = _make_stats()
        outcomes = [
            {"id": "x", "status": "dismissed", "type": "hook", "reason": "bad_value"},
        ]
        fp._update_feedback_signals(stats, outcomes)
        assert stats["feedback_signals"]["dismissal_reasons"]["hook"]["unspecified"] == 1

    def test_modification_type_aggregated(self):
        stats = _make_stats()
        outcomes = [
            {"id": "x", "status": "applied", "type": "hook",
             "modification_type": "added_approval_gate"},
        ]
        fp._update_feedback_signals(stats, outcomes)
        fs = stats["feedback_signals"]
        assert fs["modification_signals"]["hook"]["added_approval_gate"] == 1
        assert fs["category_precision"]["hook"]["approved"] == 1

    def test_applied_without_modification_no_signal(self):
        stats = _make_stats()
        outcomes = [
            {"id": "x", "status": "applied", "type": "rule"},
        ]
        fp._update_feedback_signals(stats, outcomes)
        fs = stats["feedback_signals"]
        assert fs["modification_signals"] == {}
        assert fs["category_precision"]["rule"]["approved"] == 1

    def test_skip_increments_counter(self):
        stats = _make_stats()
        outcomes = [
            {"id": "my-proposal", "status": "pending", "type": "skill"},
        ]
        fp._update_feedback_signals(stats, outcomes)
        assert stats["feedback_signals"]["skip_counts"]["my-proposal"] == 1

    def test_skip_accumulates(self):
        stats = _make_stats({"skip_counts": {"my-proposal": 2}})
        outcomes = [
            {"id": "my-proposal", "status": "pending", "type": "skill"},
        ]
        fp._update_feedback_signals(stats, outcomes)
        assert stats["feedback_signals"]["skip_counts"]["my-proposal"] == 3

    def test_skip_cleaned_on_dismiss(self):
        """Dismissing a proposal removes its skip count."""
        stats = _make_stats({"skip_counts": {"old-proposal": 2}})
        outcomes = [
            {"id": "old-proposal", "status": "dismissed", "type": "hook",
             "reason": "low_impact"},
        ]
        fp._update_feedback_signals(stats, outcomes)
        assert "old-proposal" not in stats["feedback_signals"]["skip_counts"]

    def test_skip_cleaned_on_apply(self):
        """Applying a proposal removes its skip count."""
        stats = _make_stats({"skip_counts": {"my-skill": 1}})
        outcomes = [
            {"id": "my-skill", "status": "applied", "type": "skill"},
        ]
        fp._update_feedback_signals(stats, outcomes)
        assert "my-skill" not in stats["feedback_signals"]["skip_counts"]

    def test_safety_gate_triggers_at_threshold(self):
        stats = _make_stats({
            "dismissal_reasons": {
                "hook": {"missing_safety": 2},
            },
            "modification_signals": {},
        })
        # Add one more missing_safety → total = 3 → triggers
        outcomes = [
            {"id": "y", "status": "dismissed", "type": "hook", "reason": "missing_safety"},
        ]
        fp._update_feedback_signals(stats, outcomes)
        sg = stats["feedback_signals"]["safety_gate"]
        assert sg["triggered"] is True
        assert sg["signal_count"] == 3

    def test_safety_gate_not_triggered_below_threshold(self):
        stats = _make_stats()
        outcomes = [
            {"id": "a", "status": "dismissed", "type": "hook", "reason": "missing_safety"},
        ]
        fp._update_feedback_signals(stats, outcomes)
        assert stats["feedback_signals"]["safety_gate"]["triggered"] is False

    def test_safety_gate_counts_modification_signals(self):
        """added_approval_gate modifications count toward safety gate."""
        stats = _make_stats({
            "dismissal_reasons": {"hook": {"missing_safety": 1}},
            "modification_signals": {"hook": {"added_approval_gate": 1}},
        })
        outcomes = [
            {"id": "z", "status": "applied", "type": "agent",
             "modification_type": "added_approval_gate"},
        ]
        fp._update_feedback_signals(stats, outcomes)
        sg = stats["feedback_signals"]["safety_gate"]
        assert sg["signal_count"] == 3  # 1 missing_safety + 1 old gate + 1 new gate
        assert sg["triggered"] is True

    def test_version_1_stats_upgraded_gracefully(self):
        stats = {
            "version": 1,
            "corrections": {"proposed": 0, "approved": 5, "dismissed": 2},
            "theme_outcomes": {},
            "suppressed_themes": [],
        }
        fp._update_feedback_signals(stats, [])
        assert "feedback_signals" in stats
        assert "category_precision" in stats["feedback_signals"]

    def test_record_dismissed_includes_reason(self, tmp_path):
        """_record_dismissed stores reason in dismissed.json entries."""
        project = tmp_path / "project"
        project.mkdir()
        dismissed = [{"id": "x", "type": "hook", "reason": "missing_safety"}]
        with patch.object(fp, "get_user_data_dir", return_value=tmp_path):
            fp._record_dismissed(project, dismissed)
        data = json.loads((tmp_path / "dismissed.json").read_text())
        assert data[0]["reason"] == "missing_safety"

    def test_record_dismissed_no_reason(self, tmp_path):
        """_record_dismissed omits reason when not provided."""
        project = tmp_path / "project"
        project.mkdir()
        dismissed = [{"id": "x", "type": "rule"}]
        with patch.object(fp, "get_user_data_dir", return_value=tmp_path):
            fp._record_dismissed(project, dismissed)
        data = json.loads((tmp_path / "dismissed.json").read_text())
        assert "reason" not in data[0]

    def test_record_applied_tracking_rule(self, tmp_path):
        """Rule proposals get correction tracking via TYPE_TO_CATEGORY."""
        project = tmp_path / "project"
        project.mkdir()
        (tmp_path / "history").mkdir(parents=True, exist_ok=True)
        applied = [{"id": "fix-imports", "type": "rule"}]
        all_proposals = [{"id": "fix-imports", "type": "rule",
                          "description": "Fix imports", "evidence_summary": "3x"}]
        with patch.object(fp, "get_user_data_dir", return_value=tmp_path):
            fp._record_applied(project, applied, all_proposals)
        data = json.loads((tmp_path / "history" / "applied.json").read_text())
        assert data[0]["tracking"]["source"] == "correction"

    def test_record_applied_tracking_hook(self, tmp_path):
        """Hook proposals get post_action tracking via TYPE_TO_CATEGORY."""
        project = tmp_path / "project"
        project.mkdir()
        (tmp_path / "history").mkdir(parents=True, exist_ok=True)
        applied = [{"id": "auto-lint", "type": "hook"}]
        all_proposals = [{"id": "auto-lint", "type": "hook",
                          "description": "Lint hook", "evidence_summary": "5x"}]
        with patch.object(fp, "get_user_data_dir", return_value=tmp_path):
            fp._record_applied(project, applied, all_proposals)
        data = json.loads((tmp_path / "history" / "applied.json").read_text())
        assert data[0]["tracking"]["source"] == "post_action"

    def test_record_applied_tracking_skill(self, tmp_path):
        """Skill proposals get repeated_prompt tracking via TYPE_TO_CATEGORY."""
        project = tmp_path / "project"
        project.mkdir()
        (tmp_path / "history").mkdir(parents=True, exist_ok=True)
        applied = [{"id": "deploy-skill", "type": "skill"}]
        all_proposals = [{"id": "deploy-skill", "type": "skill",
                          "description": "Deploy", "evidence_summary": "9x"}]
        with patch.object(fp, "get_user_data_dir", return_value=tmp_path):
            fp._record_applied(project, applied, all_proposals)
        data = json.loads((tmp_path / "history" / "applied.json").read_text())
        assert data[0]["tracking"]["source"] == "repeated_prompt"


# ---------------------------------------------------------------------------
# TestImpactCalibration — build-proposals.py
# ---------------------------------------------------------------------------

class TestImpactCalibration:
    """Verify feedback-driven impact score deflation."""

    def test_high_low_impact_ratio_deflates(self):
        """When >40% of hook dismissals cite low_impact, high → medium."""
        fs = {
            "dismissal_reasons": {
                "hook": {"low_impact": 3, "missing_safety": 1, "not_relevant": 1},
            },
        }
        proposals = [
            {"id": "a", "type": "hook", "impact": "high"},
            {"id": "b", "type": "rule", "impact": "high"},
        ]
        bp._apply_impact_calibration(proposals, fs)
        assert proposals[0]["impact"] == "medium"  # hook deflated
        assert proposals[1]["impact"] == "high"  # rule unaffected

    def test_no_feedback_no_deflation(self):
        proposals = [{"id": "a", "type": "hook", "impact": "high"}]
        bp._apply_impact_calibration(proposals, None)
        assert proposals[0]["impact"] == "high"

    def test_empty_feedback_no_deflation(self):
        proposals = [{"id": "a", "type": "hook", "impact": "high"}]
        bp._apply_impact_calibration(proposals, {})
        assert proposals[0]["impact"] == "high"

    def test_insufficient_data_no_deflation(self):
        """Need >= 3 dismissals before calibrating."""
        fs = {
            "dismissal_reasons": {
                "hook": {"low_impact": 2},  # Only 2 — not enough
            },
        }
        proposals = [{"id": "a", "type": "hook", "impact": "high"}]
        bp._apply_impact_calibration(proposals, fs)
        assert proposals[0]["impact"] == "high"

    def test_per_category_independence(self):
        """Hooks deflated but rules unaffected when only hooks have bad ratio."""
        fs = {
            "dismissal_reasons": {
                "hook": {"low_impact": 4, "not_relevant": 1},
                "rule": {"low_impact": 0, "not_relevant": 3},
            },
        }
        proposals = [
            {"id": "a", "type": "hook", "impact": "high"},
            {"id": "b", "type": "rule", "impact": "high"},
        ]
        bp._apply_impact_calibration(proposals, fs)
        assert proposals[0]["impact"] == "medium"  # hook: 80% low_impact
        assert proposals[1]["impact"] == "high"  # rule: 0% low_impact

    def test_medium_impact_not_deflated(self):
        """Only 'high' is deflated, not 'medium'."""
        fs = {
            "dismissal_reasons": {
                "hook": {"low_impact": 5},
            },
        }
        proposals = [{"id": "a", "type": "hook", "impact": "medium"}]
        bp._apply_impact_calibration(proposals, fs)
        assert proposals[0]["impact"] == "medium"

    def test_calibration_integrated_in_build_proposals(self):
        """build_proposals applies calibration when feedback_signals provided."""
        transcripts = {
            "candidates": {
                "repeated_prompts": [{
                    "canonical_text": "deploy to staging",
                    "total_occurrences": 10,
                    "session_count": 7,
                    "example_messages": ["deploy"],
                }],
                "corrections": [],
            },
        }
        config = {"existing_skills": [], "existing_agents": [], "existing_hooks": []}

        # Without feedback: high impact
        result1 = bp.build_proposals(config, transcripts, {}, [], [])
        skills1 = [p for p in result1["proposals"] if p["type"] == "skill"]
        assert skills1[0]["impact"] == "high"

        # With feedback showing 100% low_impact for skills
        fs = {"dismissal_reasons": {"skill": {"low_impact": 5}}}
        result2 = bp.build_proposals(config, transcripts, {}, [], [],
                                     feedback_signals=fs)
        skills2 = [p for p in result2["proposals"] if p["type"] == "skill"]
        assert skills2[0]["impact"] == "medium"


# ---------------------------------------------------------------------------
# TestSkipDecay — build-proposals.py
# ---------------------------------------------------------------------------

class TestSkipDecay:
    """Verify proposals skipped 3+ times are filtered from pending."""

    def _config(self):
        return {"existing_skills": [], "existing_agents": [], "existing_hooks": []}

    def test_skip_3_times_filters_pending(self):
        pending = [
            {"id": "old-skill", "type": "skill", "impact": "medium",
             "status": "pending", "description": "Old skill"},
        ]
        fs = {"skip_counts": {"old-skill": 3}}
        result = bp.build_proposals(self._config(), {}, {}, [], pending,
                                    feedback_signals=fs)
        ids = [p["id"] for p in result["proposals"]]
        assert "old-skill" not in ids

    def test_skip_below_threshold_keeps_pending(self):
        pending = [
            {"id": "ok-skill", "type": "skill", "impact": "medium",
             "status": "pending", "description": "OK skill"},
        ]
        fs = {"skip_counts": {"ok-skill": 2}}
        result = bp.build_proposals(self._config(), {}, {}, [], pending,
                                    feedback_signals=fs)
        ids = [p["id"] for p in result["proposals"]]
        assert "ok-skill" in ids

    def test_no_feedback_keeps_all_pending(self):
        pending = [
            {"id": "skill-1", "type": "skill", "impact": "medium",
             "status": "pending", "description": "Skill 1"},
        ]
        result = bp.build_proposals(self._config(), {}, {}, [], pending)
        ids = [p["id"] for p in result["proposals"]]
        assert "skill-1" in ids


# ---------------------------------------------------------------------------
# TestSafetyGate — format-proposals.py
# ---------------------------------------------------------------------------

class TestSafetyGate:
    """Verify safety gate labels on automation proposals."""

    def test_safety_label_on_hook_proposals(self):
        proposals = [
            {"id": "h1", "type": "hook", "impact": "medium",
             "description": "Auto-lint", "evidence_summary": "5 times"},
        ]
        gate = {"triggered": True, "signal_count": 4, "threshold": 3}
        table = fmt.format_proposal_table(proposals, safety_gate=gate)
        assert "[Safety review]" in table

    def test_safety_label_on_agent_proposals(self):
        proposals = [
            {"id": "a1", "type": "agent", "impact": "high",
             "description": "Deploy agent", "evidence_summary": "8 times"},
        ]
        gate = {"triggered": True, "signal_count": 3, "threshold": 3}
        table = fmt.format_proposal_table(proposals, safety_gate=gate)
        assert "[Safety review]" in table

    def test_no_safety_label_on_rules(self):
        proposals = [
            {"id": "r1", "type": "rule", "impact": "medium",
             "description": "Add vitest rule", "evidence_summary": "3 times"},
        ]
        gate = {"triggered": True, "signal_count": 5, "threshold": 3}
        table = fmt.format_proposal_table(proposals, safety_gate=gate)
        assert "[Safety review]" not in table

    def test_no_label_when_gate_not_triggered(self):
        proposals = [
            {"id": "h1", "type": "hook", "impact": "medium",
             "description": "Auto-lint", "evidence_summary": "5 times"},
        ]
        gate = {"triggered": False, "signal_count": 1, "threshold": 3}
        table = fmt.format_proposal_table(proposals, safety_gate=gate)
        assert "[Safety review]" not in table

    def test_no_label_when_no_gate(self):
        proposals = [
            {"id": "h1", "type": "hook", "impact": "medium",
             "description": "Auto-lint", "evidence_summary": "5 times"},
        ]
        table = fmt.format_proposal_table(proposals)
        assert "[Safety review]" not in table


# ---------------------------------------------------------------------------
# TestPerCategoryPrecision — analyze-transcripts.py
# ---------------------------------------------------------------------------

class TestPerCategoryPrecision:
    """Verify precision_rate works across all categories."""

    at = importlib.import_module("analyze-transcripts")

    def test_corrections_precision(self):
        stats = {"corrections": {"approved": 8, "dismissed": 2}}
        prec = self.at.precision_rate(stats, "corrections")
        assert prec == pytest.approx(0.8)

    def test_post_actions_precision(self):
        stats = {"post_actions": {"approved": 1, "dismissed": 4}}
        prec = self.at.precision_rate(stats, "post_actions")
        assert prec == pytest.approx(0.2)

    def test_repeated_prompts_precision(self):
        stats = {"repeated_prompts": {"approved": 3, "dismissed": 0}}
        prec = self.at.precision_rate(stats, "repeated_prompts")
        assert prec == pytest.approx(1.0)

    def test_insufficient_data_returns_none(self):
        stats = {"corrections": {"approved": 1, "dismissed": 1}}
        assert self.at.precision_rate(stats, "corrections") is None

    def test_missing_category_returns_none(self):
        stats = {}
        assert self.at.precision_rate(stats, "post_actions") is None


# ---------------------------------------------------------------------------
# TestBackwardCompatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Verify old data formats work with new code."""

    def test_build_proposals_without_feedback_signals(self):
        """build_proposals works fine without feedback_signals arg."""
        config = {"existing_skills": [], "existing_agents": [], "existing_hooks": []}
        result = bp.build_proposals(config, {}, {}, [], [])
        assert "proposals" in result
        assert "safety_gate" in result
        assert result["safety_gate"] is None

    def test_build_proposals_with_safety_gate(self):
        """safety_gate is passed through when feedback_signals provided."""
        config = {"existing_skills": [], "existing_agents": [], "existing_hooks": []}
        fs = {
            "safety_gate": {"triggered": True, "signal_count": 5, "threshold": 3},
        }
        result = bp.build_proposals(config, {}, {}, [], [], feedback_signals=fs)
        assert result["safety_gate"]["triggered"] is True

    def test_ensure_feedback_signals_idempotent(self):
        """Calling _ensure_feedback_signals twice doesn't reset data."""
        stats = _make_stats()
        fs = fp._ensure_feedback_signals(stats)
        fs["skip_counts"]["test"] = 5
        fs2 = fp._ensure_feedback_signals(stats)
        assert fs2["skip_counts"]["test"] == 5

    def test_compute_low_impact_ratios_empty(self):
        assert bp._compute_low_impact_ratios(None) == {}
        assert bp._compute_low_impact_ratios({}) == {}

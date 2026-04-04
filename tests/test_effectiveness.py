"""Tests for artifact effectiveness tracking (Task 3.5).

Validates that applied proposals are tracked and their effectiveness measured
by comparing triggering patterns before vs. after deployment.
"""

import importlib
import json
import sys
from pathlib import Path
from typing import Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "forge" / "scripts"))
bp = importlib.import_module("build-proposals")
fp = importlib.import_module("finalize-proposals")


# ---------------------------------------------------------------------------
# _compute_effectiveness tests
# ---------------------------------------------------------------------------

class TestComputeEffectiveness:
    """Test the effectiveness computation logic."""

    def test_no_applied_history(self):
        """Empty applied history returns empty effectiveness."""
        result = bp._compute_effectiveness([], {})
        assert result == []

    def test_no_tracking_data_skipped(self):
        """Applied entries without tracking data are skipped."""
        applied = [
            {"id": "old-rule", "type": "rule", "applied_at": "2026-03-01T00:00:00Z"},
        ]
        result = bp._compute_effectiveness(applied, {})
        assert result == []

    def test_effective_when_pattern_gone(self):
        """Artifact is effective when triggering correction no longer appears."""
        applied = [
            {
                "id": "use-vitest-rule",
                "type": "rule",
                "applied_at": "2026-03-20T00:00:00Z",
                "description": "Add rule: use vitest not jest",
                "tracking": {"source": "correction", "pattern_id": "use-vitest-rule"},
            },
        ]
        # Current analysis has no corrections
        transcripts = {"candidates": {"corrections": []}}
        result = bp._compute_effectiveness(applied, transcripts)
        assert len(result) == 1
        assert result[0]["status"] == "effective"
        assert result[0]["still_present"] is False

    def test_ineffective_when_pattern_persists(self):
        """Artifact is ineffective when triggering correction still appears."""
        applied = [
            {
                "id": "use-vitest-rule",
                "type": "rule",
                "applied_at": "2026-03-20T00:00:00Z",
                "description": "Add rule: use vitest not jest",
                "tracking": {"source": "correction", "pattern_id": "use-vitest-rule"},
            },
        ]
        # Pattern still shows up with same ID
        transcripts = {
            "candidates": {
                "corrections": [
                    {
                        "pattern": "use vitest not jest",
                        "theme_hash": "abc123",
                        "occurrences": 3,
                        "total_occurrences": 3,
                        "sessions": ["s1", "s2"],
                    },
                ],
            },
        }
        result = bp._compute_effectiveness(applied, transcripts)
        assert len(result) == 1
        assert result[0]["status"] == "ineffective"
        assert result[0]["still_present"] is True
        assert result[0]["current_frequency"] == 3

    def test_fuzzy_match_catches_similar_descriptions(self):
        """Fuzzy matching via description catches renamed patterns."""
        applied = [
            {
                "id": "pnpm-not-npm-rule",
                "type": "rule",
                "applied_at": "2026-03-20T00:00:00Z",
                "description": "Add rule: use pnpm instead of npm",
                "tracking": {"source": "correction", "pattern_id": "pnpm-not-npm-rule"},
            },
        ]
        transcripts = {
            "candidates": {
                "corrections": [
                    {
                        "pattern": "use pnpm not npm always",
                        "total_occurrences": 4,
                        "sessions": ["s1", "s2", "s3"],
                    },
                ],
            },
        }
        result = bp._compute_effectiveness(applied, transcripts)
        assert len(result) == 1
        assert result[0]["status"] == "ineffective"

    def test_post_action_tracking(self):
        """Post-action hooks are tracked for effectiveness."""
        applied = [
            {
                "id": "auto-prettier-hook",
                "type": "hook",
                "applied_at": "2026-03-20T00:00:00Z",
                "description": "Auto-format with prettier",
                "tracking": {"source": "post_action", "pattern_id": "auto-prettier-hook"},
            },
        ]
        # User still manually runs prettier
        transcripts = {
            "candidates": {
                "corrections": [],
                "post_actions": [
                    {"command": "npx prettier --write", "count": 5,
                     "sessions": ["s1", "s2"]},
                ],
            },
        }
        result = bp._compute_effectiveness(applied, transcripts)
        assert len(result) == 1
        assert result[0]["status"] == "ineffective"

    def test_post_action_effective_when_gone(self):
        """Post-action hook is effective when user stops running the command."""
        applied = [
            {
                "id": "auto-eslint-hook",
                "type": "hook",
                "applied_at": "2026-03-20T00:00:00Z",
                "description": "Auto-lint with eslint",
                "tracking": {"source": "post_action", "pattern_id": "auto-eslint-hook"},
            },
        ]
        transcripts = {"candidates": {"corrections": [], "post_actions": []}}
        result = bp._compute_effectiveness(applied, transcripts)
        assert len(result) == 1
        assert result[0]["status"] == "effective"

    def test_multiple_artifacts_mixed(self):
        """Multiple applied artifacts with mixed effectiveness."""
        applied = [
            {
                "id": "vitest-rule",
                "type": "rule",
                "applied_at": "2026-03-20T00:00:00Z",
                "description": "use vitest",
                "tracking": {"source": "correction", "pattern_id": "vitest-rule"},
            },
            {
                "id": "prettier-hook",
                "type": "hook",
                "applied_at": "2026-03-20T00:00:00Z",
                "description": "auto format",
                "tracking": {"source": "post_action", "pattern_id": "prettier-hook"},
            },
        ]
        # vitest correction is gone, but prettier is still manual
        transcripts = {
            "candidates": {
                "corrections": [],
                "post_actions": [
                    {"command": "npx prettier --write", "count": 3,
                     "sessions": ["s1"]},
                ],
            },
        }
        result = bp._compute_effectiveness(applied, transcripts)
        assert len(result) == 2
        statuses = {r["id"]: r["status"] for r in result}
        assert statuses["vitest-rule"] == "effective"
        assert statuses["prettier-hook"] == "ineffective"


class TestEffectivenessInContextHealth:
    """Test that effectiveness data flows into context_health."""

    def test_effectiveness_in_build_proposals(self):
        """build_proposals includes effectiveness when applied_history provided."""
        config = {
            "context_budget": {"claude_md_lines": 50, "rules_count": 1,
                                "skills_count": 0, "hooks_count": 0,
                                "agents_count": 0, "estimated_tier1_lines": 60},
            "tech_stack": {"detected": []},
            "placement_issues": [],
            "demotion_candidates": {},
            "existing_skills": [], "existing_agents": [], "existing_hooks": [],
            "existing_rules": [],
        }
        transcripts = {
            "sessions_analyzed": 5,
            "candidates": {"corrections": [], "post_actions": [],
                           "repeated_prompts": [], "workflow_patterns": []},
        }
        applied = [
            {
                "id": "test-rule",
                "type": "rule",
                "applied_at": "2026-03-20T00:00:00Z",
                "description": "test rule",
                "tracking": {"source": "correction", "pattern_id": "test-rule"},
            },
        ]
        result = bp.build_proposals(
            config, transcripts, {}, [], [],
            applied_history=applied,
        )
        health = result["context_health"]
        assert "effectiveness" in health
        assert health["effectiveness"]["tracked_artifacts"] == 1
        assert health["effectiveness"]["effective"] == 1

    def test_no_effectiveness_without_applied(self):
        """No effectiveness section when no applied_history."""
        config = {
            "context_budget": {"claude_md_lines": 50, "rules_count": 0,
                                "skills_count": 0, "hooks_count": 0,
                                "agents_count": 0, "estimated_tier1_lines": 50},
            "tech_stack": {"detected": []},
            "placement_issues": [],
            "demotion_candidates": {},
            "existing_skills": [], "existing_agents": [], "existing_hooks": [],
            "existing_rules": [],
        }
        transcripts = {
            "sessions_analyzed": 0,
            "candidates": {},
        }
        result = bp.build_proposals(config, transcripts, {}, [], [])
        assert "effectiveness" not in result["context_health"]


class TestFinalizeRecordsTracking:
    """Test that finalize-proposals records tracking data for applied proposals."""

    def test_tracking_recorded_for_corrections(self, tmp_path, monkeypatch):
        """Applied correction proposals include tracking data."""
        monkeypatch.setattr(fp, "get_project_data_dir", lambda root: tmp_path)
        monkeypatch.setattr(fp, "get_user_data_dir", lambda root: tmp_path)
        (tmp_path / "history").mkdir()
        (tmp_path / "proposals").mkdir()

        outcomes = [
            {"id": "vitest-rule", "status": "applied", "type": "rule"},
        ]
        all_proposals = [
            {
                "id": "vitest-rule",
                "type": "rule",
                "source_type": "corrections",
                "description": "Add rule: use vitest",
                "evidence_summary": "Corrected 5 times across 3 sessions",
            },
        ]

        fp._record_applied(tmp_path, outcomes, all_proposals)

        history = json.loads(
            (tmp_path / "history" / "applied.json").read_text()
        )
        assert len(history) == 1
        assert "tracking" in history[0]
        assert history[0]["tracking"]["source"] == "correction"
        assert history[0]["evidence_summary"] == "Corrected 5 times across 3 sessions"

    def test_no_tracking_for_demotions(self, tmp_path, monkeypatch):
        """Demotion proposals don't get tracking data."""
        monkeypatch.setattr(fp, "get_project_data_dir", lambda root: tmp_path)
        monkeypatch.setattr(fp, "get_user_data_dir", lambda root: tmp_path)
        (tmp_path / "history").mkdir()
        (tmp_path / "proposals").mkdir()

        outcomes = [
            {"id": "demotion-react", "status": "applied", "type": "demotion"},
        ]
        all_proposals = [
            {
                "id": "demotion-react",
                "type": "demotion",
                "description": "Move react entries to rule",
            },
        ]

        fp._record_applied(tmp_path, outcomes, all_proposals)

        history = json.loads(
            (tmp_path / "history" / "applied.json").read_text()
        )
        assert len(history) == 1
        assert "tracking" not in history[0]

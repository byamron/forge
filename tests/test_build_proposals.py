"""Tests for build-proposals.py."""
import sys
import importlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "forge" / "scripts"))
bp = importlib.import_module("build-proposals")


class TestThresholdFiltering:
    """Verify proposals respect occurrence/session thresholds."""

    def test_below_threshold_excluded(self):
        transcripts = {
            "candidates": {
                "repeated_prompts": [{
                    "canonical_text": "deploy to staging",
                    "total_occurrences": 1,  # below threshold of 4
                    "session_count": 1,
                    "example_messages": [],
                }],
                "corrections": [],
            },
        }
        result = bp.build_proposals({}, transcripts, {}, [], [])
        skill_proposals = [p for p in result["proposals"] if p["type"] == "skill"]
        assert len(skill_proposals) == 0

    def test_above_threshold_included(self):
        transcripts = {
            "candidates": {
                "repeated_prompts": [{
                    "canonical_text": "deploy to staging",
                    "total_occurrences": 6,
                    "session_count": 4,
                    "example_messages": ["deploy to staging please"],
                }],
                "corrections": [],
            },
        }
        result = bp.build_proposals(
            {"existing_skills": [], "existing_agents": [], "existing_hooks": []},
            transcripts, {}, [], [],
        )
        skill_proposals = [p for p in result["proposals"] if p["type"] == "skill"]
        assert len(skill_proposals) == 1


class TestDismissedFiltering:
    """Verify dismissed proposals are excluded."""

    def test_dismissed_by_id(self):
        transcripts = {
            "candidates": {
                "repeated_prompts": [{
                    "canonical_text": "deploy to staging",
                    "total_occurrences": 6,
                    "session_count": 4,
                    "example_messages": [],
                }],
                "corrections": [],
            },
        }
        dismissed = [{"id": "deploy-to-staging-skill", "description": ""}]
        result = bp.build_proposals(
            {"existing_skills": [], "existing_agents": [], "existing_hooks": []},
            transcripts, {}, dismissed, [],
        )
        skill_proposals = [p for p in result["proposals"] if p["type"] == "skill"]
        assert len(skill_proposals) == 0


class TestDuplicateDetection:
    """Verify existing skills prevent duplicate proposals."""

    def test_existing_skill_prevents_proposal(self):
        transcripts = {
            "candidates": {
                "repeated_prompts": [{
                    "canonical_text": "deploy to staging",
                    "total_occurrences": 8,
                    "session_count": 5,
                    "example_messages": [],
                }],
                "corrections": [],
            },
        }
        existing_skills = [{
            "name": "deploy-staging",
            "description": "Deploy the application to staging environment",
            "content": "deploy to staging workflow",
        }]
        result = bp.build_proposals(
            {"existing_skills": existing_skills, "existing_agents": [], "existing_hooks": []},
            transcripts, {}, [], [],
        )
        new_skills = [
            p for p in result["proposals"]
            if p["type"] == "skill" and "deploy" in p.get("id", "")
        ]
        assert len(new_skills) == 0


class TestImpactScoring:
    def test_high_occurrence_skill(self):
        assert bp._score_impact("skill", occurrences=10, sessions=6) == "high"

    def test_low_occurrence_skill(self):
        assert bp._score_impact("skill", occurrences=2, sessions=1) == "low"

    def test_hook_with_high_severity(self):
        assert bp._score_impact("hook", severity="high") == "high"


class TestSimilarity:
    def test_identical_texts(self):
        assert bp._similarity("deploy to staging", "deploy to staging") == 1.0

    def test_no_overlap(self):
        assert bp._similarity("deploy staging", "running tests") == 0.0

    def test_partial_overlap(self):
        sim = bp._similarity("deploy to staging environment", "deploy staging server")
        assert 0.0 < sim < 1.0

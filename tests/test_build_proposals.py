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


class TestDemotionProposals:
    """Verify tier demotion proposals from domain-specific entries and oversized rules."""

    def _config_with_demotions(self, claude_md_to_rule=None,
                                rule_to_reference=None,
                                over_budget=False):
        """Build a config dict with demotion_candidates."""
        demotable = claude_md_to_rule or []
        return {
            "existing_skills": [],
            "existing_agents": [],
            "existing_hooks": [],
            "demotion_candidates": {
                "claude_md_to_rule": demotable,
                "rule_to_reference": rule_to_reference or [],
                "budget": {
                    "claude_md_lines": 300 if over_budget else 100,
                    "over_budget": over_budget,
                    "total_demotable_lines": sum(
                        len(g["entries"]) for g in demotable
                    ),
                },
            },
        }

    def test_claude_md_to_rule_proposal_generated(self):
        config = self._config_with_demotions(claude_md_to_rule=[{
            "domain": "react",
            "filename": "react",
            "paths": ["**/*.tsx", "**/*.jsx"],
            "entries": [
                {"line_number": 10, "content": "Use functional components in .tsx files"},
                {"line_number": 15, "content": "Always use React hooks for state"},
            ],
        }])
        result = bp.build_proposals(config, {}, {}, [], [])
        demotions = [p for p in result["proposals"] if p["type"] == "demotion"]
        assert len(demotions) == 1
        assert demotions[0]["id"] == "demote-react-to-rule"
        assert ".claude/rules/react.md" in demotions[0]["suggested_path"]
        assert demotions[0]["demotion_detail"]["action"] == "claude_md_to_rule"
        assert len(demotions[0]["demotion_detail"]["entries"]) == 2

    def test_rule_to_reference_proposal_generated(self):
        config = self._config_with_demotions(rule_to_reference=[{
            "path": ".claude/rules/python.md",
            "filename": "python",
            "line_count": 120,
        }])
        result = bp.build_proposals(config, {}, {}, [], [])
        demotions = [p for p in result["proposals"] if p["type"] == "demotion"]
        assert len(demotions) == 1
        assert demotions[0]["id"] == "demote-python-rule-to-ref"
        assert demotions[0]["demotion_detail"]["action"] == "rule_to_reference"

    def test_over_budget_boosts_impact_to_high(self):
        config = self._config_with_demotions(
            claude_md_to_rule=[{
                "domain": "testing",
                "filename": "testing",
                "paths": ["tests/**"],
                "entries": [
                    {"line_number": 5, "content": "Put tests in tests/ directory"},
                    {"line_number": 6, "content": "Use pytest for all test files"},
                ],
            }],
            over_budget=True,
        )
        result = bp.build_proposals(config, {}, {}, [], [])
        demotions = [p for p in result["proposals"] if p["type"] == "demotion"]
        assert len(demotions) == 1
        assert demotions[0]["impact"] == "high"

    def test_under_budget_gives_medium_impact(self):
        config = self._config_with_demotions(
            claude_md_to_rule=[{
                "domain": "python",
                "filename": "python",
                "paths": ["**/*.py"],
                "entries": [
                    {"line_number": 1, "content": "Use type hints in .py files"},
                    {"line_number": 2, "content": "Use pathlib for Python filesystem ops"},
                ],
            }],
            over_budget=False,
        )
        result = bp.build_proposals(config, {}, {}, [], [])
        demotions = [p for p in result["proposals"] if p["type"] == "demotion"]
        assert demotions[0]["impact"] == "medium"

    def test_no_demotion_candidates_produces_no_proposals(self):
        config = self._config_with_demotions()
        result = bp.build_proposals(config, {}, {}, [], [])
        demotions = [p for p in result["proposals"] if p["type"] == "demotion"]
        assert len(demotions) == 0

    def test_dismissed_demotion_excluded(self):
        config = self._config_with_demotions(claude_md_to_rule=[{
            "domain": "react",
            "filename": "react",
            "paths": ["**/*.tsx"],
            "entries": [
                {"line_number": 1, "content": "Use React hooks"},
                {"line_number": 2, "content": "Prefer .tsx over .jsx"},
            ],
        }])
        dismissed = [{"id": "demote-react-to-rule", "description": ""}]
        result = bp.build_proposals(config, {}, {}, dismissed, [])
        demotions = [p for p in result["proposals"] if p["type"] == "demotion"]
        assert len(demotions) == 0

    def test_suggested_content_includes_paths_frontmatter(self):
        config = self._config_with_demotions(claude_md_to_rule=[{
            "domain": "go",
            "filename": "go",
            "paths": ["**/*.go"],
            "entries": [
                {"line_number": 1, "content": "Use gofmt on .go files"},
                {"line_number": 2, "content": "Error handling in Go"},
            ],
        }])
        result = bp.build_proposals(config, {}, {}, [], [])
        demotions = [p for p in result["proposals"] if p["type"] == "demotion"]
        content = demotions[0]["suggested_content"]
        assert "paths:" in content
        assert "**/*.go" in content

    def test_context_health_includes_demotion_count(self):
        config = self._config_with_demotions(
            claude_md_to_rule=[{
                "domain": "react",
                "filename": "react",
                "paths": ["**/*.tsx"],
                "entries": [
                    {"line_number": 1, "content": "Use hooks"},
                    {"line_number": 2, "content": "TSX only"},
                ],
            }],
            rule_to_reference=[{
                "path": ".claude/rules/big.md",
                "filename": "big",
                "line_count": 150,
            }],
        )
        result = bp.build_proposals(config, {}, {}, [], [])
        assert result["context_health"]["demotion_candidates"] == 2


class TestDemotionImpactScoring:
    def test_demotion_over_budget_is_high(self):
        assert bp._score_impact("demotion", severity="over_budget") == "high"

    def test_demotion_default_is_medium(self):
        assert bp._score_impact("demotion") == "medium"


class TestSimilarity:
    def test_identical_texts(self):
        assert bp._similarity("deploy to staging", "deploy to staging") == 1.0

    def test_no_overlap(self):
        assert bp._similarity("deploy staging", "running tests") == 0.0

    def test_partial_overlap(self):
        sim = bp._similarity("deploy to staging environment", "deploy staging server")
        assert 0.0 < sim < 1.0


class TestAgentGeneration:
    """Verify agent proposals are built from workflow patterns."""

    def _make_transcripts(self, pattern, phase_sequence, occurrences=6,
                          sessions=None):
        if sessions is None:
            sessions = ["s1", "s2", "s3"]
        return {
            "candidates": {
                "repeated_prompts": [],
                "corrections": [],
                "workflow_patterns": [{
                    "pattern": pattern,
                    "phase_sequence": phase_sequence,
                    "occurrences": occurrences,
                    "sessions": sessions,
                    "evidence": [
                        {"session": "s1", "tools_used": ["Read", "Edit", "Bash"],
                         "turn_count": 8},
                    ],
                }],
            },
        }

    def _config(self):
        return {
            "existing_skills": [],
            "existing_agents": [],
            "existing_hooks": [],
        }

    def test_workflow_pattern_produces_agent_proposal(self):
        transcripts = self._make_transcripts(
            "plan-implement-verify",
            ["read", "write", "execute"],
        )
        result = bp.build_proposals(self._config(), transcripts, {}, [], [])
        agents = [p for p in result["proposals"] if p["type"] == "agent"]
        assert len(agents) == 1
        assert "agent" in agents[0]["id"]

    def test_below_threshold_excluded(self):
        transcripts = self._make_transcripts(
            "plan-implement-verify",
            ["read", "write", "execute"],
            occurrences=2,
            sessions=["s1"],
        )
        result = bp.build_proposals(self._config(), transcripts, {}, [], [])
        agents = [p for p in result["proposals"] if p["type"] == "agent"]
        assert len(agents) == 0

    def test_existing_agent_prevents_duplicate(self):
        transcripts = self._make_transcripts(
            "plan-implement-verify",
            ["read", "write", "execute"],
        )
        config = self._config()
        config["existing_agents"] = [{
            "name": "plan-implement-verify",
            "description": "Plan, implement, and verify workflow",
        }]
        result = bp.build_proposals(config, transcripts, {}, [], [])
        agents = [p for p in result["proposals"] if p["type"] == "agent"]
        assert len(agents) == 0

    def test_generated_content_has_frontmatter(self):
        transcripts = self._make_transcripts(
            "plan-implement-verify",
            ["read", "write", "execute"],
        )
        result = bp.build_proposals(self._config(), transcripts, {}, [], [])
        agents = [p for p in result["proposals"] if p["type"] == "agent"]
        content = agents[0]["suggested_content"]
        assert content.startswith("---")
        assert "model: sonnet" in content
        assert "effort: low" in content
        assert "maxTurns:" in content

    def test_generated_content_has_workflow_steps(self):
        transcripts = self._make_transcripts(
            "plan-implement-verify",
            ["read", "write", "execute"],
        )
        result = bp.build_proposals(self._config(), transcripts, {}, [], [])
        content = [p for p in result["proposals"]
                   if p["type"] == "agent"][0]["suggested_content"]
        assert "## Step 1:" in content
        assert "## Step 2:" in content
        assert "## Step 3:" in content

    def test_read_only_agent_has_disallowed_tools(self):
        content = bp._generate_agent_content(
            "code-reviewer", ["read"], [],
        )
        assert "disallowedTools:" in content
        assert "Write" in content
        assert "Edit" in content
        assert "Bash" in content

    def test_full_cycle_agent_has_no_disallowed_tools(self):
        content = bp._generate_agent_content(
            "plan-implement-verify", ["read", "write", "execute"], [],
        )
        assert "disallowedTools:" not in content

    def test_audit_agent_disallows_write(self):
        content = bp._generate_agent_content(
            "audit-and-validate", ["read", "execute"], [],
        )
        assert "disallowedTools:" in content
        assert "Write" in content
        assert "Edit" in content

    def test_evidence_included_when_available(self):
        evidence = [
            {"session": "abc12345", "tools_used": ["Read", "Edit"],
             "turn_count": 5},
        ]
        content = bp._generate_agent_content(
            "plan-implement-verify", ["read", "write", "execute"], evidence,
        )
        assert "abc12345" in content

    def test_impact_scoring_for_agents(self):
        assert bp._score_impact("agent", occurrences=10, sessions=6) == "high"
        assert bp._score_impact("agent", occurrences=5, sessions=3) == "medium"
        assert bp._score_impact("agent", occurrences=2, sessions=1) == "low"

    def test_iterative_dev_steps_are_distinct(self):
        """The iterative-development archetype should produce distinct steps."""
        content = bp._generate_agent_content(
            "iterative-development",
            ["read", "write", "execute", "write"],
            [],
        )
        assert "## Step 1:" in content
        assert "## Step 2:" in content
        assert "## Step 3:" in content
        assert "## Step 4:" in content
        # Step 2 (Implement) and Step 4 (Fix) should have different titles
        assert "## Step 2: Implement" in content
        assert "## Step 4: Fix" in content

    def test_tdd_steps_are_distinct(self):
        """The TDD archetype should produce distinct steps for repeated phases."""
        content = bp._generate_agent_content(
            "test-driven-development",
            ["read", "write", "execute", "write", "execute"],
            [],
        )
        assert "## Step 5:" in content
        # Step 2 and Step 4 should differ, Step 3 and Step 5 should differ
        assert "## Step 2: Implement" in content
        assert "## Step 4: Fix" in content
        assert "## Step 3: Test" in content
        assert "## Step 5: Re-verify" in content

    def test_empty_phase_sequence_skipped(self):
        transcripts = {
            "candidates": {
                "repeated_prompts": [],
                "corrections": [],
                "workflow_patterns": [{
                    "pattern": "empty",
                    "phase_sequence": [],
                    "occurrences": 10,
                    "sessions": ["s1", "s2", "s3"],
                    "evidence": [],
                }],
            },
        }
        result = bp.build_proposals(self._config(), transcripts, {}, [], [])
        agents = [p for p in result["proposals"] if p["type"] == "agent"]
        assert len(agents) == 0

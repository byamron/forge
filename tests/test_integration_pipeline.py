"""Integration tests running the full Forge analysis pipeline on synthetic profiles.

Each test class exercises a different project profile, verifying that the
analysis scripts detect (or correctly filter) the expected signals and that
build-proposals produces the right proposal set.

These tests import the analysis scripts as modules and call their internal
functions directly — no subprocess calls, no git remote lookups. Transcript
loading bypasses find_all_project_session_dirs() by parsing JSONL files
directly from the profile's _transcripts/ directory.
"""

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Script imports (same pattern as existing unit tests)
# ---------------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "forge" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

_config_mod = importlib.import_module("analyze-config")
_transcripts_mod = importlib.import_module("analyze-transcripts")
_memory_mod = importlib.import_module("analyze-memory")
_proposals_mod = importlib.import_module("build-proposals")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_config_analysis(project_root: Path) -> dict:
    """Run analyze-config functions on a project directory."""
    budget, skills, agents, hooks, rules = _config_mod.compute_context_budget(project_root)
    tech_stack = _config_mod.detect_tech_stack(project_root)
    gaps = _config_mod.find_gaps(project_root, tech_stack)
    placement = _config_mod.find_placement_issues(project_root)
    demotions = _config_mod.find_demotion_candidates(project_root, placement, budget)
    return {
        "context_budget": budget,
        "existing_skills": skills,
        "existing_agents": agents,
        "existing_hooks": hooks,
        "existing_rules": rules,
        "tech_stack": tech_stack,
        "gaps": gaps,
        "placement_issues": placement,
        "demotion_candidates": demotions,
    }


def load_sessions_from_profile(project_root: Path) -> dict:
    """Load transcript sessions from the profile's _transcripts/ directory.

    Bypasses find_all_project_session_dirs() which requires git remotes.
    """
    transcripts_dir = project_root / "_transcripts"
    if not transcripts_dir.is_dir():
        return {}
    sessions = {}
    for jsonl_file in sorted(transcripts_dir.glob("*.jsonl")):
        session_id = jsonl_file.stem
        messages = _transcripts_mod.parse_transcript(jsonl_file)
        if messages:
            sessions[session_id] = messages
    return sessions


def load_stats_from_profile(project_root: Path) -> dict:
    """Load analyzer stats from the profile's _forge_data/ directory."""
    stats_path = project_root / "_forge_data" / "analyzer-stats.json"
    if stats_path.is_file():
        return json.loads(stats_path.read_text())
    return {
        "version": 1,
        "corrections": {"proposed": 0, "approved": 0, "dismissed": 0},
        "post_actions": {"proposed": 0, "approved": 0, "dismissed": 0},
        "repeated_prompts": {"proposed": 0, "approved": 0, "dismissed": 0},
        "theme_outcomes": {},
        "suppressed_themes": [],
    }


def load_dismissed_from_profile(project_root: Path) -> list:
    """Load dismissed proposals from the profile's _forge_data/ directory."""
    dismissed_path = project_root / "_forge_data" / "dismissed.json"
    if dismissed_path.is_file():
        return json.loads(dismissed_path.read_text())
    return []


def run_transcript_analysis(project_root: Path) -> dict:
    """Run transcript analysis on synthetic sessions."""
    sessions = load_sessions_from_profile(project_root)
    if not sessions:
        return {"candidates": {"corrections": [], "post_actions": [], "repeated_prompts": []}}
    stats = load_stats_from_profile(project_root)
    corrections = _transcripts_mod.find_corrections(sessions, stats)
    post_actions = _transcripts_mod.find_post_actions(sessions)
    repeated_prompts = _transcripts_mod.find_repeated_prompts(sessions)
    return {
        "sessions_analyzed": len(sessions),
        "candidates": {
            "corrections": corrections,
            "post_actions": post_actions,
            "repeated_prompts": repeated_prompts,
        },
    }


def run_memory_analysis(project_root: Path) -> dict:
    """Run memory analysis using the profile's _memory/ directory."""
    memory_dir = project_root / "_memory"
    output = {
        "auto_memory": {
            "exists": False,
            "memory_md_lines": 0,
            "topic_files": [],
            "promotable_notes": [],
        },
        "claude_local_md": {
            "exists": False,
            "lines": 0,
            "domain_specific_entries": [],
            "redundant_entries": [],
        },
    }

    if memory_dir.is_dir():
        output["auto_memory"]["exists"] = True
        memory_md = memory_dir / "MEMORY.md"
        if memory_md.is_file():
            lines = memory_md.read_text().splitlines()
            output["auto_memory"]["memory_md_lines"] = len(lines)

        topic_files = []
        for f in sorted(memory_dir.iterdir()):
            if f.is_file() and f.suffix == ".md" and f.name != "MEMORY.md":
                topic_files.append(f.name)
        output["auto_memory"]["topic_files"] = topic_files

        all_files = [memory_md] + [memory_dir / t for t in topic_files]
        for mem_file in all_files:
            if not mem_file.is_file():
                continue
            text = mem_file.read_text()
            entries = _memory_mod.parse_memory_entries(text)
            for entry in entries:
                if len(entry.strip()) < 10:
                    continue
                classification = _memory_mod.classify_entry(entry)
                is_redundant = _memory_mod.check_redundancy(entry, project_root)
                if is_redundant:
                    continue
                artifact = _memory_mod.CLASSIFICATION_TO_ARTIFACT.get(
                    classification, "claude_md_entry"
                )
                output["auto_memory"]["promotable_notes"].append({
                    "source": str(mem_file),
                    "content": entry[:300],
                    "classification": classification,
                    "suggested_artifact": artifact,
                })

    # CLAUDE.local.md
    claude_local = project_root / "CLAUDE.local.md"
    if claude_local.is_file():
        output["claude_local_md"]["exists"] = True
        lines = claude_local.read_text().splitlines()
        output["claude_local_md"]["lines"] = len(lines)
        text = claude_local.read_text()
        entries = _memory_mod.parse_memory_entries(text)
        for entry in entries:
            if len(entry.strip()) < 10:
                continue
            if _memory_mod.is_domain_specific(entry):
                output["claude_local_md"]["domain_specific_entries"].append({
                    "content": entry[:300],
                })

    return output


def run_full_pipeline(project_root: Path) -> dict:
    """Run the complete analysis pipeline and build proposals."""
    config = run_config_analysis(project_root)
    transcripts = run_transcript_analysis(project_root)
    memory = run_memory_analysis(project_root)
    dismissed = load_dismissed_from_profile(project_root)
    result = _proposals_mod.build_proposals(
        config, transcripts, memory, dismissed, pending=[],
    )
    return {
        "config": config,
        "transcripts": transcripts,
        "memory": memory,
        "proposals": result,
    }


# ===================================================================
# Profile: react-ts — Full config analysis surface
# ===================================================================

class TestReactTsProfile:
    """Verify config analysis on the react-ts profile."""

    def test_tech_stack_detection(self, react_ts_project):
        config = run_config_analysis(react_ts_project)
        detected = config["tech_stack"]["detected"]
        assert "node" in detected
        assert "react" in detected
        assert "next.js" in detected

    def test_formatter_and_linter_detected(self, react_ts_project):
        config = run_config_analysis(react_ts_project)
        assert config["tech_stack"]["formatter"] == "prettier"
        assert config["tech_stack"]["linter"] == "eslint"
        assert config["tech_stack"]["test_framework"] == "vitest"

    def test_missing_hooks_detected(self, react_ts_project):
        config = run_config_analysis(react_ts_project)
        gap_descriptions = [g["description"] for g in config["gaps"]]
        # Should detect missing prettier and eslint hooks
        assert any("prettier" in d.lower() for d in gap_descriptions)
        assert any("eslint" in d.lower() for d in gap_descriptions)

    def test_placement_issues_detected(self, react_ts_project):
        config = run_config_analysis(react_ts_project)
        # Should find domain-specific entries: .tsx mentions, tests/ mentions, api/ mentions
        assert len(config["placement_issues"]) >= 8

    def test_demotion_candidates_detected(self, react_ts_project):
        config = run_config_analysis(react_ts_project)
        demotions = config["demotion_candidates"]
        # Should group domain-specific entries by domain
        domain_names = [
            g["domain"] for g in demotions.get("claude_md_to_rule", [])
        ]
        assert "react" in domain_names
        assert "testing" in domain_names
        assert "api" in domain_names

    def test_over_budget(self, react_ts_project):
        config = run_config_analysis(react_ts_project)
        budget = config["context_budget"]
        assert budget["claude_md_lines"] > 200
        assert config["demotion_candidates"]["budget"]["over_budget"] is True

    def test_docs_gap(self, react_ts_project):
        config = run_config_analysis(react_ts_project)
        gap_types = [g["type"] for g in config["gaps"]]
        assert "missing_reference" in gap_types

    def test_proposals_include_hooks_and_demotions(self, react_ts_project):
        result = run_full_pipeline(react_ts_project)
        proposals = result["proposals"]["proposals"]
        types = [p["type"] for p in proposals]
        assert "hook" in types, f"Expected hook proposals, got: {types}"
        assert "demotion" in types, f"Expected demotion proposals, got: {types}"

    def test_hook_proposals_have_tool_names(self, react_ts_project):
        """Hook proposals should name the actual tool, not 'unknown'."""
        result = run_full_pipeline(react_ts_project)
        proposals = result["proposals"]["proposals"]
        hook_proposals = [p for p in proposals if p["type"] == "hook"]
        for p in hook_proposals:
            assert "unknown" not in p["id"], f"Hook proposal has 'unknown' in id: {p['id']}"
            assert "unknown" not in p["description"].lower(), (
                f"Hook proposal has 'unknown' in description: {p['description']}"
            )

    def test_hook_content_matches_tool(self, react_ts_project):
        """Hook content should use the correct command for each tool."""
        result = run_full_pipeline(react_ts_project)
        proposals = result["proposals"]["proposals"]
        hook_proposals = [p for p in proposals if p["type"] == "hook"]
        for p in hook_proposals:
            content = p.get("suggested_content", "")
            if "prettier" in p["id"]:
                assert "prettier" in content, (
                    f"Prettier hook should contain prettier command: {content}"
                )
            elif "eslint" in p["id"]:
                assert "eslint" in content, (
                    f"Eslint hook should contain eslint command: {content}"
                )


# ===================================================================
# Profile: python-corrections — Transcript analysis surface
# ===================================================================

class TestPythonCorrectionsProfile:
    """Verify transcript analysis on the python-corrections profile."""

    def test_sessions_loaded(self, python_corrections_project):
        sessions = load_sessions_from_profile(python_corrections_project)
        assert len(sessions) == 8

    def test_correction_theme_detected(self, python_corrections_project):
        transcripts = run_transcript_analysis(python_corrections_project)
        corrections = transcripts["candidates"]["corrections"]
        # Should detect pathlib correction theme
        assert len(corrections) >= 1, "Expected at least 1 correction theme"
        # Check that key terms include pathlib-related words
        all_terms = []
        for c in corrections:
            all_terms.extend(c.get("key_terms", []))
        assert any("pathlib" in t.lower() for t in all_terms), (
            f"Expected 'pathlib' in correction key terms, got: {all_terms}"
        )

    def test_post_action_detected(self, python_corrections_project):
        transcripts = run_transcript_analysis(python_corrections_project)
        post_actions = transcripts["candidates"]["post_actions"]
        assert len(post_actions) >= 1, "Expected at least 1 post-action pattern"
        # Should detect pytest
        patterns = [p["pattern"] for p in post_actions]
        assert any("pytest" in p.lower() for p in patterns), (
            f"Expected 'pytest' post-action, got: {patterns}"
        )

    def test_repeated_prompt_detected(self, python_corrections_project):
        transcripts = run_transcript_analysis(python_corrections_project)
        repeated = transcripts["candidates"]["repeated_prompts"]
        assert len(repeated) >= 1, "Expected at least 1 repeated prompt group"

    def test_no_formatter_hook_proposal(self, python_corrections_project):
        """Ruff hook is already configured — should not propose another."""
        config = run_config_analysis(python_corrections_project)
        # Ruff is detected as linter and formatter
        gaps = config["gaps"]
        formatter_gaps = [
            g for g in gaps
            if g["type"] == "missing_hook" and "format" in g["description"].lower()
        ]
        # ruff is configured as PostToolUse hook — no formatter gap
        assert len(formatter_gaps) == 0, (
            f"Expected no formatter hook gap (ruff configured), got: {formatter_gaps}"
        )

    def test_proposals_from_transcripts(self, python_corrections_project):
        result = run_full_pipeline(python_corrections_project)
        proposals = result["proposals"]["proposals"]
        types = [p["type"] for p in proposals]
        # Should generate rule (from corrections) and/or skill (from repeated prompts)
        assert any(t in ("rule", "skill", "hook") for t in types), (
            f"Expected transcript-derived proposals, got types: {types}"
        )

    def test_repeated_prompt_skill_name_quality(self, python_corrections_project):
        """Repeated prompt skills should derive names from user text, not summary."""
        result = run_full_pipeline(python_corrections_project)
        proposals = result["proposals"]["proposals"]
        skill_proposals = [p for p in proposals if p["type"] == "skill"]
        for p in skill_proposals:
            assert "similar-opening-prompt" not in p["id"], (
                f"Skill name derived from summary pattern, not user text: {p['id']}"
            )


# ===================================================================
# Profile: rust-minimal — Threshold enforcement
# ===================================================================

class TestRustMinimalProfile:
    """Verify that below-threshold signals produce no proposals."""

    def test_tech_stack_detected(self, rust_minimal_project):
        config = run_config_analysis(rust_minimal_project)
        assert "rust" in config["tech_stack"]["detected"]

    def test_formatter_hook_exists(self, rust_minimal_project):
        config = run_config_analysis(rust_minimal_project)
        gaps = config["gaps"]
        formatter_gaps = [
            g for g in gaps
            if g["type"] == "missing_hook" and "format" in g["description"].lower()
        ]
        assert len(formatter_gaps) == 0, "cargo fmt hook exists, should not propose"

    def test_oversized_rule_detected(self, rust_minimal_project):
        config = run_config_analysis(rust_minimal_project)
        demotions = config["demotion_candidates"]
        rule_refs = demotions.get("rule_to_reference", [])
        assert len(rule_refs) >= 1, "Expected oversized rule demotion"
        assert rule_refs[0]["line_count"] > 80

    def test_no_transcript_correction_proposals(self, rust_minimal_project):
        transcripts = run_transcript_analysis(rust_minimal_project)
        corrections = transcripts["candidates"]["corrections"]
        # 2 corrections in 1 session — below threshold (3+ in 2+ sessions)
        assert len(corrections) == 0, (
            f"Expected no corrections above threshold, got {len(corrections)}"
        )

    def test_no_repeated_prompt_proposals(self, rust_minimal_project):
        transcripts = run_transcript_analysis(rust_minimal_project)
        repeated = transcripts["candidates"]["repeated_prompts"]
        # 2 sessions with same opener — below threshold (3+ sessions)
        assert len(repeated) == 0, (
            f"Expected no repeated prompts above threshold, got {len(repeated)}"
        )

    def test_final_proposals_only_demotion(self, rust_minimal_project):
        result = run_full_pipeline(rust_minimal_project)
        proposals = result["proposals"]["proposals"]
        types = [p["type"] for p in proposals]
        # Only demotion proposals (oversized rule), nothing from transcripts
        for t in types:
            assert t == "demotion", (
                f"Expected only demotion proposals, got: {types}"
            )


# ===================================================================
# Profile: fullstack-mature — Dismissed/suppressed filtering
# ===================================================================

class TestFullstackMatureProfile:
    """Verify dismissed and suppressed filtering removes strong signals."""

    def test_hooks_already_configured(self, fullstack_mature_project):
        config = run_config_analysis(fullstack_mature_project)
        gaps = config["gaps"]
        # Prettier and eslint hooks are configured — only low-severity test hook gap remains
        high_hook_gaps = [
            g for g in gaps
            if g["type"] == "missing_hook" and g["severity"] == "high"
        ]
        assert len(high_hook_gaps) == 0, (
            f"Expected no high-severity hook gaps, got: {high_hook_gaps}"
        )

    def test_existing_skill_detected(self, fullstack_mature_project):
        config = run_config_analysis(fullstack_mature_project)
        skill_names = [s["name"] for s in config["existing_skills"]]
        assert "deploy" in skill_names

    def test_existing_agent_detected(self, fullstack_mature_project):
        config = run_config_analysis(fullstack_mature_project)
        agent_names = [a["name"] for a in config["existing_agents"]]
        assert "reviewer" in agent_names

    def test_transcript_signals_exist_raw(self, fullstack_mature_project):
        """Verify the raw transcript has strong signals before filtering."""
        sessions = load_sessions_from_profile(fullstack_mature_project)
        assert len(sessions) >= 8  # 5 deploy + 3 correction sessions

    def test_dismissed_deploy_skill_excluded(self, fullstack_mature_project):
        result = run_full_pipeline(fullstack_mature_project)
        proposals = result["proposals"]["proposals"]
        proposal_ids = [p["id"] for p in proposals]
        # The deploy skill was dismissed
        assert "deploy-to-staging-skill" not in proposal_ids

    def test_suppressed_correction_excluded(self, fullstack_mature_project):
        result = run_full_pipeline(fullstack_mature_project)
        proposals = result["proposals"]["proposals"]
        # No correction rule proposals (theme is suppressed)
        correction_rules = [
            p for p in proposals
            if p["type"] == "rule" and "correction" in p.get("description", "").lower()
        ]
        assert len(correction_rules) == 0, (
            f"Expected suppressed corrections to be excluded, got: {correction_rules}"
        )

    def test_memory_promotions_still_appear(self, fullstack_mature_project):
        memory = run_memory_analysis(fullstack_mature_project)
        notes = memory["auto_memory"]["promotable_notes"]
        # Memory promotions should still work even though other signals are filtered
        assert len(notes) >= 1, "Expected at least 1 memory promotion"

    def test_proposals_no_unknown_names(self, fullstack_mature_project):
        """No proposal should have 'unknown' in its id or description."""
        result = run_full_pipeline(fullstack_mature_project)
        proposals = result["proposals"]["proposals"]
        for p in proposals:
            assert "unknown" not in p["id"], f"Proposal has 'unknown' in id: {p['id']}"
            assert "Promote memory note to" not in p["description"] or "unknown" not in p["description"], (
                f"Memory proposal has 'unknown' in description: {p['description']}"
            )


# ===================================================================
# Profile: swift-ios — Memory-only path
# ===================================================================

class TestSwiftIosProfile:
    """Verify memory-only proposal path with no config or transcript signals."""

    def test_no_tech_stack_detection(self, swift_ios_project):
        config = run_config_analysis(swift_ios_project)
        # No package.json, pyproject.toml, or Cargo.toml
        assert len(config["tech_stack"]["detected"]) == 0

    def test_no_missing_hooks(self, swift_ios_project):
        config = run_config_analysis(swift_ios_project)
        assert len(config["gaps"]) == 0

    def test_swiftui_placement_detected(self, swift_ios_project):
        """SwiftUI mention in CLAUDE.md is correctly flagged as domain-specific."""
        config = run_config_analysis(swift_ios_project)
        assert len(config["placement_issues"]) >= 1
        frameworks = [
            p["content"] for p in config["placement_issues"]
            if "framework" in p.get("suggestion", "").lower()
        ]
        assert any("SwiftUI" in f for f in frameworks)

    def test_no_transcript_sessions(self, swift_ios_project):
        sessions = load_sessions_from_profile(swift_ios_project)
        assert len(sessions) == 0

    def test_memory_entries_detected(self, swift_ios_project):
        memory = run_memory_analysis(swift_ios_project)
        assert memory["auto_memory"]["exists"] is True
        notes = memory["auto_memory"]["promotable_notes"]
        assert len(notes) >= 1, "Expected promotable memory notes"

    def test_claude_local_exists(self, swift_ios_project):
        memory = run_memory_analysis(swift_ios_project)
        assert memory["claude_local_md"]["exists"] is True

    def test_domain_specific_local_entries(self, swift_ios_project):
        memory = run_memory_analysis(swift_ios_project)
        domain_entries = memory["claude_local_md"]["domain_specific_entries"]
        # CLAUDE.local.md mentions .swift files and .xcassets
        assert len(domain_entries) >= 1, (
            "Expected domain-specific entries in CLAUDE.local.md"
        )

    def test_pipeline_produces_no_config_proposals(self, swift_ios_project):
        result = run_full_pipeline(swift_ios_project)
        proposals = result["proposals"]["proposals"]
        config_types = {"hook", "demotion"}
        config_proposals = [p for p in proposals if p["type"] in config_types]
        assert len(config_proposals) == 0, (
            f"Expected no config proposals, got: {config_proposals}"
        )

    def test_memory_proposals_have_names(self, swift_ios_project):
        """Memory-promoted proposals should have meaningful names, not 'unknown'."""
        result = run_full_pipeline(swift_ios_project)
        proposals = result["proposals"]["proposals"]
        for p in proposals:
            assert "unknown" not in p["id"], f"Proposal has 'unknown' in id: {p['id']}"
            assert "unknown" not in p["description"], (
                f"Proposal has 'unknown' in description: {p['description']}"
            )

    def test_memory_proposals_have_correct_paths(self, swift_ios_project):
        """reference_doc proposals should target .claude/references/, not .claude/rules/."""
        result = run_full_pipeline(swift_ios_project)
        proposals = result["proposals"]["proposals"]
        for p in proposals:
            if p["type"] == "reference_doc":
                assert p["suggested_path"].startswith(".claude/references/"), (
                    f"reference_doc proposal has wrong path: {p['suggested_path']}"
                )
            elif p["type"] == "rule":
                assert p["suggested_path"].startswith(".claude/rules/"), (
                    f"rule proposal has wrong path: {p['suggested_path']}"
                )

    def test_memory_proposals_have_unique_ids(self, swift_ios_project):
        """Each memory-promoted proposal should have a unique ID."""
        result = run_full_pipeline(swift_ios_project)
        proposals = result["proposals"]["proposals"]
        ids = [p["id"] for p in proposals]
        assert len(ids) == len(set(ids)), f"Duplicate proposal IDs: {ids}"


# ===================================================================
# Cross-profile: Generator consistency
# ===================================================================

class TestGeneratorConsistency:
    """Verify the fixture generator produces valid, parseable data."""

    def test_all_profiles_generated(self, synthetic_profiles):
        expected = {"swift-ios", "react-ts", "python-corrections",
                    "rust-minimal", "fullstack-mature"}
        assert set(synthetic_profiles.keys()) == expected

    def test_all_profiles_have_claude_md(self, synthetic_profiles):
        for name, root in synthetic_profiles.items():
            assert (root / "CLAUDE.md").is_file(), (
                f"Profile {name} missing CLAUDE.md"
            )

    def test_transcript_jsonl_parseable(self, synthetic_profiles):
        """Every JSONL file must be parseable by the transcript parser."""
        for name, root in synthetic_profiles.items():
            transcripts_dir = root / "_transcripts"
            if not transcripts_dir.is_dir():
                continue
            for jsonl_file in transcripts_dir.glob("*.jsonl"):
                messages = _transcripts_mod.parse_transcript(jsonl_file)
                assert isinstance(messages, list), (
                    f"Failed to parse {jsonl_file} in profile {name}"
                )

    def test_expected_signals_metadata(self, synthetic_profiles):
        """Each profile should have an _expected.json metadata file."""
        for name, root in synthetic_profiles.items():
            expected_path = root / "_expected.json"
            assert expected_path.is_file(), (
                f"Profile {name} missing _expected.json"
            )
            data = json.loads(expected_path.read_text())
            assert isinstance(data, dict)


# ===================================================================
# Pipeline → Presentation scripts integration
# ===================================================================

class TestPipelineToPresentation:
    """Verify that pipeline output flows correctly through format-proposals
    and validate-paths scripts — the full path from synthetic data to
    presentation-ready output."""

    def _run_script(self, name, stdin_data):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / name)],
            input=stdin_data, capture_output=True, text=True, timeout=10,
        )
        return proc

    def test_format_proposals_on_react_ts(self, react_ts_project):
        """Pipeline output from react-ts profile formats without errors."""
        result = run_full_pipeline(react_ts_project)
        proposals_json = json.dumps(result["proposals"])
        proc = self._run_script("format-proposals.py", proposals_json)
        assert proc.returncode == 0, f"format-proposals failed: {proc.stderr}"
        out = json.loads(proc.stdout)
        assert out["proposal_count"] > 0
        assert "CLAUDE.md" in out["health_table"]
        assert "|" in out["proposal_table"]

    def test_format_proposals_on_rust_minimal(self, rust_minimal_project):
        """Rust-minimal has only demotion proposals — verify formatting."""
        result = run_full_pipeline(rust_minimal_project)
        proposals_json = json.dumps(result["proposals"])
        proc = self._run_script("format-proposals.py", proposals_json)
        assert proc.returncode == 0, f"format-proposals failed: {proc.stderr}"
        out = json.loads(proc.stdout)
        assert out["proposal_count"] >= 0
        assert "CLAUDE.md" in out["health_table"]

    def test_format_proposals_on_python_corrections(self, python_corrections_project):
        """Python-corrections has transcript-derived proposals."""
        result = run_full_pipeline(python_corrections_project)
        proposals_json = json.dumps(result["proposals"])
        proc = self._run_script("format-proposals.py", proposals_json)
        assert proc.returncode == 0, f"format-proposals failed: {proc.stderr}"
        out = json.loads(proc.stdout)
        # Should have proposals from correction themes
        assert isinstance(out["proposals"], list)

    def test_validate_paths_on_all_proposals(self, synthetic_profiles):
        """Every proposal from every profile must have valid paths."""
        for name, root in synthetic_profiles.items():
            result = run_full_pipeline(root)
            proposals = result["proposals"].get("proposals", [])
            if not proposals:
                continue
            # Build path validation input
            path_input = [
                {"id": p["id"], "suggested_path": p.get("suggested_path", "")}
                for p in proposals
                if p.get("suggested_path")
            ]
            if not path_input:
                continue
            proc = self._run_script("validate-paths.py", json.dumps(path_input))
            assert proc.returncode == 0, (
                f"validate-paths failed on {name}: {proc.stderr}"
            )
            out = json.loads(proc.stdout)
            # All proposals from the pipeline should have valid paths
            for r in out["results"]:
                assert r["valid"], (
                    f"Profile {name}: proposal {r['id']} has invalid path "
                    f"{r['path']}: {r.get('reason', '')}"
                )

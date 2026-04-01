"""Tests for SKILL.md extraction scripts: format-proposals, validate-paths, merge-settings."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "forge" / "scripts"


def run_script(name: str, stdin_data: str, extra_args=None):
    """Run a script with JSON stdin and return (returncode, stdout_json, stderr)."""
    cmd = [sys.executable, str(SCRIPTS_DIR / name)]
    if extra_args:
        cmd.extend(extra_args)
    proc = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True, timeout=10)
    stdout_json = None
    if proc.returncode == 0 and proc.stdout.strip():
        try:
            stdout_json = json.loads(proc.stdout)
        except json.JSONDecodeError:
            pass
    return proc.returncode, stdout_json, proc.stderr


# ---------------------------------------------------------------------------
# format-proposals.py
# ---------------------------------------------------------------------------

class TestFormatProposals:
    def test_basic_health_table(self):
        data = {
            "proposals": [],
            "context_health": {
                "claude_md_lines": 87,
                "rules_count": 3,
                "skills_count": 2,
                "hooks_count": 1,
                "agents_count": 0,
                "stale_artifacts_count": 0,
            },
        }
        rc, out, _ = run_script("format-proposals.py", json.dumps(data))
        assert rc == 0
        assert "87" in out["health_table"]
        assert out["proposal_count"] == 0
        assert out["proposal_table"] == ""

    def test_proposal_table(self):
        data = {
            "proposals": [
                {"id": "p1", "impact": "high", "type": "hook",
                 "description": "Auto-lint", "evidence_summary": "ESLint found"},
                {"id": "p2", "impact": "medium", "type": "rule",
                 "description": "Use vitest", "evidence_summary": "3 corrections"},
            ],
            "context_health": {},
        }
        rc, out, _ = run_script("format-proposals.py", json.dumps(data))
        assert rc == 0
        assert out["proposal_count"] == 2
        assert "Auto-lint" in out["proposal_table"]
        assert "Use vitest" in out["proposal_table"]

    def test_over_budget_warning(self):
        data = {
            "proposals": [],
            "context_health": {"claude_md_lines": 310, "over_budget": True},
        }
        rc, out, _ = run_script("format-proposals.py", json.dumps(data))
        assert rc == 0
        assert "\u26a0" in out["health_table"]

    def test_stale_artifacts_warning(self):
        data = {
            "proposals": [],
            "context_health": {"stale_artifacts_count": 2},
        }
        rc, out, _ = run_script("format-proposals.py", json.dumps(data))
        assert rc == 0
        assert "\u26a0" in out["health_table"]

    def test_ineffective_artifacts(self):
        data = {
            "proposals": [],
            "context_health": {
                "effectiveness": {"ineffective": 3},
            },
        }
        rc, out, _ = run_script("format-proposals.py", json.dumps(data))
        assert rc == 0
        assert "Ineffective" in out["health_table"]

    def test_deep_cache_flag(self):
        data = {
            "proposals": [],
            "context_health": {},
            "deep_analysis_cache": {"proposals": [], "timestamp": 123},
        }
        rc, out, _ = run_script("format-proposals.py", json.dumps(data))
        assert rc == 0
        assert out["has_deep_cache"] is True

    def test_no_deep_cache(self):
        data = {"proposals": [], "context_health": {}}
        rc, out, _ = run_script("format-proposals.py", json.dumps(data))
        assert rc == 0
        assert out["has_deep_cache"] is False

    def test_malformed_input(self):
        rc, _, stderr = run_script("format-proposals.py", "not json")
        assert rc == 1

    def test_empty_input(self):
        rc, _, stderr = run_script("format-proposals.py", "")
        assert rc == 1


# ---------------------------------------------------------------------------
# validate-paths.py
# ---------------------------------------------------------------------------

class TestValidatePaths:
    def test_valid_paths(self):
        data = [
            {"id": "p1", "suggested_path": ".claude/rules/lint.md"},
            {"id": "p2", "suggested_path": "CLAUDE.md"},
            {"id": "p3", "suggested_path": ".claude/skills/my-skill/SKILL.md"},
            {"id": "p4", "suggested_path": ".claude/settings.json"},
            {"id": "p5", "suggested_path": ".claude/forge/cache.json"},
        ]
        rc, out, _ = run_script("validate-paths.py", json.dumps(data))
        assert rc == 0
        assert out["all_valid"] is True
        assert all(r["valid"] for r in out["results"])

    def test_absolute_path(self):
        data = [{"id": "p1", "suggested_path": "/etc/passwd"}]
        rc, out, _ = run_script("validate-paths.py", json.dumps(data))
        assert rc == 0
        assert out["all_valid"] is False
        assert "Absolute" in out["results"][0]["reason"]

    def test_home_path(self):
        data = [{"id": "p1", "suggested_path": "~/.claude/rules/x.md"}]
        rc, out, _ = run_script("validate-paths.py", json.dumps(data))
        assert rc == 0
        assert out["results"][0]["valid"] is False

    def test_path_traversal(self):
        data = [
            {"id": "p1", "suggested_path": "../../../etc/passwd"},
            {"id": "p2", "suggested_path": ".claude/rules/../../etc/passwd"},
        ]
        rc, out, _ = run_script("validate-paths.py", json.dumps(data))
        assert rc == 0
        assert out["all_valid"] is False
        assert all(not r["valid"] for r in out["results"])

    def test_disallowed_location(self):
        data = [
            {"id": "p1", "suggested_path": "src/main.py"},
            {"id": "p2", "suggested_path": "node_modules/x.js"},
        ]
        rc, out, _ = run_script("validate-paths.py", json.dumps(data))
        assert rc == 0
        assert out["all_valid"] is False

    def test_empty_array(self):
        rc, out, _ = run_script("validate-paths.py", "[]")
        assert rc == 0
        assert out["all_valid"] is True
        assert out["results"] == []

    def test_mixed_valid_invalid(self):
        data = [
            {"id": "p1", "suggested_path": ".claude/rules/x.md"},
            {"id": "p2", "suggested_path": "/etc/passwd"},
        ]
        rc, out, _ = run_script("validate-paths.py", json.dumps(data))
        assert rc == 0
        assert out["all_valid"] is False
        assert out["results"][0]["valid"] is True
        assert out["results"][1]["valid"] is False

    def test_malformed_input(self):
        rc, _, _ = run_script("validate-paths.py", "not json")
        assert rc == 1


# ---------------------------------------------------------------------------
# merge-settings.py
# ---------------------------------------------------------------------------

class TestMergeSettings:
    def test_new_file(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        hook = {"event": "PostToolUse", "matcher": "Write|Edit",
                "command": "prettier --write", "timeout": 10}
        rc, out, _ = run_script(
            "merge-settings.py", json.dumps(hook),
            extra_args=["--settings-path", str(settings_path)])
        assert rc == 0
        assert out["status"] == "added"
        # Verify file was written
        data = json.loads(settings_path.read_text())
        assert "PostToolUse" in data["hooks"]
        assert data["hooks"]["PostToolUse"][0]["hooks"][0]["command"] == "prettier --write"

    def test_existing_with_other_hooks(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        existing = {
            "hooks": {
                "PreToolUse": [{"hooks": [{"type": "command", "command": "lint"}]}]
            }
        }
        settings_path.write_text(json.dumps(existing))
        hook = {"event": "PostToolUse", "command": "format"}
        rc, out, _ = run_script(
            "merge-settings.py", json.dumps(hook),
            extra_args=["--settings-path", str(settings_path)])
        assert rc == 0
        assert out["status"] == "added"
        data = json.loads(settings_path.read_text())
        # Existing hooks preserved
        assert "PreToolUse" in data["hooks"]
        assert "PostToolUse" in data["hooks"]

    def test_duplicate_hook(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        existing = {
            "hooks": {
                "PostToolUse": [{"matcher": "Write", "hooks": [
                    {"type": "command", "command": "format", "timeout": 10}
                ]}]
            }
        }
        settings_path.write_text(json.dumps(existing))
        hook = {"event": "PostToolUse", "matcher": "Write", "command": "format"}
        rc, out, _ = run_script(
            "merge-settings.py", json.dumps(hook),
            extra_args=["--settings-path", str(settings_path)])
        assert rc == 0
        assert out["status"] == "already_exists"

    def test_empty_settings(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        settings_path.write_text("{}")
        hook = {"event": "Stop", "command": "npm test"}
        rc, out, _ = run_script(
            "merge-settings.py", json.dumps(hook),
            extra_args=["--settings-path", str(settings_path)])
        assert rc == 0
        assert out["status"] == "added"
        data = json.loads(settings_path.read_text())
        assert "Stop" in data["hooks"]

    def test_malformed_settings(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        settings_path.write_text("not json {{{")
        hook = {"event": "PostToolUse", "command": "format"}
        rc, out, stderr = run_script(
            "merge-settings.py", json.dumps(hook),
            extra_args=["--settings-path", str(settings_path)])
        assert rc == 0
        assert out["status"] == "added"
        assert "malformed" in stderr.lower()

    def test_missing_required_fields(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        hook = {"matcher": "Write"}  # missing event and command
        rc, _, stderr = run_script(
            "merge-settings.py", json.dumps(hook),
            extra_args=["--settings-path", str(settings_path)])
        assert rc == 1

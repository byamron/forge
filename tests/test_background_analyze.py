"""Tests for background-analyze.py."""
import importlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "forge" / "scripts"))
ba = importlib.import_module("background-analyze")
import project_identity as pi


@pytest.fixture
def tmp_project_with_home(tmp_path):
    """Create a project dir + fake home for isolated testing."""
    project = tmp_path / "project"
    (project / ".claude" / "rules").mkdir(parents=True)
    (project / "CLAUDE.md").write_text("# Test\n")

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    return project, fake_home


@pytest.fixture
def user_data_dir(tmp_project_with_home, monkeypatch):
    """Set up user data dir with mocked home."""
    project, fake_home = tmp_project_with_home
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    with patch.object(pi, "_get_git_remote_url", return_value=None):
        data_dir = pi.get_user_data_dir(project)
    data_dir.mkdir(parents=True, exist_ok=True)
    return project, data_dir


def _write_sessions(data_dir, count):
    """Write N entries to the unanalyzed-sessions.log."""
    log = data_dir / "unanalyzed-sessions.log"
    lines = [f"2026-03-{20+i:02d}T10:00:00Z session-{i}" for i in range(count)]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_settings(data_dir, nudge_level):
    """Write settings.json with the given nudge level."""
    settings = data_dir / "settings.json"
    settings.write_text(json.dumps({"nudge_level": nudge_level}), encoding="utf-8")


# ---------------------------------------------------------------------------
# count_unanalyzed_sessions
# ---------------------------------------------------------------------------


class TestCountUnanalyzedSessions:
    def test_no_log_returns_zero(self, tmp_path):
        assert ba.count_unanalyzed_sessions(tmp_path) == 0

    def test_empty_log_returns_zero(self, tmp_path):
        (tmp_path / "unanalyzed-sessions.log").write_text("", encoding="utf-8")
        assert ba.count_unanalyzed_sessions(tmp_path) == 0

    def test_counts_lines(self, tmp_path):
        _write_sessions(tmp_path, 7)
        assert ba.count_unanalyzed_sessions(tmp_path) == 7


# ---------------------------------------------------------------------------
# is_locked
# ---------------------------------------------------------------------------


class TestIsLocked:
    def test_no_lock_file(self, tmp_path):
        assert ba.is_locked(tmp_path) is False

    def test_fresh_lock(self, tmp_path):
        lock = tmp_path / "analysis.lock"
        lock.write_text(str(int(time.time())), encoding="utf-8")
        assert ba.is_locked(tmp_path) is True

    def test_stale_lock_removed(self, tmp_path):
        lock = tmp_path / "analysis.lock"
        lock.write_text("old", encoding="utf-8")
        # Set mtime to 10 minutes ago
        old_time = time.time() - 600
        os.utime(lock, (old_time, old_time))
        assert ba.is_locked(tmp_path) is False
        assert not lock.exists()


# ---------------------------------------------------------------------------
# load_nudge_level
# ---------------------------------------------------------------------------


class TestLoadNudgeLevel:
    def test_default_balanced(self, user_data_dir, monkeypatch):
        project, data_dir = user_data_dir
        with patch.object(pi, "_get_git_remote_url", return_value=None):
            assert ba.load_nudge_level(project) == "balanced"

    def test_reads_settings(self, user_data_dir, monkeypatch):
        project, data_dir = user_data_dir
        _write_settings(data_dir, "eager")
        with patch.object(pi, "_get_git_remote_url", return_value=None):
            assert ba.load_nudge_level(project) == "eager"

    def test_invalid_level_falls_back(self, user_data_dir, monkeypatch):
        project, data_dir = user_data_dir
        _write_settings(data_dir, "invalid")
        with patch.object(pi, "_get_git_remote_url", return_value=None):
            assert ba.load_nudge_level(project) == "balanced"


# ---------------------------------------------------------------------------
# Hook mode (main without --run): threshold checks and spawn logic
# ---------------------------------------------------------------------------


class TestHookMode:
    """Test the threshold-checking and spawn-or-skip logic in main()."""

    def test_quiet_mode_no_spawn(self, user_data_dir, monkeypatch):
        project, data_dir = user_data_dir
        _write_settings(data_dir, "quiet")
        _write_sessions(data_dir, 10)

        with patch.object(pi, "_get_git_remote_url", return_value=None), \
             patch("subprocess.Popen") as mock_popen:
            monkeypatch.setattr(
                sys, "argv",
                ["background-analyze.py", "--project-root", str(project)]
            )
            ba.main()
            mock_popen.assert_not_called()

    def test_below_threshold_no_spawn(self, user_data_dir, monkeypatch):
        project, data_dir = user_data_dir
        _write_sessions(data_dir, 3)  # balanced threshold is 5

        with patch.object(pi, "_get_git_remote_url", return_value=None), \
             patch("subprocess.Popen") as mock_popen:
            monkeypatch.setattr(
                sys, "argv",
                ["background-analyze.py", "--project-root", str(project)]
            )
            ba.main()
            mock_popen.assert_not_called()

    def test_above_threshold_spawns(self, user_data_dir, monkeypatch):
        project, data_dir = user_data_dir
        _write_sessions(data_dir, 6)  # above balanced threshold of 5

        with patch.object(pi, "_get_git_remote_url", return_value=None), \
             patch("subprocess.Popen") as mock_popen:
            monkeypatch.setattr(
                sys, "argv",
                ["background-analyze.py", "--project-root", str(project)]
            )
            ba.main()
            mock_popen.assert_called_once()
            # Verify the spawned command includes --run
            args = mock_popen.call_args
            cmd = args[0][0]
            assert "--run" in cmd
            assert "--project-root" in cmd
            # Verify lock file was created
            assert (data_dir / "analysis.lock").exists()

    def test_eager_lower_threshold(self, user_data_dir, monkeypatch):
        project, data_dir = user_data_dir
        _write_settings(data_dir, "eager")
        _write_sessions(data_dir, 2)  # eager threshold is 2

        with patch.object(pi, "_get_git_remote_url", return_value=None), \
             patch("subprocess.Popen") as mock_popen:
            monkeypatch.setattr(
                sys, "argv",
                ["background-analyze.py", "--project-root", str(project)]
            )
            ba.main()
            mock_popen.assert_called_once()

    def test_locked_no_spawn(self, user_data_dir, monkeypatch):
        project, data_dir = user_data_dir
        _write_sessions(data_dir, 10)
        # Create a fresh lock file
        (data_dir / "analysis.lock").write_text(
            str(int(time.time())), encoding="utf-8"
        )

        with patch.object(pi, "_get_git_remote_url", return_value=None), \
             patch("subprocess.Popen") as mock_popen:
            monkeypatch.setattr(
                sys, "argv",
                ["background-analyze.py", "--project-root", str(project)]
            )
            ba.main()
            mock_popen.assert_not_called()

    def test_stale_lock_allows_spawn(self, user_data_dir, monkeypatch):
        project, data_dir = user_data_dir
        _write_sessions(data_dir, 10)
        # Create a stale lock file
        lock = data_dir / "analysis.lock"
        lock.write_text("old", encoding="utf-8")
        old_time = time.time() - 600
        os.utime(lock, (old_time, old_time))

        with patch.object(pi, "_get_git_remote_url", return_value=None), \
             patch("subprocess.Popen") as mock_popen:
            monkeypatch.setattr(
                sys, "argv",
                ["background-analyze.py", "--project-root", str(project)]
            )
            ba.main()
            mock_popen.assert_called_once()

    def test_spawn_uses_start_new_session(self, user_data_dir, monkeypatch):
        """Verify the spawned process is fully detached."""
        project, data_dir = user_data_dir
        _write_sessions(data_dir, 6)

        with patch.object(pi, "_get_git_remote_url", return_value=None), \
             patch("subprocess.Popen") as mock_popen:
            monkeypatch.setattr(
                sys, "argv",
                ["background-analyze.py", "--project-root", str(project)]
            )
            ba.main()
            kwargs = mock_popen.call_args[1]
            assert kwargs["start_new_session"] is True
            assert kwargs["stdin"] == subprocess.DEVNULL
            assert kwargs["stdout"] == subprocess.DEVNULL
            assert kwargs["stderr"] == subprocess.DEVNULL

    def test_spawn_failure_cleans_up_lock(self, user_data_dir, monkeypatch):
        """If Popen fails, the lock file must be removed."""
        project, data_dir = user_data_dir
        _write_sessions(data_dir, 6)

        with patch.object(pi, "_get_git_remote_url", return_value=None), \
             patch("subprocess.Popen", side_effect=OSError("spawn failed")):
            monkeypatch.setattr(
                sys, "argv",
                ["background-analyze.py", "--project-root", str(project)]
            )
            ba.main()
            # Lock must be cleaned up
            assert not (data_dir / "analysis.lock").exists()


# ---------------------------------------------------------------------------
# Run mode (--run): analysis execution and cleanup
# ---------------------------------------------------------------------------


class TestRunMode:
    def test_runs_cache_manager_and_deep_analysis(self, user_data_dir, monkeypatch):
        """After successful Phase A, deep analysis always runs."""
        project, data_dir = user_data_dir
        # Create lock file (as the hook mode would)
        lock = data_dir / "analysis.lock"
        lock.write_text(str(int(time.time())), encoding="utf-8")
        # Create fake unanalyzed log
        _write_sessions(data_dir, 5)

        # Create a fake cache-manager.py in the plugin root
        plugin_root = project / "fake-plugin"
        scripts_dir = plugin_root / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "cache-manager.py").write_text("# stub", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch.object(pi, "_get_git_remote_url", return_value=None), \
             patch("subprocess.run", return_value=mock_result) as mock_run, \
             patch.object(ba, "_run_deep_analysis") as mock_deep:
            ba._run_analysis(project, str(plugin_root), data_dir)

        # Verify cache-manager was called
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "cache-manager.py" in cmd[1]
        assert "--update" in cmd

        # Verify deep analysis was always called (no settings check)
        mock_deep.assert_called_once_with(
            project, str(plugin_root), data_dir
        )

        # Verify lock was cleaned up
        assert not lock.exists()

        # Verify unanalyzed log was cleared
        log = data_dir / "unanalyzed-sessions.log"
        assert log.read_text(encoding="utf-8") == ""

    def test_deep_analysis_runs_regardless_of_settings(self, user_data_dir, monkeypatch):
        """Deep analysis is not gated by nudge_level or any other setting."""
        project, data_dir = user_data_dir
        lock = data_dir / "analysis.lock"
        lock.write_text(str(int(time.time())), encoding="utf-8")
        _write_sessions(data_dir, 5)

        plugin_root = project / "fake-plugin"
        scripts_dir = plugin_root / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "cache-manager.py").write_text("# stub", encoding="utf-8")

        # Write settings with quiet nudge — deep should STILL run
        settings_dir = data_dir
        settings_dir.mkdir(parents=True, exist_ok=True)
        (settings_dir / "settings.json").write_text(
            '{"nudge_level": "quiet"}', encoding="utf-8"
        )

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch.object(pi, "_get_git_remote_url", return_value=None), \
             patch("subprocess.run", return_value=mock_result), \
             patch.object(ba, "_run_deep_analysis") as mock_deep:
            ba._run_analysis(project, str(plugin_root), data_dir)

        # Deep analysis must run regardless of settings
        mock_deep.assert_called_once()

    def test_deep_analysis_not_called_on_phase_a_failure(self, user_data_dir, monkeypatch):
        """Deep analysis should not run if Phase A fails."""
        project, data_dir = user_data_dir
        lock = data_dir / "analysis.lock"
        lock.write_text(str(int(time.time())), encoding="utf-8")
        _write_sessions(data_dir, 5)

        plugin_root = project / "fake-plugin"
        scripts_dir = plugin_root / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "cache-manager.py").write_text("# stub", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.returncode = 1  # failure

        with patch.object(pi, "_get_git_remote_url", return_value=None), \
             patch("subprocess.run", return_value=mock_result), \
             patch.object(ba, "_run_deep_analysis") as mock_deep:
            ba._run_analysis(project, str(plugin_root), data_dir)

        # Deep analysis should NOT be called after Phase A failure
        mock_deep.assert_not_called()

    def test_lock_cleaned_on_error(self, user_data_dir, monkeypatch):
        project, data_dir = user_data_dir
        lock = data_dir / "analysis.lock"
        lock.write_text(str(int(time.time())), encoding="utf-8")

        # Create a fake cache-manager.py
        plugin_root = project / "fake-plugin"
        scripts_dir = plugin_root / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "cache-manager.py").write_text("# stub", encoding="utf-8")

        with patch.object(pi, "_get_git_remote_url", return_value=None), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired(
                 cmd=[], timeout=60
             )):
            ba._run_analysis(project, str(plugin_root), data_dir)

        # Lock must be cleaned up even on failure
        assert not lock.exists()

    def test_log_not_cleared_on_failure(self, user_data_dir, monkeypatch):
        project, data_dir = user_data_dir
        lock = data_dir / "analysis.lock"
        lock.write_text(str(int(time.time())), encoding="utf-8")
        _write_sessions(data_dir, 5)

        plugin_root = project / "fake-plugin"
        scripts_dir = plugin_root / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "cache-manager.py").write_text("# stub", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.returncode = 1  # failure

        with patch.object(pi, "_get_git_remote_url", return_value=None), \
             patch("subprocess.run", return_value=mock_result):
            ba._run_analysis(project, str(plugin_root), data_dir)

        # Log should NOT be cleared on failure
        log = data_dir / "unanalyzed-sessions.log"
        assert ba.count_unanalyzed_sessions(data_dir) == 5

    def test_missing_cache_manager_exits_gracefully(self, user_data_dir, monkeypatch):
        project, data_dir = user_data_dir
        lock = data_dir / "analysis.lock"
        lock.write_text(str(int(time.time())), encoding="utf-8")

        # Plugin root with no cache-manager.py
        plugin_root = project / "empty-plugin"
        plugin_root.mkdir(parents=True)

        with patch.object(pi, "_get_git_remote_url", return_value=None), \
             patch("subprocess.run") as mock_run:
            # Also patch Path(__file__).parent to avoid finding the real one
            ba._run_analysis(project, str(plugin_root), data_dir)

        # Lock cleaned up, no crash
        assert not lock.exists()


# ---------------------------------------------------------------------------
# Deep analysis: prompt building and result parsing
# ---------------------------------------------------------------------------


class TestBuildDeepPrompt:
    def test_builds_prompt_with_proposals_and_pairs(self, tmp_path):
        """Prompt includes script proposals, conversation pairs, and new output instructions."""
        agent_path = tmp_path / "session-analyzer.md"
        agent_path.write_text(
            "---\nname: session-analyzer\n---\nYou are the analyzer.",
            encoding="utf-8",
        )
        proposals = [{"id": "test-rule", "type": "rule", "impact": "high"}]
        pairs = [{"session_id": "s1", "user_text": "use vitest"}]

        prompt = ba._build_deep_prompt(proposals, pairs, agent_path)

        assert prompt is not None
        assert "You are the analyzer." in prompt
        assert "test-rule" in prompt
        assert "use vitest" in prompt
        # Verify the prompt asks for the new output format
        assert "filtered_proposals" in prompt
        assert "additional_proposals" in prompt
        assert "removed_count" in prompt
        assert "removal_reasons" in prompt

    def test_returns_none_for_missing_agent(self, tmp_path):
        agent_path = tmp_path / "nonexistent.md"
        result = ba._build_deep_prompt([], [], agent_path)
        assert result is None

    def test_strips_yaml_frontmatter(self, tmp_path):
        agent_path = tmp_path / "session-analyzer.md"
        agent_path.write_text(
            "---\nname: test\nmodel: sonnet\n---\nBody content here.",
            encoding="utf-8",
        )
        prompt = ba._build_deep_prompt([], [], agent_path)
        assert "Body content here." in prompt
        assert "name: test" not in prompt

    def test_truncates_pairs_to_max(self, tmp_path):
        agent_path = tmp_path / "session-analyzer.md"
        agent_path.write_text("---\nname: test\n---\nAnalyze.", encoding="utf-8")
        pairs = [{"id": f"pair-{i}"} for i in range(50)]

        prompt = ba._build_deep_prompt([], pairs, agent_path)
        # Should only include DEEP_MAX_PAIRS (30)
        assert "pair-29" in prompt
        assert "pair-30" not in prompt


class TestRunDeepAnalysis:
    def test_caches_new_format_result(self, user_data_dir, monkeypatch):
        """Deep analysis caches the new format with filtered/additional proposals."""
        project, data_dir = user_data_dir
        plugin_root = project / "fake-plugin"
        agents_dir = plugin_root / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "session-analyzer.md").write_text(
            "---\nname: test\n---\nAnalyze.", encoding="utf-8"
        )

        # Write cached proposals and transcripts
        cache_dir = data_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "proposals.json").write_text(
            json.dumps({"proposals": [{"id": "p1", "type": "rule"}]}),
            encoding="utf-8",
        )
        (cache_dir / "transcripts.json").write_text(
            json.dumps({
                "version": 1,
                "result": {
                    "conversation_pairs_sample": [
                        {"session_id": "s1", "user_text": "test"}
                    ]
                }
            }),
            encoding="utf-8",
        )

        # Mock the LLM returning new format
        llm_output = json.dumps({
            "filtered_proposals": [{"id": "p1", "type": "rule", "impact": "medium"}],
            "additional_proposals": [{"id": "deep1", "source": "deep_analysis"}],
            "removed_count": 0,
            "removal_reasons": [],
        })
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = llm_output

        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("subprocess.run", return_value=mock_proc):
            ba._run_deep_analysis(project, str(plugin_root), data_dir)

        # Verify the cache was written with the new format
        deep_cache = cache_dir / "deep-analysis.json"
        assert deep_cache.is_file()
        cached = json.loads(deep_cache.read_text(encoding="utf-8"))
        assert "filtered_proposals" in cached
        assert "additional_proposals" in cached
        assert "removed_count" in cached
        assert "removal_reasons" in cached
        assert cached["filtered_proposals"][0]["id"] == "p1"
        assert cached["additional_proposals"][0]["id"] == "deep1"
        assert cached["source"] == "background_deep_analysis"

    def test_handles_legacy_array_output(self, user_data_dir, monkeypatch):
        """If LLM returns a plain array (legacy), convert to new format."""
        project, data_dir = user_data_dir
        plugin_root = project / "fake-plugin"
        agents_dir = plugin_root / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "session-analyzer.md").write_text(
            "---\nname: test\n---\nAnalyze.", encoding="utf-8"
        )

        cache_dir = data_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        script_proposals = [{"id": "p1", "type": "rule"}]
        (cache_dir / "proposals.json").write_text(
            json.dumps({"proposals": script_proposals}),
            encoding="utf-8",
        )
        (cache_dir / "transcripts.json").write_text(
            json.dumps({
                "version": 1,
                "result": {
                    "conversation_pairs_sample": [
                        {"session_id": "s1", "user_text": "test"}
                    ]
                }
            }),
            encoding="utf-8",
        )

        # LLM returns legacy array format
        llm_output = json.dumps([{"id": "deep1", "source": "deep_analysis"}])
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = llm_output

        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("subprocess.run", return_value=mock_proc):
            ba._run_deep_analysis(project, str(plugin_root), data_dir)

        deep_cache = cache_dir / "deep-analysis.json"
        cached = json.loads(deep_cache.read_text(encoding="utf-8"))
        # Legacy array should be converted: proposals become filtered, array becomes additional
        assert cached["filtered_proposals"] == script_proposals
        assert cached["additional_proposals"] == [{"id": "deep1", "source": "deep_analysis"}]
        assert cached["removed_count"] == 0

    def test_skips_when_no_pairs(self, user_data_dir, monkeypatch):
        """Deep analysis should skip when no conversation pairs exist."""
        project, data_dir = user_data_dir
        plugin_root = project / "fake-plugin"
        agents_dir = plugin_root / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "session-analyzer.md").write_text(
            "---\nname: test\n---\nAnalyze.", encoding="utf-8"
        )

        cache_dir = data_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "proposals.json").write_text(
            json.dumps({"proposals": []}), encoding="utf-8"
        )
        # No conversation pairs
        (cache_dir / "transcripts.json").write_text(
            json.dumps({"version": 1, "result": {"conversation_pairs_sample": []}}),
            encoding="utf-8",
        )

        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("subprocess.run") as mock_run:
            ba._run_deep_analysis(project, str(plugin_root), data_dir)

        # subprocess.run should not be called (no pairs to analyze)
        mock_run.assert_not_called()

    def test_skips_when_no_claude_cli(self, user_data_dir, monkeypatch):
        """Deep analysis should skip gracefully when claude CLI is not installed."""
        project, data_dir = user_data_dir

        with patch("shutil.which", return_value=None), \
             patch("subprocess.run") as mock_run:
            ba._run_deep_analysis(project, str(project), data_dir)

        mock_run.assert_not_called()

    def test_handles_llm_failure(self, user_data_dir, monkeypatch):
        """Deep analysis handles LLM process failure gracefully."""
        project, data_dir = user_data_dir
        plugin_root = project / "fake-plugin"
        agents_dir = plugin_root / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "session-analyzer.md").write_text(
            "---\nname: test\n---\nAnalyze.", encoding="utf-8"
        )

        cache_dir = data_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "proposals.json").write_text(
            json.dumps({"proposals": [{"id": "p1"}]}), encoding="utf-8"
        )
        (cache_dir / "transcripts.json").write_text(
            json.dumps({
                "version": 1,
                "result": {
                    "conversation_pairs_sample": [{"session_id": "s1", "user_text": "t"}]
                }
            }),
            encoding="utf-8",
        )

        mock_proc = MagicMock()
        mock_proc.returncode = 1  # failure

        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("subprocess.run", return_value=mock_proc):
            # Should not raise
            ba._run_deep_analysis(project, str(plugin_root), data_dir)

        # No deep cache should be written
        assert not (cache_dir / "deep-analysis.json").is_file()

    def test_strips_markdown_fences_from_output(self, user_data_dir, monkeypatch):
        """LLM output wrapped in markdown fences should be handled."""
        project, data_dir = user_data_dir
        plugin_root = project / "fake-plugin"
        agents_dir = plugin_root / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "session-analyzer.md").write_text(
            "---\nname: test\n---\nAnalyze.", encoding="utf-8"
        )

        cache_dir = data_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "proposals.json").write_text(
            json.dumps({"proposals": []}), encoding="utf-8"
        )
        (cache_dir / "transcripts.json").write_text(
            json.dumps({
                "version": 1,
                "result": {
                    "conversation_pairs_sample": [{"session_id": "s1", "user_text": "t"}]
                }
            }),
            encoding="utf-8",
        )

        result_obj = {
            "filtered_proposals": [],
            "additional_proposals": [],
            "removed_count": 0,
            "removal_reasons": [],
        }
        fenced_output = f"```json\n{json.dumps(result_obj)}\n```"
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = fenced_output

        with patch("shutil.which", return_value="/usr/bin/claude"), \
             patch("subprocess.run", return_value=mock_proc):
            ba._run_deep_analysis(project, str(plugin_root), data_dir)

        cached = json.loads(
            (cache_dir / "deep-analysis.json").read_text(encoding="utf-8")
        )
        assert cached["removed_count"] == 0

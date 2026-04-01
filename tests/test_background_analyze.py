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
    def test_runs_cache_manager(self, user_data_dir, monkeypatch):
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
             patch("subprocess.run", return_value=mock_result) as mock_run:
            ba._run_analysis(project, str(plugin_root), data_dir)

        # Verify cache-manager was called
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "cache-manager.py" in cmd[1]
        assert "--update" in cmd

        # Verify lock was cleaned up
        assert not lock.exists()

        # Verify unanalyzed log was cleared
        log = data_dir / "unanalyzed-sessions.log"
        assert log.read_text(encoding="utf-8") == ""

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

"""Integration tests for find_all_project_session_dirs — the 5-strategy transcript discovery function.

Tests the full discovery pipeline with controlled filesystem layouts and mocked
git subprocess calls. Uses monkeypatch + tmp_path (Option A from the test plan)
to redirect Path.home() and subprocess.run.
"""

import importlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Import module under test
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "forge" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
at = importlib.import_module("analyze-transcripts")


# ---------------------------------------------------------------------------
# Test environment
# ---------------------------------------------------------------------------

class DiscoveryEnv:
    """Controlled environment for transcript discovery tests.

    Provides helpers to create encoded project dirs, git repos, worktree
    output, and repo-index.json — all within a fake home directory.
    """

    def __init__(self, tmp_path, fake_home, claude_projects):
        self.tmp_path = tmp_path
        self.fake_home = fake_home
        self.claude_projects = claude_projects
        self._git_remotes = {}       # resolved path str -> remote URL
        self._worktree_output = ""

    def make_project_dir(self, real_path, *, with_jsonl=True, mtime=None):
        """Create a real directory and its encoded counterpart in ~/.claude/projects/.

        Args:
            real_path: The actual project directory (created if missing).
            with_jsonl: Whether to create a dummy JSONL file in the encoded dir.
            mtime: Optional mtime to set on the JSONL file (for sort-order tests).

        Returns:
            The encoded directory name.
        """
        real_path = Path(real_path)
        real_path.mkdir(parents=True, exist_ok=True)
        encoded = at._encode_path_as_project_dir(str(real_path))
        proj_dir = self.claude_projects / encoded
        proj_dir.mkdir(parents=True, exist_ok=True)
        if with_jsonl:
            jsonl = proj_dir / "session-1.jsonl"
            jsonl.write_text(
                '{"type":"user","message":{"role":"user","content":"hi"}}\n'
            )
            if mtime is not None:
                os.utime(jsonl, (mtime, mtime))
        return encoded

    def make_git_repo(self, real_path, remote_url):
        """Mark a real directory as a git repo with the given remote URL."""
        real_path = Path(real_path)
        real_path.mkdir(parents=True, exist_ok=True)
        (real_path / ".git").mkdir(parents=True, exist_ok=True)
        self._git_remotes[str(real_path.resolve())] = remote_url

    def set_worktree_output(self, worktree_paths):
        """Configure the mocked `git worktree list --porcelain` output.

        Args:
            worktree_paths: List of absolute path strings.
        """
        lines = []
        for wt in worktree_paths:
            lines.append("worktree {}".format(wt))
            lines.append("")
        self._worktree_output = "\n".join(lines)

    def make_repo_index(self, index_data):
        """Create ~/.claude/forge/repo-index.json."""
        forge_dir = self.fake_home / ".claude" / "forge"
        forge_dir.mkdir(parents=True, exist_ok=True)
        (forge_dir / "repo-index.json").write_text(json.dumps(index_data))


@pytest.fixture
def discovery_env(tmp_path, monkeypatch):
    """Build a controlled environment for find_all_project_session_dirs tests."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    claude_projects = fake_home / ".claude" / "projects"
    claude_projects.mkdir(parents=True)

    env = DiscoveryEnv(tmp_path, fake_home, claude_projects)

    # Redirect Path.home() to our fake home
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    # Mock subprocess.run to handle git commands deterministically
    def mock_subprocess_run(cmd, **kwargs):
        if not isinstance(cmd, list) or not cmd or cmd[0] != "git":
            raise OSError("unexpected subprocess call in test: {}".format(cmd))

        # git -C <path> remote get-url origin
        if "remote" in cmd and "get-url" in cmd:
            try:
                path_idx = cmd.index("-C") + 1
            except ValueError:
                path_idx = None
            if path_idx and path_idx < len(cmd):
                resolved = str(Path(cmd[path_idx]).resolve())
                url = env._git_remotes.get(resolved)
                if url:
                    mock = MagicMock()
                    mock.returncode = 0
                    mock.stdout = url + "\n"
                    return mock
            # No remote configured for this path
            mock = MagicMock()
            mock.returncode = 128
            mock.stdout = ""
            return mock

        # git -C <path> worktree list --porcelain
        if "worktree" in cmd and "list" in cmd:
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = env._worktree_output
            return mock

        # Fallback: unknown git command
        mock = MagicMock()
        mock.returncode = 1
        mock.stdout = ""
        return mock

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

    return env


# ---------------------------------------------------------------------------
# Strategy 1: Exact path match
# ---------------------------------------------------------------------------

class TestStrategy1ExactMatch:
    """Encode current project path → find matching dir in ~/.claude/projects/."""

    def test_finds_exact_match(self, discovery_env):
        project = discovery_env.tmp_path / "myproject"
        discovery_env.make_git_repo(project, "https://github.com/org/repo.git")
        discovery_env.make_project_dir(project)

        result = at.find_all_project_session_dirs(project)
        assert len(result) == 1
        assert result[0].name == at._encode_path_as_project_dir(str(project))

    def test_returns_empty_when_no_match(self, discovery_env):
        project = discovery_env.tmp_path / "myproject"
        discovery_env.make_git_repo(project, "https://github.com/org/repo.git")
        # Don't create the encoded dir in ~/.claude/projects/

        result = at.find_all_project_session_dirs(project)
        assert result == []

    def test_exact_match_works_without_remote(self, discovery_env):
        """Strategy 1 doesn't need a git remote — it's pure path encoding."""
        project = discovery_env.tmp_path / "local-only"
        project.mkdir(parents=True)
        # No .git dir → no remote
        discovery_env.make_project_dir(project)

        result = at.find_all_project_session_dirs(project)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Strategy 2: Git worktree list
# ---------------------------------------------------------------------------

class TestStrategy2WorktreeList:
    """Mock `git worktree list --porcelain` and verify worktree dirs are found."""

    def test_finds_worktree_dirs(self, discovery_env):
        main = discovery_env.tmp_path / "workspace" / "main"
        wt1 = discovery_env.tmp_path / "workspace" / "feature-a"
        wt2 = discovery_env.tmp_path / "workspace" / "feature-b"

        discovery_env.make_git_repo(main, "https://github.com/org/repo.git")
        discovery_env.make_project_dir(main)
        discovery_env.make_project_dir(wt1)
        discovery_env.make_project_dir(wt2)
        discovery_env.set_worktree_output([str(main), str(wt1), str(wt2)])

        result = at.find_all_project_session_dirs(main)
        assert len(result) == 3

    def test_skips_worktree_without_project_dir(self, discovery_env):
        """A worktree whose encoded dir doesn't exist is silently skipped."""
        main = discovery_env.tmp_path / "workspace" / "main"
        wt1 = discovery_env.tmp_path / "workspace" / "feature-a"

        discovery_env.make_git_repo(main, "https://github.com/org/repo.git")
        discovery_env.make_project_dir(main)
        # wt1 exists on disk but has no encoded dir in ~/.claude/projects/
        wt1.mkdir(parents=True, exist_ok=True)
        discovery_env.set_worktree_output([str(main), str(wt1)])

        result = at.find_all_project_session_dirs(main)
        assert len(result) == 1  # only main

    def test_skipped_when_no_remote(self, discovery_env):
        """Strategy 2 requires a git remote — skipped for local-only repos."""
        project = discovery_env.tmp_path / "local-only"
        project.mkdir(parents=True)
        discovery_env.make_project_dir(project)
        # No .git dir → no remote → strategy 2 skipped
        discovery_env.set_worktree_output([str(project)])

        result = at.find_all_project_session_dirs(project)
        assert len(result) == 1  # only strategy 1 match


# ---------------------------------------------------------------------------
# Strategy 3: Forward index (repo-index.json)
# ---------------------------------------------------------------------------

class TestStrategy3ForwardIndex:
    """Verify dirs from repo-index.json are found when remote URL matches."""

    def test_finds_indexed_dirs(self, discovery_env):
        project = discovery_env.tmp_path / "myproject"
        indexed_dir = discovery_env.tmp_path / "old-checkout"

        discovery_env.make_git_repo(project, "https://github.com/org/repo.git")
        discovery_env.make_project_dir(project)
        encoded_old = discovery_env.make_project_dir(indexed_dir)

        discovery_env.make_repo_index({
            "https://github.com/org/repo.git": [encoded_old],
        })

        result = at.find_all_project_session_dirs(project)
        result_names = {d.name for d in result}
        assert encoded_old in result_names

    def test_normalizes_url_trailing_git(self, discovery_env):
        """Remote URL comparison ignores trailing .git and case."""
        project = discovery_env.tmp_path / "myproject"
        indexed_dir = discovery_env.tmp_path / "other-checkout"

        discovery_env.make_git_repo(project, "https://github.com/org/repo.git")
        discovery_env.make_project_dir(project)
        encoded_other = discovery_env.make_project_dir(indexed_dir)

        # Index has URL without .git suffix and different casing
        discovery_env.make_repo_index({
            "https://GitHub.com/org/repo": [encoded_other],
        })

        result = at.find_all_project_session_dirs(project)
        result_names = {d.name for d in result}
        assert encoded_other in result_names

    def test_rejects_different_remote(self, discovery_env):
        """Dirs indexed under a different remote URL must NOT be included."""
        project = discovery_env.tmp_path / "myproject"
        unrelated = discovery_env.tmp_path / "unrelated"

        discovery_env.make_git_repo(project, "https://github.com/org/repo.git")
        discovery_env.make_project_dir(project)
        encoded_unrelated = discovery_env.make_project_dir(unrelated)

        discovery_env.make_repo_index({
            "https://github.com/other-org/other-repo.git": [encoded_unrelated],
        })

        result = at.find_all_project_session_dirs(project)
        result_names = {d.name for d in result}
        assert encoded_unrelated not in result_names

    def test_skips_missing_dir(self, discovery_env):
        """Indexed dir name that doesn't exist on disk is silently skipped."""
        project = discovery_env.tmp_path / "myproject"
        discovery_env.make_git_repo(project, "https://github.com/org/repo.git")
        discovery_env.make_project_dir(project)

        discovery_env.make_repo_index({
            "https://github.com/org/repo.git": ["nonexistent-dir-name"],
        })

        result = at.find_all_project_session_dirs(project)
        assert len(result) == 1  # only exact match


# ---------------------------------------------------------------------------
# Strategy 4: Workspace-prefix heuristic
# ---------------------------------------------------------------------------

class TestStrategy4WorkspacePrefix:
    """Verify prefix heuristic finds sibling worktrees and rejects cross-project dirs."""

    def test_finds_sibling_worktree_by_prefix(self, discovery_env):
        """A dir sharing the workspace prefix with a known worktree is found."""
        workspace = discovery_env.tmp_path / "ws"
        main = workspace / "main"
        feature = workspace / "feature"
        old_branch = workspace / "old-branch"

        discovery_env.make_git_repo(main, "https://github.com/org/repo.git")
        discovery_env.make_git_repo(feature, "https://github.com/org/repo.git")
        discovery_env.make_git_repo(old_branch, "https://github.com/org/repo.git")

        discovery_env.make_project_dir(main)
        discovery_env.make_project_dir(feature)
        encoded_old = discovery_env.make_project_dir(old_branch)

        # Worktree list includes main + feature (but NOT old-branch)
        discovery_env.set_worktree_output([str(main), str(feature)])

        result = at.find_all_project_session_dirs(main)
        result_names = {d.name for d in result}
        # old-branch should be found by workspace-prefix heuristic
        assert encoded_old in result_names
        assert len(result) == 3

    def test_rejects_sibling_with_different_remote(self, discovery_env):
        """CRITICAL: A sibling dir with a different git remote must NOT be included."""
        workspace = discovery_env.tmp_path / "ws"
        main = workspace / "main"
        feature = workspace / "feature"
        different_repo = workspace / "other-project"

        discovery_env.make_git_repo(main, "https://github.com/org/repo.git")
        discovery_env.make_git_repo(feature, "https://github.com/org/repo.git")
        discovery_env.make_git_repo(different_repo, "https://github.com/org/DIFFERENT-repo.git")

        discovery_env.make_project_dir(main)
        discovery_env.make_project_dir(feature)
        encoded_different = discovery_env.make_project_dir(different_repo)

        discovery_env.set_worktree_output([str(main), str(feature)])

        result = at.find_all_project_session_dirs(main)
        result_names = {d.name for d in result}
        assert encoded_different not in result_names

    def test_excludes_exact_match_from_prefix_source(self, discovery_env):
        """Strategy 4 only derives prefixes from non-exact matches.

        The main checkout's parent dir could contain unrelated repos,
        so it must not be used as a workspace prefix source.
        """
        workspace = discovery_env.tmp_path / "ws"
        main = workspace / "main"
        unrelated = workspace / "unrelated"

        discovery_env.make_git_repo(main, "https://github.com/org/repo.git")
        discovery_env.make_git_repo(unrelated, "https://github.com/org/OTHER.git")

        discovery_env.make_project_dir(main)
        encoded_unrelated = discovery_env.make_project_dir(unrelated)

        # No worktree list (only main itself) — strategy 4 has no
        # worktree matches to derive prefixes from.
        discovery_env.set_worktree_output([str(main)])

        result = at.find_all_project_session_dirs(main)
        result_names = {d.name for d in result}
        assert encoded_unrelated not in result_names


# ---------------------------------------------------------------------------
# Strategy 5: Git remote scan fallback
# ---------------------------------------------------------------------------

class TestStrategy5GitRemoteScan:
    """Verify the expensive fallback scan and its performance guard."""

    def test_scan_finds_dirs_when_few_matches(self, discovery_env):
        """When strategies 1-4 find < 2 matches, strategy 5 scans all dirs."""
        project = discovery_env.tmp_path / "myproject"
        other_checkout = discovery_env.tmp_path / "other-checkout"

        remote = "https://github.com/org/repo.git"
        discovery_env.make_git_repo(project, remote)
        discovery_env.make_git_repo(other_checkout, remote)

        discovery_env.make_project_dir(project)
        encoded_other = discovery_env.make_project_dir(other_checkout)

        # No worktree output, no index — only strategy 1 matches (1 < 2)
        result = at.find_all_project_session_dirs(project)
        result_names = {d.name for d in result}
        assert encoded_other in result_names

    def test_scan_skipped_when_enough_matches(self, discovery_env):
        """When strategies 1-4 find >= 2 matches, strategy 5 is skipped (perf guard)."""
        workspace = discovery_env.tmp_path / "ws"
        main = workspace / "main"
        feature = workspace / "feature"
        extra = discovery_env.tmp_path / "extra-checkout"

        remote = "https://github.com/org/repo.git"
        discovery_env.make_git_repo(main, remote)
        discovery_env.make_git_repo(feature, remote)
        discovery_env.make_git_repo(extra, remote)

        discovery_env.make_project_dir(main)
        discovery_env.make_project_dir(feature)
        encoded_extra = discovery_env.make_project_dir(extra)

        # Worktree list gives us 2 matches → strategy 5 should NOT run
        discovery_env.set_worktree_output([str(main), str(feature)])

        result = at.find_all_project_session_dirs(main)
        result_names = {d.name for d in result}
        # extra is not in worktree list, not in index, and strategy 5 is skipped
        assert encoded_extra not in result_names

    def test_scan_rejects_different_remote(self, discovery_env):
        """Strategy 5 verifies git remote before accepting a dir."""
        project = discovery_env.tmp_path / "myproject"
        unrelated = discovery_env.tmp_path / "unrelated"

        discovery_env.make_git_repo(project, "https://github.com/org/repo.git")
        discovery_env.make_git_repo(unrelated, "https://github.com/org/other.git")

        discovery_env.make_project_dir(project)
        encoded_unrelated = discovery_env.make_project_dir(unrelated)

        result = at.find_all_project_session_dirs(project)
        result_names = {d.name for d in result}
        assert encoded_unrelated not in result_names


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Cover boundary conditions and error paths."""

    def test_no_claude_projects_dir(self, tmp_path, monkeypatch):
        """Returns empty list when ~/.claude/projects/ doesn't exist."""
        fake_home = tmp_path / "empty-home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

        project = tmp_path / "myproject"
        project.mkdir()

        result = at.find_all_project_session_dirs(project)
        assert result == []

    def test_no_git_remote_only_strategy1(self, discovery_env):
        """Local-only repo (no remote) — only strategy 1 runs, strategies 2-5 skipped."""
        project = discovery_env.tmp_path / "local-only"
        project.mkdir(parents=True)
        # No .git dir → _get_repo_remote returns None
        discovery_env.make_project_dir(project)

        result = at.find_all_project_session_dirs(project)
        assert len(result) == 1

    def test_subprocess_timeout(self, discovery_env, monkeypatch):
        """Git subprocess timeout doesn't crash — graceful degradation."""
        project = discovery_env.tmp_path / "myproject"
        discovery_env.make_git_repo(project, "https://github.com/org/repo.git")
        discovery_env.make_project_dir(project)

        def timeout_subprocess(cmd, **kwargs):
            # Let _get_repo_remote succeed, timeout everything else
            if "remote" in cmd and "get-url" in cmd:
                mock = MagicMock()
                mock.returncode = 0
                mock.stdout = "https://github.com/org/repo.git\n"
                return mock
            raise subprocess.TimeoutExpired(cmd, 5)

        monkeypatch.setattr(subprocess, "run", timeout_subprocess)

        # Should not raise — graceful fallback
        result = at.find_all_project_session_dirs(project)
        assert len(result) >= 1  # at least strategy 1

    def test_oserror_git_not_found(self, discovery_env, monkeypatch):
        """OSError (e.g., git binary missing) doesn't crash — graceful degradation."""
        project = discovery_env.tmp_path / "myproject"
        discovery_env.make_git_repo(project, "https://github.com/org/repo.git")
        discovery_env.make_project_dir(project)

        def oserror_subprocess(cmd, **kwargs):
            raise OSError("No such file or directory: 'git'")

        monkeypatch.setattr(subprocess, "run", oserror_subprocess)

        # _get_repo_remote → _get_git_remote catches OSError → returns None
        # All remote-dependent strategies skipped; strategy 1 still works
        result = at.find_all_project_session_dirs(project)
        assert len(result) == 1

    def test_encoded_dir_without_real_path(self, discovery_env):
        """An encoded dir whose decoded path doesn't exist on disk is handled safely."""
        project = discovery_env.tmp_path / "myproject"
        discovery_env.make_git_repo(project, "https://github.com/org/repo.git")
        discovery_env.make_project_dir(project)

        # Create a project dir whose real path was deleted
        ghost_encoded = at._encode_path_as_project_dir("/nonexistent/deleted/project")
        ghost_dir = discovery_env.claude_projects / ghost_encoded
        ghost_dir.mkdir()
        (ghost_dir / "session.jsonl").write_text("{}\n")

        result = at.find_all_project_session_dirs(project)
        result_names = {d.name for d in result}
        assert ghost_encoded not in result_names

    def test_results_sorted_by_mtime(self, discovery_env):
        """Results are sorted by most recent JSONL file modification time (newest first)."""
        workspace = discovery_env.tmp_path / "ws"
        main = workspace / "main"
        old_wt = workspace / "old"
        new_wt = workspace / "new"

        remote = "https://github.com/org/repo.git"
        discovery_env.make_git_repo(main, remote)
        discovery_env.make_git_repo(old_wt, remote)
        discovery_env.make_git_repo(new_wt, remote)

        now = time.time()
        discovery_env.make_project_dir(main, mtime=now - 100)
        discovery_env.make_project_dir(old_wt, mtime=now - 200)
        discovery_env.make_project_dir(new_wt, mtime=now)

        discovery_env.set_worktree_output([str(main), str(old_wt), str(new_wt)])

        result = at.find_all_project_session_dirs(main)
        assert len(result) == 3
        # Newest first: new_wt, main, old_wt
        expected_order = [
            at._encode_path_as_project_dir(str(new_wt)),
            at._encode_path_as_project_dir(str(main)),
            at._encode_path_as_project_dir(str(old_wt)),
        ]
        actual_order = [d.name for d in result]
        assert actual_order == expected_order

    def test_mtime_uses_max_across_multiple_jsonl(self, discovery_env):
        """With multiple JSONL files, sorting uses the most recent file's mtime."""
        project_old = discovery_env.tmp_path / "proj-old"
        project_new = discovery_env.tmp_path / "proj-new"

        remote = "https://github.com/org/repo.git"
        discovery_env.make_git_repo(project_old, remote)
        discovery_env.make_git_repo(project_new, remote)

        now = time.time()
        # proj-old: one old file, one very old file → max is old
        encoded_old = discovery_env.make_project_dir(project_old, mtime=now - 200)
        old_dir = discovery_env.claude_projects / encoded_old
        extra = old_dir / "session-2.jsonl"
        extra.write_text("{}\n")
        os.utime(extra, (now - 300, now - 300))

        # proj-new: one old file, one recent file → max is recent
        encoded_new = discovery_env.make_project_dir(project_new, mtime=now - 500)
        new_dir = discovery_env.claude_projects / encoded_new
        recent = new_dir / "session-2.jsonl"
        recent.write_text("{}\n")
        os.utime(recent, (now, now))

        result = at.find_all_project_session_dirs(project_old)
        assert len(result) == 2
        # proj-new has the most recent single file, so it comes first
        assert result[0].name == encoded_new
        assert result[1].name == encoded_old

    def test_dir_without_jsonl_still_included(self, discovery_env):
        """A matched dir with no JSONL files gets mtime=0 but is still returned."""
        project = discovery_env.tmp_path / "myproject"
        discovery_env.make_git_repo(project, "https://github.com/org/repo.git")
        discovery_env.make_project_dir(project, with_jsonl=False)

        result = at.find_all_project_session_dirs(project)
        assert len(result) == 1

    def test_deduplication_across_strategies(self, discovery_env):
        """A dir found by multiple strategies is only returned once."""
        project = discovery_env.tmp_path / "myproject"
        remote = "https://github.com/org/repo.git"
        discovery_env.make_git_repo(project, remote)
        encoded = discovery_env.make_project_dir(project)

        # Strategy 1: exact match
        # Strategy 2: worktree list
        discovery_env.set_worktree_output([str(project)])
        # Strategy 3: forward index
        discovery_env.make_repo_index({remote: [encoded]})

        result = at.find_all_project_session_dirs(project)
        assert len(result) == 1

    def test_malformed_repo_index(self, discovery_env):
        """Malformed repo-index.json doesn't crash — logged and skipped."""
        project = discovery_env.tmp_path / "myproject"
        discovery_env.make_git_repo(project, "https://github.com/org/repo.git")
        discovery_env.make_project_dir(project)

        forge_dir = discovery_env.fake_home / ".claude" / "forge"
        forge_dir.mkdir(parents=True, exist_ok=True)
        (forge_dir / "repo-index.json").write_text("not valid json {{{")

        # Should not raise
        result = at.find_all_project_session_dirs(project)
        assert len(result) >= 1


# ---------------------------------------------------------------------------
# Multi-strategy integration
# ---------------------------------------------------------------------------

class TestMultiStrategyIntegration:
    """End-to-end tests exercising multiple strategies together."""

    def test_full_discovery_across_all_strategies(self, discovery_env):
        """Verify that strategies compose correctly and all valid dirs are found."""
        workspace = discovery_env.tmp_path / "ws"
        remote = "https://github.com/org/repo.git"

        # Main checkout (strategy 1: exact match)
        main = workspace / "main"
        discovery_env.make_git_repo(main, remote)
        discovery_env.make_project_dir(main)

        # Active worktree (strategy 2: worktree list)
        feature = workspace / "feature"
        discovery_env.make_project_dir(feature)
        discovery_env.set_worktree_output([str(main), str(feature)])

        # Indexed old checkout (strategy 3: forward index)
        old_checkout = discovery_env.tmp_path / "old"
        encoded_old = discovery_env.make_project_dir(old_checkout)
        discovery_env.make_repo_index({remote: [encoded_old]})

        # Deleted worktree sibling (strategy 4: workspace prefix from feature)
        stale = workspace / "stale-branch"
        discovery_env.make_git_repo(stale, remote)
        discovery_env.make_project_dir(stale)

        result = at.find_all_project_session_dirs(main)
        result_names = {d.name for d in result}

        assert at._encode_path_as_project_dir(str(main)) in result_names
        assert at._encode_path_as_project_dir(str(feature)) in result_names
        assert encoded_old in result_names
        assert at._encode_path_as_project_dir(str(stale)) in result_names
        assert len(result) == 4

    def test_ssh_remote_url_matching(self, discovery_env):
        """SSH remote URLs work through the full discovery pipeline."""
        project = discovery_env.tmp_path / "myproject"
        indexed_dir = discovery_env.tmp_path / "worktree"

        ssh_remote = "git@github.com:org/repo.git"
        discovery_env.make_git_repo(project, ssh_remote)
        discovery_env.make_project_dir(project)
        encoded_wt = discovery_env.make_project_dir(indexed_dir)

        # Index uses same SSH URL without .git suffix
        discovery_env.make_repo_index({
            "git@github.com:org/repo": [encoded_wt],
        })

        result = at.find_all_project_session_dirs(project)
        result_names = {d.name for d in result}
        assert encoded_wt in result_names

    def test_nested_git_repo(self, discovery_env):
        """Project nested inside a git repo (.git in parent) still discovers correctly."""
        repo_root = discovery_env.tmp_path / "monorepo"
        project = repo_root / "packages" / "frontend"

        # .git is at repo_root, NOT at project
        discovery_env.make_git_repo(repo_root, "https://github.com/org/monorepo.git")
        project.mkdir(parents=True)
        discovery_env.make_project_dir(project)

        # _get_repo_remote walks up from project → packages → monorepo, finds .git
        # Then calls _get_git_remote(str(monorepo)) which must be in the mock
        result = at.find_all_project_session_dirs(project)
        assert len(result) == 1

    def test_mixed_remotes_isolation(self, discovery_env):
        """Two repos in the same workspace — each only discovers its own dirs."""
        workspace = discovery_env.tmp_path / "ws"
        repo_a = workspace / "repo-a"
        repo_b = workspace / "repo-b"
        wt_a = workspace / "wt-a"

        remote_a = "https://github.com/org/repo-a.git"
        remote_b = "https://github.com/org/repo-b.git"

        discovery_env.make_git_repo(repo_a, remote_a)
        discovery_env.make_git_repo(repo_b, remote_b)
        discovery_env.make_git_repo(wt_a, remote_a)

        discovery_env.make_project_dir(repo_a)
        encoded_b = discovery_env.make_project_dir(repo_b)
        discovery_env.make_project_dir(wt_a)

        discovery_env.set_worktree_output([str(repo_a), str(wt_a)])

        # Search from repo_a
        result = at.find_all_project_session_dirs(repo_a)
        result_names = {d.name for d in result}
        assert encoded_b not in result_names
        assert len(result) == 2  # repo_a + wt_a

"""Tests for project_identity.py — project hash, user data dir, migration."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "forge" / "scripts"))
import project_identity as pi


class TestComputeProjectHash:
    """Verify stable hash generation from git remote URLs."""

    def test_same_url_produces_same_hash(self, tmp_path):
        url = "https://github.com/org/repo.git"
        with patch.object(pi, "_get_git_remote_url", return_value=url):
            h1 = pi.compute_project_hash(tmp_path)
            h2 = pi.compute_project_hash(tmp_path)
        assert h1 == h2

    def test_hash_is_12_hex_chars(self, tmp_path):
        with patch.object(
            pi, "_get_git_remote_url",
            return_value="https://github.com/org/repo.git",
        ):
            h = pi.compute_project_hash(tmp_path)
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_urls_produce_different_hashes(self, tmp_path):
        with patch.object(
            pi, "_get_git_remote_url",
            return_value="https://github.com/org/repo-a.git",
        ):
            h1 = pi.compute_project_hash(tmp_path)
        with patch.object(
            pi, "_get_git_remote_url",
            return_value="https://github.com/org/repo-b.git",
        ):
            h2 = pi.compute_project_hash(tmp_path)
        assert h1 != h2

    def test_strips_credentials_before_hashing(self, tmp_path):
        with patch.object(
            pi, "_get_git_remote_url",
            return_value="https://token@github.com/org/repo.git",
        ):
            h_with_creds = pi.compute_project_hash(tmp_path)
        with patch.object(
            pi, "_get_git_remote_url",
            return_value="https://github.com/org/repo.git",
        ):
            h_clean = pi.compute_project_hash(tmp_path)
        assert h_with_creds == h_clean

    def test_fallback_to_path_when_no_remote(self, tmp_path):
        with patch.object(pi, "_get_git_remote_url", return_value=None):
            h = pi.compute_project_hash(tmp_path)
        # Path-based fallback: replace / with -, strip leading -
        expected = str(tmp_path.resolve()).replace("/", "-").lstrip("-")
        assert h == expected

    def test_two_worktrees_same_remote_produce_same_hash(self, tmp_path):
        wt1 = tmp_path / "worktree-1"
        wt2 = tmp_path / "worktree-2"
        wt1.mkdir()
        wt2.mkdir()
        url = "https://github.com/org/shared-repo.git"
        with patch.object(pi, "_get_git_remote_url", return_value=url):
            h1 = pi.compute_project_hash(wt1)
            h2 = pi.compute_project_hash(wt2)
        assert h1 == h2


class TestGetUserDataDir:
    """Verify user-level directory creation and path."""

    def test_returns_path_under_home(self, tmp_path):
        with patch.object(pi, "_get_git_remote_url", return_value=None):
            d = pi.get_user_data_dir(tmp_path)
        assert ".claude" in str(d)
        assert "forge" in str(d)
        assert "projects" in str(d)

    def test_creates_directory(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
        with patch.object(pi, "_get_git_remote_url", return_value=None):
            d = pi.get_user_data_dir(tmp_path)
        assert d.is_dir()


class TestResolveUserFile:
    """Verify migrate-on-read behavior."""

    def test_rejects_path_traversal(self, tmp_path):
        with pytest.raises(ValueError, match="\\.\\."):
            pi.resolve_user_file(tmp_path, "../etc/passwd")

    def test_returns_new_path_when_file_exists_there(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

        with patch.object(pi, "_get_git_remote_url", return_value=None):
            data_dir = pi.get_user_data_dir(tmp_path)
        (data_dir / "settings.json").write_text('{"nudge_level":"quiet"}')

        with patch.object(pi, "_get_git_remote_url", return_value=None):
            result = pi.resolve_user_file(tmp_path, "settings.json")
        assert result == data_dir / "settings.json"

    def test_migrates_from_legacy_location(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

        # Set up legacy file
        legacy_dir = tmp_path / ".claude" / "forge"
        legacy_dir.mkdir(parents=True)
        legacy_file = legacy_dir / "dismissed.json"
        legacy_file.write_text('[{"id":"test"}]')

        with patch.object(pi, "_get_git_remote_url", return_value=None):
            result = pi.resolve_user_file(tmp_path, "dismissed.json")

        # File migrated to new location
        assert result.is_file()
        assert json.loads(result.read_text()) == [{"id": "test"}]
        # Legacy file removed
        assert not legacy_file.exists()

    def test_returns_new_path_when_neither_exists(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

        with patch.object(pi, "_get_git_remote_url", return_value=None):
            result = pi.resolve_user_file(tmp_path, "settings.json")
        # Returns the new-location path even though file doesn't exist
        assert "projects" in str(result)
        assert not result.exists()

    def test_nested_relative_path_migrates(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

        # Set up legacy nested file
        legacy_dir = tmp_path / ".claude" / "forge" / "history"
        legacy_dir.mkdir(parents=True)
        legacy_file = legacy_dir / "applied.json"
        legacy_file.write_text("[]")

        with patch.object(pi, "_get_git_remote_url", return_value=None):
            result = pi.resolve_user_file(tmp_path, "history/applied.json")

        assert result.is_file()
        assert result.read_text() == "[]"
        assert not legacy_file.exists()


class TestFindProjectRoot:
    """Test the consolidated find_project_root function."""

    def test_override_returns_resolved_path(self, tmp_path):
        """Override string is resolved to an absolute Path."""
        result = pi.find_project_root(str(tmp_path))
        assert result == tmp_path.resolve()

    def test_finds_git_directory(self, tmp_path, monkeypatch):
        """Walks up to find .git marker."""
        (tmp_path / ".git").mkdir()
        subdir = tmp_path / "src" / "deep"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)
        result = pi.find_project_root()
        assert result == tmp_path

    def test_finds_claude_directory(self, tmp_path, monkeypatch):
        """Walks up to find .claude marker."""
        (tmp_path / ".claude").mkdir()
        subdir = tmp_path / "nested"
        subdir.mkdir()
        monkeypatch.chdir(subdir)
        result = pi.find_project_root()
        assert result == tmp_path

    def test_falls_back_to_cwd(self, tmp_path, monkeypatch):
        """Returns cwd when no marker is found."""
        # tmp_path has no .git or .claude
        monkeypatch.chdir(tmp_path)
        result = pi.find_project_root()
        assert result == tmp_path.resolve()

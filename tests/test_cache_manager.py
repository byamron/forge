"""Tests for cache-manager.py."""
import json
import os
import sys
import importlib
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "forge" / "scripts"))
cm = importlib.import_module("cache-manager")
import project_identity as pi


@pytest.fixture
def tmp_project_with_home(tmp_path):
    """Create a project dir + fake home so cache_dir resolves to temp."""
    project = tmp_path / "project"
    (project / ".claude" / "rules").mkdir(parents=True)
    (project / ".claude" / "skills").mkdir(parents=True)
    (project / ".claude" / "agents").mkdir(parents=True)
    (project / "CLAUDE.md").write_text("# Test Project\n")

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    return project, fake_home


class TestWriteCacheAtomic:
    """Verify atomic write pattern: temp file + rename."""

    def test_write_creates_file(self, tmp_project_with_home, monkeypatch):
        project, fake_home = tmp_project_with_home
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
        with patch.object(pi, "_get_git_remote_url", return_value=None):
            cm.write_cache(project, "config", "fp123", {"test": True})
            cache_d = cm.cache_dir(project)
        cache_file = cache_d / "config.cache.json"
        assert cache_file.exists()
        data = json.loads(cache_file.read_text())
        assert data["result"] == {"test": True}
        assert data["fingerprint"] == "fp123"
        assert data["version"] == cm.CACHE_VERSION

    def test_read_cache_roundtrip(self, tmp_project_with_home, monkeypatch):
        project, fake_home = tmp_project_with_home
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
        with patch.object(pi, "_get_git_remote_url", return_value=None):
            cm.write_cache(project, "memory", "fp456", {"notes": []})
            result = cm.read_cache(project, "memory")
        assert result is not None
        assert result["result"] == {"notes": []}
        assert result["fingerprint"] == "fp456"

    def test_read_cache_missing_returns_none(self, tmp_project_with_home, monkeypatch):
        project, fake_home = tmp_project_with_home
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
        with patch.object(pi, "_get_git_remote_url", return_value=None):
            assert cm.read_cache(project, "nonexistent") is None

    def test_read_cache_corrupt_returns_none(self, tmp_project_with_home, monkeypatch):
        project, fake_home = tmp_project_with_home
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
        with patch.object(pi, "_get_git_remote_url", return_value=None):
            cache_d = cm.cache_dir(project)
            cache_d.mkdir(parents=True, exist_ok=True)
            (cache_d / "config.cache.json").write_text("not json!")
            assert cm.read_cache(project, "config") is None


class TestFingerprintDeterminism:
    """Verify fingerprint properties that matter for cache invalidation."""

    def test_order_independent(self):
        """Checksum sorts entries, so order shouldn't matter."""
        h1 = cm.compute_checksum(["b:1:2", "a:3:4"])
        h2 = cm.compute_checksum(["a:3:4", "b:1:2"])
        assert h1 == h2

    def test_different_inputs_different_checksum(self):
        h1 = cm.compute_checksum(["file1:123:456"])
        h2 = cm.compute_checksum(["file1:123:457"])
        assert h1 != h2


class TestCheckCache:
    """Verify cache freshness checking."""

    def test_empty_project_all_stale(self, tmp_project_with_home, monkeypatch):
        project, fake_home = tmp_project_with_home
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
        with patch.object(pi, "_get_git_remote_url", return_value=None):
            result = cm.check_cache(project)
        for key in ("config", "transcripts", "memory"):
            assert result[key]["status"] == "stale"


class TestFileStat:
    def test_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        result = cm.file_stat(f)
        assert result is not None
        assert result[1] == 5  # size

    def test_missing_file(self, tmp_path):
        assert cm.file_stat(tmp_path / "nope.txt") is None

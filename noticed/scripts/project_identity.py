#!/usr/bin/env python3
"""Project identity and data directory resolution for Noticed.

Centralizes how Noticed identifies a project (via git remote URL hash) and
resolves per-project data files at two levels:

User-level (~/.claude/noticed/projects/<hash>/):
    Personal settings, caches, pending proposals, session logs, analysis lock.
    Private to each machine/user. Not shared across contributors.

Project-level (<project_root>/.claude/noticed/):
    Feedback data that shapes proposals: dismissed.json, history/applied.json,
    feedback_signals.json. Git-tracked, shared across all contributors.

Functions:
    compute_project_hash    -- SHA-256 hash of the cleaned git remote URL
    get_user_data_dir       -- ~/.claude/noticed/projects/<hash>/ with auto-create
    get_project_data_dir    -- <root>/.claude/noticed/ with auto-create
    resolve_user_file       -- migrate-on-read from legacy .claude/forge/ to user-level
    resolve_project_file    -- migrate-on-read from user-level to project-level

Migration:
    On first access to either data dir, _migrate_dir_once() copies the
    corresponding legacy Forge directory (.claude/forge/ or
    ~/.claude/forge/projects/<hash>/) forward to the Noticed location.
    Legacy directories are left intact for rollback and audit.
"""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse


def _strip_url_credentials(url: str) -> str:
    """Remove embedded credentials from a URL.

    Handles URLs like https://token@github.com/org/repo or
    https://user:pass@github.com/org/repo. On parse failure, returns
    '<redacted-url>' rather than risk leaking credentials.
    """
    try:
        parsed = urlparse(url)
        if parsed.username or parsed.password:
            netloc = parsed.hostname or ""
            if parsed.port:
                netloc += ":" + str(parsed.port)
            return urlunparse(parsed._replace(netloc=netloc))
        return url
    except Exception:
        # Fail safe: never return the original URL if parsing failed --
        # it may contain embedded credentials
        return "<redacted-url>"


def find_project_root(override: Optional[str] = None) -> Path:
    """Find the project root by walking up from cwd.

    If *override* is provided, use it directly. Otherwise walk up from the
    current working directory looking for ``.git`` or ``.claude`` markers.
    Falls back to cwd if no marker is found.
    """
    if override:
        return Path(override).resolve()
    current = Path.cwd().resolve()
    while current != current.parent:
        if (current / ".git").exists() or (current / ".claude").exists():
            return current
        current = current.parent
    return Path.cwd().resolve()


def compute_project_hash(project_root: Path) -> str:
    """Compute a stable hash identifying this project across worktrees.

    Strategy:
    1. Get the git remote origin URL (subprocess, list form, timeout=5).
    2. Strip any embedded credentials from the URL.
    3. SHA-256 hash the cleaned URL, return the first 12 hex characters.

    Fallback (no git remote): encode the resolved project path as
    ``str(path).replace("/", "-").lstrip("-")``, matching Claude Code's
    own project directory encoding scheme.

    Args:
        project_root: The root directory of the project.

    Returns:
        A 12-character hex string (remote-based) or a path-encoded string
        (fallback).
    """
    url = _get_git_remote_url(project_root)
    if url:
        cleaned = _strip_url_credentials(url)
        digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
        return digest[:12]

    # Fallback: path-based encoding (matches Claude Code's scheme)
    resolved = str(project_root.resolve())
    return resolved.replace("/", "-").lstrip("-")


def _get_git_remote_url(project_root: Path) -> Optional[str]:
    """Get the origin remote URL for the project's git repository.

    Runs ``git -C <path> remote get-url origin`` with a 5-second timeout.
    Returns None on any failure (no git, no remote, timeout, etc.).
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        url = result.stdout.strip()
        if result.returncode == 0 and url:
            return url
        return None
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(
            "Warning: git remote check failed for {}: {}".format(
                project_root, exc
            ),
            file=sys.stderr,
        )
        return None


def _migrate_dir_once(legacy: Path, current: Path) -> None:
    """Copy a legacy Forge data directory to the new Noticed location.

    One-shot, idempotent, race-safe: if ``legacy`` exists as a directory
    and ``current`` does not yet exist, copies the entire tree to a
    sibling tmp directory and atomically renames it into place. If a
    concurrent process completes the migration first, the losing
    process cleans up its tmp copy and proceeds. The legacy directory
    is left intact so users can rollback or audit the pre-rename state.

    Failures are logged but never raise -- the caller proceeds with an
    empty ``current`` if migration fails.

    Note: if both ``legacy`` and ``current`` exist (e.g. user ran both
    old Forge and new Noticed in parallel), this is a silent no-op.
    ``current`` is treated as canonical; ``legacy`` is left untouched.
    The user can manually consolidate if needed.
    """
    if not legacy.is_dir() or current.exists():
        return
    current.parent.mkdir(parents=True, exist_ok=True)
    tmp = current.parent / "{}.migrating.{}".format(current.name, os.getpid())
    try:
        # Clean any leftover tmp from a prior failed attempt by this PID.
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(legacy, tmp)
        try:
            # Atomic on POSIX when the target does not exist. If another
            # process raced ahead and created `current`, os.rename fails
            # with ENOTEMPTY (or similar) and we treat their copy as
            # canonical, cleaning up ours.
            os.rename(tmp, current)
        except OSError:
            shutil.rmtree(tmp, ignore_errors=True)
    except OSError as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        print(
            "Warning: Forge to Noticed migration of {} failed: {}".format(
                legacy, exc
            ),
            file=sys.stderr,
        )


def get_user_data_dir(project_root: Path) -> Path:
    """Return the user-level data directory for this project.

    The directory is ``~/.claude/noticed/projects/<project_hash>/``.
    On first access, migrates the pre-rename Forge directory
    (``~/.claude/forge/projects/<project_hash>/``) forward by copy.
    Creates the directory (with parents) if it does not already exist.

    Args:
        project_root: The root directory of the project.

    Returns:
        The resolved Path to the user-data directory.
    """
    project_hash = compute_project_hash(project_root)
    data_dir = Path.home() / ".claude" / "noticed" / "projects" / project_hash
    legacy_dir = Path.home() / ".claude" / "forge" / "projects" / project_hash
    _migrate_dir_once(legacy_dir, data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_project_data_dir(project_root: Path) -> Path:
    """Return the project-level Noticed data directory (.claude/noticed/).

    This directory is git-tracked and shared across all contributors.
    Contains feedback data that shapes proposals: dismissed.json,
    history/applied.json, feedback_signals.json.

    On first access, migrates the pre-rename Forge directory
    (``.claude/forge/``) forward by copy. Legacy directory is left intact
    so contributors who haven't updated still see their data; the new
    directory becomes the source of truth going forward.

    Args:
        project_root: The root directory of the project.

    Returns:
        The resolved Path to the project-level data directory.
    """
    data_dir = project_root / ".claude" / "noticed"
    legacy_dir = project_root / ".claude" / "forge"
    _migrate_dir_once(legacy_dir, data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def resolve_project_file(project_root: Path, relative_path: str) -> Path:
    """Resolve a project-level data file, migrating from user-level if needed.

    The project-level location is ``<project_root>/.claude/noticed/``.
    The user-level location is ``~/.claude/noticed/projects/<hash>/``.

    If the file exists at the project location, it is returned immediately.
    If the file only exists at the user-level location, it is copied to the
    project location. The user-level copy is NOT deleted -- other worktrees
    or older Noticed versions may still read from there.
    If neither location has the file, the project-level path is returned
    for the caller to create or handle absence.

    Args:
        project_root: The root directory of the project.
        relative_path: Path relative to the data directory
            (e.g., ``"dismissed.json"`` or ``"history/applied.json"``).

    Returns:
        The Path to the file at the project-level location.

    Raises:
        ValueError: If ``relative_path`` contains ``..`` (path traversal).
    """
    if ".." in relative_path:
        raise ValueError(
            "relative_path must not contain '..': {}".format(relative_path)
        )

    new_path = get_project_data_dir(project_root) / relative_path

    # Already at project location -- return immediately
    if new_path.is_file():
        return new_path

    # Try migrating from user-level location
    user_path = get_user_data_dir(project_root) / relative_path
    if user_path.is_file():
        new_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = user_path.read_bytes()
            new_path.write_bytes(data)
            # Do NOT delete the user-level copy -- other worktrees or
            # older Noticed versions may still reference it.
        except OSError as exc:
            print(
                "Warning: migration of {} to project-level failed: {}".format(
                    user_path, exc
                ),
                file=sys.stderr,
            )

    return new_path


def resolve_user_file(project_root: Path, relative_path: str) -> Path:
    """Resolve a user-data file, migrating from legacy location if needed.

    The new location is under ``~/.claude/noticed/projects/<hash>/``.
    The legacy location is ``<project_root>/.claude/forge/`` (pre-storage-
    split layout, retained for users who skipped several versions).

    If the file exists at the new location, it is returned immediately.
    If the file only exists at the legacy location, it is copied to the
    new location and the legacy file is deleted (migrate-on-read).
    If neither location has the file, the new-location path is returned
    for the caller to create or handle absence.

    Args:
        project_root: The root directory of the project.
        relative_path: Path relative to the data directory
            (e.g., ``"dismissed.json"`` or ``"history/applied.json"``).

    Returns:
        The Path to the file at the new location.

    Raises:
        ValueError: If ``relative_path`` contains ``..`` (path traversal).
    """
    if ".." in relative_path:
        raise ValueError(
            "relative_path must not contain '..': {}".format(relative_path)
        )

    new_path = get_user_data_dir(project_root) / relative_path
    legacy_path = project_root / ".claude" / "forge" / relative_path

    # Already at new location -- return immediately
    if new_path.is_file():
        return new_path

    # Migrate from legacy location if it exists there
    if legacy_path.is_file():
        new_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = legacy_path.read_bytes()
            new_path.write_bytes(data)
            legacy_path.unlink()
        except OSError as exc:
            # Migration failed -- return new path anyway; caller will
            # either find an incomplete file or create a fresh one.
            print(
                "Warning: migration of {} failed: {}".format(
                    legacy_path, exc
                ),
                file=sys.stderr,
            )

    return new_path


# ---------------------------------------------------------------------------
# CLI — used by log-session.sh to get the user data directory
# ---------------------------------------------------------------------------

def main() -> None:
    """Print the user-level data directory for a project root."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Print the user-level Noticed data directory for a project."
    )
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args()

    data_dir = get_user_data_dir(Path(args.project_root).resolve())
    print(str(data_dir))


if __name__ == "__main__":
    main()

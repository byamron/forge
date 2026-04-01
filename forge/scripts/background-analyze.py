#!/usr/bin/env python3
"""Background analysis trigger for Forge SessionStart hook.

Checks if enough unanalyzed sessions have accumulated and, if so,
spawns cache-manager.py --update as a fully detached background process.
Returns immediately so the hook does not block session start.

The background analysis is script-only (Phase A) — zero LLM token cost.

Usage (hook mode — returns immediately):
    python3 background-analyze.py [--plugin-root /path] [--project-root /path]

Usage (internal — runs analysis synchronously, called by the spawned subprocess):
    python3 background-analyze.py --run --project-root /path --plugin-root /path
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from project_identity import get_user_data_dir, resolve_user_file


# Reuse nudge level thresholds — if the user configured their nudge level,
# that's the appropriate threshold for background analysis too.
LEVEL_THRESHOLDS = {
    "quiet": None,
    "balanced": 5,
    "eager": 2,
}

# Lock file staleness: if older than this, consider it abandoned
LOCK_STALENESS_SECONDS = 300

# Maximum time for the background analysis subprocess
ANALYSIS_TIMEOUT_SECONDS = 60


def find_project_root(override: Optional[str] = None) -> Path:
    if override:
        return Path(override).resolve()
    current = Path.cwd().resolve()
    while current != current.parent:
        if (current / ".git").exists() or (current / ".claude").exists():
            return current
        current = current.parent
    return Path.cwd().resolve()


def load_nudge_level(project_root: Path) -> str:
    settings_path = resolve_user_file(project_root, "settings.json")
    if settings_path.is_file():
        try:
            with open(settings_path, "r") as f:
                data = json.load(f)
            level = data.get("nudge_level", "balanced")
            if level in LEVEL_THRESHOLDS:
                return level
        except (json.JSONDecodeError, OSError):
            pass
    return "balanced"


def count_unanalyzed_sessions(user_data_dir: Path) -> int:
    log_path = user_data_dir / "unanalyzed-sessions.log"
    if not log_path.is_file():
        return 0
    try:
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        return len(lines)
    except OSError:
        return 0


def is_locked(user_data_dir: Path) -> bool:
    """Check if background analysis is already running."""
    lock_path = user_data_dir / "analysis.lock"
    if not lock_path.is_file():
        return False
    try:
        mtime = lock_path.stat().st_mtime
        if time.time() - mtime > LOCK_STALENESS_SECONDS:
            # Stale lock — previous run likely crashed
            try:
                lock_path.unlink()
            except OSError:
                pass
            return False
        return True
    except OSError:
        return False


def _run_analysis(root: Path, plugin_root: str, user_data_dir: Path) -> None:
    """Run analysis synchronously. Called in the detached background subprocess."""
    lock_path = user_data_dir / "analysis.lock"
    try:
        cache_manager = Path(plugin_root) / "scripts" / "cache-manager.py"
        if not cache_manager.is_file():
            cache_manager = Path(__file__).parent / "cache-manager.py"

        if not cache_manager.is_file():
            return

        proc = subprocess.run(
            [sys.executable, str(cache_manager), "--update",
             "--project-root", str(root),
             "--plugin-root", plugin_root],
            timeout=ANALYSIS_TIMEOUT_SECONDS,
            capture_output=True,
        )

        if proc.returncode == 0:
            # Reset the unanalyzed sessions log — analysis is complete.
            # Any SessionEnd that fires during analysis adds a new entry;
            # those are acceptable to lose since the cache is now fresh.
            log_path = user_data_dir / "unanalyzed-sessions.log"
            try:
                log_path.write_text("", encoding="utf-8")
            except OSError:
                pass
    except (subprocess.TimeoutExpired, OSError):
        pass
    finally:
        try:
            lock_path.unlink()
        except OSError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Forge background analysis trigger"
    )
    parser.add_argument("--plugin-root", type=str, default=None)
    parser.add_argument("--project-root", type=str, default=None)
    parser.add_argument(
        "--run", action="store_true",
        help="Run analysis synchronously (internal — called by spawned subprocess)"
    )
    args = parser.parse_args()

    root = find_project_root(args.project_root)
    user_data_dir = get_user_data_dir(root)

    plugin_root = args.plugin_root or os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not plugin_root:
        plugin_root = str(Path(__file__).parent.parent)

    if args.run:
        _run_analysis(root, plugin_root, user_data_dir)
        return

    # --- Hook mode: check thresholds and spawn background if needed ---

    level = load_nudge_level(root)
    threshold = LEVEL_THRESHOLDS.get(level)
    if threshold is None:
        return

    unanalyzed = count_unanalyzed_sessions(user_data_dir)
    if unanalyzed < threshold:
        return

    if is_locked(user_data_dir):
        return

    # Create lock file before spawning.
    # If spawn fails, clean up the lock so it doesn't block future runs.
    lock_path = user_data_dir / "analysis.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(str(int(time.time())), encoding="utf-8")

    try:
        # Spawn self with --run as a fully detached process.
        # start_new_session=True detaches from the parent's process group
        # so the hook can return immediately.
        subprocess.Popen(
            [
                sys.executable, str(Path(__file__).resolve()),
                "--run",
                "--project-root", str(root),
                "--plugin-root", plugin_root,
            ],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        # Spawn failed — clean up lock to avoid blocking future runs
        try:
            lock_path.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # SessionStart hooks must never crash visibly.
        # Failure here just means background analysis doesn't run —
        # the user can still invoke /forge manually.
        pass

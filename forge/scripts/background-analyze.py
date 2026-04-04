#!/usr/bin/env python3
"""Background analysis trigger for Forge SessionStart hook.

Checks if enough unanalyzed sessions have accumulated and, if so,
spawns cache-manager.py --update as a fully detached background process.
Returns immediately so the hook does not block session start.

Script analysis (Phase A) is always zero LLM token cost. After Phase A
completes, a deep analysis pass runs via `claude -p --bare --model sonnet`,
filtering script proposals for quality and finding additional patterns.
The result is cached for the next `/forge` invocation.

Usage (hook mode -- returns immediately):
    python3 background-analyze.py [--plugin-root /path] [--project-root /path]

Usage (internal -- runs analysis synchronously, called by the spawned subprocess):
    python3 background-analyze.py --run --project-root /path --plugin-root /path
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from project_identity import find_project_root, get_user_data_dir, resolve_user_file


# Reuse nudge level thresholds -- if the user configured their nudge level,
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

# Maximum time for the deep analysis (LLM) subprocess
DEEP_ANALYSIS_TIMEOUT_SECONDS = 120

# Maximum conversation pairs to send to deep analysis
DEEP_MAX_PAIRS = 30


def _load_settings(project_root: Path) -> Dict[str, Any]:
    """Load Forge settings, returning empty dict on failure."""
    settings_path = resolve_user_file(project_root, "settings.json")
    if settings_path.is_file():
        try:
            with open(settings_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def load_nudge_level(project_root: Path) -> str:
    data = _load_settings(project_root)
    level = data.get("nudge_level", "balanced")
    if level in LEVEL_THRESHOLDS:
        return level
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
            # Stale lock -- previous run likely crashed
            try:
                lock_path.unlink()
            except OSError:
                pass
            return False
        return True
    except OSError:
        return False


def _read_cached_proposals(user_data_dir: Path) -> Dict[str, Any]:
    """Read the cached proposals JSON from the cache directory."""
    # Cache dir is a sibling of user_data_dir: .../cache/proposals.json
    cache_dir = user_data_dir / "cache"
    proposals_path = cache_dir / "proposals.json"
    if proposals_path.is_file():
        try:
            return json.loads(proposals_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _read_cached_transcripts(user_data_dir: Path) -> Dict[str, Any]:
    """Read the cached transcript analysis result."""
    cache_dir = user_data_dir / "cache"
    transcripts_path = cache_dir / "transcripts.json"
    if transcripts_path.is_file():
        try:
            data = json.loads(transcripts_path.read_text(encoding="utf-8"))
            return data.get("result", {})
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _build_deep_prompt(
    proposals: List[Dict[str, Any]],
    pairs: List[Dict[str, Any]],
    agent_prompt_path: Path,
) -> Optional[str]:
    """Build the prompt for the deep analysis LLM call.

    Sends script proposals for quality filtering and conversation pairs
    for additional pattern detection.
    """
    if not agent_prompt_path.is_file():
        return None

    agent_md = agent_prompt_path.read_text(encoding="utf-8")
    # Strip YAML frontmatter
    if agent_md.startswith("---"):
        end = agent_md.find("---", 3)
        if end != -1:
            agent_md = agent_md[end + 3:].strip()

    # Truncate pairs to limit
    pairs_sample = pairs[:DEEP_MAX_PAIRS]

    prompt = (
        f"{agent_md}\n\n"
        f"## Input: Script proposals\n\n"
        f"```json\n{json.dumps(proposals, indent=2)}\n```\n\n"
        f"## Input: Conversation pairs sample\n\n"
        f"```json\n{json.dumps(pairs_sample, indent=2)}\n```\n\n"
        f"Output a JSON object with `filtered_proposals` (script proposals that "
        f"pass quality review, with impact potentially adjusted), "
        f"`additional_proposals` (new patterns you found), `removed_count` "
        f"(how many script proposals you filtered out), and `removal_reasons` "
        f"(array of reason strings). "
        f"Output ONLY a valid JSON object -- no markdown fences, no explanation."
    )
    return prompt


def _run_deep_analysis(
    root: Path,
    plugin_root: str,
    user_data_dir: Path,
) -> None:
    """Run deep analysis via `claude -p --bare --model sonnet`.

    Reads cached script proposals and transcript pairs, builds a prompt,
    invokes the LLM, and caches the result as deep-analysis.json.
    The LLM filters script proposals for quality and finds additional patterns.
    """
    # Check if claude CLI is available
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return

    # Read cached data from script analysis
    proposals_data = _read_cached_proposals(user_data_dir)
    proposals = proposals_data.get("proposals", [])

    transcripts = _read_cached_transcripts(user_data_dir)
    pairs = transcripts.get("conversation_pairs_sample", [])
    if not pairs:
        return

    # Build the prompt
    agent_path = Path(plugin_root) / "agents" / "session-analyzer.md"
    prompt = _build_deep_prompt(proposals, pairs, agent_path)
    if not prompt:
        return

    deep_cache_path = user_data_dir / "cache" / "deep-analysis.json"
    try:
        proc = subprocess.run(
            [
                claude_bin, "-p",
                "--bare",
                "--model", "sonnet",
                "--effort", "low",
                "--no-session-persistence",
                "--output-format", "text",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=DEEP_ANALYSIS_TIMEOUT_SECONDS,
            cwd=str(root),
        )

        if proc.returncode != 0:
            return

        # Parse the LLM output -- expect a JSON object
        output = proc.stdout.strip()
        # Strip markdown fences if the LLM wrapped them anyway
        if output.startswith("```"):
            lines = output.splitlines()
            # Remove first and last fence lines
            lines = [l for l in lines if not l.startswith("```")]
            output = "\n".join(lines).strip()

        deep_result = json.loads(output)

        # Accept both the new object format and legacy array format
        if isinstance(deep_result, list):
            # Legacy format: plain array of additional proposals
            deep_result = {
                "filtered_proposals": proposals,
                "additional_proposals": deep_result,
                "removed_count": 0,
                "removal_reasons": [],
            }
        elif not isinstance(deep_result, dict):
            return

        # Validate required keys exist (use defaults for missing)
        if "filtered_proposals" not in deep_result:
            deep_result["filtered_proposals"] = proposals
        if "additional_proposals" not in deep_result:
            deep_result["additional_proposals"] = []
        if "removed_count" not in deep_result:
            deep_result["removed_count"] = 0
        if "removal_reasons" not in deep_result:
            deep_result["removal_reasons"] = []

        # Cache the result
        result = {
            "filtered_proposals": deep_result["filtered_proposals"],
            "additional_proposals": deep_result["additional_proposals"],
            "removed_count": deep_result["removed_count"],
            "removal_reasons": deep_result["removal_reasons"],
            "timestamp": time.time(),
            "pairs_analyzed": len(pairs),
            "source": "background_deep_analysis",
        }
        deep_cache_path.parent.mkdir(parents=True, exist_ok=True)
        deep_cache_path.write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass


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
            # Reset the unanalyzed sessions log -- analysis is complete.
            # Any SessionEnd that fires during analysis adds a new entry;
            # those are acceptable to lose since the cache is now fresh.
            log_path = user_data_dir / "unanalyzed-sessions.log"
            try:
                log_path.write_text("", encoding="utf-8")
            except OSError:
                pass

            # Always run LLM quality gate after successful Phase A
            _run_deep_analysis(root, plugin_root, user_data_dir)

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
        help="Run analysis synchronously (internal -- called by spawned subprocess)"
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
        # Spawn failed -- clean up lock to avoid blocking future runs
        try:
            lock_path.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # SessionStart hooks must never crash visibly.
        # Failure here just means background analysis doesn't run --
        # the user can still invoke /forge manually.
        pass

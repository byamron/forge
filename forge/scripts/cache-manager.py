#!/usr/bin/env python3
"""Cache manager for Forge analysis results.

Provides two modes:
  --check:  Compare cached fingerprints against current file state.
            Outputs which scripts need re-running vs. which have fresh cache.
  --update: Run stale analysis scripts and write fresh cache files.
            Called by the SessionEnd hook for background caching.

Cache files live in ~/.claude/forge/projects/<hash>/cache/ and store:
  - The analysis result JSON
  - A fingerprint (mtime+size of all input files) for invalidation

Usage:
    python3 cache-manager.py --check [--project-root /path] [--plugin-root /path]
    python3 cache-manager.py --update [--project-root /path] [--plugin-root /path]
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from project_identity import (
    find_project_root,
    get_project_data_dir,
    get_user_data_dir,
    resolve_project_file,
    resolve_user_file,
)


# ---------------------------------------------------------------------------
# File stat helpers
# ---------------------------------------------------------------------------

def file_stat(path: Path) -> Optional[Tuple[float, int]]:
    """Return (mtime, size) for a file, or None if it doesn't exist."""
    try:
        s = path.stat()
        return (s.st_mtime, s.st_size)
    except OSError:
        return None


def dir_file_stats(directory: Path, pattern: str = "*.md") -> List[Tuple[str, float, int]]:
    """Return sorted list of (relative_path, mtime, size) for files matching pattern."""
    results = []
    if directory.is_dir():
        for f in sorted(directory.rglob(pattern)):
            if f.is_file():
                try:
                    s = f.stat()
                    results.append((str(f), s.st_mtime, s.st_size))
                except OSError:
                    pass
    return results


def compute_checksum(entries: List[str]) -> str:
    """SHA-256 of sorted entries joined by newlines."""
    h = hashlib.sha256()
    for e in sorted(entries):
        h.update(e.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Fingerprint functions — one per analysis script
# ---------------------------------------------------------------------------

def fingerprint_config(root: Path) -> str:
    """Fingerprint all inputs that analyze-config.py depends on."""
    entries = []

    # CLAUDE.md — check both locations
    for candidate in [root / "CLAUDE.md", root / ".claude" / "CLAUDE.md"]:
        stat = file_stat(candidate)
        if stat:
            entries.append(f"{candidate}:{stat[0]}:{stat[1]}")

    # Rules
    for item in dir_file_stats(root / ".claude" / "rules"):
        entries.append(f"{item[0]}:{item[1]}:{item[2]}")

    # Skills (modern format)
    for item in dir_file_stats(root / ".claude" / "skills"):
        entries.append(f"{item[0]}:{item[1]}:{item[2]}")

    # Commands (legacy format)
    for item in dir_file_stats(root / ".claude" / "commands"):
        entries.append(f"{item[0]}:{item[1]}:{item[2]}")

    # Agents
    for item in dir_file_stats(root / ".claude" / "agents"):
        entries.append(f"{item[0]}:{item[1]}:{item[2]}")

    # settings.json (hooks)
    stat = file_stat(root / ".claude" / "settings.json")
    if stat:
        entries.append(f"settings.json:{stat[0]}:{stat[1]}")

    # Package/manifest files for tech stack detection
    for manifest in ["package.json", "Cargo.toml", "pyproject.toml", "go.mod",
                     "Gemfile", "build.gradle", "pom.xml", "composer.json"]:
        stat = file_stat(root / manifest)
        if stat:
            entries.append(f"{manifest}:{stat[0]}:{stat[1]}")

    return compute_checksum(entries)


def fingerprint_transcripts(root: Path) -> str:
    """Fingerprint inputs that analyze-transcripts.py depends on.

    Uses the unanalyzed-sessions.log as the primary signal — it's appended
    to every SessionEnd, so its mtime+size change whenever new sessions exist.
    Also includes analyzer-stats.json (feedback loop affects thresholds).
    """
    entries = []

    # Unanalyzed sessions log — primary freshness signal (user-level, shared)
    log_path = get_user_data_dir(root) / "unanalyzed-sessions.log"
    stat = file_stat(log_path)
    if stat:
        entries.append(f"unanalyzed-log:{stat[0]}:{stat[1]}")
    else:
        entries.append("unanalyzed-log:missing")

    # Analyzer stats (feedback loop)
    home = Path.home()
    stats_path = home / ".claude" / "forge" / "analyzer-stats.json"
    stat = file_stat(stats_path)
    if stat:
        entries.append(f"analyzer-stats:{stat[0]}:{stat[1]}")

    # Dismissed proposals (affects filtering) — now in project-level dir
    dismissed_path = resolve_project_file(root, "dismissed.json")
    stat = file_stat(dismissed_path)
    if stat:
        entries.append(f"dismissed:{stat[0]}:{stat[1]}")

    # Feedback signals (affects calibration) — project-level
    fs_path = get_project_data_dir(root) / "feedback_signals.json"
    stat = file_stat(fs_path)
    if stat:
        entries.append(f"feedback-signals:{stat[0]}:{stat[1]}")

    # Count JSONL files in the project's session directory for backup signal
    project_hash = str(root).replace("/", "-").lstrip("-")
    project_session_dir = home / ".claude" / "projects" / project_hash
    if project_session_dir.is_dir():
        jsonl_files = sorted(project_session_dir.glob("*.jsonl"))
        entries.append(f"jsonl-count:{len(jsonl_files)}")
        if jsonl_files:
            newest = max(f.stat().st_mtime for f in jsonl_files)
            entries.append(f"jsonl-newest:{newest}")

    return compute_checksum(entries)


def fingerprint_memory(root: Path) -> str:
    """Fingerprint inputs that analyze-memory.py depends on."""
    entries = []
    home = Path.home()

    # User-level CLAUDE.local.md
    stat = file_stat(home / ".claude" / "CLAUDE.local.md")
    if stat:
        entries.append(f"user-local-md:{stat[0]}:{stat[1]}")

    # Project-level CLAUDE.local.md
    stat = file_stat(root / "CLAUDE.local.md")
    if stat:
        entries.append(f"project-local-md:{stat[0]}:{stat[1]}")

    # Auto-memory files
    project_hash = str(root).replace("/", "-").lstrip("-")
    memory_dir = home / ".claude" / "projects" / project_hash / "memory"
    for item in dir_file_stats(memory_dir):
        entries.append(f"{item[0]}:{item[1]}:{item[2]}")

    # CLAUDE.md + rules (for redundancy detection)
    for candidate in [root / "CLAUDE.md", root / ".claude" / "CLAUDE.md"]:
        stat = file_stat(candidate)
        if stat:
            entries.append(f"{candidate}:{stat[0]}:{stat[1]}")

    for item in dir_file_stats(root / ".claude" / "rules"):
        entries.append(f"{item[0]}:{item[1]}:{item[2]}")

    return compute_checksum(entries)


# ---------------------------------------------------------------------------
# Cache read/write
# ---------------------------------------------------------------------------

CACHE_VERSION = 1
SCRIPT_NAMES = {
    "config": "analyze-config.py",
    "transcripts": "analyze-transcripts.py",
    "memory": "analyze-memory.py",
}
FINGERPRINT_FNS = {
    "config": fingerprint_config,
    "transcripts": fingerprint_transcripts,
    "memory": fingerprint_memory,
}
SCRIPT_TIMEOUTS = {
    "config": 5,
    "transcripts": 10,
    "memory": 5,
}


def cache_dir(root: Path) -> Path:
    return get_user_data_dir(root) / "cache"


def read_cache(root: Path, script_key: str) -> Optional[Dict[str, Any]]:
    """Read a cache file, returning the parsed JSON or None."""
    path = cache_dir(root) / f"{script_key}.cache.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != CACHE_VERSION:
            return None
        return data
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def write_cache(root: Path, script_key: str, fingerprint: str,
                result: Any) -> None:
    """Write a cache file atomically."""
    cdir = cache_dir(root)
    cdir.mkdir(parents=True, exist_ok=True)

    data = {
        "version": CACHE_VERSION,
        "script": script_key,
        "fingerprint": fingerprint,
        "result": result,
    }

    target = cdir / f"{script_key}.cache.json"
    # Write to temp file then rename for atomicity
    fd, tmp_path = tempfile.mkstemp(
        dir=str(cdir), suffix=".tmp", prefix=f"{script_key}."
    )
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.rename(tmp_path, str(target))
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Check mode — report cache freshness
# ---------------------------------------------------------------------------

def check_cache(root: Path) -> Dict[str, Any]:
    """Check each script's cache freshness. Returns status dict."""
    result = {}
    for key, fp_fn in FINGERPRINT_FNS.items():
        current_fp = fp_fn(root)
        cached = read_cache(root, key)

        if cached and cached.get("fingerprint") == current_fp:
            result[key] = {
                "status": "fresh",
                "result": cached["result"],
            }
        else:
            result[key] = {"status": "stale"}

    return result


# ---------------------------------------------------------------------------
# Update mode — run stale scripts and write cache
# ---------------------------------------------------------------------------

def update_cache(root: Path, plugin_root: Optional[str] = None) -> Dict[str, str]:
    """Run analysis scripts for stale caches. Returns status per script."""
    statuses = {}

    for key, fp_fn in FINGERPRINT_FNS.items():
        current_fp = fp_fn(root)
        cached = read_cache(root, key)

        if cached and cached.get("fingerprint") == current_fp:
            statuses[key] = "fresh"
            continue

        # Cache is stale — run the script
        script_name = SCRIPT_NAMES[key]
        timeout = SCRIPT_TIMEOUTS[key]

        # Determine script path
        if plugin_root:
            script_path = Path(plugin_root) / "scripts" / script_name
        else:
            # Fallback: script is in same directory as cache-manager
            script_path = Path(__file__).parent / script_name

        if not script_path.is_file():
            statuses[key] = "error:script_not_found"
            continue

        try:
            proc = subprocess.run(
                ["python3", str(script_path), "--project-root", str(root)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(root),
            )

            if proc.returncode != 0:
                statuses[key] = f"error:exit_{proc.returncode}"
                continue

            script_result = json.loads(proc.stdout)
            # Validate shape: all analysis scripts output JSON objects
            if not isinstance(script_result, dict):
                statuses[key] = "error:invalid_shape"
                continue
            write_cache(root, key, current_fp, script_result)
            statuses[key] = "updated"

        except subprocess.TimeoutExpired:
            statuses[key] = "error:timeout"
        except json.JSONDecodeError:
            statuses[key] = "error:invalid_json"
        except Exception as e:
            statuses[key] = f"error:{type(e).__name__}"

    return statuses


# ---------------------------------------------------------------------------
# Proposal building from cache
# ---------------------------------------------------------------------------

def _build_proposals_from_cache(root: Path,
                                 plugin_root: Optional[str] = None) -> None:
    """Run build-proposals.py using cached analysis results."""
    # Collect cached results
    config_cache = read_cache(root, "config")
    transcripts_cache = read_cache(root, "transcripts")
    memory_cache = read_cache(root, "memory")

    config_result = config_cache["result"] if config_cache else {}
    transcripts_result = (transcripts_cache["result"]
                          if transcripts_cache else {})
    memory_result = memory_cache["result"] if memory_cache else {}

    # Write combined JSON to a temp file for build-proposals.py
    combined = {
        "config": config_result,
        "transcripts": transcripts_result,
        "memory": memory_result,
    }

    cdir = cache_dir(root)
    cdir.mkdir(parents=True, exist_ok=True)
    combined_path = cdir / "combined-analysis.json"
    combined_path.write_text(json.dumps(combined), encoding="utf-8")

    # Run build-proposals
    if plugin_root:
        script_path = Path(plugin_root) / "scripts" / "build-proposals.py"
    else:
        script_path = Path(__file__).parent / "build-proposals.py"

    # Dismissed and applied are project-level (shared across contributors)
    dismissed_path = resolve_project_file(root, "dismissed.json")
    applied_path = resolve_project_file(root, "history/applied.json")
    # Pending stays user-level (personal, regenerated each run)
    pending_path = resolve_user_file(root, "proposals/pending.json")

    cmd = [
        "python3", str(script_path),
        "--combined", str(combined_path),
    ]
    if dismissed_path.is_file():
        cmd.extend(["--dismissed", str(dismissed_path)])
    if pending_path.is_file():
        cmd.extend(["--pending", str(pending_path)])
    if applied_path.is_file():
        cmd.extend(["--applied", str(applied_path)])

    # Pass project-level feedback signals for calibration (preferred)
    fs_path = get_project_data_dir(root) / "feedback_signals.json"
    if fs_path.is_file():
        cmd.extend(["--feedback-signals", str(fs_path)])
    else:
        # Fall back to user-level analyzer-stats.json for legacy compat
        stats_path = Path.home() / ".claude" / "forge" / "analyzer-stats.json"
        if stats_path.is_file():
            cmd.extend(["--stats", str(stats_path)])

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=5, cwd=str(root)
        )
        if proc.returncode == 0:
            proposals_path = cdir / "proposals.json"
            proposals_path.write_text(proc.stdout, encoding="utf-8")
    except (subprocess.TimeoutExpired, OSError):
        pass


def _extract_pairs_sample(root: Path) -> List[Dict[str, Any]]:
    """Extract conversation_pairs_sample from the transcript cache."""
    cached = read_cache(root, "transcripts")
    if not cached:
        return []
    result = cached.get("result", {})
    return result.get("conversation_pairs_sample", [])


def _read_deep_analysis_cache(root: Path) -> Optional[Dict[str, Any]]:
    """Read cached deep analysis results from background-analyze.py.

    Returns the cache dict with 'proposals' and 'timestamp', or None.
    The cache is considered stale after 24 hours.
    """
    deep_path = cache_dir(root) / "deep-analysis.json"
    if not deep_path.is_file():
        return None
    try:
        import time
        data = json.loads(deep_path.read_text(encoding="utf-8"))
        ts = data.get("timestamp", 0)
        if time.time() - ts > 86400:  # 24 hours
            return None
        return data
    except (OSError, json.JSONDecodeError):
        return None


def get_proposals(root: Path, plugin_root: Optional[str] = None) -> Dict[str, Any]:
    """Get proposals: use cached if available, otherwise build fresh.

    This is the single entry point for /forge — returns ready-to-present
    proposals plus context health, with all analysis cached.
    """
    # First, ensure analysis cache is fresh
    statuses = update_cache(root, plugin_root)
    any_updated = any(s == "updated" for s in statuses.values())

    # Check for cached deep analysis results from background-analyze.py
    deep_cache = _read_deep_analysis_cache(root)

    # Return cached proposals only if no analysis was refreshed
    proposals_path = cache_dir(root) / "proposals.json"
    if not any_updated:
        try:
            proposals = json.loads(
                proposals_path.read_text(encoding="utf-8")
            )
            if isinstance(proposals, dict) and "proposals" in proposals:
                proposals["cache_status"] = statuses
                proposals["conversation_pairs_sample"] = _extract_pairs_sample(root)
                proposals["deep_analysis_cache"] = deep_cache
                return proposals
        except (OSError, json.JSONDecodeError):
            pass

    # Build proposals fresh
    _build_proposals_from_cache(root, plugin_root)
    try:
        proposals = json.loads(
            proposals_path.read_text(encoding="utf-8")
        )
        if isinstance(proposals, dict):
            proposals["cache_status"] = statuses
            proposals["conversation_pairs_sample"] = _extract_pairs_sample(root)
            proposals["deep_analysis_cache"] = deep_cache
            return proposals
    except (OSError, json.JSONDecodeError):
        pass

    return {"proposals": [], "context_health": {}, "cache_status": statuses,
            "conversation_pairs_sample": [],
            "deep_analysis_cache": None}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Forge cache manager")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true",
                       help="Check cache freshness, output status JSON")
    group.add_argument("--update", action="store_true",
                       help="Run stale scripts and update cache")
    group.add_argument("--proposals", action="store_true",
                       help="Get ready-to-present proposals (runs analysis if needed)")
    parser.add_argument("--project-root", type=str, default=None)
    parser.add_argument("--plugin-root", type=str, default=None)
    args = parser.parse_args()

    root = find_project_root(args.project_root)

    if not root.is_dir():
        print(f"Error: project root does not exist: {root}", file=sys.stderr)
        sys.exit(1)

    # Resolve plugin root from env if not provided
    plugin_root = args.plugin_root or os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not plugin_root:
        # Fallback: assume scripts are siblings of this file
        plugin_root = str(Path(__file__).parent.parent)

    if args.check:
        result = check_cache(root)
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    elif args.update:
        statuses = update_cache(root, plugin_root)
        # After updating caches, build proposals
        _build_proposals_from_cache(root, plugin_root)
        json.dump(statuses, sys.stdout, indent=2)
        sys.stdout.write("\n")
    elif args.proposals:
        result = get_proposals(root, plugin_root)
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()

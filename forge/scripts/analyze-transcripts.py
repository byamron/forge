#!/usr/bin/env python3
"""Analyze Claude Code session transcripts for patterns.

Scans session transcript JSONL files from ~/.claude/projects/ to detect:
- Repeated user corrections (same feedback across sessions)
- Post-action patterns (user always runs a command after Claude edits)
- Repeated opening prompts (sessions starting with similar messages)

Usage:
    python3 analyze-transcripts.py [--project-root /path] [--min-occurrences 3] [--max-sessions 20]

Transcript JSONL format (observed structure, not a stable API):
    Each line is a JSON object. Entry types observed:
    - "type": "user" | "assistant" | "queue-operation"
    - "message": {"role": "user"|"assistant", "content": str|list}
    - "uuid": unique message identifier
    - "parentUuid": preceding message UUID (conversation threading)
    - "timestamp": ISO8601 timestamp (e.g., "2026-03-20T14:22:00.123Z")
    - "sessionId": session identifier
    - "isSidechain": boolean (subagent turns)

    User content: either a plain string or list with tool_result blocks.
    System-injected messages start with <system_instruction> or <local-command-caveat>.
    Assistant content: list of blocks — "text", "tool_use", "thinking".
    Tool use blocks: {"type": "tool_use", "name": "Edit", "input": {...}}
"""

import argparse
import datetime
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Python 3.8 compatibility
# ---------------------------------------------------------------------------

def _removesuffix(s: str, suffix: str) -> str:
    """str.removesuffix() backport for Python 3.8."""
    if suffix and s.endswith(suffix):
        return s[: -len(suffix)]
    return s


# ---------------------------------------------------------------------------
# Text sanitization
# ---------------------------------------------------------------------------

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_text(text: str, max_len: int = 0) -> str:
    """Remove control characters and optionally truncate."""
    cleaned = _CONTROL_CHAR_RE.sub("", text)
    if max_len > 0:
        cleaned = cleaned[:max_len]
    return cleaned


# ---------------------------------------------------------------------------
# NLP utilities — tokenization, stopwords, TF-IDF scoring
# ---------------------------------------------------------------------------

STOPWORDS = frozenset({
    # Standard English
    "a", "an", "the", "is", "it", "in", "on", "at", "to", "for",
    "of", "and", "or", "but", "not", "no", "with", "from", "by",
    "this", "that", "these", "those", "i", "you", "we", "they",
    "my", "your", "our", "its", "me", "us", "them", "he", "she",
    "be", "been", "being", "was", "were", "are", "am", "have",
    "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "can", "may", "might", "shall", "must",
    "so", "if", "then", "than", "when", "where", "how", "what",
    "which", "who", "whom", "there", "here", "all", "each",
    "every", "both", "few", "more", "most", "some", "any",
    "other", "such", "only", "just", "also", "very", "too",
    "about", "up", "out", "into", "over", "after", "before",
    # High-frequency in corrections but non-discriminating
    "use", "using", "please", "make", "sure", "always", "never",
    "don", "ve", "ll", "re",
    "claude", "code", "file", "files", "want", "need", "like",
    "think", "know", "see", "look", "way", "thing", "things",
    "going", "right", "good", "get", "got", "put", "let",
})

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_]*(?:-[a-zA-Z0-9_]+)*")


def tokenize(text: str) -> List[str]:
    """Extract content words: lowercase, remove stopwords and single chars."""
    return [
        t.lower() for t in _TOKEN_RE.findall(text)
        if t.lower() not in STOPWORDS and len(t) > 1
    ]


class TermScorer:
    """Stdlib TF-IDF scoring across a corpus of documents."""

    def __init__(self, documents: List[List[str]]):
        self.n_docs = max(len(documents), 1)
        self.df = Counter()  # type: Counter
        for doc in documents:
            for term in set(doc):
                self.df[term] += 1

    def idf(self, term: str) -> float:
        if self.df[term] == 0:
            return 0.0
        return math.log((self.n_docs + 1) / (self.df[term] + 1)) + 1.0

    def top_terms(self, tokens: List[str], n: int = 7) -> List[str]:
        tf = Counter(tokens)
        total = max(len(tokens), 1)
        scores = {t: (c / total) * self.idf(t) for t, c in tf.items()}
        return sorted(scores, key=lambda t: scores[t], reverse=True)[:n]


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def compute_theme_hash(key_terms: List[str], top_n: int = 5) -> str:
    normalized = sorted(set(t.lower() for t in key_terms))[:top_n]
    return hashlib.md5("|".join(normalized).encode()).hexdigest()[:8]


# ---------------------------------------------------------------------------
# Conversation pair classification
# ---------------------------------------------------------------------------

# Correction keyword patterns — scored, not binary
_STRONG_CORRECTION = [
    (re.compile(r"\bI told you\b", re.I), 0.4),
    (re.compile(r"\bthat'?s (?:not right|wrong|incorrect)\b", re.I), 0.4),
    (re.compile(r"\bI said\b", re.I), 0.35),
    (re.compile(r"\bwe use .+ not\b", re.I), 0.35),
    (re.compile(r"\buse .+ instead\b", re.I), 0.3),
    (re.compile(r"\bdon'?t (?:use|do|add|change|modify|remove)\b", re.I), 0.3),
    (re.compile(r"\bnever (?:use|do|add)\b", re.I), 0.3),
    (re.compile(r"\bshould(?:n'?t| not) (?:be|have|use)\b", re.I), 0.3),
]
_MILD_CORRECTION = [
    (re.compile(r"^no[,.\s]", re.I), 0.2),
    (re.compile(r"\bactually[,.]", re.I), 0.15),
    (re.compile(r"\binstead[,.]?\s", re.I), 0.15),
    (re.compile(r"\bswitch to\b", re.I), 0.15),
    (re.compile(r"\bwrong\b", re.I), 0.15),
    (re.compile(r"\bshould be\b", re.I), 0.15),
    (re.compile(r"\bnot that\b", re.I), 0.15),
]
_CONFIRMATORY = [
    re.compile(r"^(?:yes|yeah|yep|ok|okay|sure|perfect|great|thanks|thank you|looks? good|lgtm|nice|awesome|exactly)[.!,\s]*$", re.I),
    re.compile(r"\bthat(?:'?s| is) (?:right|correct|perfect|great|good)\b", re.I),
    re.compile(r"\bno(?:,| ).*(?:looks? good|that'?s (?:right|correct|perfect|great))", re.I),
]

# Post-action commands to watch for
POST_ACTION_COMMANDS = [
    re.compile(r"\bnpx\s+prettier\b", re.I),
    re.compile(r"\bnpm\s+run\s+(?:lint|format|test)\b", re.I),
    re.compile(r"\bnpm\s+test\b", re.I),
    re.compile(r"\bnpx\s+eslint\b", re.I),
    re.compile(r"\bcargo\s+(?:fmt|test|clippy)\b", re.I),
    re.compile(r"\bblack\s", re.I),
    re.compile(r"\bruff\b", re.I),
    re.compile(r"\bgo\s+(?:fmt|test|vet)\b", re.I),
    re.compile(r"\bpnpm\s+(?:test|lint|format)\b", re.I),
    re.compile(r"\byarn\s+(?:test|lint|format)\b", re.I),
    re.compile(r"\bpytest\b", re.I),
    re.compile(r"\bmypy\b", re.I),
]


def _extract_file_paths(tool_uses: list) -> List[str]:
    """Extract file paths from tool use inputs."""
    paths = []
    for tool in tool_uses:
        inp = tool.get("input", {})
        if isinstance(inp, dict):
            for key in ("file_path", "path", "filePath"):
                val = inp.get(key, "")
                if val:
                    paths.append(str(val))
    return paths


def classify_response(
    user_text: str,
    assistant_text: str,
    assistant_tools: list,
    assistant_files: List[str],
) -> Tuple[str, float]:
    """Classify a user response as corrective, confirmatory, new_instruction, or followup.

    Returns (classification, correction_strength).
    correction_strength is 0.0-1.0 for corrective, 0.0 otherwise.
    """
    text = user_text.strip()
    if not text or len(text) < 5:
        return ("followup", 0.0)

    # Slash commands are instructions, not corrections
    if text.startswith("/"):
        return ("new_instruction", 0.0)

    text_lower = text.lower()

    # --- Check confirmatory first ---
    for pat in _CONFIRMATORY:
        if pat.search(text_lower):
            return ("confirmatory", 0.0)

    # --- Score correction signals ---
    score = 0.0

    # Keyword scoring
    for pat, weight in _STRONG_CORRECTION:
        if pat.search(text_lower):
            score += weight
    for pat, weight in _MILD_CORRECTION:
        if pat.search(text_lower):
            score += weight

    # Cap keyword score at 0.5 — needs context to go higher
    keyword_score = min(score, 0.5)

    # --- Context: does the user reference the assistant's action? ---
    action_ref_score = 0.0
    if assistant_tools:
        # User references tool names or file paths from the action
        tool_names = [t.get("name", "").lower() for t in assistant_tools]
        for tn in tool_names:
            if tn and tn in text_lower:
                action_ref_score += 0.1

        for fp in assistant_files:
            # Check filename (not full path)
            fname = fp.rsplit("/", 1)[-1].lower() if "/" in fp else fp.lower()
            if fname and fname in text_lower:
                action_ref_score += 0.15

    # Check for word overlap with assistant text (indicates referencing the action)
    if assistant_text:
        user_tokens = set(tokenize(text))
        asst_tokens = set(tokenize(assistant_text[:500]))
        if user_tokens and asst_tokens:
            overlap = len(user_tokens & asst_tokens) / max(len(user_tokens), 1)
            if overlap > 0.2:
                action_ref_score += 0.1

    action_ref_score = min(action_ref_score, 0.3)

    # --- Imperative / directive tone ---
    imperative_score = 0.0
    # Short, directive messages after actions are likely corrections
    if len(text.split()) < 20 and assistant_tools:
        imperative_score += 0.1
    # Very short imperative ("use X", "change Y to Z")
    if len(text.split()) < 10 and keyword_score > 0:
        imperative_score += 0.1
    imperative_score = min(imperative_score, 0.2)

    total = keyword_score + action_ref_score + imperative_score

    if total >= 0.25:
        return ("corrective", min(total, 1.0))

    # --- Not corrective: new instruction or followup? ---
    if assistant_text:
        user_tokens = set(tokenize(text))
        asst_tokens = set(tokenize(assistant_text[:500]))
        if user_tokens and asst_tokens:
            overlap = len(user_tokens & asst_tokens) / max(len(user_tokens), 1)
            if overlap < 0.1:
                return ("new_instruction", 0.0)

    return ("followup", 0.0)


# ---------------------------------------------------------------------------
# Project directory mapping (cross-worktree aware)
# ---------------------------------------------------------------------------

def _encode_path_as_project_dir(path: str) -> str:
    """Encode a filesystem path to Claude Code's project directory name format.

    Claude Code replaces / with - and prepends a leading -:
        /Users/ben/project -> -Users-ben-project
    """
    return path.replace("/", "-").replace("\\", "-")


def _decode_project_dir(encoded: str) -> str:
    """Best-effort reconstruction of filesystem path from project dir name.

    Walks segments left-to-right, greedily joining with - when the joined
    path exists on disk. Falls back to treating each - as a / separator.
    Returns resolved absolute path, or empty string on any safety violation.
    """
    parts = encoded.lstrip("-").split("-")
    # Reject if any segment is a literal ".." path traversal component
    if any(p == ".." for p in parts):
        return ""
    result = ["/"]
    i = 0
    while i < len(parts):
        best_segment = parts[i]
        best_j = i
        for j in range(i + 1, len(parts)):
            candidate = "-".join(parts[i : j + 1])
            test_path = Path(*result, candidate)
            if test_path.exists():
                best_segment = candidate
                best_j = j
        result.append(best_segment)
        i = best_j + 1
    # Resolve symlinks and normalize to prevent traversal via symlinks
    decoded = str(Path(*result).resolve())
    # Final safety check: reject if ".." survived resolution
    if ".." in decoded.split("/"):
        return ""
    return decoded


def _strip_url_credentials(url: str) -> str:
    """Remove embedded credentials from a URL (e.g., https://token@github.com/...)."""
    from urllib.parse import urlparse, urlunparse

    try:
        parsed = urlparse(url)
        if parsed.username or parsed.password:
            netloc = parsed.hostname or ""
            if parsed.port:
                netloc += ":" + str(parsed.port)
            return urlunparse(parsed._replace(netloc=netloc))
        return url
    except Exception:
        # Fail safe: never return the original URL if parsing failed —
        # it may contain embedded credentials
        return "<redacted-url>"


def _get_git_remote(path: str) -> Optional[str]:
    """Get the origin remote URL for a git repo, with credentials stripped."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "-C", path, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        url = result.stdout.strip()
        if result.returncode == 0 and url:
            return _strip_url_credentials(url)
        return None
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"Warning: git remote check failed for {path}: {e}", file=sys.stderr)
        return None


def _get_repo_remote(project_root: Path) -> Optional[str]:
    """Get the origin remote URL for the repo at project_root.

    Walks up from project_root to find the git root.
    """
    path = project_root
    while path != path.parent:
        if (path / ".git").exists():
            return _get_git_remote(str(path))
        path = path.parent
    return None


def _load_repo_index() -> Dict[str, List[str]]:
    """Load the Forge repo index (remote_url -> list of project dir names).

    The index is maintained by the SessionEnd hook for forward coverage.
    Stored at ~/.claude/forge/repo-index.json.
    """
    index_path = Path.home() / ".claude" / "forge" / "repo-index.json"
    if not index_path.is_file():
        return {}
    try:
        with open(index_path, "r") as f:
            data = json.load(f)
        # Validate structure: {str: [str, ...]}
        if isinstance(data, dict):
            return {
                k: v for k, v in data.items() if isinstance(v, list)
            }
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: failed to load repo index: {e}", file=sys.stderr)
    return {}


def find_all_project_session_dirs(project_root: Path) -> List[Path]:
    """Find all ~/.claude/projects/ directories for the given repo.

    Aggregates across worktrees by matching on git remote URL. Uses
    multiple strategies to maximize coverage:

    1. Exact match: encode current path -> find in projects/
    2. Git worktree list: encode each worktree path -> find in projects/
    3. Forward index: check repo-index.json (maintained by SessionEnd hook)
    4. Git remote scan: for dirs that still exist, check remote URL
    5. Name heuristic: match dir name prefixes for deleted worktrees

    Returns all matching project directories, sorted by modification time.
    """
    claude_projects = Path.home() / ".claude" / "projects"
    if not claude_projects.is_dir():
        return []

    matched_dirs = set()  # dir names we've matched
    current_remote = _get_repo_remote(project_root)

    # Strategy 1: Exact match for current path
    encoded = _encode_path_as_project_dir(str(project_root))
    exact = claude_projects / encoded
    if exact.is_dir():
        matched_dirs.add(encoded)

    # Strategy 2: Git worktree list — finds active worktrees
    if current_remote:
        import subprocess

        try:
            result = subprocess.run(
                ["git", "-C", str(project_root), "worktree", "list", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.startswith("worktree "):
                        wt_path = line[len("worktree ") :]
                        wt_encoded = _encode_path_as_project_dir(wt_path)
                        wt_dir = claude_projects / wt_encoded
                        if wt_dir.is_dir():
                            matched_dirs.add(wt_encoded)
        except (OSError, subprocess.TimeoutExpired):
            pass

    # Strategy 3: Forward index (maintained by SessionEnd hook)
    if current_remote:
        repo_index = _load_repo_index()
        # Normalize remote URL for comparison (strip trailing .git, lowercase)
        norm_remote = _removesuffix(current_remote.rstrip("/"), ".git").lower()
        for indexed_remote, dir_names in repo_index.items():
            norm_indexed = _removesuffix(indexed_remote.rstrip("/"), ".git").lower()
            if norm_indexed == norm_remote:
                for name in dir_names:
                    d = claude_projects / name
                    if d.is_dir():
                        matched_dirs.add(name)

    # Strategy 4: Workspace-prefix heuristic for deleted worktrees.
    # From confirmed worktree matches (strategies 2-3), decode the path and
    # use the parent directory as a workspace prefix. Other dirs with the
    # same prefix are likely worktrees of the same repo that were cleaned up.
    # Only uses matches OTHER than the exact current-project match (strategy 1)
    # to avoid using the main checkout's parent dir (which may contain
    # unrelated repos) as a false workspace root.
    # Runs BEFORE git remote scan (strategy 5) because it's fast (string
    # prefix matching, no subprocesses) and catches most worktree dirs.
    #
    # IMPORTANT: After prefix matching, verify the git remote matches to
    # prevent cross-project leakage from sibling directories.
    exact_encoded = _encode_path_as_project_dir(str(project_root))
    worktree_matches = {m for m in matched_dirs if m != exact_encoded}
    if worktree_matches:
        workspace_prefixes = set()
        for m in worktree_matches:
            decoded = _decode_project_dir(m)
            if not decoded:
                continue
            parent = Path(decoded).parent
            if parent.is_dir():
                parent_encoded = _encode_path_as_project_dir(str(parent))
                workspace_prefixes.add(parent_encoded)

        if workspace_prefixes and current_remote:
            norm_remote = _removesuffix(current_remote.rstrip("/"), ".git").lower()
            for d in claude_projects.iterdir():
                if not d.is_dir() or d.name in matched_dirs:
                    continue
                for prefix in workspace_prefixes:
                    if d.name.startswith(prefix + "-"):
                        # Verify git remote matches before accepting.
                        # Without this, sibling projects in the same
                        # workspace directory would leak in.
                        verified = False
                        decoded_path = _decode_project_dir(d.name)
                        if decoded_path and Path(decoded_path).is_dir():
                            remote = _get_git_remote(decoded_path)
                            if remote:
                                norm = _removesuffix(remote.rstrip("/"), ".git").lower()
                                if norm == norm_remote:
                                    verified = True
                        if verified:
                            matched_dirs.add(d.name)
                        break

    # Strategy 5: Git remote scan — check dirs whose paths still exist on disk.
    # This is expensive (spawns a subprocess per directory), so only run if
    # strategies 1-4 found fewer than 2 matches (meaning we likely missed
    # worktrees that aren't in a shared workspace directory).
    if current_remote and len(matched_dirs) < 2:
        norm_remote = _removesuffix(current_remote.rstrip("/"), ".git").lower()
        for d in claude_projects.iterdir():
            if not d.is_dir() or d.name in matched_dirs:
                continue
            decoded_path = _decode_project_dir(d.name)
            if decoded_path and Path(decoded_path).is_dir():
                remote = _get_git_remote(decoded_path)
                if remote:
                    norm = _removesuffix(remote.rstrip("/"), ".git").lower()
                    if norm == norm_remote:
                        matched_dirs.add(d.name)

    # Convert to Path objects, sorted by most recent modification time
    result_dirs = []
    for name in matched_dirs:
        d = claude_projects / name
        if d.is_dir():
            # Use the most recent JSONL file's mtime as the directory's recency
            jsonl_files = list(d.glob("*.jsonl"))
            mtime = max((f.stat().st_mtime for f in jsonl_files), default=0)
            result_dirs.append((mtime, d))

    result_dirs.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in result_dirs]


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------

def _extract_text_content(content) -> str:
    """Extract plain text from a message content field."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return ""


def _extract_tool_uses(content) -> list:
    """Extract tool use entries from message content."""
    tools = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                tools.append({
                    "name": item.get("name", ""),
                    "input": item.get("input", {}),
                })
    return tools


def parse_transcript(filepath: Path) -> list:
    """Parse a JSONL transcript file into a list of structured messages."""
    messages = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = entry.get("type", "")

                # Skip non-message entry types (e.g., queue-operation)
                if msg_type not in ("user", "assistant"):
                    continue

                # Skip sidechain/subagent entries — these are internal agent
                # conversations, not user-facing interaction
                if entry.get("isSidechain", False):
                    continue

                message = entry.get("message", {})
                role = message.get("role", "") if isinstance(message, dict) else ""
                content = message.get("content", "") if isinstance(message, dict) else ""
                timestamp = entry.get("timestamp", "")

                text = _extract_text_content(content)
                tool_uses = _extract_tool_uses(content)

                # Skip system-injected and auto-generated messages
                if role == "user" and text:
                    stripped_text = text.lstrip()
                    if stripped_text.startswith(("<system", "<local-command")):
                        continue
                    # Skip context continuation summaries (auto-generated)
                    if "continued from a previous conversation" in text[:200]:
                        continue
                    # Skip command invocations (skill/slash command triggers)
                    if stripped_text.startswith(("<command", "<task-notification")):
                        continue

                messages.append({
                    "type": msg_type,
                    "role": role,
                    "text": text,
                    "tool_uses": tool_uses,
                    "timestamp": timestamp,
                    "raw_type": msg_type,
                })
    except (OSError, UnicodeDecodeError) as e:
        print(f"Warning: failed to parse {filepath}: {e}", file=sys.stderr)

    return messages


def load_sessions(session_dirs: List[Path], max_sessions: int) -> dict:
    """Load up to max_sessions most recent session transcripts.

    Aggregates JSONL files across multiple project directories (worktrees).
    Returns {session_id: [messages]} sorted by recency.
    """
    # Collect all JSONL files across all directories
    all_files = []
    for d in session_dirs:
        for f in d.glob("*.jsonl"):
            try:
                all_files.append((f.stat().st_mtime, f))
            except OSError:
                continue

    # Sort by recency, take the most recent max_sessions
    all_files.sort(key=lambda x: x[0], reverse=True)
    selected = all_files[:max_sessions]

    sessions = {}
    for _, filepath in selected:
        session_id = filepath.stem
        messages = parse_transcript(filepath)
        if messages:
            sessions[session_id] = messages

    return sessions


# ---------------------------------------------------------------------------
# Conversation pair building
# ---------------------------------------------------------------------------

def build_conversation_pairs(sessions: dict) -> List[dict]:
    """Build assistant-action → user-response pairs from all sessions.

    Each pair captures what the assistant did and how the user responded,
    including classification and correction strength.
    """
    all_pairs = []

    for session_id, messages in sessions.items():
        # Track the most recent assistant turn
        last_assistant = None  # type: Optional[dict]
        turn_index = 0

        for msg in messages:
            if msg["role"] == "assistant":
                last_assistant = msg
            elif msg["role"] == "user" and msg["text"].strip():
                asst_text = last_assistant["text"][:500] if last_assistant else ""
                asst_tools = last_assistant["tool_uses"] if last_assistant else []
                asst_files = _extract_file_paths(asst_tools)

                classification, strength = classify_response(
                    msg["text"], asst_text, asst_tools, asst_files,
                )

                all_pairs.append({
                    "session_id": session_id,
                    "timestamp": msg["timestamp"],
                    "turn_index": turn_index,
                    "user_text": _sanitize_text(msg["text"], 500),
                    "user_tokens": tokenize(msg["text"]),
                    "classification": classification,
                    "correction_strength": strength,
                    "assistant_text": asst_text,
                    "assistant_tools": [t.get("name", "") for t in asst_tools],
                    "assistant_files": asst_files,
                })
                turn_index += 1
                last_assistant = None  # consumed

    return all_pairs


# ---------------------------------------------------------------------------
# Feedback loop — learning from past proposals
# ---------------------------------------------------------------------------

def load_feedback_stats() -> dict:
    """Load analyzer stats from ~/.claude/forge/analyzer-stats.json."""
    stats_path = Path.home() / ".claude" / "forge" / "analyzer-stats.json"
    default = {
        "version": 1,
        "corrections": {"proposed": 0, "approved": 0, "dismissed": 0},
        "post_actions": {"proposed": 0, "approved": 0, "dismissed": 0},
        "repeated_prompts": {"proposed": 0, "approved": 0, "dismissed": 0},
        "theme_outcomes": {},
        "suppressed_themes": [],
    }
    if not stats_path.is_file():
        return default
    try:
        with open(stats_path, "r") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("version") == 1:
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return default


def precision_rate(stats: dict, category: str) -> Optional[float]:
    """Compute precision for a category. Returns None if insufficient data."""
    cat = stats.get(category, {})
    approved = cat.get("approved", 0)
    dismissed = cat.get("dismissed", 0)
    total = approved + dismissed
    if total < 3:
        return None
    return approved / total


def adjusted_threshold(base: float, prec: Optional[float]) -> float:
    """Adjust scoring threshold based on historical precision."""
    if prec is None:
        return base
    # Poor precision (< 0.5) → raise threshold up to 1.5x
    # Good precision (> 0.8) → lower threshold down to 0.8x
    adjustment = 1.0 + (0.5 - prec)
    return base * max(0.8, min(1.5, adjustment))


# ---------------------------------------------------------------------------
# Theme extraction and scoring
# ---------------------------------------------------------------------------

def _intra_session_weight(count: int) -> float:
    """Weight for repeated corrections within a single session.

    Repeated corrections in one session are a strong signal — Claude keeps
    making the same mistake and the user keeps correcting it.

    1st: 1.0, 2nd: 1.5, 3rd: 2.0, 4th+: 2.5 each (capped at 100)
    """
    if count <= 0:
        return 0.0
    count = min(count, 100)  # cap to prevent unbounded allocation
    base_weights = [1.0, 1.5, 2.0]
    if count <= 3:
        return sum(base_weights[:count])
    return sum(base_weights) + 2.5 * (count - 3)


def _recency_weight(timestamp: str) -> float:
    """More recent sessions count more. <7 days: 1.0, <30: 0.7, else: 0.4."""
    try:
        ts = datetime.datetime.fromisoformat(
            timestamp.replace("Z", "+00:00")
        )
        now = datetime.datetime.now(datetime.timezone.utc)
        age_days = (now - ts).total_seconds() / 86400
    except (ValueError, TypeError, AttributeError):
        return 0.5
    if age_days <= 7:
        return 1.0
    elif age_days <= 30:
        return 0.7
    return 0.4


def group_into_themes(
    pairs: List[dict],
    scorer: TermScorer,
    threshold: float = 0.3,
) -> List[dict]:
    """Group corrective pairs into themes by key-term Jaccard similarity."""
    # Extract top terms for each pair
    pair_terms = []
    for pair in pairs:
        top = scorer.top_terms(pair["user_tokens"], n=7)
        pair_terms.append((pair, set(top)))

    # Greedy agglomerative clustering
    themes = []
    used = set()

    for i, (pair_i, terms_i) in enumerate(pair_terms):
        if i in used:
            continue
        cluster_pairs = [pair_i]
        cluster_terms = set(terms_i)
        used.add(i)

        for j, (pair_j, terms_j) in enumerate(pair_terms):
            if j in used or j <= i:
                continue
            sim = jaccard(cluster_terms, terms_j)
            if sim >= threshold:
                cluster_pairs.append(pair_j)
                cluster_terms |= terms_j
                used.add(j)
                # Prevent runaway clusters
                if len(cluster_terms) > 15:
                    break

        key_terms = sorted(cluster_terms)
        themes.append({
            "key_terms": key_terms,
            "theme_hash": compute_theme_hash(key_terms),
            "pairs": cluster_pairs,
        })

    return themes


def score_theme(theme: dict) -> dict:
    """Score a theme using intra-session weighting, recency, and strength."""
    pairs = theme["pairs"]

    # Group by session
    by_session = defaultdict(list)  # type: Dict[str, list]
    for p in pairs:
        by_session[p["session_id"]].append(p)

    total_score = 0.0
    intra_detail = {}

    for sid, session_pairs in by_session.items():
        count = len(session_pairs)
        intra_w = _intra_session_weight(count)
        recency = _recency_weight(session_pairs[0]["timestamp"])
        avg_strength = sum(p["correction_strength"] for p in session_pairs) / count
        session_score = intra_w * recency * avg_strength
        total_score += session_score
        intra_detail[sid] = {
            "count": count,
            "weighted": round(session_score, 2),
        }

    theme["weighted_score"] = round(total_score, 2)
    theme["num_sessions"] = len(by_session)
    theme["total_occurrences"] = len(pairs)
    theme["intra_session_detail"] = intra_detail
    return theme


def score_to_confidence(
    score: float,
    num_sessions: int,
    base_high: float = 6.0,
    base_medium: float = 3.0,
) -> str:
    """Map aggregate score to confidence level."""
    if score >= base_high and num_sessions >= 2:
        return "high"
    elif score >= base_medium:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Correction analysis pipeline
# ---------------------------------------------------------------------------

def find_corrections(sessions: dict, stats: dict) -> list:
    """Find repeated corrections using conversation-pair analysis.

    Pipeline:
    1. Build conversation pairs from all sessions
    2. Filter to corrective pairs
    3. Build TF-IDF scorer from corrective pair texts
    4. Group into themes by key-term similarity
    5. Score with intra-session weighting
    6. Filter by feedback-adjusted thresholds
    """
    all_pairs = build_conversation_pairs(sessions)

    # Filter to corrective pairs only
    corrections = [p for p in all_pairs if p["classification"] == "corrective"]

    if len(corrections) < 2:
        return []

    # Build TF-IDF scorer from correction texts
    all_tokens = [p["user_tokens"] for p in corrections]
    scorer = TermScorer(all_tokens)

    # Group into themes
    themes = group_into_themes(corrections, scorer, threshold=0.3)

    # Score each theme
    for theme in themes:
        score_theme(theme)

    # Adjust thresholds based on feedback
    prec = precision_rate(stats, "corrections")
    high_threshold = adjusted_threshold(6.0, prec)
    medium_threshold = adjusted_threshold(3.0, prec)

    # Filter suppressed themes
    suppressed = set(stats.get("suppressed_themes", []))

    results = []
    for theme in themes:
        if theme["theme_hash"] in suppressed:
            continue

        # Check if previously dismissed — require higher score to resurface
        outcome = stats.get("theme_outcomes", {}).get(theme["theme_hash"])
        if outcome and outcome.get("outcome") == "dismissed":
            if theme["weighted_score"] < high_threshold * 1.5:
                continue

        confidence = score_to_confidence(
            theme["weighted_score"],
            theme["num_sessions"],
            high_threshold,
            medium_threshold,
        )
        if confidence == "low":
            continue

        # Build evidence from top pairs (sorted by strength)
        top_pairs = sorted(
            theme["pairs"],
            key=lambda p: p["correction_strength"],
            reverse=True,
        )[:5]

        # Generate a readable pattern description from key terms
        terms_str = ", ".join(theme["key_terms"][:5])

        results.append({
            "pattern": f"Repeated correction: {terms_str}",
            "theme_hash": theme["theme_hash"],
            "key_terms": theme["key_terms"],
            "occurrences": theme["total_occurrences"],
            "weighted_score": theme["weighted_score"],
            "sessions": list(theme["intra_session_detail"].keys()),
            "intra_session_detail": theme["intra_session_detail"],
            "evidence": [
                {
                    "session": p["session_id"],
                    "timestamp": p["timestamp"],
                    "user_message": _sanitize_text(p["user_text"], 300),
                    "preceding_action": {
                        "tools": p["assistant_tools"],
                        "files": p["assistant_files"],
                    },
                    "correction_strength": round(p["correction_strength"], 2),
                }
                for p in top_pairs
            ],
            "suggested_artifact": "claude_md_entry",
            "suggested_content": "",
            "confidence": confidence,
        })

    # Sort by weighted score descending
    results.sort(key=lambda r: r["weighted_score"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Post-action detection
# ---------------------------------------------------------------------------

def find_post_actions(sessions: dict) -> list:
    """Find patterns where user runs specific commands after Claude edits."""
    action_counts = defaultdict(
        lambda: {"count": 0, "sessions": set(), "evidence": []}
    )

    for session_id, messages in sessions.items():
        prev_was_edit = False
        prev_tool = ""

        for msg in messages:
            if msg["role"] == "assistant" and msg["tool_uses"]:
                for tool in msg["tool_uses"]:
                    if tool["name"] in ("Write", "Edit", "write", "edit"):
                        prev_was_edit = True
                        prev_tool = tool["name"]
                        break

            elif msg["role"] == "user" and prev_was_edit and msg["text"]:
                text = msg["text"].strip()
                for pattern in POST_ACTION_COMMANDS:
                    match = pattern.search(text)
                    if match:
                        cmd = match.group(0).lower().strip()
                        entry = action_counts[cmd]
                        entry["count"] += 1
                        entry["sessions"].add(session_id)
                        if len(entry["evidence"]) < 5:
                            entry["evidence"].append({
                                "session": session_id,
                                "timestamp": msg["timestamp"],
                                "user_message": _sanitize_text(text, 200),
                                "after_tool": prev_tool,
                            })
                        break
                prev_was_edit = False
            elif msg["role"] == "user":
                prev_was_edit = False

    results = []
    for cmd, data in action_counts.items():
        if data["count"] >= 3 and len(data["sessions"]) >= 2:
            results.append({
                "pattern": f"User runs '{cmd}' after Claude edits",
                "occurrences": data["count"],
                "sessions": list(data["sessions"]),
                "evidence": data["evidence"],
                "suggested_artifact": "hook",
                "suggested_content": "",
                "confidence": (
                    "high" if data["count"] >= 5 and len(data["sessions"]) >= 3
                    else "medium"
                ),
            })
    return results


# ---------------------------------------------------------------------------
# Repeated prompt detection (with key-term overlap)
# ---------------------------------------------------------------------------

def find_repeated_prompts(sessions: dict) -> list:
    """Find sessions starting with similar opening messages.

    Uses key-term Jaccard similarity instead of raw string matching.
    """
    openers = []
    for session_id, messages in sessions.items():
        for msg in messages:
            if msg["role"] == "user" and msg["text"].strip():
                text = _sanitize_text(msg["text"], 300)
                tokens = tokenize(text)
                openers.append((session_id, text, set(tokens)))
                break

    if len(openers) < 3:
        return []

    # Group by Jaccard similarity on tokens
    groups = []
    used = set()

    for i, (sid1, text1, tokens1) in enumerate(openers):
        if i in used:
            continue
        group = [(sid1, text1)]
        group_tokens = set(tokens1)
        used.add(i)

        for j, (sid2, text2, tokens2) in enumerate(openers):
            if j in used or j <= i:
                continue
            sim = jaccard(group_tokens, tokens2)
            if sim > 0.3:
                group.append((sid2, text2))
                group_tokens |= tokens2
                used.add(j)

        if len(group) >= 3:
            groups.append({
                "pattern": f"Similar opening prompt in {len(group)} sessions",
                "occurrences": len(group),
                "sessions": [s for s, _ in group],
                "evidence": [
                    {"session": s, "user_message": t} for s, t in group[:5]
                ],
                "suggested_artifact": "skill",
                "suggested_content": "",
                "confidence": "high" if len(group) >= 4 else "medium",
            })

    return groups


# ---------------------------------------------------------------------------
# Conversation pairs sampling (for deep analysis)
# ---------------------------------------------------------------------------

def _sample_pairs(all_pairs: List[dict],
                  max_pairs: int = 30,
                  max_per_session: int = 5,
                  max_sessions: int = 6) -> List[dict]:
    """Select a diverse sample of conversation pairs for deep LLM analysis.

    Picks from the most recent sessions, up to max_per_session per session,
    strips internal fields, and truncates text to keep the sample compact.
    """
    # Group by session, sort sessions by most recent pair timestamp
    by_session = {}  # type: dict
    for pair in all_pairs:
        sid = pair.get("session_id", "")
        by_session.setdefault(sid, []).append(pair)

    # Sort sessions by their most recent timestamp (descending)
    session_order = sorted(
        by_session.keys(),
        key=lambda s: max(
            (p.get("timestamp", "") for p in by_session[s]),
            default=""
        ),
        reverse=True,
    )

    sample = []
    for sid in session_order[:max_sessions]:
        pairs = by_session[sid]
        # Take the most recent pairs from each session
        pairs.sort(key=lambda p: p.get("turn_index", 0), reverse=True)
        for pair in pairs[:max_per_session]:
            sample.append({
                "session_id": pair.get("session_id", ""),
                "turn_index": pair.get("turn_index", 0),
                "user_text": pair.get("user_text", "")[:300],
                "classification": pair.get("classification", ""),
                "correction_strength": pair.get("correction_strength", 0),
                "assistant_text": pair.get("assistant_text", "")[:200],
                "assistant_tools": pair.get("assistant_tools", []),
                "assistant_files": pair.get("assistant_files", []),
            })
            if len(sample) >= max_pairs:
                return sample

    return sample


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analyze Claude Code session transcripts for patterns."
    )
    parser.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="Project root path (defaults to cwd).",
    )
    parser.add_argument(
        "--min-occurrences",
        type=int,
        default=2,
        help="Minimum occurrences to flag a pattern (default: 2).",
    )
    parser.add_argument(
        "--max-sessions",
        type=int,
        default=50,
        help="Maximum sessions to analyze (default: 50).",
    )
    args = parser.parse_args()

    root = (
        Path(args.project_root).resolve()
        if args.project_root
        else Path.cwd().resolve()
    )

    if not root.is_dir():
        print(f"Error: project root does not exist: {root}", file=sys.stderr)
        sys.exit(1)

    # Load feedback stats for threshold adjustment
    stats = load_feedback_stats()

    # Find all session directories (cross-worktree)
    session_dirs = find_all_project_session_dirs(root)

    # Compute precision info for output
    corr_prec = precision_rate(stats, "corrections")
    feedback_info = {
        "loaded": bool(stats.get("theme_outcomes")),
        "corrections_precision": round(corr_prec, 2) if corr_prec is not None else None,
        "suppressed_count": len(stats.get("suppressed_themes", [])),
    }

    output = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "project_dirs_matched": len(session_dirs),
        "sessions_analyzed": 0,
        "session_date_range": "",
        "feedback_stats": feedback_info,
        "candidates": {
            "corrections": [],
            "post_actions": [],
            "repeated_prompts": [],
        },
    }

    if not session_dirs:
        json.dump(output, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    # Load sessions (aggregated across all matched directories)
    sessions = load_sessions(session_dirs, args.max_sessions)
    output["sessions_analyzed"] = len(sessions)

    if not sessions:
        json.dump(output, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    # Compute date range
    all_timestamps = []
    for msgs in sessions.values():
        for msg in msgs:
            ts = msg.get("timestamp", "")
            if ts:
                all_timestamps.append(ts[:10])
    if all_timestamps:
        all_timestamps.sort()
        output["session_date_range"] = (
            f"{all_timestamps[0]} to {all_timestamps[-1]}"
        )

    # Run detectors
    output["candidates"]["corrections"] = find_corrections(sessions, stats)
    output["candidates"]["post_actions"] = find_post_actions(sessions)
    output["candidates"]["repeated_prompts"] = find_repeated_prompts(sessions)

    # Filter by min occurrences
    min_occ = args.min_occurrences
    for key in output["candidates"]:
        output["candidates"][key] = [
            c for c in output["candidates"][key]
            if c["occurrences"] >= min_occ
        ]

    # Build conversation pairs sample for deep analysis
    all_pairs = build_conversation_pairs(sessions)
    output["conversation_pairs_sample"] = _sample_pairs(all_pairs)

    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

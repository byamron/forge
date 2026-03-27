#!/bin/bash
# Forge SessionEnd hook — logs session and updates repo index for cross-worktree tracking.
# Reads hook input JSON from stdin, extracts session_id, appends to session log,
# and updates ~/.claude/forge/repo-index.json so future analysis can find all
# worktrees/checkouts of the same repo.

set -euo pipefail

# Read hook input from stdin
INPUT=$(cat)

# Extract session ID from the JSON input using python3
SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_id', d.get('sessionId', 'unknown')))" 2>/dev/null || echo "unknown")

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Find project root — walk up from cwd looking for .git or .claude
PROJECT_ROOT="$(pwd)"
while [ "$PROJECT_ROOT" != "/" ]; do
  if [ -d "$PROJECT_ROOT/.git" ] || [ -d "$PROJECT_ROOT/.claude" ]; then
    break
  fi
  PROJECT_ROOT="$(dirname "$PROJECT_ROOT")"
done

# Create forge directory if needed
mkdir -p "$PROJECT_ROOT/.claude/forge"

# Append session entry
echo "$TIMESTAMP $SESSION_ID" >> "$PROJECT_ROOT/.claude/forge/unanalyzed-sessions.log"

# --- Update repo index for cross-worktree discovery ---
# Maps git remote URL -> list of Claude Code project directory names.
# Stored globally at ~/.claude/forge/repo-index.json.

REMOTE_URL=$(git -C "$PROJECT_ROOT" remote get-url origin 2>/dev/null || echo "")
if [ -z "$REMOTE_URL" ]; then
  exit 0
fi

# Encode the project path as Claude Code stores it (/ -> -)
PROJECT_DIR_NAME=$(echo "$PROJECT_ROOT" | tr '/' '-')

# Update index atomically using python3 (handles JSON read-modify-write)
mkdir -p "$HOME/.claude/forge"
python3 -c "
import json, sys
from pathlib import Path

index_path = Path.home() / '.claude' / 'forge' / 'repo-index.json'
dir_name = '$PROJECT_DIR_NAME'

# Strip credentials from remote URL before storing (e.g., https://token@github.com/...)
from urllib.parse import urlparse, urlunparse
_parsed = urlparse('$REMOTE_URL')
if _parsed.username or _parsed.password:
    _clean = _parsed._replace(netloc=_parsed.hostname + (':' + str(_parsed.port) if _parsed.port else ''))
    remote = urlunparse(_clean)
else:
    remote = '$REMOTE_URL'

# Load existing index
index = {}
if index_path.is_file():
    try:
        with open(index_path) as f:
            index = json.load(f)
    except (json.JSONDecodeError, OSError):
        pass

# Add this directory to the remote's list (deduplicated)
dirs = index.get(remote, [])
if dir_name not in dirs:
    dirs.append(dir_name)
    index[remote] = dirs
    # Write atomically via temp file
    tmp = str(index_path) + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(index, f, indent=2)
        f.write('\n')
    Path(tmp).replace(index_path)
" 2>/dev/null || true

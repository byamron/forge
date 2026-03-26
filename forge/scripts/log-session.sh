#!/bin/bash
# Forge SessionEnd hook — logs session ID and timestamp for tracking unanalyzed sessions.
# Reads hook input JSON from stdin, extracts session_id, appends to log file.

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

"""Shared fixtures for Forge tests."""
import json
import pytest
from pathlib import Path


@pytest.fixture
def tmp_project(tmp_path):
    """Create a minimal project directory with .claude/ structure."""
    (tmp_path / ".claude" / "rules").mkdir(parents=True)
    (tmp_path / ".claude" / "forge" / "cache").mkdir(parents=True)
    (tmp_path / ".claude" / "skills").mkdir(parents=True)
    (tmp_path / ".claude" / "agents").mkdir(parents=True)
    (tmp_path / "CLAUDE.md").write_text("# Test Project\n")
    return tmp_path


@pytest.fixture
def sample_transcript_jsonl(tmp_path):
    """Create a sample JSONL transcript file with user/assistant pairs."""
    lines = [
        {
            "type": "user",
            "message": {"role": "user", "content": "Fix the login bug"},
            "timestamp": "2026-03-20T10:00:00Z",
            "sessionId": "test-session-1",
            "isSidechain": False,
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll fix the login bug."},
                    {
                        "type": "tool_use",
                        "name": "Edit",
                        "input": {"file_path": "/src/auth.py"},
                    },
                ],
            },
            "timestamp": "2026-03-20T10:00:05Z",
            "sessionId": "test-session-1",
            "isSidechain": False,
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": "No, don't use that approach. Use JWT instead.",
            },
            "timestamp": "2026-03-20T10:00:30Z",
            "sessionId": "test-session-1",
            "isSidechain": False,
        },
    ]
    filepath = tmp_path / "test-session-1.jsonl"
    with open(filepath, "w") as f:
        for entry in lines:
            f.write(json.dumps(entry) + "\n")
    return filepath

"""Shared fixtures for Forge tests."""
import json
import pytest
from pathlib import Path


@pytest.fixture
def tmp_project(tmp_path):
    """Create a minimal project directory with .claude/ structure."""
    (tmp_path / ".claude" / "rules").mkdir(parents=True)
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


# ---------------------------------------------------------------------------
# Synthetic profile fixtures (integration testing)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def synthetic_profiles(tmp_path_factory):
    """Generate all synthetic project profiles once per test session.

    Returns a dict of {profile_name: project_root_path}.
    """
    from generate_fixtures import generate_all

    base = tmp_path_factory.mktemp("synthetic")
    return generate_all(base)


@pytest.fixture
def swift_ios_project(synthetic_profiles):
    """Swift/iOS project root — memory promotions only."""
    return synthetic_profiles["swift-ios"]


@pytest.fixture
def react_ts_project(synthetic_profiles):
    """React/TypeScript project root — full config analysis surface."""
    return synthetic_profiles["react-ts"]


@pytest.fixture
def python_corrections_project(synthetic_profiles):
    """Python project root — transcript correction patterns."""
    return synthetic_profiles["python-corrections"]


@pytest.fixture
def rust_minimal_project(synthetic_profiles):
    """Rust project root — below-threshold transcript signals."""
    return synthetic_profiles["rust-minimal"]


@pytest.fixture
def fullstack_mature_project(synthetic_profiles):
    """Full-stack project root — dismissed/suppressed filtering."""
    return synthetic_profiles["fullstack-mature"]

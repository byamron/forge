"""Tests for check-pending.py: session start terminal notifications."""

import json
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

# Add the scripts directory to the path so we can import check-pending functions.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "forge" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

# Import after path setup. The module name has a hyphen, use importlib.
import importlib
check_pending = importlib.import_module("check-pending")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proposal(
    pid: str = "test-proposal",
    status: str = "pending",
) -> Dict[str, Any]:
    return {
        "id": pid,
        "confidence": "high",
        "impact": "high",
        "occurrences": 6,
        "sessions": 4,
        "description": "Add rule: always use vitest",
        "evidence_summary": "Corrected 8 times across 6 sessions",
        "status": status,
        "type": "rule",
    }


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# load_settings
# ---------------------------------------------------------------------------

class TestLoadSettings:
    def test_defaults_when_no_file(self, tmp_path):
        orig = check_pending.resolve_user_file
        check_pending.resolve_user_file = lambda root, rel: tmp_path / rel
        try:
            settings = check_pending.load_settings(tmp_path)
        finally:
            check_pending.resolve_user_file = orig
        assert settings["nudge_level"] == "balanced"
        assert settings["proactive_proposals"] is True

    def test_reads_settings(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        _write_json(settings_file, {"nudge_level": "eager", "proactive_proposals": False})
        orig = check_pending.resolve_user_file
        check_pending.resolve_user_file = lambda root, rel: settings_file
        try:
            settings = check_pending.load_settings(tmp_path)
        finally:
            check_pending.resolve_user_file = orig
        assert settings["nudge_level"] == "eager"
        assert settings["proactive_proposals"] is False

    def test_invalid_nudge_level_falls_back(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        _write_json(settings_file, {"nudge_level": "invalid_level"})
        orig = check_pending.resolve_user_file
        check_pending.resolve_user_file = lambda root, rel: settings_file
        try:
            settings = check_pending.load_settings(tmp_path)
        finally:
            check_pending.resolve_user_file = orig
        assert settings["nudge_level"] == "balanced"


# ---------------------------------------------------------------------------
# count_total_sessions
# ---------------------------------------------------------------------------

class TestCountTotalSessions:
    def test_no_files(self, tmp_path):
        assert check_pending.count_total_sessions(tmp_path) == 0

    def test_from_unanalyzed_log(self, tmp_path):
        (tmp_path / "unanalyzed-sessions.log").write_text("a\nb\nc\n")
        assert check_pending.count_total_sessions(tmp_path) == 3

    def test_from_session_log(self, tmp_path):
        (tmp_path / "session-log.jsonl").write_text('{"a":1}\n{"b":2}\n')
        assert check_pending.count_total_sessions(tmp_path) == 2

    def test_takes_max(self, tmp_path):
        (tmp_path / "unanalyzed-sessions.log").write_text("a\nb\n")
        (tmp_path / "session-log.jsonl").write_text('{"a":1}\n{"b":2}\n{"c":3}\n{"d":4}\n{"e":5}\n')
        assert check_pending.count_total_sessions(tmp_path) == 5


# ---------------------------------------------------------------------------
# load_pending_proposals
# ---------------------------------------------------------------------------

class TestLoadPendingProposals:
    def test_no_file(self, tmp_path):
        orig = check_pending.resolve_user_file
        check_pending.resolve_user_file = lambda root, rel: tmp_path / rel
        try:
            result = check_pending.load_pending_proposals(tmp_path)
        finally:
            check_pending.resolve_user_file = orig
        assert result == []

    def test_loads_pending_only(self, tmp_path):
        proposals_file = tmp_path / "proposals" / "pending.json"
        _write_json(proposals_file, [
            _make_proposal(pid="p1", status="pending"),
            _make_proposal(pid="p2", status="dismissed"),
            _make_proposal(pid="p3", status="pending"),
        ])
        orig = check_pending.resolve_user_file
        check_pending.resolve_user_file = lambda root, rel: tmp_path / rel
        try:
            result = check_pending.load_pending_proposals(tmp_path)
        finally:
            check_pending.resolve_user_file = orig
        assert len(result) == 2
        assert {p["id"] for p in result} == {"p1", "p3"}


# ---------------------------------------------------------------------------
# main() integration
# ---------------------------------------------------------------------------

class TestMain:
    """Integration tests that exercise main() output for each notification state."""

    def _run_main(self, tmp_path, proposals=None, settings=None,
                  unanalyzed_count=0, session_log_count=0):
        """Set up state and capture main() stdout."""
        user_data = tmp_path / "user-data"
        user_data.mkdir(exist_ok=True)

        if proposals is not None:
            _write_json(user_data / "proposals" / "pending.json", proposals)

        if settings is not None:
            _write_json(user_data / "settings.json", settings)

        if unanalyzed_count > 0:
            (user_data / "unanalyzed-sessions.log").write_text(
                "\n".join("s{}".format(i) for i in range(unanalyzed_count)) + "\n"
            )

        if session_log_count > 0:
            (user_data / "session-log.jsonl").write_text(
                "\n".join('{{"n":{}}}'.format(i) for i in range(session_log_count)) + "\n"
            )

        project_root = tmp_path / "project"
        project_root.mkdir(exist_ok=True)
        (project_root / ".git").mkdir(exist_ok=True)

        import io
        captured = io.StringIO()

        with patch.object(check_pending, "find_project_root", return_value=project_root), \
             patch.object(check_pending, "get_user_data_dir", return_value=user_data), \
             patch.object(check_pending, "resolve_user_file",
                          side_effect=lambda root, rel: user_data / rel), \
             patch("sys.stdout", captured):
            check_pending.main()

        output = captured.getvalue()
        if not output.strip():
            return None
        return json.loads(output)

    # --- Proposals exist ---

    def test_single_proposal(self, tmp_path):
        result = self._run_main(tmp_path, proposals=[_make_proposal()])
        assert result["systemMessage"] == "Forge has 1 proposal. Run `/forge` to review."

    def test_multiple_proposals(self, tmp_path):
        result = self._run_main(tmp_path, proposals=[
            _make_proposal(pid="p1"),
            _make_proposal(pid="p2"),
            _make_proposal(pid="p3"),
        ])
        assert result["systemMessage"] == "Forge has 3 proposals. Run `/forge` to review."

    # --- No proposals, sessions tracked ---

    def test_health_signal_with_sessions(self, tmp_path):
        result = self._run_main(tmp_path, proposals=[], session_log_count=23)
        assert result["systemMessage"] == "Forge: tracking 23 sessions for this project."

    def test_health_signal_singular(self, tmp_path):
        result = self._run_main(tmp_path, proposals=[], session_log_count=1)
        assert result["systemMessage"] == "Forge: tracking 1 session for this project."

    # --- Empty state ---

    def test_empty_state_silence(self, tmp_path):
        """No proposals, no sessions → no output."""
        result = self._run_main(tmp_path, proposals=[])
        assert result is None

    def test_first_session_silence(self, tmp_path):
        """First session ever, nothing to report."""
        result = self._run_main(tmp_path)
        assert result is None

    # --- Settings ---

    def test_proactive_disabled_skips_proposals(self, tmp_path):
        """proactive_proposals=false → don't show proposal count."""
        result = self._run_main(
            tmp_path,
            proposals=[_make_proposal()],
            settings={"proactive_proposals": False},
            session_log_count=10,
        )
        # Should fall through to health signal instead
        assert "tracking 10 sessions" in result["systemMessage"]

    def test_proactive_disabled_no_sessions_silence(self, tmp_path):
        """proactive_proposals=false, no sessions → silence."""
        result = self._run_main(
            tmp_path,
            proposals=[_make_proposal()],
            settings={"proactive_proposals": False},
        )
        assert result is None

    def test_quiet_mode_suppresses_health(self, tmp_path):
        """quiet mode suppresses health signal when no proposals."""
        result = self._run_main(
            tmp_path,
            proposals=[],
            settings={"nudge_level": "quiet"},
            session_log_count=10,
        )
        assert result is None

    def test_quiet_mode_still_shows_proposals(self, tmp_path):
        """quiet mode does NOT suppress proposal count."""
        result = self._run_main(
            tmp_path,
            proposals=[_make_proposal()],
            settings={"nudge_level": "quiet"},
        )
        assert result["systemMessage"] == "Forge has 1 proposal. Run `/forge` to review."

    # --- Proposals take priority over health ---

    def test_proposals_override_health_signal(self, tmp_path):
        """When proposals exist, show proposal count, not session tracking."""
        result = self._run_main(
            tmp_path,
            proposals=[_make_proposal()],
            session_log_count=50,
        )
        assert "1 proposal" in result["systemMessage"]
        assert "tracking" not in result["systemMessage"]

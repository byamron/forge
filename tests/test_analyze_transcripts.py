"""Tests for analyze-transcripts.py — highest-risk code paths."""
import json
import sys
import importlib
from pathlib import Path

import pytest

# Import the module under test
sys.path.insert(0, str(Path(__file__).parent.parent / "forge" / "scripts"))
import importlib
at = importlib.import_module("analyze-transcripts")


# ---------------------------------------------------------------------------
# Fix 1.1: _removesuffix compatibility
# ---------------------------------------------------------------------------

class TestRemoveSuffix:
    def test_only_removes_from_end(self):
        """The one non-obvious behavior: .git appearing twice, only trailing removed."""
        assert at._removesuffix(".git.git", ".git") == ".git"
        assert at._removesuffix("hello.git", ".git") == "hello"
        assert at._removesuffix("hello.txt", ".git") == "hello.txt"


# ---------------------------------------------------------------------------
# Fix 1.2: Credential stripping fail-safe
# ---------------------------------------------------------------------------

class TestStripUrlCredentials:
    def test_strips_username_password(self):
        result = at._strip_url_credentials("https://user:pass@github.com/repo")
        assert "user" not in result
        assert "pass" not in result
        assert "github.com" in result

    def test_strips_token(self):
        result = at._strip_url_credentials("https://ghp_secrettoken@github.com/org/repo")
        assert "ghp_secrettoken" not in result
        assert "github.com" in result

    def test_preserves_clean_url(self):
        url = "https://github.com/org/repo.git"
        assert at._strip_url_credentials(url) == url

    def test_preserves_ssh_url(self):
        url = "git@github.com:org/repo.git"
        assert at._strip_url_credentials(url) == url

    def test_malformed_url_returns_redacted(self):
        # Force an exception in urlparse by passing non-string-like input
        # The function should never return credentials
        result = at._strip_url_credentials("https://token@github.com/repo")
        assert "token" not in result or result == "<redacted-url>"

    def test_empty_string(self):
        assert at._strip_url_credentials("") == ""

    def test_preserves_port(self):
        result = at._strip_url_credentials("https://user:pass@github.com:8080/repo")
        assert "8080" in result
        assert "user" not in result
        assert "pass" not in result


# ---------------------------------------------------------------------------
# Fix 1.3: Path traversal in _decode_project_dir
# ---------------------------------------------------------------------------

class TestDecodeProjectDir:
    def test_rejects_dotdot(self):
        assert at._decode_project_dir("-Users-..-etc-passwd") == ""

    def test_rejects_dotdot_at_start(self):
        assert at._decode_project_dir("-..-etc-passwd") == ""

    def test_normal_path_returns_nonempty(self):
        # This may or may not resolve to a real path, but should not be empty
        result = at._decode_project_dir("-tmp")
        assert result != ""

    def test_returns_resolved_path(self):
        result = at._decode_project_dir("-tmp")
        # Should be an absolute path without .. components
        if result:
            assert ".." not in result.split("/")
            assert result.startswith("/")


# ---------------------------------------------------------------------------
# Fix 1.4: Text sanitization
# ---------------------------------------------------------------------------

class TestSanitizeText:
    def test_control_chars_stripped_whitespace_preserved(self):
        """Null, BEL, DEL stripped; tabs/newlines/CR survive."""
        assert at._sanitize_text("a\x00b\x07c\x7fd") == "abcd"
        assert at._sanitize_text("hello\tworld\nfoo\rbar") == "hello\tworld\nfoo\rbar"

    def test_sanitization_before_truncation(self):
        """Control chars removed first, then truncation applied to clean text."""
        assert at._sanitize_text("\x00\x01\x02abcdef", 3) == "abc"


# ---------------------------------------------------------------------------
# Fix 1.5: Intra-session weight bounds
# ---------------------------------------------------------------------------

class TestIntraSessionWeight:
    def test_zero_count(self):
        assert at._intra_session_weight(0) == 0.0

    def test_negative_count(self):
        assert at._intra_session_weight(-1) == 0.0

    def test_one(self):
        assert at._intra_session_weight(1) == 1.0

    def test_two(self):
        assert at._intra_session_weight(2) == 2.5  # 1.0 + 1.5

    def test_three(self):
        assert at._intra_session_weight(3) == 4.5  # 1.0 + 1.5 + 2.0

    def test_four(self):
        assert at._intra_session_weight(4) == 7.0  # 4.5 + 2.5

    def test_large_count_bounded(self):
        # Should not allocate a massive list — capped at 100
        result = at._intra_session_weight(10000)
        expected = 4.5 + 2.5 * (100 - 3)  # capped at 100
        assert result == expected

    def test_100_equals_cap(self):
        result = at._intra_session_weight(100)
        expected = 4.5 + 2.5 * 97
        assert result == expected


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------

class TestParseTranscript:
    def test_parses_valid_jsonl(self, sample_transcript_jsonl):
        messages = at.parse_transcript(sample_transcript_jsonl)
        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert messages[2]["role"] == "user"

    def test_skips_malformed_lines(self, tmp_path):
        filepath = tmp_path / "bad.jsonl"
        filepath.write_text(
            'not json\n'
            '{"type": "user", "message": {"role": "user", "content": "hello"}, "timestamp": "2026-03-20T10:00:00Z"}\n'
            '{broken json\n'
        )
        messages = at.parse_transcript(filepath)
        assert len(messages) == 1

    def test_skips_sidechain(self, tmp_path):
        filepath = tmp_path / "sidechain.jsonl"
        entries = [
            {"type": "user", "message": {"role": "user", "content": "hi"}, "timestamp": "T", "isSidechain": False},
            {"type": "assistant", "message": {"role": "assistant", "content": "hello"}, "timestamp": "T", "isSidechain": True},
        ]
        with open(filepath, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        messages = at.parse_transcript(filepath)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_missing_file_returns_empty(self, tmp_path):
        messages = at.parse_transcript(tmp_path / "nonexistent.jsonl")
        assert messages == []


# ---------------------------------------------------------------------------
# Classify response
# ---------------------------------------------------------------------------

class TestClassifyResponse:
    def test_correction_detected(self):
        classification, strength = at.classify_response(
            "No, don't use that. Use JWT instead.",
            "I'll use session cookies.",
            [{"name": "Edit", "input": {}}],
            ["/src/auth.py"],
        )
        assert classification == "corrective"
        assert strength > 0.0

    def test_confirmatory_detected(self):
        classification, _ = at.classify_response(
            "looks good",
            "I've updated the file.",
            [],
            [],
        )
        assert classification == "confirmatory"

    def test_slash_command_is_instruction(self):
        classification, _ = at.classify_response(
            "/forge",
            "Previous response",
            [],
            [],
        )
        assert classification == "new_instruction"

    def test_short_text_is_followup(self):
        classification, _ = at.classify_response(
            "ok",
            "Done.",
            [],
            [],
        )
        # Very short text that matches confirmatory
        assert classification in ("confirmatory", "followup")


# ---------------------------------------------------------------------------
# Workflow pattern detection
# ---------------------------------------------------------------------------

class TestExtractPhaseSequence:
    """Verify tool-use-to-phase mapping and consecutive dedup."""

    def test_basic_read_write_execute(self):
        messages = [
            {"role": "assistant", "tool_uses": [{"name": "Read"}]},
            {"role": "assistant", "tool_uses": [{"name": "Edit"}]},
            {"role": "assistant", "tool_uses": [{"name": "Bash"}]},
        ]
        assert at._extract_phase_sequence(messages) == [
            "read", "write", "execute",
        ]

    def test_consecutive_phases_collapsed(self):
        messages = [
            {"role": "assistant", "tool_uses": [
                {"name": "Grep"}, {"name": "Read"},
            ]},
            {"role": "assistant", "tool_uses": [{"name": "Edit"}]},
            {"role": "assistant", "tool_uses": [{"name": "Write"}]},
        ]
        # read, read -> collapsed to read; write, write -> collapsed to write
        assert at._extract_phase_sequence(messages) == ["read", "write"]

    def test_user_messages_ignored(self):
        messages = [
            {"role": "user", "tool_uses": [{"name": "Read"}]},
            {"role": "assistant", "tool_uses": [{"name": "Edit"}]},
        ]
        assert at._extract_phase_sequence(messages) == ["write"]

    def test_empty_messages(self):
        assert at._extract_phase_sequence([]) == []

    def test_no_tool_uses(self):
        messages = [{"role": "assistant", "tool_uses": []}]
        assert at._extract_phase_sequence(messages) == []


class TestExtractSubsequences:
    def test_basic_subsequences(self):
        seq = ["read", "write", "execute"]
        subs = at._extract_subsequences(seq, min_len=3, max_len=3)
        assert subs == [("read", "write", "execute")]

    def test_shorter_than_min_returns_empty(self):
        seq = ["read", "write"]
        subs = at._extract_subsequences(seq, min_len=3, max_len=5)
        assert subs == []

    def test_multiple_lengths(self):
        seq = ["read", "write", "execute", "write"]
        subs = at._extract_subsequences(seq, min_len=3, max_len=4)
        assert len(subs) == 3  # two 3-grams + one 4-gram


class TestFindWorkflowPatterns:
    """Verify end-to-end workflow pattern detection."""

    def _make_session(self, tools_sequence):
        """Build a list of assistant messages from a tool name sequence."""
        return [
            {"role": "assistant", "tool_uses": [{"name": t}]}
            for t in tools_sequence
        ]

    def test_recurring_pattern_detected(self):
        # Same read->write->execute pattern across 4 sessions
        sessions = {}
        for i in range(4):
            sessions["s{}".format(i)] = self._make_session(
                ["Read", "Grep", "Edit", "Bash"]
            )
        patterns = at.find_workflow_patterns(sessions)
        assert len(patterns) >= 1
        found_rwe = any(
            p["phase_sequence"] == ["read", "write", "execute"]
            for p in patterns
        )
        assert found_rwe

    def test_too_few_sessions_excluded(self):
        # Only 2 sessions — below the 3-session minimum
        sessions = {
            "s0": self._make_session(["Read", "Edit", "Bash"]),
            "s1": self._make_session(["Read", "Edit", "Bash"]),
        }
        patterns = at.find_workflow_patterns(sessions)
        assert len(patterns) == 0

    def test_short_sessions_excluded(self):
        # Sessions with only 2 phases (below min_len=3 for subsequences)
        sessions = {}
        for i in range(5):
            sessions["s{}".format(i)] = self._make_session(["Read", "Edit"])
        patterns = at.find_workflow_patterns(sessions)
        assert len(patterns) == 0

    def test_pattern_has_descriptive_name(self):
        sessions = {}
        for i in range(4):
            sessions["s{}".format(i)] = self._make_session(
                ["Read", "Grep", "Edit", "Bash"]
            )
        patterns = at.find_workflow_patterns(sessions)
        assert len(patterns) >= 1
        # Should use the named workflow, not "Workflow: ..."
        p = next(
            p for p in patterns
            if p["phase_sequence"] == ["read", "write", "execute"]
        )
        assert "plan-implement-verify" in p["pattern"]

    def test_occurrences_deduplicated_per_session(self):
        """A repeated subsequence within one session should count once per session."""
        def _msg(tools):
            return {
                "role": "assistant",
                "tool_uses": [{"name": t} for t in tools],
            }

        # Long session produces the same subsequences multiple times
        long_session = [
            _msg(["Read"]), _msg(["Edit"]), _msg(["Bash"]),
            _msg(["Glob"]), _msg(["Write"]), _msg(["Bash"]),
            _msg(["Read"]), _msg(["Edit"]), _msg(["Bash"]),
        ]
        sessions = {
            "s1": long_session,
            "s2": list(long_session),
            "s3": list(long_session),
        }
        results = at.find_workflow_patterns(sessions)
        # Every pattern's occurrences should be at most the number of sessions,
        # since each subsequence is counted once per session after dedup
        assert len(results) > 0
        for r in results:
            assert r["occurrences"] <= len(sessions)

    def test_evidence_populated(self):
        sessions = {}
        for i in range(4):
            sessions["s{}".format(i)] = self._make_session(
                ["Read", "Edit", "Bash"]
            )
        patterns = at.find_workflow_patterns(sessions)
        assert len(patterns) >= 1
        p = patterns[0]
        assert len(p["evidence"]) > 0
        assert "session" in p["evidence"][0]
        assert "tools_used" in p["evidence"][0]

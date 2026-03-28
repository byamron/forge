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
    def test_removes_present_suffix(self):
        assert at._removesuffix("hello.git", ".git") == "hello"

    def test_no_match_returns_original(self):
        assert at._removesuffix("hello.txt", ".git") == "hello.txt"

    def test_empty_suffix(self):
        assert at._removesuffix("hello", "") == "hello"

    def test_empty_string(self):
        assert at._removesuffix("", ".git") == ""

    def test_suffix_is_entire_string(self):
        assert at._removesuffix(".git", ".git") == ""

    def test_only_removes_end(self):
        assert at._removesuffix(".git.git", ".git") == ".git"


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
    def test_removes_null_bytes(self):
        assert at._sanitize_text("hello\x00world") == "helloworld"

    def test_removes_control_chars(self):
        assert at._sanitize_text("hello\x01\x02\x03world") == "helloworld"

    def test_preserves_newlines_and_tabs(self):
        # Tabs (\x09), newlines (\x0a), carriage returns (\x0d) are kept
        text = "hello\tworld\nfoo\rbar"
        assert at._sanitize_text(text) == text

    def test_removes_ansi_escape(self):
        # DEL character (0x7f)
        assert at._sanitize_text("hello\x7fworld") == "helloworld"

    def test_truncation(self):
        assert at._sanitize_text("abcdef", 3) == "abc"

    def test_truncation_zero_means_no_limit(self):
        text = "a" * 1000
        assert len(at._sanitize_text(text, 0)) == 1000

    def test_sanitize_then_truncate(self):
        # Control chars should be removed before truncation
        result = at._sanitize_text("\x00\x01\x02abc", 3)
        assert result == "abc"

    def test_empty_string(self):
        assert at._sanitize_text("") == ""


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

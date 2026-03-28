"""Cross-cutting security regression tests.

These tests verify security invariants across the entire codebase,
preventing regressions on fixes applied during enterprise hardening.
"""
import subprocess
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "forge" / "scripts"


def _grep_scripts(pattern: str) -> list:
    """Search all Python scripts for a pattern, return matching lines."""
    matches = []
    for script in SCRIPTS_DIR.glob("*.py"):
        for i, line in enumerate(script.read_text().splitlines(), 1):
            if pattern in line and not line.strip().startswith("#") and not line.strip().startswith('"""') and "docstring" not in line:
                matches.append(f"{script.name}:{i}: {line.strip()}")
    return matches


class TestNoShellTrue:
    """Verify no subprocess calls use shell=True."""

    def test_no_shell_true_in_python(self):
        matches = _grep_scripts("shell=True")
        assert matches == [], f"shell=True found in scripts: {matches}"


class TestNoRawRemoveSuffix:
    """Verify str.removesuffix() is not used (Python 3.9+ only)."""

    def test_no_removesuffix_method_calls(self):
        matches = []
        for script in SCRIPTS_DIR.glob("*.py"):
            for i, line in enumerate(script.read_text().splitlines(), 1):
                # Match .removesuffix( but not _removesuffix( or docstring mentions
                stripped = line.strip()
                if ".removesuffix(" in stripped and not stripped.startswith("#") and not stripped.startswith('"""'):
                    # Exclude our helper function definition
                    if "def _removesuffix" not in stripped and 'str.removesuffix()' not in stripped:
                        matches.append(f"{script.name}:{i}: {stripped}")
        assert matches == [], f"Raw .removesuffix() calls found: {matches}"


class TestCredentialStripping:
    """Verify credentials never survive stripping."""

    def test_token_url_stripped(self):
        import sys
        sys.path.insert(0, str(SCRIPTS_DIR))
        import importlib
        at = importlib.import_module("analyze-transcripts")

        test_urls = [
            "https://ghp_secret123@github.com/org/repo.git",
            "https://user:password@github.com/org/repo.git",
            "https://oauth2:token@gitlab.com/org/repo.git",
        ]
        for url in test_urls:
            result = at._strip_url_credentials(url)
            assert "ghp_secret123" not in result, f"Token leaked in: {result}"
            assert "password" not in result, f"Password leaked in: {result}"
            assert "token" not in result or result == "<redacted-url>", f"Token leaked in: {result}"

    def test_credential_fail_safe_returns_redacted(self):
        """If stripping fails, result should be <redacted-url>, not the original."""
        import sys
        sys.path.insert(0, str(SCRIPTS_DIR))
        import importlib
        at = importlib.import_module("analyze-transcripts")

        # The function should handle any URL without leaking credentials
        result = at._strip_url_credentials("https://secret@host.com/repo")
        assert "secret" not in result


class TestNoEvalOrExec:
    """Verify no eval() or exec() calls in scripts."""

    def test_no_eval(self):
        matches = _grep_scripts("eval(")
        # Filter out comments
        real_matches = [m for m in matches if "# " not in m.split("eval(")[0][-5:]]
        assert real_matches == [], f"eval() found in scripts: {real_matches}"

    def test_no_exec(self):
        matches = _grep_scripts("exec(")
        real_matches = [m for m in matches if "# " not in m.split("exec(")[0][-5:]]
        assert real_matches == [], f"exec() found in scripts: {real_matches}"


class TestPathTraversal:
    """Verify path traversal defenses."""

    def test_decode_project_dir_rejects_dotdot(self):
        import sys
        sys.path.insert(0, str(SCRIPTS_DIR))
        import importlib
        at = importlib.import_module("analyze-transcripts")

        dangerous_inputs = [
            "-Users-..-etc-passwd",
            "-..-etc-shadow",
            "-tmp-..-etc-hosts",
        ]
        for encoded in dangerous_inputs:
            result = at._decode_project_dir(encoded)
            assert result == "", f"Path traversal not blocked for: {encoded}"

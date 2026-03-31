# Transcript Discovery Integration Test Plan

## Problem

`find_all_project_session_dirs()` in `analyze-transcripts.py` is the most fragile
code in the pipeline. It uses 5 strategies to find all `~/.claude/projects/` directories
belonging to the current repo, involving subprocess calls to git, path encoding/decoding,
a forward index, and workspace-prefix heuristics. There are zero integration tests for
this function — only unit tests for the helper functions it calls (`_encode_path_as_project_dir`,
`_decode_project_dir`, `_strip_url_credentials`).

A regression here has two failure modes:
1. **Silent data loss** — Forge misses worktree transcript dirs and analyzes fewer sessions
   than it should, producing weaker or missing proposals.
2. **Cross-project leakage** — Forge includes transcript dirs from unrelated projects,
   violating the security boundary (see `.claude/rules/security.md`).

## What to test

### Strategy 1: Exact path match
- Encode current project path → find matching dir in fake `~/.claude/projects/`
- Verify it matches when the dir exists, returns empty when it doesn't.

### Strategy 2: Git worktree list
- Mock `git worktree list --porcelain` output with 2-3 worktree paths
- Create matching encoded dirs in the fake projects directory
- Verify all worktree dirs are found

### Strategy 3: Forward index (repo-index.json)
- Create a `~/.claude/forge/repo-index.json` with the current remote URL mapped to dir names
- Verify those dirs are included in results
- Verify dirs for a DIFFERENT remote URL are NOT included

### Strategy 4: Workspace-prefix heuristic
- Set up: main checkout at `/workspace/main`, worktree at `/workspace/feature-branch`
- Create encoded dirs for both in projects/
- Add a third dir `/workspace/old-branch` (not in worktree list, not in index)
- Verify the prefix heuristic finds it because it shares the `/workspace/` prefix
- **Critical negative test:** Add a sibling `/workspace/different-repo` with a different
  git remote. Verify it is NOT included (cross-project leakage prevention).

### Strategy 5: Git remote scan fallback
- Set up: only 1 match from strategies 1-4 (< 2 threshold)
- Create additional project dirs whose decoded paths exist on disk with matching remotes
- Verify the scan finds them
- Verify it does NOT run when strategies 1-4 already found 2+ matches (perf guard)

### Edge cases
- No `~/.claude/projects/` directory exists → returns empty list
- No git remote (local-only repo) → only strategy 1 runs
- Git subprocess timeout → graceful fallback, no crash
- Encoded dir exists but decoded path no longer exists on disk → skipped safely
- JSONL file sorting — verify results ordered by most recent transcript mtime

## Approach

The function depends on three external systems: the filesystem at `~/.claude/projects/`,
git subprocess calls, and `repo-index.json`. All three need to be controlled.

### Option A: monkeypatch + tmp_path (recommended)
- Use `monkeypatch` to redirect `Path.home()` to a tmp dir (so `~/.claude/projects/` resolves there)
- Use `monkeypatch` on `subprocess.run` to return canned git responses
- Create real directory structures in tmp_path for path existence checks
- Pro: tests run fast, no real git repos needed, deterministic
- Con: monkeypatching Path.home() is broad — need to ensure it doesn't break other things

### Option B: refactor for dependency injection
- Extract `_get_git_remote` and `_load_repo_index` into injectable dependencies
- Pass a `ProjectsDir` abstraction instead of hardcoding `Path.home() / ".claude" / "projects"`
- Pro: cleaner, more testable
- Con: refactoring production code for testability — larger scope

**Recommendation:** Start with Option A. If the monkeypatching gets unwieldy, refactor
toward Option B as needed. The function is already ~140 lines with clear strategy boundaries,
so targeted monkeypatching should work without major contortion.

### Test file
`tests/test_session_discovery.py` — separate from `test_analyze_transcripts.py` because
the discovery function has different dependencies (subprocess mocking, filesystem layout)
than the analysis functions.

### Fixture
A reusable fixture that creates a fake `~/.claude/projects/` layout with encoded dirs,
JSONL files, and a repo-index.json. Similar to the synthetic profile generator but focused
on the directory structure rather than transcript content.

## Estimated scope
~15-20 tests, covering the 5 strategies + edge cases + the critical cross-project leakage
negative test. Implementation should be straightforward once the monkeypatch fixture is set up.

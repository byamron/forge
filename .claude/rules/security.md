Forge is a read-analyze-suggest tool. It must never cause data loss, introduce vulnerabilities, or make unsanctioned changes. All generated artifacts are drafts the user reviews before applying.

## Read boundary

Forge's data access is equivalent to Claude Code's own — the plugin does not gain additional filesystem permissions. To prevent unintentional cross-project leakage:

- During normal analysis (`/forge`, `/forge --deep`), only read files within the current project directory, its `.claude/` configuration, and `~/.claude/projects/` directories matched by git remote URL for the current project.
- Never proactively browse, list, or read other project directories under `~/.claude/projects/` as part of analysis. Cross-project data must never unintentionally influence proposals.
- If a user explicitly asks to analyze or reference another project, comply — but tell them which directories you're accessing and that the data is outside the current project's scope. The user always has the authority to direct what Forge reads.
- The only cross-project file accessed during normal analysis is `~/.claude/forge/analyzer-stats.json`, which contains aggregate counts only (no content, no project names).

## Write boundary

All file writes are restricted to `.claude/` (project-level config — rules, skills, agents, settings), `CLAUDE.md` at the project root, and `~/.claude/forge/projects/<hash>/` (all Forge runtime data — decisions, caches, session log, shared across worktrees). Forge does not write to `.claude/forge/` in the project directory. Forge never writes to:
- Source code directories
- User-level config other than `~/.claude/forge/` (the user can choose to move artifacts elsewhere, but Forge never suggests it)
- Absolute paths or paths containing `..`

## Shell safety

- Never interpolate untrusted values into shell command strings or Python `-c` code. Pass via environment variables or stdin.
- All `subprocess` calls must use list form (never `shell=True`).
- Hook commands must be single, well-known tool invocations (formatters, linters). No chained commands, no redirects, no `rm`/`git push`/network calls.

## Agent isolation

- `session-analyzer` is read-only: `disallowedTools: [Write, Edit, Bash]`.
- `artifact-generator` cannot run arbitrary commands: `disallowedTools: [Bash]`.
- Both agents use `model: sonnet` and `effort: low` to minimize blast radius from misinterpretation.

## Data handling

- Git remote URLs are stripped of embedded credentials before storage. On parse failure, URLs are replaced with `<redacted-url>` — never returned as-is.
- User message text is sanitized (control characters stripped) and truncated (500 chars in analysis, 300 in proposals) to limit exposure.
- Forge never reads or stores API keys, tokens, `.env` files, or credentials.
- All analysis is scoped to the current project. Never read, reference, or reason about transcripts, memory files, or configuration from unrelated projects.
- Decoded project directory paths are resolved (`Path.resolve()`) to prevent symlink-based traversal.

## Destructive operations

- Forge never deletes user files. The only deletions allowed are: (1) removing a legacy `.claude/commands/*.md` when the user explicitly approves migration to the modern skills format, and (2) removing legacy `.claude/forge/` files during transparent migration to user-level storage (`resolve_user_file()` copies to new location then deletes old).
- Forge never overwrites `.claude/settings.json`. It always reads, merges, and writes back.
- Generated hooks must be non-destructive (format, lint, validate, log only).
- Generated skills and agents are drafts. They never auto-execute — the user invokes them.

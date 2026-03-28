Forge is a read-analyze-suggest tool. It must never cause data loss, introduce vulnerabilities, or make unsanctioned changes. All generated artifacts are drafts the user reviews before applying.

## Write boundary

All file writes are restricted to `.claude/` (project-level config) and `CLAUDE.md` at the project root. Forge never writes to:
- Source code directories
- User-level config (`~/.claude/`) — the user can choose to move artifacts there, but Forge never suggests it
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
- All analysis is scoped to the current project. Forge never reads transcripts from unrelated projects.
- Decoded project directory paths are resolved (`Path.resolve()`) to prevent symlink-based traversal.

## Destructive operations

- Forge never deletes user files. The only deletion allowed is removing a legacy `.claude/commands/*.md` when the user explicitly approves migration to the modern skills format.
- Forge never overwrites `.claude/settings.json`. It always reads, merges, and writes back.
- Generated hooks must be non-destructive (format, lint, validate, log only).
- Generated skills and agents are drafts. They never auto-execute — the user invokes them.

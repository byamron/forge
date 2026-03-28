# Forge — Claude Code Infrastructure Plugin

## Project

Forge is a Claude Code plugin that analyzes sessions, configuration, and auto-memory to generate optimized rules, skills, hooks, agents, and reference docs. It manages context architecture as a living system.

The plugin lives in `forge/` and is tested with `claude --plugin-dir ./forge`. After changes to skills, agents, or hooks, run `/reload-plugins` to pick up updates.

## Architecture

- **Skills** (`forge/skills/*/SKILL.md`): User-facing commands — `/forge` (unified analysis + review), `/forge:settings` (nudge frequency config), `/forge:version` (installed version and freshness check)
- **Agents** (`forge/agents/*.md`): Subagents — `session-analyzer` (LLM analysis pass for deep mode)
- **Scripts** (`forge/scripts/*.py`): Zero-token Phase A analysis — `analyze-config.py`, `analyze-transcripts.py`, `analyze-memory.py`
- **Hooks** (`forge/hooks/hooks.json`): SessionEnd hook for session tracking
- **References** (`forge/references/*.md`): Templates and best practices used during artifact generation

## Key Constraints

- **Security is non-negotiable.** Forge must never delete user code, write outside `.claude/`/`CLAUDE.md`, or introduce vulnerabilities. All writes go through user approval. See `.claude/rules/security.md` for the full security policy.
- Python scripts use only the standard library (no pip dependencies). Must work on Python 3.8+.
- Subagents use `model: sonnet` and `effort: low` to minimize token cost. Every token Forge consumes comes from the user's quota.
- The plugin never interrupts mid-task. All analysis is retroactive.
- Generated skills and agents are drafts. CLAUDE.md entries, rules, and hooks are typically production-ready.
- Session transcript JSONL format is not a stable API — parser must handle format variations gracefully.
- **Analysis scope is per-project.** All pattern detection is scoped to the current project and its worktrees. Forge never reads transcripts from unrelated projects. Cross-project aggregation is a future opt-in feature only.
- **Artifacts default to project-level.** All generated artifacts go to `.claude/` (project-level), never `~/.claude/` (user-level). The user can override during review. Forge never suggests user-level on its own.

## Code Style

- Python: use type hints, `pathlib.Path` over `os.path`, `argparse` for CLI. Scripts output JSON to stdout, errors to stderr.
- Markdown: YAML frontmatter for skills and agents. Imperative voice for instructions.
- Hooks: valid JSON, case-sensitive matchers, no spaces around `|` in matcher patterns.

## Testing

Test the plugin by running `claude --plugin-dir ./forge` against real projects. Use `claude --debug` for plugin loading and hook execution logs.

Automated tests live in `tests/` and run with `pytest`. They cover security invariants, the transcript analyzer, cache manager, and proposal builder. Run with `python3 -m pytest tests/ -v`. Pytest is a dev-only dependency — runtime scripts use only the standard library.

## License

Proprietary. No license file — all rights reserved by default. The `plugin.json` `license` field is omitted intentionally.

## History

For the history of significant design and technical decisions, see `.claude/references/history.md`. **Proactively update this file** whenever you make a significant design decision, change an architectural approach, resolve a non-obvious tradeoff, or deviate from the spec. Each entry should capture what was decided, why, and what alternatives were considered.

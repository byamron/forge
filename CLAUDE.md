# Forge — Claude Code Infrastructure Plugin

## Project

Forge is a Claude Code plugin that analyzes sessions, configuration, and auto-memory to generate optimized rules, skills, hooks, agents, and reference docs. It manages context architecture as a living system.

The plugin lives in `forge/` and is tested with `claude --plugin-dir ./forge`. After changes to skills, agents, or hooks, run `/reload-plugins` to pick up updates.

## Spec and Roadmap

The product spec is at `.context/attachments/forge-spec.md`. The implementation roadmap is at `.context/attachments/forge-roadmap.md`. Read these before making architectural decisions or adding new features.

## Architecture

- **Skills** (`forge/skills/*/SKILL.md`): User-facing commands — `/forge:status`, `/forge:analyze`, `/forge:optimize`, `/forge:settings`
- **Agents** (`forge/agents/*.md`): Subagents — `session-analyzer` (LLM analysis pass, replaces Phase B confirmation), `artifact-generator` (creates artifacts)
- **Scripts** (`forge/scripts/*.py`): Zero-token Phase A analysis — `analyze-config.py`, `analyze-transcripts.py`, `analyze-memory.py`
- **Hooks** (`forge/hooks/hooks.json`): SessionEnd hook for session tracking
- **References** (`forge/references/*.md`): Templates and best practices used by the artifact-generator

## Key Constraints

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

Test the plugin by running `claude --plugin-dir ./forge` against real projects. Use `claude --debug` for plugin loading and hook execution logs. There is no automated test suite yet.

## History

For the history of significant design and technical decisions, see `.claude/references/history.md`. **Proactively update this file** whenever you make a significant design decision, change an architectural approach, resolve a non-obvious tradeoff, or deviate from the spec. Each entry should capture what was decided, why, and what alternatives were considered.

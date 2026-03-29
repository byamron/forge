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

## Core Documents

All project documentation lives in `core-docs/`. Review and update these as part of your workflow.

| Document | Path | Purpose |
|----------|------|---------|
| Plan | `core-docs/plan.md` | Living roadmap -- current focus, active work, completed features |
| History | `core-docs/history.md` | Decision log -- what was done, why, tradeoffs, branch+SHA |
| Feedback | `core-docs/feedback.md` | Synthesized user feedback distilled into rules |
| Workflow | `core-docs/workflow.md` | Agent workflow and session start checklist |

## Development Infrastructure

**Important:** The plugin ships from `forge/`. The dev infrastructure in `.claude/` is for *us* when working on Forge. These are completely separate.

| What | Plugin (ships to users) | Dev (our tools) |
|------|------------------------|-----------------|
| Skills | `forge/skills/` (`/forge`, `/forge:settings`, `/forge:version`) | `.claude/skills/` (`/ship`, `/audit`) |
| Agents | `forge/agents/` (`session-analyzer`) | `.claude/agents/` (`planner`, `domain`, `testing`, `docs`) |
| Rules | — | `.claude/rules/` (general, documentation, security, plugin-structure, python-scripts, skills-and-agents) |

Dev agents are invoked with `claude --agent <name>`. See `core-docs/workflow.md` for the standard workflow.

## PR Readiness

Before creating any PR, verify the following:

- **Version bump.** If any file under `forge/` changed, bump the version in all three locations: `forge/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` `metadata.version`, and `.claude-plugin/marketplace.json` `plugins[0].version`.
- **Tests pass.** Run `python3 -m pytest tests/ -v` and confirm all tests pass. Do not create a PR with failing tests.
- **CLAUDE.md is current.** If the change adds, removes, or renames skills, agents, scripts, hooks, or references, update the Architecture section of this file to match.
- **Rules are current.** If the change introduces a new convention or constraint (e.g., a new required manifest field, a new security boundary), add or update the relevant rule in `.claude/rules/`.
- **History is updated.** If the change involves a significant design decision, architectural change, or non-obvious tradeoff, add an entry to `core-docs/history.md`.

## History

For the history of significant design and technical decisions, see `core-docs/history.md`. **Proactively update this file** whenever you make a significant design decision, change an architectural approach, resolve a non-obvious tradeoff, or deviate from the spec. Each entry should capture what was decided, why, and what alternatives were considered.
